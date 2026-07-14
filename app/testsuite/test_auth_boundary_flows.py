from types import SimpleNamespace
from typing import Any

import pytest

from app.api.audit import _fetch_team_names
from app.auth.auth_service import AuthService
from app.auth.mcp_dependencies import get_current_machine_principal
from app.auth.models import UserRole
from app.auth.password_service import PasswordService
from app.auth.permission_service import PermissionService
from app.models.app_token import AppTokenPrincipal
from app.models.database_models import User


class _FakeScalarResult:
    def __init__(self, scalar_value: Any = None):
        self._scalar_value = scalar_value

    def scalar(self):
        return self._scalar_value

    def scalar_one_or_none(self):
        return self._scalar_value


class _FakeRowResult:
    def __init__(self, rows: list[tuple[Any, ...]]):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeSession:
    def __init__(self, execute_results: list[Any] | None = None):
        self._execute_results = list(execute_results or [])
        self.flush_calls = 0
        self.commit_calls = 0
        self.rollback_calls = 0

    async def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003
        if not self._execute_results:
            raise AssertionError("unexpected execute call")
        return self._execute_results.pop(0)

    async def flush(self) -> None:
        self.flush_calls += 1

    async def refresh(self, obj: Any) -> None:
        return None

    async def commit(self) -> None:
        self.commit_calls += 1

    async def rollback(self) -> None:
        self.rollback_calls += 1


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
async def test_auth_service_authenticate_user_uses_boundary_for_login_update():
    user = User(
        id=10,
        username="alice",
        email="alice@example.com",
        full_name="Alice",
        role=UserRole.ADMIN,
        hashed_password=PasswordService.hash_password("secret123"),
        is_active=True,
        last_login_at=None,
    )
    session = _FakeSession(execute_results=[_FakeScalarResult(user)])
    boundary = _FakeBoundary(session)
    service = AuthService(main_boundary=boundary)

    authenticated = await service.authenticate_user(
        username_or_email="alice",
        password="secret123",
    )

    assert authenticated is user
    assert boundary.write_calls == 1
    assert user.last_login_at is not None
    assert getattr(user, "was_first_login", False) is True
    assert session.flush_calls == 1


@pytest.mark.asyncio
async def test_permission_service_check_user_role_uses_boundary():
    session = _FakeSession(execute_results=[_FakeScalarResult(UserRole.ADMIN.value)])
    boundary = _FakeBoundary(session)
    service = PermissionService(main_boundary=boundary)

    allowed = await service.check_user_role(5, UserRole.USER)

    assert allowed is True
    assert boundary.read_calls == 1


@pytest.mark.asyncio
async def test_permission_cache_hits_avoid_db_until_cleared():
    """回歸測試：app/api/users.py 變更 role/is_active 後必須呼叫 clear_permission_cache，
    否則同一個 worker 在 TTL 到期前仍會用到已經過期的角色（曾經完全沒有任何地方呼叫這個
    清除函式，等同權限變更後最多 5 分鐘才會生效——見 2026-07-14 的 Phase 3 修正）。"""
    session = _FakeSession(
        execute_results=[
            _FakeScalarResult(UserRole.ADMIN.value),
            _FakeScalarResult(UserRole.VIEWER.value),
        ]
    )
    boundary = _FakeBoundary(session)
    service = PermissionService(main_boundary=boundary)

    first = await service.check_user_role(5, UserRole.USER)
    assert first is True
    assert boundary.read_calls == 1

    # 快取命中：TTL 內重複查詢不該再打 DB。
    second = await service.check_user_role(5, UserRole.USER)
    assert second is True
    assert boundary.read_calls == 1

    # 清除快取後（比照 clear_permission_cache 的呼叫方式）必須重新查詢 DB，
    # 拿到 DB 端已經變更（降為 VIEWER）的最新角色。
    await service.clear_cache(user_id=5)
    third = await service.check_user_role(5, UserRole.USER)
    assert third is False
    assert boundary.read_calls == 2


@pytest.mark.asyncio
async def test_fetch_team_names_uses_main_boundary():
    session = _FakeSession(execute_results=[_FakeRowResult([(1, "Team A"), (2, "Team B")])])
    boundary = _FakeBoundary(session)

    team_map = await _fetch_team_names([1, 2, 2], main_boundary=boundary)

    assert boundary.read_calls == 1
    assert team_map == {1: "Team A", 2: "Team B"}


@pytest.mark.asyncio
async def test_get_current_machine_principal_maps_app_token_principal():
    """`get_current_machine_principal` is now a thin compatibility wrapper: it
    receives an already-resolved `AppTokenPrincipal` (token lookup and
    `last_used_at` bookkeeping happen upstream in `get_current_app_token_principal`,
    covered by test_app_token_auth.py) and maps it onto `MCPMachinePrincipal`
    for legacy `/api/mcp/*` consumers."""
    app_principal = AppTokenPrincipal(
        credential_id=7,
        credential_name="robot",
        owner_team_id=None,
        scopes=["test_case:read", "test_run:read"],
        allow_all_teams=True,
        team_scope_ids=[],
        is_legacy=True,
        legacy_permission="mcp_read",
    )
    request = SimpleNamespace(
        url=SimpleNamespace(path="/api/mcp/teams/1", query=""),
        method="GET",
        client=SimpleNamespace(host="127.0.0.1"),
        headers={},
        path_params={"team_id": "1"},
        state=SimpleNamespace(),
    )

    principal = await get_current_machine_principal(request=request, app_principal=app_principal)

    assert principal.credential_id == 7
    assert principal.credential_name == "robot"
    assert principal.permission == "mcp_read"
    assert principal.allow_all_teams is True


@pytest.mark.asyncio
async def test_get_current_machine_principal_rejects_missing_read_scope():
    app_principal = AppTokenPrincipal(
        credential_id=8,
        credential_name="write-only",
        owner_team_id=1,
        scopes=["test_case:write"],
        allow_all_teams=False,
        team_scope_ids=[1],
        is_legacy=False,
    )
    request = SimpleNamespace(
        url=SimpleNamespace(path="/api/mcp/teams/1", query=""),
        method="GET",
        client=SimpleNamespace(host="127.0.0.1"),
        headers={},
        path_params={"team_id": "1"},
        state=SimpleNamespace(),
    )

    with pytest.raises(Exception) as exc_info:
        await get_current_machine_principal(request=request, app_principal=app_principal)

    assert getattr(exc_info.value, "status_code", None) == 403
