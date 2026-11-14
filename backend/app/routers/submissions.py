from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .. import db, pipeline, storage
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
    }


@router.get("/assignments/{assignment_id}")
async def get_assignment(assignment_id: str, user: dict = Depends(current_user)):
    assignment, course = await load_assignment(user, assignment_id)
    out = db.serialize(assignment)
    out["course"] = {"id": str(course["_id"]), "name": course["name"]}

    if user["role"] == "student":
        sub = await db.submissions.find_one({"assignment_id": assignment["_id"], "student_id": user["_id"]})
        out["my_submission"] = _sub_summary(sub) if sub else None
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
        out["student_count"] = len(course.get("student_ids", []))
    return out


@router.post("/assignments/{assignment_id}/submissions")
async def upload_submission(
    assignment_id: str,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    user: dict = Depends(student),
):
    assignment, _ = await load_assignment(user, assignment_id)

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
        "consent_at": None,
        "error": None,
        "created_at": db.now(),
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
    out["course"] = {"id": str(course["_id"]), "name": course["name"]}

    if user["role"] == "student":
        # Students see progress only; scores are for the instructor to review first.
        out.pop("overall", None)
        out.pop("needs_review", None)
        return out

    stu = await db.users.find_one({"_id": sub["student_id"]})
    turns = await db.viva_turns.find({"submission_id": sub["_id"]}).sort([("question_index", 1), ("kind", -1)]).to_list(None)
    score = await db.scores.find_one({"submission_id": sub["_id"]})
    out.update({
        "student": {"name": stu["name"], "email": stu["email"]} if stu else None,
        "analysis": sub.get("analysis"),
        "questions": sub.get("questions", []),
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
    })
    return out


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
    score = await db.scores.find_one({"submission_id": sub["_id"]})
    if not score or not (0 <= dim_index < len(score["dimensions"])):
        raise HTTPException(404, "Score not found")

    dims = score["dimensions"]
    dims[dim_index]["override_score"] = body.override_score
    dims[dim_index]["override_note"] = body.override_note.strip()
    dims[dim_index]["overridden_by"] = user["name"] if body.override_score is not None else None
    overall = pipeline.overall_score(dims)
    # A dimension the instructor has overridden no longer needs review.
    needs_review = any(d["needs_review"] and d.get("override_score") is None for d in dims)

    await db.scores.update_one(
        {"_id": score["_id"]}, {"$set": {"dimensions": dims, "overall": overall, "needs_review": needs_review}}
    )
    await db.submissions.update_one({"_id": sub["_id"]}, {"$set": {"overall": overall, "needs_review": needs_review}})
    return {"dimensions": dims, "overall": overall, "needs_review": needs_review}
