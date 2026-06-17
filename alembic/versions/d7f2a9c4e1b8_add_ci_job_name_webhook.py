"""add_ci_job_name_webhook

Adds nullable ci_job_name_webhook to automation_script_groups so a suite's
webhook-triggered runs execute on a dedicated CI job (separate build history /
queue / Allure project from Test-Run-Set runs). The webhook job is created
lazily on the suite's first webhook trigger, so existing rows get NULL and no
backfill is needed. Non-destructive; downgrade drops the column.

Revision ID: d7f2a9c4e1b8
Revises: c3e7a1f9d2b4
Create Date: 2026-06-17 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d7f2a9c4e1b8"
down_revision: Union[str, Sequence[str], None] = "c3e7a1f9d2b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("automation_script_groups")}
    if "ci_job_name_webhook" in columns:
        return
    with op.batch_alter_table("automation_script_groups") as batch_op:
        batch_op.add_column(sa.Column("ci_job_name_webhook", sa.String(length=200), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("automation_script_groups")}
    if "ci_job_name_webhook" not in columns:
        return
    with op.batch_alter_table("automation_script_groups") as batch_op:
        batch_op.drop_column("ci_job_name_webhook")
