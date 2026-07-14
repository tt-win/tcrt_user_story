"""convert_enum_columns_to_portable_values

主庫 17 個 enum 欄位（10 個 enum 類別）從「儲存 member.name、MySQL inline ENUM／
PostgreSQL 具名 TYPE」改為「儲存 member.value、三引擎皆為一般字串欄位
（`values_callable` + `native_enum=False`）」。SQLite 僅資料轉換（本來就是 VARCHAR）；
MySQL 逐欄位放寬為 VARCHAR 後轉換資料，不再收斂回 ENUM；PostgreSQL 逐 enum 類別把
欄位改為 TEXT、drop 具名 TYPE 後轉換資料，不再重建 TYPE（可能跨多個 table/column
共用同一個 TYPE）。不再要求原生 ENUM / named TYPE 是「新增 enum 值不需要
`ALTER TYPE` / `MODIFY COLUMN`」得以成立的原因。downgrade 會轉換回原生具名型別。
詳見 `app/db_migrations_enum_support.py`。

Revision ID: 21a93e84da75
Revises: d4e6f8a0b2c4
Create Date: 2026-07-13 22:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

from app.db_migrations_enum_support import EnumColumnRef, migrate_enum_storage

revision: str = "21a93e84da75"
down_revision: Union[str, Sequence[str], None] = "d4e6f8a0b2c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 每個 enum 類別：(PostgreSQL 具名 type 名稱, {name: value} 對照, 使用該 enum 的欄位清單)
_ENUM_GROUPS: list[tuple[str, dict[str, str], list[EnumColumnRef]]] = [
    (
        "priority",
        {"HIGH": "High", "MEDIUM": "Medium", "LOW": "Low"},
        [
            EnumColumnRef("teams", "default_priority", nullable=True),
            EnumColumnRef("test_cases", "priority", nullable=True),
            EnumColumnRef("adhoc_run_items", "priority", nullable=True),
        ],
    ),
    (
        "teamstatus",
        {"ACTIVE": "active", "INACTIVE": "inactive", "ARCHIVED": "archived"},
        [EnumColumnRef("teams", "status", nullable=True)],
    ),
    (
        "testrunstatus",
        {"ACTIVE": "active", "COMPLETED": "completed", "DRAFT": "draft", "ARCHIVED": "archived"},
        [
            EnumColumnRef("test_run_configs", "status", nullable=True),
            EnumColumnRef("adhoc_runs", "status", nullable=False),
        ],
    ),
    (
        "testrunsetstatus",
        {"ACTIVE": "active", "COMPLETED": "completed", "ARCHIVED": "archived"},
        [EnumColumnRef("test_run_sets", "status", nullable=False)],
    ),
    (
        "testresultstatus",
        {
            "PASSED": "Passed",
            "FAILED": "Failed",
            "RETEST": "Retest",
            "NOT_AVAILABLE": "Not Available",
            "PENDING": "Pending",
            "NOT_REQUIRED": "Not Required",
            "SKIP": "Skip",
        },
        [
            EnumColumnRef("test_run_items", "test_result", nullable=True),
            EnumColumnRef("test_run_item_result_history", "prev_result", nullable=True),
            EnumColumnRef("test_run_item_result_history", "new_result", nullable=True),
            EnumColumnRef("test_cases", "test_result", nullable=True),
            EnumColumnRef("adhoc_run_items", "test_result", nullable=True),
        ],
    ),
    (
        "syncstatus",
        {"SYNCED": "synced", "PENDING": "pending", "CONFLICT": "conflict"},
        [EnumColumnRef("test_cases", "sync_status", nullable=False)],
    ),
    (
        "userrole",
        {"VIEWER": "viewer", "USER": "user", "ADMIN": "admin", "SUPER_ADMIN": "super_admin"},
        [EnumColumnRef("users", "role", nullable=False)],
    ),
    (
        "permissiontype",
        {"READ": "read", "WRITE": "write", "ADMIN": "admin"},
        [EnumColumnRef("user_team_permissions", "permission", nullable=False)],
    ),
    (
        "mcpmachinecredentialstatus",
        {"ACTIVE": "active", "REVOKED": "revoked"},
        [EnumColumnRef("mcp_machine_credentials", "status", nullable=False)],
    ),
    (
        "teamapptokenstatus",
        {"ACTIVE": "active", "REVOKED": "revoked"},
        [EnumColumnRef("team_app_tokens", "status", nullable=False)],
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
