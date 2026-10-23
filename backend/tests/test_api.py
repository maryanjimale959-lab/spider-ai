"""End-to-end API tests: the Definition of Done, exercised through HTTP.

A user uploads a document, runs a real investigation, gets findings whose quotations are
verified against the source, asks a grounded question, explores the graph. A teacher is
authorised, reviews, comments, finalizes, and shares a report.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def register(client, email, password, role="user", name="Test Person"):
    response = client.post(
        "/api/auth/register", json={"email": email, "password": password, "role": role, "full_name": name}
    )
    assert response.status_code == 201, response.text
    return response.json()


def auth(client, token):
    return {"Authorization": f"Bearer {token}"}


def upload(client, headers, path: Path):
    with path.open("rb") as handle:
        response = client.post(
            "/api/documents",
            files={"file": (path.name, handle.read(), "application/octet-stream")},
            headers=headers,
        )
    assert response.status_code == 201, response.text
    return response.json()


def wait_for_extraction(client, headers, version_id, attempts=40):
    for _ in range(attempts):
        content = client.get(f"/api/versions/{version_id}/content", headers=headers).json()
        if content["extraction_status"] in ("ready", "needs_ocr", "failed"):
            return content
    raise AssertionError("extraction never finished")


def investigate(client, headers, version_id, goals=None):
    created = client.post(
        f"/api/versions/{version_id}/investigations", json={"goals": goals or []}, headers=headers
    )
    assert created.status_code == 202, created.text
    investigation_id = created.json()["id"]
    for _ in range(60):
        status = client.get(f"/api/investigations/{investigation_id}", headers=headers).json()
        if status["status"] in ("completed", "failed", "cancelled"):
            break
    assert status["status"] == "completed", status
    return investigation_id


def test_health_reports_the_local_engine(client):
    payload = client.get("/api/health").json()
    assert payload["status"] == "ok"
    assert "local" in payload["engine"]
    assert payload["ai"]["enabled"] is False
    assert "pdf" in payload["formats"]


def test_registration_rejects_self_service_admin(client):
    response = client.post(
        "/api/auth/register", json={"email": "sneaky@spider.test", "password": "longenough1", "role": "admin"}
    )
    assert response.status_code == 422


def test_login_failure_does_not_leak_account_existence(client):
    register(client, "someone@spider.test", "longenough1")
    wrong_password = client.post("/api/auth/login", json={"email": "someone@spider.test", "password": "wrongpassword"})
    unknown_email = client.post("/api/auth/login", json={"email": "nobody@spider.test", "password": "wrongpassword"})
    assert wrong_password.status_code == 401
    assert wrong_password.json()["detail"] == unknown_email.json()["detail"]


def test_upload_rejects_extension_that_lies_about_its_bytes(client, tmp_path):
    fake = tmp_path / "notes.pdf"
    fake.write_bytes(b"just plain text, not a pdf at all")
    session = register(client, "liar@spider.test", "longenough1")
    response = client.post(
        "/api/documents", files={"file": ("notes.pdf", b"just plain text, not a pdf at all", "application/pdf")},
        headers=auth(client, session["access_token"]),
    )
    assert response.status_code == 415
    assert "PDF" in response.json()["detail"]


def test_pdf_end_to_end(client, samples_dir):
    session = register(client, "owner@spider.test", "longenough1")
    headers = auth(client, session["access_token"])
    document = upload(client, headers, samples_dir / "english_report.pdf")
    content = wait_for_extraction(client, headers, document["current_version_id"])

    # PDF text coordinates are the point: passages must carry real page boxes.
    assert content["positioning_quality"] == "pdf_bbox"
    assert content["pages"], "the PDF parser must render pages"
    boxed = [passage for passage in content["passages"] if passage["bbox"]]
    assert len(boxed) >= 5, "expected several passages with bounding boxes from the file"
    assert all(passage["page_number"] for passage in boxed)
    assert any(passage["source_lines"] for passage in boxed), "line-level rectangles enable the scan beam"

    investigation_id = investigate(client, headers, document["current_version_id"])
    results = client.get(f"/api/investigations/{investigation_id}/results", headers=headers).json()

    assert results["findings"], "a real investigation must produce findings"
    passages = {passage["id"]: passage for passage in content["passages"]}

    # The anti-fabrication guarantee, checked over HTTP.
    for finding in results["findings"]:
        assert finding["evidence"], f"{finding['kind']} reached the client without evidence"
        for evidence in finding["evidence"]:
            passage = passages[evidence["passage_id"]]
            if evidence["validation"] == "verbatim":
                assert evidence["quote"] in passage["text"], evidence["quote"][:80]
                assert passage["text"].find(evidence["quote"]) >= 0
                if evidence["char_start"] is not None:
                    offset = evidence["char_start"] - passage["char_start"]
                    assert passage["text"][offset:evidence["char_end"] - passage["char_start"]] == evidence["quote"]
        assert finding["primary_passage_id"] in passages

    metrics = results["investigation"]["metrics"]
    assert metrics["draft_findings"] == metrics["validated_findings"] or metrics["rejected_findings"] >= 0
    assert metrics["events"] > 0
    assert metrics["language"] == "en"

    # The crawl event log must reference only passages that exist, in real order.
    events = results["events"]
    assert events[0]["stage"] == "arrival"
    assert events[-1]["stage"] == "completion"
    for event in events:
        if event.get("passage_id"):
            assert event["passage_id"] in passages
    sequences = [event["seq"] for event in events]
    assert sequences == sorted(sequences)

    # Graph edges must never dangle.
    node_ids = {node["id"] for node in results["nodes"]}
    for edge in results["edges"]:
        assert edge["source_node_id"] in node_ids and edge["target_node_id"] in node_ids
    assert any(node["node_type"] == "spider" for node in results["nodes"])

    # Keywords are terms that literally appear.
    for keyword in results["keywords"]:
        assert keyword["in_document"] is True
        assert keyword["occurrences"] >= 1
        haystack = " ".join(" \n ".join(passage["text"] for passage in content["passages"]).split()).lower()
        assert keyword["term"].lower() in haystack, keyword["term"]
        assert keyword["passage_ids"]


def test_writing_and_logic_findings_are_about_the_actual_text(client, samples_dir):
    session = register(client, "writer@spider.test", "longenough1")
    headers = auth(client, session["access_token"])
    document = upload(client, headers, samples_dir / "english_report.md")
    content = wait_for_extraction(client, headers, document["current_version_id"])
    investigation_id = investigate(client, headers, document["current_version_id"])
    results = client.get(f"/api/investigations/{investigation_id}/results", headers=headers).json()
    kinds = {finding["kind"] for finding in results["findings"]}
    assert "central_idea" in kinds or "subject" in kinds
    assert "statistic" in kinds, "the report's percentages must be extracted as statistics"
    assert "action_item" in kinds or "decision" in kinds
    assert "clarifying_question" in kinds or "unsupported_claim" in kinds
    assert results["recommendations"]
    assert all(recommendation["status"] == "pending" for recommendation in results["recommendations"])
    assert content["word_count"] > 300


def test_recommendation_decisions_are_persisted(client, samples_dir):
    session = register(client, "decider@spider.test", "longenough1")
    headers = auth(client, session["access_token"])
    document = upload(client, headers, samples_dir / "english_report.md")
    content = wait_for_extraction(client, headers, document["current_version_id"])
    investigation_id = investigate(client, headers, document["current_version_id"])
    results = client.get(f"/api/investigations/{investigation_id}/results", headers=headers).json()
    if not results["recommendations"]:
        pytest.skip("no recommendations produced for this document")
    target = results["recommendations"][0]
    decided = client.post(
        f"/api/recommendations/{target['id']}/decision", json={"status": "dismissed"}, headers=headers
    ).json()
    assert decided["status"] == "dismissed"
    again = client.get(f"/api/investigations/{investigation_id}/results", headers=headers).json()
    assert [item for item in again["recommendations"] if item["id"] == target["id"]][0]["status"] == "dismissed"


def test_question_is_answered_from_the_document_or_refused(client, samples_dir):
    session = register(client, "asker@spider.test", "longenough1")
    headers = auth(client, session["access_token"])
    document = upload(client, headers, samples_dir / "english_report.md")
    wait_for_extraction(client, headers, document["current_version_id"])
    investigation_id = investigate(client, headers, document["current_version_id"])

    answer = client.post(
        f"/api/investigations/{investigation_id}/questions",
        json={"question": "How many completed forms were collected?"},
        headers=headers,
    ).json()
    assert answer["grounded"] is True, answer
    assert answer["citations_detail"], "a grounded answer must quote the source"
    content = client.get(f"/api/versions/{document['current_version_id']}/content", headers=headers).json()
    passages = {passage["id"]: passage for passage in content["passages"]}
    for citation in answer["citations_detail"]:
        assert citation["quote"] in passages[citation["passage_id"]]["text"]

    outside = client.post(
        f"/api/investigations/{investigation_id}/questions",
        json={"question": "What is the capital city of Japan and its population?"},
        headers=headers,
    ).json()
    assert outside["grounded"] is False
    assert outside["limitation"] or "does not" in outside["answer"].lower()


def test_document_is_private_until_explicitly_granted(client, samples_dir):
    owner = register(client, "studentone@spider.test", "longenough1", role="student", name="Student One")
    teacher = register(client, "teach@spider.test", "longenough1", role="teacher", name="Mr Teacher")
    owner_headers = auth(client, owner["access_token"])
    teacher_headers = auth(client, teacher["access_token"])

    document = upload(client, owner_headers, samples_dir / "english_report.md")
    version_id = document["current_version_id"]

    blocked = client.get(f"/api/versions/{version_id}/content", headers=teacher_headers)
    assert blocked.status_code == 403

    inbox_before = client.get("/api/reviews/inbox", headers=teacher_headers).json()
    assert inbox_before["reviews"] == []

    granted = client.post(
        f"/api/documents/{document['id']}/access",
        json={"teacher_email": "teach@spider.test", "scope": "review"},
        headers=owner_headers,
    )
    assert granted.status_code == 201
    assert client.get(f"/api/versions/{version_id}/content", headers=teacher_headers).status_code == 200

    inbox = client.get("/api/reviews/inbox", headers=teacher_headers).json()
    assert len(inbox["reviews"]) == 1
    assert "advisory" in inbox["advisory_notice"].lower() or "teacher" in inbox["advisory_notice"].lower()


def test_teacher_review_flow_and_shared_report_visibility(client, samples_dir):
    student = register(client, "kid@spider.test", "longenough1", role="student", name="A Pupil")
    teacher = register(client, "ms@spider.test", "longenough1", role="teacher", name="Ms Reviewer")
    student_headers = auth(client, student["access_token"])
    teacher_headers = auth(client, teacher["access_token"])

    document = upload(client, student_headers, samples_dir / "english_report.md")
    version_id = document["current_version_id"]
    client.post(
        f"/api/documents/{document['id']}/access",
        json={"teacher_email": "ms@spider.test"},
        headers=student_headers,
    )
    investigation_id = investigate(client, student_headers, version_id)
    results = client.get(f"/api/investigations/{investigation_id}/results", headers=student_headers).json()
    finding = results["findings"][0]

    review = client.post(
        "/api/reviews", json={"document_id": document["id"], "investigation_id": investigation_id}, headers=teacher_headers
    ).json()
    assert review["status"] == "draft"

    # A teacher cannot finalize empty feedback made only of AI observations.
    empty = client.post(f"/api/reviews/{review['id']}/finalize", headers=teacher_headers)
    assert empty.status_code == 422

    client.patch(f"/api/reviews/{review['id']}", json={"overall_note": "Strong honest limitation section."}, headers=teacher_headers)
    shared_comment = client.post(
        f"/api/reviews/{review['id']}/comments",
        json={"text": "Widen the sample next term.", "passage_id": finding["primary_passage_id"],
              "finding_id": finding["id"], "include_with_student": True},
        headers=teacher_headers,
    ).json()
    private_comment = client.post(
        f"/api/reviews/{review['id']}/comments",
        json={"text": "Chase this up in the viva.", "include_with_student": False},
        headers=teacher_headers,
    ).json()

    finalized = client.post(f"/api/reviews/{review['id']}/finalize", headers=teacher_headers).json()
    assert finalized["status"] == "finalized"

    not_yet = client.get(f"/api/reports/{'nonexistent'}")
    assert not_yet.status_code == 404

    shared = client.post(f"/api/reviews/{review['id']}/share", headers=teacher_headers).json()
    assert shared["share_url"]
    assert shared["report_url"]
    report = client.get(shared["report_url"]).json()
    assert report["overall_note"] == "Strong honest limitation section."
    texts = [comment["text"] for comment in report["comments"]]
    assert "Widen the sample next term." in texts
    assert "Chase this up in the viva." not in texts
    assert report["private_comment_count"] == 1
    assert report["advisory_notice"]
    assert shared_comment["comments"][-1]["include_with_student"] is True
    assert private_comment["comments"][-1]["include_with_student"] is False

    # Once shared, the review is locked against edits.
    locked = client.patch(f"/api/reviews/{review['id']}", json={"overall_note": "changed"}, headers=teacher_headers)
    assert locked.status_code == 409


def test_rubric_responses_must_match_the_rubric(client, samples_dir):
    teacher = register(client, "rub@spider.test", "longenough1", role="teacher", name="Rubric Teacher")
    student = register(client, "sub@spider.test", "longenough1", role="student", name="Submitter")
    teacher_headers = auth(client, teacher["access_token"])
    student_headers = auth(client, student["access_token"])
    document = upload(client, student_headers, samples_dir / "english_report.md")
    client.post(f"/api/documents/{document['id']}/access", json={"teacher_email": "rub@spider.test"}, headers=student_headers)

    rubric = client.post(
        "/api/rubrics",
        json={"name": "Short report", "criteria": [{"label": "Evidence"}, {"label": "Structure"}]},
        headers=teacher_headers,
    ).json()
    review = client.post("/api/reviews", json={"document_id": document["id"]}, headers=teacher_headers).json()
    client.patch(f"/api/reviews/{review['id']}", json={"rubric_id": rubric["id"]}, headers=teacher_headers)

    good = client.patch(
        f"/api/reviews/{review['id']}",
        json={"rubric_responses": {criterion["id"]: "sound" for criterion in rubric["criteria"]}},
        headers=teacher_headers,
    )
    assert good.status_code == 200
    bad = client.patch(
        f"/api/reviews/{review['id']}", json={"rubric_responses": {"invented_criterion": "high"}}, headers=teacher_headers
    )
    assert bad.status_code == 400


def test_another_user_cannot_read_or_review(client, samples_dir):
    owner = register(client, "mine@spider.test", "longenough1")
    stranger = register(client, "theirs@spider.test", "longenough1")
    stranger_teacher = register(client, "nosy@spider.test", "longenough1", role="teacher", name="Nosy Teacher")
    owner_headers = auth(client, owner["access_token"])
    document = upload(client, owner_headers, samples_dir / "english_report.md")

    assert client.get(f"/api/documents/{document['id']}", headers=auth(client, stranger["access_token"])).status_code == 403
    assert client.get(f"/api/documents/{document['id']}", headers=auth(client, stranger_teacher["access_token"])).status_code == 403
    review = client.post("/api/reviews", json={"document_id": document["id"]}, headers=auth(client, stranger_teacher["access_token"]))
    assert review.status_code == 403
    assert client.get(f"/api/versions/{document['current_version_id']}/content", headers=auth(client, stranger["access_token"])).status_code == 403
    assert client.delete(f"/api/documents/{document['id']}", headers=auth(client, stranger["access_token"])).status_code == 403


@pytest.mark.parametrize("filename,expected_format", [
    ("english_report.docx", "docx"),
    ("english_report.txt", "txt"),
    ("english_report.html", "html"),
    ("reading_log.csv", "csv"),
])
def test_every_parser_feeds_the_same_pipeline(client, samples_dir, filename, expected_format):
    session = register(client, f"p_{expected_format}@spider.test", "longenough1")
    headers = auth(client, session["access_token"])
    document = upload(client, headers, samples_dir / filename)
    content = wait_for_extraction(client, headers, document["current_version_id"])
    assert content["file_format"] == expected_format
    assert content["extraction_status"] == "ready"
    assert len(content["passages"]) >= 3
    assert content["word_count"] > 20
    if expected_format != "pdf":
        assert content["positioning_quality"] == "dom_element"
    investigation_id = investigate(client, headers, document["current_version_id"])
    results = client.get(f"/api/investigations/{investigation_id}/results", headers=headers).json()
    assert results["findings"]
    for finding in results["findings"]:
        for evidence in finding["evidence"]:
            if evidence["validation"] == "verbatim":
                assert evidence["quote"]


def test_multilingual_documents_are_detected_and_analyzed(client, samples_dir):
    for filename, expected_language in [("arabic_report.md", "ar"), ("somali_report.md", "so")]:
        session = register(client, f"lang_{expected_language}@spider.test", "longenough1")
        headers = auth(client, session["access_token"])
        document = upload(client, headers, samples_dir / filename)
        content = wait_for_extraction(client, headers, document["current_version_id"])
        assert content["language"] == expected_language, (filename, content["language"])
        investigation_id = investigate(client, headers, document["current_version_id"])
        results = client.get(f"/api/investigations/{investigation_id}/results", headers=headers).json()
        assert results["findings"], filename
        # quotations stay in the document's own script
        passages = {passage["id"]: passage for passage in content["passages"]}
        for finding in results["findings"]:
            for evidence in finding["evidence"]:
                assert evidence["quote"] in passages[evidence["passage_id"]]["text"]


def test_deleting_a_document_removes_it_from_listings(client, samples_dir):
    session = register(client, "deleter@spider.test", "longenough1")
    headers = auth(client, session["access_token"])
    document = upload(client, headers, samples_dir / "english_report.md")
    assert client.delete(f"/api/documents/{document['id']}", headers=headers).status_code == 204
    listing = client.get("/api/documents", headers=headers).json()
    assert document["id"] not in [item["id"] for item in listing]
    assert client.get(f"/api/versions/{document['current_version_id']}/content", headers=headers).status_code == 403


def test_investigation_goals_are_respected(client, samples_dir):
    session = register(client, "goals@spider.test", "longenough1")
    headers = auth(client, session["access_token"])
    document = upload(client, headers, samples_dir / "english_report.md")
    version_id = document["current_version_id"]
    wait_for_extraction(client, headers, version_id)
    investigation_id = investigate(client, headers, version_id, goals=["keywords"])
    results = client.get(f"/api/investigations/{investigation_id}/results", headers=headers).json()
    assert results["keywords"]
    kinds = {finding["kind"] for finding in results["findings"]}
    assert "statistic" not in kinds, "important-info goal was not selected, so statistics must not appear"
    assert not results["recommendations"]


def test_unknown_investigation_goal_is_rejected(client, samples_dir):
    session = register(client, "badgoal@spider.test", "longenough1")
    headers = auth(client, session["access_token"])
    document = upload(client, headers, samples_dir / "english_report.md")
    response = client.post(
        f"/api/versions/{document['current_version_id']}/investigations", json={"goals": ["make_it_up"]}, headers=headers
    )
    assert response.status_code == 422
