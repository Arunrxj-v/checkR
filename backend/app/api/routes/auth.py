"""Authentication routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.api.rate_limit import limiter
from app.core.config import settings
from app.schemas.auth import (
    AuthEnvironment,
    DemoCredentials,
    LoginRequest,
    PasswordChange,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
    UserUpdate,
)
from app.schemas.common import Message
from app.services import auth_service
from app.services.auth_service import AuthError

router = APIRouter(prefix="/auth", tags=["auth"])

# Brute-force protection: these key on the client IP because no user is
# authenticated yet.
_login_limits = limiter(10, 60, scope="auth.login")
_register_limits = limiter(10, 60, scope="auth.register")


@router.get("/environment", response_model=AuthEnvironment)
async def environment() -> AuthEnvironment:
    """Public sign-in configuration for the SPA.

    Tells the client whether account creation is offered and, in development
    only, which demo account is seeded. Never returns credentials in
    production — see :attr:`Settings.demo_credentials`.
    """
    credentials = settings.demo_credentials
    return AuthEnvironment(
        environment=settings.environment,
        self_registration_enabled=settings.self_registration_enabled,
        demo_credentials=(
            DemoCredentials(email=credentials[0], password=credentials[1])
            if credentials
            else None
        ),
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_register_limits)],
)
async def register(payload: RegisterRequest, db: DbSession) -> TokenResponse:
    if not settings.self_registration_enabled:
        # Institution-controlled provisioning is the default. The SPA hides the
        # link, but the server is the authority.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Account creation is managed by your institution. "
                "Contact your administrator for access."
            ),
        )
    try:
        user = await auth_service.register_user(
            db,
            email=payload.email,
            full_name=payload.full_name,
            password=payload.password,
            department=payload.department,
            institution=payload.institution,
        )
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    access, refresh = await auth_service.issue_tokens(db, user)
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=auth_service.access_token_ttl_seconds(),
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(_login_limits)])
async def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    try:
        user = await auth_service.authenticate(db, email=payload.email, password=payload.password)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    access, refresh = await auth_service.issue_tokens(db, user)
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=auth_service.access_token_ttl_seconds(),
        user=UserOut.model_validate(user),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, db: DbSession) -> TokenResponse:
    try:
        access, new_refresh, user = await auth_service.refresh_tokens(db, payload.refresh_token)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return TokenResponse(
        access_token=access,
        refresh_token=new_refresh,
        expires_in=auth_service.access_token_ttl_seconds(),
        user=UserOut.model_validate(user),
    )


@router.post("/logout", response_model=Message)
async def logout(payload: RefreshRequest, db: DbSession) -> Message:
    await auth_service.revoke_refresh_token(db, payload.refresh_token)
    return Message(detail="Signed out.")


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.post("/password", response_model=Message)
async def change_password(
    payload: PasswordChange, db: DbSession, user: CurrentUser
) -> Message:
    try:
        await auth_service.change_password(
            db,
            user,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return Message(detail="Password changed. Please sign in again.")


@router.patch("/me", response_model=UserOut)
async def update_me(payload: UserUpdate, db: DbSession, user: CurrentUser) -> UserOut:
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(user, field, value)
    await db.flush()
    return UserOut.model_validate(user)
