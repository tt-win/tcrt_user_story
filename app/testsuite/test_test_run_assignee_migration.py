"""Regression coverage for the local Test Run assignee migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "c4d5e6f7a8b9_add_test_run_item_assignee_user.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("test_run_assignee_migration", _MIGRATION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bind_operations(monkeypatch, module: ModuleType, connection) -> None:
    monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))


def _make_legacy_sqlite_database(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-assignee.db'}", future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE users ("
                "id INTEGER PRIMARY KEY, lark_user_id VARCHAR(64), email VARCHAR(255), "
                "is_active BOOLEAN NOT NULL, role VARCHAR(32) NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE test_run_items ("
                "id INTEGER PRIMARY KEY, assignee_id VARCHAR(64), assignee_name VARCHAR(255), "
                "assignee_email VARCHAR(255), assignee_json TEXT, updated_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE test_run_item_result_history ("
                "id INTEGER PRIMARY KEY, changed_by_id VARCHAR(64), changed_at DATETIME)"
            )
        )
    return engine


def test_sqlite_upgrade_backfills_only_safe_exact_identity_and_downgrade_preserves_snapshot(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_migration()
    engine = _make_legacy_sqlite_database(tmp_path)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, lark_user_id, email, is_active, role) VALUES "
                    "(1, ' ou-unique ', 'unique@example.com', 1, 'user'), "
                    "(2, 'ou-conflict', 'other@example.com', 1, 'user'), "
                    "(3, 'ou-inactive', 'inactive@example.com', 0, 'user'), "
                    "(4, 'ou-viewer', 'viewer@example.com', 1, 'viewer'), "
                    "(5, 'ou-duplicate-a', 'duplicate@example.com', 1, 'user'), "
                    "(6, 'ou-duplicate-b', ' DUPLICATE@example.com ', 1, 'admin')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO test_run_items "
                    "(id, assignee_id, assignee_name, assignee_email, assignee_json, updated_at) VALUES "
                    "(10, ' ou-unique ', 'Unique', NULL, '{\"id\":\" ou-unique \"}', CURRENT_TIMESTAMP), "
                    "(11, NULL, 'Email only', ' UNIQUE@EXAMPLE.COM ', '{\"email\":\" UNIQUE@EXAMPLE.COM \"}', CURRENT_TIMESTAMP), "
                    "(12, 'ou-unique', 'Conflict', 'other@example.com', NULL, CURRENT_TIMESTAMP), "
                    "(13, 'ou-inactive', 'Inactive', NULL, NULL, CURRENT_TIMESTAMP), "
                    "(14, 'ou-viewer', 'Viewer', NULL, NULL, CURRENT_TIMESTAMP), "
                    "(15, NULL, 'Duplicate', 'duplicate@example.com', NULL, CURRENT_TIMESTAMP), "
                    "(16, NULL, 'Name only', NULL, NULL, CURRENT_TIMESTAMP)"
                )
            )

        with engine.connect() as connection:
            _bind_operations(monkeypatch, module, connection)
            module.upgrade()
            connection.commit()

        with engine.connect() as connection:
            assignee_ids = dict(
                connection.execute(
                    text("SELECT id, assignee_user_id FROM test_run_items ORDER BY id")
                ).all()
            )
            assert assignee_ids == {
                10: 1,
                11: 1,
                12: None,
                13: None,
                14: None,
                15: None,
                16: None,
            }
            indexes = {index["name"] for index in inspect(connection).get_indexes("test_run_items")}
            history_indexes = {
                index["name"]
                for index in inspect(connection).get_indexes("test_run_item_result_history")
            }
            assert "ix_test_run_items_assignee_user_updated" in indexes
            assert "ix_result_history_changed_by_time" in history_indexes
            foreign_keys = inspect(connection).get_foreign_keys("test_run_items")
            assert any(
                foreign_key["constrained_columns"] == ["assignee_user_id"]
                and foreign_key["options"].get("ondelete") == "SET NULL"
                for foreign_key in foreign_keys
            )

            _bind_operations(monkeypatch, module, connection)
            module.downgrade()
            connection.commit()

        with engine.connect() as connection:
            columns = {column["name"] for column in inspect(connection).get_columns("test_run_items")}
            assert "assignee_user_id" not in columns
            snapshot = connection.execute(
                text("SELECT assignee_id, assignee_name, assignee_email, assignee_json FROM test_run_items WHERE id = 10")
            ).one()
            assert snapshot == (
                " ou-unique ",
                "Unique",
                None,
                '{"id":" ou-unique "}',
            )
    finally:
        engine.dispose()


class _EmptyMappingsResult:
    def mappings(self):
        return []


class _PortableOperationRecorder:
    def __init__(self, dialect_name: str) -> None:
        self.bind = _PortableBind(dialect_name)
        self.calls: list[tuple[str, tuple, dict]] = []

    def get_bind(self):
        return self.bind

    def execute(self, _statement):
        return _EmptyMappingsResult()

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return record


class _PortableBind:
    def __init__(self, dialect_name: str) -> None:
        self.dialect = SimpleNamespace(name=dialect_name)

    def execute(self, _statement):
        return _EmptyMappingsResult()


@pytest.mark.parametrize("dialect_name", ["mysql", "postgresql"])
def test_non_sqlite_branches_use_portable_fk_and_index_operations(monkeypatch, dialect_name: str) -> None:
    module = _load_migration()
    recorder = _PortableOperationRecorder(dialect_name)
    monkeypatch.setattr(module, "op", recorder)

    module.upgrade()
    module.downgrade()

    call_names = [name for name, _, _ in recorder.calls]
    assert "add_column" in call_names
    assert "create_foreign_key" in call_names
    assert call_names.count("create_index") == 2
    assert "drop_constraint" in call_names
    assert call_names.count("drop_index") == 2
