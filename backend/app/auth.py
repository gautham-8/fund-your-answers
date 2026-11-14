from datetime import timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import db
from .config import settings

bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(user_id: str, role: str) -> str:
    payload = {"sub": user_id, "role": role, "exp": db.now() + timedelta(hours=settings.jwt_expire_hours)}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def public_user(user: dict) -> dict:
    return {"id": str(user["_id"]), "email": user["email"], "name": user["name"], "role": user["role"]}


async def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if creds is None:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(creds.credentials, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")
    user = await db.users.find_one({"_id": db.oid(payload["sub"])})
    if not user:
        raise HTTPException(401, "User not found")
    return user


async def instructor(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "instructor":
        raise HTTPException(403, "Instructors only")
    return user


async def student(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "student":
        raise HTTPException(403, "Students only")
    return user
