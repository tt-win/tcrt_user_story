"""add_webhook_script_group_id

Adds nullable script_group_id FK to automation_webhooks so an INBOUND webhook
can bind a test suite (script group) and trigger its run via the public
/trigger endpoint. Non-destructive: existing rows get NULL.

Revision ID: c1d2e3f4a5b6
Revises: b9d4e7a3c0f2
Create Date: 2026-05-27 15:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b9d4e7a3c0f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("automation_webhooks")}
    if "script_group_id" in columns:
        return
    with op.batch_alter_table("automation_webhooks") as batch_op:
        batch_op.add_column(sa.Column("script_group_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_automation_webhooks_script_group_id",
            "automation_script_groups",
            ["script_group_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_automation_webhooks_script_group_id",
            ["script_group_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("automation_webhooks")}
    if "script_group_id" not in columns:
        return
    with op.batch_alter_table("automation_webhooks") as batch_op:
        batch_op.drop_index("ix_automation_webhooks_script_group_id")
        batch_op.drop_constraint("fk_automation_webhooks_script_group_id", type_="foreignkey")
        batch_op.drop_column("script_group_id")
