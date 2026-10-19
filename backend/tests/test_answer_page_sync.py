"""Question → answer → manuscript-page synchronisation (API contract).

The evaluation workspace navigates the manuscript viewer purely from server
data, so the page association must be exposed per answer and must never be
invented. These tests pin that contract at the API boundary.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select

from app.db.enums import JobType
from app.models.answer import Answer, AnswerRegion
from app.models.submission import SubmissionPage
from app.services import processing_service
from tests.conftest import auth_header, pdf_bytes, register_and_login

EXAM_PAYLOAD = {
    "title": "Page Mapping — Test",
    "subject": "Computer Networks",
    "subject_code": "CS312",
    "course": "Semester 5",
    "academic_year": "2026",
    "duration_minutes": 90,
    "status": "active",
    "questions": [
        {
            "number": 1,
            "text": "Explain the OSI reference model.",
            "max_marks": 5,
            "question_type": "explanation",
            "criteria": [{"name": "Layers", "max_marks": 5}],
        },
        {
            "number": 2,
            "text": "Compare TCP and UDP.",
            "max_marks": 5,
            "question_type": "explanation",
            "criteria": [{"name": "Comparison", "max_marks": 5}],
        },
        {
            "number": 3,
            "text": "Reverse a singly linked list.",
            "max_marks": 5,
            "question_type": "programming",
            "criteria": [{"name": "Code", "max_marks": 5}],
        },
    ],
}


class _Job:
    """Minimal stand-in for a persisted ProcessingJob row."""

    def __init__(self, job_type, submission_id):
        self.id = uuid.uuid4()
        self.job_type = job_type
        self.submission_id = submission_id
        self.answer_id = None
        self.page_id = None
        self.payload = {}


async def _setup(client, db):
    """Register, create a 3-question exam and submit a 3-page booklet."""
    data = await register_and_login(client)
    headers = auth_header(data["access_token"])

    resp = await client.post("/api/exams", json=EXAM_PAYLOAD, headers=headers)
    assert resp.status_code == 201, resp.text
    exam = resp.json()

    resp = await client.post(
        f"/api/exams/{exam['id']}/submissions",
        files={
            "files": (
                "booklet.pdf",
                pdf_bytes(["page one content", "page two content", "page three content"]),
                "application/pdf",
            )
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    submission = resp.json()[0]
    submission_id = uuid.UUID(submission["id"])

    await processing_service.process_submission(
        db, _Job(JobType.PROCESS_SUBMISSION, submission_id)
    )
    await db.flush()
    await processing_service.segment_answers_job(
        db, _Job(JobType.SEGMENT_ANSWERS, submission_id)
    )
    await db.flush()
    await db.commit()

    pages = (
        await db.execute(
            select(SubmissionPage)
            .where(SubmissionPage.submission_id == submission_id)
            .order_by(SubmissionPage.page_number)
        )
    ).scalars().all()
    answers = (
        await db.execute(
            select(Answer)
            .where(Answer.submission_id == submission_id)
            .order_by(Answer.order_index)
        )
    ).scalars().all()
    assert [p.page_number for p in pages] == [1, 2, 3]
    assert len(answers) == 3
    return headers, submission, pages, answers


async def _assign(db, answers, pages, mapping, *, detection_pages=None):
    """Replace the detected regions with a precise, known page mapping.

    ``mapping`` is ``{answer_id: [page_number, ...]}``. Detection metadata is
    reset so the fallback path is exercised only when a test asks for it.
    """
    await db.execute(delete(AnswerRegion))
    by_number = {page.page_number: page for page in pages}
    detection_pages = detection_pages or {}
    for answer in answers:
        numbers = mapping.get(answer.id, [])
        answer.detection_meta = {
            "has_content": True,
            "source_pages": list(detection_pages.get(answer.id, [])),
        }
        for index, number in enumerate(numbers):
            db.add(
                AnswerRegion(
                    answer_id=answer.id,
                    page_id=by_number[number].id,
                    x0=0.1,
                    y0=round(0.1 + index * 0.1, 3),
                    x1=0.8,
                    y1=round(0.18 + index * 0.1, 3),
                    label=f"line {index}",
                    confidence=0.9,
                )
            )
    await db.commit()


# --------------------------------------------------------------------------- #
# Detail endpoint
# --------------------------------------------------------------------------- #
async def test_answer_detail_maps_each_answer_to_its_detected_pages(client, db):
    headers, submission, pages, answers = await _setup(client, db)
    q1, q2, q3 = answers
    await _assign(db, answers, pages, {q1.id: [1], q2.id: [3], q3.id: [2]})

    resp = await client.get(f"/api/answers/{q2.id}", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Q2 lives on page 3 — not on page 2 because of its position in the roster.
    assert body["page_numbers"] == [3]
    assert [p["page_number"] for p in body["pages"]] == [3]
    assert body["page_mapping_uncertain"] is False
    assert body["page_mapping_source"] == "regions"
    assert len(body["pages"][0]["regions"]) == 1

    resp = await client.get(f"/api/answers/{q3.id}", headers=headers)
    assert resp.json()["page_numbers"] == [2]


async def test_detail_reports_a_multi_page_answer_in_order(client, db):
    headers, submission, pages, answers = await _setup(client, db)
    q1, _, _ = answers
    await _assign(db, answers, pages, {q1.id: [1, 3], answers[1].id: [2]})

    resp = await client.get(f"/api/answers/{q1.id}", headers=headers)
    body = resp.json()

    assert body["page_numbers"] == [1, 3]
    assert [p["page_number"] for p in body["pages"]] == [1, 3]
    assert [len(p["regions"]) for p in body["pages"]] == [1, 1]
    # Coordinates stay normalised so the viewer can overlay them at any zoom.
    for page in body["pages"]:
        for region in page["regions"]:
            assert 0 <= region["x0"] < region["x1"] <= 1
            assert 0 <= region["y0"] < region["y1"] <= 1


async def test_answer_without_regions_is_uncertain_and_claims_no_page(client, db):
    """No detection evidence ⇒ no page claimed (never a default of page 1)."""
    headers, submission, pages, answers = await _setup(client, db)
    q1, _, q3 = answers
    await _assign(db, answers, pages, {q1.id: [1]})

    resp = await client.get(f"/api/answers/{q3.id}", headers=headers)
    body = resp.json()

    assert body["page_numbers"] == []
    assert body["pages"] == []
    assert body["page_mapping_uncertain"] is True
    assert body["page_mapping_source"] == "unknown"


async def test_detection_fallback_is_served_but_marked_uncertain(client, db):
    headers, submission, pages, answers = await _setup(client, db)
    _, _, q3 = answers
    await _assign(
        db,
        answers,
        pages,
        {},
        detection_pages={q3.id: [2]},
    )

    resp = await client.get(f"/api/answers/{q3.id}", headers=headers)
    body = resp.json()

    assert body["page_numbers"] == [2]
    assert body["page_mapping_uncertain"] is True
    assert body["page_mapping_source"] == "detection_meta"
    assert body["pages"][0]["uncertain"] is True


async def test_region_on_an_unknown_page_does_not_displace_the_mapping(client, db):
    headers, submission, pages, answers = await _setup(client, db)
    q1, _, _ = answers
    await _assign(db, answers, pages, {q1.id: [1]})

    # An orphaned region (page not part of this submission) must be ignored.
    db.add(
        AnswerRegion(
            answer_id=q1.id,
            page_id=uuid.uuid4(),
            x0=0.1,
            y0=0.5,
            x1=0.9,
            y1=0.6,
            label="orphan",
        )
    )
    await db.commit()

    body = (await client.get(f"/api/answers/{q1.id}", headers=headers)).json()
    assert body["page_numbers"] == [1]
    assert body["page_mapping_uncertain"] is True


# --------------------------------------------------------------------------- #
# Roster endpoint (drives the Question Roster without extra requests)
# --------------------------------------------------------------------------- #
async def test_answer_list_serves_the_page_mapping_for_the_roster(client, db):
    headers, submission, pages, answers = await _setup(client, db)
    q1, q2, q3 = answers
    await _assign(db, answers, pages, {q1.id: [1], q2.id: [1, 2], q3.id: [3]})

    resp = await client.get(
        f"/api/submissions/{submission['id']}/answers", headers=headers
    )
    assert resp.status_code == 200, resp.text
    by_id = {row["id"]: row for row in resp.json()}

    assert by_id[str(q1.id)]["page_numbers"] == [1]
    assert by_id[str(q2.id)]["page_numbers"] == [1, 2]
    assert by_id[str(q3.id)]["page_numbers"] == [3]
    assert by_id[str(q1.id)]["page_mapping_uncertain"] is False


async def test_answer_list_flags_an_unmapped_answer_as_uncertain(client, db):
    headers, submission, pages, answers = await _setup(client, db)
    q1, _, q3 = answers
    await _assign(db, answers, pages, {q1.id: [1]})

    resp = await client.get(
        f"/api/submissions/{submission['id']}/answers", headers=headers
    )
    by_id = {row["id"]: row for row in resp.json()}
    assert by_id[str(q3.id)]["page_numbers"] == []
    assert by_id[str(q3.id)]["page_mapping_uncertain"] is True
