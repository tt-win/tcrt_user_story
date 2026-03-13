from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.audit.database import AuditDatabaseManager
from app.db_migrations import (
    LegacyDatabaseAdoptionRequiredError,
    adopt_legacy_database,
    get_sync_engine_for_target,
    upgrade_database,
    validate_legacy_database,
)
from app.models import user_story_map_db
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
)


def _sqlite_url(db_path: Path) -> str:
    return f"sqlite:///{db_path}"


@pytest.mark.parametrize(
    ("target_name", "required_tables"),
    [
        ("audit", {"audit_logs"}),
        ("usm", {"user_story_maps", "user_story_map_nodes"}),
    ],
)
def test_auxiliary_database_requires_explicit_adoption(
    tmp_path: Path,
    target_name: str,
    required_tables: set[str],
) -> None:
    db_path = tmp_path / f"{target_name}.db"
    database_url = _sqlite_url(db_path)

    upgrade_database(database_url=database_url, target_name=target_name)

    engine = get_sync_engine_for_target(target_name, database_url=database_url)
    try:
        inspector = inspect(engine)
        assert required_tables.issubset(set(inspector.get_table_names()))

        with engine.begin() as conn:
            conn.execute(text("DROP TABLE alembic_version"))
    finally:
        engine.dispose()

    assert validate_legacy_database(database_url=database_url, target_name=target_name) == []

    with pytest.raises(LegacyDatabaseAdoptionRequiredError):
        upgrade_database(database_url=database_url, target_name=target_name)

    baseline_revision = adopt_legacy_database(database_url=database_url, target_name=target_name)
    assert baseline_revision

    engine = get_sync_engine_for_target(target_name, database_url=database_url)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == baseline_revision
    finally:
        engine.dispose()


def test_audit_legacy_varchar_enum_schema_is_treated_as_compatible(tmp_path: Path) -> None:
    db_path = tmp_path / "audit_legacy.db"
    database_url = _sqlite_url(db_path)
    engine = get_sync_engine_for_target("audit", database_url=database_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE audit_logs (
                        id INTEGER NOT NULL,
                        timestamp DATETIME NOT NULL,
                        user_id INTEGER NOT NULL,
                        username VARCHAR(100) NOT NULL,
                        role VARCHAR(50) NOT NULL,
                        action_type VARCHAR(6) NOT NULL,
                        resource_type VARCHAR(12) NOT NULL,
                        resource_id VARCHAR(100) NOT NULL,
                        team_id INTEGER NOT NULL,
                        details TEXT,
                        action_brief VARCHAR(500),
                        severity VARCHAR(8) NOT NULL,
                        ip_address VARCHAR(45),
                        user_agent VARCHAR(500),
                        PRIMARY KEY (id)
                    )
                    """
                )
            )
            for ddl in (
                "CREATE INDEX ix_audit_logs_resource_id ON audit_logs (resource_id)",
                "CREATE INDEX ix_audit_logs_action_type ON audit_logs (action_type)",
                "CREATE INDEX ix_audit_logs_resource_type ON audit_logs (resource_type)",
                "CREATE INDEX ix_audit_logs_user_id ON audit_logs (user_id)",
                "CREATE INDEX ix_audit_logs_severity ON audit_logs (severity)",
                "CREATE INDEX idx_audit_user_time ON audit_logs (user_id, timestamp)",
                "CREATE INDEX idx_audit_resource ON audit_logs (resource_type, resource_id)",
                "CREATE INDEX idx_audit_severity_time ON audit_logs (severity, timestamp)",
                "CREATE INDEX ix_audit_logs_role ON audit_logs (role)",
                "CREATE INDEX idx_audit_action_time ON audit_logs (action_type, timestamp)",
                "CREATE INDEX idx_audit_role_time ON audit_logs (role, timestamp)",
                "CREATE INDEX idx_audit_username_time ON audit_logs (username, timestamp)",
                "CREATE INDEX ix_audit_logs_team_id ON audit_logs (team_id)",
                "CREATE INDEX ix_audit_logs_username ON audit_logs (username)",
                "CREATE INDEX ix_audit_logs_timestamp ON audit_logs (timestamp)",
                "CREATE INDEX idx_audit_time_team ON audit_logs (timestamp, team_id)",
            ):
                conn.execute(text(ddl))
    finally:
        engine.dispose()

    assert validate_legacy_database(database_url=database_url, target_name="audit") == []


@pytest.mark.parametrize(
    ("target_name", "required_tables"),
    [
        ("audit", {"audit_logs"}),
        ("usm", {"user_story_maps", "user_story_map_nodes"}),
    ],
)
def test_managed_test_database_helper_supports_auxiliary_targets(
    tmp_path: Path,
    target_name: str,
    required_tables: set[str],
) -> None:
    database_bundle = create_managed_test_database(
        tmp_path / f"{target_name}.db",
        target_name=target_name,
    )
    try:
        inspector = inspect(database_bundle["sync_engine"])
        assert required_tables.issubset(set(inspector.get_table_names()))
    finally:
        dispose_managed_test_database(database_bundle)


@pytest.mark.asyncio
async def test_audit_initialize_does_not_mutate_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "audit_runtime.db"
    manager = AuditDatabaseManager()
    manager.config.database_url = _sqlite_url(db_path)

    await manager.initialize()
    await manager.cleanup()

    engine = get_sync_engine_for_target("audit", database_url=_sqlite_url(db_path))
    try:
        assert inspect(engine).get_table_names() == []
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_usm_initialize_does_not_mutate_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "usm_runtime.db"
    async_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        poolclass=NullPool,
        connect_args={
            "check_same_thread": False,
            "timeout": 30,
        },
    )
    monkeypatch.setattr(user_story_map_db, "usm_engine", async_engine)

    try:
        await user_story_map_db.init_usm_db()
    finally:
        await async_engine.dispose()

    engine = get_sync_engine_for_target("usm", database_url=_sqlite_url(db_path))
    try:
        assert inspect(engine).get_table_names() == []
    finally:
        engine.dispose()
