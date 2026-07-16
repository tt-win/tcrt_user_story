from __future__ import annotations

import importlib.util
from collections import defaultdict
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from app.models.database_models import Base


_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
_MIGRATION = "8f1b2c3d4e5a_remove_redundant_single_column_indexes.py"


def _load_migration_module() -> ModuleType:
    path = _VERSIONS_DIR / _MIGRATION
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _index_names(engine, table_name: str) -> set[str]:
    return {index["name"] for index in inspect(engine).get_indexes(table_name)}


def test_models_do_not_define_duplicate_equivalent_indexes() -> None:
    for table_name in (
        "active_sessions",
        "password_reset_tokens",
        "test_case_sets",
        "user_team_permissions",
    ):
        indexes_by_columns: dict[tuple[str, ...], list[str]] = defaultdict(list)
        for index in Base.metadata.tables[table_name].indexes:
            indexes_by_columns[tuple(column.name for column in index.columns)].append(index.name)

        assert {
            columns: names
            for columns, names in indexes_by_columns.items()
            if len(names) > 1
        } == {}


def test_migration_drops_only_redundant_indexes_and_downgrade_restores_them(
    monkeypatch,
) -> None:
    module = _load_migration_module()
    engine = create_engine("sqlite://", future=True)
    custom_indexes = {
        "active_sessions": "ix_sessions_expires",
        "password_reset_tokens": "ix_reset_tokens_expires",
        "test_case_sets": "ix_test_case_sets_team",
    }

    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE active_sessions (expires_at INTEGER)"))
            connection.execute(text("CREATE TABLE password_reset_tokens (expires_at INTEGER)"))
            connection.execute(text("CREATE TABLE test_case_sets (team_id INTEGER)"))
            connection.execute(
                text(
                    "CREATE TABLE user_team_permissions ("
                    "permission INTEGER, team_id INTEGER, user_id INTEGER)"
                )
            )
            for table_name, redundant_index, column_name in module.REDUNDANT_INDEXES:
                connection.execute(
                    text(f"CREATE INDEX {redundant_index} ON {table_name} ({column_name})")
                )
            for table_name, custom_index in custom_indexes.items():
                column_name = next(
                    column
                    for candidate_table, _index, column in module.REDUNDANT_INDEXES
                    if candidate_table == table_name
                )
                connection.execute(
                    text(f"CREATE INDEX {custom_index} ON {table_name} ({column_name})")
                )
            for index_name, column_name in (
                ("ix_user_team_perms_permission", "permission"),
                ("ix_user_team_perms_team", "team_id"),
                ("ix_user_team_perms_user", "user_id"),
            ):
                connection.execute(
                    text(
                        f"CREATE INDEX {index_name} ON user_team_permissions ({column_name})"
                    )
                )

            monkeypatch.setattr(
                module,
                "op",
                Operations(MigrationContext.configure(connection)),
            )
            module.upgrade()

            for table_name, redundant_index, _column_name in module.REDUNDANT_INDEXES:
                assert redundant_index not in _index_names(engine, table_name)
            assert "ix_sessions_expires" in _index_names(engine, "active_sessions")
            assert "ix_reset_tokens_expires" in _index_names(engine, "password_reset_tokens")
            assert "ix_test_case_sets_team" in _index_names(engine, "test_case_sets")
            assert {
                "ix_user_team_perms_permission",
                "ix_user_team_perms_team",
                "ix_user_team_perms_user",
            } <= _index_names(engine, "user_team_permissions")

            module.downgrade()
            for table_name, redundant_index, _column_name in module.REDUNDANT_INDEXES:
                assert redundant_index in _index_names(engine, table_name)
    finally:
        engine.dispose()
