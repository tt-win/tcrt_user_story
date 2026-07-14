"""Bootstrap 專用的升版前備份／回退／failure-marker 模組。

設計依據：openspec/changes/add-boot-upgrade-backup-rollback/design.md（D2-D7）。

僅供 ``database_init.py`` 的 bootstrap 流程呼叫；使用 sync engine 與 subprocess，
依專案慣例（migration/bootstrap 場景例外）允許，但不得被 web runtime import 使用。
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.pool import NullPool

_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
_FAILURE_MARKER_NAME = "upgrade-failure.json"
_TOOL_VERSION = 1

_ENGINE_EXTENSIONS = {
    "sqlite": "sqlite3",
    "mysql": "sql.gz",
    "postgresql": "pgdump",
}


class BackupError(RuntimeError):
    """升版前備份失敗（缺 dump client、目錄不可寫、dump/連線失敗等）。"""


class RestoreError(RuntimeError):
    """升版失敗後回退還原失敗，需人工介入。"""


@dataclass(frozen=True)
class BackupResult:
    target: str
    engine: str
    path: Path
    from_revision: str | None
    to_revision: str


def engine_key_for_url(database_url: str) -> str:
    backend = make_url(database_url).get_backend_name().lower()
    if backend in ("mysql", "mariadb"):
        return "mysql"
    if backend == "postgresql":
        return "postgresql"
    return "sqlite"


def _backup_filename(from_revision: str | None, to_revision: str, ext: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime(_TIMESTAMP_FORMAT)
    from_part = from_revision or "none"
    return f"{timestamp}__{from_part}__{to_revision}.{ext}"


def _meta_path(backup_path: Path) -> Path:
    return backup_path.with_name(backup_path.name + ".meta.json")


def _write_meta(result: BackupResult, database_url: str) -> None:
    url = make_url(database_url)
    meta = {
        "target": result.target,
        "engine": result.engine,
        "database": url.database,
        "from_revision": result.from_revision,
        "to_revision": result.to_revision,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tool_version": _TOOL_VERSION,
    }
    _meta_path(result.path).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def create_backup(
    target_name: str,
    *,
    database_url: str,
    from_revision: str | None,
    to_revision: str,
    backup_dir: Path,
) -> BackupResult:
    """依資料庫引擎建立升版前備份。呼叫前提：pending.is_pending 且非 pending.is_fresh。"""
    engine_key = engine_key_for_url(database_url)
    target_dir = backup_dir / target_name
    target_dir.mkdir(parents=True, exist_ok=True)
    ext = _ENGINE_EXTENSIONS[engine_key]
    backup_path = target_dir / _backup_filename(from_revision, to_revision, ext)

    if engine_key == "sqlite":
        _backup_sqlite(database_url, backup_path)
    elif engine_key == "mysql":
        _backup_mysql(database_url, backup_path)
    else:
        _backup_postgresql(database_url, backup_path)

    result = BackupResult(
        target=target_name,
        engine=engine_key,
        path=backup_path,
        from_revision=from_revision,
        to_revision=to_revision,
    )
    _write_meta(result, database_url)
    return result


def restore_backup(result: BackupResult, *, database_url: str) -> None:
    if result.engine == "sqlite":
        _restore_sqlite(database_url, result.path)
    elif result.engine == "mysql":
        _restore_mysql(database_url, result.path)
    else:
        _restore_postgresql(database_url, result.path)


def _parse_backup_timestamp(filename: str) -> str | None:
    prefix, sep, _rest = filename.partition("__")
    if not sep:
        return None
    if len(prefix) == 16 and prefix[8] == "T" and prefix.endswith("Z"):
        return prefix
    return None


def apply_retention(backup_dir: Path, target_name: str, keep: int) -> list[Path]:
    """保留最近 keep 份備份（依檔名時戳排序），刪除其餘備份與其 sidecar。"""
    target_dir = backup_dir / target_name
    if not target_dir.exists():
        return []

    candidates: list[tuple[str, Path]] = []
    for entry in target_dir.iterdir():
        if not entry.is_file() or entry.name.endswith(".meta.json") or entry.name == _FAILURE_MARKER_NAME:
            continue
        timestamp = _parse_backup_timestamp(entry.name)
        if timestamp is None:
            continue
        candidates.append((timestamp, entry))

    candidates.sort(key=lambda item: item[0], reverse=True)
    removed: list[Path] = []
    for _, path in candidates[keep:]:
        path.unlink(missing_ok=True)
        _meta_path(path).unlink(missing_ok=True)
        removed.append(path)
    return removed


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------


def _sqlite_path(database_url: str) -> Path:
    url = make_url(database_url)
    database = url.database
    if not database or database == ":memory:":
        raise BackupError(f"SQLite URL 沒有實體檔案路徑，無法備份/還原：{database_url}")
    return Path(database)


def _backup_sqlite(database_url: str, backup_path: Path) -> None:
    db_path = _sqlite_path(database_url)
    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        destination = sqlite3.connect(str(backup_path))
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()


def _restore_sqlite(database_url: str, backup_path: Path) -> None:
    db_path = _sqlite_path(database_url)
    source = sqlite3.connect(str(backup_path))
    try:
        destination = sqlite3.connect(str(db_path))
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
    for suffix in ("-wal", "-shm"):
        stray = Path(str(db_path) + suffix)
        if stray.exists():
            stray.unlink()


# ---------------------------------------------------------------------------
# MySQL / MariaDB
# ---------------------------------------------------------------------------


def _mysql_conn_args(url: URL) -> tuple[list[str], dict[str, str]]:
    args: list[str] = []
    if url.host:
        args += ["--host", url.host]
    if url.port:
        args += ["--port", str(url.port)]
    if url.username:
        args += ["--user", url.username]
    env = dict(os.environ)
    if url.password:
        env["MYSQL_PWD"] = url.password
    return args, env


def _backup_mysql(database_url: str, backup_path: Path) -> None:
    if shutil.which("mysqldump") is None:
        raise BackupError("找不到 mysqldump，無法備份 MySQL/MariaDB target；請於 image 安裝 mysql client 工具")
    url = make_url(database_url)
    if not url.database:
        raise BackupError(f"MySQL URL 缺少 database 名稱，無法備份：{database_url}")
    args, env = _mysql_conn_args(url)
    command = [
        "mysqldump",
        "--single-transaction",
        "--no-tablespaces",
        "--add-drop-table",
        "--routines",
        *args,
        url.database,
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    try:
        with gzip.open(backup_path, "wb") as gz_file:
            shutil.copyfileobj(process.stdout, gz_file)
        stderr_output = process.stderr.read() if process.stderr else b""
        returncode = process.wait()
    finally:
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()
    if returncode != 0:
        backup_path.unlink(missing_ok=True)
        raise BackupError(f"mysqldump 失敗（exit={returncode}）：{stderr_output.decode(errors='replace')[:2000]}")


def _drop_all_mysql_tables(database_url: str) -> None:
    engine = create_engine(database_url, poolclass=NullPool, future=True)
    try:
        database_name = make_url(database_url).database
        preparer = engine.dialect.identifier_preparer
        with engine.begin() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
            table_rows = conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :db AND table_type = 'BASE TABLE'"
                ),
                {"db": database_name},
            ).fetchall()
            for (table_name,) in table_rows:
                conn.execute(text(f"DROP TABLE IF EXISTS {preparer.quote(table_name)}"))
            conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    finally:
        engine.dispose()


def _restore_mysql(database_url: str, backup_path: Path) -> None:
    if shutil.which("mysql") is None:
        raise RestoreError("找不到 mysql client，無法還原 MySQL/MariaDB target")
    url = make_url(database_url)
    if not url.database:
        raise RestoreError(f"MySQL URL 缺少 database 名稱，無法還原：{database_url}")
    _drop_all_mysql_tables(database_url)
    args, env = _mysql_conn_args(url)
    command = ["mysql", *args, url.database]
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env
    )
    try:
        with gzip.open(backup_path, "rb") as gz_file:
            shutil.copyfileobj(gz_file, process.stdin)
        process.stdin.close()
        output = process.stdout.read() if process.stdout else b""
        returncode = process.wait()
    finally:
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        if process.stdout:
            process.stdout.close()
    if returncode != 0:
        raise RestoreError(f"mysql 還原失敗（exit={returncode}）：{output.decode(errors='replace')[:2000]}")


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------


def _pg_conn_args(url: URL) -> tuple[list[str], dict[str, str]]:
    args: list[str] = []
    if url.host:
        args += ["--host", url.host]
    if url.port:
        args += ["--port", str(url.port)]
    if url.username:
        args += ["--username", url.username]
    env = dict(os.environ)
    if url.password:
        env["PGPASSWORD"] = url.password
    return args, env


def _backup_postgresql(database_url: str, backup_path: Path) -> None:
    if shutil.which("pg_dump") is None:
        raise BackupError("找不到 pg_dump，無法備份 PostgreSQL target；請於 image 安裝 postgresql-client 工具")
    url = make_url(database_url)
    if not url.database:
        raise BackupError(f"PostgreSQL URL 缺少 database 名稱，無法備份：{database_url}")
    args, env = _pg_conn_args(url)
    command = ["pg_dump", "--format=custom", f"--file={backup_path}", *args, url.database]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, check=False)
    if result.returncode != 0:
        backup_path.unlink(missing_ok=True)
        raise BackupError(f"pg_dump 失敗（exit={result.returncode}）：{result.stderr.decode(errors='replace')[:2000]}")


def _reset_postgresql_schema(database_url: str) -> None:
    engine = create_engine(database_url, poolclass=NullPool, future=True)
    try:
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()


def _restore_postgresql(database_url: str, backup_path: Path) -> None:
    if shutil.which("pg_restore") is None:
        raise RestoreError("找不到 pg_restore，無法還原 PostgreSQL target")
    url = make_url(database_url)
    if not url.database:
        raise RestoreError(f"PostgreSQL URL 缺少 database 名稱，無法還原：{database_url}")
    _reset_postgresql_schema(database_url)
    args, env = _pg_conn_args(url)
    command = ["pg_restore", "--no-owner", *args, f"--dbname={url.database}", str(backup_path)]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, check=False)
    if result.returncode != 0:
        raise RestoreError(f"pg_restore 失敗（exit={result.returncode}）：{result.stderr.decode(errors='replace')[:2000]}")


# ---------------------------------------------------------------------------
# Failure marker（連續失敗防護，design D7）
# ---------------------------------------------------------------------------


def _marker_path(backup_dir: Path, target_name: str) -> Path:
    return backup_dir / target_name / _FAILURE_MARKER_NAME


def read_failure_marker(backup_dir: Path, target_name: str) -> dict[str, Any] | None:
    path = _marker_path(backup_dir, target_name)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def record_upgrade_failure(
    backup_dir: Path,
    target_name: str,
    *,
    head: str,
    from_revision: str | None,
    error: str,
    rolled_back: bool,
) -> dict[str, Any]:
    path = _marker_path(backup_dir, target_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_failure_marker(backup_dir, target_name)
    if existing and existing.get("head") == head:
        attempts = int(existing.get("attempts", 0)) + 1
    else:
        attempts = 1
    marker = {
        "target": target_name,
        "head": head,
        "from_revision": from_revision,
        "attempts": attempts,
        "last_error": str(error)[:2000],
        "last_attempt_at": datetime.now(timezone.utc).isoformat(),
        "rolled_back": rolled_back,
    }
    path.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
    return marker


def clear_failure_marker(backup_dir: Path, target_name: str) -> None:
    _marker_path(backup_dir, target_name).unlink(missing_ok=True)


def clear_all_failure_markers(backup_dir: Path, target_names: tuple[str, ...]) -> list[str]:
    cleared = []
    for target_name in target_names:
        path = _marker_path(backup_dir, target_name)
        if path.exists():
            path.unlink()
            cleared.append(target_name)
    return cleared
