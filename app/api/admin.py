from fastapi import APIRouter, Query, HTTPException, Depends
from fastapi.responses import JSONResponse
from datetime import datetime, timezone, timedelta, date
import os
import time
import logging
import sqlite3
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import SessionLocal
from app.auth.dependencies import require_super_admin
from app.models.database_models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin")

# 伺服器啟動時間（近似）：模組載入時記錄
_PROCESS_START_TIME = time.time()


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
    days: int = Query(30, ge=1, le=90)
):
    """
    統計過去 N 天（預設 30 天）Test Run 的建立數（依 test_run_items.created_at 日期彙總）。
    僅 super_admin 可存取。
    Returns: { "dates": [...], "counts": [...] }
    """
    try:
        since_dt = datetime.now(timezone.utc) - timedelta(days=days)
        since_date_str = since_dt.date().isoformat()

        async with SessionLocal() as session:
            q = text(
                """
                SELECT date(created_at) AS day,
                       COUNT(*) AS cnt
                FROM test_run_items
                WHERE date(created_at) >= :since_date
                GROUP BY day
                ORDER BY day ASC
                """
            )
            result = await session.execute(q, {"since_date": since_date_str})
            rows = result.all()
            dates = [r[0] for r in rows]
            counts = [int(r[1]) for r in rows]
            return {
                "dates": dates,
                "counts": counts
            }
    except sqlite3.OperationalError as e:
        if "no such table" in str(e).lower():
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
    days: int = Query(30, ge=1, le=90)
):
    """
    統計過去 N 天 Test Case 的建立數（依 test_cases.created_at 日期彙總）。
    僅 super_admin 可存取。
    Returns: { "dates": [...], "counts": [...] }
    """
    try:
        since_dt = datetime.now(timezone.utc) - timedelta(days=days)
        since_date_str = since_dt.date().isoformat()

        async with SessionLocal() as session:
            q = text(
                """
                SELECT date(created_at) AS day,
                       COUNT(*) AS cnt
                FROM test_cases
                WHERE date(created_at) >= :since_date
                GROUP BY day
                ORDER BY day ASC
                """
            )
            result = await session.execute(q, {"since_date": since_date_str})
            rows = result.all()
            dates = [r[0] for r in rows]
            counts = [int(r[1]) for r in rows]
            return {
                "dates": dates,
                "counts": counts
            }
    except sqlite3.OperationalError as e:
        if "no such table" in str(e).lower():
            logger.warning("資料庫表格 test_cases 不存在，返回空統計數據")
            return {"dates": [], "counts": []}
        else:
            logger.error(f"統計 Test Case 每日建立數據失敗: {e}")
            raise HTTPException(status_code=500, detail={"error": "無法載入統計數據"})
    except Exception as e:
        logger.error(f"統計 Test Case 每日建立數據失敗: {e}")
        raise HTTPException(status_code=500, detail={"error": "無法載入統計數據"})
