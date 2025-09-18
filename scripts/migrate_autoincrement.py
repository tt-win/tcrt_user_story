#!/usr/bin/env python3
"""Rebuild teams and test_run_configs tables with AUTOINCREMENT primary keys.

This migration targets SQLite databases created before enabling
`sqlite_autoincrement` on the SQLAlchemy models. It preserves existing data while
ensuring future inserts continue numbering instead of reusing deleted IDs.

Usage:
    python scripts/migrate_autoincrement.py

The script will:
1. Verify the target tables still lack AUTOINCREMENT.
2. Rename the existing table to a temporary backup name.
3. Recreate the table structure via SQLAlchemy metadata (which now includes
   AUTOINCREMENT).
4. Copy data back and drop the temporary table.

A backup of the database is recommended before executing this script because it
performs schema changes in place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

# Ensure project root is available on the import path when invoked directly.
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
import sys
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.database import engine
from app.models.database_models import Team, TestRunConfig


def table_has_autoincrement(connection, table_name: str) -> bool:
    """Detect whether the given table already uses AUTOINCREMENT."""
    sql = connection.execute(
        text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": table_name},
    ).scalar()
    if not sql:
        raise RuntimeError(f"Table '{table_name}' not found; aborting migration")
    return "AUTOINCREMENT" in sql.upper()


def rebuild_table_with_autoincrement(connection, table, backup_suffix: str = "_backup_autoinc") -> None:
    """Rename, recreate (with AUTOINCREMENT), and repopulate the specified table."""
    original_name = table.name
    backup_name = f"{original_name}{backup_suffix}"

    print(f"\n→ Processing table '{original_name}' ...")
    connection.execute(text("PRAGMA foreign_keys=OFF"))
    try:
        connection.execute(text(f"ALTER TABLE {original_name} RENAME TO {backup_name}"))

        # Drop named indexes carried over with the backup table to avoid conflicts
        index_rows = connection.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND tbl_name=:name"
            ),
            {"name": backup_name},
        ).fetchall()
        for (index_name,) in index_rows:
            if index_name and not index_name.startswith("sqlite_autoindex"):
                connection.execute(text(f'DROP INDEX IF EXISTS "{index_name}"'))

        # Recreate table using the updated SQLAlchemy metadata (includes AUTOINCREMENT)
        table.create(bind=connection)

        column_names: Iterable[str] = [column.name for column in table.columns]
        columns_list = ", ".join(f'"{name}"' for name in column_names)

        connection.execute(
            text(
                f"INSERT INTO {original_name} ({columns_list}) "
                f"SELECT {columns_list} FROM {backup_name}"
            )
        )

        connection.execute(text(f"DROP TABLE {backup_name}"))

        # Sync sqlite_sequence to the current max id to keep numbering monotonic.
        try:
            connection.execute(
                text(
                    "INSERT INTO sqlite_sequence(name, seq) "
                    "SELECT :name, COALESCE((SELECT MAX(id) FROM {table}), 0) "
                    "WHERE NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name = :name)"
                    .format(table=original_name)
                ),
                {"name": original_name},
            )
            connection.execute(
                text(
                    "UPDATE sqlite_sequence SET seq = "
                    "COALESCE((SELECT MAX(id) FROM {table}), 0) "
                    "WHERE name = :name"
                    .format(table=original_name)
                ),
                {"name": original_name},
            )
        except OperationalError:
            # sqlite_sequence might not exist (e.g., fresh databases). Safe to ignore.
            pass
    finally:
        connection.execute(text("PRAGMA foreign_keys=ON"))
    print(f"   ✅ '{original_name}' rebuilt with AUTOINCREMENT.")


def main() -> None:
    db_path = Path(engine.url.database or "(memory)")
    print("Starting AUTOINCREMENT migration for SQLite database:", db_path)

    tables_to_migrate = [Team.__table__, TestRunConfig.__table__]

    with engine.begin() as connection:
        pending = [
            table for table in tables_to_migrate
            if not table_has_autoincrement(connection, table.name)
        ]

        if not pending:
            print("All target tables already use AUTOINCREMENT. No action needed.")
            return

        for table in pending:
            rebuild_table_with_autoincrement(connection, table)

    print("\nMigration completed successfully.")


if __name__ == "__main__":
    main()
