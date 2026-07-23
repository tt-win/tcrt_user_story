"""Super Admin 系統 log viewer 的 in-memory 捕捉層。

以額外 handler 旁路複製 log record 進有界 ring buffer，stdout 輸出完全不受影響。
並行模型（見 openspec design D1）：
- 單一 threading.Lock 保護 buffer、seq 配號與訂閱者 registry。
- 跨 thread 投遞採「有界 pending deque + 合併喚醒」：emit() 直接 append pending，
  僅在 wakeup_scheduled False→True 時排程一次 call_soon_threadsafe(wake_event.set)；
  callback 不搬資料，generator 醒來後在同一 critical section 自取 batch。
- emit() 永不拋出、不呼叫 logging（防遞迴）。
"""

import asyncio
import logging
import os
import re
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import List, Optional, Tuple

TRUNCATION_MARKER = "…[truncated]"
REDACTION_MARKER = "***REDACTED***"

# Secret field names for redaction - each as a word with boundaries to avoid
# false matches like "token" inside "automation.run.cancel"
_SECRET_FIELD_NAMES = r"password|secret|api_key|access_token|refresh_token|client_secret|token|authorization"
# Build word-boundary pattern: \b(?:password|secret|...)\b
_SECRET_FIELD_NAMES_WB = r"\b(?:" + _SECRET_FIELD_NAMES + r")\b"

# Quoted JSON / Python repr values must be consumed through their closing quote so
# whitespace cannot leave a plaintext suffix behind. Unquoted env/query values keep
# the narrower delimiter set to avoid redacting the rest of an unrelated log line.
_DOUBLE_QUOTED_ASSIGNMENT_RE = re.compile(
    r'(?P<prefix>"?' + _SECRET_FIELD_NAMES_WB + r'"?\s*[=:]\s*)"(?:\\.|[^"\\])*"',
    re.IGNORECASE,
)
_SINGLE_QUOTED_ASSIGNMENT_RE = re.compile(
    r"(?P<prefix>'?" + _SECRET_FIELD_NAMES_WB + r"'?\s*[=:]\s*)'(?:\\.|[^'\\])*'",
    re.IGNORECASE,
)
_UNQUOTED_ASSIGNMENT_RE = re.compile(
    r"(?P<prefix>['\"]?" + _SECRET_FIELD_NAMES_WB + r"['\"]?\s*[=:]\s*)(?P<value>[^'\"\s&,;]+)",
    re.IGNORECASE,
)
_AUTHORIZATION_SCHEME_RE = re.compile(
    r"(?P<prefix>\bauthorization\s*[=:]\s*)(?:[A-Za-z][A-Za-z0-9_-]*\s+)?[^\s&,;]+",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9\-._~+/=]+", re.IGNORECASE)
# JWT: three base64url parts separated by dots, not part of longer dot sequence
# JWT: three base64url parts separated by dots
# Exclude all-lowercase three-part patterns (like "automation.run.cancel")
# Real JWTs have mixed case, digits, or base64url encoding
_JWT_RE = re.compile(
    r"(?<!\.)\b(?!([a-z]+\.){2}[a-z]+\b)[A-Za-z0-9_-]{3,}\.[A-Za-z0-9_-]{3,}\.[A-Za-z0-9_-]{3,}\b(?!\.)"
)

# Pattern to extract event_code and outcome from structured log suffix
# Format: " | event=tcrt.ops.xxx outcome=success key=value ..."
_EVENT_SUFFIX_RE = re.compile(r" \|\s*(.+)$")
_EVENT_KV_RE = re.compile(r"(\w+)=([^\s]+)")


def _parse_event_suffix(message: str) -> tuple[Optional[str], Optional[str]]:
    """Parse event_code and outcome from structured log message suffix.
    
    Expected suffix format: " | event=tcrt.xxx outcome=success key=value ..."
    Returns (event_code, outcome) or (None, None) if not present.
    """
    match = _EVENT_SUFFIX_RE.search(message)
    if not match:
        return None, None
    suffix = match.group(1)
    pairs = _EVENT_KV_RE.findall(suffix)
    d = dict(pairs)
    return d.get("event"), d.get("outcome")


def redact_sensitive(text: str) -> str:
    """輸出前遮罩疑似 secret 片段（buffer 內保留原文，僅讀取路徑付費）。"""
    text = _DOUBLE_QUOTED_ASSIGNMENT_RE.sub(
        lambda m: f'{m.group("prefix")}"{REDACTION_MARKER}"', text
    )
    text = _SINGLE_QUOTED_ASSIGNMENT_RE.sub(
        lambda m: f"{m.group('prefix')}'{REDACTION_MARKER}'", text
    )
    text = _BEARER_RE.sub(f"Bearer {REDACTION_MARKER}", text)
    text = _AUTHORIZATION_SCHEME_RE.sub(
        lambda m: f"{m.group('prefix')}{REDACTION_MARKER}", text
    )
    text = _UNQUOTED_ASSIGNMENT_RE.sub(
        lambda m: f"{m.group('prefix')}{REDACTION_MARKER}", text
    )
    text = _JWT_RE.sub(REDACTION_MARKER, text)
    return text


class Subscriber:
    """單一 SSE 連線的訂閱狀態；pending deque 是唯一共享緩衝。"""

    def __init__(self, loop: asyncio.AbstractEventLoop, queue_size: int):
        self.loop = loop
        self.pending: deque = deque(maxlen=queue_size)
        self.wake_event = asyncio.Event()
        self.wakeup_scheduled = False
        self.dead = False


class RingBufferLogHandler(logging.Handler):
    def __init__(self, buffer_size: int, max_message_chars: int, subscriber_queue_size: int):
        super().__init__()
        self.setFormatter(logging.Formatter("%(message)s"))
        self._lock = threading.Lock()
        self._buffer: deque = deque(maxlen=buffer_size)
        self._seq = 0
        self._subscribers: set = set()
        self._max_message_chars = max_message_chars
        self._subscriber_queue_size = subscriber_queue_size
        self.worker_instance_id = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"

    # ---- 捕捉（任意 thread） ----

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
        try:
            message = self.format(record)  # 含 exc_info traceback 與多行
            if len(message) > self._max_message_chars:
                message = message[: self._max_message_chars] + TRUNCATION_MARKER
            entry = {
                "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
                    timespec="milliseconds"
                ),
                "level": record.levelname,
                "logger_name": record.name,
                "message": message,
                "pid": os.getpid(),
            }
            dead_subscribers = []
            with self._lock:
                self._seq += 1
                entry["seq"] = self._seq
                self._buffer.append(entry)
                for sub in self._subscribers:
                    sub.pending.append(entry)  # deque maxlen：滿即淘汰最舊未投遞筆
                    if not sub.wakeup_scheduled:
                        sub.wakeup_scheduled = True
                        try:
                            sub.loop.call_soon_threadsafe(sub.wake_event.set)
                        except RuntimeError:
                            dead_subscribers.append(sub)
                for sub in dead_subscribers:
                    self._subscribers.discard(sub)
        except Exception:
            # 捕捉層故障只能導致 viewer 缺資料，不得影響 log 呼叫端
            pass

    # ---- 查詢／訂閱（event loop） ----

    def seq_range(self) -> Tuple[Optional[int], Optional[int]]:
        with self._lock:
            if not self._buffer:
                return None, None
            return self._buffer[0]["seq"], self._buffer[-1]["seq"]

    def snapshot(
        self,
        level: Optional[str] = None,
        logger_prefix: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Tuple[List[dict], Optional[int], Optional[int]]:
        """一致性快照；limit 為 tail 語意（取最新 N 筆後依 seq 遞增回傳）。"""
        with self._lock:
            entries = list(self._buffer)
            oldest = entries[0]["seq"] if entries else None
            latest = entries[-1]["seq"] if entries else None
        if level:
            min_levelno = logging._nameToLevel.get(level.upper())
            if min_levelno is not None:
                entries = [
                    e for e in entries
                    if logging._nameToLevel.get(e["level"], 0) >= min_levelno
                ]
        if logger_prefix:
            entries = [e for e in entries if e["logger_name"].startswith(logger_prefix)]
        if limit is not None and len(entries) > limit:
            entries = entries[-limit:]
        return entries, oldest, latest

    def subscribe(self) -> Tuple[Subscriber, List[dict], int]:
        """原子化訂閱：註冊 pending + 複製 replay snapshot + 記 replay_latest_seq
        於同一 critical section 完成，保證訂閱瞬間的 log 無遺失、無重複。"""
        sub = Subscriber(asyncio.get_running_loop(), self._subscriber_queue_size)
        with self._lock:
            replay = list(self._buffer)
            replay_latest_seq = self._seq
            self._subscribers.add(sub)
        return sub, replay, replay_latest_seq

    def unsubscribe(self, sub: Subscriber) -> None:
        with self._lock:
            sub.dead = True
            self._subscribers.discard(sub)

    def take_batch(self, sub: Subscriber) -> List[dict]:
        """generator 醒來後自取 batch；flag/event/pending 狀態轉換在同一 critical section。"""
        with self._lock:
            batch = list(sub.pending)
            sub.pending.clear()
            sub.wake_event.clear()
            sub.wakeup_scheduled = False
        return batch

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


_handler: Optional[RingBufferLogHandler] = None
_UVICORN_LOGGERS = ("uvicorn.access", "uvicorn.error")


def install_system_log_handler(
    buffer_size: int, max_message_chars: int, subscriber_queue_size: int
) -> RingBufferLogHandler:
    """掛載到 root logger 與 uvicorn loggers；idempotent，重複呼叫不重複捕捉。"""
    global _handler
    if _handler is None:
        _handler = RingBufferLogHandler(buffer_size, max_message_chars, subscriber_queue_size)
    _attach(logging.getLogger(), _handler)
    for name in _UVICORN_LOGGERS:
        logger = logging.getLogger(name)
        # uvicorn logger 若 propagate 到 root 就不另掛，避免重複捕捉
        if not _propagates_to_root(logger):
            _attach(logger, _handler)
        else:
            _detach(logger, _handler)
    return _handler


def _attach(logger: logging.Logger, handler: RingBufferLogHandler) -> None:
    if not any(isinstance(h, RingBufferLogHandler) for h in logger.handlers):
        logger.addHandler(handler)


def _detach(logger: logging.Logger, handler: RingBufferLogHandler) -> None:
    for h in list(logger.handlers):
        if isinstance(h, RingBufferLogHandler):
            logger.removeHandler(h)


def _propagates_to_root(logger: logging.Logger) -> bool:
    current = logger
    while current.propagate and current.parent is not None:
        current = current.parent
    return current is logging.getLogger()


def get_system_log_handler() -> Optional[RingBufferLogHandler]:
    return _handler


def reset_system_log_handler() -> None:
    """測試用：卸載並清除單例。"""
    global _handler
    if _handler is not None:
        _detach(logging.getLogger(), _handler)
        for name in _UVICORN_LOGGERS:
            _detach(logging.getLogger(name), _handler)
    _handler = None
