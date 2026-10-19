"""Shared FastAPI dependencies: authentication, authorisation and lookups."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenError, decode_token
from app.db.enums import UserRole
from app.db.session import get_db
from app.models.answer import Answer
from app.models.exam import Exam
from app.models.submission import Submission
from app.models.user import User
from app.services import auth_service

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]

_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated.",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None or not credentials.credentials:
        raise _CREDENTIALS_EXCEPTION
    try:
        payload = decode_token(credentials.credentials, expected_type="access")
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise _CREDENTIALS_EXCEPTION from exc

    user = await auth_service.get_user_by_id(db, user_id)
    if user is None:
        raise _CREDENTIALS_EXCEPTION
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole):
    """Dependency factory enforcing that the caller holds one of ``roles``."""

    async def _guard(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return user

    return _guard


async def get_owned_exam(exam_id: uuid.UUID, db: DbSession, user: CurrentUser) -> Exam:
    exam = (
        await db.get(Exam, exam_id)
    )
    if exam is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Examination not found.")
    if exam.owner_id != user.id and user.role != UserRole.ADMIN:
        # Do not reveal existence to other teachers.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Examination not found.")
    return exam


OwnedExam = Annotated[Exam, Depends(get_owned_exam)]


async def get_owned_submission(
    submission_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> Submission:
    submission = await db.get(Submission, submission_id)
    if submission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found.")
    exam = await db.get(Exam, submission.exam_id)
    if exam is None or (exam.owner_id != user.id and user.role != UserRole.ADMIN):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found.")
    return submission


OwnedSubmission = Annotated[Submission, Depends(get_owned_submission)]


async def get_owned_answer(answer_id: uuid.UUID, db: DbSession, user: CurrentUser) -> Answer:
    answer = await db.get(Answer, answer_id)
    if answer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Answer not found.")
    submission = await db.get(Submission, answer.submission_id)
    if submission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Answer not found.")
    exam = await db.get(Exam, submission.exam_id)
    if exam is None or (exam.owner_id != user.id and user.role != UserRole.ADMIN):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Answer not found.")
    return answer


OwnedAnswer = Annotated[Answer, Depends(get_owned_answer)]
