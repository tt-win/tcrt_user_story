"""Knowledge base + global SQL read tools for AI Assistant."""

from __future__ import annotations

from app.auth.models import PermissionType
from app.services.assistant.schema_helpers import s_int, s_str
from app.services.assistant.tool_registry import READ, AssistantTool

TOOLS = [
    AssistantTool(
        name="get_test_case_global",
        method="LOCAL",
        path_template="",
        summary=(
            "Get FULL detail of one test case by exact test_case_number across accessible teams "
            "(precondition, steps, expected_result, priority, team_name, set_name). "
            "Prefer this for questions like 'TCG-xxx 的內容/步驟是什麼'. "
            "Do not use knowledge graph for this simple lookup."
        ),
        permission=PermissionType.READ,
        risk_level=READ,
        execution_mode="local",
        team_check="none",
        query_params={
            "test_case_number": s_str("exact test case number, e.g. TCG-134380.010.010"),
        },
        required_query=("test_case_number",),
        projection=(
            "status",
            "found",
            "test_case_number",
            "title",
            "priority",
            "precondition",
            "steps",
            "expected_result",
            "team_id",
            "team_name",
            "set_id",
            "set_name",
            "section_name",
            "record_id",
            "message",
        ),
    ),
    AssistantTool(
        name="search_knowledge",
        method="LOCAL",
        path_template="",
        summary=(
            "Semantic knowledge-base search (vector + optional graph): historical test cases, "
            "USM nodes. Use for fuzzy/semantic questions (e.g. which team owns a feature when "
            "you only have a concept, not an exact number). "
            "Not for simple exact test_case_number lookups — use get_test_case_global instead. "
            "Returns ranked hits with team_id/team_name; may set fallback_recommended."
        ),
        permission=PermissionType.READ,
        risk_level=READ,
        execution_mode="local",
        team_check="none",
        query_params={
            "query": s_str("search query string"),
        },
        required_query=("query",),
        projection=("status", "results", "message", "fallback_recommended"),
    ),
    AssistantTool(
        name="search_test_cases_global",
        method="LOCAL",
        path_template="",
        summary=(
            "SQL keyword search on test case title and test_case_number across accessible teams. "
            "Use for exact/keyword list queries and team ownership by keyword. "
            "Returns slim rows (number, title, priority, team_name, set_id, set_name) — "
            "for full steps use get_test_case_global on a specific number. "
            "Also a fallback when search_knowledge is degraded or empty."
        ),
        permission=PermissionType.READ,
        risk_level=READ,
        execution_mode="local",
        team_check="none",
        query_params={
            "query": s_str("keyword to search in title or test_case_number"),
            "limit": s_int("max results, default 20"),
        },
        required_query=("query",),
        projection=("status", "results", "total"),
    ),
    AssistantTool(
        name="analyze_knowledge_impact",
        method="LOCAL",
        path_template="",
        summary=(
            "Analyze dependency relationships and impact for a test case, USM node, or Jira ticket "
            "via knowledge graph traversal."
        ),
        permission=PermissionType.READ,
        risk_level=READ,
        execution_mode="local",
        team_check="none",
        query_params={
            "entity_type": s_str("entity type: test_case | usm_node | jira_ticket"),
            "entity_id": s_str("entity ID or ticket key"),
        },
        required_query=("entity_type", "entity_id"),
        projection=("status", "results", "message", "fallback_recommended"),
    ),
]
