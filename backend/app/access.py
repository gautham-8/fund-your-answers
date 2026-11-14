"""Load a resource and check the current user is allowed to see it."""

from fastapi import HTTPException

from . import db


def _is_instructor_of(user: dict, course: dict) -> bool:
    return user["role"] == "instructor" and course["instructor_id"] == user["_id"]


def _is_member_of(user: dict, course: dict) -> bool:
    return user["role"] == "student" and user["_id"] in course.get("student_ids", [])


async def load_course(user: dict, course_id: str) -> dict:
    course = await db.courses.find_one({"_id": db.oid(course_id)})
    if not course or not (_is_instructor_of(user, course) or _is_member_of(user, course)):
        raise HTTPException(404, "Class not found")
    return course


async def load_assignment(user: dict, assignment_id: str) -> tuple[dict, dict]:
    assignment = await db.assignments.find_one({"_id": db.oid(assignment_id)})
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    course = await load_course(user, str(assignment["course_id"]))
    return assignment, course


async def load_submission(user: dict, submission_id: str) -> tuple[dict, dict, dict]:
    sub = await db.submissions.find_one({"_id": db.oid(submission_id)})
    if not sub:
        raise HTTPException(404, "Submission not found")
    assignment = await db.assignments.find_one({"_id": sub["assignment_id"]})
    course = await db.courses.find_one({"_id": assignment["course_id"]})
    if _is_instructor_of(user, course) or sub["student_id"] == user["_id"]:
        return sub, assignment, course
    raise HTTPException(404, "Submission not found")
