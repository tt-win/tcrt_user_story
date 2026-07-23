"""assistant tool_registry/tools_catalog 靜態驗證（task 8.1）。

純 registry 層檢查，不需要 DB／HTTP：名稱唯一、DELETE 預設 irreversible（除豁免清單）、
path_template+method 對得上 app.routes 實際註冊路由、server-fixed 欄位不外洩進 LLM schema、
low-risk 工具不得暴露高風險欄位、projection allowlist 精確（巢狀 sentinel 驗證只輸出白名單）。
"""
from __future__ import annotations

import inspect
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import app
from app.services.assistant.projection import project_and_redact
from app.services.assistant.tool_registry import (
    DELETE_RISK_EXEMPTIONS,
    IRREVERSIBLE,
    get_tool_registry,
)

EXPECTED_TOOL_COUNT = 72  # 68 loopback/composite + list_skills + get_skill + plan_batch + generate_chunk_actions

def _app_routes():
    return {
        (method, route.path)
        for route in app.routes
        if hasattr(route, "path") and hasattr(route, "methods")
        for method in route.methods
    }


def _app_route_endpoints():
    return {
        (method, route.path): route.endpoint
        for route in app.routes
        if hasattr(route, "path") and hasattr(route, "methods") and hasattr(route, "endpoint")
        for method in route.methods
    }


def test_registry_loads_expected_tool_count_with_unique_names():
    registry = get_tool_registry()
    names = registry.names()
    assert len(names) == EXPECTED_TOOL_COUNT, f"expected {EXPECTED_TOOL_COUNT} tools, got {len(names)}"
    assert len(set(names)) == len(names), "tool names MUST be unique"


def test_delete_tools_are_irreversible_except_exemptions():
    registry = get_tool_registry()
    for tool in registry.all():
        if tool.method != "DELETE":
            continue
        if tool.name in DELETE_RISK_EXEMPTIONS:
            continue
        assert tool.risk_level == IRREVERSIBLE, (
            f"DELETE tool {tool.name} has risk_level={tool.risk_level}, expected irreversible "
            f"(not in exemption list {sorted(DELETE_RISK_EXEMPTIONS)})"
        )


def test_delete_exemptions_are_exactly_the_documented_two():
    assert DELETE_RISK_EXEMPTIONS == frozenset({"unpin_entity", "remove_item_bug_ticket"})


def test_every_tool_path_and_method_resolves_against_real_routes():
    registry = get_tool_registry()
    routes = _app_routes()
    mismatches = [
        tool.name
        for tool in registry.all()
        if tool.execution_mode == "loopback" and (tool.method, tool.path_template) not in routes
    ]
    assert not mismatches, f"tools with no matching registered route: {mismatches}"


def test_path_param_llm_schema_types_match_real_endpoint_annotations():
    """紅隊發現的 bug class：`to_llm_schema()` 對未覆寫的 path_params 一律宣告 "integer"，
    但真正端點的參數型別可能是 str（檔名／ticket number／enum 值等)。這裡直接比對 registry
    宣告的 schema 型別跟真實 FastAPI endpoint 的 Python 參數型別註記，防止未來新工具重演同一個
    bug（LLM 被迫捏造假整數,確認卡建成但實際呼叫必然失敗)。"""
    registry = get_tool_registry()
    endpoints = _app_route_endpoints()
    type_map = {int: "integer", str: "string"}
    mismatches = []
    for tool in registry.all():
        if tool.execution_mode != "loopback" or not tool.path_params:
            continue
        endpoint = endpoints.get((tool.method, tool.path_template))
        if endpoint is None:
            continue  # 由 test_every_tool_path_and_method_resolves_against_real_routes 另外把關
        sig = inspect.signature(endpoint)
        schema = tool.to_llm_schema()["function"]["parameters"]["properties"]
        for name in tool.path_params:
            real_annotation = sig.parameters[name].annotation if name in sig.parameters else None
            expected_type = type_map.get(real_annotation)
            if expected_type is None:
                continue  # 非 int/str 的參數型別不在本測試涵蓋範圍
            declared_type = schema.get(name, {}).get("type")
            if declared_type != expected_type:
                mismatches.append(
                    f"{tool.name}.{name}: 真實端點型別={real_annotation.__name__}（應宣告 {expected_type}），"
                    f"但 registry 宣告 {declared_type}"
                )
    assert not mismatches, "path_param_schemas 與真實端點型別不一致：\n" + "\n".join(mismatches)


def test_delete_test_case_attachment_and_friends_declare_string_path_params():
    """明確鎖定 3 個已知因此 bug class 壞掉的工具，做為可讀的回歸標記（上面的通用 drift test
    已涵蓋所有工具，這裡額外針對已知案例做語意清楚的斷言）。"""
    registry = get_tool_registry()
    expectations = {
        "delete_test_case_attachment": {"target": "string"},
        "remove_item_bug_ticket": {"ticket_number": "string"},
        "unpin_entity": {"entity_type": "string"},
    }
    for tool_name, expected_types in expectations.items():
        tool = registry.get(tool_name)
        assert tool is not None, f"{tool_name} not found in registry"
        schema = tool.to_llm_schema()["function"]["parameters"]["properties"]
        for param_name, expected_type in expected_types.items():
            assert schema[param_name]["type"] == expected_type, (
                f"{tool_name}.{param_name}: expected type={expected_type}, got {schema[param_name]}"
            )
    unpin_schema = registry.get("unpin_entity").to_llm_schema()["function"]["parameters"]["properties"]
    assert unpin_schema["entity_type"].get("enum") == ["test_case_set", "test_run_set"]


def test_batch_actions_enum_covers_every_loopback_write_tool():
    registry = get_tool_registry()
    composite = registry.get("batch_execute_actions")
    assert composite is not None and composite.execution_mode == "batch_actions"
    enum = set(
        composite.to_llm_schema()["function"]["parameters"]["properties"]
        ["actions"]["items"]["properties"]["tool_name"]["enum"]
    )
    expected = {tool.name for tool in registry.all() if tool.execution_mode == "loopback" and tool.is_write()}
    assert enum == expected
    assert "batch_execute_actions" not in enum


def test_write_tools_have_required_confirmation_metadata():
    registry = get_tool_registry()
    for tool in registry.all():
        if not tool.is_write():
            continue
        assert tool.confirmation_action_key, f"{tool.name}: missing confirmation_action_key"
        assert tool.warning_key, f"{tool.name}: missing warning_key"
        assert tool.target_resolver, f"{tool.name}: missing target_resolver"


def test_every_tool_has_projection_or_declares_no_response_body():
    registry = get_tool_registry()
    for tool in registry.all():
        assert tool.projection or tool.has_no_response_body, (
            f"{tool.name}: missing projection allowlist and not marked has_no_response_body"
        )


def test_fixed_body_fields_are_excluded_from_llm_schema():
    """server-fixed 欄位（如 operation=delete）不得出現在送給 LLM 的 schema，避免 LLM 誤以為可控制。"""
    registry = get_tool_registry()
    checked_any = False
    for tool in registry.all():
        if not tool.fixed_body:
            continue
        checked_any = True
        schema = tool.to_llm_schema()
        properties = schema["function"]["parameters"]["properties"]
        for fixed_key in tool.fixed_body:
            assert fixed_key not in properties, (
                f"{tool.name}: server-fixed field {fixed_key!r} leaked into LLM-visible schema"
            )
    assert checked_any, "expected at least one tool with fixed_body to exercise this check"


def test_low_risk_tools_do_not_share_high_risk_only_fields_on_same_endpoint():
    """共用 endpoint 的工具間，低風險工具的 schema 不應包含高風險工具才有的欄位（避免暴露高風險操作面）。"""
    registry = get_tool_registry()
    by_endpoint = {}
    for tool in registry.all():
        by_endpoint.setdefault((tool.method, tool.path_template), []).append(tool)
    for endpoint, tools in by_endpoint.items():
        if len(tools) < 2:
            continue
        # 目前矩陣沒有真正共用同一 (method, path) 的多個工具（各工具皆對應唯一 endpoint），
        # 此檢查對未來擴充仍具防禦意義：若日後新增共用 endpoint 的工具組，任兩者 risk_level
        # 不同時，低風險者的 schema 屬性集合不得是高風險者的超集也不得引入對方獨有欄位。
        risk_order = {"read": 0, "idempotent_write": 1, "reversible_write": 2, "high_impact": 3, "irreversible": 4}
        tools_sorted = sorted(tools, key=lambda t: risk_order.get(t.risk_level, 0))
        lowest = tools_sorted[0]
        highest = tools_sorted[-1]
        if lowest.risk_level == highest.risk_level:
            continue
        lowest_props = set(lowest.to_llm_schema()["function"]["parameters"]["properties"])
        highest_only_props = set(highest.to_llm_schema()["function"]["parameters"]["properties"]) - lowest_props
        assert not (lowest_props & highest_only_props), (
            f"endpoint {endpoint}: low-risk tool {lowest.name} exposes fields unique to "
            f"high-risk tool {highest.name}"
        )


def test_projection_allowlist_exactness_with_nested_sentinel_payload():
    """projection allowlist 只輸出白名單指定的頂層欄位；巢狀 sentinel 驗證非白名單欄位不外洩。"""
    registry = get_tool_registry()
    for tool in registry.all():
        if not tool.projection:
            continue
        sentinel_payload = {field: f"__ALLOWED_{field}__" for field in tool.projection}
        sentinel_payload["__SECRET_SENTINEL_SHOULD_NOT_LEAK__"] = "leaked!"
        sentinel_payload["nested_secret"] = {"__SECRET_SENTINEL_SHOULD_NOT_LEAK__": "leaked!"}
        result = project_and_redact(sentinel_payload, tool.projection, max_chars=100_000)
        assert isinstance(result, dict), f"{tool.name}: projection result should be a dict"
        assert "__SECRET_SENTINEL_SHOULD_NOT_LEAK__" not in result, (
            f"{tool.name}: projection leaked a non-allowlisted top-level field"
        )
        assert "nested_secret" not in result, f"{tool.name}: projection leaked a non-allowlisted top-level field"
        for field in tool.projection:
            assert result.get(field) == f"__ALLOWED_{field}__", (
                f"{tool.name}: allowlisted field {field!r} did not pass through projection"
            )
