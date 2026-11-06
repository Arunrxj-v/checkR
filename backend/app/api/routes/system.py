"""System routes: health, capability discovery, audit trail.

The AI status reported here is always the result of an actual check against
the configured runtime (``GET /api/tags``, ``GET /api/ps`` and — via
``POST /system/ai/probe`` — a real inference request). Nothing in this module
reports success because a provider object exists.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app import __version__
from app.ai.base import AIProviderError
from app.ai.factory import get_provider
from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.logging import get_logger
from app.db.enums import QuestionType
from app.models.audit import AuditLog
from app.schemas.common import HealthResponse, Page
from app.storage import storage_health

logger = get_logger(__name__)

router = APIRouter(tags=["system"])

#: Statuses at which the runtime can actually accept work.
_REACHABLE = ("connected", "ready", "model_loading")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _capability_detail(kind: str, payload: dict) -> str:
    """Human explanation of why a capability is (un)available."""
    status = payload["status"]
    model = payload.get("model") or "the configured model"
    if kind == "ocr" and not payload["ocr_enabled"]:
        return "Handwriting recognition is disabled (OCR_ENABLED=false)."
    if kind == "evaluation" and not payload["evaluation_enabled"]:
        return "AI evaluation is disabled (EVALUATION_ENABLED=false)."
    if status == "unavailable":
        return "Ollama is not reachable."
    if status == "error":
        return "Ollama answered unexpectedly; see the availability message."
    if status == "model_not_installed":
        return f"{model} is not installed. Run: ollama pull {model}"
    if status == "inference_error":
        return "Inference is failing; see the availability message."
    if kind == "ocr":
        vision = payload.get("vision_capable")
        if vision is False:
            return f"{model} does not accept image input (no vision capability)."
        if vision is None:
            return "Vision support could not be confirmed from Ollama."
        return "Vision model available for handwriting recognition."
    return "Model available for answer evaluation."


def _apply_capabilities(payload: dict) -> dict:
    """Derive capability availability from real runtime state."""
    payload["ocr_enabled"] = settings.ocr_enabled if "ocr_enabled" not in payload else payload["ocr_enabled"]
    payload["evaluation_enabled"] = (
        settings.evaluation_enabled
        if "evaluation_enabled" not in payload
        else payload["evaluation_enabled"]
    )
    reachable = payload["status"] in _REACHABLE
    vision = payload.get("vision_capable")
    payload["ocr_available"] = bool(payload["ocr_enabled"] and reachable and vision)
    payload["evaluation_available"] = bool(
        payload["evaluation_enabled"] and reachable
    )
    payload["ocr_detail"] = _capability_detail("ocr", payload)
    payload["evaluation_detail"] = _capability_detail("evaluation", payload)
    return payload


def _failed_ai(detail: str, *, provider=None, status: str = "error") -> dict:
    """Status payload when the provider cannot even be resolved/queried.

    Used instead of raising so health/settings always answer — with a truthful
    failure, never with a fabricated success.
    """
    name = getattr(provider, "name", None) or settings.ai_provider
    model = getattr(provider, "model", None) or (
        settings.ollama_model if name == "ollama" else settings.ai_model
    )
    payload = {
        "provider": name,
        "model": model,
        "display_name": (f"{model} · Local" if model else name),
        "is_mock": False,
        "base_url": settings.ollama_base_url if name == "ollama" else "",
        "status": status,
        "ok": False,
        "connected": False,
        "available": False,
        "model_installed": None,
        "model_loaded": None,
        "vision_capable": None,
        "inference_ok": None,
        "inference_ms": None,
        "inference_checked_at": None,
        "checked_at": _now(),
        "detail": detail,
        "ocr_enabled": settings.ocr_enabled,
        "evaluation_enabled": settings.evaluation_enabled,
    }
    return _apply_capabilities(payload)


async def _ai_status() -> dict:
    """Resolve the configured provider's real status. Never raises."""
    try:
        provider = get_provider()
    except AIProviderError as exc:
        status = "unavailable" if exc.kind == "unavailable" else "error"
        return _failed_ai(str(exc), status=status)
    except Exception as exc:  # pragma: no cover - defensive
        return _failed_ai(f"{type(exc).__name__}: {exc}")

    try:
        raw = await provider.health()
    except AIProviderError as exc:
        status = "unavailable" if exc.kind == "unavailable" else "error"
        return _failed_ai(str(exc), provider=provider, status=status)
    except Exception as exc:  # a broken provider must not 500 the health page
        logger.warning("AI health check failed: %s", exc)
        return _failed_ai(f"{type(exc).__name__}: {exc}", provider=provider)
    return _ai_payload(provider, raw)


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
    payload.setdefault("base_url", "")
    if "status" not in payload:
        payload["status"] = "connected" if payload.get("ok") else "unavailable"
    payload.setdefault(
        "connected",
        payload["status"] in _REACHABLE or payload["status"] == "inference_error",
    )
    payload.setdefault("available", payload["connected"])
    payload.setdefault(
        "ok", payload["status"] in ("ready", "connected")
    )
    payload.setdefault("model_installed", None)
    payload.setdefault("model_loaded", None)
    payload.setdefault("vision_capable", None)
    # Tri-state: None until a real inference request has been made.
    payload.setdefault("inference_ok", None)
    payload.setdefault("inference_ms", None)
    payload.setdefault("inference_checked_at", None)
    payload.setdefault("checked_at", _now())
    payload.setdefault(
        "detail",
        "Local inference reachable."
        if payload["status"] == "connected"
        else "The configured AI provider reported a problem.",
    )
    return _apply_capabilities(payload)


@router.get("/health", response_model=HealthResponse)
async def health(db: DbSession) -> HealthResponse:
    """Liveness + dependency status. Safe to expose: contains no secrets."""
    db_status = "ok"
    try:
        await db.execute(select(1))
    except Exception as exc:  # pragma: no cover - depends on outage
        db_status = f"error: {type(exc).__name__}"

    ai = await _ai_status()
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
    """Runtime configuration surfaced to the Settings screen (no secrets).

    The ``ai`` block reflects the live health check (see :func:`_ai_status`),
    never the mere existence of a provider object.
    """
    ai = await _ai_status()
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
            "connected": ai["connected"],
            "model_installed": ai["model_installed"],
            "model_loaded": ai["model_loaded"],
            "vision_capable": ai["vision_capable"],
            "inference_ok": ai["inference_ok"],
            "inference_ms": ai["inference_ms"],
            "inference_checked_at": ai["inference_checked_at"],
            "checked_at": ai["checked_at"],
            "base_url": ai["base_url"],
            "ocr_enabled": ai["ocr_enabled"],
            "evaluation_enabled": ai["evaluation_enabled"],
            "ocr_available": ai["ocr_available"],
            "evaluation_available": ai["evaluation_available"],
            "ocr_detail": ai["ocr_detail"],
            "evaluation_detail": ai["evaluation_detail"],
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


@router.post("/system/ai/probe")
async def probe_ai(user: CurrentUser, force: bool = Query(default=False)) -> dict:
    """Run a real inference request against the configured model.

    This is the only endpoint that can move the status to ``ready``: it sends
    an actual ``POST /api/chat`` to Ollama. ``force=True`` bypasses the cached
    result. Used by the Settings screen's model check.
    """
    try:
        provider = get_provider()
    except AIProviderError as exc:
        status = "unavailable" if exc.kind == "unavailable" else "error"
        return {"ai": _failed_ai(str(exc), status=status)}

    probe = getattr(provider, "probe_inference", None)
    if not callable(probe):
        # Non-Ollama providers (test suite) have no chat endpoint to probe;
        # report their health truthfully instead of claiming success.
        return {"ai": await _ai_status()}

    try:
        await probe(force=force)
    except Exception as exc:  # probe must not 500 the Settings page
        logger.warning("AI inference probe failed: %s", exc)
    return {"ai": await _ai_status()}


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
