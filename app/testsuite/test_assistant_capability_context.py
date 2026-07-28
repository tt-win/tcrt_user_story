"""回合能力上下文（spec assistant-agent-loop「回合能力上下文」＋ tool-execution「能力自述工具」）。

回歸目標：VIEWER 被工具目錄預過濾後，送往 LLM 的 system prompt 必須說明「能力被移除及其原因」，
而不是讓模型推論成「系統沒有這個功能」。LLM 輸出無法確定性斷言，因此斷言對象是
（a）送進 LLM 的 system prompt 內容、（b）`describe_capabilities` 的結構化事實。
"""

from __future__ import annotations


import pytest


from app.auth.models import PermissionType, UserRole
from app.config import AssistantConfig
from app.database import get_db
from app.db_access.main import get_main_access_boundary
from app.main import app
from app.models.database_models import Team
from app.services.assistant import content_store as store
from app.services.assistant.capability_context import (
    NO_TEAM_CONTEXT,
    OTHER_WRITE,
    ROLE_INSUFFICIENT,
    append_capability_context,
    build_capability_context,
    build_capability_facts,
    capability_category,
    tools_for_turn,
)
from app.services.assistant.content_store import (
    assemble_system_prompt_for_agent,
    get_system_prompt_row,
    update_system_prompt,
)
from app.services.assistant.tool_executor import ToolExecutor
from app.services.assistant.tool_registry import get_tool_registry
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)

_CONTEXT_HEADING = "## 本回合能力事實"


def _facts(role: UserRole, scope_type: str, team_id=None, team_name=None) -> dict:
    registry = get_tool_registry()
    allowed = tools_for_turn(registry, team_id=team_id, role=role)
    return build_capability_facts(
        role=role,
        scope_type=scope_type,
        team_id=team_id,
        team_name=team_name,
        all_tools=registry.all(),
        allowed_tool_names=[t.name for t in allowed],
    )


# --------------------------------------------------------------------------- #
# 能力類別映射（registry 層守門）
# --------------------------------------------------------------------------- #


def test_every_write_permission_tool_maps_to_a_capability_category():
    """新增需 WRITE 權限的工具但忘了歸類時，withheld 摘要會退化成空泛的「其他寫入類操作」。"""
    unmapped = [
        tool.name
        for tool in get_tool_registry().all()
        if tool.permission != PermissionType.READ and capability_category(tool.name) == OTHER_WRITE
    ]
    assert not unmapped, (
        "以下工具未映射到能力類別，請更新 capability_context._CATEGORY_RULES："
        f"{sorted(unmapped)}"
    )


def test_withheld_categories_are_stable_and_labelled():
    facts = _facts(UserRole.VIEWER, "team", team_id=1, team_name="ART")
    withheld = facts["withheld_capabilities"]
    assert withheld, "VIEWER 在 team 對話應有被隱藏的寫入能力"
    assert [item["id"] for item in withheld] == [item["id"] for item in _facts(
        UserRole.VIEWER, "team", team_id=1, team_name="ART"
    )["withheld_capabilities"]]
    assert all(item["label"] for item in withheld)
    assert OTHER_WRITE not in [item["id"] for item in withheld]


# --------------------------------------------------------------------------- #
# capability context 內容
# --------------------------------------------------------------------------- #


def test_viewer_in_team_scope_gets_role_attribution():
    facts = _facts(UserRole.VIEWER, "team", team_id=1, team_name="ART")
    assert facts["scope"] == "team"
    assert facts["role"] == "viewer"
    assert facts["allowed_permissions"] == ["read"]
    assert facts["reasons"] == [ROLE_INSUFFICIENT]
    assert facts["remediation"]

    text = build_capability_context(facts)
    assert _CONTEXT_HEADING in text
    assert "`ART`" in text and "team_id=1" in text
    assert "`viewer`" in text
    assert ROLE_INSUFFICIENT in text
    assert "團隊管理員" in text
    # 錯誤歸因的具體反例（本次修正的來源）必須被明文禁止
    assert "不得聲稱系統沒有這個功能" in text
    assert "網頁介面" in text


def test_user_in_team_scope_has_no_restriction_narrative():
    facts = _facts(UserRole.USER, "team", team_id=1, team_name="ART")
    assert facts["withheld_capabilities"] == []
    assert facts["reasons"] == []

    text = build_capability_context(facts)
    assert "未受限" in text
    assert ROLE_INSUFFICIENT not in text
    assert "移除" not in text


def test_admin_in_team_scope_has_no_restriction_narrative():
    facts = _facts(UserRole.ADMIN, "team", team_id=2, team_name="CID")
    assert facts["withheld_capabilities"] == []
    assert facts["reasons"] == []
    assert facts["allowed_permissions"] == ["read", "write", "admin"]


def test_global_turn_with_context_team_behaves_like_team_scope():
    """全域對話帶入工作區 team 後，寫入能力必須恢復（本 change 的核心行為）。"""
    facts = _facts(UserRole.USER, "global", team_id=1, team_name="ART")
    assert facts["scope"] == "global"
    assert facts["team_id"] == 1
    assert facts["withheld_capabilities"] == []
    assert facts["reasons"] == []

    text = build_capability_context(facts)
    assert "`ART`" in text and "context team" in text
    assert "未受限" in text
    assert "目標 team 消歧" in text, "有目標 team 時必須帶消歧規則"


def test_global_turn_without_context_team_reports_no_team_context():
    facts = _facts(UserRole.USER, "global")
    assert facts["scope"] == "global"
    assert facts["team_id"] is None
    assert facts["reasons"] == [NO_TEAM_CONTEXT]
    assert any("工作區" in item for item in facts["remediation"])

    text = build_capability_context(facts)
    assert NO_TEAM_CONTEXT in text
    assert "本回合目標 team：無" in text
    assert ROLE_INSUFFICIENT not in text


def test_no_team_context_never_suggests_switching_to_a_team_conversation():
    """前端只建立全域對話；要切換的是工作區，不是「team 對話」。"""
    for role in (UserRole.VIEWER, UserRole.USER, UserRole.ADMIN):
        facts = _facts(role, "global")
        assert not [item for item in facts["remediation"] if "對話" in item and "切換" in item]
        text = build_capability_context(facts)
        assert "不得叫使用者「切換到某個 team 的對話」" in text
        assert "要切換的是工作區" in text


def test_no_team_context_with_viewer_reports_both_reasons():
    facts = _facts(UserRole.VIEWER, "global")
    assert facts["reasons"] == [NO_TEAM_CONTEXT, ROLE_INSUFFICIENT]
    assert len(facts["remediation"]) == 2

    text = build_capability_context(facts)
    assert NO_TEAM_CONTEXT in text and ROLE_INSUFFICIENT in text
    # 兩個限制彼此獨立；角色不足時網頁介面不是解法
    assert "仍需要 write 權限" in text
    assert "同一權限限制在網頁介面同樣成立" in text


def test_viewer_with_context_team_is_role_insufficient_not_no_team_context():
    facts = _facts(UserRole.VIEWER, "global", team_id=1, team_name="ART")
    assert facts["reasons"] == [ROLE_INSUFFICIENT]
    assert NO_TEAM_CONTEXT not in build_capability_context(facts)


def test_team_scope_falls_back_to_team_id_when_name_missing():
    text = build_capability_context(_facts(UserRole.VIEWER, "team", team_id=7))
    assert "Team-7" in text


@pytest.mark.parametrize(
    "role,scope,team_id",
    [
        (UserRole.VIEWER, "team", 1),
        (UserRole.USER, "team", 1),
        (UserRole.VIEWER, "global", 1),
        (UserRole.VIEWER, "global", None),
        (UserRole.SUPER_ADMIN, "global", None),
    ],
)
def test_context_block_stays_compact(role, scope, team_id):
    """context budget（spec assistant-context-budget）：以類別摘要取代工具名列舉。"""
    text = build_capability_context(_facts(role, scope, team_id=team_id))
    lines = [line for line in text.splitlines() if line.strip()]
    assert len(lines) <= 12, f"capability context 行數過多: {len(lines)}"
    assert len(text) <= 1500, f"capability context 過長: {len(text)} chars"
    tool_names = [t.name for t in get_tool_registry().all()]
    assert not [name for name in tool_names if name != "describe_capabilities" and name in text], (
        "capability context 不應列舉工具名（只描述能力類別）"
    )


def test_append_does_not_mutate_base_prompt_and_isolates_roles():
    base = "你是 TCRT 助手。\n\n## Skill catalog\n\n- foo\n"
    viewer_prompt = append_capability_context(base, _facts(UserRole.VIEWER, "team", team_id=1, team_name="ART"))
    admin_prompt = append_capability_context(base, _facts(UserRole.ADMIN, "team", team_id=1, team_name="ART"))

    assert _CONTEXT_HEADING not in base, "base prompt 不得被就地改寫"
    assert base.rstrip() in viewer_prompt and base.rstrip() in admin_prompt
    assert "`viewer`" in viewer_prompt and "`viewer`" not in admin_prompt
    assert ROLE_INSUFFICIENT in viewer_prompt and ROLE_INSUFFICIENT not in admin_prompt


# --------------------------------------------------------------------------- #
# DB-backed：prompt 快取與管理員自訂 prompt
# --------------------------------------------------------------------------- #


@pytest.fixture
def prompt_db(tmp_path, monkeypatch):
    bundle = create_managed_test_database(tmp_path / "asst_capability.db")
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
    store.invalidate_content_cache()

    yield bundle

    store.invalidate_content_cache()
    app.dependency_overrides.pop(get_db, None)
    dispose_managed_test_database(bundle)


async def test_assembled_prompt_cache_is_never_polluted_by_per_turn_context(prompt_db):
    """快取的是跨使用者共用的 base；per-turn 內容只存在於各自組出的 prompt。"""
    boundary = get_main_access_boundary()
    base_first = await assemble_system_prompt_for_agent(boundary)
    viewer_prompt = append_capability_context(
        base_first, _facts(UserRole.VIEWER, "team", team_id=1, team_name="ART")
    )
    # 第二個回合（不同角色）重新取用同一快取
    base_second = await assemble_system_prompt_for_agent(boundary)
    admin_prompt = append_capability_context(
        base_second, _facts(UserRole.ADMIN, "team", team_id=1, team_name="ART")
    )

    assert _CONTEXT_HEADING not in base_first
    assert _CONTEXT_HEADING not in base_second
    # 只比對 capability 區塊：base prompt 本身也會提到 role_insufficient 這個原因名稱
    viewer_block = viewer_prompt[viewer_prompt.index(_CONTEXT_HEADING) :]
    admin_block = admin_prompt[admin_prompt.index(_CONTEXT_HEADING) :]
    assert "`viewer`" in viewer_block and "`viewer`" not in admin_block
    assert ROLE_INSUFFICIENT in viewer_block and ROLE_INSUFFICIENT not in admin_block


async def test_admin_customized_prompt_still_receives_capability_context(prompt_db):
    """管理員自訂 prompt（含舊的絕對化措辭、無任何 capability token）仍必須拿到 capability context。"""
    boundary = get_main_access_boundary()
    await assemble_system_prompt_for_agent(boundary)  # seed
    custom = (
        "你是自訂版本的 TCRT 助手。\n"
        "- 工具目錄以外的操作一律視為不可能。\n"
        # `validate_system_content` 有最小長度限制（200 字），補足即可，內容本身不影響斷言。
        + "- 這是自訂 prompt 的填充說明，用於滿足系統 prompt 的最小長度限制。\n" * 4
        + "\n{{SKILL_CATALOG}}\n"
    )
    current = await get_system_prompt_row(boundary)
    await update_system_prompt(
        boundary, content=custom, expected_version=int(current["version"]), updated_by=None
    )
    store.invalidate_content_cache()

    base = await assemble_system_prompt_for_agent(boundary)
    assert "自訂版本" in base
    assert _CONTEXT_HEADING not in base

    prompt = append_capability_context(base, _facts(UserRole.VIEWER, "team", team_id=1, team_name="ART"))
    assert _CONTEXT_HEADING in prompt
    assert prompt.index("自訂版本") < prompt.index(_CONTEXT_HEADING), "capability context 必須在最後"


# --------------------------------------------------------------------------- #
# describe_capabilities（local read 工具）
# --------------------------------------------------------------------------- #


def test_describe_capabilities_tool_declaration():
    tool = get_tool_registry().get("describe_capabilities")
    assert tool is not None
    assert tool.execution_mode == "local"
    assert tool.method == "LOCAL"
    assert tool.team_check == "none"
    assert tool.permission == PermissionType.READ
    assert tool.is_write() is False
    for field in ("scope", "role", "allowed_permissions", "withheld_capabilities", "reasons", "remediation"):
        assert field in tool.projection

    # 全域對話可用；且不得成為 batch_execute_actions 的子動作
    assert "describe_capabilities" in [t.name for t in get_tool_registry().discovery_only()]
    batch = get_tool_registry().get("batch_execute_actions")
    schema = batch.to_llm_schema()["function"]["parameters"]
    assert "describe_capabilities" not in str(schema.get("properties", {}))


def _make_executor() -> ToolExecutor:
    return ToolExecutor(
        app=app,
        main_boundary=get_main_access_boundary(),
        config=AssistantConfig(),
        registry=get_tool_registry(),
    )


@pytest.mark.parametrize(
    "role,expected_permissions,expect_withheld",
    [
        (UserRole.VIEWER, ["read"], True),
        (UserRole.USER, ["read", "write"], False),
        (UserRole.ADMIN, ["read", "write", "admin"], False),
    ],
)
async def test_describe_capabilities_local_execution_per_role(
    prompt_db, role, expected_permissions, expect_withheld
):
    executor = _make_executor()
    tool = get_tool_registry().get("describe_capabilities")

    status, payload = await executor._run_local_read_tool(
        tool, {}, team_id=1, user_id=1, role=role, scope_type="team"
    )

    assert status == 200
    assert payload["scope"] == "team"
    assert payload["team_id"] == 1
    assert payload["team_name"] == "ART"
    assert payload["role"] == role.value
    assert payload["allowed_permissions"] == expected_permissions
    assert bool(payload["withheld_capabilities"]) is expect_withheld
    assert (ROLE_INSUFFICIENT in payload["reasons"]) is expect_withheld


async def test_describe_capabilities_available_in_global_scope(prompt_db):
    executor = _make_executor()
    tool = get_tool_registry().get("describe_capabilities")

    status, payload = await executor._run_local_read_tool(
        tool, {}, team_id=None, user_id=1, role=UserRole.USER, scope_type="global"
    )

    assert status == 200
    assert payload["scope"] == "global"
    assert payload["team_id"] is None
    assert NO_TEAM_CONTEXT in payload["reasons"]
    assert payload["withheld_capabilities"], "全域對話應回報寫入能力被移除"
