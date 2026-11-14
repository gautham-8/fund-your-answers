from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from pymongo.errors import DuplicateKeyError

from .. import db
from ..auth import create_token, current_user, hash_password, public_user, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    role: Literal["instructor", "student"]


class LoginIn(BaseModel):
    email: EmailStr
    password: str


def _auth_response(user: dict) -> dict:
    return {"token": create_token(str(user["_id"]), user["role"]), "user": public_user(user)}


@router.post("/register")
async def register(body: RegisterIn):
    user = {
        "name": body.name.strip(),
        "email": body.email.lower(),
        "password_hash": hash_password(body.password),
        "role": body.role,
        "created_at": db.now(),
    }
    try:
        res = await db.users.insert_one(user)
    except DuplicateKeyError:
        raise HTTPException(409, "An account with that email already exists")
    user["_id"] = res.inserted_id
    return _auth_response(user)


@router.post("/login")
async def login(body: LoginIn):
    user = await db.users.find_one({"email": body.email.lower()})
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Wrong email or password")
    return _auth_response(user)


@router.get("/me")
async def me(user: dict = Depends(current_user)):
    return public_user(user)
