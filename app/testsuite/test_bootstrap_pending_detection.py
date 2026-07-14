from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from app.db_migrations import (
    _get_baseline_revision,
    build_alembic_config,
    get_pending_status,
    get_sync_engine_for_target,
    upgrade_database,
)


def _sqlite_url(db_path: Path) -> str:
    return f"sqlite:///{db_path}"


def test_empty_database_is_fresh_and_pending(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path / "usm.db")

    status = get_pending_status("usm", database_url=database_url)

    assert status.is_fresh is True
    assert status.is_pending is True
    assert status.current is None
    assert status.head


def test_up_to_date_database_is_not_pending(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path / "usm.db")
    upgrade_database(database_url=database_url, target_name="usm")

    status = get_pending_status("usm", database_url=database_url)

    assert status.is_pending is False
    assert status.is_fresh is False
    assert status.current == status.head


def test_stale_revision_is_pending_but_not_fresh(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path / "usm.db")
    upgrade_database(database_url=database_url, target_name="usm")

    cfg = build_alembic_config(database_url, target_name="usm")
    baseline_revision = _get_baseline_revision(cfg)

    engine = get_sync_engine_for_target("usm", database_url=database_url)
    try:
        with engine.begin() as conn:
            conn.execute(text("UPDATE alembic_version SET version_num = :rev"), {"rev": baseline_revision})
    finally:
        engine.dispose()

    status = get_pending_status("usm", database_url=database_url)

    assert status.is_pending is True
    assert status.is_fresh is False
    assert status.current == baseline_revision
    assert status.current != status.head


def test_legacy_unmanaged_database_is_pending_but_not_fresh(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path / "usm.db")
    upgrade_database(database_url=database_url, target_name="usm")

    engine = get_sync_engine_for_target("usm", database_url=database_url)
    try:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE alembic_version"))
    finally:
        engine.dispose()

    status = get_pending_status("usm", database_url=database_url)

    assert status.is_pending is True
    assert status.is_fresh is False
    assert status.current is None
