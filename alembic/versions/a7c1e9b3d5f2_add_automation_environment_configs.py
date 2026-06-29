"""add_automation_environment_configs

Adds TCRT-managed automation environment config:

- automation_environments: per-team, user-defined environment catalog (dev/sit/prod).
- automation_environment_params: per-environment shared parameter values.
- automation_script_env_vars: per-script override values (env x key).
- automation_scripts.declared_vars_json: per-script declared variables discovered
  from source TCRT_VARS by smart-scan (names only, no values).
- automation_runs.environment: environment name used by the run (name only).
- test_run_sets.default_automation_environment: per-set default environment name.

Config values (incl. secrets) live in TCRT (not the repo); secrets are
AES-256-GCM encrypted in *_encrypted columns. Non-destructive; downgrade drops
the new columns and tables.

Revision ID: a7c1e9b3d5f2
Revises: d7f2a9c4e1b8
Create Date: 2026-06-24 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7c1e9b3d5f2"
down_revision: Union[str, Sequence[str], None] = "d7f2a9c4e1b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_column(inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "automation_environments"):
        op.create_table(
            "automation_environments",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("team_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=60), nullable=False),
            sa.Column("label", sa.String(length=100), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_by", sa.String(length=64), nullable=True),
            sa.Column("updated_by", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("team_id", "name", name="uq_automation_environment_name"),
        )
        op.create_index(
            "ix_automation_environments_team_id", "automation_environments", ["team_id"]
        )
        op.create_index(
            "ix_automation_environments_team_default",
            "automation_environments",
            ["team_id", "is_default"],
        )

    if not _has_table(inspector, "automation_environment_params"):
        op.create_table(
            "automation_environment_params",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("environment_id", sa.Integer(), nullable=False),
            sa.Column("key", sa.String(length=120), nullable=False),
            sa.Column("is_secret", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("value_plaintext", sa.Text(), nullable=True),
            sa.Column("value_encrypted", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(length=64), nullable=True),
            sa.Column("updated_by", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["environment_id"], ["automation_environments.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("environment_id", "key", name="uq_automation_environment_param_key"),
        )
        op.create_index(
            "ix_automation_environment_params_environment_id",
            "automation_environment_params",
            ["environment_id"],
        )

    if not _has_table(inspector, "automation_script_env_vars"):
        op.create_table(
            "automation_script_env_vars",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("team_id", sa.Integer(), nullable=False),
            sa.Column("automation_script_id", sa.Integer(), nullable=False),
            sa.Column("script_ref_path", sa.String(length=500), nullable=False),
            sa.Column("environment_id", sa.Integer(), nullable=False),
            sa.Column("key", sa.String(length=120), nullable=False),
            sa.Column("is_secret", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("value_plaintext", sa.Text(), nullable=True),
            sa.Column("value_encrypted", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(length=64), nullable=True),
            sa.Column("updated_by", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["automation_script_id"], ["automation_scripts.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["environment_id"], ["automation_environments.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "automation_script_id", "environment_id", "key",
                name="uq_automation_script_env_var",
            ),
        )
        op.create_index(
            "ix_automation_script_env_vars_team_id", "automation_script_env_vars", ["team_id"]
        )
        op.create_index(
            "ix_automation_script_env_vars_automation_script_id",
            "automation_script_env_vars",
            ["automation_script_id"],
        )
        op.create_index(
            "ix_automation_script_env_vars_environment_id",
            "automation_script_env_vars",
            ["environment_id"],
        )
        op.create_index(
            "ix_automation_script_env_vars_team_path",
            "automation_script_env_vars",
            ["team_id", "script_ref_path"],
        )

    if not _has_column(inspector, "automation_scripts", "declared_vars_json"):
        with op.batch_alter_table("automation_scripts") as batch_op:
            batch_op.add_column(sa.Column("declared_vars_json", sa.Text(), nullable=True))

    if not _has_column(inspector, "automation_runs", "environment"):
        with op.batch_alter_table("automation_runs") as batch_op:
            batch_op.add_column(sa.Column("environment", sa.String(length=60), nullable=True))

    if not _has_column(inspector, "test_run_sets", "default_automation_environment"):
        with op.batch_alter_table("test_run_sets") as batch_op:
            batch_op.add_column(
                sa.Column("default_automation_environment", sa.String(length=60), nullable=True)
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_column(inspector, "test_run_sets", "default_automation_environment"):
        with op.batch_alter_table("test_run_sets") as batch_op:
            batch_op.drop_column("default_automation_environment")

    if _has_column(inspector, "automation_runs", "environment"):
        with op.batch_alter_table("automation_runs") as batch_op:
            batch_op.drop_column("environment")

    if _has_column(inspector, "automation_scripts", "declared_vars_json"):
        with op.batch_alter_table("automation_scripts") as batch_op:
            batch_op.drop_column("declared_vars_json")

    if _has_table(inspector, "automation_script_env_vars"):
        op.drop_table("automation_script_env_vars")
    if _has_table(inspector, "automation_environment_params"):
        op.drop_table("automation_environment_params")
    if _has_table(inspector, "automation_environments"):
        op.drop_table("automation_environments")
