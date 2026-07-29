import asyncio
from contextlib import asynccontextmanager
import threading
import time

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


from app.db_access.coordinator import CrossDatabaseCoordinator
from app.db_access.core import BoundaryContract, DatabaseTarget, ManagedAccessBoundary
from app.db_access import (
    create_audit_access_boundary_for_session,
    create_usm_access_boundary_for_session,
)


class FakeSession:
    def __init__(self) -> None:
        self.commit_calls = 0
        self.rollback_calls = 0

    async def commit(self) -> None:
        self.commit_calls += 1

    async def rollback(self) -> None:
        self.rollback_calls += 1

    async def run_sync(self, operation):
        return operation(self)


class FakeBoundary(ManagedAccessBoundary):
    def __init__(self, session: FakeSession) -> None:
        self._fake_session = session
        super().__init__(
            contract=BoundaryContract(
                target=DatabaseTarget.MAIN,
                session_provider="tests.fake_provider",
            ),
            session_provider=self._session_provider,
        )

    @asynccontextmanager
    async def _session_provider(self):
        yield self._fake_session


@pytest.mark.asyncio
async def test_run_write_commits_once():
    session = FakeSession()
    boundary = FakeBoundary(session)

    result = await boundary.run_write(lambda current_session: _async_value(current_session, 123))

    assert result == 123
    assert session.commit_calls == 1
    assert session.rollback_calls == 0


@pytest.mark.asyncio
async def test_run_write_rolls_back_on_error():
    session = FakeSession()
    boundary = FakeBoundary(session)

    with pytest.raises(RuntimeError, match="boom"):
        await boundary.run_write(_raise_boom)

    assert session.commit_calls == 0
    assert session.rollback_calls == 1


@pytest.mark.asyncio
async def test_serialized_write_blocks_second_sqlite_connection(tmp_path):
    database_path = tmp_path / "serialized-boundary.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}",
        connect_args={"timeout": 2},
        poolclass=NullPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _register_sleep(dbapi_connection, _connection_record):
        dbapi_connection.create_function(
            "sleep_ms",
            1,
            lambda milliseconds: time.sleep(milliseconds / 1000),
        )

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    def _boundary() -> ManagedAccessBoundary:
        @asynccontextmanager
        async def _provider():
            async with session_factory() as session:
                yield session

        return ManagedAccessBoundary(
            contract=BoundaryContract(
                target=DatabaseTarget.MAIN,
                session_provider="tests.sqlite_provider",
            ),
            session_provider=_provider,
        )

    order: list[str] = []
    first_started = threading.Event()

    def _first(sync_session):
        order.append("first-start")
        first_started.set()
        sync_session.execute(text("SELECT sleep_ms(150)"))
        order.append("first-end")

    def _second(sync_session):
        order.append("second-start")
        sync_session.execute(text("SELECT 1"))
        order.append("second-end")

    try:
        first_task = asyncio.create_task(_boundary().run_sync_serialized_write(_first))
        assert await asyncio.to_thread(first_started.wait, 1)
        second_task = asyncio.create_task(_boundary().run_sync_serialized_write(_second))
        await asyncio.gather(first_task, second_task)
    finally:
        await engine.dispose()

    assert order == ["first-start", "first-end", "second-start", "second-end"]


def test_cross_database_coordinator_holds_boundaries():
    main = object()
    audit = object()
    usm = object()

    coordinator = CrossDatabaseCoordinator(main=main, audit=audit, usm=usm)

    assert coordinator.main is main
    assert coordinator.audit is audit
    assert coordinator.usm is usm


@pytest.mark.asyncio
async def test_audit_boundary_can_bind_existing_session():
    session = FakeSession()
    boundary = create_audit_access_boundary_for_session(session)

    returned_session = await boundary.run_sync_read(lambda current_session: current_session)

    assert boundary.target is DatabaseTarget.AUDIT
    assert boundary.contract.session_provider == "provided_async_session"
    assert returned_session is session


@pytest.mark.asyncio
async def test_usm_boundary_can_bind_existing_session():
    session = FakeSession()
    boundary = create_usm_access_boundary_for_session(session)

    returned_session = await boundary.run_sync_read(lambda current_session: current_session)

    assert boundary.target is DatabaseTarget.USM
    assert boundary.contract.session_provider == "provided_async_session"
    assert returned_session is session


async def _async_value(_session, value):
    return value


async def _raise_boom(_session):
    raise RuntimeError("boom")
