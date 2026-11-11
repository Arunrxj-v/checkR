"""Answer retrieval, AI evaluation and teacher review routes."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, OwnedAnswer, OwnedSubmission
from app.api.rate_limit import limiter
from app.db.enums import JobType
from app.models.answer import Answer, AnswerRegion, OCRResult
from app.models.exam import Question
from app.models.submission import SubmissionPage
from app.schemas.answer import (
    AnswerDetail,
    AnswerOut,
    AnswerPageOut,
    AnswerRegionOut,
    EvaluationCriterionOut,
    EvaluationOut,
    OCRProvenanceOut,
    PageMappingUpdate,
    ReviewOut,
    ReviewRequest,
    TranscriptionUpdate,
)
from app.schemas.job import JobOut
from app.services import (
    audit_service,
    evaluation_service,
    job_service,
    review_service,
    submission_service,
)
from app.services.page_mapping import PAGE_MAPPING_OVERRIDE_KEY, build_answer_page_mapping
from app.services.review_service import ReviewError

router = APIRouter(tags=["answers"])

_eval_limits = limiter(240, 60, scope="evaluate")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


async def _submission_pages(db: DbSession, submission_id: uuid.UUID) -> list[SubmissionPage]:
    return list(
        (
            await db.execute(
                select(SubmissionPage)
                .where(SubmissionPage.submission_id == submission_id)
                .order_by(SubmissionPage.page_number)
            )
        )
        .scalars()
        .all()
    )


@router.get("/submissions/{submission_id}/answers", response_model=list[AnswerOut])
async def list_answers(
    submission: OwnedSubmission, db: DbSession
) -> list[AnswerOut]:
    answers = (
        await db.execute(
            select(Answer)
            .where(Answer.submission_id == submission.id)
            .order_by(Answer.order_index)
        )
    ).scalars().all()

    # One extra query feeds the roster with the answer → manuscript-page map, so
    # the workspace never has to infer pages from list position.
    regions_by_answer: dict[uuid.UUID, list[AnswerRegion]] = defaultdict(list)
    if answers:
        regions = (
            await db.execute(
                select(AnswerRegion).where(
                    AnswerRegion.answer_id.in_([a.id for a in answers])
                )
            )
        ).scalars().all()
        for region in regions:
            regions_by_answer[region.answer_id].append(region)

    pages = await _submission_pages(db, submission.id)

    result: list[AnswerOut] = []
    for answer in answers:
        mapping = build_answer_page_mapping(
            regions=regions_by_answer.get(answer.id, []),
            pages=pages,
            detection_meta=answer.detection_meta,
        )
        item = AnswerOut.model_validate(answer)
        item.page_numbers = list(mapping.page_numbers)
        item.page_mapping_uncertain = mapping.uncertain
        result.append(item)
    return result


@router.get("/answers/{answer_id}", response_model=AnswerDetail)
async def get_answer(answer: OwnedAnswer, db: DbSession) -> AnswerDetail:
    answer = (
        await db.execute(
            select(Answer)
            .where(Answer.id == answer.id)
            .options(
                selectinload(Answer.regions),
                selectinload(Answer.question).selectinload(Question.criteria),
                selectinload(Answer.reviews),
            )
        )
    ).scalar_one()

    evaluation = await evaluation_service.latest_evaluation(db, answer.id)

    pages = await _submission_pages(db, answer.submission_id)
    mapping = build_answer_page_mapping(
        regions=answer.regions,
        pages=pages,
        detection_meta=answer.detection_meta,
    )

    detail = AnswerDetail.model_validate(answer)
    detail.regions = [
        AnswerRegionOut.model_validate(r)
        for r in sorted(answer.regions, key=lambda r: (r.y0, r.x0))
    ]
    detail.pages = [
        AnswerPageOut(
            page_id=page.page_id,
            page_number=page.page_number,
            regions=[AnswerRegionOut.model_validate(r) for r in page.regions],
            uncertain=page.uncertain,
        )
        for page in mapping.pages
    ]
    detail.page_numbers = list(mapping.page_numbers)
    detail.page_mapping_uncertain = mapping.uncertain
    detail.page_mapping_source = mapping.source
    detail.question_label = answer.question.label
    detail.question_text = answer.question.text
    detail.question_type = answer.question.question_type
    detail.expected_answer = answer.question.expected_answer
    detail.guidance = answer.question.guidance
    detail.keywords = list(answer.question.keywords or [])
    detail.marking_scheme = [
        {
            "id": str(c.id),
            "name": c.name,
            "description": c.description,
            "max_marks": float(c.max_marks),
            "order_index": c.order_index,
        }
        for c in answer.question.criteria
    ]
    detail.evaluation = _evaluation_out(evaluation) if evaluation else None
    detail.ocr = await _ocr_out(db, answer)
    detail.reviews = [ReviewOut.model_validate(r) for r in sorted(answer.reviews, key=lambda r: r.created_at, reverse=True)]
    return detail


async def _ocr_out(db: DbSession, answer: Answer) -> OCRProvenanceOut | None:
    """OCR provenance for this answer's transcription (newest page result)."""
    row = (
        await db.execute(
            select(OCRResult)
            .join(SubmissionPage, OCRResult.page_id == SubmissionPage.id)
            .join(AnswerRegion, AnswerRegion.page_id == SubmissionPage.id)
            .where(AnswerRegion.answer_id == answer.id)
            .order_by(OCRResult.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    status = str((row.raw_response or {}).get("ocr_status") or "") or None
    return OCRProvenanceOut(
        model=row.model,
        provider=row.provider,
        prompt_version=row.prompt_version,
        confidence=row.confidence,
        duration_ms=row.duration_ms,
        ocr_status=status,
        is_mock=row.is_mock,
        completed_at=row.created_at,
    )


def _evaluation_out(evaluation) -> EvaluationOut:
    data = EvaluationOut.model_validate(evaluation)
    data.criteria = [
        EvaluationCriterionOut.model_validate(c) for c in evaluation.criteria
    ]
    data.needs_human_review = any(c.needs_human_review for c in evaluation.criteria) or any(
        "human review" in str(f).lower() for f in (evaluation.flags or [])
    )
    data.evaluation_completed_at = evaluation.created_at
    return data


@router.get("/answers/{answer_id}/evaluation", response_model=EvaluationOut)
async def get_evaluation(answer: OwnedAnswer, db: DbSession) -> EvaluationOut:
    evaluation = await evaluation_service.latest_evaluation(db, answer.id)
    if evaluation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This answer has not been evaluated yet.",
        )
    return _evaluation_out(evaluation)


@router.get("/answers/{answer_id}/evaluations", response_model=list[EvaluationOut])
async def evaluation_history(answer: OwnedAnswer, db: DbSession) -> list[EvaluationOut]:
    history = await evaluation_service.evaluation_history(db, answer.id)
    return [_evaluation_out(e) for e in history]


@router.post(
    "/answers/{answer_id}/evaluate",
    response_model=JobOut,
    dependencies=[Depends(_eval_limits)],
)
async def evaluate_answer(
    answer: OwnedAnswer,
    db: DbSession,
    user: CurrentUser,
    force: bool = Query(default=True, description="Re-evaluate even if a result exists."),
) -> JobOut:
    """Queue an (re-)evaluation of a single answer."""
    job = await job_service.enqueue(
        db,
        job_type=JobType.EVALUATE_ANSWER,
        submission_id=answer.submission_id,
        answer_id=answer.id,
        payload={"force": force},
    )
    await db.flush()
    await job_service.notify_pending()
    return JobOut.model_validate(job)


@router.patch("/answers/{answer_id}/transcription", response_model=AnswerDetail)
async def correct_transcription(
    payload: TranscriptionUpdate,
    answer: OwnedAnswer,
    db: DbSession,
    user: CurrentUser,
) -> AnswerDetail:
    """Save an examiner-corrected transcription for one answer.

    The AI suggestion is never overwritten in place: the original OCR output
    stays in ``ocr_results.raw_response`` (and ``Answer.transcription`` holds
    the examiner's text from now on), and the correction is recorded in the
    audit trail.
    """
    previous = answer.transcription
    answer.transcription = payload.transcription
    # The teacher read the script: the handwriting is no longer "uncertain".
    answer.is_handwriting_uncertain = False
    answer.detection_meta = {
        **(answer.detection_meta or {}),
        "transcription_corrected_by_examiner": True,
        "transcription_corrected_at": _now_iso(),
        "transcription_corrected_by": str(user.id),
    }
    await db.flush()
    await audit_service.record(
        db,
        action="answer.transcription_corrected",
        entity_type="answer",
        actor=user,
        entity_id=answer.id,
        description="Examiner corrected the AI transcription.",
        old_value={"transcription": previous},
        new_value={"transcription": answer.transcription},
    )
    return await get_answer(answer, db)


@router.put("/answers/{answer_id}/pages", response_model=AnswerDetail)
async def correct_page_mapping(
    payload: PageMappingUpdate,
    answer: OwnedAnswer,
    db: DbSession,
    user: CurrentUser,
) -> AnswerDetail:
    """Save an examiner-corrected answer ↔ page mapping.

    The mapping is stored under ``detection_meta.page_mapping_override`` and
    wins over anything detection inferred — question numbers are never
    assumed to equal page numbers. Existing overlay regions are kept, but the
    read path only shows regions on the corrected pages.
    """
    pages = await _submission_pages(db, answer.submission_id)
    known = {p.page_number for p in pages}
    unknown = [n for n in payload.page_numbers if n not in known]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Page(s) {', '.join(str(n) for n in unknown)} do not exist in "
                f"this submission (it has {len(pages)} page(s))."
            ),
        )

    previous = (answer.detection_meta or {}).get(PAGE_MAPPING_OVERRIDE_KEY)
    answer.detection_meta = {
        **(answer.detection_meta or {}),
        PAGE_MAPPING_OVERRIDE_KEY: {
            "page_numbers": list(payload.page_numbers),
            "updated_at": _now_iso(),
            "actor_id": str(user.id),
        },
    }
    await db.flush()
    await audit_service.record(
        db,
        action="answer.page_mapping_corrected",
        entity_type="answer",
        actor=user,
        entity_id=answer.id,
        description=(
            "Examiner corrected the pages this answer appears on: "
            + ", ".join(str(n) for n in payload.page_numbers)
        ),
        old_value={PAGE_MAPPING_OVERRIDE_KEY: previous},
        new_value={PAGE_MAPPING_OVERRIDE_KEY: answer.detection_meta.get(PAGE_MAPPING_OVERRIDE_KEY)},
    )
    return await get_answer(answer, db)


@router.put("/answers/{answer_id}/review", response_model=AnswerDetail)
async def review_answer(
    payload: ReviewRequest,
    answer: OwnedAnswer,
    db: DbSession,
    user: CurrentUser,
) -> AnswerDetail:
    """Record a teacher decision (accept / override / flag)."""
    try:
        await review_service.review_answer(db, answer=answer, actor=user, data=payload)
    except ReviewError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await db.flush()
    await db.refresh(answer)

    submission = await submission_service.get_submission(db, answer.submission_id)
    if submission is not None:
        from app.services import result_service

        await result_service.recompute_submission_totals(db, submission)

    return await get_answer(answer, db)


@router.get("/answers/{answer_id}/reviews", response_model=list[ReviewOut])
async def list_reviews(answer: OwnedAnswer, db: DbSession) -> list[ReviewOut]:
    reviews = await review_service.recent_reviews(db, answer.id)
    return [ReviewOut.model_validate(r) for r in reviews]
