#!/usr/bin/env python3
"""Cleanup historical manual automation links.

Usage:
  python scripts/cleanup_manual_automation_links.py [--team-id TEAM_ID]
  python scripts/cleanup_manual_automation_links.py --confirm [--team-id TEAM_ID]

Before running with --confirm, back up the database first:
  cp test_case_repo.db test_case_repo.db.bak.<ts>

Notes:
  - Rows with NULL created_by are preserved as legacy data.
  - Rows created by marker sync (`marker-sync`) are preserved.
  - Rows created by AI suggestions (`ai-suggest:*`) are preserved.
  - Only historical manual rows are deleted.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "test_case_repo.db"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delete historical manual rows from automation_script_case_links."
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually delete rows after an interactive YES confirmation.",
    )
    parser.add_argument(
        "--team-id",
        type=int,
        help="Restrict cleanup to one team_id.",
    )
    return parser.parse_args()


def build_where_clause(team_id: int | None) -> tuple[str, list[object]]:
    clauses = [
        "created_by IS NOT NULL",
        "created_by != ?",
        "created_by NOT LIKE ?",
    ]
    params: list[object] = ["marker-sync", "ai-suggest:%"]
    if team_id is not None:
        clauses.append("team_id = ?")
        params.append(team_id)
    return " AND ".join(clauses), params


def fetch_preview_rows(conn: sqlite3.Connection, team_id: int | None) -> tuple[int, list[sqlite3.Row]]:
    where_clause, params = build_where_clause(team_id)
    count = conn.execute(
        f"SELECT COUNT(*) FROM automation_script_case_links WHERE {where_clause}",
        params,
    ).fetchone()[0]
    rows = conn.execute(
        (
            "SELECT id, team_id, automation_script_id, test_case_id, link_type, created_by "
            f"FROM automation_script_case_links WHERE {where_clause} "
            "ORDER BY id LIMIT 10"
        ),
        params,
    ).fetchall()
    return count, rows


def delete_rows(conn: sqlite3.Connection, team_id: int | None) -> int:
    where_clause, params = build_where_clause(team_id)
    cursor = conn.execute(
        f"DELETE FROM automation_script_case_links WHERE {where_clause}",
        params,
    )
    conn.commit()
    return cursor.rowcount


def main() -> int:
    args = parse_args()
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        count, preview_rows = fetch_preview_rows(conn, args.team_id)
        scope = f"team_id={args.team_id}" if args.team_id is not None else "all teams"
        print(f"Scope: {scope}")
        print(f"Would delete {count} rows from automation_script_case_links")
        if preview_rows:
            print("Sample rows (max 10):")
            for row in preview_rows:
                print(
                    "  "
                    f"id={row['id']} team_id={row['team_id']} "
                    f"script_id={row['automation_script_id']} test_case_id={row['test_case_id']} "
                    f"link_type={row['link_type']} created_by={row['created_by']}"
                )
        else:
            print("Sample rows: none")

        if not args.confirm:
            print("Dry run only. Re-run with --confirm to delete rows.")
            return 0

        answer = input("Type YES to delete these rows: ").strip()
        if answer != "YES":
            print("Aborted.")
            return 1

        deleted = delete_rows(conn, args.team_id)
        print(f"Deleted {deleted} rows.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
