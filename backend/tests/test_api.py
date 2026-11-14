from datetime import datetime, timedelta, timezone

from app import audio as audio_codec
from conftest import ok, register, wav


def make_class(client, n_students=1):
    I, _ = register(client, "Prof", "instructor")
    course = ok(client.post("/api/courses", json={"name": "CS101"}, headers=I))
    students = []
    for i in range(n_students):
        S, email = register(client, f"Stu{i}", "student")
        ok(client.post("/api/courses/join", json={"code": course["join_code"].lower()}, headers=S))
        students.append(S)
    asg = ok(client.post(f"/api/courses/{course['id']}/assignments", json={"title": "Sorting", "description": "Sort"}, headers=I))
    return I, students, course, asg


def run_viva(client, asg, S, voice_first=True):
    sid = ok(client.post(f"/api/assignments/{asg['id']}/submissions", files={"file": ("a.pdf", b"%PDF-1.4 fake")}, headers=S))["id"]
    ok(client.post(f"/api/submissions/{sid}/viva/consent", headers=S))
    st = ok(client.get(f"/api/submissions/{sid}/viva", headers=S))
    while st["current"]:
        cur = st["current"]
        data = {"question_index": cur["question_index"], "kind": cur["kind"]}
        if voice_first and cur["question_index"] == 0 and cur["kind"] == "main":
            st = ok(client.post(f"/api/submissions/{sid}/viva/answer", data=data, files={"audio": ("a.wav", wav(), "audio/wav")}, headers=S))
        else:
            st = ok(client.post(f"/api/submissions/{sid}/viva/answer", data={**data, "text": f"answer about pivots {cur['question_index']}"}, headers=S))
    return sid


# ---------- auth ----------

def test_register_login_and_duplicates(client):
    _, email = register(client, "Sam", "student")
    assert client.post("/api/auth/register", json={"name": "Sam", "email": email, "password": "secret1", "role": "student"}).status_code == 409
    assert client.post("/api/auth/login", json={"email": email, "password": "wrong!!"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": email, "password": "secret1"}).status_code == 200


def test_login_lockout_after_repeated_failures(client):
    _, email = register(client, "Locky", "student")
    for _ in range(5):
        assert client.post("/api/auth/login", json={"email": email, "password": "nope123"}).status_code == 401
    r = client.post("/api/auth/login", json={"email": email, "password": "secret1"})
    assert r.status_code == 429 and "Too many" in r.json()["detail"]  # locked even with the right password


# ---------- classes ----------

def test_roles_membership_and_roster(client):
    I, (S,), course, _ = make_class(client)
    assert client.post("/api/courses", json={"name": "x"}, headers=S).status_code == 403
    outsider, _ = register(client, "Out", "student")
    assert client.get(f"/api/courses/{course['id']}", headers=outsider).status_code == 404

    inst_view = ok(client.get(f"/api/courses/{course['id']}", headers=I))
    assert [s["name"] for s in inst_view["students"]] == ["Stu0"]
    stu_view = ok(client.get(f"/api/courses/{course['id']}", headers=S))
    assert "students" not in stu_view and "join_code" not in stu_view


def test_submissions_closed_after_due_date(client):
    I, (S,), course, _ = make_class(client)
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    asg = ok(client.post(f"/api/courses/{course['id']}/assignments", json={"title": "Late", "due_date": past}, headers=I))
    r = client.post(f"/api/assignments/{asg['id']}/submissions", files={"file": ("a.pdf", b"%PDF-1.4")}, headers=S)
    assert r.status_code == 400 and "due date" in r.json()["detail"]


# ---------- full viva flow ----------

def test_full_viva_flow(client, fake_gemini, files_coll):
    I, (S,), _, asg = make_class(client)
    assert client.post(f"/api/assignments/{asg['id']}/submissions", files={"file": ("a.pdf", b"not pdf")}, headers=S).status_code == 400

    # Replacing a PDF before the viva removes the old file from GridFS
    first = ok(client.post(f"/api/assignments/{asg['id']}/submissions", files={"file": ("old.pdf", b"%PDF-1.4 old")}, headers=S))
    sid = ok(client.post(f"/api/assignments/{asg['id']}/submissions", files={"file": ("a.pdf", b"%PDF-1.4 fake")}, headers=S))["id"]
    assert first["id"] == sid
    from bson import ObjectId
    assert files_coll.count_documents({"metadata.kind": "submission_pdf", "metadata.submission_id": ObjectId(sid)}) == 1

    st = ok(client.get(f"/api/submissions/{sid}/viva", headers=S))
    assert st["status"] == "ready" and st["total_questions"] == 4
    no_consent = client.post(f"/api/submissions/{sid}/viva/answer", data={"question_index": 0, "kind": "main", "text": "x"}, headers=S)
    assert no_consent.status_code == 400
    ok(client.post(f"/api/submissions/{sid}/viva/consent", headers=S))

    st = ok(client.post(f"/api/submissions/{sid}/viva/answer", data={"question_index": 0, "kind": "main"},
                        files={"audio": ("a.wav", wav(), "audio/wav")}, headers=S))
    assert st["current"] == {"question_index": 0, "kind": "followup", "question": "Why that pivot?"}
    wrong = client.post(f"/api/submissions/{sid}/viva/answer", data={"question_index": 1, "kind": "main", "text": "x"}, headers=S)
    assert wrong.status_code == 409
    st = ok(client.post(f"/api/submissions/{sid}/viva/answer", data={"question_index": 0, "kind": "followup", "text": "median of three, answer about pivots"}, headers=S))
    assert "Original question" in fake_gemini.eval_calls[-1]["context"]
    for i in (1, 2, 3):
        assert st["current"]["question_index"] == i and st["current"]["kind"] == "main"
        st = ok(client.post(f"/api/submissions/{sid}/viva/answer", data={"question_index": i, "kind": "main", "text": f"answer about pivots {i}"}, headers=S))
    assert st["current"] is None

    # Students see progress only
    stud_view = ok(client.get(f"/api/submissions/{sid}", headers=S))
    assert "overall" not in stud_view and "turns" not in stud_view

    rep = ok(client.get(f"/api/submissions/{sid}", headers=I))
    assert rep["status"] == "completed"
    dims = rep["score"]["dimensions"]
    assert not dims[0]["quote_verified"] and dims[0]["needs_review"]      # made-up quote
    assert dims[1]["needs_review"]                                         # low confidence
    assert dims[2]["quote_verified"] and not dims[2]["needs_review"]
    assert rep["needs_review"] and rep["score"]["overall"] == 80.0
    assert len(rep["turns"]) == 5 and rep["turns"][0]["has_audio"] and rep["turns"][1]["kind"] == "followup"

    # Files come back from GridFS; audio is compressed to MP3 when ffmpeg is present
    a = client.get(f"/api/turns/{rep['turns'][0]['id']}/audio", headers=I)
    assert a.status_code == 200
    if audio_codec.FFMPEG:
        assert a.headers["content-type"] == "audio/mpeg" and len(a.content) < len(wav()) / 4
    else:
        assert a.content == wav() and a.headers["content-type"] == "audio/wav"
    pdf = client.get(f"/api/submissions/{sid}/pdf", headers=I)
    assert pdf.content == b"%PDF-1.4 fake" and pdf.headers["content-type"] == "application/pdf"

    other, _ = register(client, "Eve", "student")
    assert client.get(f"/api/turns/{rep['turns'][0]['id']}/audio", headers=other).status_code == 404
    assert client.get(f"/api/submissions/{sid}/pdf", headers=other).status_code == 404

    # Overrides
    r = ok(client.patch(f"/api/submissions/{sid}/scores/0", json={"override_score": 2, "override_note": "weak"}, headers=I))
    assert r["overall"] == 70.0 and r["needs_review"]
    r = ok(client.patch(f"/api/submissions/{sid}/scores/1", json={"override_score": 5}, headers=I))
    assert r["needs_review"] is False and r["overall"] == 75.0
    assert client.patch(f"/api/submissions/{sid}/scores/0", json={"override_score": 2}, headers=S).status_code == 403

    lst = ok(client.get(f"/api/assignments/{asg['id']}", headers=I))
    assert lst["submissions"][0]["overall"] == 75.0 and lst["submissions"][0]["student"]["name"] == "Stu0"
    # Can't replace the PDF once the viva has started
    assert client.post(f"/api/assignments/{asg['id']}/submissions", files={"file": ("a.pdf", b"%PDF-1.4")}, headers=S).status_code == 409


# ---------- class insights ----------

def test_class_insights(client):
    I, students, _, asg = make_class(client, n_students=3)
    url = f"/api/assignments/{asg['id']}/insights"

    assert ok(client.get(url, headers=I))["completed"] == 0
    s0 = run_viva(client, asg, students[0])
    assert client.post(url + "/concept-gaps", headers=I).status_code == 400  # needs >= 2
    run_viva(client, asg, students[1], voice_first=False)

    ok(client.patch(f"/api/submissions/{s0}/scores/0", json={"override_score": 5}, headers=I))  # AI 4 -> 5
    ok(client.patch(f"/api/submissions/{s0}/scores/3", json={"override_score": 1}, headers=I))  # AI 4 -> 1

    data = ok(client.get(url, headers=I))
    assert data["completed"] == 2
    acc = next(r for r in data["rubric"] if r["dimension"] == "Accuracy")
    assert acc["avg_ai"] == 4 and acc["avg_final"] == 4.5 and acc["overrides"] == 1 and acc["avg_adjustment"] == 1
    ag = data["agreement"]
    assert ag["scored_dimensions"] == 8 and ag["overridden"] == 2
    assert ag["within_one"] == 0.5 and ag["mean_abs_difference"] == 2 and ag["untouched_rate"] == 0.75

    gaps = ok(client.post(url + "/concept-gaps", headers=I))
    assert gaps["based_on"] == 2
    assert gaps["gaps"][0]["students"] == ["Student A", "Student B"]  # unknown label dropped
    assert gaps["gaps"][0]["student_count"] == 2
    assert ok(client.get(url, headers=I))["concept_gaps"]["overview"] == "Mixed."

    assert client.get(url, headers=students[0]).status_code == 403  # students can't see insights
