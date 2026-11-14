import secrets
from collections import Counter, defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from .. import db, pipeline, schedule
from ..access import load_assignment, load_course
from ..auth import current_user, instructor, student
from ..config import DEFAULT_RUBRIC

router = APIRouter(prefix="/api", tags=["courses"])

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I
# Statuses where the student has finished their part.
DONE = (pipeline.SCORING, pipeline.SCORING_FAILED, pipeline.COMPLETED)


class CourseIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    code: str = Field(default="", max_length=40)
    term: str = Field(default="", max_length=40)


class CoursePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    code: str | None = Field(default=None, max_length=40)
    term: str | None = Field(default=None, max_length=40)


class JoinIn(BaseModel):
    code: str


class RubricItem(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = ""


class AssignmentIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    release_date: datetime | None = None
    due_date: datetime | None = None
    late_due_date: datetime | None = None
    rubric: list[RubricItem] | None = None
    parts: list[str] = Field(default=[], max_length=30, description="The assignment's own questions, in order")


class AssignmentPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    release_date: datetime | None = None
    due_date: datetime | None = None
    late_due_date: datetime | None = None
    grades_published: bool | None = None


def _course_out(course: dict, user: dict, instructor_name: str | None = None) -> dict:
    out = {
        "id": str(course["_id"]),
        "name": course["name"],
        "code": course.get("code", ""),
        "term": course.get("term") or schedule.term_for(course.get("created_at") or db.now()),
        "student_count": len(course.get("student_ids", [])),
        "instructor_name": instructor_name,
    }
    if user["role"] == "instructor":
        out["join_code"] = course["join_code"]
    return out


async def _instructor_names(courses: list[dict]) -> dict:
    ids = list({c["instructor_id"] for c in courses})
    users = await db.users.find({"_id": {"$in": ids}}, {"name": 1}).to_list(None)
    return {u["_id"]: u["name"] for u in users}


@router.post("/courses")
async def create_course(body: CourseIn, user: dict = Depends(instructor)):
    for _ in range(5):
        course = {
            "name": body.name.strip(),
            "code": body.code.strip(),
            "term": body.term.strip() or schedule.term_for(db.now()),
            "instructor_id": user["_id"],
            "join_code": "".join(secrets.choice(CODE_ALPHABET) for _ in range(6)),
            "student_ids": [],
            "created_at": db.now(),
        }
        try:
            res = await db.courses.insert_one(course)
            course["_id"] = res.inserted_id
            return _course_out(course, user, user["name"])
        except DuplicateKeyError:
            continue
    raise HTTPException(500, "Could not generate a join code, try again")


@router.get("/courses")
async def list_courses(user: dict = Depends(current_user)):
    is_inst = user["role"] == "instructor"
    q = {"instructor_id": user["_id"]} if is_inst else {"student_ids": user["_id"]}
    items = await db.courses.find(q).sort("created_at", -1).to_list(None)
    if not items:
        return []
    ids = [c["_id"] for c in items]
    now = db.now()
    names = await _instructor_names(items)

    asgs = await db.assignments.find({"course_id": {"$in": ids}}).to_list(None)
    if not is_inst:
        asgs = [a for a in asgs if schedule.is_released(a, now)]
    by_course = defaultdict(list)
    for a in asgs:
        by_course[a["course_id"]].append(a)

    open_regrades: Counter = Counter()
    done_ids: set = set()
    if is_inst:
        async for r in db.regrade_requests.find({"course_id": {"$in": ids}, "status": "open"}, {"course_id": 1}):
            open_regrades[r["course_id"]] += 1
    else:
        subs = await db.submissions.find(
            {"student_id": user["_id"], "assignment_id": {"$in": [a["_id"] for a in asgs]}, "status": {"$in": list(DONE)}},
            {"assignment_id": 1},
        ).to_list(None)
        done_ids = {s["assignment_id"] for s in subs}

    out = []
    for c in items:
        course_asgs = by_course[c["_id"]]
        upcoming = sorted(
            (schedule.utc(a["due_date"]) for a in course_asgs
             if a.get("due_date") and schedule.utc(a["due_date"]) > now and a["_id"] not in done_ids),
        )
        item = _course_out(c, user, names.get(c["instructor_id"]))
        item["assignment_count"] = len(course_asgs)
        item["next_due"] = upcoming[0] if upcoming else None
        if is_inst:
            item["open_regrades"] = open_regrades[c["_id"]]
        else:
            item["todo_count"] = len(upcoming)
        out.append(item)
    return out


@router.get("/upcoming")
async def upcoming(user: dict = Depends(current_user)):
    """Assignments across all of the user's classes that are still open for submissions, soonest first."""
    is_inst = user["role"] == "instructor"
    q = {"instructor_id": user["_id"]} if is_inst else {"student_ids": user["_id"]}
    courses = {c["_id"]: c for c in await db.courses.find(q).to_list(None)}
    now = db.now()
    asgs = await db.assignments.find({"course_id": {"$in": list(courses)}, "due_date": {"$ne": None}}).to_list(None)
    asgs = [a for a in asgs if schedule.deadline(a) and schedule.deadline(a) > now
            and (is_inst or schedule.is_released(a, now))]
    asgs.sort(key=lambda a: schedule.utc(a["due_date"]))

    statuses = {}
    if not is_inst:
        subs = await db.submissions.find(
            {"student_id": user["_id"], "assignment_id": {"$in": [a["_id"] for a in asgs]}}, {"assignment_id": 1, "status": 1}
        ).to_list(None)
        statuses = {s["assignment_id"]: s["status"] for s in subs}
        asgs = [a for a in asgs if statuses.get(a["_id"]) not in DONE]

    out = []
    for a in asgs[:8]:
        c = courses[a["course_id"]]
        item = {
            "id": str(a["_id"]),
            "title": a["title"],
            "release_date": a.get("release_date"),
            "due_date": a.get("due_date"),
            "late_due_date": a.get("late_due_date"),
            "course": {"id": str(c["_id"]), "name": c["name"], "code": c.get("code", "")},
        }
        if not is_inst:
            item["my_status"] = statuses.get(a["_id"])
        out.append(item)
    return out


@router.post("/courses/join")
async def join_course(body: JoinIn, user: dict = Depends(student)):
    code = body.code.strip().upper()
    course = await db.courses.find_one({"join_code": code})
    if not course:
        raise HTTPException(404, "No class with that join code")
    await db.courses.update_one({"_id": course["_id"]}, {"$addToSet": {"student_ids": user["_id"]}})
    course["student_ids"] = list({*course.get("student_ids", []), user["_id"]})
    return _course_out(course, user)


@router.patch("/courses/{course_id}")
async def update_course(course_id: str, body: CoursePatch, user: dict = Depends(instructor)):
    course = await load_course(user, course_id)
    changes = {k: v.strip() for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if changes:
        await db.courses.update_one({"_id": course["_id"]}, {"$set": changes})
        course.update(changes)
    return _course_out(course, user, user["name"])


@router.delete("/courses/{course_id}/enrollment", status_code=204)
async def unenroll(course_id: str, user: dict = Depends(student)):
    course = await load_course(user, course_id)
    await db.courses.update_one({"_id": course["_id"]}, {"$pull": {"student_ids": user["_id"]}})


@router.delete("/courses/{course_id}/students/{student_id}", status_code=204)
async def remove_student(course_id: str, student_id: str, user: dict = Depends(instructor)):
    course = await load_course(user, course_id)
    await db.courses.update_one({"_id": course["_id"]}, {"$pull": {"student_ids": db.oid(student_id)}})


@router.get("/courses/{course_id}")
async def get_course(course_id: str, user: dict = Depends(current_user)):
    course = await load_course(user, course_id)
    is_inst = user["role"] == "instructor"
    now = db.now()
    assignments = await db.assignments.find({"course_id": course["_id"]}).sort("created_at", -1).to_list(None)
    if not is_inst:
        assignments = [a for a in assignments if schedule.is_released(a, now)]
    asg_ids = [a["_id"] for a in assignments]

    q = {"assignment_id": {"$in": asg_ids}}
    if not is_inst:
        q["student_id"] = user["_id"]
    subs = await db.submissions.find(q, {"assignment_id": 1, "status": 1, "overall": 1, "needs_review": 1, "late": 1}).to_list(None)
    subs_by_asg = defaultdict(list)
    for s in subs:
        subs_by_asg[s["assignment_id"]].append(s)

    open_regrades = Counter()
    if is_inst:
        async for r in db.regrade_requests.find({"course_id": course["_id"], "status": "open"}, {"assignment_id": 1}):
            open_regrades[r["assignment_id"]] += 1
    else:
        async for r in db.regrade_requests.find({"course_id": course["_id"], "student_id": user["_id"], "status": "open"}, {"assignment_id": 1}):
            open_regrades[r["assignment_id"]] += 1

    names = await _instructor_names([course])
    out = _course_out(course, user, names.get(course["instructor_id"]))
    out["open_regrades"] = sum(open_regrades.values())
    out["assignments"] = []
    for a in assignments:
        item = {
            "id": str(a["_id"]),
            "title": a["title"],
            "release_date": a.get("release_date"),
            "due_date": a.get("due_date"),
            "late_due_date": a.get("late_due_date"),
            "grades_published": bool(a.get("grades_published")),
            "open_regrades": open_regrades[a["_id"]],
        }
        a_subs = subs_by_asg[a["_id"]]
        if is_inst:
            item["released"] = schedule.is_released(a, now)
            item["submitted_count"] = len(a_subs)
            item["completed_count"] = sum(s["status"] == pipeline.COMPLETED for s in a_subs)
            item["needs_review_count"] = sum(bool(s.get("needs_review")) for s in a_subs if s["status"] == pipeline.COMPLETED)
        else:
            mine = a_subs[0] if a_subs else None
            item["my_status"] = mine["status"] if mine else None
            item["my_late"] = bool(mine and mine.get("late"))
            published = item["grades_published"] and mine and mine["status"] == pipeline.COMPLETED
            item["my_score"] = mine.get("overall") if published else None
        out["assignments"].append(item)

    if is_inst:
        students = await db.users.find(
            {"_id": {"$in": course.get("student_ids", [])}}, {"name": 1, "email": 1}
        ).sort("name", 1).to_list(None)
        counts = Counter()
        async for s in db.submissions.find({"assignment_id": {"$in": asg_ids}}, {"student_id": 1}):
            counts[s["student_id"]] += 1
        out["students"] = [
            {"id": str(s["_id"]), "name": s["name"], "email": s["email"], "submission_count": counts[s["_id"]]}
            for s in students
        ]
    return out


@router.post("/courses/{course_id}/assignments")
async def create_assignment(course_id: str, body: AssignmentIn, user: dict = Depends(instructor)):
    course = await load_course(user, course_id)
    schedule.check_dates(body.release_date, body.due_date, body.late_due_date)
    rubric = [r.model_dump() for r in body.rubric] if body.rubric else DEFAULT_RUBRIC
    doc = {
        "course_id": course["_id"],
        "title": body.title.strip(),
        "description": body.description.strip(),
        "release_date": body.release_date,
        "due_date": body.due_date,
        "late_due_date": body.late_due_date,
        "grades_published": False,
        "rubric": rubric,
        "parts": [q.strip()[:2000] for q in body.parts if q.strip()],
        "created_at": db.now(),
    }
    res = await db.assignments.insert_one(doc)
    doc["_id"] = res.inserted_id
    return db.serialize(doc)


@router.patch("/assignments/{assignment_id}")
async def update_assignment(assignment_id: str, body: AssignmentPatch, user: dict = Depends(instructor)):
    assignment, _ = await load_assignment(user, assignment_id)
    changes = body.model_dump(exclude_unset=True)
    for key in ("title", "grades_published"):  # these can't be cleared
        if key in changes and changes[key] is None:
            del changes[key]
    if "title" in changes:
        changes["title"] = changes["title"].strip()
    if changes.get("description") is not None:
        changes["description"] = changes["description"].strip()
    elif "description" in changes:
        changes["description"] = ""
    merged = {**assignment, **changes}
    schedule.check_dates(merged.get("release_date"), merged.get("due_date"), merged.get("late_due_date"))
    if changes:
        await db.assignments.update_one({"_id": assignment["_id"]}, {"$set": changes})
    return db.serialize(merged)
