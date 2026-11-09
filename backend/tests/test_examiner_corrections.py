"""Examiner corrections: transcription and answer ↔ page mapping.

The examiner can fix what the model read and where the answer sits on the
manuscript, without ever overwriting the original AI output. Question numbers
are never assumed to equal page numbers: the examiner states the pages.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.answer import Answer, OCRResult
from app.models.audit import AuditLog
from app.services.page_mapping import PAGE_MAPPING_OVERRIDE_KEY, SOURCE_EXAMINER
from tests.test_review_results import _answers, _processed_submission


async def test_examiner_corrects_transcription_without_touching_ai_output(client, db):
    headers, exam, submission = await _processed_submission(client, db)
    answer = (await _answers(db, submission["id"]))[0]

    original_ocr = (
        await db.execute(select(OCRResult).where(OCRResult.page_id.is_not(None)))
    ).scalars().first()
    original_text = original_ocr.text
    original_raw = dict(original_ocr.raw_response)
    original_ai_suggestion = answer.transcription

    corrected = "1. The algorithm runs in a single pass and uses O(n) time."
    resp = await client.patch(
        f"/api/answers/{answer.id}/transcription",
        json={"transcription": corrected},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["transcription"] == corrected
    # The examiner read the script — the handwriting is no longer "uncertain".
    assert body["is_handwriting_uncertain"] is False

    db.expire_all()
    # The original OCR row (model output) is untouched: the correction lives
    # only on the answer, and the AI suggestion is still auditable.
    stored_ocr = (
        await db.execute(select(OCRResult).where(OCRResult.id == original_ocr.id))
    ).scalar_one()
    assert stored_ocr.text == original_text
    assert dict(stored_ocr.raw_response) == original_raw

    detail = (await db.execute(select(Answer).where(Answer.id == answer.id))).scalar_one()
    assert detail.transcription == corrected
    assert detail.detection_meta["transcription_corrected_by_examiner"] is True
    assert original_ai_suggestion != corrected  # sanity: the correction moved

    audit = (
        (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.action == "answer.transcription_corrected",
                    AuditLog.entity_id == answer.id,
                )
            )
        )
        .scalars()
        .one()
    )
    assert audit.actor_email
    assert audit.old_value["transcription"] == original_ai_suggestion
    assert audit.new_value["transcription"] == corrected


async def test_examiner_corrects_page_mapping(client, db):
    headers, exam, submission = await _processed_submission(client, db)
    answer = (await _answers(db, submission["id"]))[0]
    from app.models.submission import SubmissionPage

    pages = (
        (
            await db.execute(
                select(SubmissionPage)
                .where(SubmissionPage.submission_id == uuid.UUID(submission["id"]))
                .order_by(SubmissionPage.page_number)
            )
        )
        .scalars()
        .all()
    )
    assert pages, "the pipeline must store the uploaded page(s)"
    target = pages[0].page_number

    resp = await client.put(
        f"/api/answers/{answer.id}/pages",
        json={"page_numbers": [target]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [p["page_number"] for p in body["pages"]] == [target]
    assert body["page_mapping_source"] == SOURCE_EXAMINER
    for page in body["pages"]:
        assert page["uncertain"] is False

    # The correction persists and wins on the next read.
    reread = await client.get(f"/api/answers/{answer.id}", headers=headers)
    assert reread.status_code == 200
    assert reread.json()["page_mapping_source"] == SOURCE_EXAMINER
    assert [p["page_number"] for p in reread.json()["pages"]] == [target]

    db.expire_all()
    stored = (await db.execute(select(Answer).where(Answer.id == answer.id))).scalar_one()
    override = stored.detection_meta[PAGE_MAPPING_OVERRIDE_KEY]
    assert override["page_numbers"] == [target]
    assert override["actor_id"]

    audit = (
        (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.action == "answer.page_mapping_corrected",
                    AuditLog.entity_id == answer.id,
                )
            )
        )
        .scalars()
        .one()
    )
    assert str(target) in audit.description


async def test_page_mapping_rejects_pages_that_do_not_exist(client, db):
    headers, exam, submission = await _processed_submission(client, db)
    answer = (await _answers(db, submission["id"]))[0]

    resp = await client.put(
        f"/api/answers/{answer.id}/pages",
        json={"page_numbers": [999]},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "999" in resp.json()["detail"]


async def test_page_mapping_rejects_an_empty_set(client, db):
    headers, exam, submission = await _processed_submission(client, db)
    answer = (await _answers(db, submission["id"]))[0]

    resp = await client.put(
        f"/api/answers/{answer.id}/pages",
        json={"page_numbers": []},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_correcting_requires_an_owned_answer(client, db):
    headers, exam, submission = await _processed_submission(client, db)
    answer = (await _answers(db, submission["id"]))[0]
    answer_id = answer.id

    from tests.conftest import auth_header, register_and_login

    other = await register_and_login(
        client,
        {
            "email": "other-teacher@example.com",
            "full_name": "Dr. Other Teacher",
            "password": "Str0ngPass1",
            "department": "Mathematics",
        },
    )
    other_headers = auth_header(other["access_token"])

    resp = await client.patch(
        f"/api/answers/{uuid.uuid4()}/transcription",
        json={"transcription": "x"},
        headers=other_headers,
    )
    assert resp.status_code in (403, 404)

    resp = await client.put(
        f"/api/answers/{answer_id}/pages",
        json={"page_numbers": [1]},
        headers=other_headers,
    )
    assert resp.status_code in (403, 404)
