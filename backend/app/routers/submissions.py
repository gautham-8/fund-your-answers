from collections import Counter
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .. import db, pipeline, schedule, storage
from ..access import load_assignment, load_submission
from ..auth import current_user, instructor, student
from ..config import settings

router = APIRouter(prefix="/api", tags=["submissions"])


def _sub_summary(sub: dict) -> dict:
    return {
        "id": str(sub["_id"]),
        "status": sub["status"],
        "error": sub.get("error"),
        "filename": sub.get("filename"),
        "created_at": sub.get("created_at"),
        "overall": sub.get("overall"),
        "needs_review": sub.get("needs_review"),
        "late": bool(sub.get("late")),
    }


def _regrade_out(r: dict) -> dict:
    return {
        "id": str(r["_id"]),
        "submission_id": str(r["submission_id"]),
        "dimension_index": r["dimension_index"],
        "dimension": r["dimension"],
        "message": r["message"],
        "status": r["status"],
        "response": r.get("response", ""),
        "score_before": r.get("score_before"),
        "score_after": r.get("score_after"),
        "created_at": r["created_at"],
        "resolved_at": r.get("resolved_at"),
        "resolved_by": r.get("resolved_by"),
    }


async def student_results(sub: dict, assignment: dict) -> dict | None:
    """What a student sees once grades are published: final scores and feedback, no AI confidence."""
    if not assignment.get("grades_published") or sub["status"] != pipeline.COMPLETED:
        return None
    score = await db.scores.find_one({"submission_id": sub["_id"]})
    if not score:
        return None
    regrades = await db.regrade_requests.find({"submission_id": sub["_id"]}).sort("created_at", -1).to_list(None)
    return {
        "overall": score["overall"],
        "summary": score.get("summary", ""),
        "dimensions": [
            {
                "dimension": d["dimension"],
                "score": d["override_score"] if d.get("override_score") is not None else d["score"],
                "max": 5,
                "evidence_quote": d.get("evidence_quote", ""),
                "rationale": d.get("rationale", ""),
                "instructor_note": d.get("override_note", "") if d.get("override_score") is not None else "",
                "adjusted": d.get("override_score") is not None,
            }
            for d in score["dimensions"]
        ],
        "regrade_requests": [_regrade_out(r) for r in regrades],
    }


async def apply_override(sub: dict, dim_index: int, override_score: int | None, note: str, user: dict) -> dict:
    score = await db.scores.find_one({"submission_id": sub["_id"]})
    if not score or not (0 <= dim_index < len(score["dimensions"])):
        raise HTTPException(404, "Score not found")

    dims = score["dimensions"]
    dims[dim_index]["override_score"] = override_score
    dims[dim_index]["override_note"] = note.strip()
    dims[dim_index]["overridden_by"] = user["name"] if override_score is not None else None
    overall = pipeline.overall_score(dims)
    # A dimension the instructor has overridden no longer needs review.
    needs_review = any(d["needs_review"] and d.get("override_score") is None for d in dims)

    await db.scores.update_one(
        {"_id": score["_id"]}, {"$set": {"dimensions": dims, "overall": overall, "needs_review": needs_review}}
    )
    await db.submissions.update_one({"_id": sub["_id"]}, {"$set": {"overall": overall, "needs_review": needs_review}})
    return {"dimensions": dims, "overall": overall, "needs_review": needs_review}


@router.get("/assignments/{assignment_id}")
async def get_assignment(assignment_id: str, user: dict = Depends(current_user)):
    assignment, course = await load_assignment(user, assignment_id)
    out = db.serialize(assignment)
    out["course"] = {"id": str(course["_id"]), "name": course["name"], "code": course.get("code", "")}
    out["grades_published"] = bool(assignment.get("grades_published"))
    now = db.now()
    out["released"] = schedule.is_released(assignment, now)
    deadline = schedule.deadline(assignment)
    out["accepting_submissions"] = out["released"] and (deadline is None or now <= deadline)

    if user["role"] == "student":
        sub = await db.submissions.find_one({"assignment_id": assignment["_id"], "student_id": user["_id"]})
        out["my_submission"] = {
            **_sub_summary(sub),
            "page_map": sub.get("page_map"),
            "page_count": sub.get("page_count"),
            "page_order": sub.get("page_order"),
            "page_rotation": sub.get("page_rotation"),
            "pages_pending": pipeline.pages_pending(sub),
        } if sub else None
        if sub:
            results = await student_results(sub, assignment)
            if results:
                out["my_submission"]["overall"] = results["overall"]
            out["my_results"] = results
    else:
        subs = await db.submissions.find({"assignment_id": assignment["_id"]}).sort("created_at", -1).to_list(None)
        students = await db.users.find({"_id": {"$in": [s["student_id"] for s in subs]}}).to_list(None)
        names = {u["_id"]: u for u in students}
        out["submissions"] = [
            {
                **_sub_summary(s),
                "student": {"name": names[s["student_id"]]["name"], "email": names[s["student_id"]]["email"]}
                if s["student_id"] in names else None,
            }
            for s in subs
        ]
        submitted = {s["student_id"] for s in subs}
        missing = await db.users.find(
            {"_id": {"$in": [i for i in course.get("student_ids", []) if i not in submitted]}}, {"name": 1, "email": 1}
        ).sort("name", 1).to_list(None)
        out["missing"] = [{"id": str(u["_id"]), "name": u["name"], "email": u["email"]} for u in missing]
        out["student_count"] = len(course.get("student_ids", []))
        regrades = Counter()
        async for r in db.regrade_requests.find({"assignment_id": assignment["_id"], "status": "open"}, {"submission_id": 1}):
            regrades[str(r["submission_id"])] += 1
        for s in out["submissions"]:
            s["open_regrades"] = regrades[s["id"]]
    return out


@router.post("/assignments/{assignment_id}/submissions")
async def upload_submission(
    assignment_id: str,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    user: dict = Depends(student),
):
    assignment, _ = await load_assignment(user, assignment_id)
    now = db.now()
    deadline = schedule.deadline(assignment)
    if deadline and now > deadline:
        what = "late due date" if assignment.get("late_due_date") else "due date"
        raise HTTPException(400, f"The {what} has passed, so new submissions are closed")

    data = await file.read()
    if len(data) > settings.max_pdf_mb * 1024 * 1024:
        raise HTTPException(413, f"PDF must be under {settings.max_pdf_mb} MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "Please upload a PDF file")

    existing = await db.submissions.find_one({"assignment_id": assignment["_id"], "student_id": user["_id"]})
    if existing and existing["status"] not in (pipeline.ANALYZING, pipeline.ANALYSIS_FAILED, pipeline.READY):
        raise HTTPException(409, "You've already started the viva for this assignment, so the PDF can't be replaced")

    doc = {
        "assignment_id": assignment["_id"],
        "student_id": user["_id"],
        "filename": file.filename or "submission.pdf",
        "status": pipeline.ANALYZING,
        "analysis": None,
        "questions": [],
        "page_map": None,
        "page_order": None,
        "page_rotation": None,
        "pages_confirmed_at": None,
        "consent_at": None,
        "error": None,
        "late": schedule.is_late(assignment, now),
        "created_at": now,
    }
    if existing:
        sub_id = existing["_id"]
        await storage.delete(existing.get("pdf_file_id"))  # replacing the PDF
        await db.submissions.update_one({"_id": sub_id}, {"$set": doc})
    else:
        sub_id = (await db.submissions.insert_one(doc)).inserted_id

    pdf_file_id = await storage.save(
        data, doc["filename"], "application/pdf", kind="submission_pdf", submission_id=sub_id
    )
    await db.submissions.update_one({"_id": sub_id}, {"$set": {"pdf_file_id": pdf_file_id}})

    background.add_task(pipeline.run_analysis, sub_id)
    return {"id": str(sub_id), "status": pipeline.ANALYZING}


@router.get("/submissions/{submission_id}")
async def get_submission(submission_id: str, user: dict = Depends(current_user)):
    sub, assignment, course = await load_submission(user, submission_id)
    out = _sub_summary(sub)
    out["assignment"] = {"id": str(assignment["_id"]), "title": assignment["title"]}
    out["course"] = {"id": str(course["_id"]), "name": course["name"], "code": course.get("code", "")}

    if user["role"] == "student":
        # Students see progress only until the instructor publishes grades.
        out.pop("overall", None)
        out.pop("needs_review", None)
        results = await student_results(sub, assignment)
        if results:
            out["results"] = results
        out.update({
            "parts": assignment.get("parts") or [],
            "page_map": sub.get("page_map"),
            "page_count": sub.get("page_count"),
            "page_order": sub.get("page_order"),
            "page_rotation": sub.get("page_rotation"),
            "pages_pending": pipeline.pages_pending(sub),
        })
        return out

    stu = await db.users.find_one({"_id": sub["student_id"]})
    turns = await db.viva_turns.find({"submission_id": sub["_id"]}).sort([("question_index", 1), ("kind", -1)]).to_list(None)
    score = await db.scores.find_one({"submission_id": sub["_id"]})
    out.update({
        "student": {"name": stu["name"], "email": stu["email"]} if stu else None,
        "analysis": sub.get("analysis"),
        "questions": sub.get("questions", []),
        "parts": assignment.get("parts") or [],
        "page_map": sub.get("page_map"),
        "pages_confirmed_at": sub.get("pages_confirmed_at"),
        "consent_at": sub.get("consent_at"),
        "rubric": assignment["rubric"],
        "turns": [
            {
                "id": str(t["_id"]),
                "question_index": t["question_index"],
                "kind": t["kind"],
                "question": t["question"],
                "transcript": t.get("transcript", ""),
                "answer_mode": t.get("answer_mode"),
                "has_audio": bool(t.get("audio_file_id")),
                "quality": t.get("quality"),
                "notes": t.get("notes"),
            }
            for t in turns
        ],
        "score": db.serialize(score),
        "grades_published": bool(assignment.get("grades_published")),
        "regrade_requests": [
            _regrade_out(r)
            for r in await db.regrade_requests.find({"submission_id": sub["_id"]}).sort("created_at", -1).to_list(None)
        ],
    })
    return out


class PagesIn(BaseModel):
    pages: list[list[int]] = Field(description="Pages for each assignment question, in order")
    order: list[int] | None = Field(None, description="Every PDF page once, in the order the student arranged them")
    rotation: list[Literal[0, 90, 180, 270]] | None = Field(None, description="Clockwise degrees per PDF page")


@router.put("/submissions/{submission_id}/pages")
async def confirm_pages(submission_id: str, body: PagesIn, user: dict = Depends(student)):
    """The student checks (and fixes) the AI's page matches, which submits them and opens the viva."""
    sub, _, _ = await load_submission(user, submission_id)
    if sub["status"] != pipeline.READY or sub.get("page_map") is None:
        raise HTTPException(400, "Pages can only be set after analysis and before the viva starts")
    if len(body.pages) != len(sub["page_map"]):
        raise HTTPException(400, "Give pages for every question")
    page_count = sub.get("page_count") or 0
    if any(not 1 <= p <= page_count for pages in body.pages for p in pages):
        raise HTTPException(400, f"Pages must be between 1 and {page_count}")
    if body.order is not None and sorted(body.order) != list(range(1, page_count + 1)):
        raise HTTPException(400, "Page order must list every page exactly once")
    if body.rotation is not None and len(body.rotation) != page_count:
        raise HTTPException(400, "Give a rotation for every page")
    page_map = [pipeline.clean_pages(pages, page_count) for pages in body.pages]
    await db.submissions.update_one(
        {"_id": sub["_id"]},
        {"$set": {
            "page_map": page_map, "page_order": body.order, "page_rotation": body.rotation,
            "pages_confirmed_at": db.now(),
        }},
    )
    return {"page_map": page_map, "pages_pending": False}


@router.get("/submissions/{submission_id}/pdf")
async def get_pdf(submission_id: str, user: dict = Depends(current_user)):
    sub, _, _ = await load_submission(user, submission_id)
    return await storage.file_response(sub.get("pdf_file_id"))


@router.post("/submissions/{submission_id}/retry")
async def retry(submission_id: str, background: BackgroundTasks, user: dict = Depends(current_user)):
    """Re-run a failed step (analysis or scoring)."""
    sub, _, _ = await load_submission(user, submission_id)
    if sub["status"] == pipeline.ANALYSIS_FAILED:
        await db.submissions.update_one({"_id": sub["_id"]}, {"$set": {"status": pipeline.ANALYZING, "error": None}})
        background.add_task(pipeline.run_analysis, sub["_id"])
        return {"status": pipeline.ANALYZING}
    # Anyone can retry failed scoring; instructors can also re-score a completed viva.
    if sub["status"] == pipeline.SCORING_FAILED or (
        sub["status"] == pipeline.COMPLETED and user["role"] == "instructor"
    ):
        await db.submissions.update_one({"_id": sub["_id"]}, {"$set": {"status": pipeline.SCORING, "error": None}})
        background.add_task(pipeline.run_scoring, sub["_id"])
        return {"status": pipeline.SCORING}
    raise HTTPException(400, "Nothing to retry")


class OverrideIn(BaseModel):
    override_score: int | None = Field(default=None, ge=1, le=5)
    override_note: str = ""


@router.patch("/submissions/{submission_id}/scores/{dim_index}")
async def override_score(submission_id: str, dim_index: int, body: OverrideIn, user: dict = Depends(instructor)):
    sub, _, _ = await load_submission(user, submission_id)
    return await apply_override(sub, dim_index, body.override_score, body.override_note, user)
