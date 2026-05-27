"""add_automation_hub_tables

Revision ID: e1a2b3c4d5f6
Revises: d4f6b8e2a3c1
Create Date: 2026-05-14 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db_types import MediumText


revision: str = "e1a2b3c4d5f6"
down_revision: Union[str, Sequence[str], None] = "d4f6b8e2a3c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


provider_slot_enum = sa.Enum("storage", "ci", "result", name="automation_provider_slot", native_enum=False)
script_format_enum = sa.Enum(
    "PLAYWRIGHT_PY_ASYNC",
    "PYTEST",
    "PLAYWRIGHT_JS",
    "OTHER",
    name="automation_script_format",
    native_enum=False,
)
link_type_enum = sa.Enum("PRIMARY", "COVERS", "REFERENCES", name="automation_script_link_type", native_enum=False)
script_group_job_type_enum = sa.Enum(
    "GITHUB_ACTIONS",
    "JENKINS",
    name="automation_script_group_job_type",
    native_enum=False,
)
run_status_enum = sa.Enum(
    "QUEUED",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    "CANCELLED",
    "UNKNOWN",
    name="automation_run_status",
    native_enum=False,
)
run_trigger_enum = sa.Enum("USER", "WEBHOOK", "SCHEDULE", "MCP", name="automation_run_trigger", native_enum=False)
webhook_direction_enum = sa.Enum("INBOUND", "OUTBOUND", name="automation_webhook_direction", native_enum=False)


def upgrade() -> None:
    op.create_table(
        "team_automation_providers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("provider_slot", provider_slot_enum, nullable=False),
        sa.Column("provider_type", sa.String(length=60), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("config_json", MediumText(), nullable=False),
        sa.Column("credentials_encrypted", MediumText(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_health_check_at", sa.DateTime(), nullable=True),
        sa.Column("last_health_status", sa.String(length=40), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id", "provider_slot", "name", name="uq_team_automation_provider_name"),
    )
    op.create_index("ix_team_automation_providers_team_id", "team_automation_providers", ["team_id"], unique=False)
    op.create_index(
        "ix_team_automation_providers_team_slot_active",
        "team_automation_providers",
        ["team_id", "provider_slot", "is_active"],
        unique=False,
    )

    op.create_table(
        "automation_scripts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", MediumText(), nullable=True),
        sa.Column("script_format", script_format_enum, nullable=False),
        sa.Column("ref_path", sa.String(length=500), nullable=False),
        sa.Column("ref_branch", sa.String(length=200), nullable=False),
        sa.Column("cached_content", MediumText(), nullable=True),
        sa.Column("cached_content_etag", sa.String(length=120), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("tags_json", MediumText(), nullable=True),
        sa.Column("preferred_runner_label", sa.String(length=100), nullable=True),
        sa.Column("linked_test_case_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["team_automation_providers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id", "provider_id", "ref_path", "ref_branch", name="uq_automation_script_ref"),
    )
    op.create_index("ix_automation_scripts_provider_id", "automation_scripts", ["provider_id"], unique=False)
    op.create_index("ix_automation_scripts_provider_synced", "automation_scripts", ["provider_id", "last_synced_at"], unique=False)
    op.create_index("ix_automation_scripts_team_format", "automation_scripts", ["team_id", "script_format"], unique=False)
    op.create_index("ix_automation_scripts_team_id", "automation_scripts", ["team_id"], unique=False)

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
    op.create_index("ix_automation_script_groups_team_id", "automation_script_groups", ["team_id"], unique=False)

    op.create_table(
        "automation_webhooks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("direction", webhook_direction_enum, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("secret", sa.String(length=128), nullable=True),
        sa.Column("target_url", sa.String(length=500), nullable=True),
        sa.Column("events_json", MediumText(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_triggered_at", sa.DateTime(), nullable=True),
        sa.Column("last_status", sa.String(length=40), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token", name="uq_automation_webhooks_token"),
    )
    op.create_index("ix_automation_webhooks_team_id", "automation_webhooks", ["team_id"], unique=False)
    op.create_index(
        "ix_automation_webhooks_team_direction_active",
        "automation_webhooks",
        ["team_id", "direction", "is_active"],
        unique=False,
    )

    op.create_table(
        "automation_script_case_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("automation_script_id", sa.Integer(), nullable=False),
        sa.Column("test_case_id", sa.Integer(), nullable=False),
        sa.Column("link_type", link_type_enum, nullable=False),
        sa.Column("note", MediumText(), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["automation_script_id"], ["automation_scripts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["test_case_id"], ["test_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("automation_script_id", "test_case_id", name="uq_automation_script_case_link"),
    )
    op.create_index("ix_automation_script_case_links_automation_script_id", "automation_script_case_links", ["automation_script_id"], unique=False)
    op.create_index("ix_automation_script_case_links_team_id", "automation_script_case_links", ["team_id"], unique=False)
    op.create_index("ix_automation_script_case_links_test_case_id", "automation_script_case_links", ["test_case_id"], unique=False)

    op.create_table(
        "automation_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("automation_script_id", sa.Integer(), nullable=True),
        sa.Column("script_group_id", sa.Integer(), nullable=True),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("external_run_id", sa.String(length=120), nullable=True),
        sa.Column("external_run_url", sa.String(length=500), nullable=True),
        sa.Column("status", run_status_enum, nullable=False),
        sa.Column("triggered_by", run_trigger_enum, nullable=False),
        sa.Column("triggered_by_user_id", sa.String(length=64), nullable=True),
        sa.Column("triggered_by_webhook_id", sa.Integer(), nullable=True),
        sa.Column("tcrt_correlation_id", sa.String(length=36), nullable=False),
        sa.Column("ci_correlation_id", sa.String(length=120), nullable=True),
        sa.Column("workflow_id", sa.String(length=200), nullable=False),
        sa.Column("branch", sa.String(length=200), nullable=False),
        sa.Column("inputs_json", MediumText(), nullable=True),
        sa.Column("runner_label", sa.String(length=100), nullable=True),
        sa.Column("report_url", sa.String(length=500), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_summary", MediumText(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["automation_script_id"], ["automation_scripts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["script_group_id"], ["automation_script_groups.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["provider_id"], ["team_automation_providers.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["triggered_by_webhook_id"], ["automation_webhooks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tcrt_correlation_id", name="uq_automation_runs_tcrt_correlation_id"),
    )
    op.create_index("ix_automation_runs_automation_script_id", "automation_runs", ["automation_script_id"], unique=False)
    op.create_index("ix_automation_runs_external_run_id", "automation_runs", ["external_run_id"], unique=False)
    op.create_index("ix_automation_runs_group_started", "automation_runs", ["script_group_id", "started_at"], unique=False)
    op.create_index("ix_automation_runs_provider_id", "automation_runs", ["provider_id"], unique=False)
    op.create_index("ix_automation_runs_script_group_id", "automation_runs", ["script_group_id"], unique=False)
    op.create_index("ix_automation_runs_script_started", "automation_runs", ["automation_script_id", "started_at"], unique=False)
    op.create_index("ix_automation_runs_status_synced", "automation_runs", ["status", "last_synced_at"], unique=False)
    op.create_index("ix_automation_runs_team_id", "automation_runs", ["team_id"], unique=False)
    op.create_index("ix_automation_runs_team_started", "automation_runs", ["team_id", "started_at"], unique=False)
    op.create_index("ix_automation_runs_tcrt_correlation_id", "automation_runs", ["tcrt_correlation_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_automation_runs_tcrt_correlation_id", table_name="automation_runs")
    op.drop_index("ix_automation_runs_team_started", table_name="automation_runs")
    op.drop_index("ix_automation_runs_team_id", table_name="automation_runs")
    op.drop_index("ix_automation_runs_status_synced", table_name="automation_runs")
    op.drop_index("ix_automation_runs_script_started", table_name="automation_runs")
    op.drop_index("ix_automation_runs_script_group_id", table_name="automation_runs")
    op.drop_index("ix_automation_runs_provider_id", table_name="automation_runs")
    op.drop_index("ix_automation_runs_group_started", table_name="automation_runs")
    op.drop_index("ix_automation_runs_external_run_id", table_name="automation_runs")
    op.drop_index("ix_automation_runs_automation_script_id", table_name="automation_runs")
    op.drop_table("automation_runs")

    op.drop_index("ix_automation_script_case_links_test_case_id", table_name="automation_script_case_links")
    op.drop_index("ix_automation_script_case_links_team_id", table_name="automation_script_case_links")
    op.drop_index("ix_automation_script_case_links_automation_script_id", table_name="automation_script_case_links")
    op.drop_table("automation_script_case_links")

    op.drop_index("ix_automation_webhooks_team_direction_active", table_name="automation_webhooks")
    op.drop_index("ix_automation_webhooks_team_id", table_name="automation_webhooks")
    op.drop_table("automation_webhooks")

    op.drop_index("ix_automation_script_groups_team_id", table_name="automation_script_groups")
    op.drop_table("automation_script_groups")

    op.drop_index("ix_automation_scripts_team_id", table_name="automation_scripts")
    op.drop_index("ix_automation_scripts_team_format", table_name="automation_scripts")
    op.drop_index("ix_automation_scripts_provider_synced", table_name="automation_scripts")
    op.drop_index("ix_automation_scripts_provider_id", table_name="automation_scripts")
    op.drop_table("automation_scripts")

    op.drop_index("ix_team_automation_providers_team_slot_active", table_name="team_automation_providers")
    op.drop_index("ix_team_automation_providers_team_id", table_name="team_automation_providers")
    op.drop_table("team_automation_providers")
