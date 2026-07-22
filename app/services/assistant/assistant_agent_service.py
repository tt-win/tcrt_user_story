"""Agent 迴圈本體與 detached runner 入口（design D4/D7/D9；spec assistant-agent-loop）。

兩個對外入口皆設計為由 `runner_supervisor.try_start()` 包起來、於 lifespan-managed
background task 執行，不隸屬任何單一 HTTP request/StreamingResponse：

- `run_agent_turn`：全新使用者訊息 turn（呼叫端已完成 TurnStart Tx）。
- `run_confirm_turn`：write 已確認 turn（呼叫端已完成 Confirm Tx A / `claim_pending_for_confirm`）；
  先執行已確認的 write，寫回結果，成功時再續跑 LLM 迴圈規劃下一步（design「多步驟寫入逐步確認」）。

兩者共用 `_run_llm_loop`：載入 history → 呼叫 LLM → 執行至多一個工具呼叫（read 連鎖執行、
遇 write 即停下建立 pending）→ 迭代直到純文字回覆、上限、取消或錯誤終止。
"""

from __future__ import annotations

import contextlib
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.auth.models import PermissionType, UserRole
from app.services.assistant import attachment_storage, ids
from app.services.assistant.assistant_llm_service import (
    AssistantLLMContextLengthError,
    AssistantLLMError,
    AssistantLLMService,
)
from app.services.assistant.conversation_service import (
    LEASE_SAFETY_MARGIN_SECONDS,
    ConversationService,
)
from app.services.assistant.errors import PendingActionNotFoundError
from app.services.assistant.history_builder import build_llm_messages, drop_oldest_group
from app.services.assistant.tool_executor import (
    RejectionResult,
    ToolExecutionOutcome,
    ToolExecutor,
)
from app.services.assistant.tool_registry import READ, ToolRegistry

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "assistant" / "system.md"

# max_iterations 達上限時的收尾訊息；非 LLM 生成，系統控制路徑固定文案（見 design「上限即終止」）。
_MAX_ITERATIONS_NOTICE = (
    "已達本次對話可執行的操作次數上限，請查看目前已完成的結果；如需繼續，請再傳一則新訊息。\n"
    "Reached the max number of operations for this turn. Please review the results so far, "
    "or send a new message to continue."
)


@lru_cache(maxsize=1)
def _load_system_prompt() -> str:
    return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def _allowed_permissions_for_role(role: UserRole) -> set[PermissionType]:
    """角色→權限等級映射，鏡射 `permission_service._role_to_permission`（design D2 工具目錄預過濾）。"""
    if role in (UserRole.SUPER_ADMIN, UserRole.ADMIN):
        return {PermissionType.READ, PermissionType.WRITE, PermissionType.ADMIN}
    if role == UserRole.USER:
        return {PermissionType.READ, PermissionType.WRITE}
    return {PermissionType.READ}


async def _renew_or_stop(conversation_service: ConversationService, *, conversation_id: int, turn_key: str, ttl_seconds: int) -> bool:
    return await conversation_service.renew_lease(conversation_id=conversation_id, turn_key=turn_key, ttl_seconds=ttl_seconds)


async def _resolve_file_ref(
    conversation_service: ConversationService, *, conversation_id: int, turn, user_id: int, raw_file_ref
) -> Optional[dict[str, int]]:
    """`multipart_file_param` 工具的 `file_ref` fail-fast 驗證（spec assistant-conversations
    「聊天附檔暫存」：僅本對話、本 turn 的既有暫存附件可被引用）。回傳 `None` 代表無效，呼叫端需以
    fixable 拒絕續跑迴圈；有效時回傳 `{"turn_id":.., "attachment_index":..}` 供 execution_payload
    保存——confirm 階段重讀檔案內容，原始 bytes 不落 DB。"""
    if raw_file_ref is None:
        return None
    try:
        attachment_index = int(raw_file_ref)
    except (TypeError, ValueError):
        return None
    try:
        await conversation_service.get_uploaded_file_owned(
            user_id=user_id, conversation_id=conversation_id, turn_id=turn.id, attachment_index=attachment_index
        )
    except PendingActionNotFoundError:
        return None
    return {"turn_id": turn.id, "attachment_index": attachment_index}


async def _finalize_confirm_as_failed(
    conversation_service: ConversationService, *, conversation, turn, pending_action, user_id: int, http_status: int, detail: str,
) -> None:
    """confirm 側 pre-loopback 驗證失敗（例如 `file_ref` 已不可用）：直接標 failed 收尾，不呼叫 loopback。

    重用 `finalize_confirm_outcome` 寫入 paired synthetic result／終態 pending／journal／
    單一 `tool_finished` 事件，語意等同「已知失敗」（非 unknown——我們確定從未送出過 loopback 請求）。"""
    finalized = await conversation_service.finalize_confirm_outcome(
        conversation_id=conversation.id, turn=turn, action_id=pending_action.id, user_id=user_id,
        outcome_status="failed", tool_result_payload={"status": http_status, "detail": detail}, http_status=http_status,
    )
    if not finalized:
        return
    await conversation_service.complete_continuation_turn(
        conversation_id=conversation.id, turn_id=turn.id, turn_key=turn.turn_key, user_id=user_id, status="failed",
    )
    await conversation_service.append_event(turn_id=turn.id, event_type="done", payload=None)


async def _finish_error(conversation_service: ConversationService, *, conversation, turn, user_id: int, error_message: str) -> None:
    if not await conversation_service.renew_lease(
        conversation_id=conversation.id,
        turn_key=turn.turn_key,
        ttl_seconds=LEASE_SAFETY_MARGIN_SECONDS,
    ):
        return
    await conversation_service.append_event(turn_id=turn.id, event_type="error", payload={"message": error_message[:500]})
    await conversation_service.complete_turn_release_lease(
        conversation_id=conversation.id, turn_id=turn.id, turn_key=turn.turn_key, user_id=user_id,
        status="failed", error_message=error_message[:500],
    )
    await conversation_service.append_event(turn_id=turn.id, event_type="done", payload=None)


async def _finish_cancelled(conversation_service: ConversationService, *, conversation, turn, user_id: int) -> None:
    if not await conversation_service.renew_lease(
        conversation_id=conversation.id,
        turn_key=turn.turn_key,
        ttl_seconds=LEASE_SAFETY_MARGIN_SECONDS,
    ):
        return
    await conversation_service.complete_turn_release_lease(
        conversation_id=conversation.id, turn_id=turn.id, turn_key=turn.turn_key, user_id=user_id, status="cancelled",
    )
    await conversation_service.append_event(turn_id=turn.id, event_type="cancelled", payload=None)


async def _finish_without_terminal_text(
    conversation_service: ConversationService, *, conversation, turn, user_id: int, status: str = "completed"
) -> None:
    """Confirm 已有權威 tool_finished；沒有新 tool call 時只結束 continuation，不追加文字／錯誤泡泡。"""
    await conversation_service.complete_turn_release_lease(
        conversation_id=conversation.id,
        turn_id=turn.id,
        turn_key=turn.turn_key,
        user_id=user_id,
        status=status,
    )
    await conversation_service.append_event(turn_id=turn.id, event_type="done", payload=None)


async def _run_llm_loop(
    *,
    conversation,
    turn,
    user_id: int,
    role: UserRole,
    jwt: str,
    conversation_service: ConversationService,
    executor: ToolExecutor,
    llm_service: AssistantLLMService,
    registry: ToolRegistry,
    config,
    suppress_terminal_text: bool = False,
) -> None:
    """從 turn 目前歷史開始跑 LLM 迴圈，直到純文字回覆／pending 建立／取消／錯誤／上限。

    confirm continuation 使用 ``suppress_terminal_text``：權威 tool_finished 已呈現結果；若模型沒有
    提出真正的新工具呼叫，其 terminal prose 不再持久化／送 UI，避免完成後又說「準備執行」。
    """
    conversation_id = conversation.id
    turn_key = turn.turn_key

    if conversation.scope_type != "team" or conversation.team_id is None:
        tools = registry.discovery_only()
    else:
        tools = registry.filter_by_permission(_allowed_permissions_for_role(role))
    tools_by_name = {t.name: t for t in tools}
    llm_tools_schema = [t.to_llm_schema() for t in tools]
    system_prompt = _load_system_prompt()

    if await conversation_service.is_cancel_requested(turn_id=turn.id):
        await _finish_cancelled(conversation_service, conversation=conversation, turn=turn, user_id=user_id)
        return
    if not await _renew_or_stop(
        conversation_service,
        conversation_id=conversation_id,
        turn_key=turn_key,
        ttl_seconds=config.llm_timeout_seconds + LEASE_SAFETY_MARGIN_SECONDS,
    ):
        return
    await conversation_service.append_event(turn_id=turn.id, event_type="message_start", payload=None)

    iteration = 0
    while True:
        if await conversation_service.is_cancel_requested(turn_id=turn.id):
            await _finish_cancelled(conversation_service, conversation=conversation, turn=turn, user_id=user_id)
            return

        if iteration >= config.max_iterations:
            if suppress_terminal_text:
                await _finish_without_terminal_text(
                    conversation_service, conversation=conversation, turn=turn, user_id=user_id
                )
                return
            await conversation_service.append_message(turn_id=turn.id, role="assistant", content=_MAX_ITERATIONS_NOTICE)
            await conversation_service.append_event(turn_id=turn.id, event_type="text_delta", payload={"content": _MAX_ITERATIONS_NOTICE})
            await conversation_service.complete_turn_release_lease(
                conversation_id=conversation_id, turn_id=turn.id, turn_key=turn_key, user_id=user_id, status="completed",
            )
            await conversation_service.append_event(turn_id=turn.id, event_type="done", payload=None)
            return
        iteration += 1

        if not await _renew_or_stop(
            conversation_service, conversation_id=conversation_id, turn_key=turn_key,
            ttl_seconds=config.llm_timeout_seconds + LEASE_SAFETY_MARGIN_SECONDS,
        ):
            logger.info("assistant runner lost lease turn_key=%s before LLM call, stopping", turn_key)
            return

        rows = await conversation_service.load_conversation_messages(conversation_id=conversation_id)
        messages = build_llm_messages(rows, max_chars=config.history_max_chars)

        try:
            result = await llm_service.call(system_prompt=system_prompt, messages=messages, tools=llm_tools_schema)
        except AssistantLLMContextLengthError:
            trimmed = drop_oldest_group(messages)
            try:
                result = await llm_service.call(system_prompt=system_prompt, messages=trimmed, tools=llm_tools_schema)
            except AssistantLLMError as exc2:
                logger.warning(
                    "assistant LLM retry failed turn_key=%s error_type=%s",
                    turn_key,
                    type(exc2).__name__,
                )
                if suppress_terminal_text:
                    await _finish_without_terminal_text(
                        conversation_service, conversation=conversation, turn=turn, user_id=user_id
                    )
                else:
                    await _finish_error(
                        conversation_service, conversation=conversation, turn=turn, user_id=user_id,
                        error_message="The assistant could not process this conversation.",
                    )
                return
        except AssistantLLMError as exc:
            logger.warning(
                "assistant LLM call failed turn_key=%s error_type=%s",
                turn_key,
                type(exc).__name__,
            )
            if suppress_terminal_text:
                await _finish_without_terminal_text(
                    conversation_service, conversation=conversation, turn=turn, user_id=user_id
                )
            else:
                await _finish_error(
                    conversation_service,
                    conversation=conversation,
                    turn=turn,
                    user_id=user_id,
                    error_message="The assistant could not generate a response.",
                )
            return

        if not await _renew_or_stop(
            conversation_service,
            conversation_id=conversation_id,
            turn_key=turn_key,
            ttl_seconds=config.llm_timeout_seconds + LEASE_SAFETY_MARGIN_SECONDS,
        ):
            return

        if await conversation_service.is_cancel_requested(turn_id=turn.id):
            await _finish_cancelled(conversation_service, conversation=conversation, turn=turn, user_id=user_id)
            return

        if not result.tool_calls:
            if suppress_terminal_text:
                await _finish_without_terminal_text(
                    conversation_service, conversation=conversation, turn=turn, user_id=user_id
                )
                return
            content = (result.content or "").strip()
            if not content:
                await _finish_error(
                    conversation_service,
                    conversation=conversation,
                    turn=turn,
                    user_id=user_id,
                    error_message="The assistant returned an empty response.",
                )
                return
            await conversation_service.append_message(turn_id=turn.id, role="assistant", content=content)
            await conversation_service.append_event(turn_id=turn.id, event_type="text_delta", payload={"content": content})
            await conversation_service.complete_turn_release_lease(
                conversation_id=conversation_id, turn_id=turn.id, turn_key=turn_key, user_id=user_id, status="completed",
            )
            await conversation_service.append_event(turn_id=turn.id, event_type="done", payload=None)
            return

        # design D4「LLM history 正規化」：一則 response 只處理第一個 tool call，其餘一律丟棄。
        call = result.tool_calls[0]
        tool = tools_by_name.get(call.name)

        if not await _renew_or_stop(
            conversation_service, conversation_id=conversation_id, turn_key=turn_key,
            ttl_seconds=config.tool_timeout_seconds + LEASE_SAFETY_MARGIN_SECONDS,
        ):
            logger.info("assistant runner lost lease turn_key=%s before tool call, stopping", turn_key)
            return

        if tool is None:
            llm_tool_call_id = ids.generate_llm_tool_call_id()
            synthetic = {"status": "error", "code": "unknown_tool", "message": f"tool '{call.name}' is not available"}
            await conversation_service.reject_write_before_pending(
                conversation_id=conversation_id, turn_id=turn.id, turn_key=turn_key, user_id=user_id,
                llm_tool_call_id=llm_tool_call_id, tool_name=call.name, arguments_for_history=call.arguments,
                synthetic_result=synthetic, terminate_turn=False,
            )
            await conversation_service.append_event(
                turn_id=turn.id, event_type="tool_finished",
                payload={"tool_name": call.name, "ok": False, "code": "unknown_tool"},
            )
            continue

        await conversation_service.append_event(turn_id=turn.id, event_type="tool_started", payload={"tool_name": tool.name})

        if tool.risk_level == READ:
            llm_tool_call_id = ids.generate_llm_tool_call_id()
            read_result = await executor.run_read_tool(
                tool, call.arguments, conversation=conversation, turn=turn, user_id=user_id, role=role,
                llm_tool_call_id=llm_tool_call_id, jwt=jwt, conversation_service=conversation_service,
            )
            if not await _renew_or_stop(
                conversation_service,
                conversation_id=conversation_id,
                turn_key=turn_key,
                ttl_seconds=config.tool_timeout_seconds + LEASE_SAFETY_MARGIN_SECONDS,
            ):
                return
            if read_result.rejection is not None:
                rejection = read_result.rejection
                synthetic = {"status": "error", "code": rejection.code, "message": rejection.message}
                await conversation_service.reject_write_before_pending(
                    conversation_id=conversation_id, turn_id=turn.id, turn_key=turn_key, user_id=user_id,
                    llm_tool_call_id=llm_tool_call_id, tool_name=tool.name, arguments_for_history=call.arguments,
                    synthetic_result=synthetic, terminate_turn=not rejection.fixable,
                )
                if not rejection.fixable:
                    return
                await conversation_service.append_event(
                    turn_id=turn.id, event_type="tool_finished",
                    payload={"tool_name": tool.name, "ok": False, "code": rejection.code},
                )
                continue

            await conversation_service.append_tool_call_and_result(
                turn_id=turn.id, llm_tool_call_id=llm_tool_call_id, tool_name=tool.name,
                arguments_for_history=call.arguments, tool_result_payload=read_result.result_payload,
            )
            await conversation_service.append_event(
                turn_id=turn.id, event_type="tool_finished",
                payload={"tool_name": tool.name, "ok": read_result.ok, "http_status": read_result.http_status},
            )
            continue

        # write 工具：唯一入口是 prepare_write_tool，成功時只建立 pending，不 inline 執行。
        resolved_file_ref = None
        resolved_file_refs = None
        if tool.multipart_file_param:
            resolved_file_ref = await _resolve_file_ref(
                conversation_service, conversation_id=conversation_id, turn=turn, user_id=user_id, raw_file_ref=call.arguments.get("file_ref"),
            )
            if not await _renew_or_stop(
                conversation_service,
                conversation_id=conversation_id,
                turn_key=turn_key,
                ttl_seconds=config.tool_timeout_seconds + LEASE_SAFETY_MARGIN_SECONDS,
            ):
                return
            if resolved_file_ref is None:
                llm_tool_call_id = ids.generate_llm_tool_call_id()
                synthetic = {"status": "error", "code": "file_ref_invalid", "message": "file_ref does not reference an uploaded attachment in this turn"}
                await conversation_service.reject_write_before_pending(
                    conversation_id=conversation_id, turn_id=turn.id, turn_key=turn_key, user_id=user_id,
                    llm_tool_call_id=llm_tool_call_id, tool_name=tool.name, arguments_for_history=call.arguments,
                    synthetic_result=synthetic, terminate_turn=False,
                )
                await conversation_service.append_event(
                    turn_id=turn.id, event_type="tool_finished",
                    payload={"tool_name": tool.name, "ok": False, "code": "file_ref_invalid"},
                )
                continue
        elif tool.execution_mode == "batch_actions":
            resolved_file_refs = {}
            invalid_batch_file = False
            for index, action in enumerate(call.arguments.get("actions") or []):
                if not isinstance(action, dict) or not isinstance(action.get("arguments"), dict):
                    continue  # prepare_write_tool 會以 schema_invalid 安全拒絕
                child = registry.get(action.get("tool_name"))
                if child is None or not child.multipart_file_param:
                    continue
                resolved = await _resolve_file_ref(
                    conversation_service, conversation_id=conversation_id, turn=turn, user_id=user_id,
                    raw_file_ref=action["arguments"].get("file_ref"),
                )
                if resolved is None:
                    invalid_batch_file = True
                    break
                resolved_file_refs[index] = resolved
            if invalid_batch_file:
                llm_tool_call_id = ids.generate_llm_tool_call_id()
                synthetic = {"status": "error", "code": "file_ref_invalid", "message": "a batch file_ref is invalid"}
                await conversation_service.reject_write_before_pending(
                    conversation_id=conversation_id, turn_id=turn.id, turn_key=turn_key, user_id=user_id,
                    llm_tool_call_id=llm_tool_call_id, tool_name=tool.name, arguments_for_history=call.arguments,
                    synthetic_result=synthetic, terminate_turn=False,
                )
                continue

        execution_key = ids.generate_execution_key()
        prepared = await executor.prepare_write_tool(
            tool, call.arguments, conversation=conversation, user_id=user_id, role=role, execution_key=execution_key,
            resolved_file_ref=resolved_file_ref, resolved_file_refs=resolved_file_refs,
        )
        if not await _renew_or_stop(
            conversation_service,
            conversation_id=conversation_id,
            turn_key=turn_key,
            ttl_seconds=config.tool_timeout_seconds + LEASE_SAFETY_MARGIN_SECONDS,
        ):
            return
        if isinstance(prepared, RejectionResult):
            llm_tool_call_id = ids.generate_llm_tool_call_id()
            synthetic = {"status": "error", "code": prepared.code, "message": prepared.message}
            await conversation_service.reject_write_before_pending(
                conversation_id=conversation_id, turn_id=turn.id, turn_key=turn_key, user_id=user_id,
                llm_tool_call_id=llm_tool_call_id, tool_name=tool.name, arguments_for_history=call.arguments,
                synthetic_result=synthetic, terminate_turn=not prepared.fixable,
            )
            if not prepared.fixable:
                return
            await conversation_service.append_event(
                turn_id=turn.id, event_type="tool_finished",
                payload={"tool_name": tool.name, "ok": False, "code": prepared.code},
            )
            continue

        # create_pending_action_and_complete_turn 已原子寫入 confirmation_required + done 事件，
        # 並釋放 admission/lease、標終態；此 turn 到此結束，繼續步驟交由使用者確認後的 continuation turn。
        # execution_payload_json 已由 prepare_write_tool 序列化（敏感時為 envelope 字串本體，勿再包一層）。
        await conversation_service.create_pending_action_and_complete_turn(
            conversation_id=conversation_id, turn_id=turn.id, turn_key=turn_key, user_id=user_id,
            tool_name=tool.name,
            arguments_redacted_json=json.dumps(prepared.arguments_redacted, ensure_ascii=False),
            arguments_for_history=call.arguments,
            execution_payload_json=prepared.execution_payload_json,
            execution_payload_encrypted=prepared.execution_payload_encrypted,
            confirmation_summary=prepared.confirmation_summary,
            confirmation_fingerprint=prepared.confirmation_fingerprint,
            pending_ttl_seconds=config.pending_action_ttl_seconds,
            execution_key=execution_key,
        )
        return


async def run_agent_turn(
    *,
    conversation,
    turn,
    user_id: int,
    role: UserRole,
    jwt: str,
    conversation_service: ConversationService,
    executor: ToolExecutor,
    llm_service: AssistantLLMService,
    registry: ToolRegistry,
    config,
) -> None:
    """detached runner 入口：全新使用者訊息 turn（呼叫端已完成 TurnStart Tx，此函式不再重複建立 turn）。"""
    try:
        await _run_llm_loop(
            conversation=conversation, turn=turn, user_id=user_id, role=role, jwt=jwt,
            conversation_service=conversation_service, executor=executor, llm_service=llm_service,
            registry=registry, config=config,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "assistant run_agent_turn crashed turn_key=%s error_type=%s",
            turn.turn_key,
            type(exc).__name__,
        )
        with contextlib.suppress(Exception):
            await _finish_error(
                conversation_service,
                conversation=conversation,
                turn=turn,
                user_id=user_id,
                error_message="The assistant could not finish the request.",
            )


async def run_confirm_turn(
    *,
    conversation,
    continuation_turn,
    pending_action,
    tool,
    user_id: int,
    role: UserRole,
    jwt: str,
    conversation_service: ConversationService,
    executor: ToolExecutor,
    llm_service: AssistantLLMService,
    registry: ToolRegistry,
    config,
    execution_payload: Optional[dict] = None,
) -> None:
    """detached runner 入口：confirm continuation turn（呼叫端已完成 Confirm Tx A / `claim_pending_for_confirm`）。

    先執行已確認的 write 並寫回結果（Confirm Tx B）；只有 outcome=succeeded 才續跑 LLM 迴圈規劃
    下一步（design「多步驟寫入逐步確認」）——failed/unknown 一律終止本 turn，不讓 LLM 在結果不可靠
    或已知失敗的狀態下自行「重新規劃」，避免未經確認的重試。

    `execution_payload`：API 在 claim 前解密到 request memory 後傳入（Tx A 已清 DB payload）。
    若未傳入則嘗試從 pending_action 殘餘欄位解密（測試／相容路徑）；失敗則標 failed 終態。
    """
    turn = continuation_turn
    write_dispatched = False
    write_finalized = False
    finalized_turn_status = "failed"
    try:
        if execution_payload is None:
            if not pending_action.execution_payload_json:
                await _finalize_confirm_as_failed(
                    conversation_service, conversation=conversation, turn=turn, pending_action=pending_action,
                    user_id=user_id, http_status=500, detail="execution payload missing after claim",
                )
                return
            try:
                execution_payload = executor.decrypt_execution_payload(
                    tool, execution_key=pending_action.execution_key,
                    execution_payload_json=pending_action.execution_payload_json,
                    encrypted=pending_action.execution_payload_encrypted,
                )
            except Exception as decrypt_exc:  # noqa: BLE001
                logger.warning(
                    "assistant execution payload decrypt failed turn_key=%s error_type=%s",
                    turn.turn_key,
                    type(decrypt_exc).__name__,
                )
                await _finalize_confirm_as_failed(
                    conversation_service, conversation=conversation, turn=turn, pending_action=pending_action,
                    user_id=user_id, http_status=500,
                    detail="The confirmed action could not be prepared.",
                )
                return

        multipart_file = None
        multipart_files = None
        if tool.multipart_file_param:
            file_ref = execution_payload.get("file_ref")
            if not file_ref:
                await _finalize_confirm_as_failed(
                    conversation_service, conversation=conversation, turn=turn, pending_action=pending_action,
                    user_id=user_id, http_status=422, detail="missing file_ref",
                )
                return
            try:
                uploaded_file = await conversation_service.get_uploaded_file_owned(
                    user_id=user_id, conversation_id=conversation.id,
                    turn_id=file_ref["turn_id"], attachment_index=file_ref["attachment_index"],
                )
                file_bytes = attachment_storage.resolve_stored_path(uploaded_file.relative_path).read_bytes()
                multipart_file = (uploaded_file.original_name, file_bytes, uploaded_file.content_type or "application/octet-stream")
            except (PendingActionNotFoundError, OSError):
                await _finalize_confirm_as_failed(
                    conversation_service, conversation=conversation, turn=turn, pending_action=pending_action,
                    user_id=user_id, http_status=404, detail="referenced attachment is no longer available",
                )
                return
        elif tool.execution_mode == "batch_actions":
            multipart_files = {}
            try:
                for raw_index, file_ref in (execution_payload.get("file_refs") or {}).items():
                    uploaded_file = await conversation_service.get_uploaded_file_owned(
                        user_id=user_id, conversation_id=conversation.id,
                        turn_id=file_ref["turn_id"], attachment_index=file_ref["attachment_index"],
                    )
                    file_bytes = attachment_storage.resolve_stored_path(uploaded_file.relative_path).read_bytes()
                    multipart_files[int(raw_index)] = (
                        uploaded_file.original_name, file_bytes,
                        uploaded_file.content_type or "application/octet-stream",
                    )
            except (PendingActionNotFoundError, OSError, KeyError, TypeError, ValueError):
                await _finalize_confirm_as_failed(
                    conversation_service, conversation=conversation, turn=turn, pending_action=pending_action,
                    user_id=user_id, http_status=404, detail="a referenced batch attachment is no longer available",
                )
                return

        if not await _renew_or_stop(
            conversation_service,
            conversation_id=conversation.id,
            turn_key=turn.turn_key,
            ttl_seconds=config.tool_timeout_seconds + LEASE_SAFETY_MARGIN_SECONDS,
        ):
            return

        try:
            redacted_arguments = json.loads(pending_action.arguments_redacted_json or "{}")
        except (TypeError, json.JSONDecodeError):
            redacted_arguments = {}
        await conversation_service.append_event(
            turn_id=turn.id,
            event_type="tool_started",
            payload={
                "action_id": pending_action.id,
                "tool_name": tool.name,
                "arguments": redacted_arguments,
                "display_mode": "status_only",
            },
        )

        write_dispatched = True
        exec_result = await executor.execute_confirmed_write(
            tool, team_id=conversation.team_id, execution_payload=execution_payload, jwt=jwt,
            conversation_key=conversation.conversation_key, multipart_file=multipart_file,
            multipart_files=multipart_files,
        )
        # finalize_confirm_outcome emits the single authoritative tool_finished event.
        finalized = await conversation_service.finalize_confirm_outcome(
            conversation_id=conversation.id, turn=turn, action_id=pending_action.id, user_id=user_id,
            outcome_status=exec_result.outcome_status, tool_result_payload=exec_result.result_payload,
            http_status=exec_result.http_status,
        )
        if not finalized:
            return
        write_finalized = True

        if exec_result.outcome_status != ToolExecutionOutcome.SUCCEEDED:
            await conversation_service.complete_continuation_turn(
                conversation_id=conversation.id, turn_id=turn.id, turn_key=turn.turn_key, user_id=user_id, status="failed",
            )
            await conversation_service.append_event(turn_id=turn.id, event_type="done", payload=None)
            return

        finalized_turn_status = "completed"
        await _run_llm_loop(
            conversation=conversation, turn=turn, user_id=user_id, role=role, jwt=jwt,
            conversation_service=conversation_service, executor=executor, llm_service=llm_service,
            registry=registry, config=config, suppress_terminal_text=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "assistant run_confirm_turn crashed turn_key=%s error_type=%s",
            turn.turn_key,
            type(exc).__name__,
        )
        # Write 已終態化後，後續 LLM 規劃異常不得反過來暗示 mutation 失敗。
        # 此時靜默結束 continuation；只有尚未終態化的 claim 才進入 failed/unknown 補償。
        if write_finalized:
            with contextlib.suppress(Exception):
                await _finish_without_terminal_text(
                    conversation_service,
                    conversation=conversation,
                    turn=turn,
                    user_id=user_id,
                    status=finalized_turn_status,
                )
            return

        # claim 之後任何例外都必須把仍 executing 的 pending 收成終態，避免卡在 executing
        # 且 payload 已於 claim 清除。若 loopback 可能已送出 → unknown；否則 failed。
        with contextlib.suppress(Exception):
            outcome = "unknown" if write_dispatched else "failed"
            await conversation_service.finalize_confirm_outcome(
                conversation_id=conversation.id, turn=turn, action_id=pending_action.id, user_id=user_id,
                outcome_status=outcome,
                tool_result_payload={
                    "status": "error",
                    "code": "internal_error",
                    "detail": "The assistant could not finish the confirmed action.",
                },
                http_status=None,
            )
            await conversation_service.append_event(
                turn_id=turn.id,
                event_type="error",
                payload={"code": "internal_error", "message": "The assistant could not finish the confirmed action."},
            )
            await conversation_service.complete_continuation_turn(
                conversation_id=conversation.id, turn_id=turn.id, turn_key=turn.turn_key, user_id=user_id, status="failed",
            )
            await conversation_service.append_event(turn_id=turn.id, event_type="done", payload=None)
