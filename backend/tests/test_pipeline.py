"""End-to-end processing pipeline (upload -> OCR -> segment -> evaluate).

The pipeline handlers are invoked directly (as the worker would) so the test is
fast and deterministic. The mock provider makes every result reproducible.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db.enums import PageStatus, SubmissionStatus
from app.models.answer import Answer, OCRResult
from app.models.submission import Submission, SubmissionPage
from app.services import processing_service
from tests.conftest import (
    auth_header,
    create_exam_with_questions,
    pdf_bytes,
    png_bytes,
    register_and_login,
)


class FakeJob:
    """Minimal stand-in for a persisted ProcessingJob row."""

    def __init__(self, job_type, submission_id=None, answer_id=None, page_id=None, payload=None):
        self.id = uuid.uuid4()
        self.job_type = job_type
        self.submission_id = submission_id
        self.answer_id = answer_id
        self.page_id = page_id
        self.payload = payload or {}


async def _upload(client, headers, exam_id, *, files, data=None):
    resp = await client.post(
        f"/api/exams/{exam_id}/submissions",
        files=files,
        data=data or {},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()[0]


async def _run_pipeline(db, submission_id):
    """Execute the three pipeline stages in order, as the worker would."""
    from app.db.enums import JobType

    await processing_service.process_submission(
        db, FakeJob(JobType.PROCESS_SUBMISSION, submission_id=submission_id, payload={"content_type": "image/png"})
    )
    await db.flush()
    await processing_service.segment_answers_job(
        db, FakeJob(JobType.SEGMENT_ANSWERS, submission_id=submission_id)
    )
    await db.flush()
    await processing_service.evaluate_submission(
        db, FakeJob(JobType.EVALUATE_SUBMISSION, submission_id=submission_id, payload={"force": False})
    )
    await db.flush()


async def test_full_pipeline_produces_answers_and_evaluations(client, db):
    data = await register_and_login(client)
    headers = auth_header(data["access_token"])
    exam = await create_exam_with_questions(client, headers)

    submission = await _upload(
        client,
        headers,
        exam["id"],
        files={"files": ("script.png", png_bytes(700, 900, "Q1. SYN SYN-ACK ACK\nQ2. 62 hosts"), "image/png")},
        data={"student_roll": "2026-CS-777"},
    )

    await _run_pipeline(db, uuid.UUID(submission["id"]))
    await db.commit()

    submission_row = (
        await db.execute(select(Submission).where(Submission.id == uuid.UUID(submission["id"])))
    ).scalar_one()

    # Pages were extracted, preprocessed and transcribed.
    assert submission_row.page_count == 1
    assert submission_row.processed_page_count == 1

    pages = (
        await db.execute(
            select(SubmissionPage).where(SubmissionPage.submission_id == submission_row.id)
        )
    ).scalars().all()
    assert len(pages) == 1
    assert pages[0].status == PageStatus.OCR_DONE
    assert pages[0].processed_storage_key
    assert pages[0].thumbnail_storage_key

    ocr = (await db.execute(select(OCRResult))).scalars().all()
    assert len(ocr) == 1
    assert ocr[0].text
    assert ocr[0].is_mock is True

    # One answer per question, each with an AI evaluation.
    answers = (
        await db.execute(
            select(Answer).where(Answer.submission_id == submission_row.id).order_by(Answer.order_index)
        )
    ).scalars().all()
    assert len(answers) == 2
    for answer in answers:
        assert answer.ai_score is not None
        assert answer.ai_confidence is not None
        assert 0 <= float(answer.ai_score) <= float(answer.max_marks)
    assert submission_row.status == SubmissionStatus.READY_FOR_REVIEW
    assert float(submission_row.max_total_marks) == 11
    # Totals were recomputed from the answer scores.
    assert float(submission_row.final_total_marks) == sum(
        float(a.ai_score) for a in answers
    )


async def test_pdf_pipeline_handles_multiple_pages(client, db):
    data = await register_and_login(client)
    headers = auth_header(data["access_token"])
    exam = await create_exam_with_questions(client, headers)

    submission = await _upload(
        client,
        headers,
        exam["id"],
        files={
            "files": (
                "booklet.pdf",
                pdf_bytes(["Q1. First page answer.", "Q2. Second page answer."]),
                "application/pdf",
            )
        },
    )
    await _run_pipeline(db, uuid.UUID(submission["id"]))
    await db.commit()

    pages = (
        await db.execute(
            select(SubmissionPage)
            .where(SubmissionPage.submission_id == uuid.UUID(submission["id"]))
            .order_by(SubmissionPage.page_number)
        )
    ).scalars().all()
    assert [p.page_number for p in pages] == [1, 2]
    assert all(p.status == PageStatus.OCR_DONE for p in pages)

    answers = (
        await db.execute(
            select(Answer).where(Answer.submission_id == uuid.UUID(submission["id"]))
        )
    ).scalars().all()
    assert len(answers) == 2


async def test_reprocessing_is_idempotent_and_does_not_duplicate_answers(client, db):
    data = await register_and_login(client)
    headers = auth_header(data["access_token"])
    exam = await create_exam_with_questions(client, headers)

    submission = await _upload(
        client,
        headers,
        exam["id"],
        files={"files": ("script.png", png_bytes(), "image/png")},
    )
    submission_id = uuid.UUID(submission["id"])

    await _run_pipeline(db, submission_id)
    await db.commit()
    first_answers = (
        await db.execute(select(Answer).where(Answer.submission_id == submission_id))
    ).scalars().all()
    first_ids = {a.id for a in first_answers}

    # Run again: pages, OCR rows and answers must not be duplicated.
    await _run_pipeline(db, submission_id)
    await db.commit()

    second_answers = (
        await db.execute(select(Answer).where(Answer.submission_id == submission_id))
    ).scalars().all()
    assert len(second_answers) == 2
    assert {a.id for a in second_answers} != first_ids  # rebuilt, not appended
    assert len((await db.execute(select(SubmissionPage))).scalars().all()) == 1
    assert len((await db.execute(select(OCRResult))).scalars().all()) == 1


async def test_ocr_is_cached_and_not_repeated(client, db):
    """A completed OCR pass is reused: no second provider call, no new row."""
    data = await register_and_login(client)
    headers = auth_header(data["access_token"])
    exam = await create_exam_with_questions(client, headers)
    submission = await _upload(
        client, headers, exam["id"], files={"files": ("s.png", png_bytes(), "image/png")}
    )
    submission_id = uuid.UUID(submission["id"])

    await _run_pipeline(db, submission_id)
    await db.commit()

    page = (await db.execute(select(SubmissionPage))).scalars().one()
    before = (await db.execute(select(OCRResult))).scalars().all()
    assert len(before) == 1

    # Re-running preprocessing+OCR without force reuses the cached OCR row.
    await processing_service._transcribe_page(db, page, force=False)
    await db.commit()
    after = (await db.execute(select(OCRResult))).scalars().all()
    assert len(after) == 1
    assert after[0].id == before[0].id


async def test_answers_flagged_when_no_content_detected(client, db):
    """A blank page must not be confidently graded — it is flagged instead."""
    data = await register_and_login(client)
    headers = auth_header(data["access_token"])
    exam = await create_exam_with_questions(client, headers)
    submission = await _upload(
        client,
        headers,
        exam["id"],
        files={"files": ("blank.png", png_bytes(300, 300), "image/png")},
    )
    await _run_pipeline(db, uuid.UUID(submission["id"]))
    await db.commit()

    answers = (
        await db.execute(
            select(Answer).where(Answer.submission_id == uuid.UUID(submission["id"]))
        )
    ).scalars().all()
    # The mock OCR returns nothing resembling a question heading, so all answers
    # carry no detected content and must be flagged for the teacher.
    assert all(a.is_flagged for a in answers)
    assert all(a.flag_reason for a in answers)


async def test_status_endpoint_reports_progress(client, db):
    data = await register_and_login(client)
    headers = auth_header(data["access_token"])
    exam = await create_exam_with_questions(client, headers)
    submission = await _upload(
        client, headers, exam["id"], files={"files": ("s.png", png_bytes(), "image/png")}
    )
    await _run_pipeline(db, uuid.UUID(submission["id"]))
    await db.commit()

    resp = await client.get(f"/api/submissions/{submission['id']}/status", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready_for_review"
    assert body["answer_count"] == 2
    assert body["evaluated_count"] == 2
    assert body["stage_message"]
