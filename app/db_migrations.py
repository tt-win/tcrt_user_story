from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.schema import MetaData
from sqlalchemy.sql import sqltypes

from app.config import load_config
from app.db_url import (
    is_sqlite_url,
    normalize_async_database_url,
    normalize_sync_database_url,
    required_driver_specs_for_url,
)
from app.models.database_models import Base as MainBase

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_USM_DATABASE_URL = f"sqlite:///{(PROJECT_ROOT / 'userstorymap.db').resolve()}"


class LegacyDatabaseAdoptionRequiredError(RuntimeError):
    pass


class LegacyDatabaseValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class MigrationTarget:
    key: str
    display_name: str
    alembic_ini_path: Path
    script_location: Path
    resolve_url: Callable[[], str]
    metadata_factory: Callable[[], MetaData]
    validate_flag: str
    adopt_flag: str
    allowed_extra_tables: frozenset[str] = frozenset()

    @property
    def metadata(self) -> MetaData:
        return self.metadata_factory()


def should_render_as_batch(database_url: str) -> bool:
    return is_sqlite_url(database_url)


def _load_settings():
    config_path = os.getenv("APP_CONFIG_PATH", str(PROJECT_ROOT / "config.yaml"))
    return load_config(config_path)


def resolve_main_database_url() -> str:
    settings = _load_settings()
    raw_database_url = (
        os.getenv("DATABASE_URL")
        or os.getenv("SYNC_DATABASE_URL")
        or settings.app.database_url
    )
    return normalize_async_database_url(raw_database_url)


def resolve_audit_database_url() -> str:
    settings = _load_settings()
    raw_database_url = os.getenv("AUDIT_DATABASE_URL", settings.audit.database_url)
    return normalize_async_database_url(raw_database_url)


def resolve_usm_database_url() -> str:
    settings = _load_settings()
    raw_database_url = os.getenv("USM_DATABASE_URL", settings.usm.database_url or DEFAULT_USM_DATABASE_URL)
    return normalize_async_database_url(raw_database_url)


def _load_audit_metadata() -> MetaData:
    from app.audit.database import AuditBase

    return AuditBase.metadata


def _load_usm_metadata() -> MetaData:
    from app.models.user_story_map_db import Base as UserStoryMapBase

    return UserStoryMapBase.metadata


TARGETS = {
    "main": MigrationTarget(
        key="main",
        display_name="主資料庫",
        alembic_ini_path=PROJECT_ROOT / "alembic.ini",
        script_location=PROJECT_ROOT / "alembic",
        resolve_url=resolve_main_database_url,
        metadata_factory=lambda: MainBase.metadata,
        validate_flag="--validate-legacy-main-db",
        adopt_flag="--adopt-legacy-main-db",
        allowed_extra_tables=frozenset({"migration_history"}),
    ),
    "audit": MigrationTarget(
        key="audit",
        display_name="audit 資料庫",
        alembic_ini_path=PROJECT_ROOT / "alembic_audit.ini",
        script_location=PROJECT_ROOT / "alembic_audit",
        resolve_url=resolve_audit_database_url,
        metadata_factory=_load_audit_metadata,
        validate_flag="--validate-legacy-audit-db",
        adopt_flag="--adopt-legacy-audit-db",
    ),
    "usm": MigrationTarget(
        key="usm",
        display_name="USM 資料庫",
        alembic_ini_path=PROJECT_ROOT / "alembic_usm.ini",
        script_location=PROJECT_ROOT / "alembic_usm",
        resolve_url=resolve_usm_database_url,
        metadata_factory=_load_usm_metadata,
        validate_flag="--validate-legacy-usm-db",
        adopt_flag="--adopt-legacy-usm-db",
    ),
}


def get_migration_target(target_name: str = "main") -> MigrationTarget:
    try:
        return TARGETS[target_name]
    except KeyError as exc:
        valid_targets = ", ".join(sorted(TARGETS))
        raise ValueError(f"不支援的 migration target: {target_name}；可用值：{valid_targets}") from exc


def resolve_database_url(target_name: str = "main") -> str:
    return get_migration_target(target_name).resolve_url()


def build_alembic_config(
    database_url: str | None = None,
    *,
    target_name: str = "main",
) -> Config:
    target = get_migration_target(target_name)
    resolved_database_url = normalize_async_database_url(database_url or target.resolve_url())
    cfg = Config(str(target.alembic_ini_path))
    cfg.set_main_option("script_location", str(target.script_location))
    cfg.set_main_option("sqlalchemy.url", resolved_database_url)
    cfg.attributes["resolved_database_url"] = resolved_database_url
    return cfg


def _build_sync_engine(database_url: str):
    sync_url = normalize_sync_database_url(database_url)
    engine_kwargs = {"future": True}
    if sync_url.startswith("sqlite://"):
        engine_kwargs["connect_args"] = {
            "check_same_thread": False,
            "timeout": 30,
        }
    return create_engine(sync_url, **engine_kwargs)


def get_sync_engine_for_target(target_name: str = "main", database_url: str | None = None):
    return _build_sync_engine(database_url or resolve_database_url(target_name))


def _get_baseline_revision(cfg: Config) -> str:
    script = ScriptDirectory.from_config(cfg)
    bases = list(script.get_bases())
    if not bases:
        raise RuntimeError("找不到 Alembic baseline revision")
    if len(bases) > 1:
        raise RuntimeError(f"偵測到多個 Alembic base revisions，無法自動選定 baseline：{bases}")
    return bases[0]


def _get_head_revision(cfg: Config) -> str:
    script = ScriptDirectory.from_config(cfg)
    heads = list(script.get_heads())
    if not heads:
        raise RuntimeError("找不到 Alembic head revision")
    if len(heads) > 1:
        raise RuntimeError(f"偵測到多個 Alembic head revisions，無法自動選定 head：{heads}")
    return heads[0]


def _get_database_state(database_url: str) -> str:
    engine = _build_sync_engine(database_url)
    try:
        inspector = inspect(engine)
        table_names = {name.lower() for name in inspector.get_table_names()}
        non_system_tables = table_names - {"sqlite_sequence"}

        if not non_system_tables:
            return "empty"

        if "alembic_version" not in table_names:
            return "legacy_unmanaged"

        with engine.connect() as conn:
            version_rows = conn.execute(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            ).fetchall()

        if not version_rows or not str(version_rows[0][0] or "").strip():
            return "legacy_unmanaged"

        return "managed"
    finally:
        engine.dispose()


def _get_current_revision(database_url: str) -> str | None:
    engine = _build_sync_engine(database_url)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def _quote_ident_for_engine(engine, name: str) -> str:
    return engine.dialect.identifier_preparer.quote(name)


def _driver_statuses_for_url(database_url: str) -> list[dict[str, Any]]:
    driver_statuses: list[dict[str, Any]] = []
    for package_name, import_name in required_driver_specs_for_url(database_url):
        driver_statuses.append(
            {
                "package": package_name,
                "import_name": import_name,
                "available": importlib.util.find_spec(import_name) is not None,
            }
        )
    return driver_statuses


def _diff_table_name(diff: Any) -> str | None:
    if not isinstance(diff, tuple) or not diff:
        return None

    op_name = diff[0]
    if op_name == "remove_table":
        table = diff[1]
        return getattr(table, "name", None)

    if op_name in {"remove_index", "add_index"}:
        index = diff[1]
        table = getattr(index, "table", None)
        return getattr(table, "name", None)

    if op_name == "remove_constraint":
        constraint = diff[1]
        table = getattr(constraint, "table", None)
        return getattr(table, "name", None)

    if len(diff) > 1 and isinstance(diff[1], str):
        return diff[1]

    return None


def _is_allowed_extra_diff(diff: Any, allowed_extra_tables: frozenset[str]) -> bool:
    if not isinstance(diff, tuple) or not diff:
        return False

    op_name = diff[0]
    table_name = (_diff_table_name(diff) or "").lower()
    if table_name not in allowed_extra_tables:
        return False

    return op_name in {"remove_table", "remove_index", "remove_constraint"}


def _iter_flatten_diffs(diffs: list[Any]) -> list[Any]:
    flattened: list[Any] = []
    for diff in diffs:
        if isinstance(diff, list):
            flattened.extend(_iter_flatten_diffs(diff))
        else:
            flattened.append(diff)
    return flattened


def _is_sqlite_string_affinity_type_change(diff: Any, dialect_name: str) -> bool:
    if dialect_name != "sqlite":
        return False
    if not isinstance(diff, tuple) or not diff or diff[0] != "modify_type":
        return False
    if len(diff) < 7:
        return False

    existing_type = diff[5]
    target_type = diff[6]
    existing_affinity = getattr(existing_type, "_type_affinity", None)
    target_affinity = getattr(target_type, "_type_affinity", None)
    return existing_affinity is sqltypes.String and target_affinity is sqltypes.String


def _format_diff(diff: Any) -> str:
    if not isinstance(diff, tuple) or not diff:
        return repr(diff)

    op_name = diff[0]
    table_name = _diff_table_name(diff)

    if op_name == "add_table":
        return f"缺少資料表：{getattr(diff[1], 'name', diff[1])}"
    if op_name == "remove_table":
        return f"多出資料表：{table_name}"
    if op_name == "add_column":
        return f"缺少欄位：{table_name}.{getattr(diff[2], 'name', diff[2])}"
    if op_name == "remove_column":
        return f"多出欄位：{table_name}.{getattr(diff[2], 'name', diff[2])}"
    if op_name == "modify_nullable":
        return f"欄位 nullable 不一致：{table_name}.{diff[3]}"
    if op_name == "modify_type":
        return f"欄位型別不一致：{table_name}.{diff[3]} ({diff[5]} -> {diff[6]})"
    if op_name == "add_index":
        return f"缺少索引：{getattr(diff[1], 'name', diff[1])}"
    if op_name == "remove_index":
        return f"多出索引：{getattr(diff[1], 'name', diff[1])}"
    if op_name == "add_constraint":
        return f"缺少約束：{getattr(diff[1], 'name', diff[1])}"
    if op_name == "remove_constraint":
        return f"多出約束：{getattr(diff[1], 'name', diff[1])}"
    return repr(diff)


def validate_legacy_database(
    database_url: str | None = None,
    *,
    target_name: str = "main",
) -> List[str]:
    target = get_migration_target(target_name)
    resolved_url = database_url or target.resolve_url()
    engine = _build_sync_engine(resolved_url)
    try:
        with engine.connect() as connection:
            metadata = target.metadata
            dialect_name = connection.dialect.name
            migration_context = MigrationContext.configure(
                connection,
                opts={
                    "compare_type": True,
                    "compare_server_default": False,
                    "target_metadata": metadata,
                    "render_as_batch": connection.dialect.name == "sqlite",
                },
            )
            raw_diffs = compare_metadata(migration_context, metadata)

        flattened_diffs = _iter_flatten_diffs(raw_diffs)
        relevant_diffs = [
            diff
            for diff in flattened_diffs
            if not _is_allowed_extra_diff(diff, target.allowed_extra_tables)
            and not _is_sqlite_string_affinity_type_change(diff, dialect_name)
        ]
        return [_format_diff(diff) for diff in relevant_diffs]
    finally:
        engine.dispose()


def adopt_legacy_database(
    database_url: str | None = None,
    *,
    target_name: str = "main",
) -> str:
    target = get_migration_target(target_name)
    cfg = build_alembic_config(database_url=database_url, target_name=target_name)
    resolved_url = cfg.get_main_option("sqlalchemy.url")
    state = _get_database_state(resolved_url)

    if state == "empty":
        raise LegacyDatabaseValidationError(
            f"目前{target.display_name}是空的，不需要 adoption；直接執行 migration 即可。"
        )
    if state == "managed":
        raise LegacyDatabaseValidationError(
            f"目前{target.display_name}已納入 Alembic 管理，不需要再做 adoption。"
        )

    diff_messages = validate_legacy_database(resolved_url, target_name=target_name)
    if diff_messages:
        preview = "\n".join(f"- {message}" for message in diff_messages[:20])
        extra = ""
        if len(diff_messages) > 20:
            extra = f"\n- ... 另有 {len(diff_messages) - 20} 項差異"
        raise LegacyDatabaseValidationError(
            f"現有{target.display_name} schema 與 baseline 不一致，拒絕自動 stamp：\n"
            f"{preview}{extra}"
        )

    baseline_revision = _get_baseline_revision(cfg)
    command.ensure_version(cfg)
    command.stamp(cfg, baseline_revision)
    return baseline_revision


def upgrade_database(
    revision: str = "head",
    database_url: str | None = None,
    *,
    target_name: str = "main",
) -> None:
    target = get_migration_target(target_name)
    cfg = build_alembic_config(database_url=database_url, target_name=target_name)
    resolved_url = cfg.get_main_option("sqlalchemy.url")
    state = _get_database_state(resolved_url)

    if state == "legacy_unmanaged":
        raise LegacyDatabaseAdoptionRequiredError(
            f"偵測到既有{target.display_name}尚未納入 Alembic 版控。\n"
            f"請先執行 `python3 database_init.py {target.adopt_flag}` 驗證並寫入 baseline version，"
            "完成後再重新啟動服務。"
        )

    command.upgrade(cfg, revision)


def collect_target_preflight(
    target_name: str = "main",
    *,
    database_url: str | None = None,
) -> dict[str, Any]:
    target = get_migration_target(target_name)
    resolved_async_url = normalize_async_database_url(database_url or target.resolve_url())
    resolved_sync_url = normalize_sync_database_url(resolved_async_url)
    cfg = build_alembic_config(database_url=resolved_async_url, target_name=target_name)
    head_revision = _get_head_revision(cfg)
    driver_statuses = _driver_statuses_for_url(resolved_async_url)
    missing_drivers = [status["package"] for status in driver_statuses if not status["available"]]
    result: dict[str, Any] = {
        "target": target.key,
        "label": target.display_name,
        "async_url": resolved_async_url,
        "sync_url": resolved_sync_url,
        "head_revision": head_revision,
        "driver_statuses": driver_statuses,
        "database_state": None,
        "current_revision": None,
        "ready": False,
        "status": "pending",
        "remediation": [],
    }

    if missing_drivers:
        result["status"] = "missing_drivers"
        result["remediation"] = [
            f"請先安裝必要 driver：pip install {' '.join(missing_drivers)}",
        ]
        return result

    try:
        database_state = _get_database_state(resolved_async_url)
        result["database_state"] = database_state
        if database_state == "managed":
            result["current_revision"] = _get_current_revision(resolved_async_url)
    except Exception as exc:
        result["status"] = "connection_error"
        result["error"] = str(exc)
        result["remediation"] = [
            "請確認資料庫服務是否已啟動，且 DATABASE_URL / AUDIT_DATABASE_URL / USM_DATABASE_URL 指向可連線的目標。",
        ]
        return result

    if result["database_state"] == "legacy_unmanaged":
        result["status"] = "legacy_unmanaged"
        result["remediation"] = [
            f"先執行 `python3 database_init.py {target.validate_flag}` 驗證現有 schema。",
            f"驗證通過後執行 `python3 database_init.py {target.adopt_flag}` 寫入 baseline revision。",
        ]
        return result

    if result["database_state"] == "empty":
        result["ready"] = True
        result["status"] = "empty_ready"
        result["remediation"] = [
            "可直接執行 `python3 database_init.py` 或 `alembic upgrade head` 建立 schema。",
        ]
        return result

    if result["current_revision"] != head_revision:
        result["status"] = "upgrade_pending"
        result["remediation"] = [
            "目前資料庫已納管，但 revision 尚未到 head；請執行 `python3 database_init.py` 完成升級。",
        ]
        return result

    result["ready"] = True
    result["status"] = "ready"
    result["remediation"] = []
    return result


def collect_target_verification_summary(
    target_name: str = "main",
    *,
    database_url: str | None = None,
    required_tables: list[str] | tuple[str, ...] | None = None,
    critical_tables: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    target = get_migration_target(target_name)
    resolved_async_url = normalize_async_database_url(database_url or target.resolve_url())
    cfg = build_alembic_config(database_url=resolved_async_url, target_name=target_name)
    head_revision = _get_head_revision(cfg)
    database_state = _get_database_state(resolved_async_url)
    engine = _build_sync_engine(resolved_async_url)
    required_tables = list(required_tables or [])
    critical_tables = list(critical_tables or required_tables)

    try:
        inspector = inspect(engine)
        existing_table_names = inspector.get_table_names()
        existing_lookup = {table_name.lower(): table_name for table_name in existing_table_names}
        required_table_status = {
            table_name: table_name.lower() in existing_lookup
            for table_name in required_tables
        }
        critical_row_counts: dict[str, int | None] = {}
        with engine.connect() as connection:
            current_revision = (
                MigrationContext.configure(connection).get_current_revision()
                if "alembic_version" in existing_lookup
                else None
            )
            for table_name in critical_tables:
                actual_table_name = existing_lookup.get(table_name.lower())
                if not actual_table_name:
                    critical_row_counts[table_name] = None
                    continue
                row_count = connection.execute(
                    text(
                        f"SELECT COUNT(*) FROM {_quote_ident_for_engine(engine, actual_table_name)}"
                    )
                ).scalar()
                critical_row_counts[table_name] = int(row_count or 0)

        ready = (
            database_state == "managed"
            and current_revision == head_revision
            and all(required_table_status.values())
        )
        return {
            "target": target.key,
            "label": target.display_name,
            "database_state": database_state,
            "head_revision": head_revision,
            "current_revision": current_revision,
            "required_tables": required_table_status,
            "critical_row_counts": critical_row_counts,
            "total_tables": len(existing_table_names),
            "ready": ready,
        }
    finally:
        engine.dispose()


def validate_legacy_main_database(database_url: str | None = None) -> List[str]:
    return validate_legacy_database(database_url, target_name="main")


def adopt_legacy_main_database(database_url: str | None = None) -> str:
    return adopt_legacy_database(database_url, target_name="main")


def upgrade_main_database(revision: str = "head", database_url: str | None = None) -> None:
    upgrade_database(revision=revision, database_url=database_url, target_name="main")


def validate_legacy_audit_database(database_url: str | None = None) -> List[str]:
    return validate_legacy_database(database_url, target_name="audit")


def adopt_legacy_audit_database(database_url: str | None = None) -> str:
    return adopt_legacy_database(database_url, target_name="audit")


def upgrade_audit_database(revision: str = "head", database_url: str | None = None) -> None:
    upgrade_database(revision=revision, database_url=database_url, target_name="audit")


def validate_legacy_usm_database(database_url: str | None = None) -> List[str]:
    return validate_legacy_database(database_url, target_name="usm")


def adopt_legacy_usm_database(database_url: str | None = None) -> str:
    return adopt_legacy_database(database_url, target_name="usm")


def upgrade_usm_database(revision: str = "head", database_url: str | None = None) -> None:
    upgrade_database(revision=revision, database_url=database_url, target_name="usm")
