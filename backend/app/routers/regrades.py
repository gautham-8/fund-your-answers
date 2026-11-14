"""Regrade requests: once grades are published, a student can ask for one rubric item to be looked at again."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db, pipeline
from ..access import load_course, load_submission
from ..auth import current_user, instructor, student
from .submissions import _regrade_out, apply_override

router = APIRouter(prefix="/api", tags=["regrades"])


class RegradeIn(BaseModel):
    dimension_index: int = Field(ge=0)
    message: str = Field(min_length=1, max_length=2000)


class RegradeResolveIn(BaseModel):
    status: Literal["resolved", "open"] = "resolved"
    response: str = Field(default="", max_length=2000)
    # Optionally change the score while resolving (1-5); None leaves it as it is.
    override_score: int | None = Field(default=None, ge=1, le=5)


def _final(d: dict) -> int:
    return d["override_score"] if d.get("override_score") is not None else d["score"]


@router.post("/submissions/{submission_id}/regrade-requests")
async def create_regrade(submission_id: str, body: RegradeIn, user: dict = Depends(student)):
    sub, assignment, course = await load_submission(user, submission_id)
    if not assignment.get("grades_published") or sub["status"] != pipeline.COMPLETED:
        raise HTTPException(400, "You can request a regrade once your grade has been published")
    score = await db.scores.find_one({"submission_id": sub["_id"]})
    if not score or body.dimension_index >= len(score["dimensions"]):
        raise HTTPException(404, "Rubric item not found")
    if await db.regrade_requests.find_one(
        {"submission_id": sub["_id"], "dimension_index": body.dimension_index, "status": "open"}
    ):
        raise HTTPException(409, "You already have an open regrade request for this rubric item")

    dim = score["dimensions"][body.dimension_index]
    doc = {
        "course_id": course["_id"],
        "assignment_id": assignment["_id"],
        "submission_id": sub["_id"],
        "student_id": user["_id"],
        "dimension_index": body.dimension_index,
        "dimension": dim["dimension"],
        "message": body.message.strip(),
        "status": "open",
        "response": "",
        "score_before": _final(dim),
        "score_after": None,
        "created_at": db.now(),
        "resolved_at": None,
        "resolved_by": None,
    }
    doc["_id"] = (await db.regrade_requests.insert_one(doc)).inserted_id
    return _regrade_out(doc)


@router.get("/courses/{course_id}/regrade-requests")
async def list_regrades(course_id: str, user: dict = Depends(current_user)):
    course = await load_course(user, course_id)
    q = {"course_id": course["_id"]}
    if user["role"] == "student":
        q["student_id"] = user["_id"]
    items = await db.regrade_requests.find(q).sort("created_at", -1).to_list(None)

    asgs = await db.assignments.find({"_id": {"$in": list({r["assignment_id"] for r in items})}}, {"title": 1}).to_list(None)
    titles = {a["_id"]: a["title"] for a in asgs}
    names = {}
    if user["role"] == "instructor":
        users = await db.users.find({"_id": {"$in": list({r["student_id"] for r in items})}}, {"name": 1, "email": 1}).to_list(None)
        names = {u["_id"]: {"name": u["name"], "email": u["email"]} for u in users}

    out = []
    for r in items:
        item = _regrade_out(r)
        item["assignment"] = {"id": str(r["assignment_id"]), "title": titles.get(r["assignment_id"], "Deleted assignment")}
        if user["role"] == "instructor":
            item["student"] = names.get(r["student_id"])
        out.append(item)
    return out


async def _load_request(user: dict, request_id: str) -> tuple[dict, dict]:
    req = await db.regrade_requests.find_one({"_id": db.oid(request_id)})
    if not req:
        raise HTTPException(404, "Regrade request not found")
    sub, _, _ = await load_submission(user, str(req["submission_id"]))  # access check
    return req, sub


@router.patch("/regrade-requests/{request_id}")
async def resolve_regrade(request_id: str, body: RegradeResolveIn, user: dict = Depends(instructor)):
    req, sub = await _load_request(user, request_id)
    if body.override_score is not None:
        await apply_override(sub, req["dimension_index"], body.override_score, body.response, user)

    changes = {"status": body.status, "response": body.response.strip()}
    if body.status == "resolved":
        score = await db.scores.find_one({"submission_id": sub["_id"]})
        dims = score["dimensions"] if score else []
        changes.update({
            "resolved_at": db.now(),
            "resolved_by": user["name"],
            "score_after": _final(dims[req["dimension_index"]]) if req["dimension_index"] < len(dims) else None,
        })
    else:
        changes.update({"resolved_at": None, "resolved_by": None, "score_after": None})
    await db.regrade_requests.update_one({"_id": req["_id"]}, {"$set": changes})
    return _regrade_out({**req, **changes})


@router.delete("/regrade-requests/{request_id}", status_code=204)
async def withdraw_regrade(request_id: str, user: dict = Depends(student)):
    req, _ = await _load_request(user, request_id)
    if req["status"] != "open":
        raise HTTPException(400, "Only open requests can be withdrawn")
    await db.regrade_requests.delete_one({"_id": req["_id"]})
