from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any, Iterable

import requests
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / ".tmp" / "db-cutover"
DEFAULT_SQLITE_FILES = {
    "DATABASE_URL": "test_case_repo.db",
    "SYNC_DATABASE_URL": "test_case_repo.db",
    "AUDIT_DATABASE_URL": "audit.db",
    "USM_DATABASE_URL": "userstorymap.db",
}
DEFAULT_SERVER_PORTS = {
    "sqlite": 19997,
    "postgres": 19998,
    "mysql": 19999,
}
TARGET_ORDER = ("main", "audit", "usm")
MIGRATE_URL_KEYS = ("DATABASE_URL", "SYNC_DATABASE_URL", "AUDIT_DATABASE_URL", "USM_DATABASE_URL")
MIGRATE_JOB_SPECS = (
    ("main", "SYNC_DATABASE_URL"),
    ("audit", "AUDIT_DATABASE_URL"),
    ("usm", "USM_DATABASE_URL"),
)
NON_EMPTY_EXCLUDE_TABLES = ("alembic_version", "migration_history")
MAX_NON_EMPTY_TABLES_REPORTED = 20


@dataclass(frozen=True)
class WorkflowTarget:
    name: str
    compose_file: str | None
    container_name: str | None
    port: int
    manages_services: bool
    environment: dict[str, str]


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int
    duration_seconds: float
    stdout: str = ""
    stderr: str = ""
    log_path: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "returncode": self.returncode,
            "duration_seconds": round(self.duration_seconds, 3),
            "stdout": self.stdout,
            "stderr": self.stderr,
            "log_path": self.log_path,
        }


@dataclass(frozen=True)
class MigrateEndpoints:
    source: dict[str, str]
    target: dict[str, str]


def parse_env_file(path: Path) -> dict[str, str]:
    """解析簡單的 `KEY=VALUE` env 檔（跳過空行/`#` 開頭，去除值的首尾引號）。"""
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key] = value
    return values


def _require_migrate_url_keys(values: dict[str, str], source_label: str) -> dict[str, str]:
    missing = [key for key in MIGRATE_URL_KEYS if not values.get(key)]
    if missing:
        raise ValueError(f"{source_label} 缺少必要鍵：{missing}")
    return {key: values[key] for key in MIGRATE_URL_KEYS}


def resolve_migrate_source_endpoints(source_env_file: str | None) -> dict[str, str]:
    if source_env_file:
        values = parse_env_file(Path(source_env_file))
        return _require_migrate_url_keys(values, f"--source-env-file={source_env_file}")

    from app.db_migrations import (
        resolve_audit_database_url,
        resolve_main_database_url,
        resolve_usm_database_url,
    )
    from app.db_url import normalize_sync_database_url

    main_url = resolve_main_database_url()
    return {
        "DATABASE_URL": main_url,
        "SYNC_DATABASE_URL": normalize_sync_database_url(main_url),
        "AUDIT_DATABASE_URL": resolve_audit_database_url(),
        "USM_DATABASE_URL": resolve_usm_database_url(),
    }


def resolve_migrate_target_endpoints(
    target_env_file: str | None,
    target: "WorkflowTarget",
) -> dict[str, str]:
    """未提供 --target-env-file 時，使用 build_workflow_target() 的 disposable 環境
    （sqlite 為 run-dir 隔離檔案；mysql/postgres 為固定 tcrt/tcrt@fixed-port，無論該服務是本次
    workflow 以 --manage-services 啟動、或操作者自行手動啟動 docker-compose.*.yml）。"""
    if target_env_file:
        values = parse_env_file(Path(target_env_file))
        return _require_migrate_url_keys(values, f"--target-env-file={target_env_file}")
    return dict(target.environment)


def _endpoint_identity(url: str) -> tuple[str, str, int | None, str | None]:
    parsed = make_url(url)
    backend = parsed.get_backend_name()
    if backend == "sqlite":
        database = str(Path(parsed.database).resolve()) if parsed.database else None
        return (backend, "", None, database)
    return (backend, parsed.host or "", parsed.port, parsed.database)


def _reject_same_database(source: dict[str, str], target: dict[str, str]) -> None:
    for key in MIGRATE_URL_KEYS:
        if _endpoint_identity(source[key]) == _endpoint_identity(target[key]):
            raise ValueError(f"{key} 的來源與目標解析為同一資料庫，拒絕執行：{source[key]}")


def resolve_migrate_endpoints(
    *,
    target: "WorkflowTarget",
    target_env_file: str | None,
    source_env_file: str | None,
) -> MigrateEndpoints:
    source = resolve_migrate_source_endpoints(source_env_file)
    target_endpoints = resolve_migrate_target_endpoints(target_env_file, target)
    _reject_same_database(source, target_endpoints)
    return MigrateEndpoints(source=source, target=target_endpoints)


def detect_non_empty_targets(endpoints: MigrateEndpoints) -> dict[str, list[dict[str, Any]]]:
    """搬移前偵測目標三庫是否已有業務資料（排除 migration 版控表）。database 不存在或無法連線視為空。"""
    from app.db_url import normalize_sync_database_url

    non_empty: dict[str, list[dict[str, Any]]] = {}
    for label, url_key in MIGRATE_JOB_SPECS:
        sync_url = normalize_sync_database_url(endpoints.target[url_key])
        try:
            engine = create_engine(sync_url, future=True)
        except Exception:  # noqa: BLE001
            continue
        try:
            inspector = inspect(engine)
            table_names = [name for name in inspector.get_table_names() if name not in NON_EMPTY_EXCLUDE_TABLES]
            preparer = engine.dialect.identifier_preparer
            rows: list[dict[str, Any]] = []
            with engine.connect() as connection:
                for table_name in table_names:
                    count = connection.execute(text(f"SELECT COUNT(*) FROM {preparer.quote(table_name)}")).scalar()
                    if count:
                        rows.append({"table": table_name, "rows": int(count)})
            if rows:
                non_empty[label] = rows[:MAX_NON_EMPTY_TABLES_REPORTED]
        except Exception:  # noqa: BLE001
            continue
        finally:
            engine.dispose()
    return non_empty


def _run_cross_migrate(
    *,
    job_name: str,
    source_url: str,
    target_url: str,
    log_path: Path,
    disable_constraints: bool,
) -> CommandResult:
    from app.db_url import normalize_sync_database_url

    arguments = [
        "--name",
        job_name,
        "--source-url",
        normalize_sync_database_url(source_url),
        "--target-url",
        normalize_sync_database_url(target_url),
        "--reset-target",
        "--json",
        "--quiet",
    ]
    if disable_constraints:
        arguments.append("--disable-constraints")
    command = [sys.executable, str(PROJECT_ROOT / "scripts" / "db_cross_migrate.py"), *arguments]
    return _run_command(command=command, environment=os.environ.copy(), log_path=log_path)


def build_workflow_target(target_name: str, run_dir: Path) -> WorkflowTarget:
    run_dir = run_dir.resolve()
    if target_name == "sqlite":
        environment = {
            key: f"sqlite:///{(run_dir / filename).resolve()}"
            for key, filename in DEFAULT_SQLITE_FILES.items()
        }
        return WorkflowTarget(
            name="sqlite",
            compose_file=None,
            container_name=None,
            port=DEFAULT_SERVER_PORTS["sqlite"],
            manages_services=False,
            environment=environment,
        )

    if target_name == "mysql":
        return WorkflowTarget(
            name="mysql",
            compose_file="docker-compose.mysql.yml",
            container_name="tcrt-mysql",
            port=DEFAULT_SERVER_PORTS["mysql"],
            manages_services=True,
            environment={
                "DATABASE_URL": "mysql+asyncmy://tcrt:tcrt@127.0.0.1:33060/tcrt_main",
                "SYNC_DATABASE_URL": "mysql+pymysql://tcrt:tcrt@127.0.0.1:33060/tcrt_main",
                "AUDIT_DATABASE_URL": "mysql+asyncmy://tcrt:tcrt@127.0.0.1:33060/tcrt_audit",
                "USM_DATABASE_URL": "mysql+asyncmy://tcrt:tcrt@127.0.0.1:33060/tcrt_usm",
            },
        )

    if target_name == "postgres":
        return WorkflowTarget(
            name="postgres",
            compose_file="docker-compose.postgres.yml",
            container_name="tcrt-postgres",
            port=DEFAULT_SERVER_PORTS["postgres"],
            manages_services=True,
            environment={
                "DATABASE_URL": "postgresql+asyncpg://tcrt:tcrt@127.0.0.1:5433/tcrt_main",
                "SYNC_DATABASE_URL": "postgresql+psycopg://tcrt:tcrt@127.0.0.1:5433/tcrt_main",
                "AUDIT_DATABASE_URL": "postgresql+asyncpg://tcrt:tcrt@127.0.0.1:5433/tcrt_audit",
                "USM_DATABASE_URL": "postgresql+asyncpg://tcrt:tcrt@127.0.0.1:5433/tcrt_usm",
            },
        )

    raise ValueError(f"Unsupported workflow target: {target_name}")


def build_runtime_environment(target: WorkflowTarget, pid_file: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(target.environment)
    environment.setdefault("JWT_SECRET_KEY", "cutover-smoke-secret")
    environment["HOST"] = "127.0.0.1"
    environment["PORT"] = str(target.port)
    environment["SERVER_PID_FILE"] = str(pid_file.resolve())
    environment["UVICORN_RELOAD"] = "0"
    environment["PYTHONPATH"] = str(PROJECT_ROOT)
    return environment


def redact_environment(environment: dict[str, str]) -> dict[str, str]:
    redacted: dict[str, str] = {}
    for key in ("DATABASE_URL", "SYNC_DATABASE_URL", "AUDIT_DATABASE_URL", "USM_DATABASE_URL"):
        value = environment.get(key)
        redacted[key] = redact_url(value) if value else ""
    if environment.get("JWT_SECRET_KEY"):
        redacted["JWT_SECRET_KEY"] = "<redacted>"
    redacted["HOST"] = environment.get("HOST", "")
    redacted["PORT"] = environment.get("PORT", "")
    redacted["SERVER_PID_FILE"] = environment.get("SERVER_PID_FILE", "")
    return redacted


def redact_url(url: str) -> str:
    if not url:
        return url
    parsed = make_url(url)
    if parsed.password is None:
        return str(parsed)
    return str(parsed.set(password="***"))


def extract_json_payload(output: str) -> dict[str, Any]:
    stripped = output.strip()
    start_index = stripped.find("{")
    if start_index < 0:
        raise ValueError("No JSON payload found in command output.")
    return json.loads(stripped[start_index:])


def compare_rehearsal_summaries(
    current_summary: dict[str, Any],
    baseline_summary: dict[str, Any],
) -> dict[str, Any]:
    current_targets = _verification_target_map(current_summary)
    baseline_targets = _verification_target_map(baseline_summary)
    comparisons: list[dict[str, Any]] = []
    matches = True

    for target_name in TARGET_ORDER:
        current = current_targets.get(target_name)
        baseline = baseline_targets.get(target_name)
        if not current or not baseline:
            matches = False
            comparisons.append(
                {
                    "target": target_name,
                    "matches": False,
                    "missing": {
                        "current": current is None,
                        "baseline": baseline is None,
                    },
                }
            )
            continue

        required_tables = sorted(
            set(current.get("required_tables", {}).keys())
            | set(baseline.get("required_tables", {}).keys())
        )
        critical_tables = sorted(
            set(current.get("critical_row_counts", {}).keys())
            | set(baseline.get("critical_row_counts", {}).keys())
        )
        required_table_checks = [
            {
                "table": table_name,
                "baseline": baseline.get("required_tables", {}).get(table_name),
                "current": current.get("required_tables", {}).get(table_name),
                "matches": baseline.get("required_tables", {}).get(table_name)
                == current.get("required_tables", {}).get(table_name),
            }
            for table_name in required_tables
        ]
        critical_row_counts = [
            {
                "table": table_name,
                "baseline": baseline.get("critical_row_counts", {}).get(table_name),
                "current": current.get("critical_row_counts", {}).get(table_name),
                "matches": baseline.get("critical_row_counts", {}).get(table_name)
                == current.get("critical_row_counts", {}).get(table_name),
            }
            for table_name in critical_tables
        ]
        revisions_match = baseline.get("current_revision") == current.get("current_revision")
        target_matches = (
            revisions_match
            and all(item["matches"] for item in required_table_checks)
            and all(item["matches"] for item in critical_row_counts)
        )
        matches = matches and target_matches
        comparisons.append(
            {
                "target": target_name,
                "matches": target_matches,
                "baseline_revision": baseline.get("current_revision"),
                "current_revision": current.get("current_revision"),
                "revisions_match": revisions_match,
                "required_tables": required_table_checks,
                "critical_row_counts": critical_row_counts,
            }
        )

    return {"matches": matches, "targets": comparisons}


def render_markdown_summary(summary: dict[str, Any]) -> str:
    lines = [
        "# DB Cutover Workflow Summary",
        "",
        f"- target: `{summary['target']}`",
        f"- mode: `{summary['mode']}`",
        f"- success: `{'yes' if summary['success'] else 'no'}`",
        f"- run_dir: `{summary['run_dir']}`",
        f"- generated_at: `{summary['generated_at']}`",
        "",
        "## Environment",
        "",
    ]
    for key, value in summary.get("environment", {}).items():
        lines.append(f"- {key}: `{value}`")

    guardrails = summary.get("guardrails") or {}
    steps = summary.get("steps") or {}
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            f"- passed: `{'yes' if guardrails.get('passed') else 'no'}`",
            f"- violations: `{len(guardrails.get('violations', []))}`",
            "",
            "## Steps",
            "",
            f"- preflight: `rc={steps.get('preflight', {}).get('returncode', 'n/a')}`",
            f"- bootstrap: `rc={steps.get('bootstrap', {}).get('returncode', 'n/a')}`",
            f"- verify: `rc={steps.get('verify', {}).get('returncode', 'n/a')}`",
        ]
    )
    if summary.get("health_check"):
        health_check = summary["health_check"]
        lines.append(f"- health: `{'ok' if health_check['ok'] else 'failed'}`")
        lines.append(f"- health_url: `{health_check['url']}`")

    lines.extend(["", "## Verification", ""])
    for target_summary in summary.get("verification", {}).get("targets", []):
        lines.append(
            f"- {target_summary['target']}: ready=`{'yes' if target_summary['ready'] else 'no'}`, "
            f"revision=`{target_summary['current_revision']}/{target_summary['head_revision']}`"
        )
        for table_name, row_count in target_summary.get("critical_row_counts", {}).items():
            lines.append(f"  - {table_name}: `{row_count}`")

    comparison = summary.get("comparison")
    if comparison:
        lines.extend(["", "## Comparison", ""])
        lines.append(f"- baseline: `{summary.get('baseline_summary_path', '')}`")
        lines.append(f"- matches: `{'yes' if comparison['matches'] else 'no'}`")
        for target_result in comparison["targets"]:
            lines.append(
                f"- {target_result['target']}: `{'match' if target_result['matches'] else 'mismatch'}`"
            )

    non_empty_tables = summary.get("non_empty_tables")
    if non_empty_tables:
        lines.extend(["", "## Non-Empty Target Tables", ""])
        for target_label, rows in non_empty_tables.items():
            lines.append(f"- {target_label}:")
            for row in rows:
                lines.append(f"  - {row['table']}: `{row['rows']}`")

    migration = summary.get("migration")
    if migration:
        lines.extend(["", "## Migration", ""])
        lines.append(f"- row_counts_match: `{'yes' if migration.get('row_counts_match') else 'no'}`")
        lines.append(f"- duration_seconds: `{migration.get('duration_seconds')}`")
        for job in migration.get("jobs", []):
            table_rows = job.get("tables", [])
            total_rows = sum(int(item.get("rows", 0)) for item in table_rows)
            lines.append(
                f"- {job.get('job', '?')}: tables=`{len(table_rows)}`, rows=`{total_rows}`, "
                f"row_counts_match=`{'yes' if job.get('row_counts_match') else 'no'}`"
            )

    env_summary = summary.get("env_summary")
    if env_summary:
        lines.extend(
            [
                "",
                "## Env Summary",
                "",
                "實際密碼請直接取自 --target-env-file，本檔不含明文密碼。",
                "",
            ]
        )
        for key, value in env_summary.items():
            lines.append(f"- {key}: `{value}`")

    lines.extend(
        [
            "",
            "## Rollback Reminders",
            "",
            "- 保留來源資料庫備份或快照。",
            "- 保留本次 run 的 preflight、bootstrap、verify 與 health 輸出。",
            "- 若 smoke 或 rehearsal 失敗，先回退 `DATABASE_URL`、`SYNC_DATABASE_URL`、`AUDIT_DATABASE_URL`、`USM_DATABASE_URL`，再重新驗證。",
        ]
    )
    return "\n".join(lines) + "\n"


def run_cutover_workflow(
    *,
    target_name: str,
    mode: str,
    output_root: Path,
    manage_services: bool,
    keep_services: bool,
    health_timeout: int,
    baseline_summary_path: Path | None = None,
    target_env_file: str | None = None,
    source_env_file: str | None = None,
    force_reset_target: bool = False,
    migrate_disable_constraints: bool = False,
) -> dict[str, Any]:
    if mode == "migrate":
        return _run_migrate_workflow(
            target_name=target_name,
            output_root=output_root,
            manage_services=manage_services,
            keep_services=keep_services,
            health_timeout=health_timeout,
            target_env_file=target_env_file,
            source_env_file=source_env_file,
            force_reset_target=force_reset_target,
            migrate_disable_constraints=migrate_disable_constraints,
        )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = (output_root / f"{timestamp}-{target_name}-{mode}").resolve()
    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    target = build_workflow_target(target_name, run_dir)
    pid_file = run_dir / "server.pid"
    environment = build_runtime_environment(target, pid_file)
    summary: dict[str, Any] = {
        "target": target_name,
        "mode": mode,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(run_dir),
        "environment": redact_environment(environment),
        "compose_file": target.compose_file,
        "guardrails": {},
        "steps": {},
        "preflight": {},
        "verification": {},
        "health_check": None,
        "success": False,
    }
    current_started_services = False

    try:
        if manage_services and target.manages_services:
            compose_result = _run_compose_up(target, environment, logs_dir / "compose-up.log")
            summary["steps"]["compose_up"] = compose_result.as_json()
            if compose_result.returncode != 0:
                return _finalize_summary(summary, run_dir, baseline_summary_path)
            current_started_services = True

        guardrail_result = _run_guardrails()
        summary["guardrails"] = guardrail_result
        if not guardrail_result["passed"]:
            return _finalize_summary(summary, run_dir, baseline_summary_path)

        preflight_result = _run_database_init_command(
            arguments=["--preflight", "--json", "--quiet"],
            environment=environment,
            log_path=logs_dir / "preflight.log",
        )
        summary["steps"]["preflight"] = preflight_result.as_json()
        if preflight_result.stdout:
            summary["preflight"] = extract_json_payload(preflight_result.stdout)
        if preflight_result.returncode != 0 or mode == "preflight":
            return _finalize_summary(summary, run_dir, baseline_summary_path)

        bootstrap_result = _run_database_init_command(
            arguments=["--no-backup", "--quiet"],
            environment=environment,
            log_path=logs_dir / "bootstrap.log",
        )
        summary["steps"]["bootstrap"] = bootstrap_result.as_json()
        if bootstrap_result.returncode != 0:
            return _finalize_summary(summary, run_dir, baseline_summary_path)

        verify_result = _run_database_init_command(
            arguments=["--verify-target", "all", "--json", "--quiet"],
            environment=environment,
            log_path=logs_dir / "verify.log",
        )
        summary["steps"]["verify"] = verify_result.as_json()
        if verify_result.stdout:
            summary["verification"] = extract_json_payload(verify_result.stdout)
        if verify_result.returncode != 0:
            return _finalize_summary(summary, run_dir, baseline_summary_path)

        health_result = _run_health_check(
            environment=environment,
            pid_file=pid_file,
            timeout_seconds=health_timeout,
            log_path=logs_dir / "start.log",
        )
        summary["steps"]["start_app"] = health_result["start_command"].as_json()
        summary["health_check"] = health_result["health"]
        if not health_result["health"]["ok"]:
            return _finalize_summary(summary, run_dir, baseline_summary_path)

        if baseline_summary_path is not None:
            baseline_summary = json.loads(baseline_summary_path.read_text(encoding="utf-8"))
            summary["baseline_summary_path"] = str(baseline_summary_path.resolve())
            summary["comparison"] = compare_rehearsal_summaries(summary, baseline_summary)

        return _finalize_summary(summary, run_dir, baseline_summary_path)
    finally:
        _stop_server_if_running(pid_file)
        if current_started_services and target.manages_services and not keep_services:
            compose_down_result = _run_compose_down(
                target,
                environment,
                logs_dir / "compose-down.log",
            )
            summary["steps"]["compose_down"] = compose_down_result.as_json()
            _write_summary_files(run_dir, summary)


def _run_migrate_workflow(
    *,
    target_name: str,
    output_root: Path,
    manage_services: bool,
    keep_services: bool,
    health_timeout: int,
    target_env_file: str | None,
    source_env_file: str | None,
    force_reset_target: bool,
    migrate_disable_constraints: bool,
) -> dict[str, Any]:
    """一鍵搬移：schema bootstrap → 三庫資料搬移 → 逐表覆核 → 驗證 → 健康檢查（design D2）。"""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = (output_root / f"{timestamp}-{target_name}-migrate").resolve()
    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    target = build_workflow_target(target_name, run_dir)
    pid_file = run_dir / "server.pid"
    summary: dict[str, Any] = {
        "target": target_name,
        "mode": "migrate",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(run_dir),
        "environment": {},
        "compose_file": target.compose_file,
        "guardrails": {},
        "steps": {},
        "preflight": {},
        "verification": {},
        "health_check": None,
        "migration": {},
        "env_summary": {},
        "success": False,
    }
    current_started_services = False
    environment: dict[str, str] | None = None

    try:
        if manage_services and target.manages_services:
            compose_environment = build_runtime_environment(target, pid_file)
            compose_result = _run_compose_up(target, compose_environment, logs_dir / "compose-up.log")
            summary["steps"]["compose_up"] = compose_result.as_json()
            if compose_result.returncode != 0:
                return _finalize_summary(summary, run_dir, None)
            current_started_services = True

        try:
            endpoints = resolve_migrate_endpoints(
                target=target,
                target_env_file=target_env_file,
                source_env_file=source_env_file,
            )
        except ValueError as exc:
            summary["error"] = str(exc)
            return _finalize_summary(summary, run_dir, None)

        environment = build_runtime_environment(target, pid_file)
        environment.update(endpoints.target)
        summary["environment"] = redact_environment(environment)

        guardrail_result = _run_guardrails()
        summary["guardrails"] = guardrail_result
        if not guardrail_result["passed"]:
            return _finalize_summary(summary, run_dir, None)

        preflight_result = _run_database_init_command(
            arguments=["--preflight", "--json", "--quiet"],
            environment=environment,
            log_path=logs_dir / "preflight.log",
        )
        summary["steps"]["preflight"] = preflight_result.as_json()
        if preflight_result.stdout:
            summary["preflight"] = extract_json_payload(preflight_result.stdout)
        if preflight_result.returncode != 0:
            return _finalize_summary(summary, run_dir, None)

        non_empty = detect_non_empty_targets(endpoints)
        if non_empty and not force_reset_target:
            summary["non_empty_tables"] = non_empty
            summary["error"] = "目標資料庫已有業務資料，且未帶 --force-reset-target，中止 migrate"
            return _finalize_summary(summary, run_dir, None)

        bootstrap_result = _run_database_init_command(
            arguments=["--no-backup", "--quiet"],
            environment=environment,
            log_path=logs_dir / "bootstrap.log",
        )
        summary["steps"]["bootstrap"] = bootstrap_result.as_json()
        if bootstrap_result.returncode != 0:
            return _finalize_summary(summary, run_dir, None)

        migration_started = time.monotonic()
        migration_jobs: list[dict[str, Any]] = []
        migration_ok = True
        for job_name, url_key in MIGRATE_JOB_SPECS:
            migrate_result = _run_cross_migrate(
                job_name=job_name,
                source_url=endpoints.source[url_key],
                target_url=endpoints.target[url_key],
                log_path=logs_dir / f"migrate-{job_name}.log",
                disable_constraints=migrate_disable_constraints,
            )
            summary["steps"][f"migrate_{job_name}"] = migrate_result.as_json()
            if migrate_result.returncode != 0:
                migration_ok = False
                migration_jobs.append({"job": job_name, "returncode": migrate_result.returncode, "status": "error"})
                break
            payload = extract_json_payload(migrate_result.stdout) if migrate_result.stdout else {}
            job_summary = (payload.get("jobs") or [{}])[0]
            job_summary["source_url"] = redact_url(job_summary.get("source_url", endpoints.source[url_key]))
            job_summary["target_url"] = redact_url(job_summary.get("target_url", endpoints.target[url_key]))
            migration_jobs.append(job_summary)
            if not job_summary.get("row_counts_match", False):
                migration_ok = False

        summary["migration"] = {
            "jobs": migration_jobs,
            "row_counts_match": migration_ok,
            "duration_seconds": round(time.monotonic() - migration_started, 3),
        }
        if not migration_ok:
            return _finalize_summary(summary, run_dir, None)

        verify_result = _run_database_init_command(
            arguments=["--verify-target", "all", "--json", "--quiet"],
            environment=environment,
            log_path=logs_dir / "verify.log",
        )
        summary["steps"]["verify"] = verify_result.as_json()
        if verify_result.stdout:
            summary["verification"] = extract_json_payload(verify_result.stdout)
        if verify_result.returncode != 0:
            return _finalize_summary(summary, run_dir, None)

        health_result = _run_health_check(
            environment=environment,
            pid_file=pid_file,
            timeout_seconds=health_timeout,
            log_path=logs_dir / "start.log",
        )
        summary["steps"]["start_app"] = health_result["start_command"].as_json()
        summary["health_check"] = health_result["health"]
        if not health_result["health"]["ok"]:
            return _finalize_summary(summary, run_dir, None)

        summary["env_summary"] = {key: redact_url(value) for key, value in endpoints.target.items()}

        return _finalize_summary(summary, run_dir, None)
    finally:
        _stop_server_if_running(pid_file)
        if current_started_services and target.manages_services and not keep_services:
            compose_down_environment = environment or build_runtime_environment(target, pid_file)
            compose_down_result = _run_compose_down(
                target,
                compose_down_environment,
                logs_dir / "compose-down.log",
            )
            summary["steps"]["compose_down"] = compose_down_result.as_json()
            _write_summary_files(run_dir, summary)


def parse_args(argv: list[str] | None = None) -> Any:
    import argparse

    parser = argparse.ArgumentParser(description="執行資料庫 cutover smoke / rehearsal workflow")
    parser.add_argument(
        "--target",
        choices=["sqlite", "mysql", "postgres"],
        required=True,
        help="要驗證的資料庫 target",
    )
    parser.add_argument(
        "--mode",
        choices=["preflight", "smoke", "rehearsal", "migrate"],
        default="smoke",
        help="workflow 模式；migrate 為單一指令端到端搬移（schema bootstrap + 資料搬移 + 逐表覆核 + 驗證 + 健康檢查）",
    )
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="輸出 run artifacts 的根目錄",
    )
    parser.add_argument(
        "--manage-services",
        action="store_true",
        help="自動啟動/關閉 MySQL 或 PostgreSQL docker compose 服務",
    )
    parser.add_argument(
        "--keep-services",
        action="store_true",
        help="搭配 --manage-services 使用；workflow 完成後保留資料庫容器",
    )
    parser.add_argument(
        "--health-timeout",
        type=int,
        default=90,
        help="等待應用程式健康檢查成功的秒數",
    )
    parser.add_argument(
        "--baseline-summary",
        help="rehearsal 比對用的 baseline summary.json 路徑（僅適用 rehearsal，不可與 --mode migrate 併用）",
    )
    parser.add_argument(
        "--target-env-file",
        help="migrate 模式：指向目標資料庫連線設定的 env 檔"
        "（含 DATABASE_URL/SYNC_DATABASE_URL/AUDIT_DATABASE_URL/USM_DATABASE_URL）；"
        "未提供且帶 --manage-services 時退回 disposable compose 目標",
    )
    parser.add_argument(
        "--source-env-file",
        help="migrate 模式：指向來源資料庫連線設定的 env 檔；未提供時使用目前 app 環境實際解析到的來源",
    )
    parser.add_argument(
        "--force-reset-target",
        action="store_true",
        help="migrate 模式：目標三庫已有業務資料時仍強制清空重灌"
        "（破壞性操作，會清空目標 main/audit/usm 三庫全部既有業務資料）",
    )
    parser.add_argument(
        "--migrate-disable-constraints",
        action="store_true",
        help="migrate 模式：搬移時透傳 db_cross_migrate 的 --disable-constraints（來源存在循環 FK 時使用）",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.mode == "migrate" and args.baseline_summary:
        print(
            json.dumps(
                {"error": "--baseline-summary 僅適用於 rehearsal 模式，不可與 --mode migrate 併用"},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    summary = run_cutover_workflow(
        target_name=args.target,
        mode=args.mode,
        output_root=Path(args.output_root),
        manage_services=bool(args.manage_services),
        keep_services=bool(args.keep_services),
        health_timeout=int(args.health_timeout),
        baseline_summary_path=Path(args.baseline_summary).resolve()
        if args.baseline_summary
        else None,
        target_env_file=args.target_env_file,
        source_env_file=args.source_env_file,
        force_reset_target=bool(args.force_reset_target),
        migrate_disable_constraints=bool(args.migrate_disable_constraints),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["success"] else 1


def _verification_target_map(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    targets = summary.get("verification", {}).get("targets", [])
    return {str(item["target"]): item for item in targets if isinstance(item, dict)}


def _run_guardrails() -> dict[str, Any]:
    from app.db_access.guardrails import format_guardrail_violations, scan_db_access_guardrails

    violations = scan_db_access_guardrails(PROJECT_ROOT)
    return {
        "passed": not violations,
        "message": format_guardrail_violations(violations),
        "violations": [asdict(item) for item in violations],
    }


def _run_database_init_command(
    *,
    arguments: list[str],
    environment: dict[str, str],
    log_path: Path,
) -> CommandResult:
    command = [sys.executable, str(PROJECT_ROOT / "database_init.py"), *arguments]
    return _run_command(
        command=command,
        environment=environment,
        log_path=log_path,
    )


def _run_compose_up(
    target: WorkflowTarget,
    environment: dict[str, str],
    log_path: Path,
) -> CommandResult:
    return _run_command(
        command=[
            "docker",
            "compose",
            "-f",
            str(PROJECT_ROOT / str(target.compose_file)),
            "up",
            "-d",
            "--wait",
        ],
        environment=environment,
        log_path=log_path,
    )


def _run_compose_down(
    target: WorkflowTarget,
    environment: dict[str, str],
    log_path: Path,
) -> CommandResult:
    return _run_command(
        command=[
            "docker",
            "compose",
            "-f",
            str(PROJECT_ROOT / str(target.compose_file)),
            "down",
            "-v",
        ],
        environment=environment,
        log_path=log_path,
    )


def _run_command(
    *,
    command: list[str],
    environment: dict[str, str],
    log_path: Path,
) -> CommandResult:
    start_time = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    duration = time.monotonic() - start_time
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        _format_command_log(command, completed.stdout, completed.stderr, completed.returncode),
        encoding="utf-8",
    )
    return CommandResult(
        command=command,
        returncode=completed.returncode,
        duration_seconds=duration,
        stdout=completed.stdout,
        stderr=completed.stderr,
        log_path=str(log_path),
    )


def _run_health_check(
    *,
    environment: dict[str, str],
    pid_file: Path,
    timeout_seconds: int,
    log_path: Path,
) -> dict[str, Any]:
    start_command = _run_start_script(environment, log_path)
    health_result = {
        "ok": False,
        "url": f"http://127.0.0.1:{environment['PORT']}/health",
        "status_code": None,
        "body": None,
        "error": None,
    }
    if start_command.returncode != 0:
        health_result["error"] = "start.sh failed"
        return {"start_command": start_command, "health": health_result}

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not pid_file.exists():
            time.sleep(1)
            continue
        try:
            response = requests.get(health_result["url"], timeout=3)
            health_result["status_code"] = response.status_code
            health_result["body"] = response.text
            if response.ok:
                health_result["ok"] = True
                health_result["error"] = None
                break
        except Exception as exc:  # pragma: no cover - exercised by live workflow
            health_result["error"] = str(exc)
        time.sleep(1)

    if not health_result["ok"] and health_result["error"] is None:
        health_result["error"] = f"health check timed out after {timeout_seconds}s"
    return {"start_command": start_command, "health": health_result}


def _run_start_script(environment: dict[str, str], log_path: Path) -> CommandResult:
    command = ["bash", str(PROJECT_ROOT / "start.sh")]
    start_time = time.monotonic()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log_handle:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            env=environment,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    duration = time.monotonic() - start_time
    return CommandResult(
        command=command,
        returncode=completed.returncode,
        duration_seconds=duration,
        log_path=str(log_path),
    )


def _stop_server_if_running(pid_file: Path) -> None:
    if not pid_file.exists():
        return
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except Exception:
        pid_file.unlink(missing_ok=True)
        return

    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            break
        except Exception:
            break
        time.sleep(1)
        if not _process_exists(pid):
            break
    pid_file.unlink(missing_ok=True)


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _finalize_summary(
    summary: dict[str, Any],
    run_dir: Path,
    baseline_summary_path: Path | None,
) -> dict[str, Any]:
    if baseline_summary_path is not None and "comparison" not in summary:
        summary["baseline_summary_path"] = str(baseline_summary_path)
    summary["success"] = _compute_success(summary)
    _write_summary_files(run_dir, summary)
    return summary


def _write_summary_files(run_dir: Path, summary: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "summary.md").write_text(render_markdown_summary(summary), encoding="utf-8")


def _compute_success(summary: dict[str, Any]) -> bool:
    guardrails_passed = bool(summary.get("guardrails", {}).get("passed"))
    preflight_rc = int(summary.get("steps", {}).get("preflight", {}).get("returncode", 1))
    if summary["mode"] == "preflight":
        return guardrails_passed and preflight_rc == 0

    bootstrap_rc = int(summary.get("steps", {}).get("bootstrap", {}).get("returncode", 1))
    verify_rc = int(summary.get("steps", {}).get("verify", {}).get("returncode", 1))
    health_ok = bool((summary.get("health_check") or {}).get("ok"))
    comparison_ok = bool(summary.get("comparison", {}).get("matches", True))
    return (
        guardrails_passed
        and preflight_rc == 0
        and bootstrap_rc == 0
        and verify_rc == 0
        and health_ok
        and comparison_ok
    )


def _format_command_log(
    command: Iterable[str],
    stdout: str,
    stderr: str,
    returncode: int,
) -> str:
    rendered_command = " ".join(command)
    return (
        f"$ {rendered_command}\n"
        f"[returncode] {returncode}\n\n"
        f"[stdout]\n{stdout}\n"
        f"[stderr]\n{stderr}\n"
    )
