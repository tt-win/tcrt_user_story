from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, AsyncIterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.models import UserCreate, UserRole
from app.auth.session_service import SessionService
from app.db_access.core import BoundaryContract, DatabaseTarget, ManagedAccessBoundary
from app.models.database_models import ActiveSession, Base, LoginChallenge, User
from app.services.user_service import UserService


class _FakeScalarResult:
    def __init__(self, scalar_value: Any = None):
        self._scalar_value = scalar_value

    def scalar(self):
        return self._scalar_value

    def scalar_one_or_none(self):
        return self._scalar_value


class _FakeSession:
    def __init__(self, execute_results: list[_FakeScalarResult] | None = None):
        self._execute_results = list(execute_results or [])
        self.added: list[Any] = []
        self.deleted: list[Any] = []

    async def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003
        if not self._execute_results:
            raise AssertionError("unexpected execute call")
        return self._execute_results.pop(0)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        for index, obj in enumerate(self.added, start=1):
            if getattr(obj, "id", None) is None:
                setattr(obj, "id", index)

    async def refresh(self, obj: Any) -> None:
        return None

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)


class _FakeBoundary:
    def __init__(self, session: _FakeSession):
        self.session = session
        self.read_calls = 0
        self.write_calls = 0

    async def run_read(self, operation):
        self.read_calls += 1
        return await operation(self.session)

    async def run_write(self, operation):
        self.write_calls += 1
        return await operation(self.session)


@pytest.mark.asyncio
async def test_user_service_create_user_async_uses_boundary():
    session = _FakeSession(
        execute_results=[
            _FakeScalarResult(None),
            _FakeScalarResult(None),
        ]
    )
    boundary = _FakeBoundary(session)
    user_create = UserCreate(
        username="alice",
        email="alice@example.com",
        full_name="Alice",
        role=UserRole.USER,
        password="secret123",
        is_active=True,
        primary_team_id=None,
        lark_user_id=None,
    )

    user = await UserService.create_user_async(user_create, main_boundary=boundary)

    assert boundary.write_calls == 1
    assert user.id == 1
    assert user.username == "alice"
    assert user.hashed_password != "secret123"


@pytest.mark.asyncio
async def test_user_service_check_lark_integration_status_uses_boundary():
    user = User(
        id=10,
        username="alice",
        email="alice@example.com",
        full_name="Alice",
        role=UserRole.USER,
        hashed_password="hashed",
        is_active=True,
        lark_user_id="ou_123",
    )
    lark_user = type(
        "LarkProfile",
        (),
        {"name": "Alice Lark", "avatar_240": "https://example.com/avatar.png"},
    )()
    session = _FakeSession(
        execute_results=[
            _FakeScalarResult(user),
            _FakeScalarResult(lark_user),
        ]
    )
    boundary = _FakeBoundary(session)

    status = await UserService.check_lark_integration_status(10, main_boundary=boundary)

    assert boundary.read_calls == 1
    assert status["lark_linked"] is True
    assert status["has_lark_data"] is True
    assert status["name"] == "Alice Lark"


@pytest.mark.asyncio
async def test_session_service_revoke_jti_updates_cache_and_state():
    active_session = ActiveSession(
        user_id=10,
        jti="token-1",
        token_type="access",
        expires_at=datetime.utcnow() + timedelta(hours=1),
        created_at=datetime.utcnow(),
    )
    session = _FakeSession(execute_results=[_FakeScalarResult(active_session)])
    boundary = _FakeBoundary(session)
    service = SessionService(main_boundary=boundary)

    revoked = await service.revoke_jti("token-1", "logout")

    assert revoked is True
    assert boundary.write_calls == 1
    assert active_session.is_revoked is True
    assert "token-1" in service._revoked_jtis


@pytest.mark.asyncio
async def test_session_service_is_jti_revoked_caches_result():
    active_session = ActiveSession(
        user_id=10,
        jti="token-2",
        token_type="access",
        is_revoked=True,
        expires_at=datetime.utcnow() + timedelta(hours=1),
        created_at=datetime.utcnow(),
    )
    session = _FakeSession(execute_results=[_FakeScalarResult(active_session)])
    boundary = _FakeBoundary(session)
    service = SessionService(main_boundary=boundary)

    first = await service.is_jti_revoked("token-2")
    second = await service.is_jti_revoked("token-2")

    assert first is True
    assert second is True
    assert boundary.read_calls == 1


def _boundary_for_session_factory(session_factory) -> ManagedAccessBoundary:
    """比照 app/db_access/main.py::MainAccessBoundary，但每次呼叫都從共用的
    session_factory 開一個新 session——模擬「多個 worker process，共用同一個
    底層資料庫」，而不是同一個 in-process 物件的多次呼叫。"""

    @asynccontextmanager
    async def _provider() -> AsyncIterator[Any]:
        async with session_factory() as session:
            yield session

    return ManagedAccessBoundary(
        contract=BoundaryContract(target=DatabaseTarget.MAIN, session_provider="test-factory"),
        session_provider=_provider,
    )


@pytest.mark.asyncio
async def test_login_challenge_survives_across_separate_worker_instances(tmp_path: Path) -> None:
    """回歸測試：登入 challenge 曾經存在 SessionService 自己的 in-process dict，
    WEB_CONCURRENCY>1 時 /challenge 與登入驗證這兩個請求若落在不同 worker，
    第二個 worker 的字典裡沒有第一個 worker 存的 challenge，合法登入會直接失敗
    （見 2026-07-14 Phase 3 修正，改為 DB-backed LoginChallenge）。這裡用兩個
    完全獨立的 SessionService + boundary 實例（各自的 session_provider 都是
    現開現關，不共用任何 Python 物件狀態）模擬兩個不同的 worker process，
    唯一共用的是底層資料庫檔案。只建 LoginChallenge 這張表（不用完整 Alembic
    migration chain）：這裡是純 async 測試，Alembic 的 upgrade_database() 內部會
    呼叫 asyncio.run()，在已經有 event loop 在跑的 async test 裡會直接炸開。"""
    db_path = tmp_path / "login_challenge.db"
    sync_engine = create_engine(f"sqlite:///{db_path}", future=True)
    try:
        Base.metadata.create_all(sync_engine, tables=[LoginChallenge.__table__])
    finally:
        sync_engine.dispose()

    async_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool, connect_args={"check_same_thread": False}
    )
    session_factory = async_sessionmaker(bind=async_engine, expire_on_commit=False)
    try:
        worker_a = SessionService(main_boundary=_boundary_for_session_factory(session_factory))
        worker_b = SessionService(main_boundary=_boundary_for_session_factory(session_factory))

        expires_at = datetime.utcnow() + timedelta(minutes=5)
        stored = await worker_a.store_challenge("alice", "deadbeef" * 8, expires_at)
        assert stored is True

        # worker_a 從未把這個 challenge 放進 worker_b 的任何記憶體結構——
        # 驗證必須完全靠共用的資料庫才能成功。
        verified = await worker_b.verify_challenge("alice", "deadbeef" * 8)
        assert verified is True

        # 驗證成功後應該已經被消耗掉（單次有效），worker_a 再驗證同一個值必須失敗。
        replayed = await worker_a.verify_challenge("alice", "deadbeef" * 8)
        assert replayed is False
    finally:
        await async_engine.dispose()
