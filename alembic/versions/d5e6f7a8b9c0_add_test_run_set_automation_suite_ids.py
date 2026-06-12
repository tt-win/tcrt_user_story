"""add_test_run_set_automation_suite_ids

Adds `automation_suite_ids_json` TEXT column to `test_run_sets` so a Test
Run Set can declare which automation suites (script_group ids) it wants
to trigger via the Run-as-Automation entry point. Non-destructive:
existing rows get NULL.

Also adds `test_run_set_id` nullable FK to `automation_runs` so runs
triggered from a Test Run Set can be traced back to their source.

See openspec/changes/move-automation-execution-to-test-run-set/.

Revision ID: d5e6f7a8b9c0
Revises: c1d2e3f4a5b6
Create Date: 2026-06-04 10:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # test_run_sets.automation_suite_ids_json
    if "test_run_sets" in inspector.get_table_names():
        trs_columns = {c["name"] for c in inspector.get_columns("test_run_sets")}
        if "automation_suite_ids_json" not in trs_columns:
            with op.batch_alter_table("test_run_sets") as batch_op:
                batch_op.add_column(
                    sa.Column(
                        "automation_suite_ids_json",
                        sa.Text(),
                        nullable=True,
                        comment=(
                            "Automation Suites (automation_script_groups.id) "
                            "this Test Run Set can trigger via Run-as-Automation. "
                            "JSON array of int."
                        ),
                    )
                )

    # automation_runs.test_run_set_id
    if "automation_runs" in inspector.get_table_names():
        ar_columns = {c["name"] for c in inspector.get_columns("automation_runs")}
        if "test_run_set_id" not in ar_columns:
            with op.batch_alter_table("automation_runs") as batch_op:
                batch_op.add_column(
                    sa.Column(
                        "test_run_set_id",
                        sa.Integer(),
                        nullable=True,
                        comment=(
                            "Source Test Run Set that triggered this run. "
                            "NULL for legacy hub-triggered runs and webhook-triggered runs."
                        ),
                    )
                )
                batch_op.create_foreign_key(
                    "fk_automation_runs_test_run_set_id",
                    "test_run_sets",
                    ["test_run_set_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
                batch_op.create_index(
                    "ix_automation_runs_test_run_set_id",
                    ["test_run_set_id"],
                )
                # Composite index used by run history queries filtered by test_run_set_id
                # and sorted by started_at; mirrors the existing (script_group_id, started_at)
                # and (automation_script_id, started_at) composite indexes.
                batch_op.create_index(
                    "ix_automation_runs_test_run_set_started",
                    ["test_run_set_id", "started_at"],
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "automation_runs" in inspector.get_table_names():
        ar_columns = {c["name"] for c in inspector.get_columns("automation_runs")}
        if "test_run_set_id" in ar_columns:
            with op.batch_alter_table("automation_runs") as batch_op:
                batch_op.drop_index("ix_automation_runs_test_run_set_started")
                batch_op.drop_index("ix_automation_runs_test_run_set_id")
                batch_op.drop_constraint(
                    "fk_automation_runs_test_run_set_id", type_="foreignkey"
                )
                batch_op.drop_column("test_run_set_id")

    if "test_run_sets" in inspector.get_table_names():
        trs_columns = {c["name"] for c in inspector.get_columns("test_run_sets")}
        if "automation_suite_ids_json" in trs_columns:
            with op.batch_alter_table("test_run_sets") as batch_op:
                batch_op.drop_column("automation_suite_ids_json")
