"""Skill catalog tools（local read，不走 ASGI loopback）。

對齊 tcrt-app skill 的「任務索引 → 讀 recipe」模式，但改成站內 assistant tool 名稱。
"""

from __future__ import annotations

from app.auth.models import PermissionType
from app.services.assistant.schema_helpers import s_str
from app.services.assistant.tool_registry import READ, AssistantTool

TOOLS = [
    AssistantTool(
        name="list_skills",
        method="LOCAL",
        path_template="",
        summary=(
            "List built-in multi-step operation recipes (skills). "
            "Call this or read the skill catalog in the system prompt before inventing a multi-step plan."
        ),
        permission=PermissionType.READ,
        risk_level=READ,
        execution_mode="local",
        team_check="none",
        projection=("skills", "count"),
    ),
    AssistantTool(
        name="get_skill",
        method="LOCAL",
        path_template="",
        summary=(
            "Load one skill recipe by skill_id. Use for multi-step requests "
            "(assign by prefix, report results, archive, batch updates) instead of trial-and-error tool probing."
        ),
        permission=PermissionType.READ,
        risk_level=READ,
        execution_mode="local",
        team_check="none",
        query_params={
            "skill_id": s_str("skill_id from list_skills / system prompt catalog"),
        },
        required_query=("skill_id",),
        projection=("skill_id", "name", "description", "triggers", "body"),
    ),
]
