"""assistant 權限矩陣測試（task 8.2）：逐工具驗證 executor 強制權限檢查，
不依賴底層真實 endpoint 是否自帶 in-handler 權限檢查——executor 的 `check_permission`
在 schema 驗證通過後、resolve_team/loopback 之前執行，對任何工具皆一視同仁。
"""
from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from app.auth.models import PermissionType, UserRole
from app.config import AssistantConfig
from app.database import get_db
from app.db_access.main import get_main_access_boundary
from app.main import app
from app.models.database_models import Team
from app.services.assistant.tool_executor import RejectionResult, ToolExecutor
from app.services.assistant.tool_registry import READ, get_tool_registry
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)

_PERMISSION_LEVEL = {PermissionType.READ: 1, PermissionType.WRITE: 2, PermissionType.ADMIN: 3}
_ROLE_LEVEL = {
    UserRole.VIEWER: _PERMISSION_LEVEL[PermissionType.READ],
    UserRole.USER: _PERMISSION_LEVEL[PermissionType.WRITE],
    UserRole.ADMIN: _PERMISSION_LEVEL[PermissionType.ADMIN],
}


def _synthetic_value(schema):
    t = schema.get("type")
    if t == "integer":
        return 1
    if t == "boolean":
        return True
    if t == "array":
        return [_synthetic_value(schema.get("items") or {"type": "string"})]
    if t == "object":
        return {k: _synthetic_value(v) for k, v in schema.get("properties", {}).items()}
    enum = schema.get("enum")
    return enum[0] if enum else "test-value"


def _synthetic_arguments(tool):
    props = tool.to_llm_schema()["function"]["parameters"]["properties"]
    return {name: _synthetic_value(schema) for name, schema in props.items()}


@pytest.fixture
def perm_db(tmp_path, monkeypatch):
    bundle = create_managed_test_database(tmp_path / "assistant_perm.db")
    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=bundle["async_engine"],
        async_session_factory=bundle["async_session_factory"],
    )
    with bundle["sync_session_factory"]() as session:
        session.add(Team(id=1, name="ART", description="", wiki_token="wt", test_case_table_id="tbl1"))
        session.commit()

    yield bundle

    app.dependency_overrides.pop(get_db, None)
    dispose_managed_test_database(bundle)


def _make_executor():
    cfg = AssistantConfig()
    boundary = get_main_access_boundary()
    registry = get_tool_registry()
    return ToolExecutor(app=app, main_boundary=boundary, config=cfg, registry=registry), registry


@pytest.mark.parametrize("tool_name", [t.name for t in get_tool_registry().all()])
async def test_permission_matrix_for_every_tool(perm_db, tool_name):
    executor, registry = _make_executor()
    tool = registry.get(tool_name)
    required_level = _PERMISSION_LEVEL[tool.permission]

    super_admin_ok = await executor.check_permission(tool, user_id=1, team_id=1, role=UserRole.SUPER_ADMIN)
    assert super_admin_ok is True, f"{tool_name}: SUPER_ADMIN must always pass regardless of tool.permission"

    for role, role_level in _ROLE_LEVEL.items():
        ok = await executor.check_permission(tool, user_id=1, team_id=1, role=role)
        expected = role_level >= required_level
        assert ok == expected, (
            f"{tool_name}: role={role.value} (level={role_level}) vs required={tool.permission.value} "
            f"(level={required_level}) expected allowed={expected}, got {ok}"
        )


async def test_viewer_denied_end_to_end_for_a_write_tool_before_any_loopback(perm_db):
    """端對端驗證（非僅 check_permission 單元呼叫）：VIEWER 對 write 工具在 prepare_write_tool
    階段就被拒絕，從未觸及 resolve_team／loopback（不論底層 endpoint 是否自帶權限檢查）。"""
    executor, registry = _make_executor()
    tool = registry.get("create_test_case")
    args = _synthetic_arguments(tool)
    args["test_case_number"] = "TC-PERM-001"
    args["title"] = "perm test"

    class _FakeConversation:
        id = 1
        team_id = 1
        scope_type = "team"

    result = await executor.prepare_write_tool(
        tool, args, conversation=_FakeConversation(), user_id=1, role=UserRole.VIEWER, execution_key="a" * 32
    )
    assert isinstance(result, RejectionResult)
    assert result.code == "permission_denied"
    assert result.fixable is False


async def test_viewer_denied_end_to_end_for_a_read_only_discovery_tool_still_allowed(perm_db):
    """對照組：VIEWER 對 read 工具應可通過權限檢查（雖然後續 team/loopback 仍可能因其他原因失敗）。"""
    executor, registry = _make_executor()
    read_tools = [t for t in registry.all() if t.risk_level == READ]
    assert read_tools, "expected at least one read tool to exist"
    tool = read_tools[0]
    ok = await executor.check_permission(tool, user_id=1, team_id=1, role=UserRole.VIEWER)
    assert ok is True, f"VIEWER should be allowed to use read tool {tool.name}"
