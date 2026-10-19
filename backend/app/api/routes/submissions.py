"""Submission intake, pages, file access and reprocessing routes."""

from __future__ import annotations

import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, OwnedSubmission, get_owned_exam
from app.api.rate_limit import limiter
from app.db.enums import (
    JobType,
    SubmissionStatus,
    UserRole,
)
from app.models.answer import Answer
from app.models.exam import Exam
from app.models.job import ProcessingJob
from app.models.submission import Submission
from app.schemas.common import Message, Page
from app.schemas.job import JobOut
from app.schemas.submission import (
    PageOut,
    SubmissionCreate,
    SubmissionDetail,
    SubmissionOut,
    SubmissionStatusOut,
    SubmissionUpdate,
)
from app.services import job_service, submission_service
from app.services.submission_service import UploadError
from app.storage import get_storage

router = APIRouter(tags=["submissions"])

_upload_limits = limiter(60, 60, scope="upload")
_eval_limits = limiter(120, 60, scope="evaluate")


# --------------------------------------------------------------------------- #
# Upload
# --------------------------------------------------------------------------- #
@router.post(
    "/exams/{exam_id}/submissions",
    response_model=list[SubmissionOut],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_upload_limits)],
)
async def upload_submissions(
    exam_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    files: list[UploadFile] = File(...),
    student_name: str | None = Form(default=None),
    student_roll: str | None = Form(default=None),
) -> list[SubmissionOut]:
    """Upload one or more answer-sheet files.

    Each uploaded file becomes its own submission (one file = one student's
    script). When several files are uploaded, per-student metadata is taken from
    the filename unless a single name/roll pair is supplied for one file.
    """
    exam = await get_owned_exam(exam_id, db, user)
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files uploaded.")
    if len(files) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Upload at most 100 files at once."
        )

    single = len(files) == 1
    created = []
    for upload in files:
        data = await upload.read()
        filename = upload.filename or "answer-sheet"
        try:
            submission = await submission_service.create_submission(
                db,
                exam=exam,
                actor=user,
                data=data,
                filename=filename,
                content_type=upload.content_type,
                student_name=student_name if single else _name_from_filename(filename),
                student_roll=student_roll if single else None,
            )
        except UploadError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{filename}: {exc}",
            ) from exc
        created.append(SubmissionOut.model_validate(submission))

    await db.flush()
    return created


def _name_from_filename(filename: str) -> str | None:
    stem = filename.rsplit("/", 1)[-1]
    stem = stem.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").strip()
    return stem.title()[:200] or None


@router.post(
    "/submissions",
    response_model=SubmissionOut,
    status_code=status.HTTP_201_CREATED,
    deprecated=True,
    summary="Deprecated: upload against an exam instead.",
)
async def create_submission_placeholder(
    payload: SubmissionCreate, db: DbSession, user: CurrentUser
) -> SubmissionOut:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Upload answer sheets using POST /exams/{exam_id}/submissions (multipart).",
    )


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
@router.get("/submissions", response_model=Page[SubmissionOut])
async def list_submissions(
    db: DbSession,
    user: CurrentUser,
    exam_id: uuid.UUID | None = Query(default=None),
    status_filter: SubmissionStatus | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[SubmissionOut]:
    if exam_id is not None:
        await get_owned_exam(exam_id, db, user)  # authorisation

    conditions = []
    # Scope to the caller's examinations unless they are an admin.
    if user.role != UserRole.ADMIN:
        owned = select(Exam.id).where(Exam.owner_id == user.id)
        conditions.append(Submission.exam_id.in_(owned))

    if exam_id is not None:
        conditions.append(Submission.exam_id == exam_id)
    if status_filter is not None:
        conditions.append(Submission.status == status_filter)
    if search:
        like = f"%{search.strip().lower()}%"
        conditions.append(
            func.lower(func.coalesce(Submission.student_name, "")).like(like)
            | func.lower(func.coalesce(Submission.student_roll, "")).like(like)
        )

    base = select(Submission)
    if conditions:
        base = base.where(*conditions)
    total = int(
        (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    )
    rows = (
        await db.execute(
            base.order_by(Submission.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return Page[SubmissionOut](
        items=[SubmissionOut.model_validate(s) for s in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/submissions/{submission_id}", response_model=SubmissionDetail)
async def get_submission(
    submission: OwnedSubmission, db: DbSession
) -> SubmissionDetail:
    full = await submission_service.get_submission(db, submission.id, with_pages=True)
    counts = await submission_service.ingroup_counts(db, submission.id)
    reviewed = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Answer)
                .where(Answer.submission_id == submission.id, Answer.is_reviewed.is_(True))
            )
        ).scalar_one()
    )
    detail = SubmissionDetail.model_validate(full)
    detail.pages = [
        PageOut(
            id=page.id,
            page_number=page.page_number,
            width=page.width,
            height=page.height,
            status=page.status,
            ocr_confidence=page.ocr_confidence,
            rotation_degrees=page.rotation_degrees,
            deskew_angle=page.deskew_angle,
            error_message=page.error_message,
            has_thumbnail=bool(page.thumbnail_storage_key),
        )
        for page in full.pages
    ]
    detail.answer_count = counts["answer_count"]
    detail.evaluated_count = counts["evaluated_count"]
    detail.reviewed_count = reviewed
    return detail


@router.get("/submissions/{submission_id}/status", response_model=SubmissionStatusOut)
async def submission_status(submission: OwnedSubmission, db: DbSession) -> SubmissionStatusOut:
    counts = await submission_service.ingroup_counts(db, submission.id)
    stage_messages = {
        SubmissionStatus.UPLOADED: "Queued for processing.",
        SubmissionStatus.PROCESSING: "Extracting and preparing pages.",
        SubmissionStatus.OCR_PROCESSING: "Reading handwriting.",
        SubmissionStatus.ANSWERS_DETECTED: "Matching answers to questions.",
        SubmissionStatus.AI_EVALUATING: "Evaluating answers against the marking scheme.",
        SubmissionStatus.READY_FOR_REVIEW: "Ready for your review.",
        SubmissionStatus.REVIEWED: "Reviewed — awaiting finalisation.",
        SubmissionStatus.COMPLETED: "Result finalised.",
        SubmissionStatus.FAILED: "Processing failed.",
    }
    return SubmissionStatusOut(
        id=submission.id,
        status=submission.status,
        page_count=submission.page_count,
        processed_page_count=submission.processed_page_count,
        answer_count=counts["answer_count"],
        evaluated_count=counts["evaluated_count"],
        flagged_count=submission.flagged_count,
        error_message=submission.error_message,
        stage_message=stage_messages.get(submission.status),
    )


@router.patch("/submissions/{submission_id}", response_model=SubmissionOut)
async def update_submission(
    payload: SubmissionUpdate, submission: OwnedSubmission, db: DbSession
) -> SubmissionOut:
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(submission, field, value)
    await db.flush()
    return SubmissionOut.model_validate(submission)


@router.delete("/submissions/{submission_id}", response_model=Message)
async def delete_submission(
    submission: OwnedSubmission, db: DbSession, user: CurrentUser
) -> Message:
    await submission_service.delete_submission(db, submission=submission, actor=user)
    return Message(detail="Submission deleted.")


# --------------------------------------------------------------------------- #
# Pages & files
# --------------------------------------------------------------------------- #
@router.get("/submissions/{submission_id}/pages", response_model=list[PageOut])
async def list_pages(submission: OwnedSubmission, db: DbSession) -> list[PageOut]:
    pages = await submission_service.list_pages(db, submission.id)
    return [
        PageOut(
            id=p.id,
            page_number=p.page_number,
            width=p.width,
            height=p.height,
            status=p.status,
            ocr_confidence=p.ocr_confidence,
            rotation_degrees=p.rotation_degrees,
            deskew_angle=p.deskew_angle,
            error_message=p.error_message,
            has_thumbnail=bool(p.thumbnail_storage_key),
        )
        for p in pages
    ]


@router.get("/pages/{page_id}/image")
async def page_image(
    page_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    variant: str = Query(default="processed", pattern="^(processed|original|thumbnail)$"),
) -> Response:
    """Stream a page image.

    Files are private: access is authorised against the owning exam on every
    request and never served from a public URL.
    """
    page = await submission_service.get_page(db, page_id)
    if page is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found.")
    submission = await submission_service.get_submission(db, page.submission_id)
    if submission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found.")
    await get_owned_exam(submission.exam_id, db, user)

    key = {
        "processed": page.processed_storage_key or page.original_storage_key,
        "original": page.original_storage_key,
        "thumbnail": page.thumbnail_storage_key or page.processed_storage_key or page.original_storage_key,
    }[variant]
    if not key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This page has not been processed yet.",
        )

    try:
        data = await get_storage().read(key)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Page image unavailable: {exc}"
        ) from exc

    media_type = "image/jpeg" if key.endswith(".jpg") else "image/png"
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/pages/{page_id}/retry", response_model=JobOut)
async def retry_page(
    page_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    mode: str = Query(default="full", pattern="^(full|ocr)$"),
) -> JobOut:
    """Re-run preprocessing + OCR (``full``) or OCR only for one page."""
    page = await submission_service.get_page(db, page_id)
    if page is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found.")
    submission = await submission_service.get_submission(db, page.submission_id)
    if submission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found.")
    await get_owned_exam(submission.exam_id, db, user)

    job = await job_service.enqueue(
        db,
        job_type=JobType.PREPROCESS_PAGE if mode == "full" else JobType.OCR_PAGE,
        submission_id=submission.id,
        page_id=page.id,
    )
    await db.flush()
    await job_service.notify_pending()
    return JobOut.model_validate(job)


# --------------------------------------------------------------------------- #
# Reprocessing
# --------------------------------------------------------------------------- #
@router.post(
    "/submissions/{submission_id}/process",
    response_model=JobOut,
    dependencies=[Depends(_eval_limits)],
)
async def reprocess_submission(
    submission: OwnedSubmission,
    db: DbSession,
    user: CurrentUser,
    force: bool = Query(default=False, description="Re-evaluate answers that already have a result."),
) -> JobOut:
    """Re-run the pipeline. With ``force=false`` completed work is reused."""
    await get_owned_exam(submission.exam_id, db, user)

    if force:
        submission.status = SubmissionStatus.ANSWERS_DETECTED
        job = await job_service.enqueue(
            db,
            job_type=JobType.EVALUATE_SUBMISSION,
            submission_id=submission.id,
            payload={"force": True},
        )
    else:
        submission.status = SubmissionStatus.PROCESSING
        job = await job_service.enqueue(
            db,
            job_type=JobType.PROCESS_SUBMISSION,
            submission_id=submission.id,
            payload={"content_type": submission.original_content_type},
        )
    await db.flush()
    await job_service.notify_pending()
    return JobOut.model_validate(job)


@router.get("/submissions/{submission_id}/jobs", response_model=list[JobOut])
async def submission_jobs(submission: OwnedSubmission, db: DbSession) -> list[JobOut]:
    jobs = (
        await db.execute(
            select(ProcessingJob)
            .where(ProcessingJob.submission_id == submission.id)
            .order_by(ProcessingJob.created_at.desc())
            .limit(50)
        )
    ).scalars().all()
    return [JobOut.model_validate(j) for j in jobs]
