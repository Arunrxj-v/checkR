"""dual-model AI provenance and criterion evidence

Adds provenance for the dual-model (OCR + evaluation) pipeline and the
per-criterion evidence the workspace shows:

* ``ocr_results.duration_ms``            — per-page OCR inference time
* ``evaluations.ocr_model``              — the OCR model whose text was graded
* ``evaluations.ocr_completed_at``       — when that OCR pass finished
* ``evaluations.processing_duration_ms``  — evaluation inference time
* ``evaluation_criteria.evidence``        — quotes justifying each award
* ``evaluation_criteria.missing_elements``— rubric elements not covered
* ``evaluation_criteria.needs_human_review``— model asks for a human check

Revision ID: c9f1d2a74b08
Revises: aa0ac4094fef
Create Date: 2026-11-09 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9f1d2a74b08"
down_revision: Union[str, None] = "aa0ac4094fef"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ocr_results", sa.Column("duration_ms", sa.Integer(), nullable=True))

    op.add_column(
        "evaluations", sa.Column("ocr_model", sa.String(length=120), nullable=True)
    )
    op.add_column(
        "evaluations",
        sa.Column("ocr_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "evaluations",
        sa.Column("processing_duration_ms", sa.Integer(), nullable=True),
    )

    op.add_column(
        "evaluation_criteria",
        sa.Column("evidence", sa.JSON(), server_default="[]", nullable=False),
    )
    op.add_column(
        "evaluation_criteria",
        sa.Column("missing_elements", sa.JSON(), server_default="[]", nullable=False),
    )
    op.add_column(
        "evaluation_criteria",
        sa.Column("needs_human_review", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("evaluation_criteria", "needs_human_review")
    op.drop_column("evaluation_criteria", "missing_elements")
    op.drop_column("evaluation_criteria", "evidence")

    op.drop_column("evaluations", "processing_duration_ms")
    op.drop_column("evaluations", "ocr_completed_at")
    op.drop_column("evaluations", "ocr_model")

    op.drop_column("ocr_results", "duration_ms")
