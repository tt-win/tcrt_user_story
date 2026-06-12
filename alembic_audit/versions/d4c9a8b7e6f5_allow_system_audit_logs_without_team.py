"""allow_system_audit_logs_without_team

Revision ID: d4c9a8b7e6f5
Revises: 8ac7d1e42b90
Create Date: 2026-06-11 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4c9a8b7e6f5"
down_revision: Union[str, Sequence[str], None] = "8ac7d1e42b90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        batch_op.alter_column(
            "team_id",
            existing_type=sa.Integer(),
            nullable=True,
        )


def downgrade() -> None:
    op.execute("UPDATE audit_logs SET team_id = 0 WHERE team_id IS NULL")
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        batch_op.alter_column(
            "team_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
