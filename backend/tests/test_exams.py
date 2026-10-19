"""Exam, question and marking-scheme CRUD."""

from __future__ import annotations

from tests.conftest import auth_header, create_exam_with_questions, register_and_login


async def _headers(client):
    data = await register_and_login(client)
    return auth_header(data["access_token"])


async def test_create_exam_with_questions_and_criteria(client):
    headers = await _headers(client)
    exam = await create_exam_with_questions(client, headers)

    assert exam["title"] == "Computer Networks — Test"
    assert exam["status"] == "active"
    assert len(exam["questions"]) == 2
    # Total marks are derived from the questions.
    assert exam["total_marks"] == 11
    q1 = exam["questions"][0]
    assert q1["label"] == "Q1"
    assert len(q1["criteria"]) == 5
    # Criterion marks must sum to the question total.
    assert sum(c["max_marks"] for c in q1["criteria"]) == q1["max_marks"]


async def test_list_and_search_exams(client):
    headers = await _headers(client)
    await create_exam_with_questions(client, headers)

    listing = await client.get("/api/exams", headers=headers)
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 1
    assert body["items"][0]["question_count"] == 2

    found = await client.get("/api/exams?search=networks", headers=headers)
    assert found.json()["total"] == 1

    missing = await client.get("/api/exams?search=chemistry", headers=headers)
    assert missing.json()["total"] == 0


async def test_get_update_delete_exam(client):
    headers = await _headers(client)
    exam = await create_exam_with_questions(client, headers)

    got = await client.get(f"/api/exams/{exam['id']}", headers=headers)
    assert got.status_code == 200
    assert len(got.json()["questions"]) == 2

    updated = await client.patch(
        f"/api/exams/{exam['id']}",
        json={"title": "Renamed Exam", "status": "archived"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Renamed Exam"
    assert updated.json()["status"] == "archived"

    deleted = await client.delete(f"/api/exams/{exam['id']}", headers=headers)
    assert deleted.status_code == 200
    assert (await client.get(f"/api/exams/{exam['id']}", headers=headers)).status_code == 404


async def test_duplicate_question_number_rejected(client):
    headers = await _headers(client)
    exam = await create_exam_with_questions(client, headers)
    resp = await client.post(
        f"/api/exams/{exam['id']}/questions",
        json={"number": 1, "text": "Duplicate", "max_marks": 3},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "already exists" in resp.json()["detail"].lower()


async def test_update_question_replaces_marking_scheme(client):
    headers = await _headers(client)
    exam = await create_exam_with_questions(client, headers)
    question = exam["questions"][0]

    resp = await client.patch(
        f"/api/questions/{question['id']}",
        json={
            "max_marks": 4,
            "criteria": [
                {"name": "Concept", "max_marks": 2},
                {"name": "Example", "max_marks": 2},
            ],
        },
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["max_marks"] == 4
    assert [c["name"] for c in body["criteria"]] == ["Concept", "Example"]

    # The exam's derived total tracks the change.
    refreshed = await client.get(f"/api/exams/{exam['id']}", headers=headers)
    assert refreshed.json()["total_marks"] == 10


async def test_exam_is_private_to_its_owner(client):
    owner_headers = await _headers(client)
    exam = await create_exam_with_questions(client, owner_headers)

    other = await register_and_login(
        client,
        {
            "email": "other@example.com",
            "full_name": "Other Teacher",
            "password": "Str0ngPass2",
        },
    )
    other_headers = auth_header(other["access_token"])

    # A different teacher must not be able to see or modify the exam.
    assert (await client.get(f"/api/exams/{exam['id']}", headers=other_headers)).status_code == 404
    assert (
        await client.patch(
            f"/api/exams/{exam['id']}", json={"title": "Hijacked"}, headers=other_headers
        )
    ).status_code == 404
    assert (
        await client.delete(f"/api/exams/{exam['id']}", headers=other_headers)
    ).status_code == 404


async def test_delete_question_recomputes_total(client):
    headers = await _headers(client)
    exam = await create_exam_with_questions(client, headers)
    question = exam["questions"][1]

    resp = await client.delete(f"/api/questions/{question['id']}", headers=headers)
    assert resp.status_code == 200

    refreshed = await client.get(f"/api/exams/{exam['id']}", headers=headers)
    assert refreshed.json()["total_marks"] == 5
    assert len(refreshed.json()["questions"]) == 1


async def test_exam_stats_shape(client):
    headers = await _headers(client)
    exam = await create_exam_with_questions(client, headers)
    stats = await client.get(f"/api/exams/{exam['id']}/stats", headers=headers)
    assert stats.status_code == 200
    body = stats.json()
    assert body["submission_count"] == 0
    assert body["max_total_marks"] == 11
