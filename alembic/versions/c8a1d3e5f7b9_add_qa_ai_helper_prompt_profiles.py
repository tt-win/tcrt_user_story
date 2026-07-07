"""add_qa_ai_helper_prompt_profiles

Revision ID: c8a1d3e5f7b9
Revises: b3f1c8e0a927
Create Date: 2026-07-06 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db_types import MediumText


# revision identifiers, used by Alembic.
revision: str = "c8a1d3e5f7b9"
down_revision: Union[str, Sequence[str], None] = "b3f1c8e0a927"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if "qa_ai_helper_prompt_profiles" not in existing_tables:
        op.create_table(
            "qa_ai_helper_prompt_profiles",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("team_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("testcase_instructions", MediumText(), nullable=True),
            sa.Column("is_default", sa.Boolean(), nullable=False),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("team_id", "name", name="uq_qa_ai_helper_prompt_profile_team_name"),
        )
        op.create_index(
            "ix_qa_ai_helper_prompt_profiles_team_id",
            "qa_ai_helper_prompt_profiles",
            ["team_id"],
            unique=False,
        )
        op.create_index(
            "ix_qa_ai_helper_prompt_profiles_team_default",
            "qa_ai_helper_prompt_profiles",
            ["team_id", "is_default"],
            unique=False,
        )

    session_columns = [col["name"] for col in inspector.get_columns("qa_ai_helper_sessions")]
    if "prompt_profile_id" not in session_columns:
        with op.batch_alter_table("qa_ai_helper_sessions") as batch_op:
            batch_op.add_column(sa.Column("prompt_profile_id", sa.Integer(), nullable=True))
        op.create_index(
            "ix_qa_ai_helper_sessions_prompt_profile_id",
            "qa_ai_helper_sessions",
            ["prompt_profile_id"],
            unique=False,
        )

    draft_set_columns = [col["name"] for col in inspector.get_columns("qa_ai_helper_testcase_draft_sets")]
    with op.batch_alter_table("qa_ai_helper_testcase_draft_sets") as batch_op:
        if "prompt_profile_id" not in draft_set_columns:
            batch_op.add_column(sa.Column("prompt_profile_id", sa.Integer(), nullable=True))
        if "custom_instructions_snapshot" not in draft_set_columns:
            batch_op.add_column(sa.Column("custom_instructions_snapshot", MediumText(), nullable=True))
    if "prompt_profile_id" not in draft_set_columns:
        op.create_index(
            "ix_qa_ai_helper_testcase_draft_sets_prompt_profile_id",
            "qa_ai_helper_testcase_draft_sets",
            ["prompt_profile_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    draft_set_columns = [col["name"] for col in inspector.get_columns("qa_ai_helper_testcase_draft_sets")]
    draft_set_indexes = [idx["name"] for idx in inspector.get_indexes("qa_ai_helper_testcase_draft_sets")]
    with op.batch_alter_table("qa_ai_helper_testcase_draft_sets") as batch_op:
        if "ix_qa_ai_helper_testcase_draft_sets_prompt_profile_id" in draft_set_indexes:
            batch_op.drop_index("ix_qa_ai_helper_testcase_draft_sets_prompt_profile_id")
        if "custom_instructions_snapshot" in draft_set_columns:
            batch_op.drop_column("custom_instructions_snapshot")
        if "prompt_profile_id" in draft_set_columns:
            batch_op.drop_column("prompt_profile_id")

    session_columns = [col["name"] for col in inspector.get_columns("qa_ai_helper_sessions")]
    session_indexes = [idx["name"] for idx in inspector.get_indexes("qa_ai_helper_sessions")]
    if "prompt_profile_id" in session_columns:
        with op.batch_alter_table("qa_ai_helper_sessions") as batch_op:
            if "ix_qa_ai_helper_sessions_prompt_profile_id" in session_indexes:
                batch_op.drop_index("ix_qa_ai_helper_sessions_prompt_profile_id")
            batch_op.drop_column("prompt_profile_id")

    if "qa_ai_helper_prompt_profiles" in inspector.get_table_names():
        op.drop_table("qa_ai_helper_prompt_profiles")
