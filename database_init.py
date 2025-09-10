#!/usr/bin/env python3
"""
資料庫初始化腳本（不依賴 migrate.py）

功能：
- 以 app.models.database_models.Base 為唯一真實來源建立資料表
- 檢查「重要表」是否存在
- 掃描「關鍵欄位」缺失（預設僅報告），可選擇安全自動新增（--auto-fix）
- 確保常用索引存在
- SQLite 自動備份（可用 --no-backup 關閉）
- 提供統計輸出（--stats-only 僅輸出統計不變更資料庫）

使用：
  python database_init.py [--auto-fix] [--no-backup] [--stats-only] [--verbose | --quiet]

注意：
- 僅新增欄位，不做破壞性變更（不改型、不刪欄、不改鍵/約束）
- 嚴禁混用不同 Base；本腳本固定採用 app.models.database_models.Base
"""

from __future__ import annotations

import os
import sys
import shutil
import argparse
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# 確保專案根目錄在匯入路徑
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import text
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.database import engine  # 僅匯入 engine，保留該檔的 SQLite 優化設定
from app.models.database_models import (
    Base,
    Team, TestRunConfig, TestRunItem, TestRunItemResultHistory,
    TCGRecord, LarkDepartment, LarkUser, SyncHistory,
)

# -----------------------------
# 輔助輸出（繁體中文）
# -----------------------------
class Logger:
    def __init__(self, verbose: bool = False, quiet: bool = False):
        self.verbose = verbose
        self.quiet = quiet

    def info(self, msg: str):
        if not self.quiet:
            print(f"[INFO] {msg}")

    def debug(self, msg: str):
        if self.verbose and not self.quiet:
            print(f"[VERBOSE] {msg}")

    def warn(self, msg: str):
        print(f"[WARN] {msg}")

    def error(self, msg: str):
        print(f"[ERROR] {msg}")


# -----------------------------
# 通用工具
# -----------------------------
IMPORTANT_TABLES: List[str] = [
    "teams",
    "test_run_configs",
    "test_run_items",
    "test_run_item_result_history",
    "tcg_records",
    "lark_departments",
    "lark_users",
    "sync_history",
]


def is_sqlite(engine: Engine) -> bool:
    return (engine.dialect.name or "").lower() == "sqlite"


def quote_ident(engine: Engine, name: str) -> str:
    return engine.dialect.identifier_preparer.quote(name)


# 欄位規格
class ColumnSpec:
    def __init__(self, name: str, type_sql: str, nullable: bool = True,
                 default: Optional[Any] = None, notes: Optional[str] = None):
        self.name = name
        self.type_sql = type_sql
        self.nullable = nullable
        self.default = default
        self.notes = notes

    def safe_to_add_on(self, engine: Engine) -> bool:
        # 安全新增規則：
        # - 可為 NULL 的欄位
        # - 或 NOT NULL 但提供 DEFAULT
        if self.nullable:
            return True
        return self.default is not None

    def default_sql_literal(self) -> Optional[str]:
        if self.default is None:
            return None
        if isinstance(self.default, str):
            return "'" + self.default.replace("'", "''") + "'"
        if self.default is True:
            return "1"
        if self.default is False:
            return "0"
        if self.default is None:
            return "NULL"
        return str(self.default)


# 欄位檢查清單（僅列出可能在既有 DB 缺少、且可由我們輕量補上的欄位）
COLUMN_CHECKS: Dict[str, List[ColumnSpec]] = {
    # TestRunItem 結果檔案追蹤欄位
    "test_run_items": [
        ColumnSpec("result_files_uploaded", "INTEGER", nullable=False, default=0),
        ColumnSpec("result_files_count", "INTEGER", nullable=False, default=0),
        ColumnSpec("upload_history_json", "TEXT", nullable=True, default=None),
        # 舊欄位檢查（存在即可，不會自動建立 NOT NULL 無預設的欄位）
        ColumnSpec("assignee_json", "TEXT", nullable=True, default=None),
        ColumnSpec("tcg_json", "TEXT", nullable=True, default=None),
        ColumnSpec("bug_tickets_json", "TEXT", nullable=True, default=None),
    ],
    # TestRunConfig 的 TP 票欄位與通知欄位
    "test_run_configs": [
        # TP 票相關
        ColumnSpec("related_tp_tickets_json", "TEXT", nullable=True, default=None),
        ColumnSpec("tp_tickets_search", "TEXT", nullable=True, default=None),
        # 通知相關（對應 ORM：notifications_enabled, notify_chat_ids_json, notify_chat_names_snapshot, notify_chats_search）
        ColumnSpec("notifications_enabled", "INTEGER", nullable=False, default=0),  # Boolean -> INTEGER(0/1)
        ColumnSpec("notify_chat_ids_json", "TEXT", nullable=True, default=None),
        ColumnSpec("notify_chat_names_snapshot", "TEXT", nullable=True, default=None),
        ColumnSpec("notify_chats_search", "TEXT", nullable=True, default=None),
    ],
    # Lark Users 重要索引欄位（若缺少欄位則僅報告，不強制新增 NOT NULL）
    "lark_users": [
        ColumnSpec("enterprise_email", "TEXT", nullable=True, default=None),
        ColumnSpec("primary_department_id", "TEXT", nullable=True, default=None),
    ],
}

# 索引規格
INDEX_SPECS: List[Dict[str, Any]] = [
    {"name": "idx_tri_configid_testcaseno", "table": "test_run_items", "columns": ["config_id", "test_case_number"]},
    {"name": "idx_tri_teamid_result", "table": "test_run_items", "columns": ["team_id", "test_result"]},
    {"name": "idx_tri_result_files_uploaded", "table": "test_run_items", "columns": ["result_files_uploaded"]},
    # test_run_configs 相關搜尋欄位索引（若 ORM 已建立，這裡以 IF NOT EXISTS 形式補強）
    {"name": "idx_trc_tp_tickets_search", "table": "test_run_configs", "columns": ["tp_tickets_search"]},
    {"name": "idx_trc_notify_chats_search", "table": "test_run_configs", "columns": ["notify_chats_search"]},
    # Lark Users 常用索引
    {"name": "idx_lu_enterprise_email", "table": "lark_users", "columns": ["enterprise_email"]},
    {"name": "idx_lu_primary_department_id", "table": "lark_users", "columns": ["primary_department_id"]},
    # Sync History
    {"name": "idx_sh_teamid_starttime", "table": "sync_history", "columns": ["team_id", "start_time"]},
]


# -----------------------------
# 核心步驟實作
# -----------------------------

def backup_sqlite_if_needed(engine: Engine, logger: Logger) -> Optional[str]:
    if not is_sqlite(engine):
        logger.debug("非 SQLite，略過備份程序")
        return None
    db_path = engine.url.database
    if not db_path or db_path == ":memory:":
        logger.debug("SQLite 記憶體資料庫，略過備份")
        return None
    if not os.path.exists(db_path):
        logger.debug(f"資料庫檔案不存在（將於 create_all 時建立）：{db_path}")
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"backup_init_{ts}.db"
    try:
        shutil.copy2(db_path, backup_path)
        logger.info(f"已建立 SQLite 備份：{backup_path}")
        return backup_path
    except Exception as e:
        logger.warn(f"建立備份失敗（不中斷）：{e}")
        return None


def create_all_tables(engine: Engine, logger: Logger):
    logger.info("建立/確保所有資料表（依據 ORM 模型）...")
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("資料表確認完成")
    except SQLAlchemyError as e:
        raise RuntimeError(f"建立資料表失敗：{e}")


def verify_required_tables(engine: Engine, logger: Logger) -> Tuple[bool, List[str]]:
    inspector = inspect(engine)
    existing = {t.lower() for t in inspector.get_table_names()}
    missing = [t for t in IMPORTANT_TABLES if t.lower() not in existing]
    if missing:
        logger.error(f"缺少重要表：{missing}")
        return False, missing
    logger.debug("所有重要表皆存在")
    return True, []


def get_existing_columns(engine: Engine, table_name: str) -> Dict[str, Dict[str, Any]]:
    # 以小寫 key 回傳
    result: Dict[str, Dict[str, Any]] = {}
    if is_sqlite(engine):
        with engine.connect() as conn:
            rows = conn.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
            # PRAGMA columns: cid, name, type, notnull, dflt_value, pk
            for _, name, typ, notnull, dflt, _ in rows:
                result[(name or "").lower()] = {
                    "name": name,
                    "type": typ,
                    "notnull": bool(notnull),
                    "default": dflt,
                }
    else:
        inspector = inspect(engine)
        cols = inspector.get_columns(table_name)
        for col in cols:
            result[(col.get("name") or "").lower()] = col
    return result


def check_missing_columns(engine: Engine, logger: Logger) -> Dict[str, List[ColumnSpec]]:
    missing: Dict[str, List[ColumnSpec]] = {}
    for table, specs in COLUMN_CHECKS.items():
        try:
            existing = get_existing_columns(engine, table)
        except Exception:
            # 表不存在或讀取失敗，交由 verify_required_tables 先行處理
            continue
        for spec in specs:
            if spec.name.lower() not in existing:
                missing.setdefault(table, []).append(spec)
    if missing:
        logger.warn("偵測到缺失欄位（預設僅報告，不自動修復）：")
        for table, specs in missing.items():
            for spec in specs:
                fixable = "可安全新增" if spec.safe_to_add_on(engine) else "需人工處理"
                logger.warn(f"  - {table}.{spec.name} ({spec.type_sql}) -> {fixable}{'｜' + spec.notes if spec.notes else ''}")
    else:
        logger.info("未發現需補充的欄位")
    return missing


def auto_fix_columns(engine: Engine, logger: Logger, missing: Dict[str, List[ColumnSpec]]):
    if not missing:
        logger.info("無欄位需要自動修復")
        return
    logger.info("開始自動新增安全欄位（僅限可安全新增的欄位）...")
    for table, specs in missing.items():
        for spec in specs:
            if not spec.safe_to_add_on(engine):
                logger.warn(f"跳過不安全新增的欄位：{table}.{spec.name}（NOT NULL 且無 DEFAULT 或需人工遷移）")
                continue
            parts = [spec.type_sql]
            default_sql = spec.default_sql_literal()
            if default_sql is not None:
                parts.append(f"DEFAULT {default_sql}")
            if not spec.nullable:
                parts.append("NOT NULL")
            col_ddl = " ".join(parts)
            sql = f"ALTER TABLE {quote_ident(engine, table)} ADD COLUMN {quote_ident(engine, spec.name)} {col_ddl}"
            try:
                with engine.begin() as conn:
                    conn.exec_driver_sql(sql)
                logger.info(f"已新增欄位：{table}.{spec.name}")
            except Exception as e:
                logger.warn(f"新增欄位失敗：{table}.{spec.name} -> {e}")


def ensure_indexes(engine: Engine, logger: Logger):
    logger.info("確保常用索引存在...")
    dialect = (engine.dialect.name or "").lower()
    supports_if_not_exists = dialect in {"sqlite", "postgresql"}
    inspector = inspect(engine)

    for idx in INDEX_SPECS:
        name = idx["name"]
        table = idx["table"]
        columns = idx["columns"]
        try:
            existing = {i.get("name") for i in inspector.get_indexes(table)}
        except Exception:
            existing = set()
        if name in existing:
            logger.debug(f"索引已存在：{name}")
            continue
        cols_sql = ", ".join(quote_ident(engine, c) for c in columns)
        if supports_if_not_exists:
            sql = f"CREATE INDEX IF NOT EXISTS {quote_ident(engine, name)} ON {quote_ident(engine, table)} ({cols_sql})"
        else:
            sql = f"CREATE INDEX {quote_ident(engine, name)} ON {quote_ident(engine, table)} ({cols_sql})"
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(sql)
            logger.info(f"已建立索引：{name}")
        except Exception as e:
            # 可能競態或已存在等情況
            logger.warn(f"建立索引警告（可能已存在）：{name} -> {e}")


def get_database_stats(engine: Engine, logger: Logger) -> Dict[str, Any]:
    stats: Dict[str, Any] = {"tables": {}, "total_tables": 0, "engine_url": str(engine.url), "errors": []}
    try:
        if is_sqlite(engine):
            with engine.connect() as conn:
                rows = conn.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
                table_names = [r[0] for r in rows]
                for t in table_names:
                    try:
                        cnt = conn.exec_driver_sql(f"SELECT COUNT(*) FROM {quote_ident(engine, t)}").scalar()
                        cols = conn.exec_driver_sql(f"PRAGMA table_info({t})").fetchall()
                        stats["tables"][t] = {
                            "rows": int(cnt or 0),
                            "columns": len(cols),
                        }
                    except Exception as e:
                        stats["tables"][t] = {"error": str(e)}
        else:
            inspector = inspect(engine)
            table_names = inspector.get_table_names()
            with engine.connect() as conn:
                for t in table_names:
                    try:
                        cnt = conn.execute(text(f"SELECT COUNT(*) FROM {quote_ident(engine, t)}")).scalar()
                        cols = inspector.get_columns(t)
                        stats["tables"][t] = {
                            "rows": int(cnt or 0),
                            "columns": len(cols),
                        }
                    except Exception as e:
                        stats["tables"][t] = {"error": str(e)}
        stats["total_tables"] = len(stats["tables"])
    except Exception as e:
        stats["errors"].append(str(e))
    return stats


def print_stats(stats: Dict[str, Any], logger: Logger):
    print("=" * 60)
    print("📊 資料庫統計摘要")
    print("=" * 60)
    print(f"總表格數：{stats.get('total_tables')}")
    tables = stats.get("tables", {})
    for t, d in sorted(tables.items()):
        if "error" in d:
            print(f"  ❌ {t}: {d['error']}")
        else:
            print(f"  ✅ {t}: {d['rows']} 筆記錄, {d['columns']} 欄位")
    print()
    print("重要表格狀態：")
    for t in IMPORTANT_TABLES:
        d = tables.get(t)
        if d is None:
            print(f"  ⚠️  {t}: 表格不存在")
        elif "error" in d:
            print(f"  ❌ {t}: {d['error']}")
        else:
            print(f"  ✅ {t}: {d['rows']} 筆記錄, {d['columns']} 欄位")
    print()
    print(f"📂 資料庫位置：{stats.get('engine_url')}")


# -----------------------------
# 參數與主流程
# -----------------------------

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="資料庫初始化腳本（不依賴 migrate.py）")
    p.add_argument("--auto-fix", action="store_true", help="自動新增可安全新增的缺失欄位")
    p.add_argument("--no-backup", action="store_true", help="（SQLite）跳過初始化前的資料庫備份")
    p.add_argument("--stats-only", action="store_true", help="僅輸出統計與狀態，不做任何變更")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--verbose", action="store_true", help="輸出更多詳細資訊")
    g.add_argument("--quiet", action="store_true", help="僅輸出必要資訊與錯誤")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    logger = Logger(verbose=args.verbose, quiet=args.quiet)

    print("=" * 60)
    print("🗃️  資料庫初始化系統（不依賴 migrate.py）")
    print("=" * 60)

    try:
        db_url = str(engine.url)
        db_kind = engine.dialect.name
        logger.info(f"偵測到資料庫：{db_kind} | URL={db_url}")

        if args.stats_only:
            stats = get_database_stats(engine, logger)
            print_stats(stats, logger)
            return 0

        # 備份（SQLite）
        backup_path = None
        if is_sqlite(engine) and not args.no_backup:
            backup_path = backup_sqlite_if_needed(engine, logger)

        # 建表
        create_all_tables(engine, logger)

        # 驗證重要表
        ok, missing = verify_required_tables(engine, logger)
        if not ok:
            logger.error("重要表缺失，請確認模型或資料庫狀態後重試。")
            return 2

        # 欄位檢查
        missing_cols = check_missing_columns(engine, logger)

        # 自動補欄位（僅安全新增）
        if args.auto_fix and missing_cols:
            auto_fix_columns(engine, logger, missing_cols)
        elif missing_cols:
            logger.info("如需自動補上可安全新增的欄位，可使用 --auto-fix 參數。")

        # 索引確保
        ensure_indexes(engine, logger)

        # 最終統計
        stats = get_database_stats(engine, logger)
        print_stats(stats, logger)

        logger.info("✅ 資料庫初始化完成！")
        if backup_path:
            logger.info(f"若需回復，可使用備份檔：{backup_path}")
        return 0

    except Exception as e:
        logger.error(f"初始化過程中發生錯誤：{e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
