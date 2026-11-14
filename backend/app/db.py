from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException
from pymongo import ASCENDING, AsyncMongoClient

from .config import settings

client: AsyncMongoClient = AsyncMongoClient(settings.mongodb_uri, tz_aware=True)
db = client[settings.mongodb_db]

users = db["users"]
courses = db["courses"]
assignments = db["assignments"]
submissions = db["submissions"]
viva_turns = db["viva_turns"]
scores = db["scores"]
regrade_requests = db["regrade_requests"]


async def ensure_indexes() -> None:
    await users.create_index("email", unique=True)
    await courses.create_index("join_code", unique=True)
    await assignments.create_index("course_id")
    await submissions.create_index([("assignment_id", ASCENDING), ("student_id", ASCENDING)], unique=True)
    await viva_turns.create_index(
        [("submission_id", ASCENDING), ("question_index", ASCENDING), ("kind", ASCENDING)], unique=True
    )
    await scores.create_index("submission_id", unique=True)
    await regrade_requests.create_index([("course_id", ASCENDING), ("created_at", ASCENDING)])
    await regrade_requests.create_index("submission_id")


def oid(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise HTTPException(404, "Not found")


def now() -> datetime:
    return datetime.now(timezone.utc)


def serialize(doc: dict | None) -> dict | None:
    """Convert ObjectIds to strings and rename _id -> id, recursively."""
    if doc is None:
        return None

    def conv(v):
        if isinstance(v, ObjectId):
            return str(v)
        if isinstance(v, dict):
            return {("id" if k == "_id" else k): conv(x) for k, x in v.items()}
        if isinstance(v, list):
            return [conv(x) for x in v]
        return v

    return conv(doc)
