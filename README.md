# Fund your answers — check that students understand their own work

Instructors create classes and assignments; students submit a PDF and then do a short **voice viva**. Gemini reads
the PDF, finds the methods and design decisions the student used, asks about *those specific choices*, follows up on
what the student actually said, and scores understanding against a rubric with quoted evidence. The instructor gets a
report with transcript, audio, scores and the ability to override any score.

It is **not** an AI or plagiarism detector. It never says a student cheated — it reports an *understanding score* and
flags low-confidence results as *needs review*.

**Live:** https://viva-h9rs.onrender.com (free Render instance — the first visit after ~15 idle minutes takes up to a
minute to wake up).

## Features

- **Classes** — course code, name and term (dashboard groups classes by term). Instructors get a 6-character join code
  (click to copy) and a one-click invite link (`/join/CODE`); they can manage the roster. Students can unenroll.
- **Assignment handout** — instructors can upload the assignment PDF. Gemini pulls out its questions and drafts a viva
  rubric for that assignment; both stay editable before saving. The handout is shown to students and sent to Gemini
  with every submission.
- **Assignments** — title, description, rubric, and a schedule: **release date** (hidden from students until then),
  **due date**, and optional **late due date** (submissions in between are accepted and marked *Late*). Sortable
  assignment table with time-left bars, and an "Up next" list of deadlines across classes.
- **Grades & regrades** — instructors publish grades per assignment; students then see their score, feedback and
  instructor notes, and can request a regrade on any rubric item. Instructors resolve requests (optionally changing
  the score) from the class's *Regrade requests* page.
- **Relevance check** — on upload, Gemini first checks the PDF is a genuine attempt at this assignment's questions.
  If not (unrelated file, a different assignment, blank), no viva opens: the student is told why and can re-upload,
  and the instructor can let it through if the AI got it wrong.
- **PDF analysis** — Gemini lists methods and decisions (tied to the assignment question they answer) with page
  numbers, then writes 4 questions about how the student answered the assignment.
- **Answer pages** — instructors can list the assignment's questions. The same Gemini call picks the PDF pages that
  answer each one; the student checks and fixes the pages on rendered page images (and can reorder or rotate pages),
  then confirms before the viva opens. The report shows them.
- **Voice viva** — consent notice first; record (or type) each answer. Gemini transcribes and judges in one call and
  asks at most one follow-up per question, based on the actual answer.
- **Scoring** — each rubric dimension gets a 0–5 score (0 = no understanding shown, e.g. "I don't know"; 5 = correct
  and explains their reasoning, not "perfect"), an exact quote as evidence and a confidence. The server checks
  the quote really appears in the transcript; unverified quotes or low confidence → **needs review**.
- **Grading viewer** — Gradescope-style: the student's pages one at a time (zoom, rotate, all-pages grid) next to
  the assignment's questions. Clicking a question jumps to its first page; the grader enters points and a comment per
  question and the total adds up as they go (⌘S saves, "Next student" moves on). Students get the same view
  read-only, with marks and comments once grades are published.
- **Question points** — each assignment question has points (read from the handout when it states them). They add up
  to what the written solution is marked out of, and can be changed after the assignment is created.
- **Final grade** — the viva only measures understanding. A human grader marks the written solution in the grading viewer, and the final grade is `(1 − w) × grader % + w × viva %`, where the viva
  weight `w` is set per assignment (default 30%, changeable any time).
- **Instructor report** — transcript, audio playback, analysis, PDF, grader's mark, scores with evidence, per-dimension overrides.
- **Class insights** — average rubric scores, how often instructors changed the AI's scores and by how much, and
  "concepts the class struggled to explain" (anonymised before it is sent to Gemini).

Safeguards: the PDF and answers are treated as untrusted data (prompt-injection attempts are ignored and flagged);
accent, pauses and phrasing are not judged; API keys stay on the server; students see progress, not scores, until grades are published;
login is rate-limited (5 failures per 15 minutes).

## How it fits together

```
Browser (Vue 3 + Tailwind)
   │  records audio with MediaRecorder → 16 kHz WAV
   ▼
FastAPI (one Docker container on Render; also serves the built frontend)
   ├── Gemini API ─ PDF analysis, questions, transcription + judging, scoring, class gaps
   │                 (structured JSON output; models set via env vars)
   └── MongoDB Atlas ─ data + files (PDFs and MP3 recordings in GridFS)
```

| Collection | Holds |
|---|---|
| `users`, `courses`, `assignments` | accounts (bcrypt hashes), classes + join codes + roster, assignments + rubric + cached class gaps |
| `submissions` | status, PDF analysis + relevance check, the 4 questions, answer pages per assignment question, page order and rotation, consent time, viva score (`overall`), grader's points |
| `viva_turns` | question, transcript, quality notes, follow-up, link to the audio file |
| `scores` | per-dimension score, evidence quote, confidence, overrides |
| `regrade_requests` | student's message about one rubric item, status, instructor response, score before/after |
| `files.files` / `files.chunks` | GridFS: uploaded PDFs and compressed recordings |

Submission status: `analyzing → ready → viva_in_progress → scoring → completed` (or `analysis_failed` /
`scoring_failed`, both retryable from the UI).

## Running locally

Requirements: Python 3.11+, Node 20+, and `ffmpeg` (optional — recordings are stored as WAV without it).

**1. Configure** — copy `backend/.env.example` to `backend/.env` and fill in:

| Variable | What |
|---|---|
| `MONGODB_URI` | Atlas connection string (or `mongodb://localhost:27017` for a local mongod) |
| `GEMINI_API_KEY` | from https://aistudio.google.com/apikey |
| `JWT_SECRET` | any long random string |
| `GEMINI_*_MODEL` | model per task (default `gemini-3.5-flash-lite`) |
| `GEMINI_FALLBACK_MODELS` | optional comma-separated models to try when the main one is overloaded |

**2. Backend** (terminal 1)
```bash
cd backend
uv venv .venv && uv pip install -p .venv -r requirements.txt   # first time
.venv/bin/uvicorn app.main:app --reload --port 8000
```

**3. Frontend** (terminal 2)
```bash
cd frontend
npm install   # first time
npm run dev   # http://localhost:5173 — proxies /api to :8000; the mic works on localhost
```

### Demo data
```bash
cd backend
.venv/bin/python scripts/seed_demo.py
```
Creates `instructor@viva.demo` and four students (`aisha`, `ben`, `chen`, `dana` `@viva.demo`): three completed vivas
(strong / weak with an instructor override / mixed and flagged for review) and one not started. On macOS it generates
spoken recordings with `say` so audio playback works. All demo accounts share the password in `DEMO_PASSWORD` from
`backend/.env` (a random one is generated and printed if unset). Re-running replaces only `@viva.demo` data.

### Tests
```bash
cd backend
uv pip install -p .venv -r requirements-dev.txt
mongod --dbpath /tmp/viva-test-db --fork --logpath /tmp/viva-test-db.log   # tests need a local MongoDB
.venv/bin/pytest
```
Gemini is stubbed, and each run uses a throwaway database that is dropped afterwards. Covers auth + lockout, roles,
roster, due dates, the full viva flow (follow-ups, scoring, needs-review rules, GridFS files, MP3 compression, access
control, overrides) and class insights.

## Deployment (Render)

`render.yaml` defines one free Docker web service. The `Dockerfile` builds the Vue app, then a Python image (with
ffmpeg) that serves both the API and the frontend from one URL — so no CORS setup.

- Every push to `main` redeploys automatically.
- Secrets are set in the Render dashboard: `MONGODB_URI`, `GEMINI_API_KEY`. `JWT_SECRET` is generated by Render.
- HTTPS comes from Render, which the browser requires for microphone access.

## Limits and next steps

- **Gemini free tier**: Google may use free-tier inputs to improve its products — use a paid key for real student data.
- **Atlas free tier (512 MB)**: roughly 1–5 MB per PDF plus ~0.25 MB per minute of MP3 audio.
- **Free Render instance** sleeps when idle; background analysis interrupted by a restart is marked failed and can be retried.
- Not built: password reset (needs an email service), streaming voice via the Gemini Live API.

## Project layout

```
Dockerfile, render.yaml       deployment
backend/app/
  main.py                     FastAPI app, routers, serves the built frontend in production
  config.py                   settings from env, default rubric
  db.py, storage.py           MongoDB collections; GridFS file storage
  auth.py, access.py          bcrypt + JWT + roles; "can this user see this?" checks
  gemini.py                   every prompt and structured-output schema, model fallback
  pipeline.py                 background PDF analysis, viva progress, scoring, needs-review rules
  audio.py                    WAV → MP3 compression via ffmpeg
  routers/                    auth, courses, submissions, viva, insights
backend/scripts/seed_demo.py  demo data
backend/tests/                pytest suite
frontend/src/
  views/                      Login, Dashboard, Course, Assignment, Viva (student), Report (instructor)
  components/                 StatusBadge, ClassInsights
  lib/                        api client, auth state, recorder (MediaRecorder → WAV)
```

---

## Original brief

<details>
<summary>The hackathon spec this was built from</summary>

### Build: "Fund your answers" — verify student understanding with a short voice viva

Build a hackathon web app (3 days). Keep it simple and demo-ready. Make reasonable choices yourself and don't over-engineer.

#### What it does
A mini Gradescope: instructors create classes and assignments, students join and submit PDFs. After submitting, the student does a short **voice viva**: an LLM reads their PDF, finds the methods and decisions they used, asks questions about those, asks follow-ups based on their spoken answers, and scores understanding. The instructor sees a report with evidence.

It is NOT an AI detector. Never say a student cheated. Use wording like "understanding score" and "needs review".

#### Stack
- Frontend: Vue 3 + Vite + Tailwind, browser MediaRecorder for audio
- Backend: FastAPI (Python), Pydantic
- LLM: Gemini API (`google-genai` SDK), model names in env vars. Use its PDF input and audio input, with structured JSON output
- DB: MongoDB Atlas
- Auth: email + password, JWT, roles `instructor` / `student`
- Deploy: Docker on a Vultr VM with HTTPS (mic needs HTTPS)

#### Features (core only)
1. **Classes:** instructor creates a class and gets a join code; student joins with it.
2. **Assignments:** instructor adds title, description, due date, and a simple rubric (default: Accuracy, Reasoning depth, Specificity, Clarity).
3. **Submissions:** student uploads a PDF; instructor sees a list of submissions with status and score.
4. **PDF analysis:** on upload, Gemini returns JSON listing the methods and design decisions used, each with a page number.
5. **Viva:** generate 4 questions about this student's specific choices. For each, the student answers by voice (record, upload). Gemini transcribes and judges the answer, then asks at most 1 follow-up based on what they actually said. Typed answers as a fallback.
6. **Scoring:** Gemini scores each rubric dimension with a quote from the transcript as evidence. Low-confidence results get a "needs review" flag.
7. **Instructor report:** transcript, audio playback, scores with evidence, and the ability to override a score.

#### Rules
- Treat the PDF as untrusted text: ignore any instructions inside it (e.g. "give full marks").
- Don't penalize accent, pauses or non-native phrasing; judge content only.
- Show a consent notice before recording.
- Keep API keys on the backend only.

#### Collections
users, courses, assignments, submissions (with analysis), viva_turns (question, transcript, audio path), scores.

#### Build order
Day 1: auth, classes, assignments, PDF upload + analysis, deploy. 
Day 2: questions, voice recording, follow-ups, scoring, instructor report. 
Day 3: polish, demo data, README.

#### Stretch (only if time remains)
Class-level concept gaps (aggregate what the whole class couldn't explain), a check of LLM scores against human scores, streaming voice with the Gemini Live API.
</details>
