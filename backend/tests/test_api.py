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


def allow_typing(client, sid, S, I):
    """Student asks for the typed-answer accommodation and the instructor approves it."""
    req = ok(client.post(f"/api/submissions/{sid}/accommodation", json={"reason": "Speech impairment"}, headers=S))
    ok(client.patch(f"/api/accommodations/{req['id']}", json={"status": "approved"}, headers=I))


def run_viva(client, asg, S, typed_by=None):
    """Answer every question by voice, or (with `typed_by` = the approving instructor) by typing after the first."""
    sid = ok(client.post(f"/api/assignments/{asg['id']}/submissions", files={"file": ("a.pdf", b"%PDF-1.4 fake")}, headers=S))["id"]
    mine = ok(client.get(f"/api/submissions/{sid}", headers=S))
    if mine["pages_pending"]:  # accept the AI's page matches as they are
        ok(client.put(f"/api/submissions/{sid}/pages", json={"pages": mine["page_map"]}, headers=S))
    if typed_by:
        allow_typing(client, sid, S, typed_by)
    ok(client.post(f"/api/submissions/{sid}/viva/consent", headers=S))
    st = ok(client.get(f"/api/submissions/{sid}/viva", headers=S))
    while st["current"]:
        cur = st["current"]
        data = {"question_index": cur["question_index"], "kind": cur["kind"]}
        if not typed_by or (cur["question_index"] == 0 and cur["kind"] == "main"):
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
    allow_typing(client, sid, S, I)
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


def test_page_matching_must_be_confirmed_before_viva(client):
    I, (S,), course, _ = make_class(client)
    asg = ok(client.post(f"/api/courses/{course['id']}/assignments",
                         json={"title": "HW", "parts": ["Prove it", "  ", "Code it"]}, headers=I))
    assert asg["parts"] == ["Prove it", "Code it"]
    sid = ok(client.post(f"/api/assignments/{asg['id']}/submissions", files={"file": ("a.pdf", b"%PDF-1.4")}, headers=S))["id"]

    mine = ok(client.get(f"/api/assignments/{asg['id']}", headers=S))["my_submission"]
    assert mine["page_map"] == [[1, 2], []] and mine["page_count"] == 3 and mine["pages_pending"]
    assert client.post(f"/api/submissions/{sid}/viva/consent", headers=S).status_code == 400

    url = f"/api/submissions/{sid}/pages"
    assert client.put(url, json={"pages": [[1]]}, headers=S).status_code == 400          # one list per question
    assert client.put(url, json={"pages": [[1], [4]]}, headers=S).status_code == 400     # past the last page
    assert client.put(url, json={"pages": [[1], [3]]}, headers=I).status_code == 403
    assert client.put(url, json={"pages": [[1], [3]], "order": [3, 1, 1]}, headers=S).status_code == 400  # not a permutation
    assert client.put(url, json={"pages": [[1], [3]], "rotation": [0, 90]}, headers=S).status_code == 400  # one per page
    assert client.put(url, json={"pages": [[1], [3]], "rotation": [0, 45, 0]}, headers=S).status_code == 422
    body = {"pages": [[2, 1, 2], [3]], "order": [3, 1, 2], "rotation": [0, 90, 0]}
    assert ok(client.put(url, json=body, headers=S))["page_map"] == [[1, 2], [3]]
    mine = ok(client.get(f"/api/submissions/{sid}", headers=S))
    assert mine["page_order"] == [3, 1, 2] and mine["page_rotation"] == [0, 90, 0]

    assert not ok(client.get(f"/api/submissions/{sid}/viva", headers=S))["pages_pending"]
    ok(client.post(f"/api/submissions/{sid}/viva/consent", headers=S))
    rep = ok(client.get(f"/api/submissions/{sid}", headers=I))
    assert rep["parts"] == ["Prove it", "Code it"] and rep["page_map"] == [[1, 2], [3]] and rep["pages_confirmed_at"]


# ---------- class insights ----------

def test_class_insights(client):
    I, students, _, asg = make_class(client, n_students=3)
    url = f"/api/assignments/{asg['id']}/insights"

    assert ok(client.get(url, headers=I))["completed"] == 0
    s0 = run_viva(client, asg, students[0])
    assert client.post(url + "/concept-gaps", headers=I).status_code == 400  # needs >= 2
    run_viva(client, asg, students[1], typed_by=I)

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


# ---------- course metadata, schedule, grades & regrades ----------

def _iso(**delta):
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


def test_course_code_term_counts_and_unenroll(client):
    I, _ = register(client, "Prof", "instructor")
    course = ok(client.post("/api/courses", json={"name": "Neural Networks", "code": "CS 682", "term": "Fall 2026"}, headers=I))
    assert course["code"] == "CS 682" and course["term"] == "Fall 2026" and course["instructor_name"] == "Prof"
    default = ok(client.post("/api/courses", json={"name": "No term"}, headers=I))
    assert default["term"].split()[0] in ("Spring", "Summer", "Fall")
    ok(client.patch(f"/api/courses/{course['id']}", json={"code": "COMPSCI 682"}, headers=I))

    S, _ = register(client, "Stu", "student")
    ok(client.post("/api/courses/join", json={"code": course["join_code"]}, headers=S))
    ok(client.post(f"/api/courses/{course['id']}/assignments", json={"title": "A1", "due_date": _iso(days=3)}, headers=I))
    ok(client.post(f"/api/courses/{course['id']}/assignments", json={"title": "Hidden", "release_date": _iso(days=1)}, headers=I))

    mine = ok(client.get("/api/courses", headers=S))
    assert mine[0]["code"] == "COMPSCI 682" and mine[0]["assignment_count"] == 1 and mine[0]["todo_count"] == 1
    assert mine[0]["instructor_name"] == "Prof"
    assert ok(client.get("/api/courses", headers=I))[1]["assignment_count"] == 2
    assert [u["title"] for u in ok(client.get("/api/upcoming", headers=S))] == ["A1"]

    assert client.delete(f"/api/courses/{course['id']}/enrollment", headers=S).status_code == 204
    assert ok(client.get("/api/courses", headers=S)) == []
    assert client.get(f"/api/courses/{course['id']}", headers=S).status_code == 404


def test_release_and_late_due_dates(client):
    I, (S,), course, _ = make_class(client)
    cid = course["id"]
    bad = client.post(f"/api/courses/{cid}/assignments", json={"title": "x", "due_date": _iso(days=1), "late_due_date": _iso(hours=1)}, headers=I)
    assert bad.status_code == 400

    hidden = ok(client.post(f"/api/courses/{cid}/assignments", json={"title": "Later", "release_date": _iso(days=1)}, headers=I))
    assert "Later" not in [a["title"] for a in ok(client.get(f"/api/courses/{cid}", headers=S))["assignments"]]
    assert client.get(f"/api/assignments/{hidden['id']}", headers=S).status_code == 404
    assert client.post(f"/api/assignments/{hidden['id']}/submissions", files={"file": ("a.pdf", b"%PDF-1.4")}, headers=S).status_code == 404
    ok(client.patch(f"/api/assignments/{hidden['id']}", json={"release_date": None}, headers=I))
    assert ok(client.get(f"/api/assignments/{hidden['id']}", headers=S))["released"]

    late = ok(client.post(f"/api/courses/{cid}/assignments", json={"title": "Late ok", "due_date": _iso(hours=-1), "late_due_date": _iso(days=1)}, headers=I))
    sub = ok(client.post(f"/api/assignments/{late['id']}/submissions", files={"file": ("a.pdf", b"%PDF-1.4")}, headers=S))
    view = ok(client.get(f"/api/assignments/{late['id']}", headers=S))
    assert view["my_submission"]["id"] == sub["id"] and view["my_submission"]["late"]

    ok(client.patch(f"/api/assignments/{late['id']}", json={"late_due_date": _iso(hours=-1, minutes=30)}, headers=I))
    r = client.post(f"/api/assignments/{late['id']}/submissions", files={"file": ("a.pdf", b"%PDF-1.4")}, headers=S)
    assert r.status_code == 400 and "late due date" in r.json()["detail"]


def test_publish_grades_and_regrade_requests(client):
    I, (S, S2), course, asg = make_class(client, n_students=2)
    sid = run_viva(client, asg, S)

    inst = ok(client.get(f"/api/assignments/{asg['id']}", headers=I))
    assert [m["name"] for m in inst["missing"]] == ["Stu1"]

    # Unpublished: no scores for the student, no regrades
    assert ok(client.get(f"/api/assignments/{asg['id']}", headers=S))["my_results"] is None
    assert client.post(f"/api/submissions/{sid}/regrade-requests", json={"dimension_index": 0, "message": "pls"}, headers=S).status_code == 400

    ok(client.patch(f"/api/assignments/{asg['id']}", json={"grades_published": True}, headers=I))
    res = ok(client.get(f"/api/assignments/{asg['id']}", headers=S))["my_results"]
    # Published but not yet marked by a grader: viva only, no final grade
    assert res["overall"] is None and res["viva"] == 80.0 and res["viva_weight"] == 0.3 and res["max_points"] == 100
    assert res["dimensions"][0]["score"] == 4 and res["dimensions"][0]["max"] == 5 and "confidence" not in res["dimensions"][0]
    assert ok(client.get(f"/api/courses/{course['id']}", headers=S))["assignments"][0]["my_score"] is None

    # Final = 70% x grader + 30% x viva. 90 x 0.7 + 80 x 0.3 = 87
    assert client.put(f"/api/submissions/{sid}/grade", json={"points": 101}, headers=I).status_code == 400
    assert client.put(f"/api/submissions/{sid}/grade", json={"points": 90}, headers=S).status_code == 403
    g = ok(client.put(f"/api/submissions/{sid}/grade", json={"points": 90, "note": "Good proof"}, headers=I))
    assert g["final"] == 87.0 and g["graded_by"] == "Prof"
    res = ok(client.get(f"/api/assignments/{asg['id']}", headers=S))["my_results"]
    assert res["overall"] == 87.0 and res["grader_points"] == 90 and res["grader_note"] == "Good proof"
    assert ok(client.get(f"/api/courses/{course['id']}", headers=S))["assignments"][0]["my_score"] == 87.0
    # The instructor can change the weighting and the points scale later
    ok(client.patch(f"/api/assignments/{asg['id']}", json={"viva_weight": 0.5, "max_points": 200}, headers=I))
    assert ok(client.get(f"/api/submissions/{sid}", headers=I))["final"] == 62.5  # 45% x 0.5 + 80% x 0.5
    ok(client.patch(f"/api/assignments/{asg['id']}", json={"viva_weight": 0.3, "max_points": 100}, headers=I))
    assert client.patch(f"/api/assignments/{asg['id']}", json={"viva_weight": 1.5}, headers=I).status_code == 422

    rr = ok(client.post(f"/api/submissions/{sid}/regrade-requests", json={"dimension_index": 0, "message": "I explained it"}, headers=S))
    assert rr["status"] == "open" and rr["score_before"] == 4
    dup = client.post(f"/api/submissions/{sid}/regrade-requests", json={"dimension_index": 0, "message": "again"}, headers=S)
    assert dup.status_code == 409
    assert client.post(f"/api/submissions/{sid}/regrade-requests", json={"dimension_index": 0, "message": "x"}, headers=S2).status_code == 404

    lst = ok(client.get(f"/api/courses/{course['id']}/regrade-requests", headers=I))
    assert lst[0]["student"]["name"] == "Stu0" and lst[0]["assignment"]["title"] == "Sorting"
    assert ok(client.get(f"/api/courses/{course['id']}/regrade-requests", headers=S2)) == []
    assert ok(client.get("/api/courses", headers=I))[0]["open_regrades"] == 1

    assert client.patch(f"/api/regrade-requests/{rr['id']}", json={"override_score": 5}, headers=S).status_code == 403
    done = ok(client.patch(f"/api/regrade-requests/{rr['id']}", json={"override_score": 5, "response": "Fair point"}, headers=I))
    assert done["status"] == "resolved" and done["score_after"] == 5 and done["resolved_by"] == "Prof"
    res = ok(client.get(f"/api/submissions/{sid}", headers=S))["results"]
    assert res["viva"] == 85.0 and res["overall"] == 88.5 and res["dimensions"][0]["adjusted"] and res["dimensions"][0]["instructor_note"] == "Fair point"
    assert client.delete(f"/api/regrade-requests/{rr['id']}", headers=S).status_code == 400  # already resolved

    rr2 = ok(client.post(f"/api/submissions/{sid}/regrade-requests", json={"dimension_index": 1, "message": "hm"}, headers=S))
    assert client.delete(f"/api/regrade-requests/{rr2['id']}", headers=S).status_code == 204


def test_course_concept_gaps_rank_what_to_revisit(client):
    I, students, course, a1 = make_class(client, n_students=3)
    a2 = ok(client.post(f"/api/courses/{course['id']}/assignments", json={"title": "Graphs"}, headers=I))
    url = f"/api/courses/{course['id']}/concept-gaps"
    assert client.get(url, headers=students[0]).status_code == 403

    for S in students:
        run_viva(client, a1, S)
    run_viva(client, a2, students[0])  # only 1 viva: too few to analyse

    rep = ok(client.get(url, headers=I))
    assert rep["gaps"] == []
    by_title = {a["title"]: a for a in rep["assignments"]}
    assert by_title["Sorting"]["stale"] and by_title["Sorting"]["completed"] == 3
    assert not by_title["Graphs"]["stale"]

    rep = ok(client.post(url, headers=I))
    assert rep["failed"] == []
    assert [(g["concept"], g["share"], g["assignment"]["title"]) for g in rep["gaps"]] == [
        ("Pivot choice", 1.0, "Sorting"), ("Stability", 0.33, "Sorting")]
    assert not {a["title"]: a for a in rep["assignments"]}["Sorting"]["stale"]
    assert "students" not in rep["gaps"][0]  # no per-student labels in the course view


def test_typed_answers_need_an_approved_accommodation(client):
    I, (S,), course, asg = make_class(client)
    sid = ok(client.post(f"/api/assignments/{asg['id']}/submissions", files={"file": ("a.pdf", b"%PDF-1.4 fake")}, headers=S))["id"]
    url = f"/api/submissions/{sid}/accommodation"
    typed = {"question_index": 0, "kind": "main", "text": "typed answer"}

    # Voice by default: typing is refused without a request
    ok(client.post(f"/api/submissions/{sid}/viva/consent", headers=S))
    assert client.post(f"/api/submissions/{sid}/viva/answer", data=typed, headers=S).status_code == 403

    # A pending request blocks starting the viva until it's decided or withdrawn
    req = ok(client.post(url, json={"reason": "Stammer; on file with disability services"}, headers=S))
    assert req["status"] == "pending"
    assert client.post(f"/api/submissions/{sid}/viva/consent", headers=S).status_code == 400
    assert ok(client.get(f"/api/courses/{course['id']}", headers=I))["pending_accommodations"] == 1
    listed = ok(client.get(f"/api/courses/{course['id']}/accommodations", headers=I))
    assert listed[0]["student"]["name"] == "Stu0" and listed[0]["assignment"]["title"] == "Sorting"
    assert client.get(f"/api/courses/{course['id']}/accommodations", headers=S).status_code == 403
    assert client.patch(f"/api/accommodations/{req['id']}", json={"status": "approved"}, headers=S).status_code == 403

    # Denied: still voice only; the student may ask again before starting
    ok(client.patch(f"/api/accommodations/{req['id']}", json={"status": "denied", "response": "Please bring the DSS letter"}, headers=I))
    st = ok(client.get(f"/api/submissions/{sid}/viva", headers=S))
    assert st["accommodation"]["status"] == "denied" and st["accommodation"]["response"] == "Please bring the DSS letter"
    assert client.post(f"/api/submissions/{sid}/viva/answer", data=typed, headers=S).status_code == 403
    assert client.delete(url, headers=S).status_code == 400  # only pending can be withdrawn
    req = ok(client.post(url, json={"reason": "Letter attached via email"}, headers=S))
    assert req["status"] == "pending"
    ok(client.patch(f"/api/accommodations/{req['id']}", json={"status": "approved"}, headers=I))

    # Approved: typed answers accepted
    st = ok(client.post(f"/api/submissions/{sid}/viva/answer", data=typed, headers=S))
    assert st["answered_questions"] == 1 and st["accommodation"]["status"] == "approved"

    # Too late to ask once the viva has started
    _, (S2,), _, asg2 = make_class(client)
    sid2 = run_viva(client, asg2, S2)
    assert client.post(f"/api/submissions/{sid2}/accommodation", json={"reason": "x"}, headers=S2).status_code == 400


def test_withdrawing_a_pending_accommodation_unblocks_voice(client):
    I, (S,), _, asg = make_class(client)
    sid = ok(client.post(f"/api/assignments/{asg['id']}/submissions", files={"file": ("a.pdf", b"%PDF-1.4 fake")}, headers=S))["id"]
    ok(client.post(f"/api/submissions/{sid}/accommodation", json={"reason": "RSI"}, headers=S))
    assert client.delete(f"/api/submissions/{sid}/accommodation", headers=S).status_code == 204
    ok(client.post(f"/api/submissions/{sid}/viva/consent", headers=S))
    assert ok(client.get(f"/api/submissions/{sid}/viva", headers=S))["accommodation"] is None


# ---------- relevance check, handouts, 0-5 scale ----------

def test_off_topic_pdf_blocks_viva_until_reupload_or_override(client, fake_gemini):
    I, (S,), course, _ = make_class(client)
    asg = ok(client.post(f"/api/courses/{course['id']}/assignments", json={"title": "HW", "parts": ["Sort a list"]}, headers=I))
    sid = ok(client.post(f"/api/assignments/{asg['id']}/submissions", files={"file": ("a.pdf", b"%PDF-1.4 unrelated")}, headers=S))["id"]

    st = ok(client.get(f"/api/submissions/{sid}/viva", headers=S))
    assert st["status"] == "off_topic" and st["total_questions"] == 0 and "cooking" in st["relevance_note"]
    assert client.post(f"/api/submissions/{sid}/viva/answer", data={"question_index": 0, "kind": "main", "text": "x"}, headers=S).status_code == 400
    assert ok(client.get(f"/api/courses/{course['id']}", headers=I))["assignments"][0]["off_topic_count"] == 1

    # The student can re-upload; a relevant PDF goes straight to the viva
    ok(client.post(f"/api/assignments/{asg['id']}/submissions", files={"file": ("b.pdf", b"%PDF-1.4 sorting")}, headers=S))
    assert ok(client.get(f"/api/submissions/{sid}/viva", headers=S))["status"] == "ready"

    # ...or the instructor overrules the check
    ok(client.post(f"/api/assignments/{asg['id']}/submissions", files={"file": ("c.pdf", b"%PDF-1.4 unrelated")}, headers=S))
    assert client.post(f"/api/submissions/{sid}/allow", headers=S).status_code == 403
    ok(client.post(f"/api/submissions/{sid}/allow", headers=I))
    rep = ok(client.get(f"/api/submissions/{sid}", headers=I))
    assert rep["status"] == "ready" and len(rep["questions"]) == 4 and rep["relevance_override_by"] == "Prof"
    assert client.post(f"/api/submissions/{sid}/allow", headers=I).status_code == 400  # not off topic any more


def test_assignment_handout_extract_and_attach(client, fake_gemini):
    I, (S,), course, _ = make_class(client)
    assert client.post("/api/assignments/brief/extract", files={"file": ("h.pdf", b"%PDF-1.4")}, headers=S).status_code == 403
    draft = ok(client.post("/api/assignments/brief/extract", files={"file": ("h.pdf", b"%PDF-1.4 handout")}, headers=I))
    assert draft["parts"] == ["1.1 Implement quicksort", "1.2 Analyse it"] and draft["rubric"][0]["name"] == "Pivot choice"
    assert draft["part_points"] == [10, None]  # None = the handout didn't say

    asg = ok(client.post(f"/api/courses/{course['id']}/assignments",
                         json={"title": draft["title"], "parts": draft["parts"], "rubric": draft["rubric"]}, headers=I))
    ok(client.put(f"/api/assignments/{asg['id']}/brief", files={"file": ("h.pdf", b"%PDF-1.4 handout")}, headers=I))
    view = ok(client.get(f"/api/assignments/{asg['id']}", headers=S))
    assert view["has_brief"] and view["brief_filename"] == "h.pdf" and "brief_file_id" not in view
    assert client.get(f"/api/assignments/{asg['id']}/brief", headers=S).content == b"%PDF-1.4 handout"

    # The handout goes to the AI together with each submission
    ok(client.post(f"/api/assignments/{asg['id']}/submissions", files={"file": ("a.pdf", b"%PDF-1.4 sorting")}, headers=S))
    assert fake_gemini.briefs[-1] == b"%PDF-1.4 handout"


def test_zero_is_a_valid_score(client):
    I, (S,), _, asg = make_class(client)
    sid = run_viva(client, asg, S)
    r = ok(client.patch(f"/api/submissions/{sid}/scores/0", json={"override_score": 0, "override_note": "said I don't know"}, headers=I))
    assert r["dimensions"][0]["override_score"] == 0 and r["overall"] == 60.0  # (0+4+4+4) / 20
    assert client.patch(f"/api/submissions/{sid}/scores/0", json={"override_score": 6}, headers=I).status_code == 422


def test_question_points_and_per_question_grading(client):
    I, (S,), course, _ = make_class(client)
    url = f"/api/courses/{course['id']}/assignments"
    assert client.post(url, json={"title": "HW", "parts": ["A", "B"], "part_points": [10]}, headers=I).status_code == 400
    assert client.post(url, json={"title": "HW", "parts": ["A", "B"], "part_points": [10, 0]}, headers=I).status_code == 400
    # A blank question is dropped together with its points
    asg = ok(client.post(url, json={"title": "HW", "parts": ["A", " ", "B"], "part_points": [30, 5, 20]}, headers=I))
    assert asg["parts"] == ["A", "B"] and asg["part_points"] == [30, 20] and asg["max_points"] == 50
    # Without points, max_points is split evenly
    even = ok(client.post(url, json={"title": "HW2", "parts": ["A", "B"], "max_points": 40}, headers=I))
    assert even["part_points"] == [20, 20] and even["max_points"] == 40

    sid = run_viva(client, asg, S)
    ok(client.patch(f"/api/assignments/{asg['id']}", json={"grades_published": True}, headers=I))
    gurl = f"/api/submissions/{sid}/question-grades"
    assert client.put(f"/api/submissions/{sid}/grade", json={"points": 40}, headers=I).status_code == 400  # per question now
    assert client.put(gurl, json={"questions": [{"points": 1}]}, headers=I).status_code == 400            # one per question
    assert client.put(gurl, json={"questions": [{"points": 31}, {"points": 1}]}, headers=I).status_code == 400  # over Q1's 30
    assert client.put(gurl, json={"questions": [{"points": 1}, {"points": 1}]}, headers=S).status_code == 403

    # Partly graded: no grader mark or final grade yet, and the student sees nothing
    g = ok(client.put(gurl, json={"questions": [{"points": 25, "comment": "Missing base case"}, {"points": None}]}, headers=I))
    assert g["grader_points"] is None and g["final"] is None
    rep = ok(client.get(f"/api/submissions/{sid}", headers=I))
    assert rep["question_grades"][0] == {"points": 25, "comment": "Missing base case"} and rep["questions_graded"] == 1
    assert ok(client.get(f"/api/submissions/{sid}", headers=S))["results"]["question_grades"] is None

    # Fully graded: points add up. 45/50 = 90% -> 0.7 x 90 + 0.3 x 80 = 87
    g = ok(client.put(gurl, json={"questions": [{"points": 25, "comment": "Missing base case"}, {"points": 20}], "note": "Nice"}, headers=I))
    assert g["grader_points"] == 45 and g["final"] == 87.0
    stu = ok(client.get(f"/api/submissions/{sid}", headers=S))
    assert stu["results"]["question_grades"][0]["comment"] == "Missing base case" and stu["results"]["part_points"] == [30, 20]
    assert stu["page_map"] == [[1, 2], []] and "page_order" in stu

    # Question points can change after creation (the questions themselves can't)
    assert client.patch(f"/api/assignments/{asg['id']}", json={"part_points": [10]}, headers=I).status_code == 400
    out = ok(client.patch(f"/api/assignments/{asg['id']}", json={"part_points": [25, 25]}, headers=I))
    assert out["max_points"] == 50 and out["part_points"] == [25, 25]
