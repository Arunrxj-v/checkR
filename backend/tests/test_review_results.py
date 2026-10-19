"""Teacher review, score preservation, audit trail, results and finalisation."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.answer import Answer
from app.models.evaluation import TeacherReview
from tests.conftest import (
    auth_header,
    create_exam_with_questions,
    png_bytes,
    register_and_login,
)
from tests.test_pipeline import _run_pipeline, _upload


async def _processed_submission(client, db):
    data = await register_and_login(client)
    headers = auth_header(data["access_token"])
    exam = await create_exam_with_questions(client, headers)
    submission = await _upload(
        client,
        headers,
        exam["id"],
        files={"files": ("s.png", png_bytes(700, 900), "image/png")},
        data={"student_name": "Jane Doe", "student_roll": "2026-CS-042"},
    )
    await _run_pipeline(db, uuid.UUID(submission["id"]))
    await db.commit()
    return headers, exam, submission


async def _answers(db, submission_id):
    return (
        await db.execute(
            select(Answer)
            .where(Answer.submission_id == uuid.UUID(submission_id))
            .options(selectinload(Answer.question))
            .order_by(Answer.order_index)
        )
    ).scalars().all()


async def test_answer_detail_includes_everything_the_workspace_needs(client, db):
    headers, exam, submission = await _processed_submission(client, db)
    answers = await _answers(db, submission["id"])
    answer_id = answers[0].id

    resp = await client.get(f"/api/answers/{answer_id}", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["question_label"] == "Q1"
    assert body["question_text"]
    assert len(body["marking_scheme"]) == 5
    assert body["evaluation"] is not None
    assert len(body["evaluation"]["criteria"]) == 5
    assert body["evaluation"]["provider"] == "mock"
    assert body["evaluation"]["is_mock"] is True
    assert body["evaluation"]["prompt_version"]
    assert body["evaluation"]["engine_version"]
    # The AI total equals the sum of its criteria.
    assert abs(
        sum(c["awarded_marks"] for c in body["evaluation"]["criteria"])
        - body["evaluation"]["awarded_marks"]
    ) < 0.01


async def test_accept_ai_suggestion(client, db):
    headers, exam, submission = await _processed_submission(client, db)
    answer = (await _answers(db, submission["id"]))[0]

    resp = await client.put(
        f"/api/answers/{answer.id}/review",
        json={"action": "accepted", "comment": "Agreed with the AI."},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_reviewed"] is True
    assert body["teacher_score"] == body["ai_score"]
    assert body["final_score"] == body["ai_score"]
    assert body["status"] == "reviewed"
    assert body["is_flagged"] is False


async def test_override_preserves_ai_score(client, db):
    headers, exam, submission = await _processed_submission(client, db)
    answer = (await _answers(db, submission["id"]))[0]
    original_ai = float(answer.ai_score)

    new_mark = round(min(float(answer.max_marks), original_ai + 1.0), 1)
    resp = await client.put(
        f"/api/answers/{answer.id}/review",
        json={
            "action": "overridden",
            "teacher_score": new_mark,
            "comment": "Explanation is acceptable.",
            "reason": "Student explained the concept in different words.",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["teacher_score"] == new_mark
    assert body["final_score"] == new_mark
    # The AI score is never overwritten.
    assert body["ai_score"] == original_ai
    assert body["is_reviewed"] is True

    # An immutable review record was written.
    db.expire_all()
    reviews = (await db.execute(select(TeacherReview))).scalars().all()
    assert len(reviews) == 1
    assert reviews[0].decision.value == "overridden"
    assert float(reviews[0].ai_score) == original_ai
    assert float(reviews[0].teacher_score) == new_mark
    assert reviews[0].reason


async def test_override_outside_range_is_rejected(client, db):
    headers, exam, submission = await _processed_submission(client, db)
    answer = (await _answers(db, submission["id"]))[0]

    too_high = await client.put(
        f"/api/answers/{answer.id}/review",
        json={"action": "overridden", "teacher_score": float(answer.max_marks) + 5},
        headers=headers,
    )
    assert too_high.status_code == 400
    assert "between" in too_high.json()["detail"].lower()


async def test_override_requires_a_mark(client, db):
    headers, exam, submission = await _processed_submission(client, db)
    answer = (await _answers(db, submission["id"]))[0]
    resp = await client.put(
        f"/api/answers/{answer.id}/review",
        json={"action": "overridden"},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_flag_and_unflag(client, db):
    headers, exam, submission = await _processed_submission(client, db)
    answer = (await _answers(db, submission["id"]))[0]

    flagged = await client.put(
        f"/api/answers/{answer.id}/review",
        json={"action": "flagged", "reason": "Handwriting is unclear around the second step."},
        headers=headers,
    )
    assert flagged.status_code == 200
    assert flagged.json()["is_flagged"] is True
    assert "unclear" in flagged.json()["flag_reason"]

    cleared = await client.put(
        f"/api/answers/{answer.id}/review",
        json={"action": "unflagged"},
        headers=headers,
    )
    assert cleared.status_code == 200
    assert cleared.json()["is_flagged"] is False


async def test_review_writes_an_audit_trail(client, db):
    headers, exam, submission = await _processed_submission(client, db)
    answer = (await _answers(db, submission["id"]))[0]
    await client.put(
        f"/api/answers/{answer.id}/review",
        json={"action": "overridden", "teacher_score": 3, "reason": "Partial credit is fair."},
        headers=headers,
    )

    logs = await client.get("/api/audit-logs", headers=headers)
    assert logs.status_code == 200
    actions = [item["action"] for item in logs.json()["items"]]
    assert any("answer.review" in a for a in actions)
    assert any(a == "answer.evaluated" for a in actions)

    override = next(
        item for item in logs.json()["items"] if item["action"] == "answer.review.overridden"
    )
    assert override["actor_email"]
    assert override["old_value"]["ai_score"] is not None
    assert override["new_value"]["final_score"] == 3
    assert override["reason"] == "Partial credit is fair."


async def test_result_and_finalisation_flow(client, db):
    headers, exam, submission = await _processed_submission(client, db)
    answers = await _answers(db, submission["id"])

    result = await client.get(f"/api/submissions/{submission['id']}/result", headers=headers)
    assert result.status_code == 200
    body = result.json()
    assert body["total_answers"] == 2
    assert len(body["rows"]) == 2
    assert body["max_total_marks"] == 11
    assert body["percentage"] is not None

    # Finalising before every answer is reviewed must be refused.
    premature = await client.post(
        f"/api/submissions/{submission['id']}/finalize", headers=headers
    )
    assert premature.status_code == 400
    assert "need a teacher decision" in premature.json()["detail"]

    for answer in answers:
        resp = await client.put(
            f"/api/answers/{answer.id}/review",
            json={"action": "accepted"},
            headers=headers,
        )
        assert resp.status_code == 200

    finalised = await client.post(
        f"/api/submissions/{submission['id']}/finalize", headers=headers
    )
    assert finalised.status_code == 200, finalised.text
    final_body = finalised.json()
    assert final_body["status"] == "completed"
    assert final_body["reviewed_count"] == 2
    assert final_body["percentage"] == round(
        final_body["final_total_marks"] / final_body["max_total_marks"] * 100, 2
    )


async def test_reopen_a_finalised_submission(client, db):
    headers, exam, submission = await _processed_submission(client, db)
    for answer in await _answers(db, submission["id"]):
        await client.put(
            f"/api/answers/{answer.id}/review", json={"action": "accepted"}, headers=headers
        )
    await client.post(f"/api/submissions/{submission['id']}/finalize", headers=headers)

    reopened = await client.post(
        f"/api/submissions/{submission['id']}/reopen", headers=headers
    )
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "reviewed"


async def test_exam_result_overview(client, db):
    headers, exam, submission = await _processed_submission(client, db)
    for answer in await _answers(db, submission["id"]):
        await client.put(
            f"/api/answers/{answer.id}/review", json={"action": "accepted"}, headers=headers
        )
    await client.post(f"/api/submissions/{submission['id']}/finalize", headers=headers)

    overview = await client.get(f"/api/exams/{exam['id']}/results", headers=headers)
    assert overview.status_code == 200
    body = overview.json()
    assert body["submission_count"] == 1
    assert body["completed_count"] == 1
    assert body["average_percentage"] is not None
    assert body["rows"][0]["student_roll"] or body["rows"][0]["student_name"] is not None


async def test_manual_evaluation_endpoint_enqueues_a_job(client, db):
    headers, exam, submission = await _processed_submission(client, db)
    answer = (await _answers(db, submission["id"]))[0]

    resp = await client.post(f"/api/answers/{answer.id}/evaluate", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["job_type"] == "evaluate_answer"


async def test_evaluation_history_is_retained(client, db):
    """Re-evaluation supersedes the old result but keeps it for the audit trail."""
    from app.services import evaluation_service

    headers, exam, submission = await _processed_submission(client, db)
    answer = (await _answers(db, submission["id"]))[0]

    first = await client.get(f"/api/answers/{answer.id}/evaluation", headers=headers)
    assert first.status_code == 200

    await evaluation_service.evaluate_answer(db, answer=answer, question=answer.question, force=True, actor=None)
    await db.commit()

    history = await client.get(f"/api/answers/{answer.id}/evaluations", headers=headers)
    assert history.status_code == 200
    assert len(history.json()) == 2
    statuses = {e["status"] for e in history.json()}
    assert "superseded" in statuses
    assert "valid" in statuses
