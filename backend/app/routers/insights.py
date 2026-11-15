"""Class-level views for instructors: rubric averages, AI-vs-instructor agreement, concept gaps."""

import string

from fastapi import APIRouter, Depends, HTTPException

from .. import db, gemini, pipeline
from ..access import load_assignment, load_course
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
        "graded": sum(1 for s in subs if s.get("grader_points") is not None),
        "avg_final": avg([f for s in subs if (f := pipeline.final_grade(assignment, s)) is not None]),
        "rubric": rubric,
        "agreement": agreement,
        "concept_gaps": assignment.get("concept_gaps"),
    }


MIN_VIVAS = 2


@router.post("/assignments/{assignment_id}/insights/concept-gaps")
async def generate_concept_gaps(assignment_id: str, user: dict = Depends(instructor)):
    assignment, _ = await load_assignment(user, assignment_id)
    return await _analyse(assignment)


async def _analyse(assignment: dict) -> dict:
    subs = await _completed(assignment["_id"])
    if len(subs) < MIN_VIVAS:
        raise HTTPException(400, f"Need at least {MIN_VIVAS} completed vivas to look for class-wide gaps")

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
        if affected:
            gaps.append({**g.model_dump(), "students": affected, "student_count": len(affected)})
    gaps.sort(key=lambda g: -g["student_count"])

    doc = {"overview": result.overview, "gaps": gaps, "based_on": len(subs), "generated_at": db.now()}
    await db.assignments.update_one({"_id": assignment["_id"]}, {"$set": {"concept_gaps": doc}})
    return doc


# ---------- Course-wide: what to revisit ----------

async def _course_assignments(course: dict) -> list[tuple[dict, int]]:
    """Every assignment in the course with its number of completed vivas, oldest first."""
    asgs = await db.assignments.find({"course_id": course["_id"]}).sort("created_at", 1).to_list(None)
    counts: dict = {}
    async for row in await db.submissions.aggregate([
        {"$match": {"assignment_id": {"$in": [a["_id"] for a in asgs]}, "status": pipeline.COMPLETED}},
        {"$group": {"_id": "$assignment_id", "n": {"$sum": 1}}},
    ]):
        counts[row["_id"]] = row["n"]
    return [(a, counts.get(a["_id"], 0)) for a in asgs]


async def _course_report(course: dict) -> dict:
    assignments, gaps = [], []
    for a, completed in await _course_assignments(course):
        cg = a.get("concept_gaps")
        assignments.append({
            "id": str(a["_id"]),
            "title": a["title"],
            "completed": completed,
            "analysed_on": cg["based_on"] if cg else None,
            "generated_at": cg["generated_at"] if cg else None,
            "overview": cg["overview"] if cg else None,
            # New vivas finished since the last analysis (or never analysed but now possible)
            "stale": completed >= MIN_VIVAS and (not cg or cg["based_on"] != completed),
        })
        if not cg or not cg["based_on"]:
            continue
        for g in cg["gaps"]:
            gaps.append({
                "concept": g["concept"],
                "explanation": g["explanation"],
                "example_quote": g.get("example_quote", ""),
                "teaching_suggestion": g["teaching_suggestion"],
                "student_count": g["student_count"],
                "based_on": cg["based_on"],
                "share": round(g["student_count"] / cg["based_on"], 2),
                "assignment": {"id": str(a["_id"]), "title": a["title"]},
            })
    gaps.sort(key=lambda g: (-g["share"], -g["student_count"]))
    return {"assignments": assignments, "gaps": gaps, "min_vivas": MIN_VIVAS}


@router.get("/courses/{course_id}/concept-gaps")
async def course_concept_gaps(course_id: str, user: dict = Depends(instructor)):
    """Concept gaps from every assignment, ranked by the share of the class affected."""
    course = await load_course(user, course_id)
    return await _course_report(course)


@router.post("/courses/{course_id}/concept-gaps")
async def refresh_course_concept_gaps(course_id: str, user: dict = Depends(instructor)):
    """Re-analyse every assignment with new completed vivas since its last analysis."""
    course = await load_course(user, course_id)
    failed = []
    for a, completed in await _course_assignments(course):
        cg = a.get("concept_gaps")
        if completed < MIN_VIVAS or (cg and cg["based_on"] == completed):
            continue
        try:
            await _analyse(a)  # one at a time: kinder to Gemini rate limits
        except HTTPException as e:
            failed.append({"id": str(a["_id"]), "title": a["title"], "error": e.detail})
    report = await _course_report(course)
    report["failed"] = failed
    return report
