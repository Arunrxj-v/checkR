"""Application configuration.

All runtime configuration is sourced from environment variables (see `.env.example`).
Nothing secret is ever hard-coded here — missing secrets fall back to safe,
development-only values and are surfaced by :func:`Settings.warnings`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/

AIProviderName = Literal["mock", "gemini", "openai", "anthropic", "local"]
StorageProviderName = Literal["local", "s3"]
Environment = Literal["development", "production", "test"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BASE_DIR / ".env", BASE_DIR.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application ---
    app_name: str = "CheckR"
    environment: Environment = "development"
    debug: bool = True
    api_prefix: str = "/api"
    frontend_origin: str = "http://localhost:5173"
    backend_origin: str = "http://localhost:8000"

    # --- Database ---
    database_url: str = "postgresql+asyncpg://checkr:checkr@localhost:5432/checkr"
    database_url_sync: str = "postgresql+psycopg://checkr:checkr@localhost:5432/checkr"

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Auth ---
    jwt_secret: str = "insecure-development-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14

    #: Whether the sign-in screen offers self-service account creation. Off by
    #: default: CheckR is deployed as institution-controlled infrastructure and
    #: accounts are provisioned by an administrator. Only enable open sign-up
    #: when it is a deliberate decision for the deployment.
    self_registration_enabled: bool = False

    #: Tri-state override for the development demo-credentials hint.
    #: ``None`` -> shown in development only; ``False`` -> never; ``True`` ->
    #: shown wherever it is safe (never in production, whatever this says).
    expose_demo_credentials: bool | None = None

    # --- AI ---
    ai_provider: AIProviderName = "mock"
    ai_api_key: str = ""
    ai_model: str = ""
    ai_base_url: str = ""
    ai_timeout_seconds: int = 90
    ai_max_retries: int = 2
    ai_confidence_high: float = 0.85
    ai_confidence_medium: float = 0.60

    # --- Storage ---
    storage_provider: StorageProviderName = "local"
    storage_path: str = "./storage_data"
    s3_bucket: str = ""
    s3_region: str = ""
    s3_endpoint_url: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""

    # --- Uploads ---
    max_upload_mb: int = 40
    max_submission_pages: int = 80

    # --- Worker ---
    worker_enabled: bool = True
    worker_poll_interval_seconds: float = 2.0
    worker_max_attempts: int = 3

    # --- Seed ---
    seed_on_startup: bool = True
    seed_teacher_email: str = "teacher@checkr.edu"
    seed_teacher_password: str = "CheckR!2026"

    # ------------------------------------------------------------------ #
    # Derived helpers
    # ------------------------------------------------------------------ #
    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_testing(self) -> bool:
        return self.environment == "test"

    @property
    def show_demo_credentials(self) -> bool:
        """Whether the sign-in screen may display the seeded demo account.

        Demo credentials are a development affordance and are never surfaced in
        production, whatever the configuration says.
        """
        if self.is_production:
            return False
        if self.expose_demo_credentials is not None:
            return self.expose_demo_credentials
        return self.environment == "development"

    @property
    def demo_credentials(self) -> tuple[str, str] | None:
        """Seeded sign-in hint, present only when it is both safe and accurate."""
        if not (self.show_demo_credentials and self.seed_on_startup):
            return None
        return (self.seed_teacher_email, self.seed_teacher_password)

    @property
    def storage_root(self) -> Path:
        p = Path(self.storage_path)
        if not p.is_absolute():
            p = (BASE_DIR / p).resolve()
        return p

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @field_validator("ai_confidence_high", "ai_confidence_medium")
    @classmethod
    def _clamp_unit(cls, v: float) -> float:
        return max(0.0, min(1.0, v))

    def warnings(self) -> list[str]:
        """Configuration problems worth surfacing at startup."""
        out: list[str] = []
        secret = self.jwt_secret or ""
        if len(secret) < 32 or "change" in secret.lower() or "insecure" in secret.lower():
            out.append(
                "JWT_SECRET is weak or default. Set a long random value before production."
            )
        if self.is_production and self.ai_provider != "mock" and not self.ai_api_key:
            out.append(f"AI_PROVIDER={self.ai_provider} but AI_API_KEY is empty.")
        if self.is_production and self.storage_provider == "s3" and not self.s3_bucket:
            out.append("STORAGE_PROVIDER=s3 but S3_BUCKET is empty.")
        if self.is_production and self.expose_demo_credentials:
            out.append(
                "EXPOSE_DEMO_CREDENTIALS is set, but demo credentials are never "
                "exposed in production. The setting is ignored."
            )
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
