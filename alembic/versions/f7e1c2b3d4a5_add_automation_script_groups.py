"""add_automation_script_groups

Revision ID: f7e1c2b3d4a5
Revises: e1a2b3c4d5f6
Create Date: 2026-05-18 13:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db_types import MediumText


revision: str = "f7e1c2b3d4a5"
down_revision: Union[str, Sequence[str], None] = "e1a2b3c4d5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


script_group_job_type_enum = sa.Enum(
    "GITHUB_ACTIONS",
    "JENKINS",
    name="automation_script_group_job_type",
    native_enum=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "automation_script_groups" not in existing_tables:
        op.create_table(
            "automation_script_groups",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("team_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("description", MediumText(), nullable=True),
            sa.Column("script_paths_json", MediumText(), nullable=False),
            sa.Column("ci_job_name", sa.String(length=200), nullable=True),
            sa.Column("ci_job_type", script_group_job_type_enum, nullable=True),
            sa.Column("created_by", sa.String(length=64), nullable=True),
            sa.Column("updated_by", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("team_id", "name", name="uq_automation_script_group_name"),
        )
        op.create_index(
            "ix_automation_script_groups_team_id",
            "automation_script_groups",
            ["team_id"],
            unique=False,
        )

    runs_columns = {col["name"] for col in inspector.get_columns("automation_runs")}
    if "script_group_id" not in runs_columns:
        with op.batch_alter_table("automation_runs") as batch_op:
            batch_op.add_column(sa.Column("script_group_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                "fk_automation_runs_script_group_id",
                "automation_script_groups",
                ["script_group_id"],
                ["id"],
                ondelete="SET NULL",
            )

        op.create_index(
            "ix_automation_runs_script_group_id",
            "automation_runs",
            ["script_group_id"],
            unique=False,
        )
        op.create_index(
            "ix_automation_runs_group_started",
            "automation_runs",
            ["script_group_id", "started_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    runs_indexes = {ix["name"] for ix in inspector.get_indexes("automation_runs")}
    if "ix_automation_runs_group_started" in runs_indexes:
        op.drop_index("ix_automation_runs_group_started", table_name="automation_runs")
    if "ix_automation_runs_script_group_id" in runs_indexes:
        op.drop_index("ix_automation_runs_script_group_id", table_name="automation_runs")

    runs_columns = {col["name"] for col in inspector.get_columns("automation_runs")}
    if "script_group_id" in runs_columns:
        with op.batch_alter_table("automation_runs") as batch_op:
            batch_op.drop_constraint("fk_automation_runs_script_group_id", type_="foreignkey")
            batch_op.drop_column("script_group_id")

    existing_tables = set(inspector.get_table_names())
    if "automation_script_groups" in existing_tables:
        op.drop_index("ix_automation_script_groups_team_id", table_name="automation_script_groups")
        op.drop_table("automation_script_groups")
