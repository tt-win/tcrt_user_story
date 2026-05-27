"""add_automation_scan_and_delivery_tables

Revision ID: a8f2d6c9e0b1
Revises: f7e1c2b3d4a5
Create Date: 2026-05-19 10:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db_types import MediumText


revision: str = "a8f2d6c9e0b1"
down_revision: Union[str, Sequence[str], None] = "f7e1c2b3d4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


smart_scan_status_enum = sa.Enum(
    "QUEUED",
    "SCANNING",
    "ENRICHING",
    "READY",
    "FAILED",
    "CANCELLED",
    name="automation_smart_scan_status",
    native_enum=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "automation_smart_scan_runs" not in existing_tables:
        op.create_table(
            "automation_smart_scan_runs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("team_id", sa.Integer(), nullable=False),
            sa.Column("provider_id", sa.Integer(), nullable=False),
            sa.Column("status", smart_scan_status_enum, nullable=False),
            sa.Column("scan_config_hash", sa.String(length=64), nullable=False),
            sa.Column("progress_json", MediumText(), nullable=True),
            sa.Column("result_json", MediumText(), nullable=True),
            sa.Column("error_summary", MediumText(), nullable=True),
            sa.Column("created_by", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["provider_id"], ["team_automation_providers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_automation_smart_scan_runs_team_id", "automation_smart_scan_runs", ["team_id"])
        op.create_index("ix_automation_smart_scan_runs_provider_id", "automation_smart_scan_runs", ["provider_id"])
        op.create_index(
            "ix_automation_smart_scan_runs_team_status",
            "automation_smart_scan_runs",
            ["team_id", "status"],
        )
        op.create_index(
            "ix_automation_smart_scan_runs_provider_hash",
            "automation_smart_scan_runs",
            ["provider_id", "scan_config_hash"],
        )

    if "automation_webhook_deliveries" not in existing_tables:
        op.create_table(
            "automation_webhook_deliveries",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("team_id", sa.Integer(), nullable=False),
            sa.Column("webhook_id", sa.Integer(), nullable=False),
            sa.Column("event", sa.String(length=80), nullable=False),
            sa.Column("delivery_id", sa.String(length=36), nullable=False),
            sa.Column("target_url", sa.String(length=500), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("status_code", sa.Integer(), nullable=True),
            sa.Column("request_body", MediumText(), nullable=False),
            sa.Column("response_body", MediumText(), nullable=True),
            sa.Column("error_message", MediumText(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["webhook_id"], ["automation_webhooks.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_automation_webhook_deliveries_team_id", "automation_webhook_deliveries", ["team_id"])
        op.create_index("ix_automation_webhook_deliveries_webhook_id", "automation_webhook_deliveries", ["webhook_id"])
        op.create_index(
            "ix_automation_webhook_deliveries_team_created",
            "automation_webhook_deliveries",
            ["team_id", "created_at"],
        )
        op.create_index(
            "ix_automation_webhook_deliveries_webhook_created",
            "automation_webhook_deliveries",
            ["webhook_id", "created_at"],
        )
        op.create_index(
            "ix_automation_webhook_deliveries_delivery_id",
            "automation_webhook_deliveries",
            ["delivery_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "automation_webhook_deliveries" in existing_tables:
        indexes = {ix["name"] for ix in inspector.get_indexes("automation_webhook_deliveries")}
        for name in (
            "ix_automation_webhook_deliveries_delivery_id",
            "ix_automation_webhook_deliveries_webhook_created",
            "ix_automation_webhook_deliveries_team_created",
            "ix_automation_webhook_deliveries_webhook_id",
            "ix_automation_webhook_deliveries_team_id",
        ):
            if name in indexes:
                op.drop_index(name, table_name="automation_webhook_deliveries")
        op.drop_table("automation_webhook_deliveries")

    if "automation_smart_scan_runs" in existing_tables:
        indexes = {ix["name"] for ix in inspector.get_indexes("automation_smart_scan_runs")}
        for name in (
            "ix_automation_smart_scan_runs_provider_hash",
            "ix_automation_smart_scan_runs_team_status",
            "ix_automation_smart_scan_runs_provider_id",
            "ix_automation_smart_scan_runs_team_id",
        ):
            if name in indexes:
                op.drop_index(name, table_name="automation_smart_scan_runs")
        op.drop_table("automation_smart_scan_runs")
