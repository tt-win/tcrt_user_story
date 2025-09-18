#!/usr/bin/env python3
"""Rebuild test_run_items table to drop legacy Test Case snapshot columns.

This migration keeps only the columns required for execution tracking
and relies on Test Case data (via team_id + test_case_number) for
display fields such as title, priority, and steps.

Usage:
    python scripts/migrate_test_run_items_remove_snapshot.py
"""

from __future__ import annotations

from pathlib import Path
import sys

from sqlalchemy import text

# ensure project root on path when executed directly
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import engine
from app.models.database_models import TestRunItem as TestRunItemDB


SNAPSHOT_COLUMNS = {
    "title",
    "priority",
    "precondition",
    "steps",
    "expected_result",
}


def has_snapshot_columns(connection) -> bool:
    info = connection.execute(text("PRAGMA table_info('test_run_items')")).fetchall()
    column_names = {row[1] for row in info}
    return any(col in column_names for col in SNAPSHOT_COLUMNS)


def drop_existing_indexes(connection, table_name: str) -> None:
    indexes = connection.execute(
        text(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND tbl_name=:name AND name IS NOT NULL"
        ),
        {"name": table_name},
    ).fetchall()
    for (index_name,) in indexes:
        if index_name and not index_name.startswith("sqlite_autoindex"):
            connection.execute(text(f'DROP INDEX IF EXISTS "{index_name}"'))


def copy_data(connection, backup_name: str) -> None:
    desired_columns = [
        'id', 'team_id', 'config_id', 'test_case_number',
        'assignee_id', 'assignee_name', 'assignee_en_name', 'assignee_email',
        'assignee_json', 'test_result', 'executed_at', 'execution_duration',
        'attachments_json', 'execution_results_json', 'user_story_map_json',
        'tcg_json', 'parent_record_json', 'raw_fields_json', 'bug_tickets_json',
        'result_files_uploaded', 'result_files_count', 'upload_history_json',
        'created_at', 'updated_at'
    ]

    available = connection.execute(text(f"PRAGMA table_info('{backup_name}')")).fetchall()
    available_columns = {row[1] for row in available}

    columns_to_copy = [col for col in desired_columns if col in available_columns]
    if not columns_to_copy:
        return

    column_csv = ", ".join(f'"{col}"' for col in columns_to_copy)
    connection.execute(
        text(
            f'INSERT INTO test_run_items ({column_csv}) '
            f'SELECT {column_csv} FROM {backup_name}'
        )
    )


def reset_autoincrement(connection) -> None:
    try:
        connection.execute(
            text(
                "INSERT INTO sqlite_sequence(name, seq) "
                "SELECT 'test_run_items', COALESCE(MAX(id), 0) FROM test_run_items "
                "WHERE NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name='test_run_items')"
            )
        )
        connection.execute(
            text(
                "UPDATE sqlite_sequence SET seq = COALESCE((SELECT MAX(id) FROM test_run_items), 0) "
                "WHERE name='test_run_items'"
            )
        )
    except Exception:
        # sqlite_sequence 不存在或不支援時忽略
        pass


def main() -> None:
    db_path = Path(engine.url.database or "(memory)")
    print("Starting test_run_items snapshot cleanup migration for:", db_path)

    with engine.begin() as connection:
        if not has_snapshot_columns(connection):
            print("test_run_items already without snapshot columns. No action required.")
            return

        backup_name = "test_run_items_backup_snapshot"
        print(f"→ Renaming table to {backup_name}")

        connection.execute(text("PRAGMA foreign_keys=OFF"))
        try:
            connection.execute(text(f"ALTER TABLE test_run_items RENAME TO {backup_name}"))
            drop_existing_indexes(connection, backup_name)

            print("→ Creating new test_run_items table")
            TestRunItemDB.__table__.create(bind=connection)

            print("→ Copying preserved columns")
            copy_data(connection, backup_name)

            print("→ Dropping backup table")
            connection.execute(text(f"DROP TABLE {backup_name}"))

            reset_autoincrement(connection)

            print("Migration completed successfully.")
        finally:
            connection.execute(text("PRAGMA foreign_keys=ON"))


if __name__ == "__main__":
    main()
