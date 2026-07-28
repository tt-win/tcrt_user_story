from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import importlib
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db_migrations import upgrade_database
from app.db_url import normalize_async_database_url, normalize_sync_database_url


class _DiscardAuditSession:
    """Minimal sink for API tests that do not install an audit database."""

    def add_all(self, _records) -> None:
        pass

    async def commit(self) -> None:
        pass


class _DiscardAuditDatabaseManager:
    """Prevent disposable API tests from touching the developer's audit DB."""

    @asynccontextmanager
    async def get_session(self):
        yield _DiscardAuditSession()


def _patch_audit_service_manager(monkeypatch, manager) -> None:
    import importlib

    audit_database = importlib.import_module("app.audit.database")
    audit_service_module = importlib.import_module("app.audit.audit_service")
    monkeypatch.setattr(audit_database, "audit_db_manager", manager)
    monkeypatch.setattr(audit_service_module, "audit_db_manager", manager)


def sqlite_database_url(db_path: Path) -> str:
    return f"sqlite:///{db_path}"


def create_managed_test_database(
    db_path: Path,
    *,
    target_name: str = "main",
) -> dict[str, Any]:
    database_url = sqlite_database_url(db_path)
    upgrade_database(database_url=database_url, target_name=target_name)

    sync_engine = create_engine(
        normalize_sync_database_url(database_url),
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_pre_ping=True,
    )
    async_engine = create_async_engine(
        normalize_async_database_url(database_url),
        connect_args={"timeout": 30},
        pool_pre_ping=True,
    )

    sync_session_factory = sessionmaker(
        bind=sync_engine,
        autocommit=False,
        autoflush=False,
    )
    async_session_factory = async_sessionmaker(
        bind=async_engine,
        expire_on_commit=False,
        autoflush=False,
        class_=AsyncSession,
    )

    return {
        "database_url": database_url,
        "sync_engine": sync_engine,
        "async_engine": async_engine,
        "sync_session_factory": sync_session_factory,
        "async_session_factory": async_session_factory,
    }


def install_main_database_overrides(
    *,
    monkeypatch,
    app,
    get_db_dependency,
    async_engine,
    async_session_factory,
):
    import app.database as app_database
    from app.audit import audit_service
    import app.services.knowledge as knowledge_module
    from app.services.knowledge import get_query_log_service
    from app.services.knowledge.task_queue import NullKnowledgeSyncTaskQueue

    monkeypatch.setattr(app_database, "engine", async_engine)
    monkeypatch.setattr(app_database, "SessionLocal", async_session_factory)

    async def override_get_db():
        async with async_session_factory() as db:
            yield db

    app.dependency_overrides[get_db_dependency] = override_get_db

    # Do not carry audit records or a query-log worker from a previous
    # TestClient into this disposable-database fixture.
    audit_service._batch_buffer.clear()
    _patch_audit_service_manager(monkeypatch, _DiscardAuditDatabaseManager())
    query_log_service = get_query_log_service()
    monkeypatch.setattr(query_log_service, "_force_disabled", True)

    # These fixtures use disposable databases and must not start a real
    # Qdrant/embedding worker from the developer's environment.  Besides
    # making tests nondeterministic, the worker's asyncio primitives would be
    # reused across TestClient lifespan loops.
    monkeypatch.setattr(knowledge_module, "is_knowledge_graph_enabled", lambda settings=None: False)
    monkeypatch.setattr(knowledge_module, "_task_queue", NullKnowledgeSyncTaskQueue())
    return override_get_db


def install_audit_database_overrides(
    *,
    monkeypatch,
    async_session_factory,
):
    import app.audit.database as audit_database
    import app.db_access.audit as audit_db_access
    audit_service_module = importlib.import_module("app.audit.audit_service")

    class _TestAuditDatabaseManager:
        @asynccontextmanager
        async def get_session(self):
            async with async_session_factory() as db:
                yield db

    _patch_audit_service_manager(monkeypatch, _TestAuditDatabaseManager())

    @asynccontextmanager
    async def override_get_audit_session():
        async with async_session_factory() as db:
            yield db

    monkeypatch.setattr(audit_database, "get_audit_session", override_get_audit_session)
    # audit_service 已不再 import get_audit_session（c87785a 移除該 F401），
    # raising=False 讓此 patch 在未來若重新引入時仍生效
    monkeypatch.setattr(
        audit_service_module, "get_audit_session", override_get_audit_session, raising=False
    )
    monkeypatch.setattr(audit_db_access, "get_audit_session", override_get_audit_session)
    return override_get_audit_session


def install_usm_database_overrides(
    *,
    monkeypatch,
    async_engine,
    async_session_factory,
):
    import app.db_access.usm as usm_access
    import app.models.user_story_map_db as usm_database

    monkeypatch.setattr(usm_database, "usm_engine", async_engine)
    monkeypatch.setattr(usm_database, "USMAsyncSessionLocal", async_session_factory)
    monkeypatch.setattr(usm_access, "USMAsyncSessionLocal", async_session_factory)
    return async_session_factory


def dispose_managed_test_database(database_bundle: dict[str, Any]) -> None:
    asyncio.run(database_bundle["async_engine"].dispose())
    database_bundle["sync_engine"].dispose()
