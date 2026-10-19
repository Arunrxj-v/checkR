"""User accounts and refresh-token registry."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.enums import UserRole


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, native_enum=False, length=32, validate_strings=True),
        default=UserRole.TEACHER,
        nullable=False,
    )
    department: Mapped[str | None] = mapped_column(String(200))
    institution: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    exams: Mapped[list[Exam]] = relationship(  # noqa: F821
        back_populates="owner", cascade="all, delete-orphan"
    )

    @property
    def is_staff(self) -> bool:
        return self.role in (UserRole.ADMIN, UserRole.TEACHER, UserRole.EVALUATOR)


class RefreshToken(UUIDPrimaryKeyMixin, Base):
    """Persisted refresh-token records so tokens can be revoked on logout."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="refresh_tokens")

    @property
    def is_usable(self) -> bool:
        now = dt.datetime.now(dt.UTC)
        expires = self.expires_at
        # SQLite (tests) returns naive datetimes; treat them as UTC.
        if expires is not None and expires.tzinfo is None:
            expires = expires.replace(tzinfo=dt.UTC)
        revoked = self.revoked_at
        if revoked is not None and revoked.tzinfo is None:
            revoked = revoked.replace(tzinfo=dt.UTC)
        return revoked is None and expires is not None and expires > now
