from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.sql import sqltypes

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import database_init
from app import db_migrations


def _load_main_migration_module(file_name: str, module_name: str):
    migration_path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / file_name
    spec = importlib.util.spec_from_file_location(module_name, migration_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class _FakeResult:
    def __init__(self, scalar_value):
        self._scalar_value = scalar_value

    def scalar(self):
        return self._scalar_value


class _FakeConnection:
    def __init__(self, *, exists_value):
        self.exists_value = exists_value
        self.statements: list[tuple[str, dict[str, str] | None]] = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append((sql, params))
        if "SELECT 1 FROM pg_database" in sql:
            return _FakeResult(self.exists_value)
        if "SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA" in sql:
            return _FakeResult(self.exists_value)
        return _FakeResult(None)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeEngine:
    def __init__(self, *, dialect_name: str, connection: _FakeConnection, connect_error=None):
        quote_char = '"' if dialect_name == "postgresql" else "`"
        self.dialect = SimpleNamespace(
            name=dialect_name,
            identifier_preparer=SimpleNamespace(quote=lambda value: f"{quote_char}{value}{quote_char}"),
        )
        self._connection = connection
        self._connect_error = connect_error
        self.disposed = False

    def connect(self):
        if self._connect_error:
            raise self._connect_error
        return self._connection

    def dispose(self):
        self.disposed = True


def test_create_database_if_missing_uses_existing_mysql_target_without_admin_access(monkeypatch) -> None:
    captured: list[tuple[object, dict[str, object]]] = []
    target_connection = _FakeConnection(exists_value=None)
    target_engine = _FakeEngine(dialect_name="mysql", connection=target_connection)

    def fake_create_engine(url, **kwargs):
        captured.append((url, kwargs))
        return target_engine

    monkeypatch.setattr(db_migrations, "create_engine", fake_create_engine)

    created = db_migrations.create_database_if_missing(
        "mysql+asyncmy://tcrt:tcrt@127.0.0.1:3306/tcrt_main"
    )

    assert created is False
    assert len(captured) == 1
    assert captured[0][0].render_as_string(hide_password=False) == (
        "mysql+pymysql://tcrt:tcrt@127.0.0.1:3306/tcrt_main"
    )
    assert target_engine.disposed is True


def test_create_database_if_missing_for_postgres(monkeypatch) -> None:
    captured: dict[str, object] = {}
    connection = _FakeConnection(exists_value=None)

    def fake_create_engine(url, **kwargs):
        if url.database == "tcrt_main":
            return _FakeEngine(
                dialect_name="postgresql",
                connection=connection,
                connect_error=RuntimeError('database "tcrt_main" does not exist'),
            )
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _FakeEngine(dialect_name="postgresql", connection=connection)

    monkeypatch.setattr(db_migrations, "create_engine", fake_create_engine)

    created = db_migrations.create_database_if_missing("postgresql+asyncpg://tcrt:tcrt@127.0.0.1:5432/tcrt_main")

    assert created is True
    assert captured["url"].render_as_string(hide_password=False) == (
        "postgresql+psycopg://tcrt:tcrt@127.0.0.1:5432/postgres"
    )
    assert captured["kwargs"] == {
        "future": True,
        "isolation_level": "AUTOCOMMIT",
        "pool_pre_ping": True,
    }
    assert connection.statements == [
        (
            "SELECT 1 FROM pg_database WHERE datname = :database_name",
            {"database_name": "tcrt_main"},
        ),
        ('CREATE DATABASE "tcrt_main"', None),
    ]


def test_create_database_if_missing_for_mysql(monkeypatch) -> None:
    captured: dict[str, object] = {}
    connection = _FakeConnection(exists_value=None)

    def fake_create_engine(url, **kwargs):
        if url.database == "tcrt_main":
            return _FakeEngine(
                dialect_name="mysql",
                connection=connection,
                connect_error=RuntimeError("Unknown database 'tcrt_main'"),
            )
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _FakeEngine(dialect_name="mysql", connection=connection)

    monkeypatch.setattr(db_migrations, "create_engine", fake_create_engine)

    created = db_migrations.create_database_if_missing("mysql+asyncmy://tcrt:tcrt@127.0.0.1:3306/tcrt_main")

    assert created is True
    assert captured["url"].render_as_string(hide_password=False) == ("mysql+pymysql://tcrt:tcrt@127.0.0.1:3306/mysql")
    assert connection.statements == [
        (
            "SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME = :database_name",
            {"database_name": "tcrt_main"},
        ),
        ("CREATE DATABASE `tcrt_main`", None),
    ]


def test_create_database_if_missing_does_not_fallback_on_auth_error(monkeypatch) -> None:
    target_engine = _FakeEngine(
        dialect_name="mysql",
        connection=_FakeConnection(exists_value=None),
        connect_error=RuntimeError("Access denied for user"),
    )
    monkeypatch.setattr(db_migrations, "create_engine", lambda *_args, **_kwargs: target_engine)

    with pytest.raises(RuntimeError, match="Access denied"):
        db_migrations.create_database_if_missing(
            "mysql+asyncmy://tcrt:tcrt@127.0.0.1:3306/tcrt_main"
        )

    assert target_engine.disposed is True


def test_collect_target_preflight_marks_missing_database_as_ready(monkeypatch) -> None:
    monkeypatch.setattr(db_migrations, "_driver_statuses_for_url", lambda _url: [])
    monkeypatch.setattr(db_migrations, "_get_head_revision", lambda _cfg: "head")

    def fake_get_database_state(_url: str):
        raise RuntimeError('database "tcrt_main" does not exist')

    monkeypatch.setattr(db_migrations, "_get_database_state", fake_get_database_state)

    summary = db_migrations.collect_target_preflight(
        "main",
        database_url="postgresql+asyncpg://tcrt:tcrt@127.0.0.1:5432/tcrt_main",
    )

    assert summary["database_state"] == "missing"
    assert summary["status"] == "database_missing"
    assert summary["ready"] is True
    assert "bootstrap 會先建立缺少的 database" in summary["remediation"][0]


def _fresh_pending_status(target: str, database_url=None):
    return db_migrations.PendingStatus(target=target, current=None, head="head", is_pending=True, is_fresh=True)


def test_bootstrap_target_creates_database_before_upgrade(monkeypatch, tmp_path) -> None:
    call_order: list[str] = []

    class _BootstrapEngine:
        def __init__(self):
            self.dialect = SimpleNamespace(name="postgresql")
            self.url = make_url("postgresql+psycopg://tcrt:tcrt@127.0.0.1:5432/tcrt_main")

        def dispose(self):
            return None

    monkeypatch.setattr(database_init, "get_sync_engine_for_target", lambda _target: _BootstrapEngine())
    monkeypatch.setattr(
        database_init,
        "create_database_if_missing",
        lambda url: call_order.append(f"create:{url.render_as_string(hide_password=False)}") or True,
    )
    monkeypatch.setattr(database_init, "get_pending_status", _fresh_pending_status)
    monkeypatch.setitem(
        database_init.TARGET_UPGRADERS,
        "main",
        lambda: call_order.append("upgrade"),
    )
    monkeypatch.setattr(
        database_init,
        "verify_required_tables",
        lambda *_args, **_kwargs: (True, []),
    )
    monkeypatch.setattr(
        database_init,
        "verify_large_text_columns",
        lambda *_args, **_kwargs: (True, []),
    )
    monkeypatch.setattr(
        database_init,
        "collect_target_verification_summary",
        lambda *_args, **_kwargs: {
            "label": "主資料庫",
            "target": "main",
            "ready": True,
            "database_state": "managed",
            "head_revision": "head",
            "current_revision": "head",
            "total_tables": 1,
            "required_tables": {"users": True},
            "critical_row_counts": {"users": 0},
        },
    )
    monkeypatch.setattr(database_init, "print_verification_summary", lambda _summary: None)

    logger = database_init.Logger(quiet=True)
    policies = database_init.BootstrapPolicies(
        backup_dir=tmp_path / "backups",
        backup_mode="off",
        backup_retention=5,
        on_failure="abort",
        max_upgrade_attempts=3,
    )
    database_init.bootstrap_target("main", logger, policies)

    assert call_order == [
        "create:postgresql+psycopg://tcrt:tcrt@127.0.0.1:5432/tcrt_main",
        "upgrade",
    ]


def test_bootstrap_target_auto_upgrades_legacy_unmanaged_db(monkeypatch, tmp_path) -> None:
    call_order: list[str] = []

    class _BootstrapEngine:
        def __init__(self):
            self.dialect = SimpleNamespace(name="postgresql")
            self.url = make_url("postgresql+psycopg://tcrt:tcrt@127.0.0.1:5432/tcrt_main")

        def dispose(self):
            return None

    monkeypatch.setattr(database_init, "get_sync_engine_for_target", lambda _target: _BootstrapEngine())
    monkeypatch.setattr(database_init, "create_database_if_missing", lambda _url: False)
    monkeypatch.setattr(
        database_init,
        "get_pending_status",
        lambda target, database_url=None: db_migrations.PendingStatus(
            target=target, current=None, head="head", is_pending=True, is_fresh=False
        ),
    )

    def _raise_adoption_required():
        call_order.append("upgrade")
        raise database_init.LegacyDatabaseAdoptionRequiredError("legacy unmanaged")

    monkeypatch.setitem(database_init.TARGET_UPGRADERS, "main", _raise_adoption_required)
    monkeypatch.setitem(
        database_init.TARGET_LEGACY_UPGRADERS,
        "main",
        lambda: call_order.append("legacy_upgrade") or ("7a26d2522198", "head"),
    )
    monkeypatch.setattr(
        database_init,
        "verify_required_tables",
        lambda *_args, **_kwargs: (True, []),
    )
    monkeypatch.setattr(
        database_init,
        "verify_large_text_columns",
        lambda *_args, **_kwargs: (True, []),
    )
    monkeypatch.setattr(
        database_init,
        "collect_target_verification_summary",
        lambda *_args, **_kwargs: {
            "label": "主資料庫",
            "target": "main",
            "ready": True,
            "database_state": "managed",
            "head_revision": "head",
            "current_revision": "head",
            "total_tables": 1,
            "required_tables": {"users": True},
            "critical_row_counts": {"users": 0},
        },
    )
    monkeypatch.setattr(database_init, "print_verification_summary", lambda _summary: None)

    logger = database_init.Logger(quiet=True)
    policies = database_init.BootstrapPolicies(
        backup_dir=tmp_path / "backups",
        backup_mode="off",
        backup_retention=5,
        on_failure="abort",
        max_upgrade_attempts=3,
    )
    database_init.bootstrap_target("main", logger, policies)

    assert call_order == ["upgrade", "legacy_upgrade"]


def test_verify_large_text_columns_is_noop_for_non_mysql_engine() -> None:
    engine = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    ok, violations = database_init.verify_large_text_columns(
        engine,
        "usm",
        database_init.Logger(quiet=True),
        "USM 資料庫",
    )

    assert ok is True
    assert violations == []


def test_verify_large_text_columns_detects_plain_text_column(monkeypatch) -> None:
    class _Inspector:
        def get_table_names(self):
            return ["user_story_maps", "user_story_map_nodes"]

        def get_columns(self, table_name):
            if table_name == "user_story_map_nodes":
                return [
                    {"name": "description", "type": sqltypes.Text(), "nullable": True},
                ]
            return []

    engine = SimpleNamespace(dialect=SimpleNamespace(name="mysql"))
    monkeypatch.setattr(database_init, "inspect", lambda _engine: _Inspector())

    ok, violations = database_init.verify_large_text_columns(
        engine,
        "usm",
        database_init.Logger(quiet=True),
        "USM 資料庫",
    )

    assert ok is False
    assert violations == ["user_story_map_nodes.description=TEXT"]


def test_verify_large_text_columns_accepts_mediumtext_columns(monkeypatch) -> None:
    class _MediumText(sqltypes.Text):
        pass

    _MediumText.__name__ = "MEDIUMTEXT"

    class _Inspector:
        def get_table_names(self):
            return ["user_story_maps", "user_story_map_nodes"]

        def get_columns(self, table_name):
            if table_name in {"user_story_maps", "user_story_map_nodes"}:
                return [
                    {"name": "description", "type": _MediumText(), "nullable": True},
                ]
            return []

    engine = SimpleNamespace(dialect=SimpleNamespace(name="mysql"))
    monkeypatch.setattr(database_init, "inspect", lambda _engine: _Inspector())

    ok, violations = database_init.verify_large_text_columns(
        engine,
        "usm",
        database_init.Logger(quiet=True),
        "USM 資料庫",
    )

    assert ok is True
    assert violations == []


def test_qa_ai_helper_v3_text_followup_migration_alters_all_mysql_columns(monkeypatch) -> None:
    module = _load_main_migration_module(
        "b2a4f6c8d0e1_widen_qa_ai_helper_v3_text_columns_to_mediumtext.py",
        "alembic_b2a4f6c8d0e1",
    )
    alter_calls: list[tuple[str, str, dict[str, object]]] = []

    monkeypatch.setattr(
        module,
        "op",
        SimpleNamespace(
            get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="mysql")),
            alter_column=lambda table_name, column_name, **kwargs: alter_calls.append(
                (table_name, column_name, kwargs)
            ),
        ),
    )

    module.upgrade()

    assert [
        (table_name, column_name, kwargs["existing_nullable"]) for table_name, column_name, kwargs in alter_calls
    ] == list(module.QA_AI_HELPER_V3_TEXT_COLUMNS)
    assert all(isinstance(kwargs["existing_type"], sqltypes.Text) for _, _, kwargs in alter_calls)
    assert all(kwargs["type_"].__class__.__name__.upper() == "MEDIUMTEXT" for _, _, kwargs in alter_calls)


def test_qa_ai_helper_v3_text_followup_migration_skips_non_mysql(monkeypatch) -> None:
    module = _load_main_migration_module(
        "b2a4f6c8d0e1_widen_qa_ai_helper_v3_text_columns_to_mediumtext.py",
        "alembic_b2a4f6c8d0e1_non_mysql",
    )
    alter_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    monkeypatch.setattr(
        module,
        "op",
        SimpleNamespace(
            get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="sqlite")),
            alter_column=lambda *args, **kwargs: alter_calls.append((args, kwargs)),
        ),
    )

    module.upgrade()
    module.downgrade()

    assert alter_calls == []


def _load_audit_migration_module(file_name: str, module_name: str):
    migration_path = Path(__file__).resolve().parents[2] / "alembic_audit" / "versions" / file_name
    spec = importlib.util.spec_from_file_location(module_name, migration_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_knowledge_query_logs_widen_migration_alters_all_mysql_columns(monkeypatch) -> None:
    module = _load_audit_migration_module(
        "b1c2d3e4f506_widen_knowledge_query_logs.py",
        "alembic_audit_b1c2d3e4f506",
    )
    upgrade_calls: list[tuple[str, str, dict[str, object]]] = []
    downgrade_calls: list[tuple[str, str, dict[str, object]]] = []
    state = {"phase": "upgrade"}

    def _fake_alter(table_name, column_name, **kwargs):
        target = upgrade_calls if state["phase"] == "upgrade" else downgrade_calls
        target.append((table_name, column_name, kwargs))

    monkeypatch.setattr(
        module,
        "op",
        SimpleNamespace(
            get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="mysql")),
            alter_column=_fake_alter,
        ),
    )

    module.upgrade()

    assert [
        (table_name, column_name, kwargs["existing_nullable"])
        for table_name, column_name, kwargs in upgrade_calls
    ] == list(module._COLUMNS)
    assert all(
        isinstance(kwargs["existing_type"], sqltypes.Text) for _, _, kwargs in upgrade_calls
    )
    assert all(
        kwargs["type_"].__class__.__name__.upper() == "MEDIUMTEXT"
        for _, _, kwargs in upgrade_calls
    )

    state["phase"] = "downgrade"
    module.downgrade()

    assert [
        (table_name, column_name, kwargs["existing_nullable"])
        for table_name, column_name, kwargs in downgrade_calls
    ] == list(module._COLUMNS)
    # 還原方向：existing_type 必須是 MEDIUMTEXT（因為剛被升級），目標回到 TEXT
    assert all(
        kwargs["existing_type"].__class__.__name__.upper() == "MEDIUMTEXT"
        for _, _, kwargs in downgrade_calls
    )
    assert all(
        kwargs["type_"].__class__.__name__.upper() == "TEXT"
        for _, _, kwargs in downgrade_calls
    )


def test_knowledge_query_logs_widen_migration_skips_non_mysql(monkeypatch) -> None:
    module = _load_audit_migration_module(
        "b1c2d3e4f506_widen_knowledge_query_logs.py",
        "alembic_audit_b1c2d3e4f506_non_mysql",
    )
    alter_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    monkeypatch.setattr(
        module,
        "op",
        SimpleNamespace(
            get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="sqlite")),
            alter_column=lambda *args, **kwargs: alter_calls.append((args, kwargs)),
        ),
    )

    module.upgrade()
    module.downgrade()

    assert alter_calls == []


def test_knowledge_query_logs_migration_declares_mediumtext_on_mysql() -> None:
    """新建立的 `20260724_knowledge_query_logs` 應在 MySQL 上直接建出 MEDIUMTEXT，
    避免新部署仍要先建 TEXT、再被 catch-up migration 升級的雙重成本。"""
    from sqlalchemy.dialects import mysql as mysql_dialect
    from sqlalchemy.schema import CreateTable

    from app.audit.database import KnowledgeQueryLogTable

    ddl = str(CreateTable(KnowledgeQueryLogTable.__table__).compile(dialect=mysql_dialect.dialect()))
    for column_name in (
        "query_text",
        "allowed_team_ids",
        "process",
        "results_summary",
        "error",
    ):
        assert f"{column_name} MEDIUMTEXT" in ddl, ddl
