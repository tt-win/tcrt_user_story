"""全域 AI 助手 API 路由（openspec change add-global-ai-assistant，task 5）。

端點只負責：認證/擁有權過濾、per-worker slot 預留、TurnStart/Confirm 判斷順序與
DB-tail SSE 串流；實際併發控制與交易邊界都委派給 `conversation_service`，
agent 迴圈本體委派給 `assistant_agent_service`（detached runner，不隸屬本次 request）。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import mimetypes
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Security, UploadFile, status
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.exc import IntegrityError

from app.auth.dependencies import get_current_user, security
from app.config import AssistantConfig, get_settings
from app.db_access.main import MainAccessBoundary, get_main_access_boundary
from app.models.assistant import (
    ActionAckResponse,
    AvailabilityResponse,
    ConversationBatchDeleteRequest,
    ConversationBatchDeleteResponse,
    ConversationCreateRequest,
    ConversationResponse,
    MessageHistoryItem,
    MessageHistoryResponse,
    StopAckResponse,
)
from app.models.database_models import User
from app.services.assistant import assistant_agent_service as agent_svc
from app.services.assistant import attachment_storage, ids
from app.services.assistant.assistant_llm_service import get_assistant_llm_service
from app.services.assistant.conversation_service import ConversationService
from app.services.assistant.errors import AdmissionDeniedError, AssistantError, ConfirmationStaleError
from app.services.assistant.param_validation import validate_arguments
from app.services.assistant.runner_supervisor import RunnerSupervisor, get_runner_supervisor
from app.services.assistant.tool_executor import ToolExecutor, combined_schema
from app.services.assistant.tool_registry import get_tool_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assistant", tags=["assistant"])

_TERMINAL_EVENT_TYPES = {"done", "cancelled"}
_POLL_INTERVAL_SECONDS = 0.5
_KEEPALIVE_EVERY_N_TICKS = 30  # ~15s


# ---------------------------------------------------------------------- #
# Dependencies
# ---------------------------------------------------------------------- #


def _get_config() -> AssistantConfig:
    return get_settings().ai.assistant


def _get_conversation_service(
    config: AssistantConfig = Depends(_get_config),
    boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> ConversationService:
    return ConversationService(boundary, config)


def _get_executor(
    request: Request,
    config: AssistantConfig = Depends(_get_config),
    boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> ToolExecutor:
    return ToolExecutor(app=request.app, main_boundary=boundary, config=config, registry=get_tool_registry())


def _get_runner_supervisor(config: AssistantConfig = Depends(_get_config)) -> RunnerSupervisor:
    return get_runner_supervisor(config.max_active_turns_per_worker)


def _require_enabled(config: AssistantConfig) -> None:
    if not (config.enabled and get_assistant_llm_service().is_configured()):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "ASSISTANT_NOT_CONFIGURED", "message": "assistant is disabled or not configured"},
        )


# ---------------------------------------------------------------------- #
# SSE：DB-tail（design D6/D7；spec assistant-agent-loop「SSE 事件協定」）
# ---------------------------------------------------------------------- #


async def _tail_turn_events(conv_svc: ConversationService, *, turn_id: int, turn_key: str, after_seq: int):
    cursor = after_seq
    idle_ticks = 0
    while True:
        events = await conv_svc.get_events_after(turn_id=turn_id, after_seq=cursor)
        if not events:
            if await conv_svc.is_turn_terminal(turn_id=turn_id):
                return
            idle_ticks += 1
            if idle_ticks % _KEEPALIVE_EVERY_N_TICKS == 0:
                yield b": keepalive\n\n"
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            continue
        idle_ticks = 0
        for event in events:
            payload = json.loads(event.payload_json) if event.payload_json else None
            data = json.dumps({"seq": event.seq, "payload": payload}, ensure_ascii=False)
            yield f"event: {event.event_type}\nid: {turn_key}:{event.seq}\ndata: {data}\n\n".encode("utf-8")
            cursor = event.seq
            if event.event_type in _TERMINAL_EVENT_TYPES:
                return


def _stream_response(conv_svc: ConversationService, *, turn_id: int, turn_key: str, after_seq: int) -> StreamingResponse:
    return StreamingResponse(
        _tail_turn_events(conv_svc, turn_id=turn_id, turn_key=turn_key, after_seq=after_seq),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
            "X-TCRT-Turn-Key": turn_key,
        },
    )


# ---------------------------------------------------------------------- #
# Availability
# ---------------------------------------------------------------------- #


@router.get("/availability", response_model=AvailabilityResponse)
async def get_availability(
    current_user: User = Depends(get_current_user),
    config: AssistantConfig = Depends(_get_config),
) -> AvailabilityResponse:
    return AvailabilityResponse(enabled=config.enabled and get_assistant_llm_service().is_configured())


# ---------------------------------------------------------------------- #
# Conversations CRUD
# ---------------------------------------------------------------------- #


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations_endpoint(
    team_id: Optional[int] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    config: AssistantConfig = Depends(_get_config),
    conv_svc: ConversationService = Depends(_get_conversation_service),
) -> list[ConversationResponse]:
    _require_enabled(config)
    rows = await conv_svc.list_conversations(user_id=current_user.id, team_id=team_id, limit=limit)
    return [ConversationResponse.model_validate(r) for r in rows]


@router.post("/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation_endpoint(
    body: ConversationCreateRequest,
    current_user: User = Depends(get_current_user),
    config: AssistantConfig = Depends(_get_config),
    conv_svc: ConversationService = Depends(_get_conversation_service),
) -> ConversationResponse:
    _require_enabled(config)
    try:
        conv = await conv_svc.create_conversation(
            user_id=current_user.id, scope_type=body.scope_type, team_id=body.team_id, title=body.title
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return ConversationResponse.model_validate(conv)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation_endpoint(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    config: AssistantConfig = Depends(_get_config),
    conv_svc: ConversationService = Depends(_get_conversation_service),
) -> None:
    _require_enabled(config)
    await conv_svc.get_conversation_owned(user_id=current_user.id, conversation_id=conversation_id)  # 404 gate
    files = await conv_svc.list_uploaded_files_for_conversation(conversation_id=conversation_id)
    await conv_svc.delete_conversation(user_id=current_user.id, conversation_id=conversation_id)
    for f in files:
        with contextlib.suppress(OSError, ValueError):
            attachment_storage.resolve_stored_path(f.relative_path).unlink(missing_ok=True)


@router.post("/conversations/batch-delete", response_model=ConversationBatchDeleteResponse)
async def batch_delete_conversations_endpoint(
    body: ConversationBatchDeleteRequest,
    current_user: User = Depends(get_current_user),
    config: AssistantConfig = Depends(_get_config),
    conv_svc: ConversationService = Depends(_get_conversation_service),
) -> ConversationBatchDeleteResponse:
    _require_enabled(config)
    deleted_ids = await conv_svc.batch_delete_conversations(
        user_id=current_user.id,
        conversation_ids=body.conversation_ids,
    )
    for cid in deleted_ids:
        with contextlib.suppress(Exception):
            files = await conv_svc.list_uploaded_files_for_conversation(conversation_id=cid)
            for f in files:
                with contextlib.suppress(OSError, ValueError):
                    attachment_storage.resolve_stored_path(f.relative_path).unlink(missing_ok=True)
    return ConversationBatchDeleteResponse(deleted_count=len(deleted_ids), deleted_ids=deleted_ids)


@router.get("/conversations/{conversation_id}/messages", response_model=MessageHistoryResponse)
async def get_messages_endpoint(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    config: AssistantConfig = Depends(_get_config),
    conv_svc: ConversationService = Depends(_get_conversation_service),
) -> MessageHistoryResponse:
    _require_enabled(config)
    await conv_svc.get_conversation_owned(user_id=current_user.id, conversation_id=conversation_id)  # 404 gate
    active_turn = await conv_svc.get_active_turn_view(conversation_id=conversation_id)
    rows = await conv_svc.load_conversation_history_view(conversation_id=conversation_id)
    return MessageHistoryResponse(messages=[MessageHistoryItem(**r) for r in rows], active_turn=active_turn)


@router.get("/conversations/{conversation_id}/turns/{turn_key}/attachments/{attachment_index}")
async def download_attachment_endpoint(
    conversation_id: int,
    turn_key: str,
    attachment_index: int,
    current_user: User = Depends(get_current_user),
    config: AssistantConfig = Depends(_get_config),
    conv_svc: ConversationService = Depends(_get_conversation_service),
) -> StreamingResponse:
    """使用者重新取得自己隨訊息上傳的暫存附件（供對話串裡的附件圖示點擊下載/預覽）。

    擁有權檢查 MUST 沿用既有的 join 過的 `get_turn_owned`／`get_uploaded_file_owned`（皆同時比對
    user_id／conversation_id／turn_id），不得另開只用 turn_key 的單獨查詢，避免弱化既有的四重
    擁有權比對。`Content-Disposition` 一律 `attachment`（不使用 inline),防止使用者上傳的
    HTML/SVG 內容被同源瀏覽器 inline 執行。
    """
    _require_enabled(config)
    turn = await conv_svc.get_turn_owned(user_id=current_user.id, conversation_id=conversation_id, turn_key=turn_key)
    uploaded = await conv_svc.get_uploaded_file_owned(
        user_id=current_user.id, conversation_id=conversation_id, turn_id=turn.id, attachment_index=attachment_index
    )
    try:
        disk_path = attachment_storage.resolve_stored_path(uploaded.relative_path)
    except ValueError:
        disk_path = None
    if disk_path is None or not disk_path.is_file():
        # 暫存附件已過保存期被 retention job 清除（或尚未清完 DB row 前的極短窗口），一律視為
        # 找不到，不回傳誤導性的其他狀態。
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ATTACHMENT_NOT_FOUND", "message": "attachment is no longer available"},
        )

    media_type = uploaded.content_type or mimetypes.guess_type(uploaded.original_name)[0] or "application/octet-stream"
    try:
        uploaded.original_name.encode("ascii")
        content_disposition = f'attachment; filename="{uploaded.original_name}"'
    except UnicodeEncodeError:
        encoded_name = urllib.parse.quote(uploaded.original_name, safe="")
        content_disposition = f"attachment; filename*=UTF-8''{encoded_name}"

    def _iterfile():
        with open(disk_path, "rb") as f:
            yield from f

    return StreamingResponse(
        _iterfile(), media_type=media_type, headers={"Content-Disposition": content_disposition}
    )


# ---------------------------------------------------------------------- #
# 送出訊息（TurnStart + detached runner + SSE）
# ---------------------------------------------------------------------- #


async def _read_capped(file: UploadFile, max_bytes: int) -> bytes:
    data = bytearray()
    while True:
        chunk = await file.read(65536)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail={"code": "UPLOAD_TOO_LARGE", "message": f"attachment exceeds {max_bytes} bytes"},
            )
    return bytes(data)


@router.post("/conversations/{conversation_id}/messages")
async def post_message_endpoint(
    conversation_id: int,
    request: Request,
    text: str = Form(""),
    client_message_id: str = Form(...),
    after_seq: int = Query(-1),
    attachments: list[UploadFile] = File(default=[]),
    current_user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Security(security),
    config: AssistantConfig = Depends(_get_config),
    conv_svc: ConversationService = Depends(_get_conversation_service),
    executor: ToolExecutor = Depends(_get_executor),
    supervisor: RunnerSupervisor = Depends(_get_runner_supervisor),
) -> StreamingResponse:
    _require_enabled(config)
    jwt = credentials.credentials
    conversation = await conv_svc.get_conversation_owned(user_id=current_user.id, conversation_id=conversation_id)

    if len(text) > config.max_message_chars:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "MESSAGE_TOO_LONG", "message": f"message exceeds {config.max_message_chars} chars"},
        )
    if len(attachments) > config.upload_max_files_per_message:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "TOO_MANY_ATTACHMENTS", "message": f"at most {config.upload_max_files_per_message} attachments"},
        )

    files_data = []
    for file in attachments:
        data = await _read_capped(file, config.upload_max_file_bytes)
        files_data.append((file.filename or "attachment", file.content_type, data, ids.compute_sha256_hex(data)))
    digests = [d[3] for d in files_data]

    reserved = await supervisor.try_reserve_slot()
    if not reserved:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "ADMISSION_DENIED", "message": "server busy, please retry"},
        )

    try:
        result = await conv_svc.start_turn(
            conversation=conversation, client_message_id=client_message_id, text=text, attachment_digests=digests
        )
    except AssistantError:
        await supervisor.release_slot()
        raise

    if result.is_replay:
        await supervisor.release_slot()
        return _stream_response(conv_svc, turn_id=result.turn.id, turn_key=result.turn.turn_key, after_seq=after_seq)

    now = datetime.utcnow()
    expires_at = now + timedelta(hours=config.upload_retention_hours)
    saved_attachments: list[dict] = []
    for idx, (original_name, content_type, data, sha256) in enumerate(files_data):
        absolute, relative = attachment_storage.generate_stored_path(conversation.conversation_key)
        absolute.parent.mkdir(parents=True, exist_ok=True)
        absolute.write_bytes(data)
        saved = await conv_svc.record_uploaded_file(
            turn_id=result.turn.id, attachment_index=idx, original_name=original_name, relative_path=relative,
            sha256=sha256, content_type=content_type, size_bytes=len(data), expires_at=expires_at,
        )
        if saved is None:
            with contextlib.suppress(OSError):
                absolute.unlink(missing_ok=True)
        else:
            saved_attachments.append(
                {"attachment_index": idx, "original_name": original_name, "content_type": content_type, "size_bytes": len(data)}
            )

    if saved_attachments:
        # 前端在此事件抵達前只知道「送出了幾個檔案」,不知道是否真的落地成功;讓使用者訊息泡泡裡
        # 的附件圖示能從 pending 轉成已確認狀態（見 spec assistant-conversations「LLM 被告知本回合
        # 可用的附件」旁的附件顯示 Requirement）。沿用既有事件系統,SSE 重連時天然可重播。
        await conv_svc.append_event(
            turn_id=result.turn.id, event_type="attachments_saved", payload={"attachments": saved_attachments}
        )

    supervisor.spawn_reserved(
        result.turn.turn_key,
        lambda: agent_svc.run_agent_turn(
            conversation=conversation, turn=result.turn, user_id=current_user.id, role=current_user.role, jwt=jwt,
            conversation_service=conv_svc, executor=executor, llm_service=get_assistant_llm_service(),
            registry=executor.registry, config=config,
        ),
    )
    return _stream_response(conv_svc, turn_id=result.turn.id, turn_key=result.turn.turn_key, after_seq=after_seq)


@router.get("/conversations/{conversation_id}/turns/{turn_key}/events")
async def stream_turn_events_endpoint(
    conversation_id: int,
    turn_key: str,
    after_seq: int = Query(-1),
    current_user: User = Depends(get_current_user),
    config: AssistantConfig = Depends(_get_config),
    conv_svc: ConversationService = Depends(_get_conversation_service),
) -> StreamingResponse:
    _require_enabled(config)
    turn = await conv_svc.get_turn_owned(user_id=current_user.id, conversation_id=conversation_id, turn_key=turn_key)
    return _stream_response(conv_svc, turn_id=turn.id, turn_key=turn.turn_key, after_seq=after_seq)


@router.post("/conversations/{conversation_id}/turns/{turn_key}/stop", response_model=StopAckResponse)
async def stop_turn_endpoint(
    conversation_id: int,
    turn_key: str,
    current_user: User = Depends(get_current_user),
    config: AssistantConfig = Depends(_get_config),
    conv_svc: ConversationService = Depends(_get_conversation_service),
) -> StopAckResponse:
    _require_enabled(config)
    turn = await conv_svc.get_turn_owned(user_id=current_user.id, conversation_id=conversation_id, turn_key=turn_key)
    await conv_svc.request_cancel(turn_id=turn.id)
    return StopAckResponse(turn_key=turn.turn_key)


# ---------------------------------------------------------------------- #
# Confirm / Cancel（spec assistant-action-confirmation「confirm 的判斷順序」）
# ---------------------------------------------------------------------- #


@router.post("/conversations/{conversation_id}/actions/{action_id}/confirm")
async def confirm_action_endpoint(
    conversation_id: int,
    action_id: int,
    after_seq: int = Query(-1),
    current_user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Security(security),
    config: AssistantConfig = Depends(_get_config),
    conv_svc: ConversationService = Depends(_get_conversation_service),
    executor: ToolExecutor = Depends(_get_executor),
    supervisor: RunnerSupervisor = Depends(_get_runner_supervisor),
):
    _require_enabled(config)
    jwt = credentials.credentials
    conversation = await conv_svc.get_conversation_owned(user_id=current_user.id, conversation_id=conversation_id)
    action = await conv_svc.get_pending_action_owned(user_id=current_user.id, conversation_id=conversation_id, action_id=action_id)

    # 判斷 1：既有 continuation → 只重播既有事件，不重新認領或執行。
    existing = await conv_svc.find_continuation_turn(conversation_id=conversation_id, execution_key=action.execution_key)
    if existing is not None:
        return _stream_response(conv_svc, turn_id=existing.id, turn_key=existing.turn_key, after_seq=after_seq)

    # 判斷 3：已達終態但無 continuation（理論上不會發生於正常路徑，防禦性處理）。
    if action.status in ("confirmed", "failed", "unknown"):
        return JSONResponse({"action_id": action.id, "status": action.status})

    # 判斷 4：expired/cancelled 一律回明確錯誤。
    if action.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "PENDING_ACTION_NOT_CLAIMABLE", "message": f"action is {action.status}"},
        )

    tool = executor.registry.get(action.tool_name)
    if tool is None or action.execution_payload_json is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "PENDING_ACTION_NOT_CLAIMABLE", "message": "action is no longer claimable"},
        )

    # Fail-closed：decrypt/parse 失敗必須 CAS expire pending，不可裸 500 留下可再 confirm 的卡到 TTL。
    try:
        execution_payload = executor.decrypt_execution_payload(
            tool, execution_key=action.execution_key, execution_payload_json=action.execution_payload_json,
            encrypted=action.execution_payload_encrypted,
        )
    except Exception:  # noqa: BLE001 - any decrypt/parse failure is fail-closed
        await conv_svc.expire_pending_now(
            action_id=action.id,
            synthetic_result={
                "status": "expired",
                "code": "execution_payload_decrypt_failed",
                "message": "execution payload could not be decrypted or parsed",
            },
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "EXECUTION_PAYLOAD_DECRYPT_FAILED",
                "message": "execution payload could not be decrypted or parsed; action expired",
            },
        )
    path_params = execution_payload.get("path_params", {})
    query_params = execution_payload.get("query_params", {})
    body_params = execution_payload.get("body_params", {})

    # combined_schema 要求 multipart 工具帶 file_ref；execution_payload 另存為
    # {"turn_id":..,"attachment_index":..}（見 tool_executor.prepare_write_tool），非原始 LLM 字串，
    # 重驗證時以其 attachment_index 合成回字串，僅供 schema「必填欄位存在」檢查用。
    revalidate_args = {**path_params, **query_params, **body_params}
    file_ref = execution_payload.get("file_ref")
    if tool.multipart_file_param and file_ref:
        revalidate_args["file_ref"] = str(file_ref.get("attachment_index"))

    validation = validate_arguments(revalidate_args, combined_schema(tool))
    if not validation.ok:
        await conv_svc.expire_pending_now(
            action_id=action.id, synthetic_result={"status": "expired", "code": "schema_invalid", "message": "; ".join(validation.errors)}
        )
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "SCHEMA_INVALID", "message": "; ".join(validation.errors)})

    if not await executor.check_permission(tool, user_id=current_user.id, team_id=conversation.team_id, role=current_user.role):
        await conv_svc.expire_pending_now(action_id=action.id, synthetic_result={"status": "expired", "code": "permission_denied"})
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "TOOL_PERMISSION_DENIED", "message": "insufficient permission"})

    if tool.execution_mode == "batch_actions":
        rejection = await executor.validate_batch_actions(
            body_params.get("actions") or [], conversation_team_id=conversation.team_id,
            user_id=current_user.id, role=current_user.role,
        )
        if rejection is not None:
            await conv_svc.expire_pending_now(
                action_id=action.id,
                synthetic_result={"status": "expired", "code": rejection.code, "message": rejection.message},
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": rejection.code.upper(), "message": rejection.message},
            )

    if conversation.scope_type != "team" or conversation.team_id is None:
        await conv_svc.expire_pending_now(action_id=action.id, synthetic_result={"status": "expired", "code": "scope_invalid"})
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "SCOPE_INVALID", "message": "conversation is no longer team-bound"})

    resolved_team = await executor.resolve_team(tool, conversation_team_id=conversation.team_id, path_params=path_params, body_params=body_params)
    if resolved_team != conversation.team_id:
        await conv_svc.expire_pending_now(action_id=action.id, synthetic_result={"status": "expired", "code": "team_mismatch"})
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "TEAM_SCOPE_MISMATCH", "message": "resource no longer belongs to this conversation's team"})

    summary_result = await executor.build_confirmation_summary(tool, path_params=path_params, body_params=body_params)
    if summary_result is None:
        await conv_svc.expire_pending_now(action_id=action.id, synthetic_result={"status": "expired", "code": "confirmation_summary_unresolvable"})
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "CONFIRMATION_SUMMARY_UNRESOLVABLE", "message": "cannot resolve a stable target for this action"},
        )
    summary, stable_identity = summary_result
    new_fingerprint = executor.compute_fingerprint(summary, stable_identity)

    if new_fingerprint != action.confirmation_fingerprint:
        await conv_svc.update_pending_summary_cas(
            action_id=action.id, old_fingerprint=action.confirmation_fingerprint, new_summary=summary, new_fingerprint=new_fingerprint
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "CONFIRMATION_STALE", "message": "target changed, please review the updated summary and confirm again"},
        )

    reserved = await supervisor.try_reserve_slot()
    if not reserved:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={"code": "ADMISSION_DENIED", "message": "server busy, please retry"})

    async def _live_fingerprint_recheck() -> tuple[str, dict]:
        # Narrow fingerprint TOCTOU: recompute after lease is taken inside claim Tx A.
        # Resource lookup still uses a separate read session (residual RT-008 risk).
        # Returns (fingerprint, summary) so claim can attach them to ConfirmationStaleError
        # for the API to CAS-update the confirmation card (same as pre-claim path).
        live_summary = await executor.build_confirmation_summary(
            tool, path_params=path_params, body_params=body_params
        )
        if live_summary is None:
            # Treat unresolvable as stale claim failure; outer AssistantError path releases slot.
            from app.services.assistant.errors import ConfirmationSummaryUnresolvableError

            raise ConfirmationSummaryUnresolvableError(
                "cannot resolve a stable target for this action"
            )
        summary2, stable2 = live_summary
        return executor.compute_fingerprint(summary2, stable2), summary2

    try:
        continuation = await conv_svc.claim_pending_for_confirm(
            conversation=conversation,
            action=action,
            recomputed_fingerprint=new_fingerprint,
            tool_timeout_seconds=config.tool_timeout_seconds,
            live_fingerprint_recheck=_live_fingerprint_recheck,
        )
    except ConfirmationStaleError as stale_exc:
        # Live recheck (or claim fingerprint check) detected change. Claim Tx A rolled back;
        # if error carries recomputed card data, CAS-update summary like the pre-claim path.
        await supervisor.release_slot()
        if stale_exc.new_summary is not None and stale_exc.new_fingerprint is not None:
            await conv_svc.update_pending_summary_cas(
                action_id=action.id,
                old_fingerprint=action.confirmation_fingerprint,
                new_summary=stale_exc.new_summary,
                new_fingerprint=stale_exc.new_fingerprint,
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CONFIRMATION_STALE",
                "message": "target changed, please review the updated summary and confirm again",
            },
        )
    except (IntegrityError, AdmissionDeniedError):
        # 併發 confirm race：continuation turn 唯一約束衝突（IntegrityError）或 lease CAS 因贏家已
        # 佔用而失敗（AdmissionDeniedError）——兩者都可能只是「同一 pending action 的並發 confirm」
        # 的副作用，贏家已 commit 的 continuation 會被以下查詢命中並走重播分支；查無則代表是與本次
        # 無關的真正拒絕（如全域/使用者 admission 已滿），回傳明確錯誤。
        await supervisor.release_slot()
        retry = await conv_svc.find_continuation_turn(conversation_id=conversation_id, execution_key=action.execution_key)
        if retry is not None:
            return _stream_response(conv_svc, turn_id=retry.id, turn_key=retry.turn_key, after_seq=after_seq)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "PENDING_ACTION_NOT_CLAIMABLE", "message": "concurrent confirm race or admission denied"})
    except AssistantError:
        await supervisor.release_slot()
        raise

    # Tx A 已清 DB payload；把 claim 前解密的明文傳給 detached runner（request memory only）。
    supervisor.spawn_reserved(
        continuation.turn_key,
        lambda: agent_svc.run_confirm_turn(
            conversation=conversation, continuation_turn=continuation, pending_action=action, tool=tool,
            user_id=current_user.id, role=current_user.role, jwt=jwt,
            conversation_service=conv_svc, executor=executor, llm_service=get_assistant_llm_service(),
            registry=executor.registry, config=config, execution_payload=execution_payload,
        ),
    )
    return _stream_response(conv_svc, turn_id=continuation.id, turn_key=continuation.turn_key, after_seq=after_seq)


@router.post("/conversations/{conversation_id}/actions/{action_id}/cancel", response_model=ActionAckResponse)
async def cancel_action_endpoint(
    conversation_id: int,
    action_id: int,
    current_user: User = Depends(get_current_user),
    config: AssistantConfig = Depends(_get_config),
    conv_svc: ConversationService = Depends(_get_conversation_service),
) -> ActionAckResponse:
    _require_enabled(config)
    await conv_svc.get_conversation_owned(user_id=current_user.id, conversation_id=conversation_id)  # 404 gate
    action = await conv_svc.get_pending_action_owned(user_id=current_user.id, conversation_id=conversation_id, action_id=action_id)
    await conv_svc.cancel_pending(action_id=action.id)
    return ActionAckResponse(action_id=action.id, status="cancelled")
