from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

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
    def __init__(self, *, dialect_name: str, connection: _FakeConnection):
        quote_char = '"' if dialect_name == "postgresql" else "`"
        self.dialect = SimpleNamespace(
            name=dialect_name,
            identifier_preparer=SimpleNamespace(quote=lambda value: f"{quote_char}{value}{quote_char}"),
        )
        self._connection = connection
        self.disposed = False

    def connect(self):
        return self._connection

    def dispose(self):
        self.disposed = True


def test_create_database_if_missing_for_postgres(monkeypatch) -> None:
    captured: dict[str, object] = {}
    connection = _FakeConnection(exists_value=None)

    def fake_create_engine(url, **kwargs):
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


def test_bootstrap_target_creates_database_before_upgrade(monkeypatch) -> None:
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
    database_init.bootstrap_target("main", logger, no_backup=True)

    assert call_order == [
        "create:postgresql+psycopg://tcrt:tcrt@127.0.0.1:5432/tcrt_main",
        "upgrade",
    ]


def test_verify_mysql_mediumtext_defaults_detects_plain_text_columns(monkeypatch) -> None:
    class _Inspector:
        def get_table_names(self):
            return ["demo", "alembic_version"]

        def get_columns(self, table_name):
            if table_name == "demo":
                return [
                    {"name": "payload_json", "type": sqltypes.Text(), "nullable": True},
                    {"name": "title", "type": sqltypes.String(length=100), "nullable": True},
                ]
            return []

    engine = SimpleNamespace(dialect=SimpleNamespace(name="mysql"))
    monkeypatch.setattr(database_init, "inspect", lambda _engine: _Inspector())

    ok, violations = database_init.verify_mysql_mediumtext_defaults(
        engine,
        database_init.Logger(quiet=True),
        "主資料庫",
    )

    assert ok is False
    assert violations == ["demo.payload_json=TEXT"]


def test_verify_mysql_mediumtext_defaults_accepts_mediumtext_columns(monkeypatch) -> None:
    class _MediumText(sqltypes.Text):
        pass

    _MediumText.__name__ = "MEDIUMTEXT"

    class _Inspector:
        def get_table_names(self):
            return ["demo"]

        def get_columns(self, table_name):
            return [
                {"name": "payload_json", "type": _MediumText(), "nullable": True},
            ]

    engine = SimpleNamespace(dialect=SimpleNamespace(name="mysql"))
    monkeypatch.setattr(database_init, "inspect", lambda _engine: _Inspector())

    ok, violations = database_init.verify_mysql_mediumtext_defaults(
        engine,
        database_init.Logger(quiet=True),
        "主資料庫",
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
