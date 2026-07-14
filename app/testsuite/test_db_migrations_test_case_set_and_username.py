"""主庫 migration `9cd6393a4da6`(test_case_set_id 回填＋NOT NULL)與
`f5f2d075fd93`(username 大小寫不敏感唯一性)的單元測試（SQLite）與真實
MySQL/PostgreSQL 整合測試。

MySQL/PostgreSQL 測試預設 skip（需要真實可連線的 server），比照
`app/testsuite/test_db_backup_server_engines.py` 的 env-gated 慣例。

migration 檔案透過 `importlib` 直接載入(revision id 開頭為數字,不能用一般 import
語法),並用 `monkeypatch.setattr` 把 `alembic.op` proxy 綁到測試連線 —— 必須用
monkeypatch(而非直接賦值),否則連線關閉後這個模組級的 `op` 參照會卡住,導致同一個
pytest process 內其他測試若真的透過 Alembic 執行 migration 會炸開(這正是
`test_db_migrations_enum_support.py` 先前踩過的雷)。
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

MYSQL_URL_ENV = "TCRT_TEST_MYSQL_URL"
POSTGRES_URL_ENV = "TCRT_TEST_POSTGRES_URL"

_VERSIONS_DIR = Path(__file__).resolve().parent.parent.parent / "alembic" / "versions"


def _load_migration_module(filename: str) -> ModuleType:
    path = _VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bind_operations(monkeypatch, module: ModuleType, connection) -> None:
    ctx = MigrationContext.configure(connection)
    monkeypatch.setattr(module, "op", Operations(ctx))


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


# ---------------------------------------------------------------------------
# 9cd6393a4da6：backfill test_case_set_id and enforce NOT NULL
# ---------------------------------------------------------------------------

_TEST_CASE_SCHEMA_SQLITE = """
CREATE TABLE teams (id INTEGER PRIMARY KEY);
CREATE TABLE test_case_sets (id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL, is_default BOOLEAN NOT NULL);
CREATE TABLE test_case_sections (id INTEGER PRIMARY KEY, test_case_set_id INTEGER NOT NULL);
CREATE TABLE test_cases (
    id INTEGER PRIMARY KEY,
    team_id INTEGER NOT NULL,
    test_case_set_id INTEGER,
    test_case_section_id INTEGER
);
"""


def _make_test_case_engine(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'main.db'}", future=True)
    with engine.begin() as conn:
        for stmt in _TEST_CASE_SCHEMA_SQLITE.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(text(stmt))
    return engine


def test_backfill_test_case_set_id_derives_from_section(monkeypatch, tmp_path: Path) -> None:
    module = _load_migration_module("9cd6393a4da6_backfill_test_case_set_id_and_enforce_.py")
    engine = _make_test_case_engine(tmp_path)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO teams VALUES (1)"))
        conn.execute(text("INSERT INTO test_case_sets VALUES (10, 1, 0)"))
        conn.execute(text("INSERT INTO test_case_sections VALUES (100, 10)"))
        conn.execute(
            text(
                "INSERT INTO test_cases (id, team_id, test_case_set_id, test_case_section_id) "
                "VALUES (1000, 1, NULL, 100)"
            )
        )

    with engine.connect() as conn:
        _bind_operations(monkeypatch, module, conn)
        module.upgrade()
        conn.commit()

    with engine.connect() as conn:
        row = conn.execute(text("SELECT test_case_set_id FROM test_cases WHERE id = 1000")).fetchone()
        assert row.test_case_set_id == 10
        cols = {c["name"]: c for c in __import__("sqlalchemy").inspect(engine).get_columns("test_cases")}
        assert cols["test_case_set_id"]["nullable"] is False


def test_backfill_test_case_set_id_derives_from_team_default(monkeypatch, tmp_path: Path) -> None:
    module = _load_migration_module("9cd6393a4da6_backfill_test_case_set_id_and_enforce_.py")
    engine = _make_test_case_engine(tmp_path)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO teams VALUES (2)"))
        conn.execute(text("INSERT INTO test_case_sets VALUES (20, 2, 1)"))
        conn.execute(
            text(
                "INSERT INTO test_cases (id, team_id, test_case_set_id, test_case_section_id) "
                "VALUES (2000, 2, NULL, NULL)"
            )
        )

    with engine.connect() as conn:
        _bind_operations(monkeypatch, module, conn)
        module.upgrade()
        conn.commit()

    with engine.connect() as conn:
        row = conn.execute(text("SELECT test_case_set_id FROM test_cases WHERE id = 2000")).fetchone()
        assert row.test_case_set_id == 20


def test_backfill_test_case_set_id_raises_when_unresolvable(monkeypatch, tmp_path: Path) -> None:
    module = _load_migration_module("9cd6393a4da6_backfill_test_case_set_id_and_enforce_.py")
    engine = _make_test_case_engine(tmp_path)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO teams VALUES (3)"))
        conn.execute(
            text(
                "INSERT INTO test_cases (id, team_id, test_case_set_id, test_case_section_id) "
                "VALUES (3000, 3, NULL, NULL)"
            )
        )

    with engine.connect() as conn:
        _bind_operations(monkeypatch, module, conn)
        with pytest.raises(RuntimeError, match="test_case_set_id"):
            module.upgrade()


def test_backfill_test_case_set_id_noop_when_already_populated(monkeypatch, tmp_path: Path) -> None:
    module = _load_migration_module("9cd6393a4da6_backfill_test_case_set_id_and_enforce_.py")
    engine = _make_test_case_engine(tmp_path)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO teams VALUES (4)"))
        conn.execute(text("INSERT INTO test_case_sets VALUES (40, 4, 1)"))
        conn.execute(
            text(
                "INSERT INTO test_cases (id, team_id, test_case_set_id, test_case_section_id) "
                "VALUES (4000, 4, 40, NULL)"
            )
        )

    with engine.connect() as conn:
        _bind_operations(monkeypatch, module, conn)
        module.upgrade()
        conn.commit()
        module.downgrade()
        conn.commit()

    with engine.connect() as conn:
        row = conn.execute(text("SELECT test_case_set_id FROM test_cases WHERE id = 4000")).fetchone()
        assert row.test_case_set_id == 40
        cols = {c["name"]: c for c in __import__("sqlalchemy").inspect(engine).get_columns("test_cases")}
        assert cols["test_case_set_id"]["nullable"] is True


def test_mysql_backfill_test_case_set_id(monkeypatch) -> None:
    database_url = _require_mysql()
    module = _load_migration_module("9cd6393a4da6_backfill_test_case_set_id_and_enforce_.py")
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as conn:
            for tbl in ("test_cases", "test_case_sections", "test_case_sets"):
                conn.execute(text(f"DROP TABLE IF EXISTS {tbl}"))
            conn.execute(
                text(
                    "CREATE TABLE test_case_sets (id INT PRIMARY KEY, team_id INT NOT NULL, "
                    "is_default TINYINT(1) NOT NULL)"
                )
            )
            conn.execute(
                text("CREATE TABLE test_case_sections (id INT PRIMARY KEY, test_case_set_id INT NOT NULL)")
            )
            conn.execute(
                text(
                    "CREATE TABLE test_cases (id INT PRIMARY KEY, team_id INT NOT NULL, "
                    "test_case_set_id INT NULL, test_case_section_id INT NULL)"
                )
            )
            conn.execute(text("INSERT INTO test_case_sets VALUES (10, 1, 1)"))
            conn.execute(
                text(
                    "INSERT INTO test_cases (id, team_id, test_case_set_id, test_case_section_id) "
                    "VALUES (1000, 1, NULL, NULL)"
                )
            )

        with engine.connect() as conn:
            _bind_operations(monkeypatch, module, conn)
            module.upgrade()
            conn.commit()

        with engine.connect() as conn:
            row = conn.execute(text("SELECT test_case_set_id FROM test_cases WHERE id = 1000")).fetchone()
            assert row.test_case_set_id == 10
            col = conn.execute(text("SHOW COLUMNS FROM test_cases LIKE 'test_case_set_id'")).fetchone()
            assert col[2] == "NO"  # Null column: "NO" 表示 NOT NULL
    finally:
        with engine.begin() as conn:
            for tbl in ("test_cases", "test_case_sections", "test_case_sets"):
                conn.execute(text(f"DROP TABLE IF EXISTS {tbl}"))
        engine.dispose()


def test_postgres_backfill_test_case_set_id(monkeypatch) -> None:
    database_url = _require_postgres()
    module = _load_migration_module("9cd6393a4da6_backfill_test_case_set_id_and_enforce_.py")
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as conn:
            for tbl in ("test_cases", "test_case_sections", "test_case_sets"):
                conn.execute(text(f"DROP TABLE IF EXISTS {tbl}"))
            conn.execute(
                text(
                    "CREATE TABLE test_case_sets (id INT PRIMARY KEY, team_id INT NOT NULL, "
                    "is_default BOOLEAN NOT NULL)"
                )
            )
            conn.execute(
                text("CREATE TABLE test_case_sections (id INT PRIMARY KEY, test_case_set_id INT NOT NULL)")
            )
            conn.execute(
                text(
                    "CREATE TABLE test_cases (id INT PRIMARY KEY, team_id INT NOT NULL, "
                    "test_case_set_id INT NULL, test_case_section_id INT NULL)"
                )
            )
            conn.execute(text("INSERT INTO test_case_sets VALUES (10, 1, true)"))
            conn.execute(
                text(
                    "INSERT INTO test_cases (id, team_id, test_case_set_id, test_case_section_id) "
                    "VALUES (1000, 1, NULL, NULL)"
                )
            )

        with engine.connect() as conn:
            _bind_operations(monkeypatch, module, conn)
            module.upgrade()
            conn.commit()

        with engine.connect() as conn:
            row = conn.execute(text("SELECT test_case_set_id FROM test_cases WHERE id = 1000")).fetchone()
            assert row.test_case_set_id == 10
            nullable = conn.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'test_cases' AND column_name = 'test_case_set_id'"
                )
            ).scalar()
            assert nullable == "NO"
    finally:
        with engine.begin() as conn:
            for tbl in ("test_cases", "test_case_sections", "test_case_sets"):
                conn.execute(text(f"DROP TABLE IF EXISTS {tbl}"))
        engine.dispose()


# ---------------------------------------------------------------------------
# f5f2d075fd93：case-insensitive username uniqueness
# ---------------------------------------------------------------------------


def _make_users_engine_sqlite(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'users.db'}", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(50) NOT NULL)"))
        conn.execute(text("CREATE UNIQUE INDEX ix_users_username ON users (username)"))
    return engine


def test_username_migration_creates_case_insensitive_unique_index(monkeypatch, tmp_path: Path) -> None:
    module = _load_migration_module("f5f2d075fd93_enforce_case_insensitive_username_.py")
    engine = _make_users_engine_sqlite(tmp_path)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id, username) VALUES (1, 'nikki'), (2, 'bob')"))

    with engine.connect() as conn:
        _bind_operations(monkeypatch, module, conn)
        module.upgrade()
        conn.commit()

    with engine.connect() as conn:
        with pytest.raises(Exception, match="(?i)unique"):
            conn.execute(text("INSERT INTO users (id, username) VALUES (3, 'Nikki')"))
            conn.commit()


def test_username_migration_downgrade_restores_case_sensitive_index(monkeypatch, tmp_path: Path) -> None:
    module = _load_migration_module("f5f2d075fd93_enforce_case_insensitive_username_.py")
    engine = _make_users_engine_sqlite(tmp_path)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id, username) VALUES (1, 'nikki'), (2, 'bob')"))

    with engine.connect() as conn:
        _bind_operations(monkeypatch, module, conn)
        module.upgrade()
        conn.commit()
        module.downgrade()
        conn.commit()

    with engine.begin() as conn:
        # 還原成大小寫敏感唯一性後，'Nikki' 與既有 'nikki' 不衝突。
        conn.execute(text("INSERT INTO users (id, username) VALUES (3, 'Nikki')"))
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
        assert count == 3


def test_username_migration_raises_on_existing_case_variant_duplicates(monkeypatch, tmp_path: Path) -> None:
    module = _load_migration_module("f5f2d075fd93_enforce_case_insensitive_username_.py")
    engine = create_engine(f"sqlite:///{tmp_path / 'users_dup.db'}", future=True)
    with engine.begin() as conn:
        # 大小寫敏感唯一性下,'nikki' 與 'Nikki' 可以同時存在(舊 schema 允許的合法狀態)。
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(50) NOT NULL)"))
        conn.execute(text("CREATE UNIQUE INDEX ix_users_username ON users (username)"))
        conn.execute(text("INSERT INTO users (id, username) VALUES (1, 'nikki'), (2, 'Nikki')"))

    with engine.connect() as conn:
        _bind_operations(monkeypatch, module, conn)
        with pytest.raises(RuntimeError, match="nikki"):
            module.upgrade()


def test_mysql_username_case_insensitive_unique_index(monkeypatch) -> None:
    # migration 寫死操作 `users` 表名。TCRT_TEST_MYSQL_URL 依慣例指向 disposable 的
    # tcrt_main（比照 test_db_backup_server_engines.py / test_db_migrations_enum_support.py），
    # 這裡直接建立／清除同名表即可，不需要另外建立獨立 schema。
    database_url = _require_mysql()
    module = _load_migration_module("f5f2d075fd93_enforce_case_insensitive_username_.py")
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS users"))
            conn.execute(
                text(
                    "CREATE TABLE users (id INT PRIMARY KEY, username VARCHAR(50) NOT NULL, "
                    "UNIQUE KEY ix_users_username (username))"
                )
            )
            conn.execute(text("INSERT INTO users VALUES (1, 'nikki'), (2, 'bob')"))

        with engine.connect() as conn:
            _bind_operations(monkeypatch, module, conn)
            module.upgrade()
            conn.commit()

        with engine.connect() as conn:
            with pytest.raises(Exception, match="(?i)duplicate"):
                conn.execute(text("INSERT INTO users (id, username) VALUES (3, 'Nikki')"))
                conn.commit()
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS users"))
        engine.dispose()


def test_postgres_username_case_insensitive_unique_index(monkeypatch) -> None:
    database_url = _require_postgres()
    module = _load_migration_module("f5f2d075fd93_enforce_case_insensitive_username_.py")
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS users"))
            # 用 CREATE UNIQUE INDEX（而非 table 級 CONSTRAINT ... UNIQUE）建立舊索引，
            # 對齊 7a26d2522198_initial_schema.py 實際建立 ix_users_username 的方式：
            # PostgreSQL 的 constraint-backed unique index 不能單靠 DROP INDEX 移除
            # （需要 DROP CONSTRAINT），而正式 migration 歷史上从未用 constraint 建過這個索引。
            conn.execute(text("CREATE TABLE users (id INT PRIMARY KEY, username VARCHAR(50) NOT NULL)"))
            conn.execute(text("CREATE UNIQUE INDEX ix_users_username ON users (username)"))
            conn.execute(text("INSERT INTO users VALUES (1, 'nikki'), (2, 'bob')"))

        with engine.connect() as conn:
            _bind_operations(monkeypatch, module, conn)
            module.upgrade()
            conn.commit()

        with engine.connect() as conn:
            with pytest.raises(Exception, match="(?i)duplicate"):
                conn.execute(text("INSERT INTO users (id, username) VALUES (3, 'Nikki')"))
                conn.commit()
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS users"))
        engine.dispose()
