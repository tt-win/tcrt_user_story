"""add_qa_ai_helper_telemetry_tables

Revision ID: 31b9a7c4d2ef
Revises: 2c4b7f3d5e61
Create Date: 2026-03-30 20:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "31b9a7c4d2ef"
down_revision: Union[str, Sequence[str], None] = "2c4b7f3d5e61"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _qa_ai_helper_large_text() -> sa.Text:
    return sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def upgrade() -> None:
    op.create_table(
        "qa_ai_helper_telemetry_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("planned_revision_id", sa.Integer(), nullable=True),
        sa.Column("draft_set_id", sa.Integer(), nullable=True),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("event_name", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("payload_json", _qa_ai_helper_large_text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["draft_set_id"], ["qa_ai_helper_draft_sets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["planned_revision_id"], ["qa_ai_helper_planned_revisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["qa_ai_helper_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_qa_ai_helper_telemetry_events_team_stage_time",
        "qa_ai_helper_telemetry_events",
        ["team_id", "stage", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_qa_ai_helper_telemetry_events_session_time",
        "qa_ai_helper_telemetry_events",
        ["session_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_qa_ai_helper_telemetry_events_session_time", table_name="qa_ai_helper_telemetry_events")
    op.drop_index("ix_qa_ai_helper_telemetry_events_team_stage_time", table_name="qa_ai_helper_telemetry_events")
    op.drop_table("qa_ai_helper_telemetry_events")
