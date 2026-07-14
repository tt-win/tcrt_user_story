from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest

from app.db_backup import (
    BackupError,
    apply_retention,
    clear_all_failure_markers,
    clear_failure_marker,
    create_backup,
    read_failure_marker,
    record_upgrade_failure,
    restore_backup,
)


def _sqlite_url(db_path: Path) -> str:
    return f"sqlite:///{db_path}"


def _make_source_db(db_path: Path, *, wal: bool = False) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        if wal:
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO widgets (name) VALUES ('a'), ('b'), ('c')")
        conn.commit()
    finally:
        conn.close()


def _count_widgets(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute("SELECT COUNT(*) FROM widgets").fetchone()[0]
    finally:
        conn.close()


def test_sqlite_backup_and_restore_roundtrip(tmp_path: Path) -> None:
    db_path = tmp_path / "main.db"
    _make_source_db(db_path)
    backup_dir = tmp_path / "backups"

    result = create_backup(
        "main",
        database_url=_sqlite_url(db_path),
        from_revision="abc123",
        to_revision="def456",
        backup_dir=backup_dir,
    )

    assert result.path.exists()
    assert _count_widgets(result.path) == 3

    # 模擬升版失敗留下的髒資料：加一列、砍一列。
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("INSERT INTO widgets (name) VALUES ('d')")
        conn.execute("DELETE FROM widgets WHERE name = 'a'")
        conn.commit()
    finally:
        conn.close()
    assert _count_widgets(db_path) == 3  # b, c, d

    restore_backup(result, database_url=_sqlite_url(db_path))

    assert _count_widgets(db_path) == 3
    conn = sqlite3.connect(str(db_path))
    try:
        names = {row[0] for row in conn.execute("SELECT name FROM widgets")}
    finally:
        conn.close()
    assert names == {"a", "b", "c"}


def test_sqlite_backup_captures_wal_data(tmp_path: Path) -> None:
    db_path = tmp_path / "main.db"
    _make_source_db(db_path, wal=True)
    backup_dir = tmp_path / "backups"

    result = create_backup(
        "main",
        database_url=_sqlite_url(db_path),
        from_revision=None,
        to_revision="head1",
        backup_dir=backup_dir,
    )

    assert _count_widgets(result.path) == 3


def test_backup_filename_and_sidecar_format(tmp_path: Path) -> None:
    db_path = tmp_path / "usm.db"
    _make_source_db(db_path)
    backup_dir = tmp_path / "backups"

    result = create_backup(
        "usm",
        database_url=_sqlite_url(db_path),
        from_revision=None,
        to_revision="7bc2e5a91d44",
        backup_dir=backup_dir,
    )

    assert result.path.parent == backup_dir / "usm"
    assert re.match(r"^\d{8}T\d{6}Z__none__7bc2e5a91d44\.sqlite3$", result.path.name)

    meta_path = result.path.with_name(result.path.name + ".meta.json")
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["target"] == "usm"
    assert meta["engine"] == "sqlite"
    assert meta["from_revision"] is None
    assert meta["to_revision"] == "7bc2e5a91d44"
    assert meta["tool_version"] == 1
    assert "created_at" in meta


def test_backup_missing_mysql_client_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.db_backup as db_backup_module

    monkeypatch.setattr(db_backup_module.shutil, "which", lambda _name: None)

    with pytest.raises(BackupError, match="mysqldump"):
        create_backup(
            "main",
            database_url="mysql+pymysql://user:pass@127.0.0.1:3306/tcrt_main",
            from_revision=None,
            to_revision="head1",
            backup_dir=tmp_path / "backups",
        )


def test_backup_missing_postgres_client_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.db_backup as db_backup_module

    monkeypatch.setattr(db_backup_module.shutil, "which", lambda _name: None)

    with pytest.raises(BackupError, match="pg_dump"):
        create_backup(
            "main",
            database_url="postgresql+psycopg://user:pass@127.0.0.1:5432/tcrt_main",
            from_revision=None,
            to_revision="head1",
            backup_dir=tmp_path / "backups",
        )


def _make_fake_backup(target_dir: Path, timestamp: str) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{timestamp}__none__head1.sqlite3"
    path.write_bytes(b"fake")
    path.with_name(path.name + ".meta.json").write_text("{}", encoding="utf-8")
    return path


def test_apply_retention_keeps_most_recent_n(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    target_dir = backup_dir / "main"
    timestamps = [f"2026010{i}T000000Z" for i in range(1, 7)]  # 6 份，時序遞增
    for ts in timestamps:
        _make_fake_backup(target_dir, ts)

    removed = apply_retention(backup_dir, "main", keep=3)

    remaining = sorted(p.name for p in target_dir.iterdir() if not p.name.endswith(".meta.json"))
    assert len(remaining) == 3
    # 保留最新 3 份（時戳最大的三個）
    assert remaining == [
        "20260104T000000Z__none__head1.sqlite3",
        "20260105T000000Z__none__head1.sqlite3",
        "20260106T000000Z__none__head1.sqlite3",
    ]
    assert len(removed) == 3
    for removed_path in removed:
        assert not removed_path.exists()
        assert not removed_path.with_name(removed_path.name + ".meta.json").exists()


def test_apply_retention_keep_one(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    target_dir = backup_dir / "main"
    for i in range(1, 4):
        _make_fake_backup(target_dir, f"2026010{i}T000000Z")

    apply_retention(backup_dir, "main", keep=1)

    remaining = [p for p in target_dir.iterdir() if not p.name.endswith(".meta.json")]
    assert len(remaining) == 1
    assert remaining[0].name.startswith("20260103T000000Z")


def test_apply_retention_no_removal_when_under_limit(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    target_dir = backup_dir / "main"
    for i in range(1, 3):
        _make_fake_backup(target_dir, f"2026010{i}T000000Z")

    removed = apply_retention(backup_dir, "main", keep=10)

    assert removed == []
    assert len([p for p in target_dir.iterdir() if not p.name.endswith(".meta.json")]) == 2


def test_apply_retention_missing_target_dir_is_noop(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    assert apply_retention(backup_dir, "main", keep=5) == []


def test_marker_accumulates_attempts_for_same_head(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    record_upgrade_failure(backup_dir, "main", head="h1", from_revision="f0", error="boom", rolled_back=False)
    marker = record_upgrade_failure(backup_dir, "main", head="h1", from_revision="f0", error="boom2", rolled_back=True)

    assert marker["attempts"] == 2
    assert marker["rolled_back"] is True
    assert marker["last_error"] == "boom2"


def test_marker_resets_attempts_on_new_head(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    record_upgrade_failure(backup_dir, "main", head="h1", from_revision="f0", error="boom", rolled_back=False)
    marker = record_upgrade_failure(backup_dir, "main", head="h2", from_revision="h1", error="boom2", rolled_back=False)

    assert marker["attempts"] == 1
    assert marker["head"] == "h2"


def test_clear_failure_marker(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    record_upgrade_failure(backup_dir, "main", head="h1", from_revision=None, error="x", rolled_back=False)
    assert read_failure_marker(backup_dir, "main") is not None

    clear_failure_marker(backup_dir, "main")

    assert read_failure_marker(backup_dir, "main") is None


def test_clear_all_failure_markers(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    record_upgrade_failure(backup_dir, "main", head="h1", from_revision=None, error="x", rolled_back=False)
    record_upgrade_failure(backup_dir, "audit", head="h2", from_revision=None, error="y", rolled_back=False)

    cleared = clear_all_failure_markers(backup_dir, ("main", "audit", "usm"))

    assert set(cleared) == {"main", "audit"}
    assert read_failure_marker(backup_dir, "main") is None
    assert read_failure_marker(backup_dir, "audit") is None
