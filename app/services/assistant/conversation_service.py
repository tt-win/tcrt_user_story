"""Assistant 對話／turn／pending action 的持久化與併發控制服務層。

實作 design D3/D4/D7/D9 的交易邊界：TurnStart Tx（quota + admission + lease + turn_seq + turn）、
ReadTool Tx A/B（journal）、Pending Tx（原子收尾 source turn）、Confirm Tx A/B、cancel CAS、
以及 orphan turn／executing pending 的 fencing recovery。所有寫入一律經
`MainAccessBoundary.run_write`，每個「Tx」對應恰好一次 `run_write` 呼叫（一次 commit）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import AssistantConfig
from app.db_access.main import MainAccessBoundary
from app.models.database_models import (
    AssistantConversation,
    AssistantEvent,
    AssistantMessage,
    AssistantPendingAction,
    AssistantRateLimitBucket,
    AssistantRuntimeCounter,
    AssistantToolExecution,
    AssistantTurn,
    AssistantUploadedFile,
)
from app.services.assistant import ids, title_service
from app.services.assistant.errors import (
    AdmissionDeniedError,
    ConfirmationStaleError,
    ConversationHasActiveTurnError,
    ConversationNotFoundError,
    IdempotencyKeyReusedError,
    PendingActionNotClaimableError,
    PendingActionNotFoundError,
    ScopeInvalidError,
)
from app.services.assistant.projection import apply_credential_redaction

logger = logging.getLogger(__name__)

# Lease 續租安全邊際：對外呼叫 timeout 之外額外保留的秒數。
LEASE_SAFETY_MARGIN_SECONDS = 15
# runtime counter 的固定 scope key；順序恆為 global -> user:<id>，避免死鎖。
GLOBAL_ADMISSION_SCOPE_KEY = "global"

# 對話標題背景生成 task：存強引用防止提前 GC（比照 runner_supervisor 的既有慣例）。
_background_title_tasks: set[asyncio.Task] = set()


def _fire_and_forget_title_generation(service: "ConversationService", conversation_key: str) -> None:
    async def _run() -> None:
        try:
            await service.maybe_generate_title(conversation_key)
        except Exception:  # noqa: BLE001
            logger.exception(
                "assistant title generation failed conversation_key=%s", conversation_key
            )

    task = asyncio.create_task(_run(), name=f"assistant-title-{conversation_key}")
    _background_title_tasks.add(task)
    task.add_done_callback(_background_title_tasks.discard)


def _fallback_title_from_user_text(text: str, *, max_chars: int) -> Optional[str]:
    collapsed = " ".join(text.split())
    if not collapsed:
        return None
    if len(collapsed) > max_chars:
        collapsed = collapsed[:max_chars].rstrip() + "…"
    return collapsed


def user_admission_scope_key(user_id: int) -> str:
    return f"user:{user_id}"


async def _db_now(session: AsyncSession) -> datetime:
    result = await session.execute(select(func.now()))
    value = result.scalar_one()
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace(" ", "T"))  # 防禦性 fallback


def _current_hour_bucket(now: datetime) -> datetime:
    return now.replace(minute=0, second=0, microsecond=0)


async def _conditional_increment_bucket(
    session: AsyncSession, *, user_id: int, bucket_started_at: datetime, limit: int
) -> bool:
    """user/hour rate-limit bucket 原子保留一個名額；savepoint insert + unique-race fallback。"""
    result = await session.execute(
        update(AssistantRateLimitBucket)
        .where(
            AssistantRateLimitBucket.user_id == user_id,
            AssistantRateLimitBucket.bucket_started_at == bucket_started_at,
            AssistantRateLimitBucket.used_count < limit,
        )
        .values(used_count=AssistantRateLimitBucket.used_count + 1)
    )
    if result.rowcount > 0:
        return True
    existing = (
        await session.execute(
            select(AssistantRateLimitBucket.id).where(
                AssistantRateLimitBucket.user_id == user_id,
                AssistantRateLimitBucket.bucket_started_at == bucket_started_at,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False  # bucket 存在但已達上限
    try:
        async with session.begin_nested():
            session.add(
                AssistantRateLimitBucket(
                    user_id=user_id,
                    bucket_started_at=bucket_started_at,
                    used_count=1,
                    expires_at=bucket_started_at + timedelta(hours=2),
                )
            )
        return True
    except IntegrityError:
        result2 = await session.execute(
            update(AssistantRateLimitBucket)
            .where(
                AssistantRateLimitBucket.user_id == user_id,
                AssistantRateLimitBucket.bucket_started_at == bucket_started_at,
                AssistantRateLimitBucket.used_count < limit,
            )
            .values(used_count=AssistantRateLimitBucket.used_count + 1)
        )
        return result2.rowcount > 0


async def _conditional_increment_counter(session: AsyncSession, *, scope_key: str, limit: int) -> bool:
    """runtime admission counter 原子保留一個名額；savepoint insert + unique-race fallback。"""
    result = await session.execute(
        update(AssistantRuntimeCounter)
        .where(AssistantRuntimeCounter.scope_key == scope_key, AssistantRuntimeCounter.active_count < limit)
        .values(active_count=AssistantRuntimeCounter.active_count + 1)
    )
    if result.rowcount > 0:
        return True
    existing = (
        await session.execute(
            select(AssistantRuntimeCounter.scope_key).where(AssistantRuntimeCounter.scope_key == scope_key)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False
    try:
        async with session.begin_nested():
            session.add(AssistantRuntimeCounter(scope_key=scope_key, active_count=1))
        return True
    except IntegrityError:
        result2 = await session.execute(
            update(AssistantRuntimeCounter)
            .where(AssistantRuntimeCounter.scope_key == scope_key, AssistantRuntimeCounter.active_count < limit)
            .values(active_count=AssistantRuntimeCounter.active_count + 1)
        )
        return result2.rowcount > 0


async def _decrement_counter(session: AsyncSession, *, scope_key: str) -> None:
    await session.execute(
        update(AssistantRuntimeCounter)
        .where(AssistantRuntimeCounter.scope_key == scope_key, AssistantRuntimeCounter.active_count > 0)
        .values(active_count=AssistantRuntimeCounter.active_count - 1)
    )


async def _release_admission_once(session: AsyncSession, *, turn: AssistantTurn, user_id: int) -> None:
    """CAS `admission_released` 確保 global/user counter 各只釋放一次。"""
    result = await session.execute(
        update(AssistantTurn)
        .where(AssistantTurn.id == turn.id, AssistantTurn.admission_released.is_(False))
        .values(admission_released=True)
    )
    if result.rowcount == 0:
        return
    await _decrement_counter(session, scope_key=GLOBAL_ADMISSION_SCOPE_KEY)
    await _decrement_counter(session, scope_key=user_admission_scope_key(user_id))


async def _acquire_or_renew_lease(
    session: AsyncSession, *, conversation_id: int, owner_key: str, ttl_seconds: int, db_now: datetime
) -> bool:
    expires_at = db_now + timedelta(seconds=ttl_seconds)
    result = await session.execute(
        update(AssistantConversation)
        .where(
            AssistantConversation.id == conversation_id,
            or_(
                AssistantConversation.active_turn_key == owner_key,
                AssistantConversation.active_turn_key.is_(None),
                AssistantConversation.turn_lease_expires_at < db_now,
            ),
        )
        .values(active_turn_key=owner_key, turn_lease_expires_at=expires_at)
    )
    return result.rowcount > 0


async def _release_lease(session: AsyncSession, *, conversation_id: int, owner_key: str) -> None:
    await session.execute(
        update(AssistantConversation)
        .where(AssistantConversation.id == conversation_id, AssistantConversation.active_turn_key == owner_key)
        .values(active_turn_key=None, turn_lease_expires_at=None)
    )


@dataclass
class TurnStartResult:
    conversation: AssistantConversation
    turn: AssistantTurn
    is_replay: bool


class ConversationService:
    def __init__(self, main_boundary: MainAccessBoundary, config: AssistantConfig):
        self.main_boundary = main_boundary
        self.config = config

    # ------------------------------------------------------------------ #
    # Conversations
    # ------------------------------------------------------------------ #

    async def create_conversation(
        self, *, user_id: int, scope_type: str, team_id: Optional[int], title: Optional[str] = None
    ) -> AssistantConversation:
        if scope_type not in ("global", "team"):
            raise ValueError("scope_type must be 'global' or 'team'")
        if scope_type == "team" and team_id is None:
            raise ValueError("team_id is required for scope_type='team'")

        async def _create(session: AsyncSession) -> AssistantConversation:
            now = await _db_now(session)
            conv = AssistantConversation(
                conversation_key=ids.generate_conversation_key(),
                user_id=user_id,
                team_id=team_id if scope_type == "team" else None,
                scope_type=scope_type,
                source_team_id=team_id if scope_type == "team" else None,
                title=title,
                status="active",
                created_at=now,
                updated_at=now,
                last_message_at=now,
            )
            session.add(conv)
            await session.flush()
            return conv

        return await self.main_boundary.run_write(_create)

    async def list_conversations(
        self, *, user_id: int, team_id: Optional[int] = None, limit: int = 10
    ) -> list[AssistantConversation]:
        async def _list(session: AsyncSession) -> list[AssistantConversation]:
            stmt = (
                select(AssistantConversation)
                .where(AssistantConversation.user_id == user_id, AssistantConversation.status == "active")
                .order_by(AssistantConversation.last_message_at.desc())
                .limit(limit)
            )
            if team_id is not None:
                stmt = stmt.where(AssistantConversation.team_id == team_id)
            return list((await session.execute(stmt)).scalars().all())

        return await self.main_boundary.run_read(_list)

    async def get_conversation_owned(self, *, user_id: int, conversation_id: int) -> AssistantConversation:
        async def _get(session: AsyncSession) -> Optional[AssistantConversation]:
            return (
                await session.execute(
                    select(AssistantConversation).where(
                        AssistantConversation.id == conversation_id,
                        AssistantConversation.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()

        conv = await self.main_boundary.run_read(_get)
        if conv is None:
            raise ConversationNotFoundError()
        return conv

    async def delete_conversation(self, *, user_id: int, conversation_id: int) -> None:
        async def _delete(session: AsyncSession) -> None:
            conv = (
                await session.execute(
                    select(AssistantConversation).where(
                        AssistantConversation.id == conversation_id,
                        AssistantConversation.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()
            if conv is None:
                raise ConversationNotFoundError()
            active_turn = (
                await session.execute(
                    select(AssistantTurn.id).where(
                        AssistantTurn.conversation_id == conv.id,
                        AssistantTurn.status == "running",
                    )
                )
            ).scalar_one_or_none()
            if active_turn is not None:
                raise ConversationHasActiveTurnError()
            executing_pending = (
                await session.execute(
                    select(AssistantPendingAction.id)
                    .join(AssistantTurn, AssistantTurn.id == AssistantPendingAction.turn_id)
                    .where(
                        AssistantTurn.conversation_id == conv.id,
                        AssistantPendingAction.status == "executing",
                    )
                )
            ).scalar_one_or_none()
            if executing_pending is not None:
                raise ConversationHasActiveTurnError()
            await session.delete(conv)

        await self.main_boundary.run_write(_delete)

    # ------------------------------------------------------------------ #
    # 對話標題自動摘要
    # ------------------------------------------------------------------ #

    async def _capture_first_turn_key_for_title(
        self, session: AsyncSession, turn: AssistantTurn
    ) -> Optional[str]:
        """僅在該 turn 是對話的第一個 turn（`turn_seq == 0`）時回傳 conversation_key,供終態化路徑
        呼叫端在 transaction commit 後背景觸發標題生成。用 `conversation_key`（不可重用）而非
        `conversation.id`（SQLite 下可能因刪除重建而被下一筆 insert 重新分配到相同數字）當識別鍵。"""
        if turn.turn_seq != 0:
            return None
        return await session.scalar(
            select(AssistantConversation.conversation_key).where(
                AssistantConversation.id == turn.conversation_id
            )
        )

    async def set_title_if_absent(self, conversation_key: str, title: str) -> bool:
        async def _set(session: AsyncSession) -> bool:
            result = await session.execute(
                update(AssistantConversation)
                .where(
                    AssistantConversation.conversation_key == conversation_key,
                    AssistantConversation.title.is_(None),
                )
                .values(title=title)
            )
            return result.rowcount > 0

        return await self.main_boundary.run_write(_set)

    async def maybe_generate_title(self, conversation_key: str) -> None:
        """讀首則 user 訊息與首則「純文字」assistant 訊息,生成一句短標題並 CAS 寫入（僅當
        `title IS NULL`,不覆蓋使用者已自訂或先前已生成的標題）。查無對話（已被刪除）或已有
        標題時直接略過,不呼叫 LLM。"""

        async def _load(session: AsyncSession) -> Optional[tuple[str, Optional[str]]]:
            row = (
                await session.execute(
                    select(AssistantConversation.id, AssistantConversation.title).where(
                        AssistantConversation.conversation_key == conversation_key
                    )
                )
            ).one_or_none()
            if row is None or row.title is not None:
                return None
            conv_id = row.id
            user_text = await session.scalar(
                select(AssistantMessage.content)
                .join(AssistantTurn, AssistantTurn.id == AssistantMessage.turn_id)
                .where(
                    AssistantTurn.conversation_id == conv_id,
                    AssistantMessage.role == "user",
                )
                .order_by(AssistantTurn.turn_seq, AssistantMessage.message_seq)
                .limit(1)
            )
            if not user_text:
                return None
            assistant_text = await session.scalar(
                select(AssistantMessage.content)
                .join(AssistantTurn, AssistantTurn.id == AssistantMessage.turn_id)
                .where(
                    AssistantTurn.conversation_id == conv_id,
                    AssistantMessage.role == "assistant",
                    AssistantMessage.tool_calls_json.is_(None),
                )
                .order_by(AssistantTurn.turn_seq, AssistantMessage.message_seq)
                .limit(1)
            )
            return (user_text, assistant_text)

        loaded = await self.main_boundary.run_read(_load)
        if loaded is None:
            return
        user_text, assistant_text = loaded

        final_title: Optional[str] = None
        if assistant_text:
            final_title = await title_service.generate_title(
                user_text=user_text,
                assistant_text=assistant_text,
                max_chars=self.config.title_max_chars,
            )
        if final_title is None:
            final_title = _fallback_title_from_user_text(
                user_text, max_chars=self.config.title_max_chars
            )
        if final_title:
            await self.set_title_if_absent(conversation_key, final_title)

    # ------------------------------------------------------------------ #
    # Turn 生命週期：TurnStart Tx
    # ------------------------------------------------------------------ #

    async def start_turn(
        self,
        *,
        conversation: AssistantConversation,
        client_message_id: str,
        text: str,
        attachment_digests: list[str],
    ) -> TurnStartResult:
        """實作 design D9 的 TurnStart Tx：冪等檢查 → quota/admission 原子保留 → lease → turn_seq → turn 建立。"""
        fingerprint = ids.compute_request_fingerprint(text, attachment_digests)
        user_id = conversation.user_id
        cfg = self.config

        async def _start(session: AsyncSession) -> TurnStartResult:
            if conversation.scope_type == "team" and conversation.team_id is None:
                # 綁定 team 已被刪除（FK SET NULL）：對話成為唯讀歷史，不得再產生新 turn。
                raise ScopeInvalidError("team 已刪除，此對話僅供查閱歷史")

            existing = (
                await session.execute(
                    select(AssistantTurn).where(
                        AssistantTurn.conversation_id == conversation.id,
                        AssistantTurn.client_message_id == client_message_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise IdempotencyKeyReusedError()
                return TurnStartResult(conversation=conversation, turn=existing, is_replay=True)

            now = await _db_now(session)
            # Spec assistant-action-confirmation：新訊息 MUST 先 expire 既有 pending
            # （含 synthetic tool result 寫入 source turn）才建立新 turn；UI lock 不足。
            await self._expire_open_pending_for_conversation_in_session(
                session, conversation_id=conversation.id, now=now
            )
            bucket_start = _current_hour_bucket(now)
            if not await _conditional_increment_bucket(
                session, user_id=user_id, bucket_started_at=bucket_start, limit=cfg.max_messages_per_hour
            ):
                raise AdmissionDeniedError("每小時訊息數已達上限")

            if not await _conditional_increment_counter(
                session, scope_key=GLOBAL_ADMISSION_SCOPE_KEY, limit=cfg.max_active_turns_global
            ):
                raise AdmissionDeniedError("系統目前進行中的對話已達上限，請稍後再試")
            if not await _conditional_increment_counter(
                session, scope_key=user_admission_scope_key(user_id), limit=cfg.max_active_turns_per_user
            ):
                raise AdmissionDeniedError("你目前進行中的對話已達上限")

            # message_count 檢查 + turn_seq 配發合併成單一原子 UPDATE（CAS by rowcount），
            # 避免「SELECT 後於 Python 端修改屬性」在併發下遺失更新。
            reserve_result = await session.execute(
                update(AssistantConversation)
                .where(
                    AssistantConversation.id == conversation.id,
                    AssistantConversation.message_count < cfg.max_messages_per_conversation,
                )
                .values(
                    message_count=AssistantConversation.message_count + 1,
                    next_turn_seq=AssistantConversation.next_turn_seq + 1,
                    last_message_at=now,
                    updated_at=now,
                )
            )
            if reserve_result.rowcount == 0:
                raise AdmissionDeniedError("單一對話訊息數已達上限")
            conv_row = await session.get(AssistantConversation, conversation.id)
            turn_seq = conv_row.next_turn_seq - 1  # 本次配發到的 turn_seq

            turn_key = ids.generate_turn_key()
            initial_ttl = cfg.turn_timeout_seconds + LEASE_SAFETY_MARGIN_SECONDS
            if not await _acquire_or_renew_lease(
                session, conversation_id=conversation.id, owner_key=turn_key, ttl_seconds=initial_ttl, db_now=now
            ):
                raise AdmissionDeniedError("該對話已有進行中的回合")

            turn = AssistantTurn(
                conversation_id=conversation.id,
                turn_seq=turn_seq,
                turn_key=turn_key,
                client_message_id=client_message_id,
                request_fingerprint=fingerprint,
                status="running",
                started_at=now,
            )
            session.add(turn)
            await session.flush()

            message_seq = turn.next_message_seq
            turn.next_message_seq = message_seq + 1
            session.add(
                AssistantMessage(
                    turn_id=turn.id,
                    message_seq=message_seq,
                    role="user",
                    content=text,
                )
            )
            return TurnStartResult(conversation=conv_row, turn=turn, is_replay=False)

        try:
            return await self.main_boundary.run_write(_start)
        except (IntegrityError, AdmissionDeniedError):
            # unique race loser：同一 client_message_id 併發送出時，SQLite/MySQL/PostgreSQL 下
            # 「先讀（無既有 turn）後寫」的兩個交易可能都通過步驟 (1) 的存在性檢查，其中一個才會
            # 真正 commit；另一個接著在 turn unique constraint（IntegrityError）或 lease CAS
            # （AdmissionDeniedError，因贏家已佔用 lease）失敗。兩種失敗都可能只是「同一 ID 的
            # race」的副作用，因此重新查一次既有 turn：命中且 fingerprint 相符即接續 replay
            # （不重複扣 quota，見 spec assistant-conversations「相同 ID 並發重送」）；查無則代表
            # 這是與本次 client_message_id 無關的真正拒絕（例如額度已滿、其他 turn 佔用 lease），
            # 原樣重新拋出。
            async def _find_existing(session: AsyncSession) -> Optional[AssistantTurn]:
                return (
                    await session.execute(
                        select(AssistantTurn).where(
                            AssistantTurn.conversation_id == conversation.id,
                            AssistantTurn.client_message_id == client_message_id,
                        )
                    )
                ).scalar_one_or_none()

            existing_turn = await self.main_boundary.run_read(_find_existing)
            if existing_turn is not None:
                if existing_turn.request_fingerprint != fingerprint:
                    raise IdempotencyKeyReusedError()
                return TurnStartResult(conversation=conversation, turn=existing_turn, is_replay=True)
            raise

    async def renew_lease(self, *, conversation_id: int, turn_key: str, ttl_seconds: int) -> bool:
        async def _renew(session: AsyncSession) -> bool:
            running_turn = await session.scalar(
                select(AssistantTurn.id).where(
                    AssistantTurn.conversation_id == conversation_id,
                    AssistantTurn.turn_key == turn_key,
                    AssistantTurn.status == "running",
                )
            )
            if running_turn is None:
                return False
            now = await _db_now(session)
            return await _acquire_or_renew_lease(
                session, conversation_id=conversation_id, owner_key=turn_key, ttl_seconds=ttl_seconds, db_now=now
            )

        return await self.main_boundary.run_write(_renew)

    async def complete_turn_release_lease(
        self, *, conversation_id: int, turn_id: int, turn_key: str, user_id: int, status: str, error_message: str | None = None
    ) -> None:
        """一般（無 pending）turn 結束：標終態、CAS 釋放 admission、owner-CAS 釋放 lease。"""

        async def _complete(session: AsyncSession) -> Optional[str]:
            now = await _db_now(session)
            turn = await session.get(AssistantTurn, turn_id)
            if turn is None or turn.status != "running":
                return None
            turn.status = status
            turn.completed_at = now
            turn.error_message = error_message
            await _release_admission_once(session, turn=turn, user_id=user_id)
            await _release_lease(session, conversation_id=conversation_id, owner_key=turn_key)
            return await self._capture_first_turn_key_for_title(session, turn)

        title_key = await self.main_boundary.run_write(_complete)
        if title_key is not None:
            _fire_and_forget_title_generation(self, title_key)

    # ------------------------------------------------------------------ #
    # Events / Messages
    # ------------------------------------------------------------------ #

    async def append_event(self, *, turn_id: int, event_type: str, payload: dict[str, Any] | None) -> int:
        async def _append(session: AsyncSession) -> int:
            turn = await session.get(AssistantTurn, turn_id)
            if turn is None:
                raise ValueError(f"turn {turn_id} not found")
            seq = turn.next_event_seq
            turn.next_event_seq = seq + 1
            session.add(
                AssistantEvent(
                    turn_id=turn_id,
                    seq=seq,
                    event_type=event_type,
                    payload_json=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                )
            )
            return seq

        return await self.main_boundary.run_write(_append)

    async def append_message(
        self,
        *,
        turn_id: int,
        role: str,
        content: str | None,
        tool_calls_json: str | None = None,
        llm_tool_call_id: str | None = None,
        tool_name: str | None = None,
    ) -> int:
        async def _append(session: AsyncSession) -> int:
            turn = await session.get(AssistantTurn, turn_id)
            if turn is None:
                raise ValueError(f"turn {turn_id} not found")
            seq = turn.next_message_seq
            turn.next_message_seq = seq + 1
            session.add(
                AssistantMessage(
                    turn_id=turn_id,
                    message_seq=seq,
                    role=role,
                    content=content,
                    tool_calls_json=tool_calls_json,
                    llm_tool_call_id=llm_tool_call_id,
                    tool_name=tool_name,
                )
            )
            return seq

        return await self.main_boundary.run_write(_append)

    async def append_tool_call_and_result(
        self,
        *,
        turn_id: int,
        llm_tool_call_id: str,
        tool_name: str,
        arguments_for_history: dict[str, Any],
        tool_result_payload: dict[str, Any],
    ) -> None:
        """read 工具成功執行後的訊息配對（design D4「read 工具訊息原子成對持久化」）：

        assistant tool-call 訊息與其 tool-result 訊息在同一交易依序寫入；若交易 rollback，
        兩者皆不出現在歷史，不留孤兒 tool call。"""

        async def _append(session: AsyncSession) -> None:
            seq1 = await self._next_message_seq_in_session(session, turn_id)
            session.add(
                AssistantMessage(
                    turn_id=turn_id,
                    message_seq=seq1,
                    role="assistant",
                    content=None,
                    tool_calls_json=json.dumps(
                        [{"id": llm_tool_call_id, "name": tool_name, "arguments": apply_credential_redaction(arguments_for_history)}],
                        ensure_ascii=False,
                    ),
                    llm_tool_call_id=llm_tool_call_id,
                    tool_name=tool_name,
                )
            )
            turn = await session.get(AssistantTurn, turn_id)
            seq2 = turn.next_message_seq
            turn.next_message_seq = seq2 + 1
            session.add(
                AssistantMessage(
                    turn_id=turn_id,
                    message_seq=seq2,
                    role="tool",
                    content=json.dumps(tool_result_payload, ensure_ascii=False),
                    llm_tool_call_id=llm_tool_call_id,
                    tool_name=tool_name,
                )
            )

        await self.main_boundary.run_write(_append)

    async def record_uploaded_file(
        self,
        *,
        turn_id: int,
        attachment_index: int,
        original_name: str,
        relative_path: str,
        sha256: str,
        content_type: str | None,
        size_bytes: int,
        expires_at: datetime,
    ) -> Optional[AssistantUploadedFile]:
        """`(turn_id, attachment_index)` unique：並發重送的 loser 回傳 None，呼叫端需清除自己剛寫的暫存檔。"""

        async def _record(session: AsyncSession) -> Optional[AssistantUploadedFile]:
            row = AssistantUploadedFile(
                turn_id=turn_id,
                attachment_index=attachment_index,
                original_name=original_name,
                relative_path=relative_path,
                sha256=sha256,
                content_type=content_type,
                size_bytes=size_bytes,
                expires_at=expires_at,
            )
            try:
                async with session.begin_nested():
                    session.add(row)
                return row
            except IntegrityError:
                return None

        return await self.main_boundary.run_write(_record)

    async def get_uploaded_file_owned(
        self, *, user_id: int, conversation_id: int, turn_id: int, attachment_index: int
    ) -> AssistantUploadedFile:
        async def _get(session: AsyncSession) -> Optional[AssistantUploadedFile]:
            return (
                await session.execute(
                    select(AssistantUploadedFile)
                    .join(AssistantTurn, AssistantTurn.id == AssistantUploadedFile.turn_id)
                    .join(AssistantConversation, AssistantConversation.id == AssistantTurn.conversation_id)
                    .where(
                        AssistantUploadedFile.turn_id == turn_id,
                        AssistantUploadedFile.attachment_index == attachment_index,
                        AssistantTurn.conversation_id == conversation_id,
                        AssistantConversation.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()

        row = await self.main_boundary.run_read(_get)
        if row is None:
            raise PendingActionNotFoundError("附件不存在或不屬於此對話")
        return row

    async def get_events_after(self, *, turn_id: int, after_seq: int) -> list[AssistantEvent]:
        async def _get(session: AsyncSession) -> list[AssistantEvent]:
            return list(
                (
                    await session.execute(
                        select(AssistantEvent)
                        .where(AssistantEvent.turn_id == turn_id, AssistantEvent.seq > after_seq)
                        .order_by(AssistantEvent.seq.asc())
                    )
                )
                .scalars()
                .all()
            )

        return await self.main_boundary.run_read(_get)

    async def load_conversation_messages(self, *, conversation_id: int) -> list[AssistantMessage]:
        """依 turn_seq→message_seq 排序回傳全對話的 LLM 語意歷史（design D4「LLM history 正規化」）。"""

        async def _load(session: AsyncSession) -> list[AssistantMessage]:
            return list(
                (
                    await session.execute(
                        select(AssistantMessage)
                        .join(AssistantTurn, AssistantTurn.id == AssistantMessage.turn_id)
                        .where(AssistantTurn.conversation_id == conversation_id)
                        .order_by(AssistantTurn.turn_seq.asc(), AssistantMessage.message_seq.asc())
                    )
                )
                .scalars()
                .all()
            )

        return await self.main_boundary.run_read(_load)

    async def load_conversation_history_view(self, *, conversation_id: int) -> list[dict[str, Any]]:
        """`GET .../messages` 用：訊息 join turn（turn_seq/turn_key）並附上目前的 pending action
        狀態/摘要，讓前端可重建含確認卡的完整歷史（spec assistant-conversations「訊息歷史可完整
        重建對話畫面」）。"""

        async def _load(session: AsyncSession) -> list[dict[str, Any]]:
            rows = (
                await session.execute(
                    select(
                        AssistantMessage,
                        AssistantTurn.turn_seq,
                        AssistantTurn.turn_key,
                        AssistantTurn.status,
                    )
                    .join(AssistantTurn, AssistantTurn.id == AssistantMessage.turn_id)
                    .where(AssistantTurn.conversation_id == conversation_id)
                    .order_by(AssistantTurn.turn_seq.asc(), AssistantMessage.message_seq.asc())
                )
            ).all()
            pending_rows = (
                (
                    await session.execute(
                        select(AssistantPendingAction)
                        .join(AssistantTurn, AssistantTurn.id == AssistantPendingAction.turn_id)
                        .where(AssistantTurn.conversation_id == conversation_id)
                    )
                )
                .scalars()
                .all()
            )
            pending_by_call_id = {p.llm_tool_call_id: p for p in pending_rows}
            journal_rows = (
                (
                    await session.execute(
                        select(AssistantToolExecution).where(
                            AssistantToolExecution.conversation_id == conversation_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            journal_outcome_by_call_id = {
                row.llm_tool_call_id: row.status
                for row in journal_rows
                if row.llm_tool_call_id and row.status in ("succeeded", "failed", "unknown")
            }

            out: list[dict[str, Any]] = []
            outcome_by_pending_status = {
                "confirmed": "succeeded",
                "failed": "failed",
                "unknown": "unknown",
            }
            for message, turn_seq, turn_key, turn_status in rows:
                item: dict[str, Any] = {
                    "turn_seq": turn_seq,
                    "turn_key": turn_key,
                    "turn_status": turn_status,
                    "message_seq": message.message_seq,
                    "role": message.role,
                    "content": message.content,
                    "tool_name": message.tool_name,
                    "llm_tool_call_id": message.llm_tool_call_id,
                    "tool_calls": json.loads(message.tool_calls_json) if message.tool_calls_json else None,
                }
                pending = pending_by_call_id.get(message.llm_tool_call_id) if message.llm_tool_call_id else None
                if message.role == "tool" and message.content:
                    try:
                        parsed_result = json.loads(message.content)
                    except (TypeError, json.JSONDecodeError):
                        parsed_result = {"message": message.content}
                    item["tool_result"] = (
                        parsed_result if isinstance(parsed_result, dict) else {"result": parsed_result}
                    )
                    if pending is not None:
                        item["tool_outcome"] = outcome_by_pending_status.get(pending.status)
                    else:
                        item["tool_outcome"] = journal_outcome_by_call_id.get(message.llm_tool_call_id)
                        if item["tool_outcome"] is None and item["tool_result"].get("status") == "error":
                            item["tool_outcome"] = "failed"
                if pending is not None:
                    item["pending_action"] = {
                        "action_id": pending.id,
                        "status": pending.status,
                        "confirmation_summary": json.loads(pending.confirmation_summary_json),
                        "expires_at": pending.expires_at.isoformat() if pending.expires_at else None,
                    }
                out.append(item)
            return out

        return await self.main_boundary.run_read(_load)

    async def get_active_turn_view(self, *, conversation_id: int) -> dict[str, Any] | None:
        async def _get(session: AsyncSession) -> dict[str, Any] | None:
            turn = (
                await session.execute(
                    select(AssistantTurn)
                    .where(AssistantTurn.conversation_id == conversation_id, AssistantTurn.status == "running")
                    .order_by(AssistantTurn.turn_seq.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            return {"turn_key": turn.turn_key, "status": turn.status} if turn is not None else None

        return await self.main_boundary.run_read(_get)

    async def list_uploaded_files_for_conversation(self, *, conversation_id: int) -> list[AssistantUploadedFile]:
        async def _list(session: AsyncSession) -> list[AssistantUploadedFile]:
            return list(
                (
                    await session.execute(
                        select(AssistantUploadedFile)
                        .join(AssistantTurn, AssistantTurn.id == AssistantUploadedFile.turn_id)
                        .where(AssistantTurn.conversation_id == conversation_id)
                    )
                )
                .scalars()
                .all()
            )

        return await self.main_boundary.run_read(_list)

    async def get_turn_owned(self, *, user_id: int, conversation_id: int, turn_key: str) -> AssistantTurn:
        async def _get(session: AsyncSession) -> Optional[AssistantTurn]:
            return (
                await session.execute(
                    select(AssistantTurn)
                    .join(AssistantConversation, AssistantConversation.id == AssistantTurn.conversation_id)
                    .where(
                        AssistantTurn.turn_key == turn_key,
                        AssistantTurn.conversation_id == conversation_id,
                        AssistantConversation.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()

        turn = await self.main_boundary.run_read(_get)
        if turn is None:
            raise ConversationNotFoundError()
        return turn

    async def is_cancel_requested(self, *, turn_id: int) -> bool:
        async def _check(session: AsyncSession) -> bool:
            row = await session.get(AssistantTurn, turn_id)
            return bool(row and row.cancel_requested)

        return await self.main_boundary.run_read(_check)

    async def request_cancel(self, *, turn_id: int) -> None:
        async def _cancel(session: AsyncSession) -> None:
            await session.execute(
                update(AssistantTurn).where(AssistantTurn.id == turn_id).values(cancel_requested=True)
            )

        await self.main_boundary.run_write(_cancel)

    # ------------------------------------------------------------------ #
    # Read-tool journal（ReadTool Tx A / B）
    # ------------------------------------------------------------------ #

    async def start_read_tool_journal(
        self,
        *,
        conversation: AssistantConversation,
        turn: AssistantTurn,
        user_id: int,
        team_id: int | None,
        llm_tool_call_id: str,
        tool_name: str,
        risk_level: str,
        arguments_json: str | None,
    ) -> int:
        # journal 的 arguments_json 由呼叫端（tool_executor）以尚未遮罩的 body_params 序列化傳入；
        # 這裡於持久化前統一套用 credential 遮罩（defense-in-depth，與 message 的處理方式一致），
        # 不依賴每個呼叫端各自記得遮罩（design：credential 原值不得進 messages/events/journal）。
        if arguments_json is not None:
            arguments_json = json.dumps(apply_credential_redaction(json.loads(arguments_json)), ensure_ascii=False)

        async def _start(session: AsyncSession) -> int:
            row = AssistantToolExecution(
                conversation_id=conversation.id,
                source_conversation_key=conversation.conversation_key,
                source_conversation_id=conversation.id,
                source_turn_key=turn.turn_key,
                execution_key=ids.generate_execution_key(),
                user_id=user_id,
                team_id=team_id,
                llm_tool_call_id=llm_tool_call_id,
                tool_name=tool_name,
                risk_level=risk_level,
                arguments_json=arguments_json,
                status="started",
            )
            session.add(row)
            await session.flush()
            return row.id

        return await self.main_boundary.run_write(_start)

    async def finish_read_tool_journal(
        self, *, journal_id: int, status: str, http_status: int | None, error_message: str | None, target_summary: str | None = None
    ) -> None:
        async def _finish(session: AsyncSession) -> None:
            now = await _db_now(session)
            await session.execute(
                update(AssistantToolExecution)
                .where(AssistantToolExecution.id == journal_id)
                .values(status=status, http_status=http_status, error_message=error_message, target_summary=target_summary, finished_at=now)
            )

        await self.main_boundary.run_write(_finish)

    # ------------------------------------------------------------------ #
    # Pending Tx：write 工具建立 pending 並原子收尾 source turn
    # ------------------------------------------------------------------ #

    async def create_pending_action_and_complete_turn(
        self,
        *,
        conversation_id: int,
        turn_id: int,
        turn_key: str,
        user_id: int,
        tool_name: str,
        arguments_redacted_json: str,
        arguments_for_history: dict[str, Any],
        execution_payload_json: str | None,
        execution_payload_encrypted: bool,
        confirmation_summary: dict[str, Any],
        confirmation_fingerprint: str,
        pending_ttl_seconds: int,
        execution_key: str,
    ) -> AssistantPendingAction:
        """`execution_key` MUST 由呼叫端預先生成（見 `ids.generate_execution_key`）並與
        `tool_executor.prepare_write_tool` 加密時使用的 AAD 一致，否則 confirm 階段解密失敗。"""
        llm_tool_call_id = ids.derive_llm_tool_call_id_for_execution(execution_key)

        async def _create(session: AsyncSession) -> tuple[AssistantPendingAction, Optional[str]]:
            now = await _db_now(session)
            seq = await self._next_message_seq_in_session(session, turn_id)
            session.add(
                AssistantMessage(
                    turn_id=turn_id,
                    message_seq=seq,
                    role="assistant",
                    content=None,
                    tool_calls_json=json.dumps(
                        [{"id": llm_tool_call_id, "name": tool_name, "arguments": apply_credential_redaction(arguments_for_history)}],
                        ensure_ascii=False,
                    ),
                    llm_tool_call_id=llm_tool_call_id,
                    tool_name=tool_name,
                )
            )
            pending = AssistantPendingAction(
                turn_id=turn_id,
                execution_key=execution_key,
                llm_tool_call_id=llm_tool_call_id,
                tool_name=tool_name,
                arguments_redacted_json=arguments_redacted_json,
                execution_payload_json=execution_payload_json,
                execution_payload_encrypted=execution_payload_encrypted,
                confirmation_summary_json=json.dumps(confirmation_summary, ensure_ascii=False),
                confirmation_fingerprint=confirmation_fingerprint,
                status="pending",
                created_at=now,
                expires_at=now + timedelta(seconds=pending_ttl_seconds),
            )
            session.add(pending)
            await session.flush()

            turn = await session.get(AssistantTurn, turn_id)
            eseq = turn.next_event_seq
            turn.next_event_seq = eseq + 1
            session.add(
                AssistantEvent(
                    turn_id=turn_id,
                    seq=eseq,
                    event_type="confirmation_required",
                    payload_json=json.dumps(
                        {"action_id": pending.id, "execution_key": execution_key, "summary": confirmation_summary},
                        ensure_ascii=False,
                    ),
                )
            )
            eseq2 = turn.next_event_seq
            turn.next_event_seq = eseq2 + 1
            session.add(
                AssistantEvent(turn_id=turn_id, seq=eseq2, event_type="done", payload_json=None)
            )

            turn.status = "completed"
            turn.completed_at = now
            await _release_admission_once(session, turn=turn, user_id=user_id)
            await _release_lease(session, conversation_id=conversation_id, owner_key=turn_key)
            title_key = await self._capture_first_turn_key_for_title(session, turn)
            return pending, title_key

        pending, title_key = await self.main_boundary.run_write(_create)
        if title_key is not None:
            _fire_and_forget_title_generation(self, title_key)
        return pending

    async def reject_write_before_pending(
        self,
        *,
        conversation_id: int,
        turn_id: int,
        turn_key: str,
        user_id: int,
        llm_tool_call_id: str,
        tool_name: str,
        arguments_for_history: dict[str, Any],
        synthetic_result: dict[str, Any],
        terminate_turn: bool,
    ) -> None:
        """schema/team/credential 驗證失敗：寫入遮罩後的 assistant tool-call + paired synthetic result。"""

        async def _reject(session: AsyncSession) -> Optional[str]:
            now = await _db_now(session)
            seq1 = await self._next_message_seq_in_session(session, turn_id)
            session.add(
                AssistantMessage(
                    turn_id=turn_id,
                    message_seq=seq1,
                    role="assistant",
                    content=None,
                    tool_calls_json=json.dumps(
                        [{"id": llm_tool_call_id, "name": tool_name, "arguments": apply_credential_redaction(arguments_for_history)}],
                        ensure_ascii=False,
                    ),
                    llm_tool_call_id=llm_tool_call_id,
                    tool_name=tool_name,
                )
            )
            turn = await session.get(AssistantTurn, turn_id)
            seq2 = turn.next_message_seq
            turn.next_message_seq = seq2 + 1
            session.add(
                AssistantMessage(
                    turn_id=turn_id,
                    message_seq=seq2,
                    role="tool",
                    content=json.dumps(synthetic_result, ensure_ascii=False),
                    llm_tool_call_id=llm_tool_call_id,
                    tool_name=tool_name,
                )
            )
            if terminate_turn:
                eseq = turn.next_event_seq
                turn.next_event_seq = eseq + 1
                session.add(
                    AssistantEvent(
                        turn_id=turn_id,
                        seq=eseq,
                        event_type="error",
                        payload_json=json.dumps(synthetic_result, ensure_ascii=False),
                    )
                )
                eseq2 = turn.next_event_seq
                turn.next_event_seq = eseq2 + 1
                session.add(AssistantEvent(turn_id=turn_id, seq=eseq2, event_type="done", payload_json=None))
                turn.status = "failed"
                turn.completed_at = now
                await _release_admission_once(session, turn=turn, user_id=user_id)
                await _release_lease(session, conversation_id=conversation_id, owner_key=turn_key)
                return await self._capture_first_turn_key_for_title(session, turn)
            return None

        title_key = await self.main_boundary.run_write(_reject)
        if title_key is not None:
            _fire_and_forget_title_generation(self, title_key)

    @staticmethod
    async def _next_message_seq_in_session(session: AsyncSession, turn_id: int) -> int:
        turn = await session.get(AssistantTurn, turn_id)
        seq = turn.next_message_seq
        turn.next_message_seq = seq + 1
        return seq

    async def _expire_open_pending_for_conversation_in_session(
        self, session: AsyncSession, *, conversation_id: int, now: datetime
    ) -> int:
        """Expire all `status=pending` actions in this conversation and pair synthetic results
        on their source turns. Called inside start_turn before creating a new turn."""
        rows = (
            await session.execute(
                select(AssistantPendingAction)
                .join(AssistantTurn, AssistantTurn.id == AssistantPendingAction.turn_id)
                .where(
                    AssistantTurn.conversation_id == conversation_id,
                    AssistantPendingAction.status == "pending",
                )
            )
        ).scalars().all()
        expired = 0
        synthetic = {"status": "expired", "code": "superseded_by_new_message"}
        for action in rows:
            result = await session.execute(
                update(AssistantPendingAction)
                .where(
                    AssistantPendingAction.id == action.id,
                    AssistantPendingAction.status == "pending",
                )
                .values(status="expired", resolved_at=now, execution_payload_json=None)
            )
            if result.rowcount == 0:
                continue
            seq = await self._next_message_seq_in_session(session, action.turn_id)
            session.add(
                AssistantMessage(
                    turn_id=action.turn_id,
                    message_seq=seq,
                    role="tool",
                    content=json.dumps(synthetic, ensure_ascii=False),
                    llm_tool_call_id=action.llm_tool_call_id,
                    tool_name=action.tool_name,
                )
            )
            expired += 1
        return expired

    # ------------------------------------------------------------------ #
    # Confirm / Cancel
    # ------------------------------------------------------------------ #

    async def get_pending_action_owned(self, *, user_id: int, conversation_id: int, action_id: int) -> AssistantPendingAction:
        async def _get(session: AsyncSession) -> Optional[AssistantPendingAction]:
            return (
                await session.execute(
                    select(AssistantPendingAction)
                    .join(AssistantTurn, AssistantTurn.id == AssistantPendingAction.turn_id)
                    .join(AssistantConversation, AssistantConversation.id == AssistantTurn.conversation_id)
                    .where(
                        AssistantPendingAction.id == action_id,
                        AssistantTurn.conversation_id == conversation_id,
                        AssistantConversation.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()

        action = await self.main_boundary.run_read(_get)
        if action is None:
            raise PendingActionNotFoundError()
        return action

    async def find_continuation_turn(self, *, conversation_id: int, execution_key: str) -> Optional[AssistantTurn]:
        client_message_id = ids.confirm_client_message_id(execution_key)

        async def _find(session: AsyncSession) -> Optional[AssistantTurn]:
            return (
                await session.execute(
                    select(AssistantTurn).where(
                        AssistantTurn.conversation_id == conversation_id,
                        AssistantTurn.client_message_id == client_message_id,
                    )
                )
            ).scalar_one_or_none()

        return await self.main_boundary.run_read(_find)

    async def claim_pending_for_confirm(
        self,
        *,
        conversation: AssistantConversation,
        action: AssistantPendingAction,
        recomputed_fingerprint: str,
        tool_timeout_seconds: int,
        live_fingerprint_recheck: Optional[Callable[[], Awaitable[tuple[str, dict[str, Any]]]]] = None,
    ) -> AssistantTurn:
        """Confirm Tx A：admission + lease + continuation turn + turn_seq + pending CAS
        （含 TTL/fingerprint、清 payload、rebind turn_id）+ journal started。

        任一步失敗即 rollback，pending 維持可重試（design D9「Pending Tx」延伸）。

        `live_fingerprint_recheck`（可選）：於取得 lease 後、CAS 前再算一次
        ``(fingerprint, summary)``，縮小資源 lookup 與 claim 之間的 TOCTOU 視窗。
        若 fingerprint 與 ``recomputed_fingerprint`` 不同，拋出帶
        ``new_summary``/``new_fingerprint`` 的 ``ConfirmationStaleError``（本 Tx
        rollback）；呼叫端（API）應 CAS 更新確認卡後回 409。完整同-Tx 資源鎖定
        仍不在 v1 範圍（callback 通常另開 read session）；殘餘風險見 red-team RT-008。
        """
        client_message_id = ids.confirm_client_message_id(action.execution_key)
        cfg = self.config

        async def _claim(session: AsyncSession) -> AssistantTurn:
            now = await _db_now(session)

            conv_row = await session.get(AssistantConversation, conversation.id)
            turn_key = ids.generate_turn_key()
            initial_ttl = tool_timeout_seconds + LEASE_SAFETY_MARGIN_SECONDS + 30
            if not await _acquire_or_renew_lease(
                session, conversation_id=conv_row.id, owner_key=turn_key, ttl_seconds=initial_ttl, db_now=now
            ):
                raise AdmissionDeniedError("該對話已有進行中的回合，請稍後再試")

            # Confirm Tx A MUST reserve admission（與 start_turn 同序 global → user）；
            # complete/recovery 會 _release_admission_once 遞減，漏加會系統性 under-count。
            if not await _conditional_increment_counter(
                session, scope_key=GLOBAL_ADMISSION_SCOPE_KEY, limit=cfg.max_active_turns_global
            ):
                raise AdmissionDeniedError("系統目前進行中的對話已達上限，請稍後再試")
            if not await _conditional_increment_counter(
                session, scope_key=user_admission_scope_key(conv_row.user_id), limit=cfg.max_active_turns_per_user
            ):
                raise AdmissionDeniedError("你目前進行中的對話已達上限")

            # 取得 lease 後再讀 pending 現況（縮小 in-memory action 與 DB 的落差）。
            action_row = await session.get(AssistantPendingAction, action.id)
            if (
                action_row is None
                or action_row.status != "pending"
                or action_row.expires_at is None
                or action_row.expires_at <= now
            ):
                raise PendingActionNotClaimableError()
            if action_row.confirmation_fingerprint != recomputed_fingerprint:
                raise ConfirmationStaleError()

            if live_fingerprint_recheck is not None:
                live_fp, live_summary = await live_fingerprint_recheck()
                if live_fp != recomputed_fingerprint:
                    # Tx A 會 rollback；呼叫端用 error 上的 summary/fp CAS 更新確認卡。
                    raise ConfirmationStaleError(
                        new_summary=live_summary,
                        new_fingerprint=live_fp,
                    )

            turn_seq = conv_row.next_turn_seq
            conv_row.next_turn_seq = turn_seq + 1
            continuation = AssistantTurn(
                conversation_id=conv_row.id,
                turn_seq=turn_seq,
                turn_key=turn_key,
                client_message_id=client_message_id,
                request_fingerprint=recomputed_fingerprint,
                status="running",
                started_at=now,
            )
            session.add(continuation)
            await session.flush()

            # Rebind pending.turn_id → continuation：orphan executing recovery 以
            # Pending.turn_id == running Turn 與 active_turn_key 聯結；若仍指 source
            # turn（已 completed）則 recovery 永遠匹配不到。
            claim_result = await session.execute(
                update(AssistantPendingAction)
                .where(
                    AssistantPendingAction.id == action.id,
                    AssistantPendingAction.status == "pending",
                    AssistantPendingAction.expires_at > now,
                    AssistantPendingAction.confirmation_fingerprint == recomputed_fingerprint,
                )
                .values(
                    status="executing",
                    executing_started_at=now,
                    execution_deadline=now
                    + timedelta(seconds=tool_timeout_seconds + LEASE_SAFETY_MARGIN_SECONDS),
                    execution_payload_json=None,
                    turn_id=continuation.id,
                )
            )
            if claim_result.rowcount == 0:
                stale = (
                    await session.execute(
                        select(AssistantPendingAction.confirmation_fingerprint, AssistantPendingAction.status).where(
                            AssistantPendingAction.id == action.id
                        )
                    )
                ).one_or_none()
                if stale is not None and stale[1] == "pending" and stale[0] != recomputed_fingerprint:
                    raise ConfirmationStaleError()
                raise PendingActionNotClaimableError()

            journal = AssistantToolExecution(
                conversation_id=conv_row.id,
                source_conversation_key=conv_row.conversation_key,
                source_conversation_id=conv_row.id,
                source_turn_key=turn_key,
                execution_key=action.execution_key,
                user_id=conv_row.user_id,
                team_id=conv_row.team_id,
                llm_tool_call_id=action.llm_tool_call_id,
                provider_tool_call_id=action.provider_tool_call_id,
                tool_name=action.tool_name,
                risk_level="write",
                arguments_json=action.arguments_redacted_json,
                status="started",
            )
            session.add(journal)
            return continuation

        return await self.main_boundary.run_write(_claim)

    async def finalize_confirm_outcome(
        self,
        *,
        conversation_id: int,
        turn: AssistantTurn,
        action_id: int,
        user_id: int,
        outcome_status: str,
        tool_result_payload: dict[str, Any],
        http_status: int | None,
    ) -> bool:
        """Confirm Tx B：更新 journal/pending 終態、寫 paired tool result、events。

        僅在 pending 仍為 `executing` 時寫入；已終態則 no-op（回傳 False），
        供 runner 錯誤路徑安全重入，避免重複 tool message。
        """

        async def _finalize(session: AsyncSession) -> bool:
            now = await _db_now(session)
            pending_status_map = {"succeeded": "confirmed", "failed": "failed", "unknown": "unknown"}
            pending_status = pending_status_map.get(outcome_status, "unknown")
            owner_is_live = exists(
                select(AssistantTurn.id)
                .join(AssistantConversation, AssistantConversation.id == AssistantTurn.conversation_id)
                .where(
                    AssistantTurn.id == turn.id,
                    AssistantTurn.conversation_id == conversation_id,
                    AssistantTurn.status == "running",
                    AssistantConversation.active_turn_key == turn.turn_key,
                )
            )
            claim = await session.execute(
                update(AssistantPendingAction)
                .where(
                    AssistantPendingAction.id == action_id,
                    AssistantPendingAction.turn_id == turn.id,
                    AssistantPendingAction.status == "executing",
                    owner_is_live,
                )
                .values(
                    status=pending_status,
                    resolved_at=now,
                    execution_payload_json=None,
                )
                .execution_options(synchronize_session=False)
            )
            if claim.rowcount == 0:
                return False
            action = await session.get(AssistantPendingAction, action_id)
            journal = (
                await session.execute(
                    select(AssistantToolExecution).where(AssistantToolExecution.execution_key == action.execution_key)
                )
            ).scalar_one_or_none()
            if journal is not None:
                journal.status = outcome_status
                journal.http_status = http_status
                journal.finished_at = now

            seq = await self._next_message_seq_in_session(session, turn.id)
            session.add(
                AssistantMessage(
                    turn_id=turn.id,
                    message_seq=seq,
                    role="tool",
                    content=json.dumps(tool_result_payload, ensure_ascii=False),
                    llm_tool_call_id=action.llm_tool_call_id,
                    tool_name=action.tool_name,
                )
            )
            turn_row = await session.get(AssistantTurn, turn.id)
            eseq = turn_row.next_event_seq
            turn_row.next_event_seq = eseq + 1
            # Single authoritative tool_finished for confirm path (frontend uses
            # tool_name + outcome; status/result retained for journal-style clients).
            session.add(
                AssistantEvent(
                    turn_id=turn.id,
                    seq=eseq,
                    event_type="tool_finished",
                    payload_json=json.dumps(
                        {
                            "action_id": action.id,
                            "execution_key": action.execution_key,
                            "tool_name": action.tool_name,
                            "status": outcome_status,
                            "outcome": outcome_status,
                            "http_status": http_status,
                            "result": tool_result_payload,
                        },
                        ensure_ascii=False,
                    ),
                )
            )
            return True

        return await self.main_boundary.run_write(_finalize)

    async def complete_continuation_turn(
        self, *, conversation_id: int, turn_id: int, turn_key: str, user_id: int, status: str
    ) -> None:
        await self.complete_turn_release_lease(
            conversation_id=conversation_id, turn_id=turn_id, turn_key=turn_key, user_id=user_id, status=status
        )

    async def is_turn_terminal(self, *, turn_id: int) -> bool:
        async def _is_terminal(session: AsyncSession) -> bool:
            row = (
                await session.execute(
                    select(AssistantTurn.status, exists().where(
                        AssistantEvent.turn_id == turn_id,
                        AssistantEvent.event_type.in_(("done", "cancelled")),
                    )).where(AssistantTurn.id == turn_id)
                )
            ).one_or_none()
            return row is None or (row[0] != "running" and bool(row[1]))

        return await self.main_boundary.run_read(_is_terminal)

    async def update_pending_summary_cas(
        self, *, action_id: int, old_fingerprint: str, new_summary: dict[str, Any], new_fingerprint: str
    ) -> bool:
        """confirm 前重算 fingerprint 改變：CAS 更新卡片摘要/fingerprint，維持 pending 讓使用者依新摘要
        再次確認（spec assistant-action-confirmation「等待確認期間影響範圍改變」）。

        回傳 False 代表 CAS 失敗（action 已被其他路徑處理，例如已被認領或已 cancelled/expired）。"""

        async def _update(session: AsyncSession) -> bool:
            result = await session.execute(
                update(AssistantPendingAction)
                .where(
                    AssistantPendingAction.id == action_id,
                    AssistantPendingAction.status == "pending",
                    AssistantPendingAction.confirmation_fingerprint == old_fingerprint,
                )
                .values(
                    confirmation_summary_json=json.dumps(new_summary, ensure_ascii=False),
                    confirmation_fingerprint=new_fingerprint,
                )
            )
            return result.rowcount > 0

        return await self.main_boundary.run_write(_update)

    async def expire_pending_now(self, *, action_id: int, synthetic_result: dict[str, Any]) -> bool:
        """confirm 前重驗（權限/team 已失效、或 high_impact/irreversible 無法解析穩定 target）：
        CAS 標 expired、清除 execution_payload、寫入 paired synthetic tool result。

        回傳 False 代表 CAS 失敗（action 已被其他路徑處理，如已被 confirm 認領或已 cancelled/expired）。"""

        async def _expire(session: AsyncSession) -> bool:
            now = await _db_now(session)
            action = await session.get(AssistantPendingAction, action_id)
            result = await session.execute(
                update(AssistantPendingAction)
                .where(AssistantPendingAction.id == action_id, AssistantPendingAction.status == "pending")
                .values(status="expired", resolved_at=now, execution_payload_json=None)
            )
            if result.rowcount == 0:
                return False
            seq = await self._next_message_seq_in_session(session, action.turn_id)
            session.add(
                AssistantMessage(
                    turn_id=action.turn_id,
                    message_seq=seq,
                    role="tool",
                    content=json.dumps(synthetic_result, ensure_ascii=False),
                    llm_tool_call_id=action.llm_tool_call_id,
                    tool_name=action.tool_name,
                )
            )
            return True

        return await self.main_boundary.run_write(_expire)

    async def cancel_pending(self, *, action_id: int) -> None:
        """cancel 亦用 CAS，避免覆寫已進入 executing 的 pending（spec assistant-action-confirmation）。"""

        async def _cancel(session: AsyncSession) -> None:
            now = await _db_now(session)
            action = await session.get(AssistantPendingAction, action_id)
            result = await session.execute(
                update(AssistantPendingAction)
                .where(AssistantPendingAction.id == action_id, AssistantPendingAction.status == "pending")
                .values(status="cancelled", resolved_at=now, execution_payload_json=None)
            )
            if result.rowcount == 0:
                raise PendingActionNotClaimableError()
            turn = await session.get(AssistantTurn, action.turn_id)
            seq = turn.next_message_seq
            turn.next_message_seq = seq + 1
            session.add(
                AssistantMessage(
                    turn_id=action.turn_id,
                    message_seq=seq,
                    role="tool",
                    content=json.dumps({"status": "cancelled"}, ensure_ascii=False),
                    llm_tool_call_id=action.llm_tool_call_id,
                    tool_name=action.tool_name,
                )
            )

        await self.main_boundary.run_write(_cancel)

    # ------------------------------------------------------------------ #
    # Recovery / Retention（供 scheduler 任務呼叫）
    # ------------------------------------------------------------------ #

    async def recover_orphan_turns(self) -> int:
        """lease 過期且仍 running、且無 executing pending 綁定的 turn：標 failed 並釋放 admission/lease。

        綁定 executing pending 的 continuation turn 交由 `recover_orphan_executing_pending`
        處理，避免只關 turn 卻留下 executing pending 無法被後續 recovery 匹配。
        """

        async def _recover(session: AsyncSession) -> tuple[int, list[str]]:
            now = await _db_now(session)
            executing_on_turn = exists(
                select(AssistantPendingAction.id).where(
                    AssistantPendingAction.turn_id == AssistantTurn.id,
                    AssistantPendingAction.status == "executing",
                )
            )
            rows = (
                await session.execute(
                    select(AssistantTurn, AssistantConversation)
                    .join(AssistantConversation, AssistantConversation.id == AssistantTurn.conversation_id)
                    .where(
                        AssistantTurn.status == "running",
                        AssistantConversation.active_turn_key == AssistantTurn.turn_key,
                        AssistantConversation.turn_lease_expires_at < now,
                        ~executing_on_turn,
                    )
                )
            ).all()
            count = 0
            title_keys: list[str] = []
            for turn, conv in rows:
                recovery_key = f"recovery:{ids.generate_turn_key()}"
                cas = await session.execute(
                    update(AssistantConversation)
                    .where(
                        AssistantConversation.id == conv.id,
                        AssistantConversation.active_turn_key == turn.turn_key,
                        AssistantConversation.turn_lease_expires_at < now,
                    )
                    .values(active_turn_key=recovery_key, turn_lease_expires_at=now + timedelta(seconds=30))
                )
                if cas.rowcount == 0:
                    continue
                turn_row = await session.get(AssistantTurn, turn.id)
                if turn_row.status != "running":
                    await _release_lease(session, conversation_id=conv.id, owner_key=recovery_key)
                    continue
                turn_row.status = "failed"
                turn_row.completed_at = now
                turn_row.error_message = "lease expired (orphan turn recovery)"
                error_payload = {
                    "code": "turn_orphaned",
                    "message": "The assistant turn expired before it could finish.",
                }
                eseq = turn_row.next_event_seq
                turn_row.next_event_seq = eseq + 2
                session.add(
                    AssistantEvent(
                        turn_id=turn_row.id,
                        seq=eseq,
                        event_type="error",
                        payload_json=json.dumps(error_payload, ensure_ascii=False),
                    )
                )
                session.add(AssistantEvent(turn_id=turn_row.id, seq=eseq + 1, event_type="done", payload_json=None))
                await _release_admission_once(session, turn=turn_row, user_id=conv.user_id)
                await _release_lease(session, conversation_id=conv.id, owner_key=recovery_key)
                title_key = await self._capture_first_turn_key_for_title(session, turn_row)
                if title_key is not None:
                    title_keys.append(title_key)
                count += 1
            return count, title_keys

        count, title_keys = await self.main_boundary.run_write(_recover)
        for title_key in title_keys:
            _fire_and_forget_title_generation(self, title_key)
        return count

    async def recover_orphan_executing_pending(self) -> int:
        """execution_deadline 已過且對話 lease 也過期的 executing pending → unknown（design D4）。"""

        async def _recover(session: AsyncSession) -> tuple[int, list[str]]:
            now = await _db_now(session)
            title_keys: list[str] = []
            rows = (
                await session.execute(
                    select(AssistantPendingAction, AssistantTurn, AssistantConversation)
                    .join(AssistantTurn, AssistantTurn.id == AssistantPendingAction.turn_id)
                    .join(AssistantConversation, AssistantConversation.id == AssistantTurn.conversation_id)
                    .where(
                        AssistantPendingAction.status == "executing",
                        AssistantPendingAction.execution_deadline < now,
                        AssistantTurn.status == "running",
                        AssistantConversation.active_turn_key == AssistantTurn.turn_key,
                        AssistantConversation.turn_lease_expires_at < now,
                    )
                )
            ).all()
            count = 0
            for action, turn, conv in rows:
                recovery_key = f"recovery:{ids.generate_turn_key()}"
                cas = await session.execute(
                    update(AssistantConversation)
                    .where(
                        AssistantConversation.id == conv.id,
                        AssistantConversation.active_turn_key == turn.turn_key,
                        AssistantConversation.turn_lease_expires_at < now,
                    )
                    .values(active_turn_key=recovery_key, turn_lease_expires_at=now + timedelta(seconds=30))
                )
                if cas.rowcount == 0:
                    continue
                action_claim = await session.execute(
                    update(AssistantPendingAction)
                    .where(
                        AssistantPendingAction.id == action.id,
                        AssistantPendingAction.status == "executing",
                        AssistantPendingAction.execution_deadline < now,
                    )
                    .values(
                        status="unknown",
                        resolved_at=now,
                        execution_payload_json=None,
                    )
                    .execution_options(synchronize_session=False)
                )
                if action_claim.rowcount == 0:
                    await _release_lease(session, conversation_id=conv.id, owner_key=recovery_key)
                    continue
                await session.refresh(action)
                journal = (
                    await session.execute(
                        select(AssistantToolExecution).where(AssistantToolExecution.execution_key == action.execution_key)
                    )
                ).scalar_one_or_none()
                if journal is not None:
                    journal.status = "unknown"
                    journal.finished_at = now
                seq = await self._next_message_seq_in_session(session, turn.id)
                session.add(
                    AssistantMessage(
                        turn_id=turn.id,
                        message_seq=seq,
                        role="tool",
                        content=json.dumps(
                            {"status": "unknown", "code": "execution_orphaned"}, ensure_ascii=False
                        ),
                        llm_tool_call_id=action.llm_tool_call_id,
                        tool_name=action.tool_name,
                    )
                )
                turn_row = await session.get(AssistantTurn, turn.id)
                turn_row.status = "failed"
                turn_row.completed_at = now
                turn_row.error_message = "execution outcome unknown (orphan recovery)"
                eseq = turn_row.next_event_seq
                turn_row.next_event_seq = eseq + 2
                session.add(
                    AssistantEvent(
                        turn_id=turn_row.id,
                        seq=eseq,
                        event_type="tool_finished",
                        payload_json=json.dumps(
                            {
                                "action_id": action.id,
                                "execution_key": action.execution_key,
                                "tool_name": action.tool_name,
                                "status": "unknown",
                                "outcome": "unknown",
                                "http_status": None,
                                "result": {"status": "unknown", "code": "execution_orphaned"},
                            },
                            ensure_ascii=False,
                        ),
                    )
                )
                session.add(AssistantEvent(turn_id=turn_row.id, seq=eseq + 1, event_type="done", payload_json=None))
                await _release_admission_once(session, turn=turn_row, user_id=conv.user_id)
                await _release_lease(session, conversation_id=conv.id, owner_key=recovery_key)
                # 結構上 turn_row 這裡一定是 claim_pending_for_confirm 重新綁定過的 continuation
                # turn（turn_seq >= 1）：pending 進入 executing 前必先被 rebind，turn_seq == 0
                # 的來源 turn 早已在 create_pending_action_and_complete_turn 當下終結並觸發過。
                # 保留這個呼叫僅為與其餘 4 個終結路徑維持一致的寫法，不預期它會產生非 None 結果。
                title_key = await self._capture_first_turn_key_for_title(session, turn_row)
                if title_key is not None:
                    title_keys.append(title_key)
                count += 1
            return count, title_keys

        count, title_keys = await self.main_boundary.run_write(_recover)
        for title_key in title_keys:
            _fire_and_forget_title_generation(self, title_key)
        return count

    async def expire_stale_pending(self) -> int:
        async def _expire(session: AsyncSession) -> int:
            now = await _db_now(session)
            rows = (
                await session.execute(
                    select(AssistantPendingAction).where(
                        AssistantPendingAction.status == "pending", AssistantPendingAction.expires_at < now
                    )
                )
            ).scalars().all()
            for action in rows:
                result = await session.execute(
                    update(AssistantPendingAction)
                    .where(AssistantPendingAction.id == action.id, AssistantPendingAction.status == "pending")
                    .values(status="expired", resolved_at=now, execution_payload_json=None)
                )
                if result.rowcount:
                    seq = await self._next_message_seq_in_session(session, action.turn_id)
                    session.add(
                        AssistantMessage(
                            turn_id=action.turn_id,
                            message_seq=seq,
                            role="tool",
                            content=json.dumps({"status": "expired"}, ensure_ascii=False),
                            llm_tool_call_id=action.llm_tool_call_id,
                            tool_name=action.tool_name,
                        )
                    )
            return len(rows)

        return await self.main_boundary.run_write(_expire)

    async def purge_expired_conversations(self) -> list[str]:
        """刪除超過 `retention_days` 未有新訊息的對話（連同訊息/事件/turns/pending 皆為 cascade delete）；
        存在進行中 turn 或 executing pending 的對話一律跳過（不強制中斷使用者正在進行的操作）。

        回傳被刪除對話的附檔 `relative_path` 清單，供呼叫端（scheduler）刪除實體檔案。"""

        async def _purge(session: AsyncSession) -> list[str]:
            now = await _db_now(session)
            cutoff = now - timedelta(days=self.config.retention_days)
            candidates = (
                (
                    await session.execute(
                        select(AssistantConversation).where(AssistantConversation.last_message_at < cutoff)
                    )
                )
                .scalars()
                .all()
            )
            relative_paths: list[str] = []
            for conv in candidates:
                active_turn = (
                    await session.execute(
                        select(AssistantTurn.id).where(
                            AssistantTurn.conversation_id == conv.id, AssistantTurn.status == "running"
                        )
                    )
                ).scalar_one_or_none()
                if active_turn is not None:
                    continue
                executing_pending = (
                    await session.execute(
                        select(AssistantPendingAction.id)
                        .join(AssistantTurn, AssistantTurn.id == AssistantPendingAction.turn_id)
                        .where(AssistantTurn.conversation_id == conv.id, AssistantPendingAction.status == "executing")
                    )
                ).scalar_one_or_none()
                if executing_pending is not None:
                    continue
                files = (
                    (
                        await session.execute(
                            select(AssistantUploadedFile.relative_path)
                            .join(AssistantTurn, AssistantTurn.id == AssistantUploadedFile.turn_id)
                            .where(AssistantTurn.conversation_id == conv.id)
                        )
                    )
                    .scalars()
                    .all()
                )
                relative_paths.extend(files)
                await session.delete(conv)
            return relative_paths

        return await self.main_boundary.run_write(_purge)

    async def purge_expired_uploaded_files(self) -> list[str]:
        """刪除已逾期（`expires_at` 已過）的附檔 DB rows；回傳其 `relative_path` 供呼叫端刪除實體檔案。

        與 `purge_expired_conversations` 各自獨立：附檔存活期（`upload_retention_hours`，預設 24h）
        遠短於對話存活期（`retention_days`，預設 90 天），需各自到期各自清理。"""

        async def _purge(session: AsyncSession) -> list[str]:
            now = await _db_now(session)
            rows = (
                (
                    await session.execute(
                        select(AssistantUploadedFile).where(AssistantUploadedFile.expires_at < now)
                    )
                )
                .scalars()
                .all()
            )
            relative_paths = [row.relative_path for row in rows]
            for row in rows:
                await session.delete(row)
            return relative_paths

        return await self.main_boundary.run_write(_purge)

    async def purge_expired_rate_limit_buckets(self) -> int:
        async def _purge(session: AsyncSession) -> int:
            now = await _db_now(session)
            result = await session.execute(
                delete(AssistantRateLimitBucket).where(AssistantRateLimitBucket.expires_at < now)
            )
            return result.rowcount or 0

        return await self.main_boundary.run_write(_purge)

    async def reconcile_admission_counters(self) -> None:
        """以 `admission_released=false` turns 為權威集合，重建 global／per-user runtime counters。

        spec assistant-agent-loop：「reconciliation 的權威集合是所有 admission_released=false
        turns；lease 暫時過期本身不得直接扣 counter」——本方法為定期防禦性 backstop，修正因例外路徑
        （非預期崩潰、未覆蓋的錯誤分支等）導致的計數漂移，不做即時強一致性假設。"""

        async def _reconcile(session: AsyncSession) -> None:
            global_count = (
                await session.execute(
                    select(func.count()).select_from(AssistantTurn).where(AssistantTurn.admission_released.is_(False))
                )
            ).scalar_one()
            await session.execute(
                update(AssistantRuntimeCounter)
                .where(AssistantRuntimeCounter.scope_key == GLOBAL_ADMISSION_SCOPE_KEY)
                .values(active_count=global_count)
            )

            per_user_rows = (
                await session.execute(
                    select(AssistantConversation.user_id, func.count())
                    .select_from(AssistantTurn)
                    .join(AssistantConversation, AssistantConversation.id == AssistantTurn.conversation_id)
                    .where(AssistantTurn.admission_released.is_(False))
                    .group_by(AssistantConversation.user_id)
                )
            ).all()
            counts_by_user = {user_id: count for user_id, count in per_user_rows}

            existing_user_scopes = (
                (
                    await session.execute(
                        select(AssistantRuntimeCounter.scope_key).where(
                            AssistantRuntimeCounter.scope_key.like("user:%")
                        )
                    )
                )
                .scalars()
                .all()
            )
            for scope_key in existing_user_scopes:
                user_id = int(scope_key.split(":", 1)[1])
                await session.execute(
                    update(AssistantRuntimeCounter)
                    .where(AssistantRuntimeCounter.scope_key == scope_key)
                    .values(active_count=counts_by_user.get(user_id, 0))
                )

        await self.main_boundary.run_write(_reconcile)
