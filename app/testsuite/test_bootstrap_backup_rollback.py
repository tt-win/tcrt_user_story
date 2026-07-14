"""database_init.py 開機升版守護（pending 偵測 → 備份 → 升版 → 失敗回退）端到端測試。

全程使用 SQLite + tmp_path，透過直接改 alembic_version 建構「有 pending 升版」的既有系統，
不依賴任何外部服務。設計依據：openspec/changes/add-boot-upgrade-backup-rollback/design.md。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from alembic import command as alembic_command

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import database_init
from app import db_migrations
from app.db_migrations import _get_baseline_revision, build_alembic_config


def _configure_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Path]:
    main_db = tmp_path / "main.db"
    audit_db = tmp_path / "audit.db"
    usm_db = tmp_path / "usm.db"
    backup_dir = tmp_path / "backups"

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{main_db}")
    monkeypatch.setenv("SYNC_DATABASE_URL", f"sqlite:///{main_db}")
    monkeypatch.setenv("AUDIT_DATABASE_URL", f"sqlite:///{audit_db}")
    monkeypatch.setenv("USM_DATABASE_URL", f"sqlite:///{usm_db}")
    monkeypatch.setenv("BOOTSTRAP_BACKUP_DIR", str(backup_dir))
    monkeypatch.delenv("BOOTSTRAP_BACKUP_MODE", raising=False)
    monkeypatch.delenv("BOOTSTRAP_ON_FAILURE", raising=False)
    monkeypatch.delenv("BOOTSTRAP_MAX_UPGRADE_ATTEMPTS", raising=False)
    monkeypatch.delenv("BOOTSTRAP_BACKUP_RETENTION", raising=False)
    monkeypatch.delenv("BOOTSTRAP_SUPER_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("BOOTSTRAP_SUPER_ADMIN_PASSWORD", raising=False)

    return {"main": main_db, "audit": audit_db, "usm": usm_db, "backup_dir": backup_dir}


def _upgrade_to_revision(database_url: str, target_name: str, revision: str) -> None:
    cfg = build_alembic_config(database_url, target_name=target_name)
    alembic_command.upgrade(cfg, revision)


def _backup_files(backup_dir: Path, target_name: str | None = None) -> list[Path]:
    if not backup_dir.exists():
        return []
    roots = [backup_dir / target_name] if target_name else list(backup_dir.iterdir())
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        files.extend(
            p for p in root.iterdir() if p.is_file() and not p.name.endswith(".meta.json") and p.name != "upgrade-failure.json"
        )
    return files


def test_fresh_bootstrap_then_repeat_boot_creates_no_backups(monkeypatch, tmp_path) -> None:
    paths = _configure_env(monkeypatch, tmp_path)

    assert database_init.main([]) == 0
    assert _backup_files(paths["backup_dir"]) == []

    assert database_init.main([]) == 0
    assert _backup_files(paths["backup_dir"]) == []


def test_pending_target_backs_up_and_upgrades(monkeypatch, tmp_path) -> None:
    paths = _configure_env(monkeypatch, tmp_path)

    _upgrade_to_revision(f"sqlite:///{paths['main']}", "main", "head")
    _upgrade_to_revision(f"sqlite:///{paths['audit']}", "audit", "head")
    usm_url = f"sqlite:///{paths['usm']}"
    usm_cfg = build_alembic_config(usm_url, target_name="usm")
    baseline = _get_baseline_revision(usm_cfg)
    _upgrade_to_revision(usm_url, "usm", baseline)

    exit_code = database_init.main([])

    assert exit_code == 0
    backups = _backup_files(paths["backup_dir"], "usm")
    assert len(backups) == 1
    assert not (paths["backup_dir"] / "usm" / "upgrade-failure.json").exists()

    status = db_migrations.get_pending_status("usm", database_url=usm_url)
    assert status.is_pending is False


def test_upgrade_failure_with_rollback_restores_database(monkeypatch, tmp_path) -> None:
    paths = _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv("BOOTSTRAP_ON_FAILURE", "rollback")

    _upgrade_to_revision(f"sqlite:///{paths['main']}", "main", "head")
    _upgrade_to_revision(f"sqlite:///{paths['audit']}", "audit", "head")
    usm_url = f"sqlite:///{paths['usm']}"
    usm_cfg = build_alembic_config(usm_url, target_name="usm")
    baseline = _get_baseline_revision(usm_cfg)
    _upgrade_to_revision(usm_url, "usm", baseline)

    def _boom():
        raise RuntimeError("simulated migration failure")

    monkeypatch.setitem(database_init.TARGET_UPGRADERS, "usm", _boom)

    exit_code = database_init.main([])

    assert exit_code == 8
    status = db_migrations.get_pending_status("usm", database_url=usm_url)
    assert status.current == baseline

    marker = database_init.read_failure_marker(paths["backup_dir"], "usm")
    assert marker is not None
    assert marker["attempts"] == 1
    assert marker["rolled_back"] is True


def test_repeated_failure_hits_max_attempts(monkeypatch, tmp_path) -> None:
    paths = _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv("BOOTSTRAP_ON_FAILURE", "rollback")
    monkeypatch.setenv("BOOTSTRAP_MAX_UPGRADE_ATTEMPTS", "3")

    _upgrade_to_revision(f"sqlite:///{paths['main']}", "main", "head")
    _upgrade_to_revision(f"sqlite:///{paths['audit']}", "audit", "head")
    usm_url = f"sqlite:///{paths['usm']}"
    usm_cfg = build_alembic_config(usm_url, target_name="usm")
    baseline = _get_baseline_revision(usm_cfg)
    _upgrade_to_revision(usm_url, "usm", baseline)

    def _boom():
        raise RuntimeError("simulated migration failure")

    monkeypatch.setitem(database_init.TARGET_UPGRADERS, "usm", _boom)

    assert database_init.main([]) == 8
    assert database_init.main([]) == 8
    assert database_init.main([]) == 8
    assert database_init.main([]) == 10

    marker = database_init.read_failure_marker(paths["backup_dir"], "usm")
    assert marker["attempts"] == 3


def test_clear_failure_markers_allows_retry(monkeypatch, tmp_path) -> None:
    paths = _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv("BOOTSTRAP_ON_FAILURE", "rollback")
    monkeypatch.setenv("BOOTSTRAP_MAX_UPGRADE_ATTEMPTS", "1")

    _upgrade_to_revision(f"sqlite:///{paths['main']}", "main", "head")
    _upgrade_to_revision(f"sqlite:///{paths['audit']}", "audit", "head")
    usm_url = f"sqlite:///{paths['usm']}"
    usm_cfg = build_alembic_config(usm_url, target_name="usm")
    baseline = _get_baseline_revision(usm_cfg)
    _upgrade_to_revision(usm_url, "usm", baseline)

    def _boom():
        raise RuntimeError("simulated migration failure")

    monkeypatch.setitem(database_init.TARGET_UPGRADERS, "usm", _boom)

    assert database_init.main([]) == 8
    assert database_init.main([]) == 10

    assert database_init.main(["--clear-failure-markers"]) == 0
    assert database_init.read_failure_marker(paths["backup_dir"], "usm") is None

    monkeypatch.setitem(database_init.TARGET_UPGRADERS, "usm", db_migrations.upgrade_usm_database)
    assert database_init.main([]) == 0
    status = db_migrations.get_pending_status("usm", database_url=usm_url)
    assert status.is_pending is False


def test_multi_target_failure_rolls_back_earlier_success(monkeypatch, tmp_path) -> None:
    paths = _configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv("BOOTSTRAP_ON_FAILURE", "rollback")

    main_url = f"sqlite:///{paths['main']}"
    main_cfg = build_alembic_config(main_url, target_name="main")
    main_baseline = _get_baseline_revision(main_cfg)
    _upgrade_to_revision(main_url, "main", main_baseline)  # main：有 pending，本輪會升級成功

    audit_url = f"sqlite:///{paths['audit']}"
    audit_cfg = build_alembic_config(audit_url, target_name="audit")
    audit_baseline = _get_baseline_revision(audit_cfg)
    _upgrade_to_revision(audit_url, "audit", audit_baseline)  # audit：有 pending，稍後注入失敗

    _upgrade_to_revision(f"sqlite:///{paths['usm']}", "usm", "head")  # usm 已最新，不受影響

    def _boom():
        raise RuntimeError("simulated audit migration failure")

    monkeypatch.setitem(database_init.TARGET_UPGRADERS, "audit", _boom)

    exit_code = database_init.main([])

    assert exit_code == 8
    main_status = db_migrations.get_pending_status("main", database_url=main_url)
    assert main_status.current == main_baseline  # main 雖升級成功，仍因 audit 失敗被回退

    assert len(_backup_files(paths["backup_dir"], "main")) == 1
    assert len(_backup_files(paths["backup_dir"], "audit")) == 1
