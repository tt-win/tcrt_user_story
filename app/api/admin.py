from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import JSONResponse
from datetime import datetime, timezone, timedelta
import os
import time
from sqlalchemy import text
from app.database import SessionLocal

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
async def stats_test_run_actions_daily(days: int = Query(30, ge=1, le=90)):
    """
    統計過去 N 天（預設 30 天）Test Run 的操作次數（來自結果歷程表），依 team 與日期彙總。
    """
    since_dt = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since_dt.isoformat()

    session = SessionLocal()
    try:
        # 取得團隊名稱映射
        teams = session.execute(text("SELECT id, name FROM teams")).all()
        team_map = {int(r[0]): r[1] for r in teams}

        # 依日期與 team 統計（SQLite 的 DATE() 會以本地時區計算；此處使用 substr 取 ISO 日期部分）
        q = text(
            """
            SELECT team_id,
                   substr(changed_at, 1, 10) AS day,
                   COUNT(*) AS cnt
            FROM test_run_item_result_history
            WHERE changed_at >= :since
            GROUP BY team_id, day
            ORDER BY day ASC, team_id ASC
            """
        )
        rows = session.execute(q, {"since": since_iso}).all()
        data = [
            {"team_id": int(r[0]) if r[0] is not None else None,
             "team_name": team_map.get(int(r[0])) if r[0] is not None else None,
             "day": r[1],
             "count": int(r[2])} for r in rows
        ]
        return JSONResponse({
            "since": since_iso,
            "days": days,
            "data": data,
            "teams": team_map,
        })
    finally:
        session.close()


@router.get("/stats/test_cases_created_daily", include_in_schema=False)
async def stats_test_cases_created_daily(days: int = Query(30, ge=1, le=90)):
    """
    統計過去 N 天各 team 的 Test Case 新增數量（依 created_at 日期彙總）。
    資料表：test_cases(team_id, created_at)
    """
    since_dt = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since_dt.isoformat()

    session = SessionLocal()
    try:
        teams = session.execute(text("SELECT id, name FROM teams")).all()
        team_map = {int(r[0]): r[1] for r in teams}

        q = text(
            """
            SELECT team_id,
                   substr(created_at, 1, 10) AS day,
                   COUNT(*) AS cnt
            FROM test_cases
            WHERE created_at >= :since
            GROUP BY team_id, day
            ORDER BY day ASC, team_id ASC
            """
        )
        rows = session.execute(q, {"since": since_iso}).all()
        data = [
            {"team_id": int(r[0]) if r[0] is not None else None,
             "team_name": team_map.get(int(r[0])) if r[0] is not None else None,
             "day": r[1],
             "count": int(r[2])} for r in rows
        ]
        return JSONResponse({
            "since": since_iso,
            "days": days,
            "data": data,
            "teams": team_map,
        })
    finally:
        session.close()
