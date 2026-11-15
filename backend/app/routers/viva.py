from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pymongo.errors import DuplicateKeyError

from .. import audio as audio_codec
from .. import db, gemini, pipeline, storage
from ..access import load_submission
from ..auth import current_user, student
from ..config import settings

router = APIRouter(prefix="/api", tags=["viva"])

AUDIO_EXT = {"audio/wav": "wav", "audio/x-wav": "wav", "audio/webm": "webm", "audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp4": "m4a"}


async def _state(sub: dict) -> dict:
    turns = await db.viva_turns.find({"submission_id": sub["_id"]}).to_list(None)
    step = pipeline.current_step(sub, turns) if sub["status"] in (pipeline.READY, pipeline.IN_PROGRESS) else None
    return {
        "status": sub["status"],
        "error": sub.get("error"),
        "relevance_note": (sub.get("analysis") or {}).get("relevance_note") if sub["status"] == pipeline.OFF_TOPIC else None,
        "consent_given": sub.get("consent_at") is not None,
        "pages_pending": pipeline.pages_pending(sub),
        "total_questions": len(sub.get("questions", [])),
        "answered_questions": len({t["question_index"] for t in turns if t["kind"] == "main"}),
        "current": step,
    }


def _context_for(sub: dict, assignment: dict, question_index: int, main_turn: dict | None) -> str:
    analysis = sub.get("analysis") or {}
    q = sub["questions"][question_index]
    item = next((i for i in analysis.get("items", []) if i["name"] == q.get("target")), None)
    lines = [f"Submission summary: {analysis.get('summary', '')}"]
    parts = assignment.get("parts") or []
    part = q.get("part") or 0
    if 1 <= part <= len(parts):
        lines.append(f"Assignment question {part} that this is about: {parts[part - 1]}")
    if item:
        lines.append(f"The question is about: {item['name']} (page {item['page']}): {item['description']}")
        lines.append(f'Excerpt from their PDF: "{item["excerpt"]}"')
    if main_turn:
        lines.append(f"Original question: {main_turn['question']}")
        lines.append(f"Student's first answer: {main_turn.get('transcript', '')}")
    return "\n".join(lines)


@router.get("/submissions/{submission_id}/viva")
async def viva_state(submission_id: str, user: dict = Depends(student)):
    sub, _, _ = await load_submission(user, submission_id)
    return await _state(sub)


@router.post("/submissions/{submission_id}/viva/consent")
async def give_consent(submission_id: str, user: dict = Depends(student)):
    sub, _, _ = await load_submission(user, submission_id)
    if pipeline.pages_pending(sub):
        raise HTTPException(400, "Confirm which pages answer each question first")
    if sub.get("consent_at") is None:
        await db.submissions.update_one({"_id": sub["_id"]}, {"$set": {"consent_at": db.now()}})
        sub["consent_at"] = db.now()
    return await _state(sub)


@router.post("/submissions/{submission_id}/viva/answer")
async def answer(
    submission_id: str,
    background: BackgroundTasks,
    question_index: int = Form(...),
    kind: Literal["main", "followup"] = Form(...),
    text: str | None = Form(None),
    audio: UploadFile | None = File(None),
    user: dict = Depends(student),
):
    sub, assignment, _ = await load_submission(user, submission_id)
    if sub["status"] not in (pipeline.READY, pipeline.IN_PROGRESS):
        raise HTTPException(400, "The viva is not open")
    if sub.get("consent_at") is None:
        raise HTTPException(400, "Please accept the recording notice first")

    turns = await db.viva_turns.find({"submission_id": sub["_id"]}).to_list(None)
    step = pipeline.current_step(sub, turns)
    if not step or step["question_index"] != question_index or step["kind"] != kind:
        raise HTTPException(409, "That question has already been answered; refresh to continue")

    audio_bytes, audio_mime = None, None
    if audio is not None:
        audio_bytes = await audio.read()
        if len(audio_bytes) > settings.max_audio_mb * 1024 * 1024:
            raise HTTPException(413, "Recording is too long")
        if len(audio_bytes) < 1000:
            raise HTTPException(400, "Recording is empty; please try again")
        audio_mime = (audio.content_type or "audio/wav").split(";")[0]
    elif not (text and text.strip()):
        raise HTTPException(400, "Record an answer or type one")

    main_turn = next((t for t in turns if t["question_index"] == question_index and t["kind"] == "main"), None)
    try:
        ev = await gemini.evaluate_answer(
            question=step["question"],
            context=_context_for(sub, assignment, question_index, main_turn if kind == "followup" else None),
            is_followup=(kind == "followup"),
            audio_bytes=audio_bytes,
            audio_mime=audio_mime or "audio/wav",
            typed_answer=None if audio_bytes else text.strip(),
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Could not process the answer, please try again ({str(e)[:200]})")

    # Store the recording only once the answer was processed, so failed attempts leave nothing behind.
    # Gemini got the original; we keep a compressed copy for playback when ffmpeg is available.
    audio_file_id = None
    if audio_bytes:
        stored, stored_mime = audio_bytes, audio_mime
        mp3 = await audio_codec.to_mp3(audio_bytes)
        if mp3:
            stored, stored_mime = mp3, "audio/mpeg"
        audio_file_id = await storage.save(
            stored,
            f"q{question_index + 1}_{kind}.{AUDIO_EXT.get(stored_mime, 'bin')}",
            stored_mime,
            kind="viva_audio",
            submission_id=sub["_id"],
            original_bytes=len(audio_bytes),
        )

    turn = {
        "submission_id": sub["_id"],
        "question_index": question_index,
        "kind": kind,
        "question": step["question"],
        "transcript": ev.transcript.strip(),
        "answer_mode": "voice" if audio_bytes else "typed",
        "audio_file_id": audio_file_id,
        "quality": ev.quality,
        "notes": ev.notes,
        "followup_question": ev.followup_question.strip() if kind == "main" else "",
        "created_at": db.now(),
    }
    try:
        await db.viva_turns.insert_one(turn)
    except DuplicateKeyError:
        await storage.delete(audio_file_id)
        raise HTTPException(409, "That question has already been answered; refresh to continue")

    turns.append(turn)
    if pipeline.current_step(sub, turns) is None:
        await db.submissions.update_one({"_id": sub["_id"]}, {"$set": {"status": pipeline.SCORING}})
        sub["status"] = pipeline.SCORING
        background.add_task(pipeline.run_scoring, sub["_id"])
    elif sub["status"] == pipeline.READY:
        await db.submissions.update_one({"_id": sub["_id"]}, {"$set": {"status": pipeline.IN_PROGRESS}})
        sub["status"] = pipeline.IN_PROGRESS

    state = await _state(sub)
    state["last_transcript"] = turn["transcript"]
    return state


@router.get("/turns/{turn_id}/audio")
async def turn_audio(turn_id: str, user: dict = Depends(current_user)):
    turn = await db.viva_turns.find_one({"_id": db.oid(turn_id)})
    if not turn or not turn.get("audio_file_id"):
        raise HTTPException(404, "No audio")
    await load_submission(user, str(turn["submission_id"]))  # access check
    return await storage.file_response(turn["audio_file_id"])
