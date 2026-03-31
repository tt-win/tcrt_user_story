"""widen_qa_ai_helper_json_columns

Revision ID: 4b5d8f2c1a9e
Revises: 31b9a7c4d2ef
Create Date: 2026-03-31 11:05:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "4b5d8f2c1a9e"
down_revision: Union[str, Sequence[str], None] = "31b9a7c4d2ef"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


QA_AI_HELPER_JSON_COLUMNS: tuple[tuple[str, str, bool], ...] = (
    ("qa_ai_helper_sessions", "source_payload_json", True),
    ("qa_ai_helper_canonical_revisions", "content_json", False),
    ("qa_ai_helper_canonical_revisions", "counter_settings_json", False),
    ("qa_ai_helper_planned_revisions", "matrix_json", False),
    ("qa_ai_helper_planned_revisions", "seed_map_json", False),
    ("qa_ai_helper_planned_revisions", "applicability_overrides_json", False),
    ("qa_ai_helper_planned_revisions", "selected_references_json", False),
    ("qa_ai_helper_planned_revisions", "counter_settings_json", False),
    ("qa_ai_helper_planned_revisions", "impact_summary_json", True),
    ("qa_ai_helper_requirement_deltas", "proposed_content_json", False),
    ("qa_ai_helper_draft_sets", "summary_json", True),
    ("qa_ai_helper_drafts", "body_json", False),
    ("qa_ai_helper_drafts", "trace_json", False),
    ("qa_ai_helper_validation_runs", "summary_json", True),
    ("qa_ai_helper_validation_runs", "errors_json", True),
    ("qa_ai_helper_telemetry_events", "payload_json", True),
)


def _alter_columns(target_type: sa.types.TypeEngine) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "mysql":
        return

    for table_name, column_name, nullable in QA_AI_HELPER_JSON_COLUMNS:
        op.alter_column(
            table_name,
            column_name,
            existing_type=sa.Text(),
            type_=target_type,
            existing_nullable=nullable,
        )


def upgrade() -> None:
    _alter_columns(mysql.MEDIUMTEXT())


def downgrade() -> None:
    _alter_columns(sa.Text())
