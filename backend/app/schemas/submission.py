"""Submission and page schemas."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import Field

from app.db.enums import PageStatus, SubmissionStatus
from app.schemas.common import ORMModel


class PageOut(ORMModel):
    id: uuid.UUID
    page_number: int
    width: int | None = None
    height: int | None = None
    status: PageStatus
    ocr_confidence: float | None = None
    rotation_degrees: int = 0
    deskew_angle: float | None = None
    error_message: str | None = None
    has_thumbnail: bool = False


class SubmissionCreate(ORMModel):
    exam_id: uuid.UUID
    student_name: str | None = Field(default=None, max_length=200)
    student_roll: str | None = Field(default=None, max_length=60)


class SubmissionUpdate(ORMModel):
    student_name: str | None = Field(default=None, max_length=200)
    student_roll: str | None = Field(default=None, max_length=60)


class SubmissionOut(ORMModel):
    id: uuid.UUID
    exam_id: uuid.UUID
    student_name: str | None = None
    student_roll: str | None = None
    status: SubmissionStatus
    page_count: int = 0
    processed_page_count: int = 0
    max_total_marks: float = 0
    ai_total_marks: float = 0
    final_total_marks: float = 0
    ai_confidence: float | None = None
    flagged_count: int = 0
    original_filename: str | None = None
    error_message: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime


class SubmissionDetail(SubmissionOut):
    pages: list[PageOut] = Field(default_factory=list)
    answer_count: int = 0
    evaluated_count: int = 0
    reviewed_count: int = 0


class SubmissionStatusOut(ORMModel):
    """Lightweight poll target for the processing screen."""

    id: uuid.UUID
    status: SubmissionStatus
    page_count: int = 0
    processed_page_count: int = 0
    answer_count: int = 0
    evaluated_count: int = 0
    flagged_count: int = 0
    error_message: str | None = None
    stage_message: str | None = None
