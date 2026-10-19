"""Structured, privacy-conscious logging.

Exam scripts and student data are sensitive. We never log raw OCR text, file
contents, tokens or secrets — only identifiers and lifecycle events.
"""

from __future__ import annotations

import logging
import sys

from app.core.config import settings

_CONFIGURED = False


class _RedactionFilter(logging.Filter):
    """Best-effort guard so secrets never reach the log stream."""

    _KEYS = ("authorization", "api_key", "apikey", "password", "token", "secret")

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            msg = record.getMessage().lower()
        except Exception:  # pragma: no cover - defensive
            return True
        if any(k in msg for k in self._KEYS):
            record.msg = "[redacted log line containing a sensitive keyword]"
            record.args = ()
        return True


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = logging.DEBUG if settings.debug else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    handler.addFilter(_RedactionFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Quiet down noisy third-party loggers.
    for noisy in ("uvicorn.access", "httpx", "httpcore", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING if not settings.debug else logging.INFO)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
