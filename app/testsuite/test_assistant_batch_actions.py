from types import MethodType

import pytest
from starlette.applications import Starlette

from app.config import AssistantConfig
from app.services.assistant.tool_executor import ToolExecutionOutcome, ToolExecutor
from app.services.assistant.tool_registry import get_tool_registry


def _executor():
    return ToolExecutor(app=Starlette(), main_boundary=None, config=AssistantConfig(tool_timeout_seconds=5), registry=get_tool_registry())


@pytest.mark.asyncio
async def test_batch_actions_preserves_order_and_projects_each_result():
    executor = _executor()
    calls = []

    async def fake_loopback(self, tool, **kwargs):
        calls.append(tool.name)
        return 200, {"id": len(calls), "name": kwargs["body_params"].get("name"), "secret": "blocked"}

    executor._loopback = MethodType(fake_loopback, executor)
    result = await executor._execute_batch_actions([
        {"tool_name": "create_test_case_set", "arguments": {"name": "A"}},
        {"tool_name": "create_test_run_set", "arguments": {"name": "B"}},
    ], team_id=1, jwt="jwt", conversation_key="c", multipart_files={})

    assert calls == ["create_test_case_set", "create_test_run_set"]
    assert result.outcome_status == ToolExecutionOutcome.SUCCEEDED
    assert result.result_payload["succeeded_count"] == 2
    assert all("secret" not in item.get("result", {}) for item in result.result_payload["results"])


@pytest.mark.asyncio
async def test_batch_actions_stops_after_ambiguous_child_without_retry():
    executor = _executor()
    calls = []

    async def fake_loopback(self, tool, **kwargs):
        calls.append(tool.name)
        if len(calls) == 2:
            raise TimeoutError
        return 204, None

    executor._loopback = MethodType(fake_loopback, executor)
    result = await executor._execute_batch_actions([
        {"tool_name": "delete_test_case", "arguments": {"record_id": 1}},
        {"tool_name": "delete_test_case", "arguments": {"record_id": 2}},
        {"tool_name": "delete_test_case", "arguments": {"record_id": 3}},
    ], team_id=1, jwt="jwt", conversation_key="c", multipart_files={})

    assert calls == ["delete_test_case", "delete_test_case"]
    assert result.outcome_status == ToolExecutionOutcome.UNKNOWN
    assert result.result_payload["succeeded_count"] == 1
    assert result.result_payload["attempted_count"] == 2
    assert result.result_payload["remaining_count"] == 1


@pytest.mark.asyncio
async def test_batch_actions_stops_after_partial_business_failure_in_200_response():
    executor = _executor()
    calls = []

    async def fake_loopback(self, tool, **kwargs):
        calls.append(tool.name)
        if tool.name == "batch_update_results":
            return 200, {
                "success": False,
                "processed_count": 2,
                "success_count": 1,
                "error_count": 1,
                "error_messages": ["item 2 failed"],
            }
        return 204, None

    executor._loopback = MethodType(fake_loopback, executor)
    result = await executor._execute_batch_actions([
        {"tool_name": "delete_test_case", "arguments": {"record_id": 1}},
        {"tool_name": "batch_update_results", "arguments": {"config_id": 3, "updates": [{"id": 1}]}},
        {"tool_name": "delete_test_case", "arguments": {"record_id": 2}},
    ], team_id=1, jwt="jwt", conversation_key="c", multipart_files={})

    assert calls == ["delete_test_case", "batch_update_results"]
    assert result.outcome_status == ToolExecutionOutcome.UNKNOWN
    assert result.result_payload["succeeded_count"] == 1
    assert result.result_payload["results"][1]["outcome"] == ToolExecutionOutcome.UNKNOWN
    assert result.result_payload["results"][1]["result"]["success_count"] == 1
    assert result.result_payload["remaining_count"] == 1


@pytest.mark.asyncio
async def test_batch_actions_reports_definitive_business_failure_before_any_mutation():
    executor = _executor()
    calls = []

    async def fake_loopback(self, tool, **kwargs):
        calls.append(tool.name)
        return 200, {"success": False, "created_count": 0, "duplicates": ["TC-1"], "errors": []}

    executor._loopback = MethodType(fake_loopback, executor)
    result = await executor._execute_batch_actions([
        {"tool_name": "bulk_create_test_cases", "arguments": {"items": [{"test_case_number": "TC-1", "title": "Duplicate"}]}},
        {"tool_name": "delete_test_case", "arguments": {"record_id": 2}},
    ], team_id=1, jwt="jwt", conversation_key="c", multipart_files={})

    assert calls == ["bulk_create_test_cases"]
    assert result.outcome_status == ToolExecutionOutcome.FAILED
    assert result.result_payload["status"] == ToolExecutionOutcome.FAILED
    assert result.result_payload["succeeded_count"] == 0
    assert result.result_payload["results"][0]["outcome"] == ToolExecutionOutcome.FAILED
    assert result.result_payload["remaining_count"] == 1


@pytest.mark.asyncio
async def test_direct_confirmed_batch_write_does_not_treat_partial_200_as_success():
    executor = _executor()
    tool = executor.registry.get("batch_delete_test_cases")

    async def fake_loopback(self, tool, **kwargs):
        return 200, {
            "success": False,
            "processed_count": 2,
            "success_count": 1,
            "error_count": 1,
            "error_messages": ["TC-2 failed"],
        }

    executor._loopback = MethodType(fake_loopback, executor)
    result = await executor.execute_confirmed_write(
        tool,
        team_id=1,
        execution_payload={"path_params": {}, "query_params": {}, "body_params": {"record_ids": [1, 2]}},
        jwt="jwt",
        conversation_key="c",
    )

    assert result.outcome_status == ToolExecutionOutcome.UNKNOWN
    assert result.result_payload["processed_count"] == 2
    assert result.result_payload["success_count"] == 1


@pytest.mark.asyncio
async def test_direct_confirmed_batch_write_reports_zero_mutation_business_failure():
    executor = _executor()
    tool = executor.registry.get("bulk_create_test_cases")

    async def fake_loopback(self, tool, **kwargs):
        return 200, {"success": False, "created_count": 0, "duplicates": ["TC-1"], "errors": []}

    executor._loopback = MethodType(fake_loopback, executor)
    result = await executor.execute_confirmed_write(
        tool,
        team_id=1,
        execution_payload={"path_params": {}, "query_params": {}, "body_params": {"items": []}},
        jwt="jwt",
        conversation_key="c",
    )

    assert result.outcome_status == ToolExecutionOutcome.FAILED
    assert result.result_payload["created_count"] == 0
