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
import base64
import binascii
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).parent))

from app.auth.models import UserRole
from app.db_backup import (
    BackupError,
    BackupResult,
    apply_retention,
    clear_all_failure_markers,
    clear_failure_marker,
    create_backup,
    read_failure_marker,
    record_upgrade_failure,
    restore_backup,
)
from app.db_migrations import (
    adopt_legacy_audit_database,
    collect_target_preflight,
    collect_target_verification_summary,
    create_database_if_missing,
    get_head_revision,
    get_migration_target,
    get_pending_status,
    LegacyDatabaseAdoptionRequiredError,
    LegacyDatabaseValidationError,
    adopt_legacy_main_database,
    adopt_legacy_usm_database,
    get_sync_engine_for_target,
    resolve_database_url,
    upgrade_audit_database,
    upgrade_legacy_audit_database,
    upgrade_legacy_main_database,
    upgrade_legacy_usm_database,
    upgrade_main_database,
    upgrade_usm_database,
    validate_legacy_audit_database,
    validate_legacy_main_database,
    validate_legacy_usm_database,
)
from app.db_types import MediumText
from app.db_url import normalize_sync_database_url
from app.auth.models import UserCreate
from app.services.user_service import UserService
from app.models.database_models import User

MAIN_REQUIRED_TABLES: List[str] = [
    "users",
    "user_team_permissions",
    "active_sessions",
    "password_reset_tokens",
    "mcp_machine_credentials",
    "team_app_tokens",
    "app_token_pins",
    "team_automation_providers",
    "system_automation_providers",
    "automation_scripts",
    "automation_script_groups",
    "automation_script_case_links",
    "automation_environments",
    "automation_environment_params",
    "automation_script_env_vars",
    "automation_runs",
    "automation_webhooks",
    "automation_webhook_deliveries",
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
    "qa_ai_helper_sessions",
    "qa_ai_helper_ticket_snapshots",
    "qa_ai_helper_requirement_plans",
    "qa_ai_helper_plan_sections",
    "qa_ai_helper_verification_items",
    "qa_ai_helper_check_conditions",
    "qa_ai_helper_seed_sets",
    "qa_ai_helper_seed_items",
    "qa_ai_helper_testcase_draft_sets",
    "qa_ai_helper_testcase_drafts",
    "qa_ai_helper_telemetry_events",
    "qa_ai_helper_commit_links",
    "lark_departments",
    "lark_users",
    "sync_history",
    "scheduled_services",
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
TARGET_LEGACY_UPGRADERS = {
    "main": upgrade_legacy_main_database,
    "audit": upgrade_legacy_audit_database,
    "usm": upgrade_legacy_usm_database,
}

_VALID_BACKUP_MODES = {"required", "best-effort", "off"}
_VALID_ON_FAILURE_MODES = {"abort", "rollback"}


@dataclass(frozen=True)
class BootstrapPolicies:
    backup_dir: Path
    backup_mode: str
    backup_retention: int
    on_failure: str
    max_upgrade_attempts: int


class BootstrapTargetFailure(Exception):
    """單一 target 的升版或升版後驗證失敗；攜帶 main() 執行回退所需的資訊。"""

    def __init__(
        self,
        target_name: str,
        head: str,
        from_revision: Optional[str],
        backup: Optional[BackupResult],
        reason: str,
    ) -> None:
        super().__init__(reason)
        self.target_name = target_name
        self.head = head
        self.from_revision = from_revision
        self.backup = backup
        self.reason = reason


def _default_backup_dir() -> Path:
    raw = os.getenv("BOOTSTRAP_BACKUP_DIR")
    return Path(raw) if raw else (Path(__file__).resolve().parent / "db_backups")


def read_bootstrap_policies(*, no_backup_flag: bool) -> BootstrapPolicies:
    backup_mode = os.getenv("BOOTSTRAP_BACKUP_MODE", "required").strip().lower()
    if backup_mode not in _VALID_BACKUP_MODES:
        raise RuntimeError(
            f"BOOTSTRAP_BACKUP_MODE={backup_mode!r} 不合法，需為 {sorted(_VALID_BACKUP_MODES)} 其一"
        )
    if no_backup_flag:
        backup_mode = "off"

    retention_raw = os.getenv("BOOTSTRAP_BACKUP_RETENTION", "5").strip()
    try:
        backup_retention = int(retention_raw)
    except ValueError as exc:
        raise RuntimeError(f"BOOTSTRAP_BACKUP_RETENTION={retention_raw!r} 必須是整數") from exc
    if backup_retention < 1:
        raise RuntimeError(f"BOOTSTRAP_BACKUP_RETENTION={backup_retention} 必須 >= 1")

    on_failure = os.getenv("BOOTSTRAP_ON_FAILURE", "abort").strip().lower()
    if on_failure not in _VALID_ON_FAILURE_MODES:
        raise RuntimeError(
            f"BOOTSTRAP_ON_FAILURE={on_failure!r} 不合法，需為 {sorted(_VALID_ON_FAILURE_MODES)} 其一"
        )

    attempts_raw = os.getenv("BOOTSTRAP_MAX_UPGRADE_ATTEMPTS", "3").strip()
    try:
        max_upgrade_attempts = int(attempts_raw)
    except ValueError as exc:
        raise RuntimeError(f"BOOTSTRAP_MAX_UPGRADE_ATTEMPTS={attempts_raw!r} 必須是整數") from exc
    if max_upgrade_attempts < 1:
        raise RuntimeError(f"BOOTSTRAP_MAX_UPGRADE_ATTEMPTS={max_upgrade_attempts} 必須 >= 1")

    return BootstrapPolicies(
        backup_dir=_default_backup_dir(),
        backup_mode=backup_mode,
        backup_retention=backup_retention,
        on_failure=on_failure,
        max_upgrade_attempts=max_upgrade_attempts,
    )


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


def quote_ident(engine: Engine, name: str) -> str:
    return engine.dialect.identifier_preparer.quote(name)


def _legacy_backup(target_name: str, database_url: str, logger: Logger, label: str, *, to_revision: str) -> None:
    """既有未納管資料庫的 adopt/upgrade 專用備份：一律嘗試（不看 pending），失敗不中斷流程。"""
    try:
        result = create_backup(
            target_name,
            database_url=database_url,
            from_revision=None,
            to_revision=to_revision,
            backup_dir=_default_backup_dir(),
        )
        logger.info(f"已建立 {label} 備份：{result.path}")
    except BackupError as exc:
        logger.warn(f"建立 {label} 備份失敗（不中斷）：{exc}")


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


def verify_large_text_columns(
    engine: Engine,
    target_name: str,
    logger: Logger,
    label: str,
) -> Tuple[bool, List[str]]:
    """引擎對稱檢查：model 端宣告為可攜大型文字型別（``app.db_types.MediumText``）的欄位，
    在 MySQL 上的實際物理型別必須是 MEDIUMTEXT/LONGTEXT。

    取代舊有 verify_mysql_mediumtext_defaults：舊版對 DB 內「任何」Text-affinity 欄位一視同仁，
    本版改以 model metadata 為準，只檢查 model 明確宣告為 MediumText 的欄位，避免誤判本來就
    設計為一般 TEXT 的欄位；SQLite/PostgreSQL 的 TEXT 無容量分級問題，此檢查在該二引擎上恆為
    no-op（迴圈執行但不會有違規），不需要為其硬編碼特例。

    刻意不採用 Alembic `compare_metadata` 做全表結構比對：目前 schema 與 model 之間存在其他
    既有、與大型文字型別無關的歷史落差（見 make-schema-engine-portable 的驗證紀錄），若在開機
    路徑加入無範圍限縮的全量 drift gate 會讓現有部署直接無法啟動。
    """
    if str(engine.dialect.name or "").lower() != "mysql":
        return True, []

    target = get_migration_target(target_name)
    inspector = inspect(engine)
    existing_tables = {name.lower() for name in inspector.get_table_names()}
    violations: List[str] = []
    for table in target.metadata.tables.values():
        if table.name.lower() not in existing_tables:
            continue
        actual_columns = {column["name"]: column for column in inspector.get_columns(table.name)}
        for column in table.columns:
            if not isinstance(column.type, MediumText):
                continue
            actual = actual_columns.get(column.name)
            if actual is None:
                continue
            actual_type_name = getattr(actual["type"].__class__, "__name__", "").upper()
            if actual_type_name not in {"MEDIUMTEXT", "LONGTEXT"}:
                violations.append(f"{table.name}.{column.name}={actual_type_name or 'TEXT'}")

    if violations:
        logger.error(f"{label} 存在未升級為 MEDIUMTEXT 的可攜文字欄位：{violations}")
        return False, violations

    logger.debug(f"{label} 可攜大型文字欄位皆為 MEDIUMTEXT/LONGTEXT（或非 MySQL，無需檢查）")
    return True, []


def verify_automation_provider_encryption_key(engine: Engine, logger: Logger) -> Tuple[bool, str | None]:
    inspector = inspect(engine, raiseerr=False)
    if inspector is None:
        logger.debug("略過 Automation provider encryption key 檢查：engine 不支援 inspect")
        return True, None
    existing = {name.lower() for name in inspector.get_table_names()}

    # The key is required once any encrypted secret exists at rest: provider
    # credentials, or automation environment/script secret values.
    needs_key = False
    with engine.connect() as conn:
        if "team_automation_providers" in existing:
            provider_count = conn.execute(
                text(f"SELECT COUNT(*) FROM {quote_ident(engine, 'team_automation_providers')}")
            ).scalar()
            if int(provider_count or 0) > 0:
                needs_key = True
        for secret_table in ("automation_environment_params", "automation_script_env_vars"):
            if needs_key:
                break
            if secret_table in existing:
                secret_count = conn.execute(
                    text(
                        f"SELECT COUNT(*) FROM {quote_ident(engine, secret_table)} "
                        "WHERE value_encrypted IS NOT NULL"
                    )
                ).scalar()
                if int(secret_count or 0) > 0:
                    needs_key = True

    if not needs_key:
        return True, None

    from app.config import get_settings

    key = (get_settings().automation_provider.encryption_key or "").strip()
    if not key:
        message = (
            "team_automation_providers 或 automation 環境設定已有加密資料，但缺少 automation provider encryption key。"
            "請於 config.yaml 設定 automation_provider.encryption_key，"
            "或匯出環境變數 AUTOMATION_PROVIDER_ENCRYPTION_KEY；"
            "金鑰需為 base64-encoded 32 bytes，例如："
            "python -c \"import secrets,base64;print(base64.b64encode(secrets.token_bytes(32)).decode())\""
        )
        logger.error(message)
        return False, message

    try:
        decoded = base64.b64decode(key, validate=True)
    except (binascii.Error, ValueError) as exc:
        message = f"AUTOMATION_PROVIDER_ENCRYPTION_KEY 不是有效 base64：{exc}"
        logger.error(message)
        return False, message

    if len(decoded) != 32:
        message = "AUTOMATION_PROVIDER_ENCRYPTION_KEY 必須解碼為 32 bytes，才能用於 AES-256-GCM"
        logger.error(message)
        return False, message

    logger.debug("Automation provider encryption key 檢查通過")
    return True, None


def _run_verification_chain(
    engine: Engine,
    logger: Logger,
    target_name: str,
    label: str,
) -> Tuple[bool, Optional[str]]:
    """既有表 + 大型文字型別（MySQL MEDIUMTEXT）+ （main）automation key 的共用驗證鏈。"""
    ok, _missing = verify_required_tables(engine, logger, TARGET_REQUIRED_TABLES[target_name], label)
    if not ok:
        return False, f"{label} 仍缺少重要表"

    text_ok, _violations = verify_large_text_columns(engine, target_name, logger, label)
    if not text_ok:
        return False, f"{label} 存在未升級為 MEDIUMTEXT 的可攜文字欄位"

    if target_name == "main":
        automation_key_ok, _error = verify_automation_provider_encryption_key(engine, logger)
        if not automation_key_ok:
            return False, "Automation provider credential encryption key 檢查失敗"

    return True, None


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
                row_count = conn.execute(text(f"SELECT COUNT(*) FROM {quote_ident(engine, table_name)}")).scalar()
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
        print(f"  - {driver_status['package']} ({driver_status['import_name']}): {flag}")
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
    database_url = resolve_database_url(target_name)
    engine = get_sync_engine_for_target(target_name, database_url=database_url)
    try:
        if not no_backup:
            _legacy_backup(target_name, database_url, logger, label, to_revision="legacy-baseline-adoption")
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


def upgrade_legacy_target(target_name: str, logger: Logger, no_backup: bool) -> int:
    label = TARGET_LABELS[target_name]
    database_url = resolve_database_url(target_name)
    engine = get_sync_engine_for_target(target_name, database_url=database_url)
    try:
        if not no_backup:
            _legacy_backup(target_name, database_url, logger, label, to_revision="legacy-auto-upgrade")

        detected_rev, final_rev = TARGET_LEGACY_UPGRADERS[target_name]()
        logger.info(
            f"已將既有{label}從偵測到的版本 {detected_rev} 升級至 {final_rev}"
        )

        ok, missing = verify_required_tables(
            engine,
            logger,
            TARGET_REQUIRED_TABLES[target_name],
            label,
        )
        if not ok:
            logger.error(f"{label} 升級完成但仍缺少表：{missing}")
            return 7

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


def bootstrap_target(
    target_name: str,
    logger: Logger,
    policies: BootstrapPolicies,
) -> Tuple[Engine, Optional[BackupResult]]:
    """執行單一 target 的 bootstrap：偵測 pending → （視需要）備份 → 升版 → 驗證。

    失敗時一律拋出 ``BootstrapTargetFailure``（攜帶 target/head/backup 供 main() 判斷是否回退），
    不在此處處理跨 target 回退——回退需要 main() 手上其他 target 已建立的備份清單。
    """
    label = TARGET_LABELS[target_name]
    engine = get_sync_engine_for_target(target_name)
    try:
        logger.info(f"偵測到{label}：{engine.dialect.name} | URL={engine.url}")
        if create_database_if_missing(engine.url):
            logger.info(f"已建立 {label} database：{engine.url.database}")

        database_url = engine.url.render_as_string(hide_password=False)
        pending = get_pending_status(target_name, database_url=database_url)
        logger.info(
            f"{label} pending 檢查：current={pending.current} head={pending.head} "
            f"pending={pending.is_pending} fresh={pending.is_fresh}"
        )

        if not pending.is_pending:
            logger.info(f"{label} 已是最新版本，略過備份與升版，僅執行驗證")
            ok, error = _run_verification_chain(engine, logger, target_name, label)
            if not ok:
                raise BootstrapTargetFailure(target_name, pending.head, pending.current, None, error)
            print_verification_summary(
                collect_target_verification_summary(
                    target_name,
                    required_tables=TARGET_REQUIRED_TABLES[target_name],
                    critical_tables=TARGET_CRITICAL_TABLES[target_name],
                )
            )
            return engine, None

        backup_result: Optional[BackupResult] = None
        # Temporarily disabled: skip pre-upgrade DB backup during bootstrap.
        # Restore this block when backup is needed again.
        logger.info(f"{label} 升版前備份已暫時停用，略過備份直接升版")
        # if pending.is_fresh:
        #     logger.debug(f"{label} 為全新資料庫，略過升版前備份")
        # elif policies.backup_mode == "off":
        #     logger.info(f"{label} 備份政策為 off，略過升版前備份")
        # else:
        #     try:
        #         backup_result = create_backup(
        #             target_name,
        #             database_url=database_url,
        #             from_revision=pending.current,
        #             to_revision=pending.head,
        #             backup_dir=policies.backup_dir,
        #         )
        #         logger.info(f"已建立 {label} 升版前備份：{backup_result.path}")
        #     except BackupError as exc:
        #         if policies.backup_mode == "required":
        #             raise BootstrapTargetFailure(
        #                 target_name, pending.head, pending.current, None, f"升版前備份失敗：{exc}"
        #             ) from exc
        #         logger.warn(f"{label} 升版前備份失敗（best-effort，繼續升版）：{exc}")

        logger.info(f"執行 {label} Alembic migration：upgrade head")
        try:
            try:
                TARGET_UPGRADERS[target_name]()
            except LegacyDatabaseAdoptionRequiredError:
                logger.info(
                    f"偵測到{label}尚未納入 Alembic 版控，"
                    "改為自動偵測 schema 版本、stamp baseline 後升級至 head"
                )
                detected_rev, final_rev = TARGET_LEGACY_UPGRADERS[target_name]()
                logger.info(
                    f"已自動將{label}從偵測到的版本 {detected_rev} 升級至 {final_rev}"
                )
        except Exception as exc:
            raise BootstrapTargetFailure(
                target_name, pending.head, pending.current, backup_result, str(exc)
            ) from exc

        ok, error = _run_verification_chain(engine, logger, target_name, label)
        if not ok:
            raise BootstrapTargetFailure(target_name, pending.head, pending.current, backup_result, error)

        logger.info(f"✅ {label} bootstrap 完成")
        print_verification_summary(
            collect_target_verification_summary(
                target_name,
                required_tables=TARGET_REQUIRED_TABLES[target_name],
                critical_tables=TARGET_CRITICAL_TABLES[target_name],
            )
        )
        return engine, backup_result
    except Exception:
        engine.dispose()
        raise


def _handle_bootstrap_failure(
    failure: BootstrapTargetFailure,
    upgraded: List[BackupResult],
    policies: BootstrapPolicies,
    logger: Logger,
) -> int:
    """依 BOOTSTRAP_ON_FAILURE 政策處理單一 target 的升版失敗：abort 或 rollback。

    rollback 還原「本次已成功 target 的備份」＋「失敗 target 自己的備份（若有）」，
    反序執行；若失敗 target 本身無備份（fresh 資料庫或 best-effort 備份失敗），
    該 target 自身不還原，但仍會還原其他已成功 target，以維持三庫一致、可換回舊版 image。
    """
    label = TARGET_LABELS[failure.target_name]
    logger.error(f"{label} bootstrap 失敗：{failure.reason}")

    restorable: List[BackupResult] = list(upgraded)
    if failure.backup is not None:
        restorable.append(failure.backup)

    if policies.on_failure != "rollback" or not restorable:
        if policies.on_failure == "rollback" and not restorable:
            logger.error("回退政策為 rollback，但沒有任何可用備份可還原（fresh 資料庫或 best-effort 備份失敗），視同 abort")
        record_upgrade_failure(
            policies.backup_dir,
            failure.target_name,
            head=failure.head,
            from_revision=failure.from_revision,
            error=failure.reason,
            rolled_back=False,
        )
        return 1

    if failure.backup is None:
        logger.warn(
            f"{label} 沒有備份可還原（fresh 資料庫或備份失敗），其目前狀態可能不完整，"
            "請人工檢查或視需要清空後重新啟動 bootstrap。"
        )

    logger.info(f"BOOTSTRAP_ON_FAILURE=rollback：開始還原 {len(restorable)} 個 target 至升版前狀態")
    try:
        for result in reversed(restorable):
            # resolve_database_url 回傳 async URL；備份/還原走 sync engine，需正規化為 sync driver。
            restore_url = normalize_sync_database_url(resolve_database_url(result.target))
            restore_backup(result, database_url=restore_url)
            logger.info(f"{TARGET_LABELS[result.target]} 已還原至升版前狀態（備份：{result.path}）")
    except Exception as restore_exc:  # noqa: BLE001
        logger.error(
            f"回退還原失敗，需人工介入：{restore_exc}\n"
            f"備份檔位置：{[str(r.path) for r in restorable]}"
        )
        record_upgrade_failure(
            policies.backup_dir,
            failure.target_name,
            head=failure.head,
            from_revision=failure.from_revision,
            error=f"{failure.reason}；回退亦失敗：{restore_exc}",
            rolled_back=False,
        )
        return 9

    record_upgrade_failure(
        policies.backup_dir,
        failure.target_name,
        head=failure.head,
        from_revision=failure.from_revision,
        error=failure.reason,
        rolled_back=True,
    )
    logger.error(
        "資料庫已回到升版前狀態。此次升版失敗，容器不會啟動 web 服務；"
        "可換回舊版 image 立即開機，或排除問題後重試。"
    )
    return 8


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
            "若要建立預設 super_admin，必須同時設定 BOOTSTRAP_SUPER_ADMIN_USERNAME 與 BOOTSTRAP_SUPER_ADMIN_PASSWORD"
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
            session.query(User).filter(User.role == UserRole.SUPER_ADMIN.value).filter(User.is_active).count()
        )

        if super_admin_count == 0 and seed_config:
            logger.info("偵測到 BOOTSTRAP_SUPER_ADMIN_* 環境變數，建立第一個 super_admin")
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
        logger.warn("尚未建立任何 super_admin。系統目前採 first-login setup 流程，請於啟動後完成 /first-login-setup。")
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
        help="跳過 migration 前備份（所有引擎），等效 BOOTSTRAP_BACKUP_MODE=off",
    )
    parser.add_argument(
        "--clear-failure-markers",
        action="store_true",
        help="清除三套資料庫的連續升版失敗 marker（人工排除問題後解鎖再次嘗試升版）",
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
    parser.add_argument(
        "--upgrade-legacy-main-db",
        action="store_true",
        help="自動偵測既有未納管主庫的 schema 版本，stamp 對應 revision 後升級至 head",
    )
    parser.add_argument(
        "--upgrade-legacy-audit-db",
        action="store_true",
        help="自動偵測既有未納管 audit 資料庫的 schema 版本，stamp 對應 revision 後升級至 head",
    )
    parser.add_argument(
        "--upgrade-legacy-usm-db",
        action="store_true",
        help="自動偵測既有未納管 USM 資料庫的 schema 版本，stamp 對應 revision 後升級至 head",
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
        if args.clear_failure_markers:
            backup_dir = _default_backup_dir()
            cleared = clear_all_failure_markers(backup_dir, MIGRATION_ORDER)
            if cleared:
                logger.info(f"已清除 failure marker：{cleared}")
            else:
                logger.info("沒有找到任何 failure marker")
            return 0

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

        if args.upgrade_legacy_main_db:
            return upgrade_legacy_target("main", logger, args.no_backup)

        if args.upgrade_legacy_audit_db:
            return upgrade_legacy_target("audit", logger, args.no_backup)

        if args.upgrade_legacy_usm_db:
            return upgrade_legacy_target("usm", logger, args.no_backup)

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
                    text_ok, _violations = verify_large_text_columns(
                        engine,
                        target_name,
                        logger,
                        TARGET_LABELS[target_name],
                    )
                    if not text_ok:
                        logger.error(f"{TARGET_LABELS[target_name]} 仍存在未升級的可攜文字欄位")
                        return 2
                    if target_name == "main":
                        automation_key_ok, _automation_key_error = verify_automation_provider_encryption_key(
                            engine,
                            logger,
                        )
                        if not automation_key_ok:
                            logger.error(f"{TARGET_LABELS[target_name]} bootstrap 檢查未通過：automation provider 金鑰缺失或無效")
                            return 2
                        ensure_super_admin_seed(engine, logger)
                finally:
                    engine.dispose()
        else:
            from app.runtime_locks import bootstrap_lock

            policies = read_bootstrap_policies(no_backup_flag=args.no_backup)

            # Failure marker 檢查在 bootstrap_lock 之外、任何備份/升版之前：純讀取本機檔案與
            # Alembic script directory（不需資料庫連線），達上限即拒絕整個 bootstrap。
            for target_name in MIGRATION_ORDER:
                head = get_head_revision(target_name)
                marker = read_failure_marker(policies.backup_dir, target_name)
                if (
                    marker
                    and marker.get("head") == head
                    and int(marker.get("attempts", 0)) >= policies.max_upgrade_attempts
                ):
                    logger.error(
                        f"{TARGET_LABELS[target_name]} 針對 head={head} 已連續失敗 "
                        f"{marker['attempts']} 次，拒絕再次嘗試升版。"
                        "請人工介入排除問題，或執行 `python3 database_init.py --clear-failure-markers` 後重試。"
                    )
                    return 10

            # 以 DB advisory lock（SQLite 為檔案鎖）序列化平行啟動下的 schema 變更，避免雙重 Alembic upgrade。
            with bootstrap_lock():
                backup_paths: Dict[str, Optional[str]] = {}
                main_engine: Optional[Engine] = None
                aux_engines: List[Engine] = []
                upgraded: List[BackupResult] = []
                try:
                    for target_name in MIGRATION_ORDER:
                        try:
                            engine, backup_result = bootstrap_target(target_name, logger, policies)
                        except BootstrapTargetFailure as failure:
                            # 還原前先釋放本次已成功 target 的連線，避免與 restore（尤其 SQLite
                            # 檔案層級還原、MySQL/PG schema 重建）衝突。
                            if main_engine is not None:
                                main_engine.dispose()
                            for aux_engine in aux_engines:
                                aux_engine.dispose()
                            return _handle_bootstrap_failure(failure, upgraded, policies, logger)

                        clear_failure_marker(policies.backup_dir, target_name)
                        if backup_result is not None:
                            backup_paths[target_name] = str(backup_result.path)
                            apply_retention(policies.backup_dir, target_name, policies.backup_retention)
                            upgraded.append(backup_result)
                        else:
                            backup_paths[target_name] = None

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
