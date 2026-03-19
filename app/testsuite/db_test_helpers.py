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

    monkeypatch.setattr(app_database, "engine", async_engine)
    monkeypatch.setattr(app_database, "SessionLocal", async_session_factory)

    async def override_get_db():
        async with async_session_factory() as db:
            yield db

    app.dependency_overrides[get_db_dependency] = override_get_db
    return override_get_db


def install_audit_database_overrides(
    *,
    monkeypatch,
    async_session_factory,
):
    import app.audit.database as audit_database
    import app.db_access.audit as audit_db_access
    audit_service_module = importlib.import_module("app.audit.audit_service")

    @asynccontextmanager
    async def override_get_audit_session():
        async with async_session_factory() as db:
            yield db

    monkeypatch.setattr(audit_database, "get_audit_session", override_get_audit_session)
    monkeypatch.setattr(audit_service_module, "get_audit_session", override_get_audit_session)
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
