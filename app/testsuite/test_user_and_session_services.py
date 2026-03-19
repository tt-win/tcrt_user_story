from datetime import datetime, timedelta
from typing import Any

import pytest

from app.auth.models import UserCreate, UserRole
from app.auth.session_service import SessionService
from app.models.database_models import ActiveSession, User
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
