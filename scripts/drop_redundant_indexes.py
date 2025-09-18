#!/usr/bin/env python3
"""Drop redundant or duplicated SQLite indexes introduced in earlier versions."""

from __future__ import annotations

from pathlib import Path
import sys

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text

from app.database import engine

# Index names identified as redundant. The list is idempotent; missing indexes are ignored.
REDUNDANT_INDEXES = [
    # Core entities
    "ix_teams_id",
    "ix_test_run_configs_id",
    "ix_test_cases_id",
    "ix_test_run_items_id",
    "ix_test_run_item_result_history_id",
    # Lark departments/users duplicates
    "ix_lark_departments_department_id",
    "ix_lark_dept_level",
    "ix_lark_dept_parent",
    "ix_lark_users_user_id",
    "idx_lu_enterprise_email",
    "idx_lu_primary_department_id",
    "ix_lark_user_dept",
    "ix_lark_user_email",
    "ix_lark_user_name",
    "ix_lark_user_type",
    # TCG records
    "idx_record_id",
    # Sync history duplicates
    "idx_sh_teamid_starttime",
    "ix_sync_history_type",
    # Test run items legacy indexes
    "idx_tri_configid_testcaseno",
    "idx_tri_result_files_uploaded",
]


def main() -> None:
    db_path = Path(engine.url.database or "(memory)")
    print("Cleaning redundant indexes for SQLite database:", db_path)

    with engine.begin() as connection:
        for index_name in REDUNDANT_INDEXES:
            print(f"→ Dropping index '{index_name}' if present ...", end=" ")
            connection.execute(text(f'DROP INDEX IF EXISTS "{index_name}"'))
            print("done")

    print("Index cleanup completed.")


if __name__ == "__main__":
    main()
