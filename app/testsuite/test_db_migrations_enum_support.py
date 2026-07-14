"""`app/db_migrations_enum_support.py` 的單元測試（SQLite）與真實 MySQL/PostgreSQL 整合測試。

MySQL/PostgreSQL 測試預設 skip（需要真實可連線的 server），比照
`app/testsuite/test_db_backup_server_engines.py` 的 env-gated 慣例。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, text

import app.db_migrations_enum_support as enum_support_module
from app.db_migrations_enum_support import EnumColumnRef, migrate_enum_storage

MYSQL_URL_ENV = "TCRT_TEST_MYSQL_URL"
POSTGRES_URL_ENV = "TCRT_TEST_POSTGRES_URL"


def _bind_operations(monkeypatch, connection) -> None:
    """把 module-level `op` 代理綁到這個測試連線，讓 helper 內的 op.execute/op.alter_column 生效。

    必須用 `monkeypatch.setattr`（而非直接賦值）：`db_migrations_enum_support.op` 原本是
    `alembic.op` 的 context-local proxy，直接賦值會把它永久換成綁定此測試連線的具體
    `Operations` 實例，導致連線關閉後，同一 pytest process 內其他測試（例如真的透過
    Alembic 執行 `21a93e84da75` 這個 migration）呼叫到 `migrate_enum_storage` 時會用到
    這個已關閉的連線而爆炸。`monkeypatch.setattr` 會在測試結束時自動還原成原本的 proxy。
    """
    ctx = MigrationContext.configure(connection)
    monkeypatch.setattr(enum_support_module, "op", Operations(ctx))


def test_sqlite_migrates_values_without_type_change(monkeypatch, tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'enum.db'}", future=True)
    metadata = MetaData()
    teams = Table(
        "teams",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("priority", String(20), nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(teams.insert(), [{"id": 1, "priority": "HIGH"}, {"id": 2, "priority": "MEDIUM"}])

    with engine.connect() as conn:
        _bind_operations(monkeypatch, conn)
        migrate_enum_storage(
            conn,
            mapping={"HIGH": "High", "MEDIUM": "Medium", "LOW": "Low"},
            columns=[EnumColumnRef("teams", "priority", nullable=False)],
            pg_type_name="priority",
        )
        conn.commit()

    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, priority FROM teams ORDER BY id")).fetchall()
    assert rows == [(1, "High"), (2, "Medium")]


def test_sqlite_no_op_when_name_equals_value(monkeypatch, tmp_path: Path) -> None:
    """name == value 的成員（如 ActionType）不應被誤觸發多餘的 UPDATE（雖然結果無害，但驗證迴圈正確跳過）。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'enum.db'}", future=True)
    metadata = MetaData()
    logs = Table(
        "audit_logs",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("action_type", String(20), nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(logs.insert(), [{"id": 1, "action_type": "CREATE"}])

    with engine.connect() as conn:
        _bind_operations(monkeypatch, conn)
        migrate_enum_storage(
            conn,
            mapping={"CREATE": "CREATE", "READ": "READ"},
            columns=[EnumColumnRef("audit_logs", "action_type", nullable=False)],
            pg_type_name="actiontype",
        )
        conn.commit()

    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, action_type FROM audit_logs ORDER BY id")).fetchall()
    assert rows == [(1, "CREATE")]


def _require_mysql() -> str:
    url = os.getenv(MYSQL_URL_ENV)
    if not url:
        pytest.skip(f"{MYSQL_URL_ENV} 未設定，略過需要真實 MySQL server 的整合測試")
    return url


def _require_postgres() -> str:
    url = os.getenv(POSTGRES_URL_ENV)
    if not url:
        pytest.skip(f"{POSTGRES_URL_ENV} 未設定，略過需要真實 PostgreSQL server 的整合測試")
    return url


def test_mysql_converts_to_portable_varchar_by_default(monkeypatch) -> None:
    """target_native 預設 False（upgrade 方向）：轉換完成後留在 VARCHAR，不收斂回 ENUM——
    這是「新增 enum 值不需要 MODIFY COLUMN」得以成立的關鍵行為。"""
    database_url = _require_mysql()
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS enum_migration_pytest"))
            conn.execute(
                text(
                    "CREATE TABLE enum_migration_pytest (id INT PRIMARY KEY, "
                    "priority ENUM('HIGH','MEDIUM','LOW') NOT NULL)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO enum_migration_pytest (id, priority) VALUES "
                    "(1,'HIGH'), (2,'MEDIUM'), (3,'LOW')"
                )
            )

        with engine.connect() as conn:
            _bind_operations(monkeypatch, conn)
            migrate_enum_storage(
                conn,
                mapping={"HIGH": "High", "MEDIUM": "Medium", "LOW": "Low"},
                columns=[EnumColumnRef("enum_migration_pytest", "priority", nullable=False)],
                pg_type_name="priority",
            )
            conn.commit()

        with engine.connect() as conn:
            rows = conn.execute(text("SELECT id, priority FROM enum_migration_pytest ORDER BY id")).fetchall()
            assert rows == [(1, "High"), (2, "Medium"), (3, "Low")]
            col_type = conn.execute(text("SHOW COLUMNS FROM enum_migration_pytest LIKE 'priority'")).fetchone()
            assert col_type[1].startswith("varchar")

            # 新增一個 enum 值（例如新增 'Critical'）不需要任何 DDL 就能寫入/讀出。
            conn.execute(
                text("INSERT INTO enum_migration_pytest (id, priority) VALUES (4, 'Critical')")
            )
            conn.commit()
            new_row = conn.execute(
                text("SELECT priority FROM enum_migration_pytest WHERE id = 4")
            ).scalar()
            assert new_row == "Critical"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS enum_migration_pytest"))
        engine.dispose()


def test_mysql_target_native_restores_enum_type(monkeypatch) -> None:
    """target_native=True（downgrade 方向）：轉換完成後收斂回原生 ENUM，還原成 migration
    執行前的具名型別狀態。"""
    database_url = _require_mysql()
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS enum_migration_pytest"))
            conn.execute(
                text(
                    "CREATE TABLE enum_migration_pytest (id INT PRIMARY KEY, "
                    "priority VARCHAR(64) NOT NULL)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO enum_migration_pytest (id, priority) VALUES "
                    "(1,'High'), (2,'Medium'), (3,'Low')"
                )
            )

        with engine.connect() as conn:
            _bind_operations(monkeypatch, conn)
            migrate_enum_storage(
                conn,
                mapping={"High": "HIGH", "Medium": "MEDIUM", "Low": "LOW"},
                columns=[EnumColumnRef("enum_migration_pytest", "priority", nullable=False)],
                pg_type_name="priority",
                target_native=True,
            )
            conn.commit()

        with engine.connect() as conn:
            rows = conn.execute(text("SELECT id, priority FROM enum_migration_pytest ORDER BY id")).fetchall()
            assert rows == [(1, "HIGH"), (2, "MEDIUM"), (3, "LOW")]
            col_type = conn.execute(text("SHOW COLUMNS FROM enum_migration_pytest LIKE 'priority'")).fetchone()
            assert col_type[1].startswith("enum(")
            assert "HIGH" in col_type[1]
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS enum_migration_pytest"))
        engine.dispose()


def test_postgres_converts_shared_named_type_to_portable_text_by_default(monkeypatch) -> None:
    """target_native 預設 False（upgrade 方向）：轉換完成後留在 TEXT，不重建具名 TYPE——
    這是「新增 enum 值不需要 ALTER TYPE」得以成立的關鍵行為。也驗證同一個具名 TYPE
    被多個 table/column 共用時，drop 該 TYPE 前所有欄位都已正確 detach。"""
    database_url = _require_postgres()
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS enum_migration_pytest_a"))
            conn.execute(text("DROP TABLE IF EXISTS enum_migration_pytest_b"))
            conn.execute(text("DROP TYPE IF EXISTS priority_pytest"))
            conn.execute(text("CREATE TYPE priority_pytest AS ENUM ('HIGH','MEDIUM','LOW')"))
            conn.execute(
                text("CREATE TABLE enum_migration_pytest_a (id INT PRIMARY KEY, priority priority_pytest NOT NULL)")
            )
            conn.execute(
                text("CREATE TABLE enum_migration_pytest_b (id INT PRIMARY KEY, priority priority_pytest)")
            )
            conn.execute(text("INSERT INTO enum_migration_pytest_a (id, priority) VALUES (1,'HIGH'), (2,'MEDIUM')"))
            conn.execute(text("INSERT INTO enum_migration_pytest_b (id, priority) VALUES (10,'LOW'), (11, NULL)"))

        with engine.connect() as conn:
            _bind_operations(monkeypatch, conn)
            migrate_enum_storage(
                conn,
                mapping={"HIGH": "High", "MEDIUM": "Medium", "LOW": "Low"},
                columns=[
                    EnumColumnRef("enum_migration_pytest_a", "priority", nullable=False),
                    EnumColumnRef("enum_migration_pytest_b", "priority", nullable=True),
                ],
                pg_type_name="priority_pytest",
            )
            conn.commit()

        with engine.connect() as conn:
            rows_a = conn.execute(text("SELECT id, priority FROM enum_migration_pytest_a ORDER BY id")).fetchall()
            rows_b = conn.execute(text("SELECT id, priority FROM enum_migration_pytest_b ORDER BY id")).fetchall()
            assert rows_a == [(1, "High"), (2, "Medium")]
            assert rows_b == [(10, "Low"), (11, None)]

            type_exists = conn.execute(
                text("SELECT 1 FROM pg_type WHERE typname = 'priority_pytest'")
            ).scalar()
            assert type_exists is None

            col_type = conn.execute(
                text(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_name = 'enum_migration_pytest_a' AND column_name = 'priority'"
                )
            ).scalar()
            assert col_type == "text"

            # 新增一個 enum 值（例如新增 'Critical'）不需要任何 DDL 就能寫入/讀出。
            conn.execute(
                text("INSERT INTO enum_migration_pytest_a (id, priority) VALUES (3, 'Critical')")
            )
            conn.commit()
            new_row = conn.execute(
                text("SELECT priority FROM enum_migration_pytest_a WHERE id = 3")
            ).scalar()
            assert new_row == "Critical"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS enum_migration_pytest_a"))
            conn.execute(text("DROP TABLE IF EXISTS enum_migration_pytest_b"))
            conn.execute(text("DROP TYPE IF EXISTS priority_pytest"))
        engine.dispose()


def test_postgres_target_native_recreates_shared_named_type_across_tables(monkeypatch) -> None:
    """target_native=True（downgrade 方向）：轉換完成後重建具名 TYPE 並讓所有欄位改回該
    TYPE，還原成 migration 執行前的具名型別狀態。"""
    database_url = _require_postgres()
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS enum_migration_pytest_a"))
            conn.execute(text("DROP TABLE IF EXISTS enum_migration_pytest_b"))
            conn.execute(text("DROP TYPE IF EXISTS priority_pytest"))
            conn.execute(
                text("CREATE TABLE enum_migration_pytest_a (id INT PRIMARY KEY, priority TEXT NOT NULL)")
            )
            conn.execute(text("CREATE TABLE enum_migration_pytest_b (id INT PRIMARY KEY, priority TEXT)"))
            conn.execute(text("INSERT INTO enum_migration_pytest_a (id, priority) VALUES (1,'High'), (2,'Medium')"))
            conn.execute(text("INSERT INTO enum_migration_pytest_b (id, priority) VALUES (10,'Low'), (11, NULL)"))

        with engine.connect() as conn:
            _bind_operations(monkeypatch, conn)
            migrate_enum_storage(
                conn,
                mapping={"High": "HIGH", "Medium": "MEDIUM", "Low": "LOW"},
                columns=[
                    EnumColumnRef("enum_migration_pytest_a", "priority", nullable=False),
                    EnumColumnRef("enum_migration_pytest_b", "priority", nullable=True),
                ],
                pg_type_name="priority_pytest",
                target_native=True,
            )
            conn.commit()

        with engine.connect() as conn:
            rows_a = conn.execute(text("SELECT id, priority FROM enum_migration_pytest_a ORDER BY id")).fetchall()
            rows_b = conn.execute(text("SELECT id, priority FROM enum_migration_pytest_b ORDER BY id")).fetchall()
            assert rows_a == [(1, "HIGH"), (2, "MEDIUM")]
            assert rows_b == [(10, "LOW"), (11, None)]
            type_labels = conn.execute(
                text(
                    "SELECT enumlabel FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid "
                    "WHERE t.typname = 'priority_pytest' ORDER BY enumsortorder"
                )
            ).fetchall()
            assert {r[0] for r in type_labels} == {"HIGH", "MEDIUM", "LOW"}
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS enum_migration_pytest_a"))
            conn.execute(text("DROP TABLE IF EXISTS enum_migration_pytest_b"))
            conn.execute(text("DROP TYPE IF EXISTS priority_pytest"))
        engine.dispose()
