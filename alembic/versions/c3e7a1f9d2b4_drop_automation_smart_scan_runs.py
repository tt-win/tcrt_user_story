"""drop_automation_smart_scan_runs

Removes the Smart Scan (智慧掃描) feature's run table. The feature and all its
code/UI/endpoints were removed; this drops its now-orphaned persistence table.
Mirrors the create block from a8f2d6c9e0b1 in downgrade() for reversibility.

**2026-07-14 engine-portability fix**: `upgrade()` used to drop each index
individually before `op.drop_table(...)` — entirely redundant (dropping a table
already drops its own indexes/constraints on every engine) and actively broken on
MySQL, which refuses to `DROP INDEX` on the auto-created index backing a still-live
foreign key (`ix_automation_smart_scan_runs_provider_id` backs the `provider_id` FK),
so this revision could never complete on a real MySQL server. Removed the redundant
index-drop loop; `op.drop_table(...)` alone is sufficient and portable.

Revision ID: c3e7a1f9d2b4
Revises: f1a2b3c4d5e6
Create Date: 2026-06-16 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db_types import MediumText


revision: str = "c3e7a1f9d2b4"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
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
    if "automation_smart_scan_runs" not in set(inspector.get_table_names()):
        return
    op.drop_table("automation_smart_scan_runs")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "automation_smart_scan_runs" in set(inspector.get_table_names()):
        return
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
