"""Background work: PDF analysis -> questions, and final scoring. Plus viva progress logic."""

import logging
import re
from pathlib import Path

from bson import ObjectId

from . import db, gemini
from .config import settings

log = logging.getLogger("viva.pipeline")

# Submission statuses
ANALYZING = "analyzing"
ANALYSIS_FAILED = "analysis_failed"
READY = "ready"  # questions generated, viva not started
IN_PROGRESS = "viva_in_progress"
SCORING = "scoring"
SCORING_FAILED = "scoring_failed"
COMPLETED = "completed"


async def run_analysis(submission_id: ObjectId) -> None:
    sub = await db.submissions.find_one({"_id": submission_id})
    assignment = await db.assignments.find_one({"_id": sub["assignment_id"]})
    try:
        pdf_bytes = Path(sub["pdf_path"]).read_bytes()
        analysis = await gemini.analyze_pdf(pdf_bytes, assignment)
        analysis_dict = analysis.model_dump()
        qs = await gemini.generate_questions(analysis_dict, assignment, settings.num_questions)
        questions = [q.model_dump() for q in qs.questions[: settings.num_questions]]
        if not questions:
            raise RuntimeError("No questions generated")
        await db.submissions.update_one(
            {"_id": submission_id},
            {"$set": {"analysis": analysis_dict, "questions": questions, "status": READY, "error": None}},
        )
    except Exception as e:  # noqa: BLE001 - surface any failure to the UI
        log.exception("Analysis failed for %s", submission_id)
        await db.submissions.update_one(
            {"_id": submission_id}, {"$set": {"status": ANALYSIS_FAILED, "error": str(e)[:500]}}
        )


def current_step(sub: dict, turns: list[dict]) -> dict | None:
    """Return the next question the student should answer, or None if the viva is finished."""
    by_key = {(t["question_index"], t["kind"]): t for t in turns}
    for i, q in enumerate(sub.get("questions", [])):
        main = by_key.get((i, "main"))
        if main is None:
            return {"question_index": i, "kind": "main", "question": q["question"]}
        if main.get("followup_question") and (i, "followup") not in by_key:
            return {"question_index": i, "kind": "followup", "question": main["followup_question"]}
    return None


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", s.lower())).strip()


def quote_found(quote: str, transcripts: str) -> bool:
    q = _normalize(quote)
    return bool(q) and q in _normalize(transcripts)


def overall_score(dimensions: list[dict]) -> float:
    vals = [d["override_score"] if d.get("override_score") is not None else d["score"] for d in dimensions]
    if not vals:
        return 0.0
    return round(sum(vals) / (5 * len(vals)) * 100, 1)


async def run_scoring(submission_id: ObjectId) -> None:
    sub = await db.submissions.find_one({"_id": submission_id})
    assignment = await db.assignments.find_one({"_id": sub["assignment_id"]})
    turns = await db.viva_turns.find({"submission_id": submission_id}).sort([("question_index", 1), ("kind", -1)]).to_list(None)
    rubric = assignment["rubric"]
    try:
        result = await gemini.score_viva(assignment, rubric, sub.get("analysis") or {}, turns)
        all_text = " ".join(t.get("transcript", "") for t in turns)
        by_name = {d.dimension.strip().lower(): d for d in result.dimensions}

        dims = []
        for r in rubric:
            d = by_name.get(r["name"].strip().lower())
            if d is None:
                dims.append({
                    "dimension": r["name"], "score": 1, "evidence_quote": "", "rationale": "Not scored by the model.",
                    "confidence": 0.0, "quote_verified": False, "needs_review": True,
                    "override_score": None, "override_note": "",
                })
                continue
            score = max(1, min(5, int(d.score)))
            conf = max(0.0, min(1.0, float(d.confidence)))
            verified = quote_found(d.evidence_quote, all_text)
            dims.append({
                "dimension": r["name"], "score": score, "evidence_quote": d.evidence_quote,
                "rationale": d.rationale, "confidence": conf, "quote_verified": verified,
                "needs_review": conf < settings.review_confidence_threshold or not verified,
                "override_score": None, "override_note": "",
            })

        needs_review = any(d["needs_review"] for d in dims)
        doc = {
            "submission_id": submission_id, "dimensions": dims, "summary": result.summary,
            "overall": overall_score(dims), "needs_review": needs_review, "created_at": db.now(),
        }
        await db.scores.replace_one({"submission_id": submission_id}, doc, upsert=True)
        await db.submissions.update_one(
            {"_id": submission_id},
            {"$set": {"status": COMPLETED, "overall": doc["overall"], "needs_review": needs_review, "error": None}},
        )
    except Exception as e:  # noqa: BLE001
        log.exception("Scoring failed for %s", submission_id)
        await db.submissions.update_one(
            {"_id": submission_id}, {"$set": {"status": SCORING_FAILED, "error": str(e)[:500]}}
        )
