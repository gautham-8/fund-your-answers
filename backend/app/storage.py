"""File storage in MongoDB GridFS (PDFs and voice recordings live in Atlas alongside the data)."""

from bson import ObjectId
from fastapi import HTTPException, UploadFile
from fastapi.responses import Response
from gridfs import AsyncGridFSBucket
from gridfs.errors import NoFile

from . import db
from .config import settings

# Stored as files.files / files.chunks collections in the app database.
bucket = AsyncGridFSBucket(db.db, bucket_name="files")


async def save(data: bytes, filename: str, content_type: str, **metadata) -> ObjectId:
    return await bucket.upload_from_stream(
        filename, data, metadata={"content_type": content_type, **metadata}
    )


async def read(file_id: ObjectId) -> tuple[bytes, str, str]:
    """Return (data, content_type, filename)."""
    try:
        stream = await bucket.open_download_stream(file_id)
    except NoFile:
        raise HTTPException(404, "File not found")
    data = await stream.read()
    meta = stream.metadata or {}
    return data, meta.get("content_type", "application/octet-stream"), stream.filename


async def delete(file_id: ObjectId | None) -> None:
    if file_id is None:
        return
    try:
        await bucket.delete(file_id)
    except NoFile:
        pass


async def file_response(file_id: ObjectId | None) -> Response:
    if file_id is None:
        raise HTTPException(404, "File not found")
    data, content_type, filename = await read(file_id)
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"', "Cache-Control": "private, max-age=3600"},
    )


async def read_pdf_upload(file: UploadFile) -> bytes:
    data = await file.read()
    if len(data) > settings.max_pdf_mb * 1024 * 1024:
        raise HTTPException(413, f"PDF must be under {settings.max_pdf_mb} MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "Please upload a PDF file")
    return data
