"""Authentication schemas."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.db.enums import UserRole
from app.schemas.common import ORMModel


class RegisterRequest(ORMModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=128)
    department: str | None = Field(default=None, max_length=200)
    institution: str | None = Field(default=None, max_length=200)

    @field_validator("full_name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Full name must not be empty.")
        return v


class LoginRequest(ORMModel):
    email: EmailStr
    password: str


class RefreshRequest(ORMModel):
    refresh_token: str


class TokenResponse(ORMModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class UserOut(ORMModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: UserRole
    department: str | None = None
    institution: str | None = None
    is_active: bool


class UserUpdate(ORMModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    department: str | None = Field(default=None, max_length=200)
    institution: str | None = Field(default=None, max_length=200)


class PasswordChange(ORMModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class DemoCredentials(BaseModel):
    """Development-only sign-in hint. Never populated in production."""

    email: str
    password: str


class AuthEnvironment(BaseModel):
    """Public sign-in configuration read by the SPA before anyone authenticates.

    Contains no secrets outside development: the server decides whether demo
    credentials may be shown and whether account creation is offered.
    """

    environment: str
    self_registration_enabled: bool = False
    demo_credentials: DemoCredentials | None = None


TokenResponse.model_rebuild()
