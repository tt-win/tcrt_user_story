from fastapi import APIRouter, Query, HTTPException, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from datetime import datetime, timezone, timedelta
from typing import Any
import os
import time
import logging
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth.dependencies import require_super_admin
from app.db_access.main import MainAccessBoundary, get_main_access_boundary
from app.models.database_models import TestCaseLocal, TestRunItem, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin")

# 伺服器啟動時間（近似）：模組載入時記錄
_PROCESS_START_TIME = time.time()
_MISSING_TABLE_PATTERNS = (
    "no such table",
    "doesn't exist",
    "does not exist",
    "undefined table",
)


def _is_missing_table_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(pattern in message for pattern in _MISSING_TABLE_PATTERNS)


def _get_loadavg():
    try:
        load1, load5, load15 = os.getloadavg()
        return {"1m": load1, "5m": load5, "15m": load15}
    except Exception:
        return {"1m": None, "5m": None, "15m": None}


def _get_memory_info():
    # 嘗試使用 psutil（若可用）
    try:
        import psutil  # type: ignore
        vm = psutil.virtual_memory()
        proc = psutil.Process()
        rss = proc.memory_info().rss
        return {
            "total": int(vm.total),
            "available": int(vm.available),
            "used": int(vm.used),
            "percent": float(vm.percent),
            "process_rss": int(rss)
        }
    except Exception:
        # 標準庫後備：僅提供 process RSS（若可）
        info = {
            "total": None,
            "available": None,
            "used": None,
            "percent": None,
            "process_rss": None,
        }
        try:
            import resource  # Unix only
            usage = resource.getrusage(resource.RUSAGE_SELF)
            # macOS 與 Linux 的 maxrss 單位不同：
            # Linux: KB；macOS: bytes
            rss = usage.ru_maxrss
            # 嘗試判斷：若值過大則視為 bytes；否則以 KB 轉 bytes
            if rss and rss < 1 << 34:  # 小於 ~16GB 視為 KB
                info["process_rss"] = int(rss * 1024)
            else:
                info["process_rss"] = int(rss)
        except Exception:
            pass
        return info


def _get_cpu_percent():
    try:
        import psutil  # type: ignore
        # 使用 non-blocking 的方式取得當前 CPU 百分比（取上一個計算快照）
        return float(psutil.cpu_percent(interval=None))
    except Exception:
        return None


async def _load_daily_counts(
    *,
    main_boundary: MainAccessBoundary,
    model: type[TestRunItem] | type[TestCaseLocal],
    days: int,
) -> dict[str, list[Any]]:
    since_date = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    day_expr = func.date(model.created_at)

    async def _query(session: AsyncSession) -> list[tuple[Any, int]]:
        result = await session.execute(
            select(day_expr.label("day"), func.count(model.id).label("cnt"))
            .where(day_expr >= since_date)
            .group_by(day_expr)
            .order_by(day_expr.asc())
        )
        return result.all()

    rows = await main_boundary.run_read(_query)
    return {
        "dates": [
            value if isinstance(value, str) else value.isoformat()
            for value, _ in rows
            if value is not None
        ],
        "counts": [int(count) for value, count in rows if value is not None],
    }


@router.get("/system_metrics", include_in_schema=False)
async def system_metrics():
    now = datetime.now(timezone.utc)
    uptime = time.time() - _PROCESS_START_TIME

    payload = {
        "time": now.isoformat(),
        "uptime_seconds": uptime,
        "load": _get_loadavg(),
        "cpu": {"percent": _get_cpu_percent()},
        "memory": _get_memory_info(),
    }
    return JSONResponse(payload)


@router.get("/stats/test_run_actions_daily", include_in_schema=False)
async def stats_test_run_actions_daily(
    current_user: User = Depends(require_super_admin()),
    days: int = Query(30, ge=1, le=90),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    """
    統計過去 N 天（預設 30 天）Test Run 的建立數（依 test_run_items.created_at 日期彙總）。
    僅 super_admin 可存取。
    Returns: { "dates": [...], "counts": [...] }
    """
    try:
        return await _load_daily_counts(
            main_boundary=main_boundary,
            model=TestRunItem,
            days=days,
        )
    except DBAPIError as e:
        if _is_missing_table_error(e):
            logger.warning("資料庫表格 test_run_items 不存在，返回空統計數據")
            return {"dates": [], "counts": []}
        else:
            logger.error(f"統計 Test Run 動作每日數據失敗: {e}")
            raise HTTPException(status_code=500, detail={"error": "無法載入統計數據"})
    except Exception as e:
        logger.error(f"統計 Test Run 動作每日數據失敗: {e}")
        raise HTTPException(status_code=500, detail={"error": "無法載入統計數據"})


@router.get("/stats/test_cases_created_daily", include_in_schema=False)
async def stats_test_cases_created_daily(
    current_user: User = Depends(require_super_admin()),
    days: int = Query(30, ge=1, le=90),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    """
    統計過去 N 天 Test Case 的建立數（依 test_cases.created_at 日期彙總）。
    僅 super_admin 可存取。
    Returns: { "dates": [...], "counts": [...] }
    """
    try:
        return await _load_daily_counts(
            main_boundary=main_boundary,
            model=TestCaseLocal,
            days=days,
        )
    except DBAPIError as e:
        if _is_missing_table_error(e):
            logger.warning("資料庫表格 test_cases 不存在，返回空統計數據")
            return {"dates": [], "counts": []}
        else:
            logger.error(f"統計 Test Case 每日建立數據失敗: {e}")
            raise HTTPException(status_code=500, detail={"error": "無法載入統計數據"})
    except Exception as e:
        logger.error(f"統計 Test Case 每日建立數據失敗: {e}")
        raise HTTPException(status_code=500, detail={"error": "無法載入統計數據"})


# ---------------------------------------------------------------------------
# Super Admin 系統 log viewer（openspec: add-super-admin-log-viewer）
# 實際路徑 /api/admin/system-logs*（admin router 經 api_router 掛於 /api 下）
# ---------------------------------------------------------------------------

_NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_SNAPSHOT_LIMIT_DEFAULT = 500
_SNAPSHOT_LIMIT_MAX = 2000
# per-worker 同時串流數（event loop 單執行緒，無 await 間隙的讀寫改動是安全的）
_active_log_streams = 0


def _redacted(entry: dict) -> dict:
    from app.utils.system_log_buffer import redact_sensitive

    return {**entry, "message": redact_sensitive(entry["message"])}


@router.get("/system-logs", include_in_schema=False)
async def get_system_logs_snapshot(
    level: str | None = Query(None, description="最低 level 門檻（如 WARNING）"),
    logger_prefix: str | None = Query(None, alias="logger", description="logger 名稱前綴"),
    limit: int = Query(_SNAPSHOT_LIMIT_DEFAULT, description="tail 筆數上限（超出即收斂）"),
    current_user: User = Depends(require_super_admin()),
) -> JSONResponse:
    """In-memory log buffer 快照（tail 語意：篩選後取最新 N 筆、依 seq 遞增回傳）。"""
    from app.utils.system_log_buffer import get_system_log_handler

    handler = get_system_log_handler()
    if handler is None:
        raise HTTPException(status_code=503, detail="log viewer 尚未初始化")
    limit = max(1, min(limit, _SNAPSHOT_LIMIT_MAX))
    entries, oldest_seq, latest_seq = handler.snapshot(
        level=level, logger_prefix=logger_prefix, limit=limit
    )
    return JSONResponse(
        content={
            "worker_instance_id": handler.worker_instance_id,
            "pid": os.getpid(),
            "oldest_seq": oldest_seq,
            "latest_seq": latest_seq,
            "entries": [_redacted(e) for e in entries],
        },
        headers=_NO_STORE_HEADERS,
    )


def _sse_frame(event: str, data: dict, seq: int | None = None) -> str:
    import json

    lines = []
    if seq is not None:
        lines.append(f"id: {seq}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"


def _parse_since_seq(raw: str | None) -> int | None:
    """raw string 解析：非整數或負數視為未提供（不得被 FastAPI 提前 422）。"""
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


@router.get("/system-logs/stream", include_in_schema=False)
async def stream_system_logs(
    request: Request,
    since_seq: str | None = Query(None),
    instance_id: str | None = Query(None),
    current_user: User = Depends(require_super_admin()),
) -> StreamingResponse:
    """SSE 即時 log 串流。契約見 openspec specs/system-log-viewer。"""
    import asyncio

    from app.config import settings
    from app.utils.system_log_buffer import get_system_log_handler

    global _active_log_streams
    handler = get_system_log_handler()
    if handler is None:
        raise HTTPException(status_code=503, detail="log viewer 尚未初始化")
    cfg = settings.log_viewer
    if _active_log_streams >= cfg.max_streams:
        raise HTTPException(status_code=429, detail="log 串流連線數已達上限")
    _active_log_streams += 1
    slot_owned = True

    def release_stream_slot() -> None:
        nonlocal slot_owned
        global _active_log_streams
        if slot_owned:
            _active_log_streams -= 1
            slot_owned = False

    cursor = _parse_since_seq(since_seq)
    if instance_id != handler.worker_instance_id:
        cursor = None  # instance 不符或缺 instance_id：忽略 cursor，全量回放

    try:
        try:
            from app.audit import ActionType, AuditSeverity, ResourceType, audit_service

            await audit_service.log_action(
                user_id=current_user.id,
                username=current_user.username,
                role=str(
                    current_user.role.value
                    if hasattr(current_user.role, "value")
                    else current_user.role
                ),
                action_type=ActionType.READ,
                resource_type=ResourceType.SYSTEM,
                resource_id="system-logs-stream",
                team_id=None,
                severity=AuditSeverity.INFO,
                action_brief="開啟系統 log 即時串流",
                details={"worker_instance_id": handler.worker_instance_id, "since_seq": since_seq},
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            )
        except Exception as audit_exc:  # audit 失敗不阻斷串流
            logger.error(f"log viewer audit 寫入失敗: {audit_exc}")

        async def event_stream():
            sub = None
            try:
                sub, replay, replay_latest_seq = handler.subscribe()
                oldest = replay[0]["seq"] if replay else None
                latest = replay[-1]["seq"] if replay else None
                yield _sse_frame(
                    "meta",
                    {
                        "worker_instance_id": handler.worker_instance_id,
                        "pid": os.getpid(),
                        "oldest_seq": oldest,
                        "latest_seq": latest,
                        "buffer_size": cfg.buffer_size,
                        "stream_max_lifetime_seconds": cfg.stream_max_lifetime_seconds,
                    },
                )
                effective_cursor = cursor
                if effective_cursor is not None and latest is not None and effective_cursor > latest:
                    effective_cursor = None  # cursor 超前於伺服器：reset
                if (
                    effective_cursor is not None
                    and oldest is not None
                    and effective_cursor < oldest - 1
                ):
                    yield _sse_frame("gap", {"lost_count": oldest - effective_cursor - 1})
                    effective_cursor = None  # 從 buffer 可用最舊處回放
                for entry in replay:
                    if effective_cursor is None or entry["seq"] > effective_cursor:
                        yield _sse_frame("log", _redacted(entry), seq=entry["seq"])

                deadline = time.monotonic() + cfg.stream_max_lifetime_seconds
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        yield _sse_frame("end", {"reason": "lifetime"})
                        break
                    try:
                        await asyncio.wait_for(
                            sub.wake_event.wait(), timeout=min(cfg.keepalive_seconds, remaining)
                        )
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    for entry in handler.take_batch(sub):
                        if entry["seq"] > replay_latest_seq:  # 與 replay 去重
                            yield _sse_frame("log", _redacted(entry), seq=entry["seq"])
            finally:
                if sub is not None:
                    handler.unsubscribe(sub)
                release_stream_slot()

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={**_NO_STORE_HEADERS, "X-Accel-Buffering": "no"},
        )
    except BaseException:
        release_stream_slot()
        raise
