"""共用 SQLite 連線 PRAGMA 設定。

供各資料庫模組（主庫同步/異步、audit、USM）的 ``connect`` event listener 呼叫，
避免四份幾乎相同的 PRAGMA 清單各自漂移。呼叫端需自行判斷該 engine 的 dialect
是否為 sqlite 後才呼叫本函式（各模組取得 dialect 的方式略有差異，故不在此處理）。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_PRAGMAS = (
    "PRAGMA journal_mode=WAL",  # 啟用 WAL 模式以改善並發
    "PRAGMA busy_timeout=30000",  # 設定 busy timeout 為 30 秒
    "PRAGMA synchronous=NORMAL",  # 同步模式 NORMAL（平衡性能與安全）
    "PRAGMA foreign_keys=ON",  # 啟用外鍵約束
    "PRAGMA cache_size=-64000",  # 優化記憶體使用（64MB cache）
    "PRAGMA temp_store=MEMORY",  # temp store 設在記憶體中
)


def apply_sqlite_pragma(dbapi_connection, *, label: str) -> None:
    """在 SQLite connect event 內套用統一的效能/安全 PRAGMA。"""
    cursor = dbapi_connection.cursor()
    try:
        for pragma in _PRAGMAS:
            cursor.execute(pragma)
        logger.debug(f"{label} SQLite 優化參數設定完成")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"{label} 設定 SQLite PRAGMA 失敗: {exc}")
    finally:
        cursor.close()
