"""Class-level views for instructors: rubric averages, AI-vs-instructor agreement, concept gaps."""

import string

from fastapi import APIRouter, Depends, HTTPException

from .. import db, gemini, pipeline
from ..access import load_assignment
from ..auth import instructor

router = APIRouter(prefix="/api", tags=["insights"])


def _labels():
    for c in string.ascii_uppercase:
        yield f"Student {c}"
    n = 27
    while True:
        yield f"Student {n}"
        n += 1


async def _completed(assignment_id) -> list[dict]:
    return await db.submissions.find({"assignment_id": assignment_id, "status": pipeline.COMPLETED}).to_list(None)


@router.get("/assignments/{assignment_id}/insights")
async def insights(assignment_id: str, user: dict = Depends(instructor)):
    assignment, _ = await load_assignment(user, assignment_id)
    subs = await _completed(assignment["_id"])
    scores = await db.scores.find({"submission_id": {"$in": [s["_id"] for s in subs]}}).to_list(None)

    # Rubric averages (AI score vs final score after instructor overrides)
    per_dim: dict[str, dict] = {r["name"]: {"ai": [], "final": [], "pairs": []} for r in assignment["rubric"]}
    for sc in scores:
        for d in sc["dimensions"]:
            bucket = per_dim.setdefault(d["dimension"], {"ai": [], "final": [], "pairs": []})
            bucket["ai"].append(d["score"])
            final = d["override_score"] if d.get("override_score") is not None else d["score"]
            bucket["final"].append(final)
            if d.get("override_score") is not None:
                bucket["pairs"].append((d["score"], d["override_score"]))

    avg = lambda xs: round(sum(xs) / len(xs), 2) if xs else None  # noqa: E731
    rubric = []
    all_pairs = []
    for name, b in per_dim.items():
        all_pairs += b["pairs"]
        rubric.append({
            "dimension": name,
            "avg_ai": avg(b["ai"]),
            "avg_final": avg(b["final"]),
            "overrides": len(b["pairs"]),
            # positive = instructors score higher than the AI on this dimension
            "avg_adjustment": avg([h - a for a, h in b["pairs"]]),
        })

    total_dims = sum(len(sc["dimensions"]) for sc in scores)
    agreement = {
        "scored_dimensions": total_dims,
        "overridden": len(all_pairs),
        # Of the scores an instructor reviewed and changed, how far off was the AI?
        "within_one": avg([1.0 if abs(a - h) <= 1 else 0.0 for a, h in all_pairs]),
        "mean_abs_difference": avg([abs(a - h) for a, h in all_pairs]),
        "untouched_rate": round(1 - len(all_pairs) / total_dims, 2) if total_dims else None,
    }

    return {
        "completed": len(subs),
        "needs_review": sum(1 for s in subs if s.get("needs_review")),
        "avg_overall": avg([s["overall"] for s in subs if s.get("overall") is not None]),
        "rubric": rubric,
        "agreement": agreement,
        "concept_gaps": assignment.get("concept_gaps"),
    }


@router.post("/assignments/{assignment_id}/insights/concept-gaps")
async def generate_concept_gaps(assignment_id: str, user: dict = Depends(instructor)):
    assignment, _ = await load_assignment(user, assignment_id)
    subs = await _completed(assignment["_id"])
    if len(subs) < 2:
        raise HTTPException(400, "Need at least 2 completed vivas to look for class-wide gaps")

    turns = await db.viva_turns.find({"submission_id": {"$in": [s["_id"] for s in subs]}}).sort(
        [("question_index", 1), ("kind", -1)]
    ).to_list(None)
    by_sub: dict = {}
    for t in turns:
        by_sub.setdefault(t["submission_id"], []).append(t)

    # Anonymise: Gemini only ever sees "Student A", never names or emails.
    labels = _labels()
    students = {}
    for s in subs:
        qs = s.get("questions", [])
        enriched = [
            {**t, "target": qs[t["question_index"]].get("target") if t["question_index"] < len(qs) else None}
            for t in by_sub.get(s["_id"], [])
        ]
        students[next(labels)] = enriched

    try:
        result = await gemini.class_concept_gaps(assignment, students)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Could not analyse the class right now ({str(e)[:200]})")

    valid = set(students)
    gaps = []
    for g in result.gaps:
        affected = sorted({s for s in g.students if s in valid})
        gaps.append({**g.model_dump(), "students": affected, "student_count": len(affected)})
    gaps.sort(key=lambda g: -g["student_count"])

    doc = {"overview": result.overview, "gaps": gaps, "based_on": len(subs), "generated_at": db.now()}
    await db.assignments.update_one({"_id": assignment["_id"]}, {"$set": {"concept_gaps": doc}})
    return doc
