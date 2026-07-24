"""工具執行核心：schema/權限/team/credential 驗證 → loopback → projection/遮罩（design D1/D8/D9；
spec assistant-tool-execution、assistant-action-confirmation）。

executor 是唯一可執行 write 工具的入口的「守門」，但 write 工具的**實際執行**只能透過
confirm 流程（`execute_confirmed_write`）——`run_tool_in_loop` 對非 read 工具一律硬拒 inline 執行，
改呼叫 `prepare_write_tool` 建立 pending action。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.applications import Starlette

from app.auth.models import PermissionType, UserRole
from app.auth.permission_service import permission_service
from app.config import AssistantConfig
from app.db_access.main import MainAccessBoundary
from app.models.database_models import TestCaseLocal
from app.models.test_case import TestDataCategory
from app.services.assistant import resolvers
from app.services.assistant.crypto import (
    AssistantPayloadEncryptionError,
    encrypt_sensitive_payload,
)
from app.services.assistant.ids import compute_confirmation_fingerprint
from app.services.assistant.param_validation import validate_arguments
from app.services.assistant.projection import project_and_redact, project_error
from app.services.assistant.content_store import get_skill_enabled, list_enabled_skills
from app.services.assistant.tool_registry import AssistantTool, ToolRegistry

logger = logging.getLogger(__name__)



class ToolExecutionOutcome:
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


_SEMANTIC_BATCH_WRITE_TOOLS = {
    "bulk_create_test_cases",
    "bulk_clone_test_cases",
    "batch_update_test_cases",
    "batch_move_test_cases",
    "batch_delete_test_cases",
    "add_test_run_items",
    "batch_update_results",
}


def _classify_batch_write_payload(tool_name: str, payload: Any) -> str:
    """判斷 2xx batch response 的業務結果，避免把部分成功誤報為完整成功。"""
    if tool_name not in _SEMANTIC_BATCH_WRITE_TOOLS:
        return ToolExecutionOutcome.SUCCEEDED
    if not isinstance(payload, dict):
        return ToolExecutionOutcome.UNKNOWN

    errors = payload.get("errors") or payload.get("error_messages") or []
    try:
        error_count = int(payload.get("error_count") or len(errors))
    except (TypeError, ValueError):
        return ToolExecutionOutcome.UNKNOWN

    success_flag = payload.get("success")
    has_business_failure = success_flag is False or error_count > 0 or bool(errors)
    if not has_business_failure:
        return ToolExecutionOutcome.SUCCEEDED if success_flag is True else ToolExecutionOutcome.UNKNOWN

    mutation_count = payload.get("success_count", payload.get("created_count", 0))
    try:
        return ToolExecutionOutcome.UNKNOWN if int(mutation_count or 0) > 0 else ToolExecutionOutcome.FAILED
    except (TypeError, ValueError):
        return ToolExecutionOutcome.UNKNOWN


@dataclass
class RejectionResult:
    """schema/permission/team/credential 驗證失敗；同一交易需寫 paired synthetic result。"""

    code: str
    message: str
    fixable: bool = False  # 僅 schema 可修正錯誤允許迴圈續跑，其餘終止回合


@dataclass
class ReadToolResult:
    ok: bool
    result_payload: dict[str, Any]
    http_status: Optional[int]
    rejection: Optional[RejectionResult] = None


@dataclass
class PendingCreationRequest:
    tool: AssistantTool
    arguments_redacted: dict[str, Any]
    # 已序列化、可直接寫入 assistant_pending_actions.execution_payload_json：
    # 非敏感為 JSON object 字串；敏感為 AES-GCM envelope JSON 字串（勿再包一層 dict）。
    execution_payload_json: str
    execution_payload_encrypted: bool
    confirmation_summary: dict[str, Any]
    confirmation_fingerprint: str


@dataclass
class ConfirmExecutionResult:
    outcome_status: str
    result_payload: dict[str, Any]
    http_status: Optional[int]


_PATH_TEAM_PLACEHOLDER = "{team_id}"
# Starlette route converter 語法（如 {test_case_id:int}、{ticket_number:path}）在 path_template
# 內用於實際路由註冊；`str.format` 不認得 ":converter" 部分，會誤判成 format spec 而拋
# ValueError，故在組出實際 request path 前先剝除，只保留 `{name}`。
_ROUTE_CONVERTER_RE = re.compile(r"\{(\w+):\w+\}")


def combined_schema(tool: AssistantTool) -> dict[str, Any]:
    """path + query + body（+file_ref）合併成單一 object schema，供整體 arguments 驗證用。"""
    return tool.to_llm_schema()["function"]["parameters"]


def _apply_assistant_list_limits(tool: AssistantTool, query_params: dict[str, Any]) -> dict[str, Any]:
    """Inject default_limit / clamp max_limit for assistant list tools (loopback only)."""
    if tool.default_limit is None and tool.max_limit is None:
        return query_params
    if "limit" not in tool.query_params:
        return query_params
    out = dict(query_params)
    if "limit" not in out and tool.default_limit is not None:
        out["limit"] = tool.default_limit
    if "limit" in out and tool.max_limit is not None:
        try:
            limit_val = int(out["limit"])
        except (TypeError, ValueError):
            limit_val = tool.max_limit
        out["limit"] = max(1, min(limit_val, tool.max_limit))
    return out


def _request_skip_from_query(query_params: dict[str, Any]) -> int:
    raw = query_params.get("skip", 0)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def _split_arguments(tool: AssistantTool, arguments: dict[str, Any]) -> tuple[dict, dict, dict]:
    path_params = {k: arguments[k] for k in tool.path_params if k in arguments}
    query_params = {k: arguments[k] for k in tool.query_params if k in arguments}
    query_params = _apply_assistant_list_limits(tool, query_params)
    body_params = {
        k: v
        for k, v in arguments.items()
        if k not in tool.path_params and k not in tool.query_params and k != "file_ref"
    }
    return path_params, query_params, body_params


def _build_path(tool: AssistantTool, *, team_id: Optional[int], path_params: dict) -> str:
    fmt_args = dict(path_params)
    if _PATH_TEAM_PLACEHOLDER in tool.path_template:
        if team_id is None:
            raise ValueError(f"{tool.name} requires team_id but conversation has none")
        fmt_args["team_id"] = team_id
    template = _ROUTE_CONVERTER_RE.sub(r"{\1}", tool.path_template)
    return template.format(**fmt_args)


def _find_credential_hits(value: Any) -> bool:
    """遞迴掃描 body 欄位，尋找 category=credential 且 value 非空的 test_data 項目。"""
    if isinstance(value, dict):
        category = str(value.get("category", "")).lower()
        if category == TestDataCategory.CREDENTIAL.value and value.get("value"):
            return True
        return any(_find_credential_hits(v) for v in value.values())
    if isinstance(value, list):
        return any(_find_credential_hits(v) for v in value)
    return False


class ToolExecutor:
    def __init__(self, *, app: Starlette, main_boundary: MainAccessBoundary, config: AssistantConfig, registry: ToolRegistry):
        self.app = app
        self.main_boundary = main_boundary
        self.config = config
        self.registry = registry

    # ------------------------------------------------------------------ #
    # 權限 / team / credential 檢查
    # ------------------------------------------------------------------ #

    async def check_permission(self, tool: AssistantTool, *, user_id: int, team_id: Optional[int], role: UserRole) -> bool:
        if role == UserRole.SUPER_ADMIN:
            return True
        if team_id is None:
            return tool.permission == PermissionType.READ  # 全域對話僅允許 discovery
        check = await permission_service.check_team_permission(user_id, team_id, tool.permission, role)
        return check.has_permission

    async def resolve_team(self, tool: AssistantTool, *, conversation_team_id: Optional[int], path_params: dict, body_params: dict) -> Optional[int]:
        """回傳工具實際作用資源的 team_id；有 resolver 時即使 path 注入 team 仍必須核對資源。"""
        if tool.team_check == "none":
            return None
        if tool.team_check == "inject" and not tool.resource_team_resolver:
            return conversation_team_id
        if tool.resource_team_resolver == "batch_actions":
            teams: set[int] = set()
            for action in body_params.get("actions") or []:
                child = self.registry.get(action.get("tool_name"))
                arguments = action.get("arguments")
                if child is None or child.execution_mode != "loopback" or not child.is_write() or not isinstance(arguments, dict):
                    return None
                if not validate_arguments(arguments, combined_schema(child)).ok:
                    return None
                child_path, _, child_body = _split_arguments(child, arguments)
                child_team = await self.resolve_team(
                    child, conversation_team_id=conversation_team_id, path_params=child_path, body_params=child_body
                )
                if child.team_check != "none" and child_team != conversation_team_id:
                    return None
                teams.add(conversation_team_id)
            return conversation_team_id if teams else None

        async def _resolve(session: AsyncSession) -> Optional[int]:
            key = tool.resource_team_resolver
            if key == "test_case":
                rid = path_params.get("record_id") or path_params.get("test_case_id")
                return await resolvers.resolve_test_case_team(session, rid)
            if key == "test_case_set":
                return await resolvers.resolve_test_case_set_team(session, path_params["set_id"])
            if key == "test_case_section":
                return await resolvers.resolve_test_case_section_team(
                    session, path_params["section_id"], expected_set_id=path_params.get("set_id")
                )
            if key == "test_run_config":
                return await resolvers.resolve_test_run_config_team(session, path_params["config_id"])
            if key == "test_run_item":
                return await resolvers.resolve_test_run_item_team(
                    session, path_params["item_id"], expected_config_id=path_params.get("config_id")
                )
            if key == "test_run_set":
                return await resolvers.resolve_test_run_set_team(session, path_params["set_id"])
            if key == "automation_run":
                return await resolvers.resolve_automation_run_team(
                    session, path_params["run_id"], expected_set_id=path_params.get("set_id")
                )
            if key in ("pin_entity",):
                return await resolvers.resolve_pin_entity_team(
                    session, body_params.get("entity_type"), body_params.get("entity_id")
                )
            if key == "unpin_entity":
                # unpin 由 executor 呼叫端注入 user_id（見 run_tool_in_loop）
                return await resolvers.resolve_pin_entity_team(
                    session, path_params.get("entity_type"), path_params.get("entity_id")
                )
            if key in ("create_test_case_scope", "move_test_case_scope"):
                return await self._resolve_all_equal(
                    session,
                    [
                        ("test_case_set", body_params.get("test_case_set_id")),
                        ("test_case_section", body_params.get("test_case_section_id")),
                    ]
                    + ([("test_case", path_params.get("record_id"))] if "record_id" in path_params else []),
                    # 未指定 set/section 時使用 team 預設 set；此情境沒有可跨查的 sub-resource，
                    # 信任對話綁定 team（同 inject 語意），而非因空集合而 fail-closed。
                    default_if_empty=conversation_team_id,
                )
            if key == "batch_test_cases_same_team":
                ids = body_params.get("record_ids") or []
                pairs = [("test_case", rid) for rid in ids]
                return await self._resolve_all_equal(session, pairs)
            if key == "batch_test_run_items_same_config":
                config_id = path_params.get("config_id")
                config_team = await resolvers.resolve_test_run_config_team(session, config_id)
                if config_team is None:
                    return None
                ids = [update.get("id") for update in body_params.get("updates") or [] if isinstance(update, dict)]
                if not ids:
                    return None
                for item_id in ids:
                    item_team = await resolvers.resolve_test_run_item_team(
                        session, item_id, expected_config_id=config_id
                    )
                    if item_team != config_team:
                        return None
                return config_team
            if key == "batch_move_test_cases":
                ids = body_params.get("record_ids") or []
                update_data = body_params.get("update_data") or {}
                pairs = [("test_case", rid) for rid in ids]
                if update_data.get("test_set_id"):
                    pairs.append(("test_case_set", update_data["test_set_id"]))
                if update_data.get("section_id"):
                    pairs.append(("test_case_section", update_data["section_id"]))
                return await self._resolve_all_equal(session, pairs)
            if key == "create_test_run_config_scope":
                ids = body_params.get("test_case_set_ids") or []
                return await self._resolve_all_equal(
                    session, [("test_case_set", sid) for sid in ids], default_if_empty=conversation_team_id
                )
            if key == "update_test_run_scope":
                ids = body_params.get("test_case_set_ids") or []
                pairs = [("test_run_config", path_params.get("config_id"))] + [("test_case_set", sid) for sid in ids]
                return await self._resolve_all_equal(session, pairs)
            if key == "add_runs_to_set":
                ids = body_params.get("config_ids") or []
                pairs = [("test_run_set", path_params.get("set_id"))] + [("test_run_config", cid) for cid in ids]
                return await self._resolve_all_equal(session, pairs)
            if key == "move_run_between_sets":
                pairs = [("test_run_config", path_params.get("config_id"))]
                if body_params.get("target_set_id"):
                    pairs.append(("test_run_set", body_params["target_set_id"]))
                return await self._resolve_all_equal(session, pairs)
            if key == "bulk_clone_test_cases":
                # API BulkCloneItem 使用 source_record_id；逐筆 resolve 來源 case 的 team。
                items = body_params.get("items") or []
                resolved_teams: list[int] = []
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    rid = it.get("source_record_id")
                    if rid is None:
                        continue
                    resolved_team = await resolvers.resolve_test_case_ref_team(session, rid)
                    if resolved_team is None:
                        return None
                    resolved_teams.append(resolved_team)
                return (
                    resolved_teams[0]
                    if resolved_teams and all(team == resolved_teams[0] for team in resolved_teams)
                    else (conversation_team_id if not resolved_teams else None)
                )
            if key == "preview_move_test_set_impact":
                ids = body_params.get("record_ids") or []
                pairs = [("test_case", rid) for rid in ids] + [("test_case_set", body_params.get("target_test_set_id"))]
                return await self._resolve_all_equal(session, pairs)
            raise ValueError(f"unknown resource_team_resolver: {key}")

        return await self.main_boundary.run_read(_resolve)

    async def _resolve_all_equal(
        self, session: AsyncSession, pairs: list[tuple[str, Any]], *, default_if_empty: Optional[int] = None
    ) -> Optional[int]:
        """依序解析每個 (resolver_key, id) 的 team，全部存在且相等才回傳該 team；否則 fail-closed 回 None。

        `default_if_empty`：當 pairs 內沒有任何非 None id 時使用（例如 create 未指定 set/section，
        使用 team 預設 set——此時沒有可跨查的 sub-resource，不應因空集合而 fail-closed）。
        """
        team_ids: set[int] = set()
        simple = {
            "test_case": resolvers.resolve_test_case_team,
            "test_case_set": resolvers.resolve_test_case_set_team,
            "test_case_section": resolvers.resolve_test_case_section_team,
            "test_run_config": resolvers.resolve_test_run_config_team,
            "test_run_set": resolvers.resolve_test_run_set_team,
        }
        any_checked = False
        for kind, rid in pairs:
            if rid is None:
                continue
            any_checked = True
            fn = simple.get(kind)
            if fn is None:
                return None
            team_id = await fn(session, rid)
            if team_id is None:
                return None  # 資源不存在
            team_ids.add(team_id)
        if not any_checked:
            return default_if_empty
        if len(team_ids) != 1:
            return None  # 跨 team
        return next(iter(team_ids))

    def check_credential_write_rejected(self, tool: AssistantTool, body_params: dict) -> bool:
        for field_name in tool.credential_check_fields:
            if field_name in body_params and _find_credential_hits(body_params[field_name]):
                return True
        return False

    async def check_update_overwrites_existing_credential(self, tool: AssistantTool, path_params: dict, body_params: dict) -> bool:
        """update_test_case 專屬：既有 case 含 credential 時拒絕 test_data 覆寫（design D8）。

        `record_id` 可能是本地整數 id 或 Lark record id 字串（紅隊發現：原本只查
        `TestCaseLocal.id`，對 Lark 同步的 case 會查無此列而靜默回傳 False，等同 fail-open
        繞過既有 credential 的保護）；查找順序須與 `resolvers.resolve_test_case_identity`／
        `resolve_test_case_team` 一致——先試本地整數 id，查無才查 `lark_record_id`。"""
        if tool.name != "update_test_case" or "test_data" not in body_params:
            return False
        record_id = path_params.get("record_id")

        async def _check(session: AsyncSession) -> bool:
            try:
                local_id = int(record_id)
            except (TypeError, ValueError):
                local_id = None
            row = None
            if local_id is not None:
                row = (
                    await session.execute(
                        select(TestCaseLocal.test_data_json).where(TestCaseLocal.id == local_id)
                    )
                ).scalar_one_or_none()
            if row is None:
                row = (
                    await session.execute(
                        select(TestCaseLocal.test_data_json).where(
                            TestCaseLocal.lark_record_id == str(record_id)
                        )
                    )
                ).scalar_one_or_none()
            if not row:
                return False
            try:
                existing = json.loads(row)
            except (TypeError, ValueError):
                return False
            return _find_credential_hits(existing)

        return await self.main_boundary.run_read(_check)

    async def validate_batch_actions(
        self, actions: list[dict[str, Any]], *, conversation_team_id: Optional[int], user_id: int, role: UserRole
    ) -> Optional[RejectionResult]:
        if not 2 <= len(actions) <= 50:
            return RejectionResult("schema_invalid", "batch requires 2-50 actions", fixable=True)
        # Size guardrail: avoid single LLM responses so large that they trigger timeout/length truncation.
        total_payload_chars = len(json.dumps(actions, ensure_ascii=False))
        max_chunk_actions = max(2, min(self.config.batch_chunk_max_actions, 50))
        max_payload_chars = max(1000, self.config.batch_chunk_max_payload_chars)
        if len(actions) > max_chunk_actions or total_payload_chars > max_payload_chars:
            return RejectionResult(
                "batch_too_large",
                (
                    f"This batch has {len(actions)} actions / {total_payload_chars} chars, which exceeds "
                    f"the safe single-call limit ({max_chunk_actions} actions / {max_payload_chars} chars). "
                    "Use plan_batch + generate_chunk_actions to split into smaller chunks."
                ),
                fixable=True,
            )
        for index, action in enumerate(actions):
            child = self.registry.get(action.get("tool_name"))
            arguments = action.get("arguments")
            if child is None or child.execution_mode != "loopback" or not child.is_write() or not isinstance(arguments, dict):
                return RejectionResult("schema_invalid", f"action {index + 1}: unsupported action", fixable=True)
            validation = validate_arguments(arguments, combined_schema(child))
            if not validation.ok:
                return RejectionResult("schema_invalid", f"action {index + 1}: {'; '.join(validation.errors)}", fixable=True)
            path_params, _, body_params = _split_arguments(child, arguments)
            if not await self.check_permission(child, user_id=user_id, team_id=conversation_team_id, role=role):
                return RejectionResult("permission_denied", f"action {index + 1}: insufficient permission")
            resolved_team = await self.resolve_team(
                child, conversation_team_id=conversation_team_id, path_params=path_params, body_params=body_params
            )
            if child.team_check != "none" and resolved_team != conversation_team_id:
                return RejectionResult("team_mismatch", f"action {index + 1}: resource is outside this team")
            if self.check_credential_write_rejected(child, body_params) or await self.check_update_overwrites_existing_credential(child, path_params, body_params):
                return RejectionResult("credential_write_rejected", f"action {index + 1}: credential writes are not supported")
        return None

    # ------------------------------------------------------------------ #
    # Confirmation summary（design D3；spec assistant-action-confirmation）
    # ------------------------------------------------------------------ #

    async def build_confirmation_summary(
        self, tool: AssistantTool, *, path_params: dict, body_params: dict
    ) -> Optional[tuple[dict[str, Any], Any]]:
        """回傳 (canonical_summary, stable_target_identity)；None 代表無法解析（fail-closed）。"""
        strategy = tool.target_resolver

        if strategy == "batch_actions":
            entries: list[dict[str, Any]] = []
            identities: list[dict[str, Any]] = []
            risk_rank = {"idempotent_write": 1, "reversible_write": 2, "high_impact": 3, "irreversible": 4}
            highest = "idempotent_write"
            for index, action in enumerate(body_params.get("actions") or []):
                child = self.registry.get(action.get("tool_name"))
                arguments = action.get("arguments")
                if child is None or child.execution_mode != "loopback" or not child.is_write() or not isinstance(arguments, dict):
                    return None
                validation = validate_arguments(arguments, combined_schema(child))
                if not validation.ok:
                    return None
                child_path, _, child_body = _split_arguments(child, arguments)
                child_summary = await self.build_confirmation_summary(child, path_params=child_path, body_params=child_body)
                if child_summary is None:
                    return None
                summary, identity = child_summary
                highest = child.risk_level if risk_rank[child.risk_level] > risk_rank[highest] else highest
                entries.append({"index": index + 1, "tool_name": child.name, "action": child.confirmation_action_key,
                                "risk_level": child.risk_level, "target": summary})
                identities.append({"index": index + 1, "tool_name": child.name, "identity": identity})
            if not 2 <= len(entries) <= 50:
                return None
            outer = {"action": tool.confirmation_action_key, "risk_level": highest,
                     "target_type": "batch_actions", "affected_count": len(entries), "actions": entries}
            return outer, {"kind": "batch_actions", "actions": identities}

        if strategy == "filter_batch":
            # Single shared resolver with the HTTP endpoint (title+number search, cap+1).
            from fastapi import HTTPException

            from app.api.test_run_items import (
                FILTER_BATCH_MATCHED_CAP,
                BatchUpdateByFilterFilter,
                resolve_filter_batch_matches_sync,
            )

            config_id = path_params.get("config_id")
            if config_id is None:
                return None

            async def _config_team(session: AsyncSession) -> Optional[int]:
                return await resolvers.resolve_test_run_config_team(session, config_id)

            config_team = await self.main_boundary.run_read(_config_team)
            if config_team is None:
                return None
            raw_filter = body_params.get("filter") or {}
            if not isinstance(raw_filter, dict):
                return None
            patch = body_params.get("patch") or {}
            if not isinstance(patch, dict):
                return None
            if patch.get("assignee_name") is None and patch.get("test_result") is None:
                return None
            try:
                filt = BatchUpdateByFilterFilter.model_validate(raw_filter)
            except Exception:  # noqa: BLE001
                return None

            def _match(sync_db):
                return resolve_filter_batch_matches_sync(
                    sync_db,
                    team_id=int(config_team),
                    config_id=int(config_id),
                    filt=filt,
                )

            try:
                rows = await self.main_boundary.run_sync_read(_match)
            except HTTPException:
                # Mutual exclusion / validation from shared resolver → fail-closed (no pending).
                return None
            if not rows or len(rows) > FILTER_BATCH_MATCHED_CAP:
                return None
            matched_ids = [int(r.id) for r in rows]
            filter_dump = filt.model_dump(exclude_none=True)
            patch_dump = {k: v for k, v in patch.items() if v is not None}
            summary = {
                "action": tool.confirmation_action_key,
                "risk_level": tool.risk_level,
                "target_type": "filter_batch",
                "affected_count": len(matched_ids),
                "matched_count": len(matched_ids),
                "filter": filter_dump,
                "patch": patch_dump,
                "sample_ids": matched_ids[:10],
                "config_id": config_id,
            }
            return summary, {
                "kind": "filter_batch",
                "config_id": config_id,
                "matched_ids": matched_ids,
                "filter": filter_dump,
                "patch": patch_dump,
            }

        async def _resolve(session: AsyncSession) -> Optional[tuple[dict, Any]]:
            if strategy == "create":
                target_label = (
                    body_params.get("name") or body_params.get("title") or body_params.get("test_case_number")
                    or body_params.get("ticket_number")
                    or (f"{body_params.get('entity_type')} #{body_params.get('entity_id')}" if body_params.get("entity_type") else None)
                )
                summary = {
                    "action": tool.confirmation_action_key,
                    "risk_level": tool.risk_level,
                    "target_type": "new",
                    "target_label": target_label,
                    "affected_count": 1,
                }
                return summary, {"kind": "create", "label": target_label}

            if strategy == "single":
                resolver_key = tool.resource_team_resolver
                identity_key = {
                    "move_test_case_scope": "test_case",
                    "update_test_run_scope": "test_run_config",
                    "move_run_between_sets": "test_run_config",
                }.get(resolver_key, resolver_key)
                identity_fn = resolvers.IDENTITY_RESOLVERS.get(identity_key)
                pk_field = {
                    "test_case": "record_id" if "record_id" in path_params else "test_case_id",
                    "test_case_set": "set_id", "test_case_section": "section_id",
                    "test_run_config": "config_id", "test_run_item": "item_id",
                    "test_run_set": "set_id", "automation_run": "run_id",
                }.get(identity_key)
                pk = path_params.get(pk_field) if pk_field else None
                if resolver_key == "unpin_entity":
                    entity_type = path_params.get("entity_type")
                    entity_id = path_params.get("entity_id")
                    if entity_type and entity_id is not None:
                        summary = {"action": tool.confirmation_action_key, "risk_level": tool.risk_level,
                                   "target_type": "pin", "target_id": entity_id,
                                   "target_label": f"{entity_type} #{entity_id}", "affected_count": 1}
                        return summary, {"kind": "single", "path_params": path_params}
                if identity_fn is None or pk is None:
                    return None
                identity = await identity_fn(session, pk)
                if identity is None:
                    return None
                label, version = identity
                if tool.name == "delete_test_case_attachment" and path_params.get("target"):
                    label = f"{label} / {path_params['target']}"
                if tool.name == "remove_item_bug_ticket" and path_params.get("ticket_number"):
                    label = f"{label} / {path_params['ticket_number']}"
                summary = {
                    "action": tool.confirmation_action_key,
                    "risk_level": tool.risk_level,
                    "target_type": identity_key,
                    "target_id": pk,
                    "target_label": label,
                    "affected_count": 1,
                }
                return summary, {"kind": "single", "id": pk, "version": version, "path_params": path_params}

            if strategy == "batch":
                targets: list[dict[str, Any]] = []
                stable_targets: list[dict[str, Any]] = []
                if tool.name == "bulk_create_test_cases":
                    for item in body_params.get("items") or []:
                        number = item.get("test_case_number")
                        label = f"{number} — {item.get('title')}"
                        targets.append({"target_key": number, "target_label": label})
                        stable_targets.append({"key": number, "label": label})
                elif tool.name == "bulk_clone_test_cases":
                    for item in body_params.get("items") or []:
                        source_ref = item.get("source_record_id")
                        identity = await resolvers.resolve_test_case_ref_identity(session, source_ref)
                        if identity is None:
                            return None
                        source_id, label, version = identity
                        new_number = item.get("test_case_number")
                        targets.append({"target_id": source_id, "target_label": f"{label} → {new_number}"})
                        stable_targets.append({"id": source_id, "source_ref": source_ref,
                                               "version": version, "new_number": new_number})
                elif tool.name == "add_test_run_items":
                    config_team = await resolvers.resolve_test_run_config_team(session, path_params.get("config_id"))
                    if config_team is None:
                        return None
                    for item in body_params.get("items") or []:
                        number = item.get("test_case_number")
                        row = (await session.execute(
                            select(TestCaseLocal.id, TestCaseLocal.title, TestCaseLocal.local_version).where(
                                TestCaseLocal.team_id == config_team, TestCaseLocal.test_case_number == number
                            )
                        )).one_or_none()
                        if row is None:
                            return None
                        targets.append({"target_id": row[0], "target_label": f"{number} — {row[1]}"})
                        stable_targets.append({"id": row[0], "number": number, "version": row[2]})
                else:
                    ids = body_params.get("record_ids") or [u.get("id") for u in body_params.get("updates", [])] or []
                    identity_fn = (
                        resolvers.resolve_test_run_item_identity
                        if tool.name == "batch_update_results" else resolvers.resolve_test_case_identity
                    )
                    def _sort_key(val: Any) -> tuple[int, int | str]:
                        try:
                            return (0, int(val))
                        except (TypeError, ValueError):
                            return (1, str(val))

                    for target_id in sorted(ids, key=_sort_key):
                        identity = await identity_fn(session, target_id)
                        if identity is None:
                            return None
                        label, version = identity
                        targets.append({"target_id": target_id, "target_label": label})
                        stable_targets.append({"id": target_id, "version": version})
                if tool.risk_level in ("high_impact", "irreversible") and not targets:
                    return None
                summary = {
                    "action": tool.confirmation_action_key,
                    "risk_level": tool.risk_level,
                    "target_type": "batch",
                    "affected_count": len(targets),
                    "targets": targets,
                }
                return summary, {"kind": "batch", "targets": stable_targets, "path_params": path_params}

            if strategy == "membership":
                config_ids = sorted(str(i) for i in (body_params.get("config_ids") or []))
                summary = {
                    "action": tool.confirmation_action_key,
                    "risk_level": tool.risk_level,
                    "target_type": "membership",
                    "target_id": path_params.get("set_id"),
                    "affected_count": len(config_ids),
                }
                return summary, {"kind": "membership", "set_id": path_params.get("set_id"), "members": config_ids}

            return None

        result = await self.main_boundary.run_read(_resolve)
        if result is None and tool.risk_level in ("high_impact", "irreversible"):
            return None  # fail-closed：高風險工具無法解析即不建立 pending
        if result is None:
            # 非高風險：仍需回傳固定「無法解析影響範圍」摘要，而非 LLM 自述
            return (
                {
                    "action": tool.confirmation_action_key,
                    "risk_level": tool.risk_level,
                    "target_type": "unknown",
                    "warning": "impact_scope_unresolvable",
                },
                {"kind": "unresolvable"},
            )
        return result

    def compute_fingerprint(self, summary: dict, stable_identity: Any) -> str:
        return compute_confirmation_fingerprint(canonical_summary=summary, stable_target_identity=stable_identity)

    # ------------------------------------------------------------------ #
    # Loopback 執行
    # ------------------------------------------------------------------ #

    async def _loopback(
        self,
        tool: AssistantTool,
        *,
        team_id: Optional[int],
        path_params: dict,
        query_params: dict,
        body_params: dict,
        jwt: str,
        conversation_key: str,
        files: Optional[dict[str, tuple[str, bytes, str]]] = None,
    ) -> tuple[int, Any]:
        path = _build_path(tool, team_id=team_id, path_params=path_params)
        headers = {
            "Authorization": f"Bearer {jwt}",
            "X-TCRT-Assistant": "1",
            "User-Agent": f"TCRT-Assistant/1.0 conversation={conversation_key}",
        }
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://assistant.internal") as client:
            body = {**tool.fixed_body, **body_params} if (tool.body_schema or tool.fixed_body) else None
            if files:
                response = await client.request(
                    tool.method, path, params=query_params or None, data=body or None, files=files, headers=headers, timeout=self.config.tool_timeout_seconds
                )
            else:
                response = await client.request(
                    tool.method, path, params=query_params or None, json=body, headers=headers, timeout=self.config.tool_timeout_seconds
                )
        try:
            payload = response.json() if response.content else None
        except ValueError:
            payload = response.text
        return response.status_code, payload

    # ------------------------------------------------------------------ #
    # Read tool（inline 執行；唯一可 inline 執行的 risk level）
    # ------------------------------------------------------------------ #

    async def _enrich_result_team_names(self, results: list[Any]) -> None:
        """Fill missing/placeholder team_name from main DB Team table (in-place)."""
        from app.models.database_models import Team

        need_ids: set[int] = set()
        for item in results:
            if not isinstance(item, dict):
                continue
            raw_id = item.get("team_id")
            name = item.get("team_name")
            if raw_id is None or raw_id == "unknown":
                continue
            try:
                tid = int(raw_id)
            except (TypeError, ValueError):
                continue
            if not name or name == f"Team-{tid}" or name == "Team-unknown":
                need_ids.add(tid)
        if not need_ids:
            return

        async def _load(session: AsyncSession) -> dict[int, str]:
            rows = (await session.execute(select(Team.id, Team.name).where(Team.id.in_(list(need_ids))))).all()
            return {int(r.id): str(r.name) for r in rows if r.name}

        try:
            names = await self.main_boundary.run_read(_load)
        except Exception:  # noqa: BLE001
            logger.exception("failed to enrich knowledge result team names")
            return

        for item in results:
            if not isinstance(item, dict):
                continue
            try:
                tid = int(item.get("team_id"))
            except (TypeError, ValueError):
                continue
            if tid in names:
                item["team_name"] = names[tid]
                meta = item.get("metadata")
                if isinstance(meta, dict):
                    meta["team_name"] = names[tid]

    async def _resolve_username(self, user_id: int | None) -> str | None:
        """從 main DB 查詢 user.username（觀測性記錄用）。

        失敗 MUST NOT 影響查詢行為；返回 None 表示「無法取得 username」，
        call site 仍會繼續記錄並把 username 留空。輕量 SQL（User.id 主鍵），
        不快取：觀測性欄位的鮮度比微秒級 cache 重要。
        """
        if user_id is None:
            return None
        try:
            from app.models.database_models import User
            from sqlalchemy import select

            async def _q(session):
                return (await session.execute(
                    select(User.username).where(User.id == user_id)
                )).scalar_one_or_none()

            return await self.main_boundary.run_read(_q)
        except Exception as exc:  # noqa: BLE001
            logger.warning("resolve username for user_id=%s failed: %s", user_id, exc)
            return None

    async def _run_local_read_tool(
        self,
        tool: AssistantTool,
        arguments: dict[str, Any],
        team_id: int | None = None,
        user_id: int | None = None,
        *,
        llm_tool_call_id: str | None = None,
        conversation_id: str | None = None,
        turn_key: str | None = None,
        username: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        """In-process skill/catalog/knowledge tools：不打 ASGI。"""
        if tool.name == "list_skills":
            skills = await list_enabled_skills(self.main_boundary)
            return 200, {"skills": skills, "count": len(skills)}
        if tool.name == "get_skill":
            skill_id = arguments.get("skill_id")
            skill = await get_skill_enabled(self.main_boundary, str(skill_id) if skill_id is not None else "")
            if skill is None:
                return 404, {"detail": f"unknown skill_id: {skill_id}"}
            return 200, skill
        if tool.name == "get_test_case_global":
            from app.models.database_models import Team, TestCaseLocal, TestCaseSection, TestCaseSet

            number = str(arguments.get("test_case_number", "")).strip()
            if not number:
                return 200, {"status": "success", "found": False, "message": "test_case_number is required."}

            allowed_team_ids_detail: list[int] = []
            if user_id is not None:
                try:
                    allowed_team_ids_detail = await permission_service.get_user_accessible_teams(user_id)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "get_test_case_global: failed to resolve accessible teams user_id=%s", user_id
                    )
                    allowed_team_ids_detail = []
            if not allowed_team_ids_detail:
                return 200, {
                    "status": "success",
                    "found": False,
                    "message": "No accessible teams for this lookup.",
                }

            async def _get_one(session: AsyncSession) -> Any | None:
                stmt = (
                    select(
                        TestCaseLocal.id,
                        TestCaseLocal.test_case_number,
                        TestCaseLocal.title,
                        TestCaseLocal.priority,
                        TestCaseLocal.precondition,
                        TestCaseLocal.steps,
                        TestCaseLocal.expected_result,
                        TestCaseLocal.team_id,
                        TestCaseLocal.test_case_set_id,
                        TestCaseSet.name.label("set_name"),
                        Team.name.label("team_name"),
                        TestCaseSection.name.label("section_name"),
                    )
                    .join(TestCaseSet, TestCaseLocal.test_case_set_id == TestCaseSet.id, isouter=True)
                    .join(Team, TestCaseLocal.team_id == Team.id, isouter=True)
                    .join(
                        TestCaseSection,
                        TestCaseLocal.test_case_section_id == TestCaseSection.id,
                        isouter=True,
                    )
                    .where(
                        TestCaseLocal.test_case_number == number,
                        TestCaseLocal.team_id.in_(allowed_team_ids_detail),
                    )
                    .limit(1)
                )
                return (await session.execute(stmt)).first()

            row = await self.main_boundary.run_read(_get_one)
            if row is None:
                return 200, {
                    "status": "success",
                    "found": False,
                    "test_case_number": number,
                    "message": f"Test case {number} not found in accessible teams.",
                }
            priority = row.priority.value if hasattr(row.priority, "value") else row.priority
            return 200, {
                "status": "success",
                "found": True,
                "record_id": row.id,
                "test_case_number": row.test_case_number,
                "title": row.title or "",
                "priority": priority,
                "precondition": row.precondition or "",
                "steps": row.steps or "",
                "expected_result": row.expected_result or "",
                "team_id": row.team_id,
                "team_name": row.team_name or f"Team-{row.team_id}",
                "set_id": row.test_case_set_id,
                "set_name": row.set_name or "",
                "section_name": row.section_name or "",
            }
        if tool.name == "search_knowledge":
            from app.services.knowledge import get_retrieval_service
            from app.audit.database import KnowledgeQuerySource

            query = str(arguments.get("query", ""))
            # Fail closed: missing user_id or empty access set → no cross-team scan.
            allowed_team_ids: list[int] = []
            if user_id is not None:
                try:
                    allowed_team_ids = await permission_service.get_user_accessible_teams(user_id)
                except Exception:  # noqa: BLE001
                    logger.exception("search_knowledge: failed to resolve accessible teams user_id=%s", user_id)
                    allowed_team_ids = []
            res = await get_retrieval_service().search_knowledge(
                query=query,
                primary_team_id=team_id,
                allowed_team_ids=allowed_team_ids,
                context={
                    "source": KnowledgeQuerySource.ASSISTANT.value,
                    "user_id": user_id,
                    "username": username,
                    "conversation_id": conversation_id,
                    "turn_key": turn_key,
                    "llm_tool_call_id": llm_tool_call_id,
                },
            )
            # Enrich team_name from main DB when payload only has team_id (common for USM).
            if isinstance(res, dict) and res.get("results"):
                await self._enrich_result_team_names(res["results"])
            return 200, res
        if tool.name == "search_test_cases_global":
            from sqlalchemy import or_

            from app.models.database_models import Team, TestCaseLocal, TestCaseSet

            query = str(arguments.get("query", "")).strip()
            if not query:
                return 200, {"status": "success", "results": [], "total": 0}

            raw_limit = arguments.get("limit", 20)
            limit = min(int(raw_limit) if raw_limit else 20, 50)

            # Fail closed: unknown access set → empty results, never scan all teams.
            allowed_team_ids_sql: list[int] = []
            if user_id is not None:
                try:
                    allowed_team_ids_sql = await permission_service.get_user_accessible_teams(user_id)
                except Exception:  # noqa: BLE001
                    logger.exception("search_test_cases_global: failed to resolve accessible teams user_id=%s", user_id)
                    allowed_team_ids_sql = []

            if not allowed_team_ids_sql:
                return 200, {"status": "success", "results": [], "total": 0}

            pattern = f"%{query}%"

            async def _search(session: AsyncSession) -> list[Any]:
                stmt = (
                    select(
                        TestCaseLocal.test_case_number,
                        TestCaseLocal.title,
                        TestCaseLocal.priority,
                        TestCaseLocal.team_id,
                        TestCaseLocal.test_case_set_id,
                        TestCaseSet.name.label("set_name"),
                        Team.name.label("team_name"),
                    )
                    .join(TestCaseSet, TestCaseLocal.test_case_set_id == TestCaseSet.id, isouter=True)
                    .join(Team, TestCaseLocal.team_id == Team.id, isouter=True)
                    .where(
                        or_(
                            TestCaseLocal.title.ilike(pattern),
                            TestCaseLocal.test_case_number.ilike(pattern),
                        ),
                        TestCaseLocal.team_id.in_(allowed_team_ids_sql),
                    )
                    .limit(limit)
                )
                return list((await session.execute(stmt)).all())

            rows = await self.main_boundary.run_read(_search)

            results = [
                {
                    "test_case_number": r.test_case_number,
                    "title": r.title,
                    "priority": r.priority.value if hasattr(r.priority, "value") else r.priority,
                    "team_id": r.team_id,
                    "team_name": r.team_name or f"Team-{r.team_id}",
                    "set_id": r.test_case_set_id,
                    "set_name": r.set_name or "",
                }
                for r in rows
            ]
            return 200, {"status": "success", "results": results, "total": len(results)}
        if tool.name == "analyze_knowledge_impact":
            from app.services.knowledge import get_retrieval_service
            from app.audit.database import KnowledgeQuerySource

            entity_type = str(arguments.get("entity_type", ""))
            entity_id = str(arguments.get("entity_id", ""))
            # Global scope: still resolve accessible teams for defense-in-depth logging;
            # impact analysis itself remains read-only graph (team filter is best-effort).
            res = await get_retrieval_service().analyze_impact(
                entity_type=entity_type,
                entity_id=entity_id,
                team_id=team_id,
                context={
                    "source": KnowledgeQuerySource.ASSISTANT.value,
                    "user_id": user_id,
                    "username": username,
                    "conversation_id": conversation_id,
                    "turn_key": turn_key,
                    "llm_tool_call_id": llm_tool_call_id,
                },
            )
            return 200, res
        return 500, {"detail": f"local tool handler missing for {tool.name}"}


    async def run_read_tool(
        self,
        tool: AssistantTool,
        arguments: dict[str, Any],
        *,
        conversation,
        turn,
        user_id: int,
        role: UserRole,
        llm_tool_call_id: str,
        jwt: str,
        conversation_service,
    ) -> ReadToolResult:
        validation = validate_arguments(arguments, combined_schema(tool))
        if not validation.ok:
            return ReadToolResult(
                ok=False,
                result_payload={},
                http_status=None,
                rejection=RejectionResult("schema_invalid", "The tool arguments could not be validated.", fixable=True),
            )

        path_params, query_params, body_params = _split_arguments(tool, arguments)

        if not await self.check_permission(tool, user_id=user_id, team_id=conversation.team_id, role=role):
            return ReadToolResult(ok=False, result_payload={}, http_status=None, rejection=RejectionResult("permission_denied", "insufficient permission", fixable=False))

        resolved_team = await self.resolve_team(tool, conversation_team_id=conversation.team_id, path_params=path_params, body_params=body_params)
        if tool.team_check != "none" and resolved_team != conversation.team_id:
            return ReadToolResult(ok=False, result_payload={}, http_status=None, rejection=RejectionResult("team_mismatch", "resource does not belong to this conversation's team", fixable=False))

        journal_args = {**query_params, **body_params} if tool.execution_mode == "local" else body_params
        journal_id = await conversation_service.start_read_tool_journal(
            conversation=conversation, turn=turn, user_id=user_id, team_id=conversation.team_id,
            llm_tool_call_id=llm_tool_call_id, tool_name=tool.name, risk_level=tool.risk_level,
            arguments_json=json.dumps(journal_args, ensure_ascii=False),
        )
        try:
            if tool.execution_mode == "local":
                # 觀測性記錄需要 username；conversation 物件沒有 username 欄位，
                # 從 main DB 依 user_id 解析（_resolve_username 失敗時不影響查詢）。
                resolved_username = await self._resolve_username(user_id)
                status_code, payload = await self._run_local_read_tool(
                    tool,
                    {**query_params, **body_params, **path_params},
                    team_id=conversation.team_id,
                    user_id=user_id,
                    llm_tool_call_id=llm_tool_call_id,
                    conversation_id=str(getattr(conversation, "conversation_key", "") or "") or None,
                    turn_key=str(getattr(turn, "id", "") or getattr(turn, "turn_key", "") or "") or None,
                    username=resolved_username,
                )

            else:
                status_code, payload = await self._loopback(
                    tool, team_id=resolved_team, path_params=path_params, query_params=query_params,
                    body_params=body_params, jwt=jwt, conversation_key=conversation.conversation_key,
                )
        except Exception:  # noqa: BLE001
            logger.exception(
                "assistant read tool transport failure tool=%s conversation_key=%s",
                tool.name,
                conversation.conversation_key,
            )
            safe_error = "The service could not be reached."
            await conversation_service.finish_read_tool_journal(
                journal_id=journal_id, status="unknown", http_status=None, error_message=safe_error
            )
            return ReadToolResult(
                ok=False,
                result_payload=project_error(0, safe_error),
                http_status=None,
                rejection=RejectionResult("transport_error", safe_error, fixable=False),
            )

        if status_code == 401:
            await conversation_service.finish_read_tool_journal(journal_id=journal_id, status="failed", http_status=401, error_message="session expired")
            return ReadToolResult(ok=False, result_payload=project_error(401, "session expired"), http_status=401, rejection=RejectionResult("session_expired", "JWT expired", fixable=False))

        if status_code >= 400:
            detail = payload.get("detail") if isinstance(payload, dict) else str(payload)
            safe_result = project_error(status_code, str(detail))
            await conversation_service.finish_read_tool_journal(
                journal_id=journal_id,
                status="failed",
                http_status=status_code,
                error_message=safe_result["detail"],
            )
            # 與 loopback 一致：4xx 進入 tool result 讓 LLM 自行修正，不 terminate turn。
            return ReadToolResult(ok=False, result_payload=safe_result, http_status=status_code)

        result = project_and_redact(
            payload,
            tool.projection,
            self.config.tool_result_max_chars,
            request_skip=_request_skip_from_query(query_params),
        )
        await conversation_service.finish_read_tool_journal(journal_id=journal_id, status="succeeded", http_status=status_code, error_message=None)
        return ReadToolResult(ok=True, result_payload=result, http_status=status_code)

    # ------------------------------------------------------------------ #
    # Write tool：僅能建立 pending（design D3 Pending Tx 的準備階段）
    # ------------------------------------------------------------------ #

    async def prepare_write_tool(
        self,
        tool: AssistantTool,
        arguments: dict[str, Any],
        *,
        conversation,
        user_id: int,
        role: UserRole,
        execution_key: str,
        resolved_file_ref: Optional[dict[str, int]] = None,
        resolved_file_refs: Optional[dict[int, dict[str, int]]] = None,
    ) -> PendingCreationRequest | RejectionResult:
        """`execution_key` MUST 由呼叫端（agent_service）預先生成並同時傳給
        `conversation_service.create_pending_action_and_complete_turn`——sensitive payload
        的加密 AAD 綁定此 key，兩處必須一致，否則 confirm 階段解密會失敗。

        `resolved_file_ref`（`multipart_file_param` 工具專用）：呼叫端須先將 LLM 提供的
        `file_ref` 解析並驗證為屬於本對話、本 turn 的既有暫存附件（`{"turn_id":.., "attachment_index":..}`），
        此處不重複驗證，只原樣存進 execution_payload 供 confirm 階段重新讀取檔案內容（design：
        原始 bytes 不落 DB，只存參照，confirm 時才從磁碟重讀）。"""
        validation = validate_arguments(arguments, combined_schema(tool))
        if not validation.ok:
            return RejectionResult("schema_invalid", "; ".join(validation.errors), fixable=True)

        path_params, query_params, body_params = _split_arguments(tool, arguments)

        if not await self.check_permission(tool, user_id=user_id, team_id=conversation.team_id, role=role):
            return RejectionResult("permission_denied", "insufficient permission", fixable=False)

        if conversation.scope_type != "team" or conversation.team_id is None:
            return RejectionResult("scope_invalid", "mutation tools require a team-bound conversation", fixable=False)

        if tool.execution_mode == "batch_actions":
            rejection = await self.validate_batch_actions(
                body_params.get("actions") or [], conversation_team_id=conversation.team_id, user_id=user_id, role=role
            )
            if rejection is not None:
                return rejection
            for index, action in enumerate(body_params.get("actions") or []):
                child = self.registry.get(action["tool_name"])
                if child.multipart_file_param and (resolved_file_refs or {}).get(index) is None:
                    return RejectionResult("file_ref_invalid", f"action {index + 1}: invalid file_ref", fixable=True)

        resolved_team = await self.resolve_team(tool, conversation_team_id=conversation.team_id, path_params=path_params, body_params=body_params)
        if resolved_team != conversation.team_id:
            return RejectionResult("team_mismatch", "resource does not belong to this conversation's team", fixable=False)

        if self.check_credential_write_rejected(tool, body_params):
            return RejectionResult("credential_write_rejected", "writing credential values via chat is not supported; use the UI", fixable=False)
        if await self.check_update_overwrites_existing_credential(tool, path_params, body_params):
            return RejectionResult("credential_write_rejected", "this case has existing credential test_data; edit it in the UI", fixable=False)

        summary_result = await self.build_confirmation_summary(tool, path_params=path_params, body_params=body_params)
        if summary_result is None:
            return RejectionResult("confirmation_summary_unresolvable", "cannot resolve a stable target for this high-impact action", fixable=False)
        summary, stable_identity = summary_result
        fingerprint = self.compute_fingerprint(summary, stable_identity)

        execution_payload = {"path_params": path_params, "query_params": query_params, "body_params": body_params}
        if resolved_file_ref is not None:
            execution_payload["file_ref"] = resolved_file_ref
        if resolved_file_refs:
            execution_payload["file_refs"] = {str(index): value for index, value in resolved_file_refs.items()}
        if tool.execution_mode == "batch_actions":
            redacted_args = {"actions": [
                {"tool_name": action["tool_name"], "arguments": project_and_redact(
                    action["arguments"], tuple(action["arguments"].keys()), self.config.tool_result_max_chars
                )}
                for action in body_params.get("actions") or []
            ]}
        else:
            redacted_args = project_and_redact(body_params, tuple(body_params.keys()), self.config.tool_result_max_chars)

        needs_encryption = bool(tool.sensitive_input_paths) or (
            tool.execution_mode == "batch_actions" and any(
                bool(self.registry.get(action["tool_name"]).sensitive_input_paths)
                for action in body_params.get("actions") or []
            )
        )
        if needs_encryption:
            if not self.config.payload_encryption_key:
                return RejectionResult("sensitive_payload_encryption_unavailable", "sensitive payload encryption key not configured", fixable=False)
            try:
                # Store the envelope string directly as execution_payload_json (design D8).
                # Do NOT wrap as {"_raw": envelope} — decrypt_execution_payload expects the envelope itself.
                payload_json_str = encrypt_sensitive_payload(
                    raw_key=self.config.payload_encryption_key,
                    execution_key=execution_key,
                    tool_name=tool.name,
                    payload=execution_payload,
                )
            except AssistantPayloadEncryptionError:
                return RejectionResult(
                    "sensitive_payload_encryption_unavailable",
                    "Sensitive payload encryption is unavailable.",
                    fixable=False,
                )
        else:
            payload_json_str = json.dumps(execution_payload, ensure_ascii=False)

        return PendingCreationRequest(
            tool=tool,
            arguments_redacted=redacted_args,
            execution_payload_json=payload_json_str,
            execution_payload_encrypted=needs_encryption,
            confirmation_summary=summary,
            confirmation_fingerprint=fingerprint,
        )

    # ------------------------------------------------------------------ #
    # Confirm 執行（Confirm Tx A 之後、Tx B 之前）
    # ------------------------------------------------------------------ #

    def decrypt_execution_payload(
        self, tool: AssistantTool, *, execution_key: str, execution_payload_json: str, encrypted: bool
    ) -> dict[str, Any]:
        """confirm 流程用：解密到呼叫端記憶體（design D8）；呼叫端（agent_service）用完即棄。"""
        if not encrypted:
            return json.loads(execution_payload_json)
        from app.services.assistant.crypto import decrypt_sensitive_payload

        return decrypt_sensitive_payload(
            raw_key=self.config.payload_encryption_key,
            execution_key=execution_key,
            tool_name=tool.name,
            envelope_json=execution_payload_json,
        )

    async def execute_confirmed_write(
        self,
        tool: AssistantTool,
        *,
        team_id: int,
        execution_payload: dict[str, Any],
        jwt: str,
        conversation_key: str,
        multipart_file: Optional[tuple[str, bytes, str]] = None,
        multipart_files: Optional[dict[int, tuple[str, bytes, str]]] = None,
    ) -> ConfirmExecutionResult:
        """`multipart_file`（`(original_name, content, content_type)`）：`multipart_file_param`
        工具專用，呼叫端（agent_service）需先依 execution_payload 的 `file_ref` 從磁碟重讀內容——
        本函式不接觸資料庫，只負責把已讀出的 bytes 併入 multipart 請求。"""
        if tool.execution_mode == "batch_actions":
            return await self._execute_batch_actions(
                execution_payload.get("body_params", {}).get("actions") or [],
                team_id=team_id, jwt=jwt, conversation_key=conversation_key,
                multipart_files=multipart_files or {},
            )
        path_params = execution_payload.get("path_params", {})
        query_params = execution_payload.get("query_params", {})
        body_params = execution_payload.get("body_params", {})
        files = {tool.multipart_file_param: multipart_file} if (tool.multipart_file_param and multipart_file is not None) else None
        try:
            status_code, payload = await self._loopback(
                tool, team_id=team_id, path_params=path_params, query_params=query_params,
                body_params=body_params, jwt=jwt, conversation_key=conversation_key, files=files,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "assistant loopback transport error tool=%s error_type=%s",
                tool.name,
                type(exc).__name__,
                exc_info=True,
            )
            return ConfirmExecutionResult(
                outcome_status=ToolExecutionOutcome.UNKNOWN,
                result_payload=project_error(0, "transport error"),
                http_status=None,
            )

        if status_code // 100 == 2:
            result = project_and_redact(
                payload,
                tool.projection,
                self.config.tool_result_max_chars,
                request_skip=_request_skip_from_query(query_params),
            )
            semantic_outcome = _classify_batch_write_payload(tool.name, payload)
            if semantic_outcome != ToolExecutionOutcome.SUCCEEDED:
                if result is None or result == {}:
                    result = {"status": semantic_outcome, "http_status": status_code}
                return ConfirmExecutionResult(
                    outcome_status=semantic_outcome, result_payload=result, http_status=status_code
                )
            if result is None or result == {}:
                # 204 No Content／projection 全空（如 has_no_response_body 工具）時，真實結果
                # 不含任何內容；若不補一個明確的成功標記，continuation turn 的 LLM 只會在 history
                # 看到 tool result content 為 "null"，無法判斷操作是否已完成，可能誤以為尚未執行而
                # 重新描述「我準備...」而非回報完成（design：不得讓「結果不明」與「明確成功」混淆）。
                result = {"status": "success", "http_status": status_code}
            return ConfirmExecutionResult(outcome_status=ToolExecutionOutcome.SUCCEEDED, result_payload=result, http_status=status_code)

        if status_code in tool.definitive_pre_mutation_errors:
            detail = payload.get("detail") if isinstance(payload, dict) else str(payload)
            return ConfirmExecutionResult(outcome_status=ToolExecutionOutcome.FAILED, result_payload=project_error(status_code, str(detail)), http_status=status_code)

        # v1：definitive_pre_mutation_errors 恆為空，故除 2xx 外一律 unknown（design D9）。
        detail = payload.get("detail") if isinstance(payload, dict) else str(payload)
        return ConfirmExecutionResult(outcome_status=ToolExecutionOutcome.UNKNOWN, result_payload=project_error(status_code, str(detail)), http_status=status_code)

    async def _execute_batch_actions(
        self, actions: list[dict[str, Any]], *, team_id: int, jwt: str, conversation_key: str,
        multipart_files: dict[int, tuple[str, bytes, str]],
    ) -> ConfirmExecutionResult:
        results: list[dict[str, Any]] = []
        total = len(actions)
        current_item: Optional[dict[str, Any]] = None
        try:
            async with asyncio.timeout(self.config.tool_timeout_seconds):
                for index, action in enumerate(actions):
                    child_tool = self.registry.get(action["tool_name"])
                    if child_tool is None or child_tool.execution_mode != "loopback" or not child_tool.is_write():
                        raise RuntimeError("batch action mapping is unavailable")
                    arguments = action["arguments"]
                    current_item = {"index": index + 1, "tool_name": child_tool.name}
                    path_params, query_params, body_params = _split_arguments(child_tool, arguments)
                    file_tuple = multipart_files.get(index)
                    files = {child_tool.multipart_file_param: file_tuple} if child_tool.multipart_file_param and file_tuple else None
                    status_code, payload = await self._loopback(
                        child_tool, team_id=team_id, path_params=path_params, query_params=query_params,
                        body_params=body_params, jwt=jwt, conversation_key=conversation_key, files=files,
                    )
                    item = current_item
                    if status_code // 100 != 2:
                        # Surface child detail so UI/LLM can explain partial batches (e.g. illegal status hop).
                        # 4xx (except timeout-ish 408) is definitive pre/post validation — not ambiguous.
                        detail = payload.get("detail") if isinstance(payload, dict) else str(payload)
                        is_definitive_client_error = 400 <= status_code < 500 and status_code != 408
                        item["outcome"] = "failed" if is_definitive_client_error else "unknown"
                        item["http_status"] = status_code
                        if detail:
                            item["detail"] = str(detail)[:500]
                        results.append(item)
                        succeeded_count = sum(1 for r in results if r.get("outcome") == "succeeded")
                        if is_definitive_client_error and succeeded_count == 0:
                            aggregate = ToolExecutionOutcome.FAILED
                        else:
                            aggregate = ToolExecutionOutcome.UNKNOWN
                        result = {
                            "status": aggregate,
                            "total": total,
                            "attempted_count": len(results),
                            "succeeded_count": succeeded_count,
                            "remaining_count": total - len(results),
                            "results": results,
                            "detail": str(detail)[:500] if detail else None,
                        }
                        return ConfirmExecutionResult(aggregate, result, status_code)
                    projected = project_and_redact(payload, child_tool.projection, self.config.tool_result_max_chars)
                    if projected:
                        item["result"] = projected
                    semantic_outcome = _classify_batch_write_payload(child_tool.name, payload)
                    if semantic_outcome != ToolExecutionOutcome.SUCCEEDED:
                        item["outcome"] = semantic_outcome
                        results.append(item)
                        succeeded_count = sum(result_item["outcome"] == "succeeded" for result_item in results)
                        aggregate_outcome = (
                            ToolExecutionOutcome.FAILED
                            if semantic_outcome == ToolExecutionOutcome.FAILED and succeeded_count == 0
                            else ToolExecutionOutcome.UNKNOWN
                        )
                        result = {
                            "status": aggregate_outcome,
                            "total": total,
                            "attempted_count": len(results),
                            "succeeded_count": succeeded_count,
                            "remaining_count": total - len(results),
                            "results": results,
                        }
                        return ConfirmExecutionResult(aggregate_outcome, result, status_code)
                    item["outcome"] = "succeeded"
                    results.append(item)
                    current_item = None
        except BaseException:  # cancellation/timeout after dispatch is ambiguous; never retry
            if current_item is not None:
                current_item["outcome"] = "unknown"
                results.append(current_item)
            result = {"status": "unknown", "total": total, "attempted_count": len(results),
                      "succeeded_count": sum(item["outcome"] == "succeeded" for item in results),
                      "remaining_count": total - len(results), "results": results}
            return ConfirmExecutionResult(ToolExecutionOutcome.UNKNOWN, result, None)
        result = {"status": "success", "total": total, "attempted_count": total,
                  "succeeded_count": total, "remaining_count": 0, "results": results}
        return ConfirmExecutionResult(ToolExecutionOutcome.SUCCEEDED, result, 200)
