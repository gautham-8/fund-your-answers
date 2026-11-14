import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .config import settings
from .routers import auth_routes, courses, submissions, viva

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.ensure_indexes()
    # Background tasks don't survive a restart; unstick anything that was mid-flight.
    await db.submissions.update_many(
        {"status": "analyzing"}, {"$set": {"status": "analysis_failed", "error": "Interrupted by a server restart"}}
    )
    await db.submissions.update_many(
        {"status": "scoring"}, {"$set": {"status": "scoring_failed", "error": "Interrupted by a server restart"}}
    )
    yield


app = FastAPI(title="Viva", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (auth_routes, courses, submissions, viva):
    app.include_router(r.router)


@app.get("/api/health")
async def health():
    return {"ok": True}
