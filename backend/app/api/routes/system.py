"""System routes: health, capability discovery, audit trail."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app import __version__
from app.ai.factory import get_provider
from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.db.enums import QuestionType
from app.models.audit import AuditLog
from app.schemas.common import HealthResponse, Page
from app.storage import storage_health

router = APIRouter(tags=["system"])


def _ai_payload(provider, raw: dict) -> dict:
    """Normalise any provider's health() into the shape the UI consumes."""
    payload = dict(raw)
    payload.setdefault("provider", getattr(provider, "name", "unknown"))
    payload.setdefault("model", getattr(provider, "model", ""))
    payload.setdefault("is_mock", bool(getattr(provider, "is_mock", False)))
    payload.setdefault(
        "display_name",
        payload.get("display_name")
        or (f"{payload['model']} · Local" if payload["model"] else payload["provider"]),
    )
    if "status" not in payload:
        payload["status"] = "ok" if payload.get("ok") else "unavailable"
    payload.setdefault(
        "detail",
        "Local inference ready."
        if payload["status"] == "ok"
        else "The configured AI provider reported a problem.",
    )
    payload.setdefault("available", payload["status"] == "ok")
    payload.setdefault("model_installed", payload["status"] != "model_missing")
    payload.setdefault("ocr_enabled", settings.ocr_enabled)
    payload.setdefault("evaluation_enabled", settings.evaluation_enabled)
    return payload


@router.get("/health", response_model=HealthResponse)
async def health(db: DbSession) -> HealthResponse:
    """Liveness + dependency status. Safe to expose: contains no secrets."""
    db_status = "ok"
    try:
        await db.execute(select(1))
    except Exception as exc:  # pragma: no cover - depends on outage
        db_status = f"error: {type(exc).__name__}"

    provider = get_provider()
    ai = _ai_payload(provider, await provider.health())
    storage = await storage_health()

    return HealthResponse(
        status="ok" if db_status == "ok" else "degraded",
        app=settings.app_name,
        version=__version__,
        environment=settings.environment,
        database=db_status,
        storage=storage,
        ai=ai,
        warnings=settings.warnings() if not settings.is_production else [],
    )


@router.get("/settings")
async def get_settings(user: CurrentUser) -> dict:
    """Runtime configuration surfaced to the Settings screen (no secrets)."""
    provider = get_provider()
    ai = _ai_payload(provider, await provider.health())
    return {
        "app_name": settings.app_name,
        "environment": settings.environment,
        "version": __version__,
        "ai": {
            "provider": ai["provider"],
            "model": ai["model"],
            "display_name": ai["display_name"],
            "is_mock": ai["is_mock"],
            "status": ai["status"],
            "detail": ai["detail"],
            "available": ai["available"],
            "model_installed": ai["model_installed"],
            "ocr_enabled": ai["ocr_enabled"],
            "evaluation_enabled": ai["evaluation_enabled"],
            "confidence_high": settings.ai_confidence_high,
            "confidence_medium": settings.ai_confidence_medium,
        },
        "storage": {"provider": settings.storage_provider},
        "uploads": {
            "max_upload_mb": settings.max_upload_mb,
            "max_submission_pages": settings.max_submission_pages,
            "accepted_types": ["application/pdf", "image/jpeg", "image/png"],
        },
        "question_types": [t.value for t in QuestionType],
    }


@router.get("/audit-logs", response_model=Page[dict])
async def audit_logs(
    db: DbSession,
    user: CurrentUser,
    entity_type: str | None = Query(default=None, max_length=60),
    entity_id: uuid.UUID | None = Query(default=None),
    action: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[dict]:
    """Audit trail.

    Teachers see their own actions; only admins see every actor's entries.
    """
    conditions = []
    if user.role.value != "admin":
        conditions.append(AuditLog.actor_id == user.id)
    if entity_type:
        conditions.append(AuditLog.entity_type == entity_type)
    if entity_id:
        conditions.append(AuditLog.entity_id == entity_id)
    if action:
        conditions.append(AuditLog.action == action)

    base = select(AuditLog)
    if conditions:
        base = base.where(*conditions)
    total = int(
        (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    )
    rows = (
        await db.execute(
            base.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()

    items = [
        {
            "id": str(row.id),
            "action": row.action,
            "entity_type": row.entity_type,
            "entity_id": str(row.entity_id) if row.entity_id else None,
            "actor_email": row.actor_email,
            "actor_role": row.actor_role,
            "description": row.description,
            "old_value": row.old_value,
            "new_value": row.new_value,
            "reason": row.reason,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]
    return Page[dict](items=items, total=total, limit=limit, offset=offset)
