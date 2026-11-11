"""Cross-process single-inference slot.

Only one inference job may run at a time on this deployment: on an 8 GB
machine two concurrent jobs would each try to load a model and the machine
would swap or OOM. Inside one process a plain ``asyncio.Lock`` (see
``OllamaProvider._infer_lock``) is enough, but the API and the worker run in
*different* processes, so the coordination lives in PostgreSQL:

* a **session-level advisory lock** (``pg_try_advisory_lock``) held on a
  dedicated connection for as long as the job runs — the lock disappears
  automatically if the process dies, so a crashed worker can never wedge the
  queue;
* SQLite (the test suite) has no advisory locks: the helpers are no-ops there,
  because tests never run two inference jobs concurrently.

Two entry points:

* :func:`inference_slot` — async context manager that *waits* for the slot
  (used by the worker before dispatching a job);
* :func:`try_inference_slot` — non-blocking check used by the Settings probe,
  which reports ``processing`` instead of piling a model load on top of a
  running job.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.logging import get_logger
from app.db.session import get_engine

logger = get_logger(__name__)

#: Arbitrary but fixed key for the "an inference job is running" lock.
INFERENCE_LOCK_KEY = 872441001

#: How often a worker re-tries acquiring the slot while another job holds it.
SLOT_POLL_SECONDS = 1.0


def _supports_advisory_locks(engine: AsyncEngine) -> bool:
    return engine.dialect.name not in ("sqlite", "mysql")


async def _try_lock(engine: AsyncEngine) -> AsyncConnection | None:
    """Acquire the slot on a fresh connection, or return ``None``."""
    if not _supports_advisory_locks(engine):
        return engine.connect()  # no-op stand-in; nothing is held
    conn = await engine.connect()
    row = (
        await conn.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": INFERENCE_LOCK_KEY}
        )
    ).first()
    if row is not None and bool(row[0]):
        return conn
    # Lock is held elsewhere: return the connection so it can be closed.
    await conn.close()
    return None


async def _unlock(conn: AsyncConnection, engine: AsyncEngine) -> None:
    try:
        if _supports_advisory_locks(engine):
            await conn.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": INFERENCE_LOCK_KEY}
            )
        await conn.close()
    except Exception as exc:  # noqa: BLE001 - releasing must never mask errors
        logger.warning("Could not release inference slot: %s", exc)


async def try_inference_slot() -> bool:
    """Non-blocking probe: is the single-inference slot free right now?

    Acquires the slot and immediately releases it — the answer is only valid
    at that instant, which is exactly what a status check needs.
    """
    engine = get_engine()
    conn = await _try_lock(engine)
    if conn is None:
        return False
    await _unlock(conn, engine)
    return True


@asynccontextmanager
async def inference_slot(*, poll_seconds: float = SLOT_POLL_SECONDS) -> AsyncIterator[None]:
    """Wait for, hold and release the single-inference slot.

    The worker wraps each job handler in this so two jobs — in two different
    worker processes, or a worker and the API — never run inference at the
    same time.
    """
    engine = get_engine()
    if not _supports_advisory_locks(engine):
        yield  # SQLite/test mode: nothing to coordinate
        return

    conn: AsyncConnection | None = None
    while conn is None:
        conn = await _try_lock(engine)
        if conn is None:
            logger.info("Inference slot busy; waiting to run job…")
            await asyncio.sleep(poll_seconds)
    try:
        yield
    finally:
        await _unlock(conn, engine)
