"""add_qa_ai_helper_core_tables

Revision ID: 1f4c8d7a9b3e
Revises: 6d8f3a1b9c20
Create Date: 2026-03-30 19:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "1f4c8d7a9b3e"
down_revision: Union[str, Sequence[str], None] = "6d8f3a1b9c20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _qa_ai_helper_large_text() -> sa.Text:
    return sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def upgrade() -> None:
    op.create_table(
        "qa_ai_helper_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("target_test_case_set_id", sa.Integer(), nullable=False),
        sa.Column("ticket_key", sa.String(length=64), nullable=True),
        sa.Column("include_comments", sa.Boolean(), nullable=False),
        sa.Column("output_locale", sa.String(length=16), nullable=False),
        sa.Column("canonical_language", sa.String(length=16), nullable=True),
        sa.Column("source_payload_json", _qa_ai_helper_large_text(), nullable=True),
        sa.Column("current_phase", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("active_canonical_revision_id", sa.Integer(), nullable=True),
        sa.Column("active_planned_revision_id", sa.Integer(), nullable=True),
        sa.Column("active_draft_set_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_test_case_set_id"], ["test_case_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_qa_ai_helper_sessions_team_status", "qa_ai_helper_sessions", ["team_id", "status"], unique=False)
    op.create_index("ix_qa_ai_helper_sessions_team_updated", "qa_ai_helper_sessions", ["team_id", "updated_at"], unique=False)
    op.create_index("ix_qa_ai_helper_sessions_ticket_key", "qa_ai_helper_sessions", ["ticket_key"], unique=False)

    op.create_table(
        "qa_ai_helper_canonical_revisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("content_json", _qa_ai_helper_large_text(), nullable=False),
        sa.Column("canonical_language", sa.String(length=16), nullable=False),
        sa.Column("counter_settings_json", _qa_ai_helper_large_text(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["qa_ai_helper_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "revision_number", name="uq_qa_ai_helper_canonical_revision"),
    )
    op.create_index(
        "ix_qa_ai_helper_canonical_revisions_session_status",
        "qa_ai_helper_canonical_revisions",
        ["session_id", "status"],
        unique=False,
    )

    op.create_table(
        "qa_ai_helper_planned_revisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("canonical_revision_id", sa.Integer(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("matrix_json", _qa_ai_helper_large_text(), nullable=False),
        sa.Column("seed_map_json", _qa_ai_helper_large_text(), nullable=False),
        sa.Column("applicability_overrides_json", _qa_ai_helper_large_text(), nullable=False),
        sa.Column("selected_references_json", _qa_ai_helper_large_text(), nullable=False),
        sa.Column("counter_settings_json", _qa_ai_helper_large_text(), nullable=False),
        sa.Column("impact_summary_json", _qa_ai_helper_large_text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("locked_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["canonical_revision_id"], ["qa_ai_helper_canonical_revisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["locked_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["qa_ai_helper_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "revision_number", name="uq_qa_ai_helper_planned_revision"),
    )
    op.create_index(
        "ix_qa_ai_helper_planned_revisions_session_canonical",
        "qa_ai_helper_planned_revisions",
        ["session_id", "canonical_revision_id"],
        unique=False,
    )
    op.create_index(
        "ix_qa_ai_helper_planned_revisions_session_status",
        "qa_ai_helper_planned_revisions",
        ["session_id", "status"],
        unique=False,
    )

    op.create_table(
        "qa_ai_helper_requirement_deltas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("source_canonical_revision_id", sa.Integer(), nullable=True),
        sa.Column("source_planned_revision_id", sa.Integer(), nullable=True),
        sa.Column("delta_type", sa.String(length=16), nullable=False),
        sa.Column("target_scope", sa.String(length=64), nullable=False),
        sa.Column("target_requirement_key", sa.String(length=128), nullable=True),
        sa.Column("target_scenario_key", sa.String(length=128), nullable=True),
        sa.Column("proposed_content_json", _qa_ai_helper_large_text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_from_phase", sa.String(length=32), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("applied_canonical_revision_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["applied_canonical_revision_id"], ["qa_ai_helper_canonical_revisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["qa_ai_helper_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_canonical_revision_id"], ["qa_ai_helper_canonical_revisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_planned_revision_id"], ["qa_ai_helper_planned_revisions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_qa_ai_helper_requirement_deltas_session_created",
        "qa_ai_helper_requirement_deltas",
        ["session_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_qa_ai_helper_requirement_deltas_source_plan",
        "qa_ai_helper_requirement_deltas",
        ["source_planned_revision_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_qa_ai_helper_requirement_deltas_source_plan", table_name="qa_ai_helper_requirement_deltas")
    op.drop_index("ix_qa_ai_helper_requirement_deltas_session_created", table_name="qa_ai_helper_requirement_deltas")
    op.drop_table("qa_ai_helper_requirement_deltas")
    op.drop_index("ix_qa_ai_helper_planned_revisions_session_status", table_name="qa_ai_helper_planned_revisions")
    op.drop_index("ix_qa_ai_helper_planned_revisions_session_canonical", table_name="qa_ai_helper_planned_revisions")
    op.drop_table("qa_ai_helper_planned_revisions")
    op.drop_index("ix_qa_ai_helper_canonical_revisions_session_status", table_name="qa_ai_helper_canonical_revisions")
    op.drop_table("qa_ai_helper_canonical_revisions")
    op.drop_index("ix_qa_ai_helper_sessions_ticket_key", table_name="qa_ai_helper_sessions")
    op.drop_index("ix_qa_ai_helper_sessions_team_updated", table_name="qa_ai_helper_sessions")
    op.drop_index("ix_qa_ai_helper_sessions_team_status", table_name="qa_ai_helper_sessions")
    op.drop_table("qa_ai_helper_sessions")
