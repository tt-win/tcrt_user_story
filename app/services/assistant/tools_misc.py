"""工具目錄：Discovery / Pins（tool-matrix.md 第 1 節，1.1–1.4）＋能力自述（local read）。"""

from __future__ import annotations

from app.auth.models import PermissionType
from app.services.assistant.schema_helpers import body, s_str
from app.services.assistant.tool_registry import IDEMPOTENT_WRITE, READ, AssistantTool

# local read（不走 ASGI loopback、team_check=none）：與 loopback 工具分開匯出，
# 因為 `tools_catalog` 只從 loopback 清單推導 batch_execute_actions 的 child enum。
LOCAL_TOOLS = [
    AssistantTool(
        name="describe_capabilities",
        method="LOCAL",
        path_template="",
        summary=(
            "Report what this turn can actually do: conversation scope, the user's role, allowed "
            "permission levels, and which write capability categories were filtered out of the tool "
            "catalog (with the reason and the correct remediation). Call this before telling the user "
            "that a TCRT operation is unavailable — a missing write tool usually means role/scope "
            "filtering, not a missing feature."
        ),
        permission=PermissionType.READ,
        risk_level=READ,
        execution_mode="local",
        team_check="none",
        projection=(
            "scope",
            "team_id",
            "team_name",
            "role",
            "allowed_permissions",
            "withheld_capabilities",
            "reasons",
            "remediation",
        ),
    ),
]

TOOLS = [
    AssistantTool(
        name="list_teams",
        method="LOCAL",
        path_template="",
        summary="List teams the current user can access.",
        permission=PermissionType.READ,
        risk_level=READ,
        team_check="none",
        execution_mode="local",
        projection=("id", "name", "description", "test_case_count"),
    ),
    AssistantTool(
        name="list_pins",
        method="GET",
        path_template="/api/pins",
        summary="List pinned test-case-sets/test-run-sets for the current team.",
        permission=PermissionType.READ,
        risk_level=READ,
        team_check="inject",
        projection=("entity_type", "ids", "token_pinned"),
    ),
    AssistantTool(
        name="pin_entity",
        method="POST",
        path_template="/api/pins",
        summary="Pin a test-case-set or test-run-set for quick access.",
        permission=PermissionType.WRITE,
        risk_level=IDEMPOTENT_WRITE,
        team_check="resolve",
        resource_team_resolver="pin_entity",
        body_schema=body(
            {
                "entity_type": s_str("test_case_set|test_run_set", enum=["test_case_set", "test_run_set"]),
                "entity_id": {"type": "integer"},
            },
            required=["entity_type", "entity_id"],
        ),
        projection=("success", "already_pinned"),
        confirmation_action_key="assistant.action.pin_entity",
        warning_key="assistant.warning.confirm_write",
        target_resolver="create",
    ),
    AssistantTool(
        name="unpin_entity",
        method="DELETE",
        path_template="/api/pins/{entity_type}/{entity_id}",
        summary="Remove a pin. Fully recoverable via pin_entity.",
        permission=PermissionType.WRITE,
        risk_level=IDEMPOTENT_WRITE,  # DELETE 豁免：見 tool-matrix「DELETE 豁免」
        path_params=("entity_type", "entity_id"),
        path_param_schemas={"entity_type": s_str("釘選項目類型", enum=["test_case_set", "test_run_set"])},
        team_check="resolve",
        resource_team_resolver="unpin_entity",
        projection=("success", "deleted"),
        confirmation_action_key="assistant.action.unpin_entity",
        warning_key="assistant.warning.confirm_write",
        target_resolver="single",
    ),
]
