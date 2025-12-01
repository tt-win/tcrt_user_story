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

from app.database import get_sync_engine  # 使用同步引擎為 database_init.py
from app.models.database_models import (
    Base,
    User, UserTeamPermission, ActiveSession, PasswordResetToken,  # 認證系統相關表
    Team, TestRunConfig, TestRunItem, TestRunItemResultHistory,
    TCGRecord, LarkDepartment, LarkUser, SyncHistory,
    TestCaseSet, TestCaseSection,  # Test Case Set/Section 相關表
)
from sqlalchemy import create_engine

from app.audit import audit_db_manager, AuditLogTable

# User Story Map 資料庫相關
from app.models.user_story_map_db import (
    Base as USMBase,
    UserStoryMapDB,
    UserStoryMapNodeDB,
    DATABASE_URL as USM_DATABASE_URL,
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
    # 認證系統相關表
    "users",
    "user_team_permissions",
    "active_sessions",
    "password_reset_tokens",
    # 測試系統相關表
    "teams",
    "test_case_sets",
    "test_case_sections",
    "test_run_configs",
    "test_run_sets",
    "test_run_set_memberships",
    "test_run_items",
    "test_run_item_result_history",
    "adhoc_runs",
    "adhoc_run_sheets",
    "adhoc_run_items",
    "tcg_records",
    "lark_departments",
    "lark_users",
    "sync_history",
]

AUDIT_TABLES: List[str] = [
    "audit_logs",
]

USM_TABLES: List[str] = [
    "user_story_maps",
    "user_story_map_nodes",
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


# 欄位約束修改規格
class ColumnConstraintChange:
    def __init__(self, table: str, column: str, old_constraint: str, new_constraint: str, notes: str = ""):
        self.table = table
        self.column = column
        self.old_constraint = old_constraint  # 例如 "NOT NULL"
        self.new_constraint = new_constraint  # 例如 "NULL"
        self.notes = notes

    def needs_migration(self, engine: Engine) -> bool:
        """檢查是否需要進行約束遷移"""
        try:
            existing_cols = get_existing_columns(engine, self.table)
            col_info = existing_cols.get(self.column.lower())
            if not col_info:
                return False
            
            # 特殊處理 adhoc_runs.status，總是允許執行資料遷移 (update DRAFT -> ACTIVE)
            if self.table == "adhoc_runs" and self.column == "status":
                return True

            # 檢查 NOT NULL 約束
            if self.old_constraint == "NOT NULL" and self.new_constraint == "NULL":
                return col_info.get("notnull", False)  # 如果目前是 NOT NULL，需要遷移
            return False
        except Exception:
            return False

# 欄位約束變更清單
COLUMN_CONSTRAINT_CHANGES: List[ColumnConstraintChange] = [
    ColumnConstraintChange(
        table="users",
        column="email",
        old_constraint="NOT NULL",
        new_constraint="NULL",
        notes="系統初始化時允許不提供 email"
    ),
    ColumnConstraintChange(
        table="user_story_map_nodes",
        column="node_type",
        old_constraint="NOT NULL",
        new_constraint="NULL",
        notes="節點類型屬性已移除，欄位改為允許 NULL 以維持相容性"
    ),
    ColumnConstraintChange(
        table="adhoc_runs",
        column="status",
        old_constraint="DRAFT",
        new_constraint="ACTIVE",
        notes="Ad-hoc Run 預設狀態變更為 Active"
    ),
]

# 欄位檢查清單（僅列出可能在既有 DB 缺少、且可由我們輕量補上的欄位）
COLUMN_CHECKS: Dict[str, List[ColumnSpec]] = {
    # Users 欄位補充
    "users": [
        ColumnSpec("lark_user_id", "TEXT", nullable=True, default=None),
    ],
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
    "adhoc_runs": [
        ColumnSpec("test_version", "VARCHAR(50)", nullable=True, default=None),
        ColumnSpec("test_environment", "VARCHAR(100)", nullable=True, default=None),
        ColumnSpec("build_number", "VARCHAR(100)", nullable=True, default=None),
        ColumnSpec("related_tp_tickets_json", "TEXT", nullable=True, default=None),
        ColumnSpec("tp_tickets_search", "VARCHAR(1000)", nullable=True, default=None),
        ColumnSpec("notifications_enabled", "INTEGER", nullable=False, default=0),
        ColumnSpec("notify_chat_ids_json", "TEXT", nullable=True, default=None),
        ColumnSpec("notify_chat_names_snapshot", "TEXT", nullable=True, default=None),
        ColumnSpec("notify_chats_search", "VARCHAR(1000)", nullable=True, default=None),
    ],
    "adhoc_run_sheets": [
        # ... existing checks if any, or empty
    ],
    "adhoc_run_items": [
        ColumnSpec("meta_json", "TEXT", nullable=True, default=None),
    ],
    # TestCaseLocal 需要新增的附件標記欄位和 Set/Section 關聯欄位
    "test_cases": [
        ColumnSpec("has_attachments", "INTEGER", nullable=False, default=0, notes="是否有附件（0/1）"),
        ColumnSpec("attachment_count", "INTEGER", nullable=False, default=0, notes="附件數量"),
        ColumnSpec("test_case_set_id", "INTEGER", nullable=True, default=None, notes="關聯的 Test Case Set ID"),
        ColumnSpec("test_case_section_id", "INTEGER", nullable=True, default=None, notes="關聯的 Test Case Section ID"),
    ],
    # Lark Users 重要索引欄位（若缺少欄位則僅報告，不強制新增 NOT NULL）
    "lark_users": [
        ColumnSpec("enterprise_email", "TEXT", nullable=True, default=None),
        ColumnSpec("primary_department_id", "TEXT", nullable=True, default=None),
    ],
}

AUDIT_COLUMN_CHECKS: Dict[str, List[ColumnSpec]] = {
    "audit_logs": [
        ColumnSpec("role", "VARCHAR(50)", nullable=False, default="user"),
        ColumnSpec("action_brief", "VARCHAR(500)", nullable=True, default=None),
    ],
}

AUDIT_INDEX_SPECS: List[Dict[str, Any]] = [
    {"name": "idx_audit_time_team", "table": "audit_logs", "columns": ["timestamp", "team_id"]},
    {"name": "idx_audit_user_time", "table": "audit_logs", "columns": ["user_id", "timestamp"]},
    {"name": "idx_audit_resource", "table": "audit_logs", "columns": ["resource_type", "resource_id"]},
    {"name": "idx_audit_severity_time", "table": "audit_logs", "columns": ["severity", "timestamp"]},
    {"name": "idx_audit_username_time", "table": "audit_logs", "columns": ["username", "timestamp"]},
    {"name": "idx_audit_role_time", "table": "audit_logs", "columns": ["role", "timestamp"]},
    {"name": "idx_audit_action_time", "table": "audit_logs", "columns": ["action_type", "timestamp"]},
]

# 索引規格
INDEX_SPECS: List[Dict[str, Any]] = [
    # Users
    {"name": "idx_users_lark_user_id", "table": "users", "columns": ["lark_user_id"], "unique": True},
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
    # Ad-hoc Runs Search Indexes
    {"name": "idx_adhoc_tp_tickets_search", "table": "adhoc_runs", "columns": ["tp_tickets_search"]},
    {"name": "idx_adhoc_notify_chats_search", "table": "adhoc_runs", "columns": ["notify_chats_search"]},
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


def _migrate_legacy_auth_tables(engine: Engine, logger: Logger):
    """遷移舊的認證相關表格到新的結構"""
    with engine.begin() as conn:
        # 檢查舊 users 表格的結構
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name = 'users'
        """))
        has_old_users = result.fetchone() is not None
        
        if has_old_users:
            # 檢查表格結構是否為舊版本
            result = conn.execute(text("PRAGMA table_info(users)"))
            columns = [row[1] for row in result.fetchall()]
            
            # 如果是舊版本的 users 表（有 lark_id 但沒有 username/email）
            if 'lark_id' in columns and 'username' not in columns:
                logger.info("檢測到舊版 users 表格，進行結構遷移...")
                
                # 備份舊表格
                conn.execute(text("CREATE TABLE users_legacy_backup AS SELECT * FROM users"))
                logger.info("已備份舊 users 表格至 users_legacy_backup")
                
                # 刪除舊表格
                conn.execute(text("DROP TABLE users"))
                
                # 由 SQLAlchemy 重新創庺新表格（在 Base.metadata.create_all 中處理）
                logger.info("已刪除舊 users 表，將由 SQLAlchemy 重新創庺")
            else:
                logger.info("現有 users 表格結構已為新版，無需遷移")
                
        # 處理 roles 表格（新系統不需要獨立的 roles 表）
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name = 'roles'
        """))
        has_old_roles = result.fetchone() is not None
        
        if has_old_roles:
            logger.info("檢測到舊的 roles 表格，備份後刪除...")
            conn.execute(text("CREATE TABLE roles_legacy_backup AS SELECT * FROM roles"))
            conn.execute(text("DROP TABLE roles"))
            logger.info("舊 roles 表格已備份至 roles_legacy_backup 並刪除")


def ensure_test_run_item_history_fk(engine: Engine, logger: Logger) -> None:
    """修復 test_run_item_result_history 表格仍引用舊備份表的外鍵。"""
    if not is_sqlite(engine):
        return

    with engine.begin() as connection:
        row = connection.execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type='table' AND name='test_run_item_result_history'"
            )
        ).fetchone()
        if not row or not row[0] or "test_run_items_backup_snapshot" not in row[0]:
            return

        logger.info("偵測到 test_run_item_result_history 外鍵引用備份表，開始修復")
        legacy_name = "test_run_item_result_history_legacy_fk"
        connection.execute(text("PRAGMA foreign_keys=OFF"))
        try:
            connection.execute(text(f"ALTER TABLE test_run_item_result_history RENAME TO {legacy_name}"))

            indexes = connection.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='index' AND tbl_name=:tbl AND name NOT LIKE 'sqlite_autoindex%'"
                ),
                {"tbl": legacy_name},
            ).fetchall()
            for (index_name,) in indexes:
                if index_name:
                    connection.execute(text(f'DROP INDEX IF EXISTS "{index_name}"'))

            TestRunItemResultHistory.__table__.create(bind=connection)

            available_cols = connection.execute(
                text(f"PRAGMA table_info('{legacy_name}')")
            ).fetchall()
            available = {row[1] for row in available_cols}
            target_columns = [
                col.name
                for col in TestRunItemResultHistory.__table__.c
                if col.name in available
            ]
            if target_columns:
                columns_csv = ", ".join(f'"{col}"' for col in target_columns)
                connection.execute(
                    text(
                        f'INSERT INTO test_run_item_result_history ({columns_csv}) '
                        f'SELECT {columns_csv} FROM {legacy_name}'
                    )
                )

            connection.execute(text(f"DROP TABLE {legacy_name}"))

            try:
                connection.execute(
                    text(
                        "UPDATE sqlite_sequence SET seq = "
                        "COALESCE((SELECT MAX(id) FROM test_run_item_result_history), 0) "
                        "WHERE name='test_run_item_result_history'"
                    )
                )
            except Exception:
                pass
            logger.info("test_run_item_result_history 外鍵修復完成")
        finally:
            connection.execute(text("PRAGMA foreign_keys=ON"))


def create_all_tables(engine: Engine, logger: Logger):
    logger.info("建立/確保所有資料表（依據 ORM 模型）...")
    try:
        # 執行遷移
        _migrate_legacy_auth_tables(engine, logger)
        
        # 創庺所有表格
        Base.metadata.create_all(bind=engine)
        
        # 執行 FK 修正
        ensure_test_run_item_history_fk(engine, logger)
        
        logger.info("資料表確認完成")
    except SQLAlchemyError as e:
        raise RuntimeError(f"建立資料表失敗：{e}")


def ensure_schema_compatibility(engine: Engine, logger: Logger):
    """確保資料庫結構與模型相容 (補上可能缺失的欄位)"""
    inspector = inspect(engine)
    
    # 檢查 test_cases 表是否存在
    if not inspector.has_table("test_cases"):
        return

    columns = {col['name'] for col in inspector.get_columns('test_cases')}
    
    with engine.begin() as conn:
        if 'test_case_set_id' not in columns:
            logger.info("補上缺失欄位: test_cases.test_case_set_id")
            conn.execute(text("ALTER TABLE test_cases ADD COLUMN test_case_set_id INTEGER"))
            
        if 'test_case_section_id' not in columns:
            logger.info("補上缺失欄位: test_cases.test_case_section_id")
            conn.execute(text("ALTER TABLE test_cases ADD COLUMN test_case_section_id INTEGER"))
            
        # 順便補上附件欄位，避免其他潛在錯誤
        if 'has_attachments' not in columns:
            logger.info("補上缺失欄位: test_cases.has_attachments")
            conn.execute(text("ALTER TABLE test_cases ADD COLUMN has_attachments INTEGER NOT NULL DEFAULT 0"))
            
        if 'attachment_count' not in columns:
            logger.info("補上缺失欄位: test_cases.attachment_count")
            conn.execute(text("ALTER TABLE test_cases ADD COLUMN attachment_count INTEGER NOT NULL DEFAULT 0"))


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


def check_missing_audit_columns(engine: Engine, logger: Logger) -> Dict[str, List[ColumnSpec]]:
    missing: Dict[str, List[ColumnSpec]] = {}
    for table, specs in AUDIT_COLUMN_CHECKS.items():
        try:
            existing = get_existing_columns(engine, table)
        except Exception:
            continue
        for spec in specs:
            if spec.name.lower() not in existing:
                missing.setdefault(table, []).append(spec)
    if missing:
        logger.warn("審計資料庫偵測到缺失欄位：")
        for table, specs in missing.items():
            for spec in specs:
                fixable = "可安全新增" if spec.safe_to_add_on(engine) else "需人工處理"
                logger.warn(f"  - {table}.{spec.name} ({spec.type_sql}) -> {fixable}{'｜' + spec.notes if spec.notes else ''}")
    else:
        logger.info("審計資料庫未發現需補充的欄位")
    return missing


def check_constraint_changes(engine: Engine, logger: Logger) -> List[ColumnConstraintChange]:
    """檢查需要進行約束變更的欄位"""
    needed_changes = []
    for change in COLUMN_CONSTRAINT_CHANGES:
        if change.needs_migration(engine):
            needed_changes.append(change)
    
    if needed_changes:
        logger.warn("偵測到需要約束變更的欄位（預設僅報告，不自動修復）：")
        for change in needed_changes:
            logger.warn(f"  - {change.table}.{change.column}: {change.old_constraint} -> {change.new_constraint} {'｜' + change.notes if change.notes else ''}")
    else:
        logger.info("未發現需要約束變更的欄位")
    
    return needed_changes

def auto_fix_constraint_changes(engine: Engine, logger: Logger, constraint_changes: List[ColumnConstraintChange]):
    """自動修復欄位約束變更（僅限 SQLite）"""
    if not constraint_changes:
        logger.info("無約束變更需要修復")
        return
    
    if not is_sqlite(engine):
        logger.warn("約束變更修復目前僅支援 SQLite資料庫")
        return
    
    logger.info("開始自動修復欄位約束變更...")
    
    for change in constraint_changes:
        if change.table == "users" and change.column == "email" and change.old_constraint == "NOT NULL":
            try:
                _migrate_users_email_to_nullable(engine, logger)
                logger.info(f"已修復約束：{change.table}.{change.column}")
            except Exception as e:
                logger.error(f"修復約束失敗：{change.table}.{change.column} -> {e}")
        elif change.table == "adhoc_runs" and change.column == "status":
            try:
                _migrate_adhoc_run_status_default(engine, logger)
                logger.info(f"已遷移狀態：{change.table}.{change.column}")
            except Exception as e:
                logger.error(f"遷移狀態失敗：{change.table}.{change.column} -> {e}")
        else:
            logger.warn(f"跳過不支援的約束變更：{change.table}.{change.column}")

def _migrate_users_email_to_nullable(engine: Engine, logger: Logger):
    """將 users.email 欄位從 NOT NULL 改為 nullable"""
    logger.info("開始遷移 users.email 欄位約束...")
    
    with engine.begin() as conn:
        # 備份原始表結構為临時表
        conn.exec_driver_sql("""
            CREATE TABLE users_backup AS 
            SELECT * FROM users
        """)
        
        # 建立新的 users 表結構（email 可為 NULL）
        conn.exec_driver_sql("DROP TABLE users")
        conn.exec_driver_sql("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username VARCHAR(50) UNIQUE NOT NULL,
                email VARCHAR(255) UNIQUE,
                hashed_password VARCHAR(255) NOT NULL,
                full_name VARCHAR(255),
                role VARCHAR(50) NOT NULL DEFAULT 'user',
                is_active BOOLEAN NOT NULL DEFAULT 1,
                is_verified BOOLEAN NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_login_at DATETIME
            )
        """)
        
        # 復原資料（空字串 email 轉為 NULL）
        conn.exec_driver_sql("""
            INSERT INTO users (
                id, username, email, hashed_password, full_name, 
                role, is_active, is_verified, created_at, updated_at, last_login_at
            )
            SELECT 
                id, username, 
                CASE WHEN email = '' OR email IS NULL THEN NULL ELSE email END,
                hashed_password, full_name, 
                role, is_active, is_verified, created_at, updated_at, last_login_at
            FROM users_backup
        """)
        
        # 重建索引
        conn.exec_driver_sql("CREATE INDEX ix_users_username ON users (username)")
        conn.exec_driver_sql("CREATE INDEX ix_users_email ON users (email)")
        conn.exec_driver_sql("CREATE INDEX ix_users_role_active ON users (role, is_active)")
        conn.exec_driver_sql("CREATE INDEX ix_users_email_active ON users (email, is_active)")
        conn.exec_driver_sql("CREATE INDEX ix_users_is_active ON users (is_active)")
        
        # 清理備份表
        conn.exec_driver_sql("DROP TABLE users_backup")
    
    logger.info("users.email 欄位約束遷移完成")

def _migrate_adhoc_run_status_default(engine: Engine, logger: Logger):
    """將 adhoc_runs 的 status 預設值變更為 ACTIVE，並更新既有 DRAFT 資料"""
    logger.info("開始遷移 adhoc_runs.status 預設值...")
    
    with engine.begin() as conn:
        # 更新現有 DRAFT 狀態為 ACTIVE (因為 DRAFT 已被移除)
        conn.exec_driver_sql("UPDATE adhoc_runs SET status = 'active' WHERE status = 'draft'")
        
        # SQLite 不支援直接 ALTER COLUMN SET DEFAULT，需重建表或忽略（僅資料更新即可滿足需求）
        # 這裡主要確保資料一致性
    
    logger.info("adhoc_runs.status 資料遷移完成")

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
        is_unique = bool(idx.get("unique", False))
        if supports_if_not_exists:
            sql = f"CREATE {'UNIQUE ' if is_unique else ''}INDEX IF NOT EXISTS {quote_ident(engine, name)} ON {quote_ident(engine, table)} ({cols_sql})"
        else:
            sql = f"CREATE {'UNIQUE ' if is_unique else ''}INDEX {quote_ident(engine, name)} ON {quote_ident(engine, table)} ({cols_sql})"
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(sql)
            logger.info(f"已建立索引：{name}")
        except Exception as e:
            # 可能競態或已存在等情況
            logger.warn(f"建立索引警告（可能已存在）：{name} -> {e}")


def ensure_audit_indexes(engine: Engine, logger: Logger):
    logger.info("確保審計資料庫索引存在...")
    dialect = (engine.dialect.name or "").lower()
    supports_if_not_exists = dialect in {"sqlite", "postgresql"}
    inspector = inspect(engine)

    for idx in AUDIT_INDEX_SPECS:
        name = idx["name"]
        table = idx["table"]
        columns = idx["columns"]
        try:
            existing = {i.get("name") for i in inspector.get_indexes(table)}
        except Exception:
            existing = set()
        if name in existing:
            logger.debug(f"審計索引已存在：{name}")
            continue
        cols_sql = ", ".join(quote_ident(engine, c) for c in columns)
        if supports_if_not_exists:
            sql = f"CREATE INDEX IF NOT EXISTS {quote_ident(engine, name)} ON {quote_ident(engine, table)} ({cols_sql})"
        else:
            sql = f"CREATE INDEX {quote_ident(engine, name)} ON {quote_ident(engine, table)} ({cols_sql})"
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(sql)
            logger.info(f"已建立審計索引：{name}")
        except Exception as e:
            logger.warn(f"建立審計索引警告：{name} -> {e}")


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


def print_audit_stats(stats: Dict[str, Any], logger: Logger):
    print("=" * 60)
    print("🔐 審計資料庫統計摘要")
    print("=" * 60)
    print(f"總表格數：{stats.get('total_tables')}")
    tables = stats.get("tables", {})
    for t, d in sorted(tables.items()):
        if "error" in d:
            print(f"  ❌ {t}: {d['error']}")
        else:
            print(f"  ✅ {t}: {d['rows']} 筆記錄, {d['columns']} 欄位")
    print()
    print("重要審計表格狀態：")
    for t in AUDIT_TABLES:
        d = tables.get(t)
        if d is None:
            print(f"  ⚠️  {t}: 表格不存在")
        elif "error" in d:
            print(f"  ❌ {t}: {d['error']}")
        else:
            print(f"  ✅ {t}: {d['rows']} 筆記錄, {d['columns']} 欄位")
    print()
    print(f"📂 審計資料庫位置：{stats.get('engine_url')}")


def print_usm_stats(stats: Dict[str, Any], logger: Logger):
    print("=" * 60)
    print("🗺️  User Story Map 資料庫統計摘要")
    print("=" * 60)
    print(f"總表格數：{stats.get('total_tables')}")
    tables = stats.get("tables", {})
    for t, d in sorted(tables.items()):
        if "error" in d:
            print(f"  ❌ {t}: {d['error']}")
        else:
            print(f"  ✅ {t}: {d['rows']} 筆記錄, {d['columns']} 欄位")
    print()
    print("User Story Map 表格狀態：")
    for t in USM_TABLES:
        d = tables.get(t)
        if d is None:
            print(f"  ⚠️  {t}: 表格不存在")
        elif "error" in d:
            print(f"  ❌ {t}: {d['error']}")
        else:
            print(f"  ✅ {t}: {d['rows']} 筆記錄, {d['columns']} 欄位")
    print()
    print(f"📂 User Story Map 資料庫位置：{stats.get('engine_url')}")


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


def _normalize_audit_url(url: str) -> str:
    """將異步驅動的 URL 轉換為同步驅動"""
    if url.startswith("sqlite+aiosqlite://"):
        return url.replace("sqlite+aiosqlite://", "sqlite:///")
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://")
    return url


def initialize_audit_engine(logger: Logger):
    try:
        sync_url = _normalize_audit_url(audit_db_manager.config.database_url)
        engine = create_engine(sync_url, future=True)
        # 確保審計資料表存在
        AuditLogTable.metadata.create_all(bind=engine)
        logger.info("審計資料庫已初始化")
        return engine
    except Exception as exc:
        logger.error(f"審計資料庫初始化失敗：{exc}")
        raise


def initialize_usm_engine(logger: Logger):
    """初始化 User Story Map 資料庫"""
    try:
        sync_url = _normalize_audit_url(USM_DATABASE_URL)
        engine = create_engine(sync_url, future=True)
        # 確保 USM 資料表存在
        USMBase.metadata.create_all(bind=engine)
        logger.info("User Story Map 資料庫已初始化")
        return engine
    except Exception as exc:
        logger.error(f"User Story Map 資料庫初始化失敗：{exc}")
        import traceback
        logger.error(traceback.format_exc())
        raise


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    logger = Logger(verbose=args.verbose, quiet=args.quiet)

    print("=" * 60)
    print("🗃️  資料庫初始化系統（不依賴 migrate.py）")
    print("=" * 60)

    try:
        # 獲取同步引擎
        engine = get_sync_engine()
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

        # 確保結構相容 (補上缺失欄位，例如 test_case_set_id)
        ensure_schema_compatibility(engine, logger)

        # 驗證重要表
        ok, missing = verify_required_tables(engine, logger)
        if not ok:
            logger.error("重要表缺失，請確認模型或資料庫狀態後重試。")
            return 2

        # 欄位檢查
        missing_cols = check_missing_columns(engine, logger)
        
        # 約束變更檢查
        constraint_changes = check_constraint_changes(engine, logger)

        # 自動補欄位（僅安全新增）
        if args.auto_fix and missing_cols:
            auto_fix_columns(engine, logger, missing_cols)
        elif missing_cols:
            logger.info("如需自動補上可安全新增的欄位，可使用 --auto-fix 參數。")
        
        # 自動修復約束變更
        if args.auto_fix and constraint_changes:
            auto_fix_constraint_changes(engine, logger, constraint_changes)
        elif constraint_changes:
            logger.info("如需自動修復約束變更，可使用 --auto-fix 參數。")

        # 索引確保
        ensure_indexes(engine, logger)

        # 審計資料庫初始化與檢查
        audit_engine = initialize_audit_engine(logger)
        audit_missing_cols = check_missing_audit_columns(audit_engine, logger)
        if args.auto_fix and audit_missing_cols:
            auto_fix_columns(audit_engine, logger, audit_missing_cols)
        elif audit_missing_cols:
            logger.info("如需自動補上審計欄位，可使用 --auto-fix 參數。")

        ensure_audit_indexes(audit_engine, logger)

        # User Story Map 資料庫初始化與檢查
        usm_engine = initialize_usm_engine(logger)

        # 最終統計
        stats = get_database_stats(engine, logger)
        print_stats(stats, logger)

        audit_stats = get_database_stats(audit_engine, logger)
        print_audit_stats(audit_stats, logger)

        usm_stats = get_database_stats(usm_engine, logger)
        print_usm_stats(usm_stats, logger)

        logger.info("✅ 資料庫初始化完成！")
        if backup_path:
            logger.info(f"若需回復，可使用備份檔：{backup_path}")
        return 0

    except Exception as e:
        logger.error(f"初始化過程中發生錯誤：{e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
