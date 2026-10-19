"""Background worker.

Runs as its own process (``python -m app.workers.worker``). It claims jobs from
PostgreSQL and dispatches them to the pipeline handlers, one at a time per
worker. Run several workers for throughput.

An optional Redis subscription shortens the poll interval to near-zero when a
new job is enqueued, so the UI feels responsive without hammering the database.
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import dispose_engine, get_sessionmaker
from app.services import job_service, processing_service
from app.services.job_service import WAKEUP_CHANNEL

logger = get_logger("checkr.worker")


class Worker:
    def __init__(self, worker_id: str | None = None, poll_interval: float | None = None) -> None:
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self.poll_interval = poll_interval or settings.worker_poll_interval_seconds
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()

    # ------------------------------------------------------------------ #
    def request_stop(self) -> None:
        logger.info("Shutdown requested; finishing current job.")
        self._stop.set()

    async def _watch_redis(self) -> None:
        """Best-effort wake-up signal. Never fatal if Redis is unavailable."""
        try:
            import redis.asyncio as aioredis
        except ImportError:
            return
        while not self._stop.is_set():
            try:
                client = aioredis.from_url(
                    settings.redis_url, socket_connect_timeout=2, socket_timeout=None
                )
                pubsub = client.pubsub()
                await pubsub.subscribe(WAKEUP_CHANNEL)
                logger.info("Listening for job notifications on Redis.")
                async for message in pubsub.listen():
                    if self._stop.is_set():
                        break
                    if message.get("type") == "message":
                        self._wake.set()
                await pubsub.aclose()
                await client.aclose()
            except Exception as exc:
                logger.debug("Redis wake-up channel unavailable (%s); polling instead.", exc)
            if not self._stop.is_set():
                await asyncio.sleep(5)

    async def _handle(self, job) -> None:
        handler = processing_service.HANDLERS.get(job.job_type)
        if handler is None:
            await job_service.mark_failed(
                job.id, f"No handler registered for job type {job.job_type}.", retry=False
            )
            return

        logger.info("Running job %s (%s)", job.id, job.job_type.value)
        maker = get_sessionmaker()
        async with maker() as db:
            try:
                await handler(db, job)
                await db.commit()
            except Exception as exc:
                await db.rollback()
                logger.exception("Job %s failed", job.id)
                await job_service.mark_failed(job.id, str(exc), retry=True)
                return
        await job_service.mark_succeeded(job.id)

    async def run(self) -> None:
        logger.info(
            "CheckR worker %s started (poll=%ss, provider=%s)",
            self.worker_id,
            self.poll_interval,
            settings.ai_provider,
        )
        requeued = await job_service.requeue_stale_running_jobs()
        if requeued:
            logger.warning("Requeued %s stale running job(s).", requeued)

        redis_task = asyncio.create_task(self._watch_redis())

        try:
            while not self._stop.is_set():
                try:
                    job = await job_service.claim_next(self.worker_id)
                except Exception:
                    logger.exception("Failed to claim a job; backing off.")
                    job = None

                if job is None:
                    self._wake.clear()
                    try:
                        await asyncio.wait_for(self._wake.wait(), timeout=self.poll_interval)
                    except TimeoutError:
                        pass
                    continue

                await self._handle(job)
        finally:
            redis_task.cancel()
            try:
                await redis_task
            except (asyncio.CancelledError, Exception):
                pass
            await dispose_engine()
            logger.info("Worker %s stopped.", self.worker_id)


async def main() -> None:
    worker = Worker()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.request_stop)
        except NotImplementedError:  # pragma: no cover - Windows
            pass
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
