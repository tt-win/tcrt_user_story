"""add_scheduled_services

Revision ID: 6d8f3a1b9c20
Revises: 2c2d0f7f4d8b
Create Date: 2026-03-24 15:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6d8f3a1b9c20"
down_revision: Union[str, Sequence[str], None] = "2c2d0f7f4d8b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scheduled_services",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("service_key", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("schedule_type", sa.String(length=20), nullable=False),
        sa.Column("run_at_time", sa.String(length=5), nullable=True, comment="每日執行時間（HH:MM）"),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("is_running", sa.Boolean(), nullable=False),
        sa.Column("last_run_status", sa.String(length=20), nullable=True),
        sa.Column("last_run_message", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_run_started_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_finished_at", sa.DateTime(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("service_key", name="uq_scheduled_services_service_key"),
    )
    with op.batch_alter_table("scheduled_services", schema=None) as batch_op:
        batch_op.create_index("ix_scheduled_services_enabled_next_run", ["enabled", "next_run_at"], unique=False)
        batch_op.create_index("ix_scheduled_services_is_running", ["is_running"], unique=False)
        batch_op.create_index("ix_scheduled_services_last_run_status", ["last_run_status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_scheduled_services_last_run_status", table_name="scheduled_services")
    op.drop_index("ix_scheduled_services_is_running", table_name="scheduled_services")
    op.drop_index("ix_scheduled_services_enabled_next_run", table_name="scheduled_services")
    op.drop_table("scheduled_services")
