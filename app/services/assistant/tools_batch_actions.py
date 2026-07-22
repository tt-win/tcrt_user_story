"""同一確認內依序執行多個完整、互不依賴的 write action。"""

from app.auth.models import PermissionType
from app.services.assistant.tool_registry import IRREVERSIBLE, AssistantTool


def build_batch_actions_tool(child_names: list[str]) -> AssistantTool:
    action_schema = {
        "type": "object",
        "properties": {
            "tool_name": {"type": "string", "enum": sorted(child_names)},
            "arguments": {"type": "object"},
        },
        "required": ["tool_name", "arguments"],
        "additionalProperties": False,
    }
    return AssistantTool(
        name="batch_execute_actions", method="COMPOSITE", path_template="",
        summary=("Execute 2-50 fully specified independent write actions with one confirmation. "
                 "Do not include actions that need an ID produced by an earlier action."),
        permission=PermissionType.WRITE, risk_level=IRREVERSIBLE, execution_mode="batch_actions",
        body_schema={"type": "object", "properties": {
            "actions": {"type": "array", "items": action_schema, "minItems": 2, "maxItems": 50}},
            "required": ["actions"], "additionalProperties": False},
        team_check="resolve", resource_team_resolver="batch_actions",
        projection=("status", "total", "attempted_count", "succeeded_count", "remaining_count", "results"),
        confirmation_action_key="assistant.action.batch_execute_actions",
        warning_key="assistant.warning.high_impact", target_resolver="batch_actions",
    )
