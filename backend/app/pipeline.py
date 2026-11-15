"""Background work: PDF analysis -> relevance check -> questions, and viva scoring. Plus viva progress and grade logic."""

import io
import logging
import re

from bson import ObjectId
from pypdf import PdfReader

from . import db, gemini, storage
from .config import settings

log = logging.getLogger("viva.pipeline")

# Submission statuses
ANALYZING = "analyzing"
ANALYSIS_FAILED = "analysis_failed"
OFF_TOPIC = "off_topic"  # PDF doesn't answer the assignment; no viva until re-upload or instructor override
READY = "ready"  # questions generated, viva not started
IN_PROGRESS = "viva_in_progress"
SCORING = "scoring"
SCORING_FAILED = "scoring_failed"
COMPLETED = "completed"


async def run_analysis(submission_id: ObjectId) -> None:
    """Analyse the PDF, check it actually answers the assignment, and only then write viva questions."""
    sub = await db.submissions.find_one({"_id": submission_id})
    assignment = await db.assignments.find_one({"_id": sub["assignment_id"]})
    try:
        pdf_bytes, _, _ = await storage.read(sub["pdf_file_id"])
        brief_bytes = None
        if assignment.get("brief_file_id"):
            brief_bytes, _, _ = await storage.read(assignment["brief_file_id"])
        analysis = await gemini.analyze_pdf(pdf_bytes, assignment, brief_bytes)
        analysis_dict = analysis.model_dump(exclude={"page_map"})
        parts = assignment.get("parts") or []
        page_count = count_pages(pdf_bytes) or analysis.page_count
        page_map = match_pages(analysis, len(parts), page_count) if parts else None
        update = {
            "analysis": analysis_dict, "page_map": page_map, "page_count": page_count,
            "page_order": None, "page_rotation": None, "pages_confirmed_at": None,
            "relevance_override_by": None, "error": None,
        }
        # No questions for a PDF that doesn't answer the assignment: the student re-uploads, or the instructor lets it through.
        off_topic = not analysis.on_topic or (page_map is not None and not any(page_map))
        if off_topic:
            await db.submissions.update_one(
                {"_id": submission_id}, {"$set": {**update, "questions": [], "status": OFF_TOPIC}}
            )
            return
        await db.submissions.update_one({"_id": submission_id}, {"$set": update})
        await run_questions(submission_id)
    except Exception as e:  # noqa: BLE001 - surface any failure to the UI
        log.exception("Analysis failed for %s", submission_id)
        await db.submissions.update_one(
            {"_id": submission_id}, {"$set": {"status": ANALYSIS_FAILED, "error": str(e)[:500]}}
        )


async def run_questions(submission_id: ObjectId) -> None:
    """Write the viva questions from a stored analysis and open the viva."""
    sub = await db.submissions.find_one({"_id": submission_id})
    assignment = await db.assignments.find_one({"_id": sub["assignment_id"]})
    try:
        qs = await gemini.generate_questions(sub.get("analysis") or {}, assignment, settings.num_questions)
        questions = [q.model_dump() for q in qs.questions[: settings.num_questions]]
        if not questions:
            raise RuntimeError("No questions generated")
        await db.submissions.update_one(
            {"_id": submission_id}, {"$set": {"questions": questions, "status": READY, "error": None}}
        )
    except Exception as e:  # noqa: BLE001
        log.exception("Question generation failed for %s", submission_id)
        await db.submissions.update_one(
            {"_id": submission_id}, {"$set": {"status": ANALYSIS_FAILED, "error": str(e)[:500]}}
        )


def count_pages(pdf_bytes: bytes) -> int | None:
    """Real page count, or None when pypdf can't parse the file (Gemini's count is the fallback)."""
    try:
        return len(PdfReader(io.BytesIO(pdf_bytes)).pages)
    except Exception:  # noqa: BLE001 - any parse failure means "unknown"
        return None


def clean_pages(pages: list[int], page_count: int) -> list[int]:
    return sorted({p for p in pages if 1 <= p <= page_count})


def match_pages(analysis: gemini.PdfAnalysis, n_parts: int, page_count: int) -> list[list[int]]:
    """AI page guesses as one sorted page list per assignment question, dropping pages outside the PDF."""
    out: list[list[int]] = [[] for _ in range(n_parts)]
    for m in analysis.page_map:
        if 1 <= m.part <= n_parts:
            out[m.part - 1] = clean_pages(out[m.part - 1] + m.pages, page_count)
    return out


def pages_pending(sub: dict) -> bool:
    """True while the student still has to confirm which pages answer each assignment question."""
    return sub.get("page_map") is not None and sub.get("pages_confirmed_at") is None


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


SCORE_MAX = 5  # rubric dimensions are scored 0-5; 0 = no understanding shown


def overall_score(dimensions: list[dict]) -> float:
    """Viva score as a percentage."""
    vals = [d["override_score"] if d.get("override_score") is not None else d["score"] for d in dimensions]
    if not vals:
        return 0.0
    return round(sum(vals) / (SCORE_MAX * len(vals)) * 100, 1)


def viva_weight(assignment: dict) -> float:
    w = assignment.get("viva_weight")
    return settings.default_viva_weight if w is None else w


def part_points(assignment: dict) -> list[float]:
    """Points per assignment question. Older assignments without them split max_points evenly."""
    parts = assignment.get("parts") or []
    pts = assignment.get("part_points") or []
    if len(pts) == len(parts):
        return list(pts)
    return [(assignment.get("max_points") or 100) / len(parts)] * len(parts) if parts else []


def max_points(assignment: dict) -> float:
    """What the written solution is marked out of: the sum of the question points when there are questions."""
    pts = part_points(assignment)
    return sum(pts) if pts else (assignment.get("max_points") or 100)


def question_grades(assignment: dict, sub: dict) -> list[dict]:
    """The grader's mark and comment per assignment question (points None = not graded yet)."""
    saved = sub.get("question_grades") or []
    return [
        {"points": saved[i].get("points"), "comment": saved[i].get("comment", "")} if i < len(saved) else {"points": None, "comment": ""}
        for i in range(len(assignment.get("parts") or []))
    ]


def grader_percent(assignment: dict, sub: dict) -> float | None:
    pts = sub.get("grader_points")
    if pts is None:
        return None
    return round(min(1.0, pts / max_points(assignment)) * 100, 1)


def final_grade(assignment: dict, sub: dict) -> float | None:
    """Final % = (1 - w) x grader's % + w x viva %. None until both the viva is scored and a grader has marked it."""
    g, v = grader_percent(assignment, sub), sub.get("overall")
    if g is None or v is None or sub.get("status") != COMPLETED:
        return None
    w = viva_weight(assignment)
    return round((1 - w) * g + w * v, 1)


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
                    "dimension": r["name"], "score": 0, "evidence_quote": "", "rationale": "Not scored by the model.",
                    "confidence": 0.0, "quote_verified": False, "needs_review": True,
                    "override_score": None, "override_note": "",
                })
                continue
            score = max(0, min(SCORE_MAX, int(d.score)))
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
