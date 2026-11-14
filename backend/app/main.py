import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

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


# In production the built Vue app is served from here too (one service, one URL, no CORS).
# Locally STATIC_DIR is unset and Vite's dev server serves the frontend instead.
if settings.static_dir:
    static_root = Path(settings.static_dir).resolve()
    index_html = static_root / "index.html"

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        file = (static_root / path).resolve()
        if path and file.is_file() and file.is_relative_to(static_root):
            # Vite fingerprints asset filenames, so they can be cached forever.
            cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
            return FileResponse(file, headers={"Cache-Control": cache})
        return FileResponse(index_html, headers={"Cache-Control": "no-cache"})  # Vue Router handles the URL
