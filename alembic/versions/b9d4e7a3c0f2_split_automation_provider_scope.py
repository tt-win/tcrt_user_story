"""split_automation_provider_scope

Splits automation provider configuration into two tables:
- team_automation_providers keeps storage providers (CHECK ensures slot='storage').
- system_automation_providers is new and holds org-scoped CI / Result providers.

Also retargets automation_runs.provider_id FK from team_automation_providers
to system_automation_providers (runs are CI runs).

This migration purges any pre-existing non-storage rows from
team_automation_providers and any existing automation_runs so the new
constraints / FKs apply cleanly.

Revision ID: b9d4e7a3c0f2
Revises: a8f2d6c9e0b1
Create Date: 2026-05-21 09:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b9d4e7a3c0f2"
down_revision: Union[str, Sequence[str], None] = "a8f2d6c9e0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# automation_runs schema is rebuilt explicitly to retarget provider_id FK
# without leaving the original anonymous FK behind. Keep this in sync with the
# ORM in app/models/database_models.py (AutomationRun).
# ---------------------------------------------------------------------------
AUTOMATION_RUNS_INDEXES = [
    ("ix_automation_runs_tcrt_correlation_id", "tcrt_correlation_id"),
    ("ix_automation_runs_team_id", "team_id"),
    ("ix_automation_runs_automation_script_id", "automation_script_id"),
    ("ix_automation_runs_script_group_id", "script_group_id"),
    ("ix_automation_runs_provider_id", "provider_id"),
    ("ix_automation_runs_external_run_id", "external_run_id"),
    ("ix_automation_runs_team_started", "team_id, started_at"),
    ("ix_automation_runs_script_started", "automation_script_id, started_at"),
    ("ix_automation_runs_group_started", "script_group_id, started_at"),
    ("ix_automation_runs_status_synced", "status, last_synced_at"),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # 1) Purge non-storage rows from team table; truncate automation_runs.
    if "automation_runs" in existing_tables:
        op.execute(sa.text("DELETE FROM automation_runs"))
    if "team_automation_providers" in existing_tables:
        op.execute(sa.text("DELETE FROM team_automation_providers WHERE provider_slot != 'storage'"))

    # 2) Create the org-scoped table.
    if "system_automation_providers" not in existing_tables:
        op.create_table(
            "system_automation_providers",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider_slot", sa.String(length=20), nullable=False),
            sa.Column("provider_type", sa.String(length=60), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("config_json", sa.Text(), nullable=False),
            sa.Column("credentials_encrypted", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("last_health_check_at", sa.DateTime(), nullable=True),
            sa.Column("last_health_status", sa.String(length=40), nullable=True),
            sa.Column("created_by", sa.String(length=64), nullable=True),
            sa.Column("updated_by", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("provider_slot", "name", name="uq_system_automation_provider_name"),
            sa.CheckConstraint(
                "provider_slot IN ('ci', 'result')",
                name="ck_system_provider_ci_or_result_only",
            ),
        )
        op.create_index(
            "ix_system_automation_providers_slot_active",
            "system_automation_providers",
            ["provider_slot", "is_active"],
        )

    # 3) Add CHECK constraint to team table (storage-only).
    inspector = sa.inspect(bind)
    team_check_names = {c.get("name") for c in inspector.get_check_constraints("team_automation_providers")}
    if "ck_team_provider_storage_only" not in team_check_names:
        with op.batch_alter_table("team_automation_providers") as batch_op:
            batch_op.create_check_constraint(
                "ck_team_provider_storage_only",
                "provider_slot = 'storage'",
            )

    # 4) Rebuild automation_runs to retarget provider_id FK. Raw DDL avoids
    #    alembic batch_alter_table preserving the original anonymous FK.
    if "automation_runs" in existing_tables:
        # Drop old indexes first (will be recreated on the new table)
        for index_name, _ in AUTOMATION_RUNS_INDEXES:
            op.execute(sa.text(f"DROP INDEX IF EXISTS {index_name}"))

        op.execute(sa.text("ALTER TABLE automation_runs RENAME TO automation_runs_old"))
        op.execute(
            sa.text(
                """
                CREATE TABLE automation_runs (
                    id INTEGER NOT NULL,
                    team_id INTEGER NOT NULL,
                    automation_script_id INTEGER,
                    script_group_id INTEGER,
                    provider_id INTEGER NOT NULL,
                    external_run_id VARCHAR(120),
                    external_run_url VARCHAR(500),
                    status VARCHAR(9) NOT NULL,
                    triggered_by VARCHAR(8) NOT NULL,
                    triggered_by_user_id VARCHAR(64),
                    triggered_by_webhook_id INTEGER,
                    tcrt_correlation_id VARCHAR(36) NOT NULL,
                    ci_correlation_id VARCHAR(120),
                    workflow_id VARCHAR(200) NOT NULL,
                    branch VARCHAR(200) NOT NULL,
                    inputs_json TEXT,
                    runner_label VARCHAR(100),
                    report_url VARCHAR(500),
                    started_at DATETIME,
                    finished_at DATETIME,
                    duration_ms INTEGER,
                    error_summary TEXT,
                    last_synced_at DATETIME,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    PRIMARY KEY (id),
                    CONSTRAINT uq_automation_runs_tcrt_correlation_id UNIQUE (tcrt_correlation_id),
                    CONSTRAINT fk_automation_runs_team_id FOREIGN KEY(team_id) REFERENCES teams (id) ON DELETE CASCADE,
                    CONSTRAINT fk_automation_runs_automation_script_id FOREIGN KEY(automation_script_id) REFERENCES automation_scripts (id) ON DELETE SET NULL,
                    CONSTRAINT fk_automation_runs_script_group_id FOREIGN KEY(script_group_id) REFERENCES automation_script_groups (id) ON DELETE SET NULL,
                    CONSTRAINT fk_automation_runs_triggered_by_webhook_id FOREIGN KEY(triggered_by_webhook_id) REFERENCES automation_webhooks (id),
                    CONSTRAINT fk_automation_runs_provider_id_system FOREIGN KEY(provider_id) REFERENCES system_automation_providers (id)
                )
                """
            )
        )
        op.execute(sa.text("DROP TABLE automation_runs_old"))
        for index_name, columns in AUTOMATION_RUNS_INDEXES:
            op.execute(sa.text(f"CREATE INDEX {index_name} ON automation_runs ({columns})"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # 1) Retarget automation_runs.provider_id back to team table via rebuild.
    if "automation_runs" in existing_tables:
        op.execute(sa.text("DELETE FROM automation_runs"))
        for index_name, _ in AUTOMATION_RUNS_INDEXES:
            op.execute(sa.text(f"DROP INDEX IF EXISTS {index_name}"))
        op.execute(sa.text("ALTER TABLE automation_runs RENAME TO automation_runs_old"))
        op.execute(
            sa.text(
                """
                CREATE TABLE automation_runs (
                    id INTEGER NOT NULL,
                    team_id INTEGER NOT NULL,
                    automation_script_id INTEGER,
                    script_group_id INTEGER,
                    provider_id INTEGER NOT NULL,
                    external_run_id VARCHAR(120),
                    external_run_url VARCHAR(500),
                    status VARCHAR(9) NOT NULL,
                    triggered_by VARCHAR(8) NOT NULL,
                    triggered_by_user_id VARCHAR(64),
                    triggered_by_webhook_id INTEGER,
                    tcrt_correlation_id VARCHAR(36) NOT NULL,
                    ci_correlation_id VARCHAR(120),
                    workflow_id VARCHAR(200) NOT NULL,
                    branch VARCHAR(200) NOT NULL,
                    inputs_json TEXT,
                    runner_label VARCHAR(100),
                    report_url VARCHAR(500),
                    started_at DATETIME,
                    finished_at DATETIME,
                    duration_ms INTEGER,
                    error_summary TEXT,
                    last_synced_at DATETIME,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    PRIMARY KEY (id),
                    CONSTRAINT uq_automation_runs_tcrt_correlation_id UNIQUE (tcrt_correlation_id),
                    FOREIGN KEY(team_id) REFERENCES teams (id) ON DELETE CASCADE,
                    FOREIGN KEY(automation_script_id) REFERENCES automation_scripts (id) ON DELETE SET NULL,
                    FOREIGN KEY(script_group_id) REFERENCES automation_script_groups (id) ON DELETE SET NULL,
                    FOREIGN KEY(triggered_by_webhook_id) REFERENCES automation_webhooks (id),
                    FOREIGN KEY(provider_id) REFERENCES team_automation_providers (id)
                )
                """
            )
        )
        op.execute(sa.text("DROP TABLE automation_runs_old"))
        for index_name, columns in AUTOMATION_RUNS_INDEXES:
            op.execute(sa.text(f"CREATE INDEX {index_name} ON automation_runs ({columns})"))

    # 2) Drop CHECK on team table.
    inspector = sa.inspect(bind)
    team_check_names = {c.get("name") for c in inspector.get_check_constraints("team_automation_providers")}
    if "ck_team_provider_storage_only" in team_check_names:
        with op.batch_alter_table("team_automation_providers") as batch_op:
            batch_op.drop_constraint("ck_team_provider_storage_only", type_="check")

    # 3) Drop the system table.
    if "system_automation_providers" in existing_tables:
        op.drop_index("ix_system_automation_providers_slot_active", table_name="system_automation_providers")
        op.drop_table("system_automation_providers")
