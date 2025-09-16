from fastapi import APIRouter
from fastapi.responses import JSONResponse
from datetime import datetime, timezone
import os
import time

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