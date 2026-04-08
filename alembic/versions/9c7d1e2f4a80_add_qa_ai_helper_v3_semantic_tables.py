"""add_qa_ai_helper_v3_semantic_tables

Revision ID: 9c7d1e2f4a80
Revises: 8d3c1b4a6f20
Create Date: 2026-04-02 20:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "9c7d1e2f4a80"
down_revision: Union[str, Sequence[str], None] = "8d3c1b4a6f20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _qa_ai_helper_large_text() -> sa.Text:
    return sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def upgrade() -> None:
    with op.batch_alter_table("qa_ai_helper_sessions") as batch_op:
        batch_op.alter_column("target_test_case_set_id", existing_type=sa.Integer(), nullable=True)
        batch_op.add_column(sa.Column("current_screen", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("active_ticket_snapshot_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("active_requirement_plan_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("active_seed_set_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("active_testcase_draft_set_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("selected_target_test_case_set_id", sa.Integer(), nullable=True))

    op.create_index(
        "ix_qa_ai_helper_sessions_current_screen",
        "qa_ai_helper_sessions",
        ["current_screen"],
        unique=False,
    )

    op.create_table(
        "qa_ai_helper_ticket_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("raw_ticket_markdown", _qa_ai_helper_large_text(), nullable=False),
        sa.Column("structured_requirement_json", _qa_ai_helper_large_text(), nullable=False),
        sa.Column("validation_summary_json", _qa_ai_helper_large_text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["qa_ai_helper_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_qa_ai_helper_ticket_snapshots_session_status",
        "qa_ai_helper_ticket_snapshots",
        ["session_id", "status"],
        unique=False,
    )

    op.create_table(
        "qa_ai_helper_requirement_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("ticket_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("section_start_number", sa.String(length=3), nullable=False),
        sa.Column("criteria_reference_json", _qa_ai_helper_large_text(), nullable=False),
        sa.Column("technical_reference_json", _qa_ai_helper_large_text(), nullable=True),
        sa.Column("autosave_summary_json", _qa_ai_helper_large_text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("locked_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["locked_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["qa_ai_helper_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ticket_snapshot_id"], ["qa_ai_helper_ticket_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "revision_number", name="uq_qa_ai_helper_requirement_plan_revision"),
    )
    op.create_index(
        "ix_qa_ai_helper_requirement_plans_session_status",
        "qa_ai_helper_requirement_plans",
        ["session_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_qa_ai_helper_requirement_plans_ticket_snapshot",
        "qa_ai_helper_requirement_plans",
        ["ticket_snapshot_id"],
        unique=False,
    )

    op.create_table(
        "qa_ai_helper_plan_sections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("requirement_plan_id", sa.Integer(), nullable=False),
        sa.Column("section_key", sa.String(length=128), nullable=False),
        sa.Column("section_id", sa.String(length=64), nullable=False),
        sa.Column("section_title", sa.Text(), nullable=False),
        sa.Column("given_json", _qa_ai_helper_large_text(), nullable=False),
        sa.Column("when_json", _qa_ai_helper_large_text(), nullable=False),
        sa.Column("then_json", _qa_ai_helper_large_text(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["requirement_plan_id"], ["qa_ai_helper_requirement_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("requirement_plan_id", "section_id", name="uq_qa_ai_helper_plan_section_id"),
        sa.UniqueConstraint("requirement_plan_id", "section_key", name="uq_qa_ai_helper_plan_section_key"),
    )
    op.create_index(
        "ix_qa_ai_helper_plan_sections_plan_order",
        "qa_ai_helper_plan_sections",
        ["requirement_plan_id", "display_order"],
        unique=False,
    )

    op.create_table(
        "qa_ai_helper_verification_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_section_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("detail_json", _qa_ai_helper_large_text(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["plan_section_id"], ["qa_ai_helper_plan_sections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_qa_ai_helper_verification_items_section_order",
        "qa_ai_helper_verification_items",
        ["plan_section_id", "display_order"],
        unique=False,
    )

    op.create_table(
        "qa_ai_helper_check_conditions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("verification_item_id", sa.Integer(), nullable=False),
        sa.Column("condition_text", sa.Text(), nullable=False),
        sa.Column("coverage_tag", sa.String(length=32), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["verification_item_id"], ["qa_ai_helper_verification_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_qa_ai_helper_check_conditions_item_order",
        "qa_ai_helper_check_conditions",
        ["verification_item_id", "display_order"],
        unique=False,
    )

    op.create_table(
        "qa_ai_helper_seed_sets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("requirement_plan_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("generation_round", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("generated_seed_count", sa.Integer(), nullable=False),
        sa.Column("included_seed_count", sa.Integer(), nullable=False),
        sa.Column("adoption_rate", sa.Float(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["requirement_plan_id"], ["qa_ai_helper_requirement_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["qa_ai_helper_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_qa_ai_helper_seed_sets_session_status",
        "qa_ai_helper_seed_sets",
        ["session_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_qa_ai_helper_seed_sets_requirement_status",
        "qa_ai_helper_seed_sets",
        ["requirement_plan_id", "status"],
        unique=False,
    )

    op.create_table(
        "qa_ai_helper_seed_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("seed_set_id", sa.Integer(), nullable=False),
        sa.Column("plan_section_id", sa.Integer(), nullable=True),
        sa.Column("verification_item_id", sa.Integer(), nullable=True),
        sa.Column("check_condition_refs_json", _qa_ai_helper_large_text(), nullable=True),
        sa.Column("coverage_tags_json", _qa_ai_helper_large_text(), nullable=False),
        sa.Column("seed_reference_key", sa.String(length=128), nullable=False),
        sa.Column("seed_summary", sa.Text(), nullable=False),
        sa.Column("seed_body_json", _qa_ai_helper_large_text(), nullable=False),
        sa.Column("comment_text", sa.Text(), nullable=True),
        sa.Column("is_ai_generated", sa.Boolean(), nullable=False),
        sa.Column("user_edited", sa.Boolean(), nullable=False),
        sa.Column("included_for_testcase_generation", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["plan_section_id"], ["qa_ai_helper_plan_sections.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["seed_set_id"], ["qa_ai_helper_seed_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["verification_item_id"], ["qa_ai_helper_verification_items.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seed_set_id", "seed_reference_key", name="uq_qa_ai_helper_seed_item_ref"),
    )
    op.create_index(
        "ix_qa_ai_helper_seed_items_included",
        "qa_ai_helper_seed_items",
        ["seed_set_id", "included_for_testcase_generation"],
        unique=False,
    )
    op.create_index(
        "ix_qa_ai_helper_seed_items_verification_item",
        "qa_ai_helper_seed_items",
        ["verification_item_id"],
        unique=False,
    )

    op.create_table(
        "qa_ai_helper_testcase_draft_sets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("seed_set_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("generated_testcase_count", sa.Integer(), nullable=False),
        sa.Column("selected_for_commit_count", sa.Integer(), nullable=False),
        sa.Column("adoption_rate", sa.Float(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("committed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["seed_set_id"], ["qa_ai_helper_seed_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["qa_ai_helper_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_qa_ai_helper_testcase_draft_sets_session_status",
        "qa_ai_helper_testcase_draft_sets",
        ["session_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_qa_ai_helper_testcase_draft_sets_seed_status",
        "qa_ai_helper_testcase_draft_sets",
        ["seed_set_id", "status"],
        unique=False,
    )

    op.create_table(
        "qa_ai_helper_testcase_drafts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("testcase_draft_set_id", sa.Integer(), nullable=False),
        sa.Column("seed_item_id", sa.Integer(), nullable=False),
        sa.Column("seed_reference_key", sa.String(length=128), nullable=False),
        sa.Column("assigned_testcase_id", sa.String(length=64), nullable=True),
        sa.Column("body_json", _qa_ai_helper_large_text(), nullable=False),
        sa.Column("is_ai_generated", sa.Boolean(), nullable=False),
        sa.Column("user_edited", sa.Boolean(), nullable=False),
        sa.Column("selected_for_commit", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["seed_item_id"], ["qa_ai_helper_seed_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["testcase_draft_set_id"], ["qa_ai_helper_testcase_draft_sets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "testcase_draft_set_id",
            "seed_reference_key",
            name="uq_qa_ai_helper_testcase_draft_ref",
        ),
    )
    op.create_index(
        "ix_qa_ai_helper_testcase_drafts_selected",
        "qa_ai_helper_testcase_drafts",
        ["testcase_draft_set_id", "selected_for_commit"],
        unique=False,
    )
    op.create_index(
        "ix_qa_ai_helper_testcase_drafts_seed_item",
        "qa_ai_helper_testcase_drafts",
        ["seed_item_id"],
        unique=False,
    )

    op.create_table(
        "qa_ai_helper_commit_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("testcase_draft_set_id", sa.Integer(), nullable=False),
        sa.Column("testcase_draft_id", sa.Integer(), nullable=False),
        sa.Column("seed_item_id", sa.Integer(), nullable=False),
        sa.Column("test_case_id", sa.Integer(), nullable=False),
        sa.Column("test_case_set_id", sa.Integer(), nullable=False),
        sa.Column("is_ai_generated", sa.Boolean(), nullable=False),
        sa.Column("selected_for_commit", sa.Boolean(), nullable=False),
        sa.Column("committed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["seed_item_id"], ["qa_ai_helper_seed_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["qa_ai_helper_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["test_case_id"], ["test_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["test_case_set_id"], ["test_case_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["testcase_draft_id"], ["qa_ai_helper_testcase_drafts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["testcase_draft_set_id"], ["qa_ai_helper_testcase_draft_sets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_qa_ai_helper_commit_links_session_committed",
        "qa_ai_helper_commit_links",
        ["session_id", "committed_at"],
        unique=False,
    )
    op.create_index(
        "ix_qa_ai_helper_commit_links_test_case",
        "qa_ai_helper_commit_links",
        ["test_case_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_qa_ai_helper_commit_links_test_case", table_name="qa_ai_helper_commit_links")
    op.drop_index("ix_qa_ai_helper_commit_links_session_committed", table_name="qa_ai_helper_commit_links")
    op.drop_table("qa_ai_helper_commit_links")

    op.drop_index("ix_qa_ai_helper_testcase_drafts_seed_item", table_name="qa_ai_helper_testcase_drafts")
    op.drop_index("ix_qa_ai_helper_testcase_drafts_selected", table_name="qa_ai_helper_testcase_drafts")
    op.drop_table("qa_ai_helper_testcase_drafts")

    op.drop_index("ix_qa_ai_helper_testcase_draft_sets_seed_status", table_name="qa_ai_helper_testcase_draft_sets")
    op.drop_index("ix_qa_ai_helper_testcase_draft_sets_session_status", table_name="qa_ai_helper_testcase_draft_sets")
    op.drop_table("qa_ai_helper_testcase_draft_sets")

    op.drop_index("ix_qa_ai_helper_seed_items_verification_item", table_name="qa_ai_helper_seed_items")
    op.drop_index("ix_qa_ai_helper_seed_items_included", table_name="qa_ai_helper_seed_items")
    op.drop_table("qa_ai_helper_seed_items")

    op.drop_index("ix_qa_ai_helper_seed_sets_requirement_status", table_name="qa_ai_helper_seed_sets")
    op.drop_index("ix_qa_ai_helper_seed_sets_session_status", table_name="qa_ai_helper_seed_sets")
    op.drop_table("qa_ai_helper_seed_sets")

    op.drop_index("ix_qa_ai_helper_check_conditions_item_order", table_name="qa_ai_helper_check_conditions")
    op.drop_table("qa_ai_helper_check_conditions")

    op.drop_index("ix_qa_ai_helper_verification_items_section_order", table_name="qa_ai_helper_verification_items")
    op.drop_table("qa_ai_helper_verification_items")

    op.drop_index("ix_qa_ai_helper_plan_sections_plan_order", table_name="qa_ai_helper_plan_sections")
    op.drop_table("qa_ai_helper_plan_sections")

    op.drop_index("ix_qa_ai_helper_requirement_plans_ticket_snapshot", table_name="qa_ai_helper_requirement_plans")
    op.drop_index("ix_qa_ai_helper_requirement_plans_session_status", table_name="qa_ai_helper_requirement_plans")
    op.drop_table("qa_ai_helper_requirement_plans")

    op.drop_index("ix_qa_ai_helper_ticket_snapshots_session_status", table_name="qa_ai_helper_ticket_snapshots")
    op.drop_table("qa_ai_helper_ticket_snapshots")

    op.drop_index("ix_qa_ai_helper_sessions_current_screen", table_name="qa_ai_helper_sessions")
    with op.batch_alter_table("qa_ai_helper_sessions") as batch_op:
        batch_op.drop_column("selected_target_test_case_set_id")
        batch_op.drop_column("active_testcase_draft_set_id")
        batch_op.drop_column("active_seed_set_id")
        batch_op.drop_column("active_requirement_plan_id")
        batch_op.drop_column("active_ticket_snapshot_id")
        batch_op.drop_column("current_screen")
        batch_op.alter_column("target_test_case_set_id", existing_type=sa.Integer(), nullable=False)
