"""make_automation_enums_portable

The 7 Automation Hub enum classes (`AutomationProviderSlot`, `AutomationScriptFormat`,
`AutomationScriptLinkType`, `AutomationScriptGroupJobType`, `AutomationRunStatus`,
`AutomationRunTrigger`, `AutomationWebhookDirection`) were the reference pattern
Change B's enum work (`21a93e84da75`/`4e8f3d57b312`) aligned to — they already used
`values_callable` (so `.value` was always stored, never `.name`), but never had
`native_enum=False`. So MySQL still had a native inline `ENUM(...)` and PostgreSQL a
named `CREATE TYPE ... AS ENUM` for all 8 of these columns, meaning adding a new
member to any of these 7 enums would still require `MODIFY COLUMN` / `ALTER TYPE`.

Since `.value` was already stored correctly, this is a pure DDL/type conversion —
identity mapping for every group, no data changes. Follows the exact same
`target_native` convention as Change B's enum migrations: `target_native=False` on
upgrade (portable VARCHAR/TEXT, no native type), `target_native=True` on downgrade
(restore native ENUM/named TYPE).

Revision ID: bc617a8e539d
Revises: f84bbca9a911
Create Date: 2026-07-14 13:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

from app.db_migrations_enum_support import EnumColumnRef, migrate_enum_storage

revision: str = "bc617a8e539d"
down_revision: Union[str, Sequence[str], None] = "f84bbca9a911"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 每組：(PostgreSQL 具名 type 名稱, 直接沿用的 value → value identity mapping, 使用該 enum 的欄位清單)
_ENUM_GROUPS: list[tuple[str, dict[str, str], list[EnumColumnRef]]] = [
    (
        "automationproviderslot",
        {"storage": "storage", "ci": "ci", "result": "result"},
        [
            EnumColumnRef("team_automation_providers", "provider_slot", nullable=False),
            EnumColumnRef("system_automation_providers", "provider_slot", nullable=False),
        ],
    ),
    (
        "automationscriptformat",
        {
            "PLAYWRIGHT_PY_ASYNC": "PLAYWRIGHT_PY_ASYNC",
            "PYTEST": "PYTEST",
            "PLAYWRIGHT_JS": "PLAYWRIGHT_JS",
            "OTHER": "OTHER",
        },
        [EnumColumnRef("automation_scripts", "script_format", nullable=False)],
    ),
    (
        "automationscriptlinktype",
        {"PRIMARY": "PRIMARY", "COVERS": "COVERS", "REFERENCES": "REFERENCES"},
        [EnumColumnRef("automation_script_case_links", "link_type", nullable=False)],
    ),
    (
        "automationscriptgroupjobtype",
        {"JENKINS": "JENKINS"},
        [EnumColumnRef("automation_script_groups", "ci_job_type", nullable=True)],
    ),
    (
        "automationrunstatus",
        {
            "QUEUED": "QUEUED",
            "RUNNING": "RUNNING",
            "SUCCEEDED": "SUCCEEDED",
            "FAILED": "FAILED",
            "CANCELLED": "CANCELLED",
            "UNKNOWN": "UNKNOWN",
        },
        [EnumColumnRef("automation_runs", "status", nullable=False)],
    ),
    (
        "automationruntrigger",
        {"USER": "USER", "WEBHOOK": "WEBHOOK", "SCHEDULE": "SCHEDULE", "MCP": "MCP"},
        [EnumColumnRef("automation_runs", "triggered_by", nullable=False)],
    ),
    (
        "automationwebhookdirection",
        {"INBOUND": "INBOUND", "OUTBOUND": "OUTBOUND"},
        [EnumColumnRef("automation_webhooks", "direction", nullable=False)],
    ),
]


def upgrade() -> None:
    bind = op.get_bind()
    for pg_type_name, mapping, columns in _ENUM_GROUPS:
        migrate_enum_storage(
            bind, mapping=mapping, columns=columns, pg_type_name=pg_type_name, target_native=False
        )


def downgrade() -> None:
    bind = op.get_bind()
    for pg_type_name, mapping, columns in _ENUM_GROUPS:
        migrate_enum_storage(
            bind, mapping=mapping, columns=columns, pg_type_name=pg_type_name, target_native=True
        )
