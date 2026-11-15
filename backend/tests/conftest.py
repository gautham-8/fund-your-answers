"""Test setup: a throwaway database on a LOCAL MongoDB, with every Gemini call stubbed out.

Run from backend/:
    mongod --dbpath /tmp/viva-test-db --fork --logpath /tmp/viva-test-db.log   # if not already running
    .venv/bin/pip install -r requirements-dev.txt
    .venv/bin/pytest
"""

import os
import struct
import uuid

# Must be set before the app is imported (settings are read at import time).
TEST_URI = os.environ.get("TEST_MONGODB_URI", "mongodb://localhost:27017")
TEST_DB = f"viva_test_{uuid.uuid4().hex[:8]}"
os.environ["MONGODB_URI"] = TEST_URI
os.environ["MONGODB_DB"] = TEST_DB
os.environ["GEMINI_API_KEY"] = "test-not-used"
os.environ["JWT_SECRET"] = "test-secret-" + "x" * 32

import pymongo  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _mongo_available() -> bool:
    try:
        pymongo.MongoClient(TEST_URI, serverSelectionTimeoutMS=1500).admin.command("ping")
        return True
    except Exception:  # noqa: BLE001
        return False


if not _mongo_available():
    pytest.skip(f"No MongoDB at {TEST_URI}; start a local mongod to run the tests", allow_module_level=True)

from app import gemini  # noqa: E402
from app.main import app  # noqa: E402


class FakeGemini:
    """Deterministic stand-ins for the Gemini calls."""

    def __init__(self):
        self.eval_calls = []
        self.briefs = []

    async def extract_brief(self, pdf):
        return gemini.AssignmentBrief(title="HW 2", description="Sort things.", parts=[
            gemini.BriefPart(text="1.1 Implement quicksort", points=10), gemini.BriefPart(text="1.2 Analyse it", points=0),
            gemini.BriefPart(text="  ", points=5)],
                                      rubric=[gemini.RubricDraft(name="Pivot choice", description="Explains the pivot")])

    async def analyze_pdf(self, pdf, assignment, brief=None):
        self.briefs.append(brief)
        # A PDF containing "unrelated" fails the relevance check.
        on_topic = b"unrelated" not in pdf
        # Q1 on pages 1-2, Q2 not found, plus junk the server must drop (page 9 > page_count, part 7 doesn't exist)
        page_map = [gemini.PageMatch(part=1, pages=[2, 1, 9]), gemini.PageMatch(part=7, pages=[3])]
        return gemini.PdfAnalysis(summary="Uses quicksort.", embedded_instructions_detected=False, items=[
            gemini.AnalysisItem(kind="method", name="Quicksort", description="sorts", page=2, excerpt="we use quicksort", part=1)],
            on_topic=on_topic, relevance_note="This is about cooking, not sorting." if not on_topic else "Answers the task.",
            page_count=3, page_map=page_map if assignment.get("parts") else [])

    async def generate_questions(self, analysis, assignment, n):
        return gemini.QuestionSet(questions=[
            gemini.VivaQuestion(question=f"Q{i}?", target="Quicksort", page=2, part=1) for i in range(n)])

    async def evaluate_answer(self, **kw):
        self.eval_calls.append(kw)
        # Ask a follow-up only on the very first main answer of each viva
        first_main = not kw["is_followup"] and kw["question"] == "Q0?"
        return gemini.AnswerEvaluation(
            transcript=kw["typed_answer"] or "spoken answer about pivots", quality="partial", notes="ok",
            followup_question="Why that pivot?" if first_main else "")

    async def score_viva(self, assignment, rubric, analysis, turns):
        return gemini.VivaScore(summary="Solid.", dimensions=[
            gemini.DimensionScore(dimension=r["name"], score=4,
                                  evidence_quote="answer about pivots" if i else "made up quote",
                                  rationale="r", confidence=0.9 if i != 1 else 0.3)
            for i, r in enumerate(rubric)])

    async def class_concept_gaps(self, assignment, students):
        labels = list(students)
        return gemini.ClassInsights(overview="Mixed.", gaps=[gemini.ConceptGap(
            concept="Pivot choice", explanation="Vague.", students=labels + ["Student ZZ"],  # ZZ must be dropped
            example_quote="answer about pivots", teaching_suggestion="Demo sorted input.")])


@pytest.fixture(scope="session")
def fake_gemini():
    fake = FakeGemini()
    for name in ("extract_brief", "analyze_pdf", "generate_questions", "evaluate_answer", "score_viva", "class_concept_gaps"):
        setattr(gemini, name, getattr(fake, name))
    return fake


@pytest.fixture(scope="session")
def client(fake_gemini):
    with TestClient(app) as c:
        yield c
    pymongo.MongoClient(TEST_URI).drop_database(TEST_DB)


@pytest.fixture(scope="session")
def files_coll():
    return pymongo.MongoClient(TEST_URI)[TEST_DB]["files.files"]


def ok(r):
    assert r.status_code < 300, (r.status_code, r.text)
    return r.json()


def register(client, name, role):
    email = f"{name.lower()}-{uuid.uuid4().hex[:6]}@x.com"
    data = ok(client.post("/api/auth/register", json={"name": name, "email": email, "password": "secret1", "role": role}))
    return {"Authorization": f"Bearer {data['token']}"}, email


def wav(n: int = 16000) -> bytes:
    """One second of 16 kHz mono silence."""
    return (b"RIFF" + struct.pack("<I", 36 + n * 2) + b"WAVEfmt "
            + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
            + b"data" + struct.pack("<I", n * 2) + b"\0" * n * 2)
