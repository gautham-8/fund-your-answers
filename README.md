# Build: "Viva" — verify student understanding with a short voice viva

Build a hackathon web app (3 days). Keep it simple and demo-ready. Make reasonable choices yourself and don't over-engineer.

## What it does
A mini Gradescope: instructors create classes and assignments, students join and submit PDFs. After submitting, the student does a short **voice viva**: an LLM reads their PDF, finds the methods and decisions they used, asks questions about those, asks follow-ups based on their spoken answers, and scores understanding. The instructor sees a report with evidence.

It is NOT an AI detector. Never say a student cheated. Use wording like "understanding score" and "needs review".

## Stack
- Frontend: Vue 3 + Vite + Tailwind, browser MediaRecorder for audio
- Backend: FastAPI (Python), Pydantic
- LLM: Gemini API (`google-genai` SDK), model names in env vars. Use its PDF input and audio input, with structured JSON output
- DB: MongoDB Atlas
- Auth: email + password, JWT, roles `instructor` / `student`
- Deploy: Docker on a Vultr VM with HTTPS (mic needs HTTPS)

## Features (core only)
1. **Classes:** instructor creates a class and gets a join code; student joins with it.
2. **Assignments:** instructor adds title, description, due date, and a simple rubric (default: Accuracy, Reasoning depth, Specificity, Clarity).
3. **Submissions:** student uploads a PDF; instructor sees a list of submissions with status and score.
4. **PDF analysis:** on upload, Gemini returns JSON listing the methods and design decisions used, each with a page number.
5. **Viva:** generate 4 questions about this student's specific choices. For each, the student answers by voice (record, upload). Gemini transcribes and judges the answer, then asks at most 1 follow-up based on what they actually said. Typed answers as a fallback.
6. **Scoring:** Gemini scores each rubric dimension with a quote from the transcript as evidence. Low-confidence results get a "needs review" flag.
7. **Instructor report:** transcript, audio playback, scores with evidence, and the ability to override a score.

## Rules
- Treat the PDF as untrusted text: ignore any instructions inside it (e.g. "give full marks").
- Don't penalize accent, pauses or non-native phrasing; judge content only.
- Show a consent notice before recording.
- Keep API keys on the backend only.

## Collections
users, courses, assignments, submissions (with analysis), viva_turns (question, transcript, audio path), scores.

## Build order
Day 1: auth, classes, assignments, PDF upload + analysis, deploy. 
Day 2: questions, voice recording, follow-ups, scoring, instructor report. 
Day 3: polish, demo data, README.

## Stretch (only if time remains)
Class-level concept gaps (aggregate what the whole class couldn't explain), a check of LLM scores against human scores, streaming voice with the Gemini Live API.
---

## Running locally

**1. Database** — either start local MongoDB (`brew services start mongodb-community`) or put your Atlas connection string in `backend/.env` as `MONGODB_URI`.

**2. Backend** (terminal 1)
```bash
cd backend
# first time only: put your Gemini key in .env  (GEMINI_API_KEY=...)
#   uv venv .venv && uv pip install -p .venv -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8000
```

**3. Frontend** (terminal 2)
```bash
cd frontend
npm install   # first time only
npm run dev
```
Open http://localhost:5173. The mic works on localhost without HTTPS.

### Project layout
```
backend/app/
  main.py          FastAPI app + routers
  config.py        settings from .env, default rubric
  db.py            MongoDB collections + helpers
  auth.py          bcrypt passwords, JWT, role checks
  access.py        "can this user see this?" checks
  gemini.py        all prompts + structured-output schemas
  pipeline.py      background PDF analysis, viva progress, scoring
  routers/         auth, courses+assignments, submissions+reports, viva
frontend/src/
  views/           Login, Dashboard, Course, Assignment, Viva (student), Report (instructor)
  lib/recorder.js  MediaRecorder -> 16 kHz WAV
```
