"""Authentication and account services."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    password_problems,
    verify_password,
)
from app.db.enums import UserRole
from app.models.user import RefreshToken, User
from app.services import audit_service


class AuthError(Exception):
    """Domain-level authentication failure (maps to HTTP 401/400)."""


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    return (
        await db.execute(select(User).where(User.email == email.lower().strip()))
    ).scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()


async def register_user(
    db: AsyncSession,
    *,
    email: str,
    full_name: str,
    password: str,
    department: str | None = None,
    institution: str | None = None,
    role: UserRole = UserRole.TEACHER,
) -> User:
    email = email.lower().strip()
    if await get_user_by_email(db, email):
        raise AuthError("An account with this email already exists.")

    problems = password_problems(password)
    if problems:
        raise AuthError(" ".join(problems))

    user = User(
        email=email,
        full_name=full_name.strip(),
        hashed_password=hash_password(password),
        role=role,
        department=department,
        institution=institution,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    await audit_service.record(
        db,
        action="user.register",
        entity_type="user",
        actor=user,
        entity_id=user.id,
        description=f"Account created for {user.email}.",
    )
    return user


async def authenticate(db: AsyncSession, *, email: str, password: str) -> User:
    user = await get_user_by_email(db, email)
    if user is None or not verify_password(password, user.hashed_password):
        # Identical message for both cases: never reveal whether an email exists.
        raise AuthError("Invalid email or password.")
    if not user.is_active:
        raise AuthError("This account has been deactivated.")
    user.last_login_at = dt.datetime.now(dt.UTC)
    await db.flush()
    return user


async def issue_tokens(db: AsyncSession, user: User) -> tuple[str, str]:
    access = create_access_token(user.id, user.role.value)
    refresh = create_refresh_token(user.id, user.role.value)

    payload = decode_token(refresh, expected_type="refresh")
    record = RefreshToken(
        user_id=user.id,
        jti=payload["jti"],
        expires_at=dt.datetime.fromtimestamp(payload["exp"], tz=dt.UTC),
    )
    db.add(record)
    await db.flush()
    return access, refresh


async def refresh_tokens(db: AsyncSession, refresh_token: str) -> tuple[str, str, User]:
    try:
        payload = decode_token(refresh_token, expected_type="refresh")
    except TokenError as exc:
        raise AuthError(str(exc)) from exc

    record = (
        await db.execute(select(RefreshToken).where(RefreshToken.jti == payload["jti"]))
    ).scalar_one_or_none()
    if record is None or not record.is_usable:
        raise AuthError("Refresh token is no longer valid. Please sign in again.")

    user = await get_user_by_id(db, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise AuthError("Account is not available.")

    # Rotate: revoke the presented token, issue a new pair.
    record.revoked_at = dt.datetime.now(dt.UTC)
    await db.flush()
    access, new_refresh = await issue_tokens(db, user)
    return access, new_refresh, user


async def revoke_refresh_token(db: AsyncSession, refresh_token: str) -> None:
    try:
        payload = decode_token(refresh_token, expected_type="refresh")
    except TokenError:
        return  # already invalid: logging out is idempotent
    record = (
        await db.execute(select(RefreshToken).where(RefreshToken.jti == payload["jti"]))
    ).scalar_one_or_none()
    if record and record.revoked_at is None:
        record.revoked_at = dt.datetime.now(dt.UTC)
        await db.flush()


async def change_password(
    db: AsyncSession, user: User, *, current_password: str, new_password: str
) -> None:
    if not verify_password(current_password, user.hashed_password):
        raise AuthError("Current password is incorrect.")
    problems = password_problems(new_password)
    if problems:
        raise AuthError(" ".join(problems))
    user.hashed_password = hash_password(new_password)
    # Invalidate every existing session.
    for token in (
        await db.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)
            )
        )
    ).scalars():
        token.revoked_at = dt.datetime.now(dt.UTC)
    await db.flush()
    await audit_service.record(
        db,
        action="user.password_changed",
        entity_type="user",
        actor=user,
        entity_id=user.id,
        description="Password changed; all sessions invalidated.",
    )


def access_token_ttl_seconds() -> int:
    return settings.access_token_expire_minutes * 60
