"""convert_enum_columns_to_portable_values

audit DB 的 `resource_type`（ResourceType，19 個成員）、`severity`（AuditSeverity，
3 個成員）、`action_type`（ActionType，6 個成員）從「儲存 member.name、MySQL inline
ENUM／PostgreSQL 具名 TYPE」改為「儲存 member.value、三引擎皆為一般字串欄位
（`values_callable` + `native_enum=False`）」。`action_type` 的 name 與 value 對每個
成員皆相同，資料轉換為 no-op，但仍需要 DDL 轉換（原生型別→字串欄位），否則新增
ActionType 成員時仍需要 `ALTER TYPE` / `MODIFY COLUMN`，違反「不再要求原生具名型別」
的可攜性目標。

**額外修正既有 drift**：audit_logs.resource_type 的原生具名型別自建立以來只有 11 個
標籤（初始 schema 當時的 ResourceType 成員），後續新增的 8 個 automation 相關成員
（AUTOMATION_PROVIDER 等）從未同步進 MySQL/PostgreSQL 的原生型別，導致在這兩個引擎上
寫入這些較新的 resource_type 值會被原生型別拒絕（SQLite 因無 CHECK 約束而未曝露此問題）。
本遷移以完整 19 成員的對照表重建型別，一併修正此 drift。

downgrade 會轉換回原生具名型別（MySQL ENUM / PostgreSQL named TYPE）。

Revision ID: 4e8f3d57b312
Revises: d4c9a8b7e6f5
Create Date: 2026-07-13 22:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

from app.db_migrations_enum_support import EnumColumnRef, migrate_enum_storage

revision: str = "4e8f3d57b312"
down_revision: Union[str, Sequence[str], None] = "d4c9a8b7e6f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ENUM_GROUPS: list[tuple[str, dict[str, str], list[EnumColumnRef]]] = [
    (
        "resourcetype",
        {
            "TEAM_SETTING": "team_setting",
            "TEST_RUN": "test_run",
            "TEST_CASE": "test_case",
            "TEST_CASE_SET": "test_case_set",
            "TEST_CASE_SECTION": "test_case_section",
            "USER_STORY_MAP": "user_story_map",
            "USER": "user",
            "AUTH": "auth",
            "PERMISSION": "permission",
            "ATTACHMENT": "attachment",
            "SYSTEM": "system",
            "AUTOMATION_PROVIDER": "automation_provider",
            "SYSTEM_AUTOMATION_PROVIDER": "system_automation_provider",
            "AUTOMATION_SCRIPT": "automation_script",
            "AUTOMATION_SCRIPT_LINK": "automation_script_link",
            "AUTOMATION_SCRIPT_GROUP": "automation_script_group",
            "AUTOMATION_RUN": "automation_run",
            "AUTOMATION_WEBHOOK": "automation_webhook",
            "AUTOMATION_ENVIRONMENT": "automation_environment",
        },
        [EnumColumnRef("audit_logs", "resource_type", nullable=False)],
    ),
    (
        "auditseverity",
        {"INFO": "info", "WARNING": "warning", "CRITICAL": "critical"},
        [EnumColumnRef("audit_logs", "severity", nullable=False)],
    ),
    (
        "actiontype",
        {
            "CREATE": "CREATE",
            "READ": "READ",
            "UPDATE": "UPDATE",
            "DELETE": "DELETE",
            "LOGIN": "LOGIN",
            "LOGOUT": "LOGOUT",
        },
        [EnumColumnRef("audit_logs", "action_type", nullable=False)],
    ),
]


def upgrade() -> None:
    bind = op.get_bind()
    for pg_type_name, name_to_value, columns in _ENUM_GROUPS:
        migrate_enum_storage(
            bind, mapping=name_to_value, columns=columns, pg_type_name=pg_type_name, target_native=False
        )


def downgrade() -> None:
    bind = op.get_bind()
    for pg_type_name, name_to_value, columns in _ENUM_GROUPS:
        value_to_name = {value: name for name, value in name_to_value.items()}
        migrate_enum_storage(
            bind, mapping=value_to_name, columns=columns, pg_type_name=pg_type_name, target_native=True
        )
