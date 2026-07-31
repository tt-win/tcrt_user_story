"""Regression coverage for immutable assistant pending-action team targets."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "f0c1e2d3a4b5_move_assistant_target_to_pending.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("assistant_target_migration", _MIGRATION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bind_operations(module: ModuleType, connection) -> None:
    module.op = Operations(MigrationContext.configure(connection))


def _legacy_database(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-assistant-target.db'}", future=True)
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.execute(text("CREATE TABLE teams (id INTEGER PRIMARY KEY, name VARCHAR(100))"))
        connection.execute(text("INSERT INTO teams (id, name) VALUES (1, 'ART'), (2, 'CID')"))
        connection.execute(
            text(
                "CREATE TABLE assistant_turns ("
                "id INTEGER PRIMARY KEY, context_team_id INTEGER, "
                "CONSTRAINT fk_assistant_turns_context_team_id "
                "FOREIGN KEY(context_team_id) REFERENCES teams(id) ON DELETE SET NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX ix_assistant_turns_context_team_id "
                "ON assistant_turns(context_team_id)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE assistant_pending_actions ("
                "id INTEGER PRIMARY KEY, turn_id INTEGER NOT NULL, status VARCHAR(32) NOT NULL, "
                "confirmation_summary_json TEXT NOT NULL, execution_payload_json TEXT, "
                "execution_payload_encrypted BOOLEAN NOT NULL DEFAULT 0, resolved_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE assistant_tool_executions ("
                "id INTEGER PRIMARY KEY, team_id INTEGER)"
            )
        )
        connection.execute(
            text("INSERT INTO assistant_turns (id, context_team_id) VALUES (10, 1), (20, 2), (30, 1)")
        )
        connection.execute(
            text(
                "INSERT INTO assistant_pending_actions "
                "(id, turn_id, status, confirmation_summary_json, execution_payload_json, "
                "execution_payload_encrypted) VALUES "
                "(1, 10, 'pending', :valid_summary, :payload, 0), "
                "(2, 20, 'pending', '{}', :payload, 0), "
                "(3, 30, 'pending', :encrypted_summary, :encrypted_payload, 1)"
            ),
            {
                "valid_summary": json.dumps({"team_id": 1, "team_name": "ART"}),
                "encrypted_summary": json.dumps({"team_id": 1, "team_name": "ART"}),
                "payload": json.dumps({"path_params": {}, "body_params": {"name": "x"}}),
                "encrypted_payload": json.dumps({"v": 1, "ciphertext": "not-migratable"}),
            },
        )
    return engine


def test_sqlite_upgrade_backfills_safe_target_and_expires_unrecoverable_pending(
    tmp_path: Path,
) -> None:
    module = _load_migration()
    engine = _legacy_database(tmp_path)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            _bind_operations(module, connection)
            module.upgrade()
            connection.commit()

        with engine.connect() as connection:
            columns = {
                column["name"]
                for column in inspect(connection).get_columns("assistant_pending_actions")
            }
            assert {
                "target_team_id",
                "target_team_name_snapshot",
                "target_selector_json",
            } <= columns
            assert "context_team_id" not in {
                column["name"] for column in inspect(connection).get_columns("assistant_turns")
            }
            assert "target_selector_json" in {
                column["name"]
                for column in inspect(connection).get_columns("assistant_tool_executions")
            }

            rows = connection.execute(
                text(
                    "SELECT id, status, target_team_id, target_team_name_snapshot, "
                    "target_selector_json, execution_payload_json "
                    "FROM assistant_pending_actions ORDER BY id"
                )
            ).mappings().all()
            assert rows[0]["status"] == "pending"
            assert rows[0]["target_team_id"] == 1
            assert rows[0]["target_team_name_snapshot"] == "ART"
            assert rows[0]["target_selector_json"] is None
            assert json.loads(rows[0]["execution_payload_json"])["target_team_id"] == 1
            assert rows[1]["status"] == "expired"
            assert rows[1]["execution_payload_json"] is None
            assert rows[2]["status"] == "expired"
            assert rows[2]["execution_payload_json"] is None

            foreign_keys = inspect(connection).get_foreign_keys("assistant_pending_actions")
            assert not any(
                foreign_key["constrained_columns"] == ["target_team_id"]
                for foreign_key in foreign_keys
            )

            _bind_operations(module, connection)
            module.downgrade()
            connection.commit()

        with engine.connect() as connection:
            pending_columns = {
                column["name"]
                for column in inspect(connection).get_columns("assistant_pending_actions")
            }
            assert "target_team_id" not in pending_columns
            assert "context_team_id" in {
                column["name"] for column in inspect(connection).get_columns("assistant_turns")
            }
            assert connection.execute(
                text("SELECT context_team_id FROM assistant_turns WHERE id = 10")
            ).scalar_one() == 1
    finally:
        engine.dispose()
