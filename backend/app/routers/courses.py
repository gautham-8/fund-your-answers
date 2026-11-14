import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from .. import db
from ..access import load_course
from ..auth import current_user, instructor, student
from ..config import DEFAULT_RUBRIC

router = APIRouter(prefix="/api", tags=["courses"])

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I


class CourseIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class JoinIn(BaseModel):
    code: str


class RubricItem(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = ""


class AssignmentIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    due_date: datetime | None = None
    rubric: list[RubricItem] | None = None
    parts: list[str] = Field(default=[], max_length=30, description="The assignment's own questions, in order")


def _course_out(course: dict, user: dict) -> dict:
    out = {
        "id": str(course["_id"]),
        "name": course["name"],
        "student_count": len(course.get("student_ids", [])),
    }
    if user["role"] == "instructor":
        out["join_code"] = course["join_code"]
    return out


@router.post("/courses")
async def create_course(body: CourseIn, user: dict = Depends(instructor)):
    for _ in range(5):
        course = {
            "name": body.name.strip(),
            "instructor_id": user["_id"],
            "join_code": "".join(secrets.choice(CODE_ALPHABET) for _ in range(6)),
            "student_ids": [],
            "created_at": db.now(),
        }
        try:
            res = await db.courses.insert_one(course)
            course["_id"] = res.inserted_id
            return _course_out(course, user)
        except DuplicateKeyError:
            continue
    raise HTTPException(500, "Could not generate a join code, try again")


@router.get("/courses")
async def list_courses(user: dict = Depends(current_user)):
    q = {"instructor_id": user["_id"]} if user["role"] == "instructor" else {"student_ids": user["_id"]}
    items = await db.courses.find(q).sort("created_at", -1).to_list(None)
    return [_course_out(c, user) for c in items]


@router.post("/courses/join")
async def join_course(body: JoinIn, user: dict = Depends(student)):
    code = body.code.strip().upper()
    course = await db.courses.find_one({"join_code": code})
    if not course:
        raise HTTPException(404, "No class with that join code")
    await db.courses.update_one({"_id": course["_id"]}, {"$addToSet": {"student_ids": user["_id"]}})
    course["student_ids"] = list({*course.get("student_ids", []), user["_id"]})
    return _course_out(course, user)


@router.get("/courses/{course_id}")
async def get_course(course_id: str, user: dict = Depends(current_user)):
    course = await load_course(user, course_id)
    assignments = await db.assignments.find({"course_id": course["_id"]}).sort("created_at", -1).to_list(None)

    my_subs = {}
    if user["role"] == "student":
        subs = await db.submissions.find(
            {"student_id": user["_id"], "assignment_id": {"$in": [a["_id"] for a in assignments]}}
        ).to_list(None)
        my_subs = {s["assignment_id"]: s["status"] for s in subs}

    out = _course_out(course, user)
    out["assignments"] = [
        {
            "id": str(a["_id"]),
            "title": a["title"],
            "due_date": a.get("due_date"),
            **({"my_status": my_subs.get(a["_id"])} if user["role"] == "student" else {}),
        }
        for a in assignments
    ]
    if user["role"] == "instructor":
        students = await db.users.find(
            {"_id": {"$in": course.get("student_ids", [])}}, {"name": 1, "email": 1}
        ).sort("name", 1).to_list(None)
        out["students"] = [{"id": str(s["_id"]), "name": s["name"], "email": s["email"]} for s in students]
    return out


@router.post("/courses/{course_id}/assignments")
async def create_assignment(course_id: str, body: AssignmentIn, user: dict = Depends(instructor)):
    course = await load_course(user, course_id)
    rubric = [r.model_dump() for r in body.rubric] if body.rubric else DEFAULT_RUBRIC
    doc = {
        "course_id": course["_id"],
        "title": body.title.strip(),
        "description": body.description.strip(),
        "due_date": body.due_date,
        "rubric": rubric,
        "parts": [q.strip()[:2000] for q in body.parts if q.strip()],
        "created_at": db.now(),
    }
    res = await db.assignments.insert_one(doc)
    doc["_id"] = res.inserted_id
    return db.serialize(doc)
