from collections import Counter
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .. import db, pipeline, schedule, storage
from ..access import load_assignment, load_submission
from ..auth import current_user, instructor, student

router = APIRouter(prefix="/api", tags=["submissions"])


def _sub_summary(sub: dict, assignment: dict) -> dict:
    """`overall` is the viva score (%); `final` blends it with the grader's mark once both exist."""
    return {
        "id": str(sub["_id"]),
        "status": sub["status"],
        "error": sub.get("error"),
        "relevance_note": (sub.get("analysis") or {}).get("relevance_note") if sub["status"] == pipeline.OFF_TOPIC else None,
        "filename": sub.get("filename"),
        "created_at": sub.get("created_at"),
        "overall": sub.get("overall"),
        "grader_points": sub.get("grader_points"),
        "questions_graded": sum(g["points"] is not None for g in pipeline.question_grades(assignment, sub)),
        "final": pipeline.final_grade(assignment, sub),
        "needs_review": sub.get("needs_review"),
        "late": bool(sub.get("late")),
    }


def _grading(assignment: dict) -> dict:
    return {
        "max_points": pipeline.max_points(assignment),
        "part_points": pipeline.part_points(assignment),
        "viva_weight": pipeline.viva_weight(assignment),
    }


def _pages(sub: dict) -> dict:
    """What the page viewer needs: which pages answer each question, and the student's page order/rotation."""
    return {
        "page_map": sub.get("page_map"),
        "page_count": sub.get("page_count"),
        "page_order": sub.get("page_order"),
        "page_rotation": sub.get("page_rotation"),
        "pages_pending": pipeline.pages_pending(sub),
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
        "overall": pipeline.final_grade(assignment, sub),  # None until a grader has marked the solution
        "viva": score["overall"],
        "grader_points": sub.get("grader_points"),
        "grader_note": sub.get("grader_note", "") if sub.get("grader_points") is not None else "",
        # Per-question marks, shown only once the whole solution is graded
        "question_grades": pipeline.question_grades(assignment, sub) if sub.get("grader_points") is not None else None,
        **_grading(assignment),
        "summary": score.get("summary", ""),
        "dimensions": [
            {
                "dimension": d["dimension"],
                "score": d["override_score"] if d.get("override_score") is not None else d["score"],
                "max": pipeline.SCORE_MAX,
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
    out.update(_grading(assignment))
    out.pop("brief_file_id", None)
    out["has_brief"] = bool(assignment.get("brief_file_id"))
    now = db.now()
    out["released"] = schedule.is_released(assignment, now)
    deadline = schedule.deadline(assignment)
    out["accepting_submissions"] = out["released"] and (deadline is None or now <= deadline)

    if user["role"] == "student":
        sub = await db.submissions.find_one({"assignment_id": assignment["_id"], "student_id": user["_id"]})
        out["my_submission"] = {
            **_sub_summary(sub, assignment),
            "page_map": sub.get("page_map"),
            "page_count": sub.get("page_count"),
            "page_order": sub.get("page_order"),
            "page_rotation": sub.get("page_rotation"),
            "pages_pending": pipeline.pages_pending(sub),
        } if sub else None
        if sub:
            # Students only see scores through published results.
            for k in ("overall", "grader_points", "final", "needs_review"):
                out["my_submission"].pop(k, None)
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
                **_sub_summary(s, assignment),
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

    data = await storage.read_pdf_upload(file)

    existing = await db.submissions.find_one({"assignment_id": assignment["_id"], "student_id": user["_id"]})
    if existing and existing["status"] not in (pipeline.ANALYZING, pipeline.ANALYSIS_FAILED, pipeline.OFF_TOPIC, pipeline.READY):
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
        "relevance_override_by": None,
        "grader_points": None,  # a mark for the old PDF doesn't carry over
        "question_grades": [],
        "grader_note": "",
        "graded_by": None,
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
    out = _sub_summary(sub, assignment)
    out["assignment"] = {"id": str(assignment["_id"]), "title": assignment["title"], **_grading(assignment)}
    out["course"] = {"id": str(course["_id"]), "name": course["name"], "code": course.get("code", "")}

    if user["role"] == "student":
        # Students see progress only until the instructor publishes grades.
        for k in ("overall", "grader_points", "questions_graded", "final", "needs_review"):
            out.pop(k, None)
        results = await student_results(sub, assignment)
        if results:
            out["results"] = results
        out.update({"parts": assignment.get("parts") or [], **_pages(sub)})
        return out

    stu = await db.users.find_one({"_id": sub["student_id"]})
    turns = await db.viva_turns.find({"submission_id": sub["_id"]}).sort([("question_index", 1), ("kind", -1)]).to_list(None)
    score = await db.scores.find_one({"submission_id": sub["_id"]})
    out.update({
        "student": {"name": stu["name"], "email": stu["email"]} if stu else None,
        "analysis": sub.get("analysis"),
        "questions": sub.get("questions", []),
        "parts": assignment.get("parts") or [],
        "grader_note": sub.get("grader_note", ""),
        "graded_by": sub.get("graded_by"),
        "question_grades": pipeline.question_grades(assignment, sub),
        "relevance_override_by": sub.get("relevance_override_by"),
        **_pages(sub),
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
        # If the instructor already let an off-topic PDF through, only the questions need redoing.
        task = pipeline.run_questions if sub.get("relevance_override_by") else pipeline.run_analysis
        background.add_task(task, sub["_id"])
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
    override_score: int | None = Field(default=None, ge=0, le=pipeline.SCORE_MAX)
    override_note: str = ""


@router.patch("/submissions/{submission_id}/scores/{dim_index}")
async def override_score(submission_id: str, dim_index: int, body: OverrideIn, user: dict = Depends(instructor)):
    sub, _, _ = await load_submission(user, submission_id)
    return await apply_override(sub, dim_index, body.override_score, body.override_note, user)


@router.post("/submissions/{submission_id}/allow")
async def allow_off_topic(submission_id: str, background: BackgroundTasks, user: dict = Depends(instructor)):
    """The instructor overrules the relevance check: write the viva questions anyway."""
    sub, _, _ = await load_submission(user, submission_id)
    if sub["status"] != pipeline.OFF_TOPIC:
        raise HTTPException(400, "Only submissions flagged as not answering the assignment can be let through")
    await db.submissions.update_one(
        {"_id": sub["_id"]}, {"$set": {"status": pipeline.ANALYZING, "relevance_override_by": user["name"], "error": None}}
    )
    background.add_task(pipeline.run_questions, sub["_id"])
    return {"status": pipeline.ANALYZING}


class GradeIn(BaseModel):
    points: float | None = Field(default=None, ge=0, description="The grader's mark for the written solution; null clears it")
    note: str = Field(default="", max_length=4000)


@router.put("/submissions/{submission_id}/grade")
async def set_grade(submission_id: str, body: GradeIn, user: dict = Depends(instructor)):
    """A human grader's mark for the solution itself. The final grade blends it with the viva score."""
    sub, assignment, _ = await load_submission(user, submission_id)
    if assignment.get("parts"):
        raise HTTPException(400, "This assignment has questions: grade each question instead")
    if body.points is not None and body.points > pipeline.max_points(assignment):
        raise HTTPException(400, f"Points can't be more than {pipeline.max_points(assignment):g}")
    changes = {
        "grader_points": body.points,
        "grader_note": body.note.strip() if body.points is not None else "",
        "graded_by": user["name"] if body.points is not None else None,
        "graded_at": db.now() if body.points is not None else None,
    }
    await db.submissions.update_one({"_id": sub["_id"]}, {"$set": changes})
    sub.update(changes)
    return {
        "grader_points": sub["grader_points"], "grader_note": sub["grader_note"], "graded_by": sub["graded_by"],
        "final": pipeline.final_grade(assignment, sub),
    }


class QuestionGradeIn(BaseModel):
    points: float | None = Field(default=None, ge=0, description="null = not graded yet")
    comment: str = Field(default="", max_length=4000)


class QuestionGradesIn(BaseModel):
    questions: list[QuestionGradeIn]
    note: str = Field(default="", max_length=4000, description="Overall feedback")


@router.put("/submissions/{submission_id}/question-grades")
async def set_question_grades(submission_id: str, body: QuestionGradesIn, user: dict = Depends(instructor)):
    """Grade the written solution question by question. Once every question has points, they add up to the
    grader's mark that goes into the final grade."""
    sub, assignment, _ = await load_submission(user, submission_id)
    maxes = pipeline.part_points(assignment)
    if not maxes:
        raise HTTPException(400, "This assignment has no questions: give one total mark instead")
    if len(body.questions) != len(maxes):
        raise HTTPException(400, "Give a grade entry for every question")
    for i, (q, top) in enumerate(zip(body.questions, maxes), 1):
        if q.points is not None and q.points > top + 1e-9:
            raise HTTPException(400, f"Q{i} is worth {top:g} points at most")

    grades = [{"points": q.points, "comment": q.comment.strip()} for q in body.questions]
    complete = all(g["points"] is not None for g in grades)
    changes = {
        "question_grades": grades,
        "grader_points": round(sum(g["points"] for g in grades), 2) if complete else None,
        "grader_note": body.note.strip(),
        "graded_by": user["name"],
        "graded_at": db.now(),
    }
    await db.submissions.update_one({"_id": sub["_id"]}, {"$set": changes})
    sub.update(changes)
    return {
        "question_grades": grades, "grader_points": sub["grader_points"], "grader_note": sub["grader_note"],
        "graded_by": sub["graded_by"], "final": pipeline.final_grade(assignment, sub),
    }
