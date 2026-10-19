"""Durable job queue.

PostgreSQL is the source of truth. Workers claim the oldest due job with
``FOR UPDATE SKIP LOCKED``, so several workers can run concurrently without
double-processing. Redis, when reachable, is only used to wake idle workers
so latency stays low; correctness never depends on it.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.enums import JobStatus, JobType
from app.db.session import get_sessionmaker
from app.models.job import ProcessingJob

logger = get_logger(__name__)

WAKEUP_CHANNEL = "checkr:jobs"


async def enqueue(
    db: AsyncSession,
    *,
    job_type: JobType,
    submission_id: uuid.UUID | None = None,
    answer_id: uuid.UUID | None = None,
    page_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
    delay_seconds: float = 0.0,
    max_attempts: int | None = None,
) -> ProcessingJob:
    now = dt.datetime.now(dt.UTC)
    job = ProcessingJob(
        job_type=job_type,
        status=JobStatus.PENDING,
        submission_id=submission_id,
        answer_id=answer_id,
        page_id=page_id,
        payload=payload or {},
        max_attempts=max_attempts or settings.worker_max_attempts,
        available_at=now + dt.timedelta(seconds=max(0.0, delay_seconds)),
    )
    db.add(job)
    await db.flush()
    return job


async def _wake_workers() -> None:
    """Best-effort nudge so an idle worker picks a new job up immediately."""
    try:
        import redis.asyncio as aioredis
    except ImportError:  # pragma: no cover
        return
    try:
        client = aioredis.from_url(settings.redis_url, socket_connect_timeout=1)
        await client.publish(WAKEUP_CHANNEL, "1")
        await client.aclose()
    except Exception:  # pragma: no cover - Redis is optional
        return


async def enqueue_and_notify(db: AsyncSession, **kwargs) -> ProcessingJob:
    job = await enqueue(db, **kwargs)
    await db.flush()
    return job


async def notify_pending() -> None:
    await _wake_workers()


async def claim_next(worker_id: str) -> ProcessingJob | None:
    """Atomically claim the next due job, or return ``None`` if the queue is idle."""
    now = dt.datetime.now(dt.UTC)
    maker = get_sessionmaker()
    async with maker() as db:
        stmt = (
            select(ProcessingJob)
            .where(
                ProcessingJob.status == JobStatus.PENDING,
                ProcessingJob.available_at <= now,
            )
            .order_by(ProcessingJob.created_at.asc())
            .limit(1)
        )
        # SQLite (used in tests) does not support row locking; PostgreSQL does.
        if db.bind.dialect.name != "sqlite":
            stmt = stmt.with_for_update(skip_locked=True)
        job = (await db.execute(stmt)).scalar_one_or_none()
        if job is None:
            return None
        job.status = JobStatus.RUNNING
        job.attempts += 1
        job.started_at = now
        job.claimed_by = worker_id
        await db.commit()
        await db.refresh(job)
        return job


async def mark_succeeded(job_id: uuid.UUID) -> None:
    async with get_sessionmaker()() as db:
        await db.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job_id)
            .values(status=JobStatus.SUCCEEDED, finished_at=dt.datetime.now(dt.UTC))
        )
        await db.commit()


async def mark_failed(job_id: uuid.UUID, error: str, *, retry: bool) -> ProcessingJob | None:
    """Fail a job, or reschedule it if attempts remain."""
    async with get_sessionmaker()() as db:
        job = (
            await db.execute(select(ProcessingJob).where(ProcessingJob.id == job_id))
        ).scalar_one_or_none()
        if job is None:
            return None
        job.error_message = error[:2000]
        if retry and job.attempts < job.max_attempts:
            job.status = JobStatus.PENDING
            backoff = min(60.0, 2.0**job.attempts)
            job.available_at = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=backoff)
            job.claimed_by = None
            await db.commit()
            await db.refresh(job)
            logger.warning(
                "Job %s failed (attempt %s/%s); retrying in %.0fs: %s",
                job_id, job.attempts, job.max_attempts, backoff, error[:200],
            )
            return job
        job.status = JobStatus.FAILED
        job.finished_at = dt.datetime.now(dt.UTC)
        await db.commit()
        await db.refresh(job)
        logger.error("Job %s permanently failed: %s", job_id, error[:300])
        return job


async def requeue_stale_running_jobs(older_than_seconds: int = 900) -> int:
    """Recover jobs left ``running`` by a crashed worker."""
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=older_than_seconds)
    async with get_sessionmaker()() as db:
        result = await db.execute(
            update(ProcessingJob)
            .where(
                ProcessingJob.status == JobStatus.RUNNING,
                ProcessingJob.started_at < cutoff,
            )
            .values(
                status=JobStatus.PENDING,
                claimed_by=None,
                available_at=dt.datetime.now(dt.UTC),
                error_message="Requeued after a worker appeared to crash.",
            )
        )
        await db.commit()
        return result.rowcount or 0


async def pending_count(db: AsyncSession) -> int:
    from sqlalchemy import func

    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(ProcessingJob)
                .where(ProcessingJob.status == JobStatus.PENDING)
            )
        ).scalar_one()
    )
