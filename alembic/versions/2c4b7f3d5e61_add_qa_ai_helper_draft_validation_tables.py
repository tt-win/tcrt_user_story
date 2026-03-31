"""add_qa_ai_helper_draft_validation_tables

Revision ID: 2c4b7f3d5e61
Revises: 1f4c8d7a9b3e
Create Date: 2026-03-30 19:45:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "2c4b7f3d5e61"
down_revision: Union[str, Sequence[str], None] = "1f4c8d7a9b3e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _qa_ai_helper_large_text() -> sa.Text:
    return sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def upgrade() -> None:
    op.create_table(
        "qa_ai_helper_draft_sets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("planned_revision_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("generation_mode", sa.String(length=32), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("summary_json", _qa_ai_helper_large_text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("committed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["planned_revision_id"], ["qa_ai_helper_planned_revisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["qa_ai_helper_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_qa_ai_helper_draft_sets_session_status", "qa_ai_helper_draft_sets", ["session_id", "status"], unique=False)
    op.create_index("ix_qa_ai_helper_draft_sets_plan_status", "qa_ai_helper_draft_sets", ["planned_revision_id", "status"], unique=False)

    op.create_table(
        "qa_ai_helper_drafts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("draft_set_id", sa.Integer(), nullable=False),
        sa.Column("item_key", sa.String(length=128), nullable=False),
        sa.Column("seed_id", sa.String(length=128), nullable=True),
        sa.Column("testcase_id", sa.String(length=64), nullable=True),
        sa.Column("body_json", _qa_ai_helper_large_text(), nullable=False),
        sa.Column("trace_json", _qa_ai_helper_large_text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["draft_set_id"], ["qa_ai_helper_draft_sets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_set_id", "item_key", name="uq_qa_ai_helper_draft_set_item_key"),
    )
    op.create_index("ix_qa_ai_helper_drafts_seed_id", "qa_ai_helper_drafts", ["seed_id"], unique=False)
    op.create_index("ix_qa_ai_helper_drafts_testcase_id", "qa_ai_helper_drafts", ["testcase_id"], unique=False)

    op.create_table(
        "qa_ai_helper_validation_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("planned_revision_id", sa.Integer(), nullable=False),
        sa.Column("draft_set_id", sa.Integer(), nullable=True),
        sa.Column("run_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("summary_json", _qa_ai_helper_large_text(), nullable=True),
        sa.Column("errors_json", _qa_ai_helper_large_text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["draft_set_id"], ["qa_ai_helper_draft_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["planned_revision_id"], ["qa_ai_helper_planned_revisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["qa_ai_helper_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_qa_ai_helper_validation_runs_draft_created",
        "qa_ai_helper_validation_runs",
        ["draft_set_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_qa_ai_helper_validation_runs_draft_created", table_name="qa_ai_helper_validation_runs")
    op.drop_table("qa_ai_helper_validation_runs")
    op.drop_index("ix_qa_ai_helper_drafts_testcase_id", table_name="qa_ai_helper_drafts")
    op.drop_index("ix_qa_ai_helper_drafts_seed_id", table_name="qa_ai_helper_drafts")
    op.drop_table("qa_ai_helper_drafts")
    op.drop_index("ix_qa_ai_helper_draft_sets_plan_status", table_name="qa_ai_helper_draft_sets")
    op.drop_index("ix_qa_ai_helper_draft_sets_session_status", table_name="qa_ai_helper_draft_sets")
    op.drop_table("qa_ai_helper_draft_sets")
