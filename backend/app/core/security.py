"""Password hashing and JWT token handling.

Passwords are hashed with bcrypt (never stored in plaintext). Tokens are signed
JWTs carrying the user id, role and a token-type claim so that refresh tokens
cannot be used as access tokens.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal
from uuid import UUID, uuid4

import bcrypt
import jwt
from jwt import ExpiredSignatureError, InvalidTokenError

from app.core.config import settings

TokenType = Literal["access", "refresh"]

_BCRYPT_MAX_BYTES = 72


class TokenError(Exception):
    """Raised when a JWT is missing, malformed, expired or of the wrong type."""


# --------------------------------------------------------------------------- #
# Password hashing
# --------------------------------------------------------------------------- #
def hash_password(plain: str) -> str:
    if plain is None:
        raise ValueError("password must not be None")
    raw = plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    if not plain or not hashed:
        return False
    try:
        raw = plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]
        return bcrypt.checkpw(raw, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def password_problems(password: str) -> list[str]:
    """Minimal, sensible password policy shared by API and tests."""
    problems: list[str] = []
    if len(password or "") < 8:
        problems.append("Password must be at least 8 characters long.")
    if (password or "").strip() != (password or ""):
        problems.append("Password must not start or end with whitespace.")
    if not any(c.isalpha() for c in password or ""):
        problems.append("Password must contain at least one letter.")
    if not any(c.isdigit() for c in password or ""):
        problems.append("Password must contain at least one digit.")
    return problems


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #
def _create_token(
    *,
    subject: str,
    token_type: TokenType,
    expires_delta: dt.timedelta,
    extra: dict[str, Any] | None = None,
) -> str:
    now = dt.datetime.now(dt.UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "jti": str(uuid4()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(
    user_id: UUID | str, role: str, extra: dict[str, Any] | None = None
) -> str:
    return _create_token(
        subject=str(user_id),
        token_type="access",
        expires_delta=dt.timedelta(minutes=settings.access_token_expire_minutes),
        extra={"role": role, **(extra or {})},
    )


def create_refresh_token(user_id: UUID | str, role: str) -> str:
    return _create_token(
        subject=str(user_id),
        token_type="refresh",
        expires_delta=dt.timedelta(days=settings.refresh_token_expire_days),
        extra={"role": role},
    )


def decode_token(token: str, *, expected_type: TokenType | None = None) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except ExpiredSignatureError as exc:  # token lifetime ended
        raise TokenError("Token has expired.") from exc
    except InvalidTokenError as exc:
        raise TokenError("Token is invalid.") from exc

    if expected_type and payload.get("type") != expected_type:
        raise TokenError(f"Expected a {expected_type} token.")
    return payload
