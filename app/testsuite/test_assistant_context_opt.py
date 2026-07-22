"""Tests for optimize-assistant-context-and-tools (budgets, soft trunc, compact, limits, filter batch)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import AssistantConfig
from app.services.assistant.history_builder import (
    build_exchange_groups,
    build_llm_messages,
    compact_exchange_groups,
    _groups_size,
)
from app.services.assistant.projection import project_and_redact, soft_truncate_list
from app.services.assistant.tool_executor import (
    ToolExecutor,
    _apply_assistant_list_limits,
    _request_skip_from_query,
)
from app.services.assistant.tool_registry import AssistantTool, get_tool_registry
from app.auth.models import PermissionType
from app.services.assistant.tool_registry import READ


def test_assistant_config_defaults_aggressive_budget():
    cfg = AssistantConfig()
    assert cfg.history_max_chars == 480000
    assert cfg.tool_result_max_chars == 64000
    assert cfg.max_iterations == 24
    assert cfg.turn_timeout_seconds == 300
    assert cfg.max_messages_per_conversation == 500
    assert cfg.history_compact_enabled is True
    assert cfg.history_compact_threshold_ratio == 0.75
    assert cfg.history_compact_keep_recent_groups == 4


def test_assistant_config_env_clamps(monkeypatch):
    monkeypatch.setenv("TCRT_ASSISTANT_HISTORY_MAX_CHARS", "999999999")
    monkeypatch.setenv("TCRT_ASSISTANT_TOOL_RESULT_MAX_CHARS", "999999999")
    monkeypatch.setenv("TCRT_ASSISTANT_MAX_ITERATIONS", "999")
    monkeypatch.setenv("TCRT_ASSISTANT_HISTORY_COMPACT_THRESHOLD_RATIO", "0.1")
    monkeypatch.setenv("TCRT_ASSISTANT_HISTORY_COMPACT_KEEP_RECENT_GROUPS", "0")
    cfg = AssistantConfig.from_env()
    assert cfg.history_max_chars == 1200000
    assert cfg.tool_result_max_chars == 200000
    assert cfg.max_iterations == 64
    assert cfg.history_compact_threshold_ratio == 0.5
    assert cfg.history_compact_keep_recent_groups == 1


def test_soft_truncate_list_keeps_full_rows_and_meta():
    rows = [{"id": i, "title": f"case-{i}", "note": "x" * 20} for i in range(50)]
    out = soft_truncate_list(rows, max_chars=800, request_skip=10)
    assert isinstance(out, dict)
    assert "items" in out
    assert out["truncated"] is True
    assert out["source_count"] == 50
    assert out["returned_count"] == len(out["items"])
    assert out["returned_count"] < 50
    assert out["next_skip"] == 10 + out["returned_count"]
    assert out["hint"]
    for row in out["items"]:
        assert "id" in row
        assert "title" in row


def test_soft_truncate_zero_rows_when_single_row_too_large():
    rows = [{"id": 1, "blob": "y" * 5000}]
    out = soft_truncate_list(rows, max_chars=200, request_skip=0)
    assert out["items"] == []
    assert out["truncated"] is True
    assert out["returned_count"] == 0
    assert out["source_count"] == 1


def test_project_and_redact_list_soft_after_redaction():
    payload = [
        {
            "id": 1,
            "title": "a",
            "secret": "nope",
            "test_data": [{"name": "pw", "category": "credential", "value": "secret-xyz"}],
        },
        {"id": 2, "title": "b", "secret": "nope2", "test_data": []},
    ]
    # Under budget: bare list shape preserved after project/redact.
    under = project_and_redact(
        payload,
        ("id", "title", "test_data"),
        max_chars=50_000,
        request_skip=0,
    )
    assert isinstance(under, list)
    assert "secret" not in under[0]
    assert under[0]["test_data"][0]["value"] == "[REDACTED]"
    assert "secret-xyz" not in json.dumps(under)

    # Over budget: envelope + soft trunc.
    fat = [{"id": i, "title": "t" * 40, "test_data": []} for i in range(40)]
    over = project_and_redact(fat, ("id", "title", "test_data"), max_chars=600, request_skip=2)
    assert isinstance(over, dict)
    assert over["truncated"] is True
    assert over["next_skip"] == 2 + over["returned_count"]
    assert over["items"]


def test_hard_truncate_non_list_after_redaction():
    payload = {"allowed_field": "z" * 200, "test_data": [{"category": "credential", "value": "hide-me", "name": "a"}]}
    out = project_and_redact(payload, ("allowed_field", "test_data"), max_chars=40)
    assert out.get("truncated") is True
    assert "hide-me" not in json.dumps(out)


def test_apply_assistant_list_limits_default_and_clamp():
    tool = AssistantTool(
        name="t",
        method="GET",
        path_template="/x",
        summary="s",
        permission=PermissionType.READ,
        risk_level=READ,
        query_params={"limit": {"type": "integer"}, "skip": {"type": "integer"}},
        projection=("id",),
        default_limit=50,
        max_limit=100,
    )
    assert _apply_assistant_list_limits(tool, {})["limit"] == 50
    assert _apply_assistant_list_limits(tool, {"limit": 50000})["limit"] == 100
    assert _apply_assistant_list_limits(tool, {"limit": 10})["limit"] == 10


def test_registry_list_tools_have_limit_clamps():
    reg = get_tool_registry()
    full_items = reg.get("list_test_run_items")
    refs = reg.get("list_test_run_item_refs")
    full_cases = reg.get("list_test_cases")
    case_refs = reg.get("list_test_case_refs")
    filt = reg.get("batch_update_test_run_items_by_filter")
    assert full_items is not None and full_items.default_limit == 50 and full_items.max_limit == 100
    assert refs is not None and refs.max_limit == 500
    assert full_cases is not None and full_cases.max_limit == 100
    assert case_refs is not None and case_refs.max_limit == 200
    assert filt is not None and filt.risk_level == "high_impact"
    assert filt.target_resolver == "filter_batch"


def test_compact_does_not_break_tool_pairs():
    groups = []
    for i in range(6):
        groups.append(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"c{i}",
                            "type": "function",
                            "function": {"name": "list_test_run_item_refs", "arguments": "{}"},
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": f"c{i}",
                    "content": json.dumps([{"id": j, "title": "t" * 80} for j in range(30)]),
                },
            ]
        )
    compact = compact_exchange_groups(
        groups,
        max_chars=2500,
        soft_threshold_ratio=0.5,
        keep_recent_groups=2,
        enabled=True,
    )
    flat = [m for g in compact for m in g]
    # Every tool message must follow its assistant tool_calls with matching id.
    i = 0
    while i < len(flat):
        msg = flat[i]
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            assert i + 1 < len(flat)
            tool_msg = flat[i + 1]
            assert tool_msg.get("role") == "tool"
            assert tool_msg.get("tool_call_id") == msg["tool_calls"][0]["id"]
            i += 2
        else:
            i += 1
    assert _groups_size(compact) <= 2500 or len(compact) == 1


def test_compact_disabled_uses_hard_trim_only():
    # Tiny budget: only newest groups kept via trim, no structural compact path when disabled
    # through build_llm_messages compact_enabled=False (trim only).
    from types import SimpleNamespace

    rows = []
    for i in range(5):
        rows.append(
            SimpleNamespace(
                role="user",
                content=f"user message {i} " + ("u" * 100),
                tool_calls_json=None,
                llm_tool_call_id=None,
                turn_id=i,
            )
        )
        rows.append(
            SimpleNamespace(
                role="assistant",
                content=f"assistant reply {i} " + ("a" * 100),
                tool_calls_json=None,
                llm_tool_call_id=None,
                turn_id=i,
            )
        )
    messages = build_llm_messages(
        rows,
        max_chars=400,
        compact_enabled=False,
    )
    text = json.dumps(messages, ensure_ascii=False)
    assert len(text) <= 450  # soft allowance for trim edge
    assert any(m.get("role") == "user" for m in messages)


def test_request_skip_helper():
    assert _request_skip_from_query({}) == 0
    assert _request_skip_from_query({"skip": 15}) == 15
    assert _request_skip_from_query({"skip": "bad"}) == 0
