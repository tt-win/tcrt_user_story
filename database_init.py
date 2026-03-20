#!/usr/bin/env python3
"""
資料庫 bootstrap 腳本。

職責：
- 透過 Alembic 將主資料庫升級到最新 schema
- 必要時自動建立缺少的 MySQL / PostgreSQL database
- 對既有未納管資料庫提供顯式 adoption / validation 流程
- 輸出主資料庫統計資訊
- 檢查系統是否已有 super_admin，若沒有則提示走 first-login setup

注意：
- schema 建立與變更已完全交給 Alembic 管理
- 本腳本不再執行手刻的 CREATE TABLE / ALTER TABLE / 資料搬移修補
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).parent))

from app.auth.models import UserRole
from app.db_migrations import (
    adopt_legacy_audit_database,
    collect_target_preflight,
    collect_target_verification_summary,
    create_database_if_missing,
    LegacyDatabaseAdoptionRequiredError,
    LegacyDatabaseValidationError,
    adopt_legacy_main_database,
    adopt_legacy_usm_database,
    get_sync_engine_for_target,
    upgrade_audit_database,
    upgrade_main_database,
    upgrade_usm_database,
    validate_legacy_audit_database,
    validate_legacy_main_database,
    validate_legacy_usm_database,
)
from app.auth.models import UserCreate
from app.services.user_service import UserService
from app.models.database_models import User
MAIN_REQUIRED_TABLES: List[str] = [
    "users",
    "user_team_permissions",
    "active_sessions",
    "password_reset_tokens",
    "mcp_machine_credentials",
    "teams",
    "test_cases",
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
    "ai_tc_helper_sessions",
    "ai_tc_helper_drafts",
    "ai_tc_helper_stage_metrics",
    "lark_departments",
    "lark_users",
    "sync_history",
]
TARGET_LABELS = {
    "main": "主資料庫",
    "audit": "audit 資料庫",
    "usm": "USM 資料庫",
}
TARGET_REQUIRED_TABLES = {
    "main": MAIN_REQUIRED_TABLES,
    "audit": ["audit_logs"],
    "usm": ["user_story_maps", "user_story_map_nodes"],
}
TARGET_CRITICAL_TABLES = {
    "main": ["users", "teams", "test_cases"],
    "audit": ["audit_logs"],
    "usm": ["user_story_maps", "user_story_map_nodes"],
}
TARGET_VALIDATORS = {
    "main": validate_legacy_main_database,
    "audit": validate_legacy_audit_database,
    "usm": validate_legacy_usm_database,
}
TARGET_ADOPTERS = {
    "main": adopt_legacy_main_database,
    "audit": adopt_legacy_audit_database,
    "usm": adopt_legacy_usm_database,
}
TARGET_UPGRADERS = {
    "main": upgrade_main_database,
    "audit": upgrade_audit_database,
    "usm": upgrade_usm_database,
}
MIGRATION_ORDER = ("main", "audit", "usm")


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


def is_sqlite(engine: Engine) -> bool:
    return str(engine.dialect.name or "").lower() == "sqlite"


def quote_ident(engine: Engine, name: str) -> str:
    return engine.dialect.identifier_preparer.quote(name)


def backup_sqlite_if_needed(engine: Engine, logger: Logger, label: str) -> Optional[str]:
    if not is_sqlite(engine):
        logger.debug(f"{label} 非 SQLite，略過備份")
        return None

    db_path = engine.url.database
    if not db_path or db_path == ":memory:":
        logger.debug(f"{label} 為 SQLite 記憶體資料庫，略過備份")
        return None

    if not Path(db_path).exists():
        logger.debug(f"{label} 的 SQLite 檔案不存在，略過備份：{db_path}")
        return None

    backup_path = Path(
        f"backup_{engine.url.database and Path(engine.url.database).stem or 'db'}_"
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    )
    try:
        shutil.copy2(db_path, backup_path)
        logger.info(f"已建立 {label} SQLite 備份：{backup_path}")
        return str(backup_path)
    except Exception as exc:
        logger.warn(f"建立 {label} SQLite 備份失敗（不中斷）：{exc}")
        return None


def verify_required_tables(
    engine: Engine,
    logger: Logger,
    required_tables: List[str],
    label: str,
) -> Tuple[bool, List[str]]:
    inspector = inspect(engine)
    existing = {name.lower() for name in inspector.get_table_names()}
    missing = [name for name in required_tables if name.lower() not in existing]
    if missing:
        logger.error(f"{label} 缺少重要表：{missing}")
        return False, missing
    logger.debug(f"{label} 所有重要表皆存在")
    return True, []


def get_database_stats(engine: Engine) -> Dict[str, Any]:
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    stats: Dict[str, Any] = {
        "engine_url": str(engine.url),
        "total_tables": len(table_names),
        "tables": {},
    }

    with engine.connect() as conn:
        for table_name in table_names:
            try:
                row_count = conn.execute(
                    text(f"SELECT COUNT(*) FROM {quote_ident(engine, table_name)}")
                ).scalar()
                stats["tables"][table_name] = {
                    "rows": int(row_count or 0),
                    "columns": len(inspector.get_columns(table_name)),
                }
            except Exception as exc:
                stats["tables"][table_name] = {"error": str(exc)}

    return stats


def print_stats(stats: Dict[str, Any], title: str) -> None:
    print("=" * 60)
    print(f"📊 {title}統計摘要")
    print("=" * 60)
    print(f"總表格數：{stats.get('total_tables', 0)}")
    for table_name, payload in sorted((stats.get("tables") or {}).items()):
        if "error" in payload:
            print(f"  ❌ {table_name}: {payload['error']}")
            continue
        print(f"  ✅ {table_name}: {payload['rows']} 筆記錄, {payload['columns']} 欄位")
    print()
    print(f"📂 資料庫位置：{stats.get('engine_url')}")


def _selected_targets(target_name: str) -> Tuple[str, ...]:
    if target_name == "all":
        return MIGRATION_ORDER
    return (target_name,)


def print_preflight_summary(summary: Dict[str, Any]) -> None:
    print("=" * 60)
    print(f"🔎 Preflight: {summary['label']}")
    print("=" * 60)
    print(f"target: {summary['target']}")
    print(f"status: {summary['status']}")
    print(f"ready: {'yes' if summary['ready'] else 'no'}")
    print(f"async_url: {summary['async_url']}")
    print(f"sync_url: {summary['sync_url']}")
    print(f"database_state: {summary['database_state']}")
    print(f"head_revision: {summary['head_revision']}")
    print(f"current_revision: {summary['current_revision']}")
    print("drivers:")
    for driver_status in summary["driver_statuses"]:
        flag = "OK" if driver_status["available"] else "MISSING"
        print(
            f"  - {driver_status['package']} ({driver_status['import_name']}): {flag}"
        )
    for remediation in summary.get("remediation", []):
        print(f"remediation: {remediation}")
    if summary.get("error"):
        print(f"error: {summary['error']}")
    print()


def print_verification_summary(summary: Dict[str, Any]) -> None:
    print("=" * 60)
    print(f"✅ Verification: {summary['label']}")
    print("=" * 60)
    print(f"target: {summary['target']}")
    print(f"ready: {'yes' if summary['ready'] else 'no'}")
    print(f"database_state: {summary['database_state']}")
    print(f"head_revision: {summary['head_revision']}")
    print(f"current_revision: {summary['current_revision']}")
    print(f"total_tables: {summary['total_tables']}")
    print("required_tables:")
    for table_name, exists in summary["required_tables"].items():
        print(f"  - {table_name}: {'OK' if exists else 'MISSING'}")
    print("critical_row_counts:")
    for table_name, row_count in summary["critical_row_counts"].items():
        printable = row_count if row_count is not None else "N/A"
        print(f"  - {table_name}: {printable}")
    print()


def validate_legacy_target(target_name: str, logger: Logger) -> int:
    label = TARGET_LABELS[target_name]
    diff_messages = TARGET_VALIDATORS[target_name]()
    if diff_messages:
        logger.error(f"既有{label}無法安全納入 Alembic baseline：")
        for message in diff_messages:
            logger.error(f"  - {message}")
        return 4
    logger.info(f"既有{label} schema 與 baseline 一致，可安全執行 adoption")
    return 0


def adopt_legacy_target(target_name: str, logger: Logger, no_backup: bool) -> int:
    label = TARGET_LABELS[target_name]
    engine = get_sync_engine_for_target(target_name)
    try:
        if not no_backup:
            backup_sqlite_if_needed(engine, logger, label)
        baseline_revision = TARGET_ADOPTERS[target_name]()
        logger.info(f"已將既有{label}納入 Alembic 管理，baseline={baseline_revision}")
        if target_name == "main":
            ensure_super_admin_seed(engine, logger)
        print_verification_summary(
            collect_target_verification_summary(
                target_name,
                required_tables=TARGET_REQUIRED_TABLES[target_name],
                critical_tables=TARGET_CRITICAL_TABLES[target_name],
            )
        )
        return 0
    finally:
        engine.dispose()


def bootstrap_target(target_name: str, logger: Logger, no_backup: bool) -> Tuple[Engine, Optional[str]]:
    label = TARGET_LABELS[target_name]
    engine = get_sync_engine_for_target(target_name)
    try:
        logger.info(f"偵測到{label}：{engine.dialect.name} | URL={engine.url}")
        if create_database_if_missing(engine.url):
            logger.info(f"已建立 {label} database：{engine.url.database}")

        backup_path = None
        if not no_backup:
            backup_path = backup_sqlite_if_needed(engine, logger, label)

        logger.info(f"執行 {label} Alembic migration：upgrade head")
        TARGET_UPGRADERS[target_name]()

        ok, _missing = verify_required_tables(
            engine,
            logger,
            TARGET_REQUIRED_TABLES[target_name],
            label,
        )
        if not ok:
            raise RuntimeError(f"{label} migration 完成後仍缺少重要表")

        logger.info(f"✅ {label} bootstrap 完成")
        print_verification_summary(
            collect_target_verification_summary(
                target_name,
                required_tables=TARGET_REQUIRED_TABLES[target_name],
                critical_tables=TARGET_CRITICAL_TABLES[target_name],
            )
        )
        return engine, backup_path
    except Exception:
        engine.dispose()
        raise


def run_preflight(target_name: str, logger: Logger, json_output: bool) -> int:
    summaries: List[Dict[str, Any]] = []
    for current_target in _selected_targets(target_name):
        summary = collect_target_preflight(current_target)
        summaries.append(summary)
        if not json_output:
            print_preflight_summary(summary)
        if not summary["ready"]:
            if json_output:
                print(
                    json.dumps(
                        {"targets": summaries},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            return 5

    if json_output:
        print(json.dumps({"targets": summaries}, ensure_ascii=False, indent=2))
    logger.info("✅ preflight 全部通過")
    return 0


def run_verification(target_name: str, json_output: bool) -> int:
    summaries = [
        collect_target_verification_summary(
            current_target,
            required_tables=TARGET_REQUIRED_TABLES[current_target],
            critical_tables=TARGET_CRITICAL_TABLES[current_target],
        )
        for current_target in _selected_targets(target_name)
    ]

    if json_output:
        print(json.dumps({"targets": summaries}, ensure_ascii=False, indent=2))
    else:
        for summary in summaries:
            print_verification_summary(summary)

    return 0 if all(summary["ready"] for summary in summaries) else 6


def _load_super_admin_seed_config() -> Optional[Dict[str, str]]:
    username = str(os.getenv("BOOTSTRAP_SUPER_ADMIN_USERNAME", "")).strip()
    password = os.getenv("BOOTSTRAP_SUPER_ADMIN_PASSWORD", "")
    full_name = str(os.getenv("BOOTSTRAP_SUPER_ADMIN_FULL_NAME", "")).strip()
    email = str(os.getenv("BOOTSTRAP_SUPER_ADMIN_EMAIL", "")).strip()

    if not username and not password:
        return None
    if not username or not password:
        raise RuntimeError(
            "若要建立預設 super_admin，必須同時設定 "
            "BOOTSTRAP_SUPER_ADMIN_USERNAME 與 BOOTSTRAP_SUPER_ADMIN_PASSWORD"
        )

    return {
        "username": username,
        "password": password,
        "full_name": full_name,
        "email": email,
    }


def ensure_super_admin_seed(engine: Engine, logger: Logger) -> Dict[str, Any]:
    inspector = inspect(engine)
    if "users" not in {name.lower() for name in inspector.get_table_names()}:
        return {
            "super_admin_count": 0,
            "needs_first_login_setup": True,
        }

    seed_config = _load_super_admin_seed_config()

    with Session(engine) as session:
        super_admin_count = (
            session.query(User)
            .filter(User.role == UserRole.SUPER_ADMIN.value)
            .filter(User.is_active == True)
            .count()
        )

        if super_admin_count == 0 and seed_config:
            logger.info(
                "偵測到 BOOTSTRAP_SUPER_ADMIN_* 環境變數，建立第一個 super_admin"
            )
            new_user = UserService.create_user(
                UserCreate(
                    username=seed_config["username"],
                    password=seed_config["password"],
                    email=seed_config["email"] or None,
                    full_name=seed_config["full_name"] or None,
                    role=UserRole.SUPER_ADMIN,
                    primary_team_id=None,
                    is_active=True,
                ),
                db=session,
            )
            new_user.last_login_at = datetime.utcnow()
            session.add(new_user)
            session.commit()
            super_admin_count = 1
            logger.info(f"已建立預設 super_admin：{new_user.username}")

    seed_state = {
        "super_admin_count": int(super_admin_count or 0),
        "needs_first_login_setup": int(super_admin_count or 0) == 0,
    }

    if seed_state["needs_first_login_setup"]:
        logger.warn(
            "尚未建立任何 super_admin。系統目前採 first-login setup 流程，"
            "請於啟動後完成 /first-login-setup。"
        )
    else:
        logger.info(f"已存在 {seed_state['super_admin_count']} 個啟用中的 super_admin")

    return seed_state


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="資料庫 bootstrap 腳本")
    parser.add_argument(
        "--auto-fix",
        action="store_true",
        help="相容舊流程的保留參數；schema 修補已改由 Alembic 管理",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="SQLite 模式下跳過 migration 前備份",
    )
    parser.add_argument(
        "--stats-only",
        action="store_true",
        help="僅輸出資料庫統計與初始化狀態，不執行 migration",
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="檢查 target database 的 driver、URL、Alembic 狀態與 legacy adoption 狀態",
    )
    parser.add_argument(
        "--preflight-target",
        choices=["all", *MIGRATION_ORDER],
        default="all",
        help="搭配 --preflight 使用；預設檢查 main、audit、usm 三套資料庫",
    )
    parser.add_argument(
        "--verify-target",
        choices=["all", *MIGRATION_ORDER],
        help="輸出指定 target 的 revision、required tables 與關鍵 row count 驗證摘要",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="搭配 --preflight 或 --verify-target 使用 JSON 輸出",
    )
    parser.add_argument(
        "--skip-migrations",
        action="store_true",
        help="假設 Alembic 已由外部流程執行，只做 bootstrap 檢查",
    )
    parser.add_argument(
        "--validate-legacy-main-db",
        action="store_true",
        help="檢查既有未納管主庫是否可安全納入 Alembic baseline",
    )
    parser.add_argument(
        "--adopt-legacy-main-db",
        action="store_true",
        help="驗證既有未納管主庫後，明確寫入 Alembic baseline version",
    )
    parser.add_argument(
        "--validate-legacy-audit-db",
        action="store_true",
        help="檢查既有未納管 audit 資料庫是否可安全納入 Alembic baseline",
    )
    parser.add_argument(
        "--adopt-legacy-audit-db",
        action="store_true",
        help="驗證既有未納管 audit 資料庫後，明確寫入 Alembic baseline version",
    )
    parser.add_argument(
        "--validate-legacy-usm-db",
        action="store_true",
        help="檢查既有未納管 USM 資料庫是否可安全納入 Alembic baseline",
    )
    parser.add_argument(
        "--adopt-legacy-usm-db",
        action="store_true",
        help="驗證既有未納管 USM 資料庫後，明確寫入 Alembic baseline version",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--verbose", action="store_true", help="輸出更多詳細資訊")
    group.add_argument("--quiet", action="store_true", help="僅輸出必要資訊與錯誤")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    logger = Logger(verbose=args.verbose, quiet=args.quiet)

    print("=" * 60)
    print("🗃️  資料庫 Bootstrap 系統（Alembic）")
    print("=" * 60)

    try:
        if args.stats_only:
            for target_name in MIGRATION_ORDER:
                engine = get_sync_engine_for_target(target_name)
                try:
                    stats = get_database_stats(engine)
                    print_stats(stats, TARGET_LABELS[target_name])
                    if target_name == "main":
                        ensure_super_admin_seed(engine, logger)
                finally:
                    engine.dispose()
            return 0

        if args.preflight:
            return run_preflight(args.preflight_target, logger, args.json)

        if args.verify_target:
            return run_verification(args.verify_target, args.json)

        if args.validate_legacy_main_db:
            return validate_legacy_target("main", logger)

        if args.adopt_legacy_main_db:
            return adopt_legacy_target("main", logger, args.no_backup)

        if args.validate_legacy_audit_db:
            return validate_legacy_target("audit", logger)

        if args.adopt_legacy_audit_db:
            return adopt_legacy_target("audit", logger, args.no_backup)

        if args.validate_legacy_usm_db:
            return validate_legacy_target("usm", logger)

        if args.adopt_legacy_usm_db:
            return adopt_legacy_target("usm", logger, args.no_backup)

        if args.auto_fix:
            logger.info("--auto-fix 已退役；schema 變更現在由 Alembic 管理")

        if args.skip_migrations:
            logger.info("略過 Alembic migration，僅執行 bootstrap 檢查")
            for target_name in MIGRATION_ORDER:
                engine = get_sync_engine_for_target(target_name)
                try:
                    ok, _missing = verify_required_tables(
                        engine,
                        logger,
                        TARGET_REQUIRED_TABLES[target_name],
                        TARGET_LABELS[target_name],
                    )
                    if not ok:
                        logger.error(f"{TARGET_LABELS[target_name]} bootstrap 檢查未通過")
                        return 2
                    if target_name == "main":
                        ensure_super_admin_seed(engine, logger)
                finally:
                    engine.dispose()
        else:
            backup_paths: Dict[str, Optional[str]] = {}
            main_engine: Optional[Engine] = None
            aux_engines: List[Engine] = []
            try:
                for target_name in MIGRATION_ORDER:
                    engine, backup_path = bootstrap_target(target_name, logger, args.no_backup)
                    backup_paths[target_name] = backup_path
                    if target_name == "main":
                        main_engine = engine
                    else:
                        aux_engines.append(engine)

                if main_engine is None:
                    raise RuntimeError("主資料庫 bootstrap 未建立 engine")

                stats = get_database_stats(main_engine)
                print_stats(stats, TARGET_LABELS["main"])
                ensure_super_admin_seed(main_engine, logger)
            finally:
                if main_engine is not None:
                    main_engine.dispose()
                for engine in aux_engines:
                    engine.dispose()

            for target_name, backup_path in backup_paths.items():
                if backup_path:
                    logger.info(f"{TARGET_LABELS[target_name]} 如需回復，可使用備份檔：{backup_path}")
            logger.info("✅ 所有資料庫 bootstrap 完成")
        return 0
    except LegacyDatabaseAdoptionRequiredError as exc:
        logger.error(str(exc))
        return 3
    except LegacyDatabaseValidationError as exc:
        logger.error(str(exc))
        return 4
    except Exception as exc:
        logger.error(f"初始化過程中發生錯誤：{exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
