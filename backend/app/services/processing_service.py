"""Async processing pipeline.

Stages, each resumable and independently retryable:

  1. ``process_submission`` — extract/validate pages, preprocess, transcribe.
  2. ``segment_answers``    — associate written content with questions.
  3. ``evaluate_submission``— AI-evaluate every detected answer.
  4. ``preprocess_page`` / ``ocr_page`` — repair a single failed page.
  5. ``generate_result``    — recompute totals.

Nothing here blocks an HTTP request: the API only enqueues jobs.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.factory import get_provider
from app.ai.validation import validate_ocr
from app.core.config import settings
from app.core.logging import get_logger
from app.db.enums import (
    AnswerStatus,
    JobType,
    PageStatus,
    SubmissionStatus,
)
from app.imaging import (
    DocumentError,
    is_pdf,
    normalise_upload_image,
    preprocess_page,
    render_pdf_pages,
)
from app.models.answer import Answer, AnswerRegion, OCRResult
from app.models.exam import Question
from app.models.job import ProcessingJob
from app.models.submission import Submission, SubmissionPage
from app.prompts.registry import CURRENT_OCR_PROMPT_VERSION
from app.segmentation import segment_answers
from app.services import evaluation_service, job_service, result_service
from app.services.page_mapping import resolve_region_page
from app.storage import KeySpace, build_key, get_storage

logger = get_logger(__name__)


class ProcessingError(Exception):
    """Raised when a stage cannot complete."""


# --------------------------------------------------------------------------- #
# Page extraction & preprocessing
# --------------------------------------------------------------------------- #
async def _extract_pages(db: AsyncSession, submission: Submission, content_type: str) -> int:
    """Rasterise the original upload into page images and store them."""
    storage = get_storage()
    if not submission.original_storage_key:
        raise ProcessingError("Submission has no stored original file.")

    data = await storage.read(submission.original_storage_key)

    if is_pdf(content_type, submission.original_filename, data):
        rendered = render_pdf_pages(data, max_pages=settings.max_submission_pages)
        source_pages = [
            (p.page_number, p.image_bytes, p.width, p.height, "image/png") for p in rendered
        ]
    else:
        normalised = normalise_upload_image(data, content_type=content_type)
        source_pages = [(1, normalised, None, None, "image/png")]

    # Replace any previously extracted pages (idempotent re-run).
    existing = (
        await db.execute(
            select(SubmissionPage).where(SubmissionPage.submission_id == submission.id)
        )
    ).scalars().all()
    if existing:
        for page in existing:
            await db.delete(page)
        await db.flush()

    for page_number, image_bytes, width, height, mime in source_pages:
        key = build_key(
            KeySpace.PAGES, str(submission.id), f"page_{page_number:03d}_original.png"
        )
        await storage.save(key, image_bytes, content_type=mime)
        db.add(
            SubmissionPage(
                submission_id=submission.id,
                page_number=page_number,
                original_storage_key=key,
                width=width,
                height=height,
                status=PageStatus.UPLOADED,
            )
        )

    submission.page_count = len(source_pages)
    submission.processed_page_count = 0
    await db.flush()
    return len(source_pages)


async def _preprocess_and_store(page: SubmissionPage) -> None:
    storage = get_storage()
    raw = await storage.read(page.original_storage_key)
    result = preprocess_page(raw)

    processed_key = build_key(
        KeySpace.PROCESSED, str(page.submission_id), f"page_{page.page_number:03d}.jpg"
    )
    thumb_key = build_key(
        KeySpace.THUMBNAILS, str(page.submission_id), f"page_{page.page_number:03d}.jpg"
    )
    await storage.save(processed_key, result.processed, content_type="image/jpeg")
    await storage.save(thumb_key, result.thumbnail, content_type="image/jpeg")

    page.processed_storage_key = processed_key
    page.thumbnail_storage_key = thumb_key
    page.width = result.width
    page.height = result.height
    page.deskew_angle = result.deskew_angle
    page.preprocessing_meta = {
        "applied": result.applied,
        "rotation_degrees": result.rotation_degrees,
        "deskew_angle": result.deskew_angle,
    }
    page.status = PageStatus.PREPROCESSED


async def _transcribe_page(db: AsyncSession, page: SubmissionPage, *, force: bool = False) -> None:
    """OCR a page, reusing an existing result unless ``force`` is set."""
    if not force:
        existing = (
            await db.execute(
                select(OCRResult)
                .where(
                    OCRResult.page_id == page.id,
                    OCRResult.prompt_version == CURRENT_OCR_PROMPT_VERSION,
                )
                .order_by(OCRResult.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            page.ocr_confidence = existing.confidence
            page.status = PageStatus.OCR_DONE
            return

    storage = get_storage()
    key = page.processed_storage_key or page.original_storage_key
    image = await storage.read(key)

    provider = get_provider()
    raw_result = await provider.transcribe_page(
        image, page_number=page.page_number, prompt_version=CURRENT_OCR_PROMPT_VERSION
    )
    result = validate_ocr(raw_result)

    # Keep a single current OCR row per page + prompt version.
    await db.execute(
        delete(OCRResult).where(
            OCRResult.page_id == page.id,
            OCRResult.prompt_version == CURRENT_OCR_PROMPT_VERSION,
        )
    )
    db.add(
        OCRResult(
            page_id=page.id,
            provider=result.provider or provider.name,
            model=result.model or provider.model,
            prompt_version=result.prompt_version or CURRENT_OCR_PROMPT_VERSION,
            text=result.text,
            confidence=result.confidence,
            regions=result.regions,
            raw_response=result.raw if isinstance(result.raw, dict) else {},
            is_mock=result.is_mock,
        )
    )
    page.ocr_confidence = result.confidence
    page.status = PageStatus.OCR_DONE
    page.error_message = None
    await db.flush()


# --------------------------------------------------------------------------- #
# Stage 1: full submission processing
# --------------------------------------------------------------------------- #
async def process_submission(db: AsyncSession, job: ProcessingJob) -> None:
    submission = (
        await db.execute(
            select(Submission)
            .where(Submission.id == job.submission_id)
            .options(selectinload(Submission.pages))
        )
    ).scalar_one_or_none()
    if submission is None:
        raise ProcessingError("Submission no longer exists.")

    content_type = (job.payload or {}).get("content_type") or submission.original_content_type
    submission.status = SubmissionStatus.PROCESSING
    submission.error_message = None
    await db.flush()

    try:
        await _extract_pages(db, submission, content_type or "")
    except DocumentError as exc:
        submission.status = SubmissionStatus.FAILED
        submission.error_message = str(exc)
        await db.flush()
        raise ProcessingError(str(exc)) from exc

    pages = await _load_pages(db, submission.id)
    submission.status = SubmissionStatus.OCR_PROCESSING
    await db.flush()

    processed = 0
    failed_pages: list[int] = []
    for page in pages:
        try:
            await _preprocess_and_store(page)
            await db.flush()
            await _transcribe_page(db, page)
            await db.flush()
            processed += 1
        except Exception as exc:  # one bad page must not kill the batch
            logger.warning("Page %s of %s failed: %s", page.page_number, submission.id, exc)
            page.status = PageStatus.FAILED
            page.error_message = str(exc)[:500]
            failed_pages.append(page.page_number)
            await db.flush()

        submission.processed_page_count = processed
        await db.flush()

    if processed == 0:
        submission.status = SubmissionStatus.FAILED
        submission.error_message = "No pages could be processed. Check the scan quality."
        await db.flush()
        raise ProcessingError("No pages could be processed.")

    submission.processing_meta = {
        **(submission.processing_meta or {}),
        "failed_pages": failed_pages,
        "ocr_prompt_version": CURRENT_OCR_PROMPT_VERSION,
    }
    await db.flush()

    # Continue the chain.
    await job_service.enqueue(
        db,
        job_type=JobType.SEGMENT_ANSWERS,
        submission_id=submission.id,
    )
    await db.flush()
    await job_service.notify_pending()


# --------------------------------------------------------------------------- #
# Stage 2: segmentation
# --------------------------------------------------------------------------- #
async def _load_pages(db: AsyncSession, submission_id: uuid.UUID) -> list[SubmissionPage]:
    return list(
        (
            await db.execute(
                select(SubmissionPage)
                .where(SubmissionPage.submission_id == submission_id)
                .order_by(SubmissionPage.page_number)
            )
        ).scalars().all()
    )


async def segment_answers_job(db: AsyncSession, job: ProcessingJob) -> None:
    submission = (
        await db.execute(select(Submission).where(Submission.id == job.submission_id))
    ).scalar_one_or_none()
    if submission is None:
        raise ProcessingError("Submission no longer exists.")

    pages = await _load_pages(db, submission.id)
    questions = list(
        (
            await db.execute(
                select(Question)
                .where(Question.exam_id == submission.exam_id)
                .options(selectinload(Question.criteria))
                .order_by(Question.order_index, Question.number)
            )
        ).scalars().all()
    )
    if not questions:
        submission.status = SubmissionStatus.FAILED
        submission.error_message = "This examination has no questions defined."
        await db.flush()
        raise ProcessingError("Exam has no questions.")

    pages_ocr: list[dict] = []
    for page in pages:
        ocr = (
            await db.execute(
                select(OCRResult)
                .where(OCRResult.page_id == page.id)
                .order_by(OCRResult.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        pages_ocr.append(
            {
                "page_id": str(page.id),
                "page_number": page.page_number,
                "text": ocr.text if ocr else "",
                "regions": ocr.regions if ocr else [],
                "confidence": ocr.confidence if ocr else None,
            }
        )

    segmentation = segment_answers(
        pages_ocr, known_question_numbers=[q.number for q in questions]
    )
    detected: dict[int, Any] = segmentation["answers"]

    # Rebuild answers for this submission from scratch (idempotent re-run).
    existing = (
        await db.execute(select(Answer).where(Answer.submission_id == submission.id))
    ).scalars().all()
    for answer in existing:
        await db.delete(answer)
    await db.flush()

    page_id_by_number = {page.page_number: page for page in pages}
    page_id_by_id = {str(page.id): page for page in pages}

    for index, question in enumerate(questions):
        block = detected.get(question.number)
        transcription = block.transcription if block else ""
        ocr_conf = block.confidence if block else None
        uncertain = bool(block.boundary_uncertain) if block else True

        answer = Answer(
            submission_id=submission.id,
            question_id=question.id,
            order_index=index,
            status=AnswerStatus.PENDING,
            transcription=transcription or None,
            ocr_confidence=ocr_conf,
            max_marks=question.max_marks,
            is_handwriting_uncertain=uncertain,
            detection_meta={
                "has_content": bool(transcription.strip()),
                "source_pages": block.page_numbers if block else [],
            },
        )
        if not transcription.strip():
            answer.is_flagged = True
            answer.flag_reason = "No answer was detected for this question. Verify manually."
        db.add(answer)
        await db.flush()

        if block:
            for region in block.regions:
                page = resolve_region_page(
                    region,
                    pages_by_id=page_id_by_id,
                    pages_by_number=page_id_by_number,
                )
                if page is None:
                    # No resolvable page reference: drop the region rather than
                    # inventing an association with the first page.
                    continue
                db.add(
                    AnswerRegion(
                        answer_id=answer.id,
                        page_id=page.id,
                        x0=float(region.get("x0", 0.0)),
                        y0=float(region.get("y0", 0.0)),
                        x1=float(region.get("x1", 1.0)),
                        y1=float(region.get("y1", 1.0)),
                        label=(region.get("text") or "")[:120] or None,
                        confidence=region.get("confidence") or ocr_conf,
                    )
                )
        await db.flush()

    submission.status = SubmissionStatus.ANSWERS_DETECTED
    await result_service.recompute_submission_totals(db, submission)

    await job_service.enqueue(
        db,
        job_type=JobType.EVALUATE_SUBMISSION,
        submission_id=submission.id,
        payload={"force": False},
    )
    await db.flush()
    await job_service.notify_pending()


# --------------------------------------------------------------------------- #
# Stage 3: evaluation
# --------------------------------------------------------------------------- #
async def evaluate_submission(db: AsyncSession, job: ProcessingJob) -> None:
    submission = (
        await db.execute(select(Submission).where(Submission.id == job.submission_id))
    ).scalar_one_or_none()
    if submission is None:
        raise ProcessingError("Submission no longer exists.")

    force = bool((job.payload or {}).get("force"))
    answers = list(
        (
            await db.execute(
                select(Answer)
                .where(Answer.submission_id == submission.id)
                .options(selectinload(Answer.question).selectinload(Question.criteria))
                .order_by(Answer.order_index)
            )
        ).scalars().all()
    )

    submission.status = SubmissionStatus.AI_EVALUATING
    await db.flush()

    evaluated = 0
    failures = 0
    for answer in answers:
        if answer.is_reviewed and not force:
            continue
        if answer.ai_score is not None and not force:
            continue
        try:
            result = await evaluation_service.evaluate_answer(
                db, answer=answer, question=answer.question, force=force
            )
            if result is not None:
                evaluated += 1
        except Exception as exc:  # keep going; surface at the end
            logger.warning("Evaluation error for answer %s: %s", answer.id, exc)
            failures += 1
            await db.rollback()
            # Re-fetch in a clean state so the loop can continue.
            submission = (
                await db.execute(select(Submission).where(Submission.id == job.submission_id))
            ).scalar_one()
        await db.flush()

    submission = (
        await db.execute(select(Submission).where(Submission.id == job.submission_id))
    ).scalar_one()
    await result_service.recompute_submission_totals(db, submission)

    any_evaluated = any(a.ai_score is not None for a in answers)
    if any_evaluated:
        submission.status = SubmissionStatus.READY_FOR_REVIEW
        submission.error_message = None
    elif failures:
        submission.status = SubmissionStatus.FAILED
        submission.error_message = "AI evaluation failed for every answer. See job logs."
    await db.flush()


async def evaluate_answer_job(db: AsyncSession, job: ProcessingJob) -> None:
    answer = (
        await db.execute(
            select(Answer)
            .where(Answer.id == job.answer_id)
            .options(selectinload(Answer.question).selectinload(Question.criteria))
        )
    ).scalar_one_or_none()
    if answer is None:
        raise ProcessingError("Answer no longer exists.")

    force = bool((job.payload or {}).get("force", True))
    await evaluation_service.evaluate_answer(
        db, answer=answer, question=answer.question, force=force
    )
    submission = (
        await db.execute(select(Submission).where(Submission.id == answer.submission_id))
    ).scalar_one()
    await result_service.recompute_submission_totals(db, submission)


# --------------------------------------------------------------------------- #
# Per-page repair
# --------------------------------------------------------------------------- #
async def preprocess_page_job(db: AsyncSession, job: ProcessingJob) -> None:
    page = (
        await db.execute(select(SubmissionPage).where(SubmissionPage.id == job.page_id))
    ).scalar_one_or_none()
    if page is None:
        raise ProcessingError("Page no longer exists.")
    await _preprocess_and_store(page)
    page.error_message = None
    await db.flush()
    await _transcribe_page(db, page, force=True)
    await db.flush()
    await job_service.enqueue(
        db, job_type=JobType.SEGMENT_ANSWERS, submission_id=page.submission_id
    )
    await db.flush()
    await job_service.notify_pending()


async def ocr_page_job(db: AsyncSession, job: ProcessingJob) -> None:
    page = (
        await db.execute(select(SubmissionPage).where(SubmissionPage.id == job.page_id))
    ).scalar_one_or_none()
    if page is None:
        raise ProcessingError("Page no longer exists.")
    await _transcribe_page(db, page, force=True)
    await db.flush()
    await job_service.enqueue(
        db, job_type=JobType.SEGMENT_ANSWERS, submission_id=page.submission_id
    )
    await db.flush()
    await job_service.notify_pending()


async def generate_result(db: AsyncSession, job: ProcessingJob) -> None:
    submission = (
        await db.execute(select(Submission).where(Submission.id == job.submission_id))
    ).scalar_one_or_none()
    if submission is None:
        raise ProcessingError("Submission no longer exists.")
    await result_service.recompute_submission_totals(db, submission)


# --------------------------------------------------------------------------- #
# Registry consumed by the worker
# --------------------------------------------------------------------------- #
HANDLERS: dict[JobType, Callable[[AsyncSession, ProcessingJob], Awaitable[None]]] = {
    JobType.PROCESS_SUBMISSION: process_submission,
    JobType.SEGMENT_ANSWERS: segment_answers_job,
    JobType.EVALUATE_SUBMISSION: evaluate_submission,
    JobType.EVALUATE_ANSWER: evaluate_answer_job,
    JobType.PREPROCESS_PAGE: preprocess_page_job,
    JobType.OCR_PAGE: ocr_page_job,
    JobType.GENERATE_RESULT: generate_result,
}
