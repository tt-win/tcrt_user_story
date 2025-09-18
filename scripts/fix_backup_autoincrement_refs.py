#!/usr/bin/env python3
"""Clean up leftover *_backup_autoinc references in SQLite schema.

This script針對先前執行 `scripts/migrate_autoincrement.py` 半途終止時留下的
`*_backup_autoinc` 暫存表名稱。當外鍵仍指向暫存表時，SQLite 會在插入資料時
出現 `no such table: main.xxx_backup_autoinc` 錯誤。本工具會：

1. 偵測所有實際 schema（sqlite_master.sql）內仍引用 *_backup_autoinc 的資料表。
2. 將這些表格以安全流程重新建表，並把外鍵指向原始名稱（去除後綴）。
3. 重建原有索引並更新 sqlite_sequence。

使用方式：
    python scripts/fix_backup_autoincrement_refs.py

執行前建議先備份資料庫檔案（專案根目錄下 `test_case_repo.db`）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Tuple

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

# 讓腳本可在專案根目錄外直接執行
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import engine  # noqa: E402


BACKUP_SUFFIX = "_backup_autoinc"


def log(msg: str) -> None:
    print(f"[fix-backup] {msg}")


def find_backup_tables(connection) -> List[str]:
    result = connection.execute(
        text(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name LIKE :suffix"
        ),
        {"suffix": f"%{BACKUP_SUFFIX}"},
    )
    return [row[0] for row in result]


def find_tables_with_backup_refs(connection) -> List[Tuple[str, str]]:
    rows = connection.execute(
        text(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='table' AND sql LIKE :pattern"
        ),
        {"pattern": f"%{BACKUP_SUFFIX}%"},
    )
    candidates: List[Tuple[str, str]] = []
    for name, sql in rows:
        if not sql:
            continue
        # 排除暫存備份表本身
        if name.endswith(BACKUP_SUFFIX):
            continue
        candidates.append((name, sql))
    return candidates


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def rebuild_table(connection, table_name: str, original_sql: str, mapping: Dict[str, str]) -> None:
    tmp_name = f"{table_name}__fix_tmp"

    log(f"修正資料表 {table_name}")

    # 蒐集索引定義，稍後重建
    index_rows = connection.execute(
        text(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='index' AND tbl_name=:tbl AND sql IS NOT NULL"
        ),
        {"tbl": table_name},
    ).fetchall()

    # 重新寫入建表 SQL（將 *_backup_autoinc 改為原名）
    fixed_sql = original_sql
    for backup_name, real_name in mapping.items():
        fixed_sql = fixed_sql.replace(backup_name, real_name)

    log(f"  建立暫存表 {tmp_name}")
    connection.execute(text(f'ALTER TABLE {quote_identifier(table_name)} RENAME TO {quote_identifier(tmp_name)}'))

    log("  重建資料表結構")
    connection.execute(text(fixed_sql))

    # 取得欄位名稱列表
    pragma_rows = connection.execute(text(f'PRAGMA table_info({quote_identifier(tmp_name)})')).fetchall()
    column_names = [row[1] for row in pragma_rows]
    column_list = ", ".join(f'"{col}"' for col in column_names)

    log("  搬移資料")
    connection.execute(
        text(
            f'INSERT INTO {quote_identifier(table_name)} ({column_list}) '
            f'SELECT {column_list} FROM {quote_identifier(tmp_name)}'
        )
    )

    log("  移除暫存表")
    connection.execute(text(f'DROP TABLE {quote_identifier(tmp_name)}'))

    log("  重建索引")
    for index_name, index_sql in index_rows:
        # 部分索引 SQL 可能為 None（自動索引），已於查詢過濾
        if index_sql:
            connection.execute(text(index_sql))

    # 更新 sqlite_sequence 以維持自動編號連續性
    quoted_table = quote_identifier(table_name)
    try:
        connection.execute(
            text(
                "INSERT INTO sqlite_sequence(name, seq) "
                f"SELECT :tbl, COALESCE(MAX(id), 0) FROM {quoted_table} "
                "WHERE NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name = :tbl)"
            ),
            {"tbl": table_name},
        )
        connection.execute(
            text(
                "UPDATE sqlite_sequence SET seq = "
                f"COALESCE((SELECT MAX(id) FROM {quoted_table}), 0) "
                "WHERE name = :tbl"
            ),
            {"tbl": table_name},
        )
    except SQLAlchemyError:
        # sqlite_sequence 不存在時忽略（例如資料庫尚未啟用 AUTOINCREMENT）
        pass


def main() -> None:
    db_path = engine.url.database or "(memory)"
    log(f"開始修正資料庫：{db_path}")

    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=OFF"))
        try:
            backup_tables = find_backup_tables(connection)
            if backup_tables:
                log("偵測到暫存備份表：" + ", ".join(backup_tables))

            tables_to_fix = find_tables_with_backup_refs(connection)
            if not tables_to_fix:
                log("沒有發現引用 *_backup_autoinc 的資料表，無需處理。")
                return

            mapping: Dict[str, str] = {}
            for backup_name in backup_tables:
                real_name = backup_name[: -len(BACKUP_SUFFIX)]
                mapping[backup_name] = real_name

            # 針對沒有備份表存在，但字串仍引用的情況，依後綴推導真名
            for _, sql in tables_to_fix:
                fragments = [part for part in sql.split() if BACKUP_SUFFIX in part]
                for fragment in fragments:
                    cleaned = fragment.strip('"`[](),')
                    if cleaned.endswith(BACKUP_SUFFIX) and cleaned not in mapping:
                        mapping[cleaned] = cleaned[: -len(BACKUP_SUFFIX)]

            for table_name, sql in tables_to_fix:
                rebuild_table(connection, table_name, sql, mapping)

            log("修正完成。")
        finally:
            connection.execute(text("PRAGMA foreign_keys=ON"))


if __name__ == "__main__":
    try:
        main()
    except SQLAlchemyError as exc:
        log(f"執行失敗：{exc}")
        sys.exit(1)
