"""Accessibility accommodations: typing viva answers instead of speaking them.

Voice is the default for everyone. A student with an accommodation asks for typed answers for a whole viva,
before starting it; the instructor approves or denies. Only an approved request unlocks typed answers.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db, pipeline
from ..access import load_course, load_submission
from ..auth import current_user, instructor, student

router = APIRouter(prefix="/api", tags=["accommodations"])

PENDING, APPROVED, DENIED = "pending", "approved", "denied"


class AccommodationIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class DecisionIn(BaseModel):
    status: Literal["approved", "denied"]
    response: str = Field(default="", max_length=2000)


def out(r: dict | None) -> dict | None:
    if r is None:
        return None
    return {
        "id": str(r["_id"]),
        "submission_id": str(r["submission_id"]),
        "reason": r["reason"],
        "status": r["status"],
        "response": r.get("response", ""),
        "created_at": r["created_at"],
        "decided_at": r.get("decided_at"),
        "decided_by": r.get("decided_by"),
    }


async def for_submission(sub: dict) -> dict | None:
    return await db.accommodation_requests.find_one({"submission_id": sub["_id"]})


async def typed_allowed(sub: dict) -> bool:
    req = await for_submission(sub)
    return bool(req and req["status"] == APPROVED)


async def _viva_started(sub: dict) -> bool:
    return sub["status"] not in (pipeline.ANALYZING, pipeline.ANALYSIS_FAILED, pipeline.OFF_TOPIC, pipeline.READY) or bool(
        await db.viva_turns.find_one({"submission_id": sub["_id"]}, {"_id": 1})
    )


@router.post("/submissions/{submission_id}/accommodation")
async def request_typed(submission_id: str, body: AccommodationIn, user: dict = Depends(student)):
    """Ask for typed answers for this whole viva. Must happen before the first answer."""
    sub, assignment, course = await load_submission(user, submission_id)
    if await _viva_started(sub):
        raise HTTPException(400, "Accommodations must be requested before you start the viva")
    existing = await for_submission(sub)
    if existing and existing["status"] == APPROVED:
        raise HTTPException(409, "Typed answers are already approved for this viva")

    doc = {
        "course_id": course["_id"],
        "assignment_id": assignment["_id"],
        "submission_id": sub["_id"],
        "student_id": user["_id"],
        "kind": "typed_answers",
        "reason": body.reason.strip(),
        "status": PENDING,
        "response": "",
        "created_at": db.now(),
        "decided_at": None,
        "decided_by": None,
    }
    # A denied request can be asked again (e.g. with documentation); it replaces the old one.
    await db.accommodation_requests.replace_one({"submission_id": sub["_id"]}, doc, upsert=True)
    return out(await for_submission(sub))


@router.delete("/submissions/{submission_id}/accommodation", status_code=204)
async def withdraw_typed(submission_id: str, user: dict = Depends(student)):
    sub, _, _ = await load_submission(user, submission_id)
    req = await for_submission(sub)
    if not req or req["status"] != PENDING:
        raise HTTPException(400, "Only a pending request can be withdrawn")
    await db.accommodation_requests.delete_one({"_id": req["_id"]})


@router.get("/courses/{course_id}/accommodations")
async def list_requests(course_id: str, user: dict = Depends(instructor)):
    course = await load_course(user, course_id)
    items = await db.accommodation_requests.find({"course_id": course["_id"]}).sort("created_at", -1).to_list(None)
    asgs = await db.assignments.find({"_id": {"$in": list({r["assignment_id"] for r in items})}}, {"title": 1}).to_list(None)
    titles = {a["_id"]: a["title"] for a in asgs}
    users = await db.users.find({"_id": {"$in": list({r["student_id"] for r in items})}}, {"name": 1, "email": 1}).to_list(None)
    names = {u["_id"]: {"name": u["name"], "email": u["email"]} for u in users}
    return [
        {
            **out(r),
            "assignment": {"id": str(r["assignment_id"]), "title": titles.get(r["assignment_id"], "Deleted assignment")},
            "student": names.get(r["student_id"]),
        }
        for r in items
    ]


@router.patch("/accommodations/{request_id}")
async def decide(request_id: str, body: DecisionIn, user: dict = Depends(instructor)):
    req = await db.accommodation_requests.find_one({"_id": db.oid(request_id)})
    if not req:
        raise HTTPException(404, "Request not found")
    await load_submission(user, str(req["submission_id"]))  # access check
    changes = {"status": body.status, "response": body.response.strip(), "decided_at": db.now(), "decided_by": user["name"]}
    await db.accommodation_requests.update_one({"_id": req["_id"]}, {"$set": changes})
    return out({**req, **changes})
