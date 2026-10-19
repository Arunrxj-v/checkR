"""Append-only audit logging.

Every consequential action (evaluation created, mark overridden, submission
finalized, exam changed) is recorded with who/what/when/old/new/reason. Rows are
immutable: this service only ever inserts.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.user import User


async def record(
    db: AsyncSession,
    *,
    action: str,
    entity_type: str,
    actor: User | None = None,
    entity_id: uuid.UUID | None = None,
    description: str | None = None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    reason: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_id=actor.id if actor else None,
        actor_email=actor.email if actor else None,
        actor_role=str(actor.role.value if actor and hasattr(actor.role, "value") else actor.role) if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        description=description,
        old_value=old_value,
        new_value=new_value,
        reason=reason,
    )
    db.add(entry)
    await db.flush()
    return entry
