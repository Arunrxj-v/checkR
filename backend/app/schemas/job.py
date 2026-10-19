"""Background-job schemas (for diagnostics and the processing screen)."""

from __future__ import annotations

import datetime as dt
import uuid

from app.db.enums import JobStatus, JobType
from app.schemas.common import ORMModel


class JobOut(ORMModel):
    id: uuid.UUID
    job_type: JobType
    status: JobStatus
    submission_id: uuid.UUID | None = None
    answer_id: uuid.UUID | None = None
    page_id: uuid.UUID | None = None
    attempts: int = 0
    max_attempts: int = 3
    error_message: str | None = None
    created_at: dt.datetime
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
