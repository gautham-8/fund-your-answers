"""Create demo data: an instructor, a class, an assignment and students at different stages.

Usage (from backend/):
    .venv/bin/python scripts/seed_demo.py                 # uses MONGODB_URI from .env
    DEMO_PASSWORD=something .venv/bin/python scripts/seed_demo.py

Safe to re-run: it first deletes everything belonging to @viva.demo accounts (and nothing else).
On macOS it also generates spoken recordings with `say` + ffmpeg so audio playback can be demoed.
"""

import asyncio
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db, storage  # noqa: E402
from app.auth import hash_password  # noqa: E402
from app.config import DEFAULT_RUBRIC  # noqa: E402
from app.pipeline import overall_score  # noqa: E402

DOMAIN = "@viva.demo"

ASSIGNMENT = {
    "title": "Sorting Algorithms Report",
    "description": "Implement a sorting algorithm for a dataset of nearly-sorted sensor readings, "
    "justify your design choices, and benchmark it against at least one alternative.",
}

ANALYSIS = {
    "summary": "The report implements quicksort for nearly-sorted sensor data, using a median-of-three pivot, "
    "an insertion-sort cutoff for small partitions, and an in-place partition. It benchmarks against mergesort.",
    "embedded_instructions_detected": False,
    "items": [
        {"kind": "decision", "name": "Median-of-three pivot", "description": "Chooses the median of first, middle and last elements as pivot.", "page": 2, "excerpt": "we pick the median of the first, middle and last element as the pivot"},
        {"kind": "decision", "name": "Insertion sort cutoff", "description": "Switches to insertion sort for partitions under 16 elements.", "page": 2, "excerpt": "below 16 elements we fall back to insertion sort"},
        {"kind": "method", "name": "In-place partitioning", "description": "Uses Hoare-style in-place partitioning to avoid extra memory.", "page": 3, "excerpt": "partitioning is done in place so no auxiliary array is needed"},
        {"kind": "method", "name": "Benchmark vs mergesort", "description": "Compares runtime and memory against mergesort on 1M readings.", "page": 4, "excerpt": "on one million readings quicksort was 1.4x faster than mergesort"},
    ],
}

QUESTIONS = [
    {"question": "Why did you choose a median-of-three pivot instead of always using the first element?", "target": "Median-of-three pivot", "page": 2},
    {"question": "What made you pick 16 as the cutoff for switching to insertion sort?", "target": "Insertion sort cutoff", "page": 2},
    {"question": "How does your in-place partition work, and what does it save compared to mergesort?", "target": "In-place partitioning", "page": 3},
    {"question": "Your benchmark shows quicksort was faster. When might mergesort be the better choice?", "target": "Benchmark vs mergesort", "page": 4},
]

# (name, email-local, status, answers[(transcript, quality, notes, followup_q, followup_answer)], scores, summary)
STUDENTS = [
    {
        "name": "Aisha Khan", "user": "aisha", "status": "completed",
        "answers": [
            ("Because our sensor data is nearly sorted, the first element would almost always be the smallest, so every partition would be lopsided and quicksort would go quadratic. The median of three gives a pivot near the middle on sorted input.", "strong", "Clear link between data shape and pivot choice.", "", ""),
            ("Honestly I tried 8, 16 and 32 and 16 was fastest on our machine. Insertion sort has low overhead on tiny arrays because there's no recursion.", "strong", "Empirical justification plus reasoning.", "", ""),
            ("We swap elements around the pivot inside the same array, so memory is just the recursion stack, log n on average. Mergesort needs an extra array of size n.", "strong", "Accurate comparison of memory use.", "", ""),
            ("If we needed a stable sort, like keeping readings with equal values in time order, mergesort is stable and quicksort isn't. Also mergesort has a guaranteed n log n worst case.", "strong", "Identifies stability and worst-case guarantees.", "", ""),
        ],
        "scores": [(5, "the first element would almost always be the smallest, so every partition would be lopsided", 0.9),
                   (4, "I tried 8, 16 and 32 and 16 was fastest on our machine", 0.85),
                   (5, "memory is just the recursion stack, log n on average", 0.9),
                   (4, "mergesort is stable and quicksort isn't", 0.85)],
        "summary": "Explains each design choice with specific reasoning tied to the dataset and shows solid understanding of trade-offs.",
    },
    {
        "name": "Ben Ortiz", "user": "ben", "status": "completed",
        "answers": [
            ("It's just better, the median of three is the standard way to do it.", "weak", "Does not explain why.", "What would go wrong with the first element as pivot on your nearly-sorted data?", "Um, I think it would be slower, maybe because the pivot is bad."),
            ("We read that 16 is a good number in a blog post.", "partial", "Cites a source but no reasoning.", "", ""),
            ("It moves smaller elements to the left and bigger to the right of the pivot, in the same array.", "partial", "Describes mechanism, does not address memory comparison.", "", ""),
            ("Mergesort is better when the data is random I think.", "weak", "Incorrect reasoning about when mergesort is preferable.", "", ""),
        ],
        "scores": [(2, "I think it would be slower, maybe because the pivot is bad", 0.7),
                   (2, "It's just better, the median of three is the standard way to do it", 0.75),
                   (2, "We read that 16 is a good number in a blog post", 0.7),
                   (3, "It moves smaller elements to the left and bigger to the right of the pivot", 0.8)],
        "summary": "Can describe what the code does but struggles to explain why the choices were made or when alternatives fit better.",
        "override": (1, 3, "Partition explanation was clearer in office hours; bumping reasoning slightly."),
    },
    {
        "name": "Chen Wei", "user": "chen", "status": "completed",
        "answers": [
            ("Median of three avoids the worst case when the input is already sorted, which is our situation with the sensors.", "strong", "Correct and specific.", "", ""),
            ("Small arrays sort faster with insertion sort. I'm not totally sure why 16 specifically.", "partial", "Partial; no justification for the constant.", "How could you find a good cutoff for your own data?", "I guess I could benchmark a few values and pick the fastest one."),
            ("Uh, I'd have to look at the code again.", "no_answer", "Could not explain the partition.", "", ""),
            ("Mergesort is stable, so if order of equal timestamps matters you'd want it.", "strong", "Correct trade-off.", "", ""),
        ],
        "scores": [(3, "Median of three avoids the worst case when the input is already sorted", 0.55),
                   (3, "I could benchmark a few values and pick the fastest one", 0.5),
                   (3, "Mergesort is stable, so if order of equal timestamps matters you'd want it", 0.6),
                   (3, "Small arrays sort faster with insertion sort", 0.7)],
        "summary": "Mixed: good grasp of pivot choice and stability, but could not explain the partition step.",
    },
    {"name": "Dana Lee", "user": "dana", "status": "ready"},
]


def make_pdf(title: str, body: list[str]) -> bytes:
    """Tiny multi-line, multi-page PDF (no dependencies)."""
    pages = [body[i:i + 1] for i in range(len(body))]
    objs: list[bytes] = []

    def add(b: bytes) -> int:
        objs.append(b)
        return len(objs)

    add(b"<< /Type /Catalog /Pages 2 0 R >>")
    add(b"")  # pages placeholder
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    kids = []
    for i, lines in enumerate(pages):
        text = [f"({title} - page {i + 1}) Tj 0 -24 Td"] + [f"({ln.replace('(', '[').replace(')', ']')}) Tj 0 -16 Td" for ln in lines]
        stream = ("BT /F1 11 Tf 50 750 Td " + " ".join(text) + " ET").encode()
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        kids.append(add(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents %d 0 R /Resources << /Font << /F1 %d 0 R >> >> >>" % (content, font)))
    objs[1] = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids) + b"] /Count %d >>" % len(kids)

    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (len(objs) + 1, x)
    return out


def speak(text: str) -> bytes | None:
    """macOS text-to-speech -> MP3. Returns None where `say`/ffmpeg aren't available."""
    if not (shutil.which("say") and shutil.which("ffmpeg")):
        return None
    with tempfile.TemporaryDirectory() as d:
        aiff, mp3 = Path(d) / "a.aiff", Path(d) / "a.mp3"
        try:
            subprocess.run(["say", "-o", str(aiff), text], check=True, capture_output=True, timeout=60)
            subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(aiff), "-ac", "1", "-b:a", "32k", str(mp3)],
                           check=True, capture_output=True, timeout=60)
            return mp3.read_bytes()
        except (subprocess.SubprocessError, OSError):
            return None


async def wipe_demo() -> None:
    pattern = re.escape(DOMAIN) + "$"
    users = await db.users.find({"email": {"$regex": pattern}}).to_list(None)
    uids = [u["_id"] for u in users]
    courses = await db.courses.find({"instructor_id": {"$in": uids}}).to_list(None)
    assignments = await db.assignments.find({"course_id": {"$in": [c["_id"] for c in courses]}}).to_list(None)
    subs = await db.submissions.find({"$or": [
        {"assignment_id": {"$in": [a["_id"] for a in assignments]}}, {"student_id": {"$in": uids}},
    ]}).to_list(None)
    sids = [s["_id"] for s in subs]
    files = await db.db["files.files"].find({"metadata.submission_id": {"$in": sids}}, {"_id": 1}).to_list(None)
    for f in files:
        await storage.delete(f["_id"])
    await db.viva_turns.delete_many({"submission_id": {"$in": sids}})
    await db.scores.delete_many({"submission_id": {"$in": sids}})
    await db.submissions.delete_many({"_id": {"$in": sids}})
    await db.assignments.delete_many({"_id": {"$in": [a["_id"] for a in assignments]}})
    await db.courses.delete_many({"_id": {"$in": [c["_id"] for c in courses]}})
    # Remove demo students from any non-demo class they might have joined
    await db.courses.update_many({}, {"$pull": {"student_ids": {"$in": uids}}})
    await db.users.delete_many({"_id": {"$in": uids}})
    print(f"Removed previous demo data: {len(users)} users, {len(courses)} classes, {len(subs)} submissions, {len(files)} files")


async def main() -> None:
    password = os.environ.get("DEMO_PASSWORD") or secrets.token_urlsafe(9)
    await db.ensure_indexes()
    await wipe_demo()
    now = db.now()
    pw_hash = hash_password(password)

    inst_id = (await db.users.insert_one({
        "name": "Dr. Demo Instructor", "email": f"instructor{DOMAIN}", "password_hash": pw_hash,
        "role": "instructor", "created_at": now,
    })).inserted_id

    student_ids = {}
    for s in STUDENTS:
        student_ids[s["user"]] = (await db.users.insert_one({
            "name": s["name"], "email": f"{s['user']}{DOMAIN}", "password_hash": pw_hash,
            "role": "student", "created_at": now,
        })).inserted_id

    course_id = (await db.courses.insert_one({
        "name": "CS 201: Algorithms (Demo)", "instructor_id": inst_id, "join_code": "DEMO" + secrets.choice("ABCDEFGHJKMNPQRSTUVWXYZ") + secrets.choice("23456789"),
        "student_ids": list(student_ids.values()), "created_at": now,
    })).inserted_id

    assignment_id = (await db.assignments.insert_one({
        "course_id": course_id, **ASSIGNMENT, "due_date": now + timedelta(days=7),
        "rubric": DEFAULT_RUBRIC, "created_at": now,
    })).inserted_id

    with_audio = 0
    for s in STUDENTS:
        pdf = make_pdf(f"{s['name']} - Sorting Report", [
            "1. Introduction. Our sensor readings arrive nearly sorted by timestamp.",
            "2. Design. We pick the median of the first, middle and last element as the pivot. Below 16 elements we fall back to insertion sort.",
            "3. Implementation. Partitioning is done in place so no auxiliary array is needed.",
            "4. Evaluation. On one million readings quicksort was 1.4x faster than mergesort.",
        ])
        completed = s["status"] == "completed"
        sub = {
            "assignment_id": assignment_id, "student_id": student_ids[s["user"]], "filename": f"{s['user']}_sorting_report.pdf",
            "status": s["status"], "analysis": ANALYSIS, "questions": QUESTIONS,
            "consent_at": now if completed else None, "error": None, "created_at": now - timedelta(hours=2),
        }
        sub_id = (await db.submissions.insert_one(sub)).inserted_id
        pdf_id = await storage.save(pdf, sub["filename"], "application/pdf", kind="submission_pdf", submission_id=sub_id)
        await db.submissions.update_one({"_id": sub_id}, {"$set": {"pdf_file_id": pdf_id}})
        if not completed:
            continue

        turns = []
        for i, (ans, quality, notes, fu_q, fu_a) in enumerate(s["answers"]):
            entries = [("main", QUESTIONS[i]["question"], ans, quality, notes, fu_q)]
            if fu_q:
                entries.append(("followup", fu_q, fu_a, "partial", "Follow-up answer.", ""))
            for kind, q, a, qual, n, fq in entries:
                audio = speak(a)
                audio_id = None
                if audio:
                    with_audio += 1
                    audio_id = await storage.save(audio, f"q{i + 1}_{kind}.mp3", "audio/mpeg", kind="viva_audio", submission_id=sub_id)
                turns.append({
                    "submission_id": sub_id, "question_index": i, "kind": kind, "question": q, "transcript": a,
                    "answer_mode": "voice" if audio_id else "typed", "audio_file_id": audio_id,
                    "quality": qual, "notes": n, "followup_question": fq, "created_at": now - timedelta(hours=1),
                })
        await db.viva_turns.insert_many(turns)

        dims = []
        for r, (score, quote, conf) in zip(DEFAULT_RUBRIC, s["scores"]):
            dims.append({
                "dimension": r["name"], "score": score, "evidence_quote": quote,
                "rationale": f"Based on the student's answer: \"{quote[:60]}...\"", "confidence": conf,
                "quote_verified": True, "needs_review": conf < 0.6, "override_score": None, "override_note": "",
            })
        if "override" in s:
            idx, new, note = s["override"]
            dims[idx].update(override_score=new, override_note=note, overridden_by="Dr. Demo Instructor")
        needs_review = any(d["needs_review"] and d.get("override_score") is None for d in dims)
        overall = overall_score(dims)
        await db.scores.insert_one({
            "submission_id": sub_id, "dimensions": dims, "summary": s["summary"],
            "overall": overall, "needs_review": needs_review, "created_at": now,
        })
        await db.submissions.update_one({"_id": sub_id}, {"$set": {"overall": overall, "needs_review": needs_review}})

    print(f"\nDemo data created in database '{db.db.name}' ({with_audio} spoken recordings).")
    print(f"  Instructor: instructor{DOMAIN}")
    print(f"  Students:   {', '.join(s['user'] + DOMAIN for s in STUDENTS)}")
    if os.environ.get("DEMO_PASSWORD"):
        print("  Password:   the DEMO_PASSWORD you set")
    else:
        print(f"  Password:   {password}   (same for all demo accounts; re-run to reset)")


if __name__ == "__main__":
    asyncio.run(main())
