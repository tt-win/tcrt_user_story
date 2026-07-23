"""Plan-and-chunk read tools for large assistant batch operations.

These tools are **read** tools: they do not mutate state.  They let the LLM
produce a lightweight plan and then generate detailed actions one chunk at a
time.  Each chunk is still executed through the normal `batch_execute_actions`
composite write tool and its confirmation flow.
"""

from __future__ import annotations

from app.auth.models import PermissionType
from app.services.assistant.schema_helpers import (
    body,
    s_array,
    s_int,
    s_obj,
    s_str,
    s_str_or_int,
)
from app.services.assistant.tool_registry import READ, AssistantTool

# --------------------------------------------------------------------------- #
# Schema fragments
# --------------------------------------------------------------------------- #

_TARGET_SCHEMA = s_obj(
    {
        "target_id": s_str_or_int("stable resource identifier (e.g. record_id, test_case_number)"),
        "target_label": s_str("human-readable label for confirmation summary"),
        "target_type": s_str("resource type: test_case | test_run_item | test_case_set | test_run_config | other"),
    },
    required=["target_id", "target_type"],
)

_CHUNK_ASSIGNMENT_SCHEMA = s_obj(
    {
        "chunk_id": s_str("opaque chunk identifier, unique within the plan"),
        "target_ids": s_array(s_str_or_int(), "list of target_id values assigned to this chunk"),
        "tool_name": s_str("write tool to use for every action in this chunk"),
        "field_scope": s_array(s_str(), "which fields the chunk may modify"),
    },
    required=["chunk_id", "target_ids", "tool_name"],
)

_ACTION_SCHEMA = s_obj(
    {
        "tool_name": s_str("write tool name"),
        "arguments": s_obj({}, required=[]),
    },
    required=["tool_name", "arguments"],
)

TOOLS = [
    AssistantTool(
        name="plan_batch",
        method="LOCAL",
        path_template="",
        summary=(
            "Create a lightweight batch plan before modifying many targets. "
            "Use when the user asks to change more than ~10 items or when a single "
            "batch_execute_actions call would be too large. Returns chunk assignments; "
            "each chunk is later turned into a normal batch_execute_actions confirmation."
        ),
        permission=PermissionType.READ,
        risk_level=READ,
        execution_mode="local",
        team_check="none",
        body_schema=body(
            {
                "batch_job_id": s_str("caller-provided opaque id for this batch job"),
                "goal": s_str("one-sentence description of what the batch should accomplish"),
                "targets": s_array(_TARGET_SCHEMA, "all targets the user wants to affect"),
                "preferred_tool_name": s_str("suggested write tool if known"),
                "max_chunk_actions": s_int("override default chunk size"),
            },
            required=["batch_job_id", "goal", "targets"],
        ),
        projection=("plan",),
    ),
    AssistantTool(
        name="generate_chunk_actions",
        method="LOCAL",
        path_template="",
        summary=(
            "Generate fully-specified write actions for one chunk of a previously "
            "created plan. The returned actions must be passed to batch_execute_actions."
        ),
        permission=PermissionType.READ,
        risk_level=READ,
        execution_mode="local",
        team_check="none",
        body_schema=body(
            {
                "batch_job_id": s_str("same batch_job_id passed to plan_batch"),
                "chunk_id": s_str("chunk identifier from plan_batch result"),
                "goal": s_str("batch goal from plan_batch"),
                "tool_name": s_str("write tool to use for every action"),
                "target_ids": s_array(s_str_or_int(), "targets in this chunk"),
                "field_scope": s_array(s_str(), "fields the chunk may modify"),
                "shared_values": s_obj({}, required=[]),
                "per_target_values": s_obj({}, required=[]),
                "grouping_hints": s_array(s_str(), "optional grouping hints such as section or set"),
            },
            required=["batch_job_id", "chunk_id", "goal", "tool_name", "target_ids"],
        ),
        projection=("actions",),
    ),
]
