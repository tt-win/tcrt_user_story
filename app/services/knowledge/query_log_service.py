"""知識圖譜 / RAG 查詢記錄寫入器（openspec: log-knowledge-graph-queries）。

設計重點（見 design.md D3 / D6）：

* 純觀測性疊加（fail-safe）：查詢路徑只做 O(1) 緩衝 append，DB 寫入由背景批次
  flush 承擔；任何寫入失敗 MUST NOT 影響查詢行為或 `_record_failure()` 斷路器計數。
* 緩衝 / flush / 清理皆包於廣義 ``try/except``，錯誤僅記錄伺服器 log。
* 保留期清理：跨引擎可攜的時間戳 DELETE（比照 ``cleanup_old_records``），放棄列數
  上限（``DELETE...LIMIT`` 僅 MySQL、``NOT IN`` 觸發 MySQL 1093，皆不可攜）。
* 清理週期性執行且併入同一筆 insert flush 交易，避免在共享 audit SQLite 上多開
  一次檔案級寫鎖交易。
* 查詢路徑上的 ``record()`` 為 ``async`` 但只做 ``await self._buffer.append(...)``
  （asyncio.Lock 保護的 O(1) append），不等待 DB I/O。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from app.audit.database import (
    KnowledgeQueryLogTable,
    KnowledgeQueryOperation,
    KnowledgeQuerySource,
    KnowledgeQueryStatus,
)
from app.config import get_settings
from app.utils.system_log_buffer import redact_sensitive

LOGGER = logging.getLogger(__name__)


def _json_dumps_safe(value: Any) -> str:
    """序列化 JSON；失敗時回傳標準化錯誤字串（避免吞整筆記錄）。"""
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as exc:  # noqa: BLE001
        LOGGER.warning("knowledge_query_log: JSON serialize failed: %s", exc)
        return json.dumps({"error": "serialization_failed"})


def _truncate_chars(text: str, max_chars: int) -> str:
    """超限安全截斷；保留尾部以利人類閱讀。"""
    if not text or max_chars <= 0 or len(text) <= max_chars:
        return text
    suffix = "...[truncated]"
    if max_chars <= len(suffix):
        return text[:max_chars]
    return text[: max_chars - len(suffix)] + suffix


def _cap_size(raw: Optional[str], max_chars: int) -> Optional[str]:
    if raw is None:
        return None
    return _truncate_chars(raw, max_chars)


class KnowledgeQueryLogService:
    """緩衝＋批次 flush 的 knowledge_query_logs 寫入器。"""

    # 背景 flush 週期：每 N 秒檢查一次 buffer；只要 buffer 非空就 flush。
    # 不開放 config 動態調：5s 是「可接受的觀測延遲」與「DB 寫入頻率」的折衷。
    _FLUSH_INTERVAL_SECONDS: float = 5.0

    def __init__(self) -> None:
        self._buffer: list[dict[str, Any]] = []
        self._buffer_lock = asyncio.Lock()
        self._flush_in_progress = False
        self._flush_count_since_cleanup = 0
        self._cleanup_every_n_flushes = 5
        self._closed = False
        # 測試用：強制停用。設為 True 時 is_enabled 一律 False，不讀 settings。
        self._force_disabled: bool = False
        # Background flush task lifecycle。每個 process 應呼叫 start() / stop() 一次
        # （app/main.py startup/shutdown 對稱呼叫）；冪等，重複 start 不會多開 task。
        self._flush_tasks: list[asyncio.Task] = []

    @property
    def is_enabled(self) -> bool:
        if self._force_disabled:
            return False
        s = get_settings()
        if not s.audit.knowledge_query_log_enabled:
            return False
        if not s.audit.enabled:
            return False
        return True

    # ---- 對外 API ----

    async def record(
        self,
        *,
        source: KnowledgeQuerySource | str,
        operation: KnowledgeQueryOperation | str,
        status: KnowledgeQueryStatus | str,
        query_text: Optional[str] = None,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        conversation_id: Optional[str] = None,
        turn_key: Optional[str] = None,
        llm_tool_call_id: Optional[str] = None,
        primary_team_id: Optional[int] = None,
        allowed_team_ids: Optional[list[int]] = None,
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None,
        fallback_recommended: Optional[bool] = None,
        degrade_reason: Optional[str] = None,
        duration_ms: Optional[int] = None,
        result_count: Optional[int] = None,
        process: Optional[dict[str, Any]] = None,
        results_summary: Optional[list[dict[str, Any]]] = None,
        error: Optional[str] = None,
        query_id: Optional[str] = None,
    ) -> None:
        """O(1) 緩衝 append。任何例外 MUST NOT 影響呼叫端。"""
        if not self.is_enabled:
            return
        try:
            config = get_settings().audit
            max_chars = max(0, int(config.knowledge_query_log_max_size_chars))
            sanitized_query = _cap_size(redact_sensitive(query_text or "") or None, max_chars)
            sanitized_error = _cap_size(redact_sensitive(error or "") or None, max_chars)
            sanitized_process = _cap_size(
                _json_dumps_safe(process) if process is not None else None, max_chars
            )
            sanitized_results = _cap_size(
                _json_dumps_safe(self._trim_results(results_summary)) if results_summary else None,
                max_chars,
            )
            sanitized_allowed = (
                _json_dumps_safe([int(t) for t in allowed_team_ids if t is not None])
                if allowed_team_ids
                else None
            )

            entry: dict[str, Any] = {
                "query_id": query_id,
                "source": source.value if isinstance(source, KnowledgeQuerySource) else str(source),
                "operation": operation.value
                if isinstance(operation, KnowledgeQueryOperation)
                else str(operation),
                "status": status.value if isinstance(status, KnowledgeQueryStatus) else str(status),
                "user_id": int(user_id) if user_id is not None else None,
                "username": username,
                "conversation_id": conversation_id,
                "turn_key": turn_key,
                "llm_tool_call_id": llm_tool_call_id,
                "query_text": sanitized_query,
                "primary_team_id": int(primary_team_id) if primary_team_id is not None else None,
                "allowed_team_ids": sanitized_allowed,
                "top_k": int(top_k) if top_k is not None else None,
                "score_threshold": float(score_threshold) if score_threshold is not None else None,
                "fallback_recommended": 1 if fallback_recommended else 0
                if fallback_recommended is not None
                else None,
                "degrade_reason": degrade_reason,
                "duration_ms": int(duration_ms) if duration_ms is not None else None,
                "result_count": int(result_count) if result_count is not None else None,
                "process": sanitized_process,
                "results_summary": sanitized_results,
                "error": sanitized_error,
                "schema_version": 1,
            }
            async with self._buffer_lock:
                self._buffer.append(entry)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("knowledge_query_log: 緩衝 append 失敗，已吞掉：%s", exc, exc_info=True)

    @staticmethod
    def _trim_results(results: Optional[Iterable[dict[str, Any]]]) -> list[dict[str, Any]]:
        """精簡 results：僅留 type/id/title(score-truncated)/score/source/team_id，無全文。"""
        if not results:
            return []
        trimmed: list[dict[str, Any]] = []
        for r in results:
            if not isinstance(r, dict):
                continue
            title = str(r.get("title") or r.get("name") or "")
            trimmed.append(
                {
                    "type": r.get("entity_type") or r.get("type"),
                    "id": r.get("entity_id") or r.get("id"),
                    "title": _truncate_chars(title, 200),
                    "score": r.get("score"),
                    "source": r.get("source"),
                    "team_id": r.get("team_id") or (r.get("metadata") or {}).get("team_id"),
                }
            )
        return trimmed

    async def force_flush(self) -> int:
        """立即 flush 緩衝。Shutdown 路徑呼叫；查詢路徑不應呼叫。"""
        if not self.is_enabled:
            return 0
        try:
            async with self._buffer_lock:
                if not self._buffer:
                    return 0
                if self._flush_in_progress:
                    return 0
                self._flush_in_progress = True
                batch = self._buffer
                self._buffer = []
            try:
                await self._flush_batch(batch)
                return len(batch)
            finally:
                self._flush_in_progress = False
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("knowledge_query_log: force_flush 失敗：%s", exc, exc_info=True)
            return 0

    # ---- Background flush lifecycle ----

    def start(self) -> None:
        """啟動 background periodic flush task。冪等；未 enable 時為 no-op。

        由 ``app/main.py`` 的 startup hook 對每個 worker 各呼叫一次（與
        ``_start_knowledge_graph_sync_workers`` 同層級，不走 leader election），
        因為 ``_buffer`` 是 process-local 的 in-memory 狀態——若只在 leader process
        跑 flush，non-leader worker 收到的查詢會卡在 in-memory 永遠不寫入。
        """
        if self._flush_tasks:
            return
        if not self.is_enabled:
            LOGGER.info("knowledge_query_log: 設定未啟用，跳過 background flush")
            return
        self._flush_tasks = [
            asyncio.create_task(
                self._periodic_flush_loop(), name="knowledge-query-log-flush"
            )
        ]
        LOGGER.info("knowledge_query_log: background flush task 啟動（週期 %.1fs）",
                    self._FLUSH_INTERVAL_SECONDS)

    async def stop(self) -> None:
        """停止 background flush task 並做最後一次 force_flush。"""
        for task in self._flush_tasks:
            task.cancel()
        for task in self._flush_tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._flush_tasks = []
        if self.is_enabled:
            flushed = await self.force_flush()
            if flushed:
                LOGGER.info("knowledge_query_log: stop() 收尾 flush %d 筆", flushed)

    async def _periodic_flush_loop(self) -> None:
        """每 N 秒呼叫一次 _maybe_flush()；CancelledError 時安靜退出。"""
        try:
            while True:
                await asyncio.sleep(self._FLUSH_INTERVAL_SECONDS)
                try:
                    await self._maybe_flush()
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning(
                        "knowledge_query_log: periodic flush 失敗：%s", exc, exc_info=True
                    )
        except asyncio.CancelledError:
            return

    async def _maybe_flush(self) -> None:
        """緩衝非空就 flush。

        背景 flush task 週期性呼叫此方法；只要 buffer 有任何紀錄就一次寫入，
        避免「使用者只查 1 筆但 batch_size 預設 50 導致永遠看不到」的情境。
        ``knowledge_query_log_batch_size`` 仍會在 ``_flush_batch`` 內一次處理
        上限筆數（單次 transaction 大小），但不作為「是否觸發 flush」的門檻。
        """
        if not self.is_enabled:
            return
        try:
            async with self._buffer_lock:
                if self._flush_in_progress:
                    return
                if not self._buffer:
                    return
                self._flush_in_progress = True
                batch = self._buffer
                self._buffer = []
            try:
                await self._flush_batch(batch)
            finally:
                self._flush_in_progress = False
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("knowledge_query_log: 背景 flush 失敗：%s", exc, exc_info=True)
            self._flush_in_progress = False

    async def _flush_batch(self, batch: list[dict[str, Any]]) -> None:
        if not batch:
            return
        config = get_settings().audit
        # 透過模組查找而非直接 import，確保測試 monkeypatch
        # app.audit.database.get_audit_session 能在這裡生效。
        from app.audit.database import get_audit_session

        try:
            async with get_audit_session() as session:
                records = []
                for entry in batch:
                    try:
                        record = KnowledgeQueryLogTable(timestamp=datetime.utcnow(), **entry)
                        records.append(record)
                    except Exception as exc:  # noqa: BLE001
                        LOGGER.warning(
                            "knowledge_query_log: 建立 record 失敗已跳過：%s", exc, exc_info=True
                        )
                if records:
                    session.add_all(records)
                self._flush_count_since_cleanup += 1
                # 週期性且併入同一筆 insert flush 交易
                if self._flush_count_since_cleanup >= self._cleanup_every_n_flushes:
                    deleted = await self._cleanup_old_records(session, config)
                    if deleted:
                        LOGGER.debug("knowledge_query_log: 保留期清理刪除 %d 筆", deleted)
                    self._flush_count_since_cleanup = 0
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("knowledge_query_log: flush 寫入失敗：%s", exc, exc_info=True)
            # 失敗的記錄放回緩衝（最多 max_buffer_size 筆），避免審計 DB 持續故障時無限增長
            try:
                async with self._buffer_lock:
                    merged = batch + self._buffer
                    cap = max(1, config.max_buffer_size)
                    if len(merged) > cap:
                        dropped = len(merged) - cap
                        merged = merged[-cap:]
                        LOGGER.warning(
                            "knowledge_query_log: 重排緩衝已達上限 %d，丟棄最舊 %d 筆",
                            cap,
                            dropped,
                        )
                    self._buffer = merged
            except Exception:  # noqa: BLE001
                pass

    async def _cleanup_old_records(self, session, config) -> int:
        """跨引擎可攜的時間戳 DELETE（避免 DELETE...LIMIT / NOT IN 子查詢）。"""
        if config.knowledge_query_log_retention_days <= 0:
            return 0
        cutoff = datetime.utcnow() - timedelta(days=config.knowledge_query_log_retention_days)
        try:
            from sqlalchemy import delete

            stmt = delete(KnowledgeQueryLogTable.__table__).where(
                KnowledgeQueryLogTable.timestamp < cutoff
            )
            result = await session.execute(stmt)
            return int(getattr(result, "rowcount", 0) or 0)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("knowledge_query_log: 保留期清理失敗：%s", exc, exc_info=True)
            return 0


# 模組層級 singleton accessor
_instance: Optional[KnowledgeQueryLogService] = None


def get_query_log_service() -> KnowledgeQueryLogService:
    global _instance
    if _instance is None:
        _instance = KnowledgeQueryLogService()
    return _instance


def reset_query_log_service_for_test() -> None:
    global _instance
    _instance = None
