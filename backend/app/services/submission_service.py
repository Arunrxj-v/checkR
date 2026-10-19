"""Submission intake, retrieval and file access.

Uploads are validated (size, MIME, magic bytes) and the *original* artefact is
stored untouched. Page extraction happens asynchronously in the worker so a
50-page PDF never blocks an HTTP request.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.enums import JobType, SubmissionStatus
from app.models.exam import Exam
from app.models.submission import Submission, SubmissionPage
from app.models.user import User
from app.services import audit_service, job_service
from app.storage import KeySpace, build_key, get_storage

ALLOWED_CONTENT_TYPES = {
    "application/pdf": "pdf",
    "image/jpeg": "image",
    "image/jpg": "image",
    "image/png": "image",
}

_MAGIC = {
    b"%PDF-": "application/pdf",
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
}


class UploadError(Exception):
    """Raised when an upload is rejected."""


def sniff_content_type(data: bytes) -> str | None:
    for magic, ctype in _MAGIC.items():
        if data.startswith(magic):
            return ctype
    return None


def validate_upload(*, data: bytes, filename: str, content_type: str | None) -> str:
    """Return the verified content type, or raise :class:`UploadError`.

    The declared content type is only trusted when it agrees with the file's
    magic bytes; otherwise the sniffed type wins and a mismatch is rejected.
    """
    if not data:
        raise UploadError("The uploaded file is empty.")
    if len(data) > settings.max_upload_bytes:
        raise UploadError(
            f"File exceeds the {settings.max_upload_mb} MB upload limit "
            f"({len(data) / 1024 / 1024:.1f} MB)."
        )

    sniffed = sniff_content_type(data)
    if sniffed is None:
        raise UploadError(
            f"Unsupported file type for '{filename}'. Upload a PDF, JPG or PNG."
        )

    declared = (content_type or "").split(";")[0].strip().lower()
    declared = {"image/jpg": "image/jpeg", "image/pjpeg": "image/jpeg"}.get(
        declared, declared
    )

    if declared and declared in ALLOWED_CONTENT_TYPES and declared != sniffed:
        raise UploadError(
            f"'{filename}' does not look like a {declared.split('/')[-1].upper()} file."
        )

    return sniffed


async def create_submission(
    db: AsyncSession,
    *,
    exam: Exam,
    actor: User,
    data: bytes,
    filename: str,
    content_type: str | None,
    student_name: str | None = None,
    student_roll: str | None = None,
) -> Submission:
    verified_type = validate_upload(data=data, filename=filename, content_type=content_type)

    submission = Submission(
        exam_id=exam.id,
        created_by_id=actor.id,
        student_name=(student_name or "").strip() or None,
        student_roll=(student_roll or "").strip() or None,
        status=SubmissionStatus.UPLOADED,
        original_filename=filename[:400],
        original_content_type=verified_type,
        original_size_bytes=len(data),
    )
    db.add(submission)
    await db.flush()

    extension = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png"}[
        verified_type
    ]
    key = build_key(
        KeySpace.ORIGINAL, str(submission.id), f"source.{extension}"
    )
    storage = get_storage()
    await storage.save(key, data, content_type=verified_type)
    submission.original_storage_key = key

    await job_service.enqueue(
        db,
        job_type=JobType.PROCESS_SUBMISSION,
        submission_id=submission.id,
        payload={"content_type": verified_type},
    )
    await db.flush()

    await audit_service.record(
        db,
        action="submission.uploaded",
        entity_type="submission",
        actor=actor,
        entity_id=submission.id,
        description=f"Uploaded '{filename}' for exam '{exam.title}'.",
        new_value={"filename": filename, "size_bytes": len(data), "content_type": verified_type},
    )
    await job_service.notify_pending()
    return submission


async def list_submissions(
    db: AsyncSession,
    *,
    exam_id: uuid.UUID | None = None,
    status: SubmissionStatus | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Submission], int]:
    conditions = []
    if exam_id is not None:
        conditions.append(Submission.exam_id == exam_id)
    if status is not None:
        conditions.append(Submission.status == status)
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
    return list(rows), total


async def get_submission(
    db: AsyncSession, submission_id: uuid.UUID, *, with_pages: bool = False
) -> Submission | None:
    stmt = select(Submission).where(Submission.id == submission_id)
    if with_pages:
        stmt = stmt.options(selectinload(Submission.pages))
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_page(db: AsyncSession, page_id: uuid.UUID) -> SubmissionPage | None:
    return (
        await db.execute(select(SubmissionPage).where(SubmissionPage.id == page_id))
    ).scalar_one_or_none()


async def list_pages(db: AsyncSession, submission_id: uuid.UUID) -> list[SubmissionPage]:
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


async def delete_submission(
    db: AsyncSession, *, submission: Submission, actor: User
) -> None:
    await audit_service.record(
        db,
        action="submission.deleted",
        entity_type="submission",
        actor=actor,
        entity_id=submission.id,
        description="Submission and all derived artefacts deleted.",
        old_value={"student_roll": submission.student_roll},
    )
    await db.delete(submission)
    await db.flush()


async def ingroup_counts(db: AsyncSession, submission_id: uuid.UUID) -> dict:
    """Answer counts used by the processing/status screens."""
    from app.db.enums import AnswerStatus
    from app.models.answer import Answer

    total = int(
        (
            await db.execute(
                select(func.count()).select_from(Answer).where(Answer.submission_id == submission_id)
            )
        ).scalar_one()
    )
    evaluated = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Answer)
                .where(
                    Answer.submission_id == submission_id,
                    Answer.status.in_(
                        [AnswerStatus.EVALUATED, AnswerStatus.REVIEWED, AnswerStatus.FLAGGED]
                    ),
                )
            )
        ).scalar_one()
    )
    return {"answer_count": total, "evaluated_count": evaluated}
