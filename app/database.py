"""
異步資料庫連接模組

將主資料庫升級為異步 aiosqlite，改善 SQLite 並發與鎖定問題。
統一使用異步模式，避免同步/異步混用導致的連接衝突。
"""

import logging
from pathlib import Path
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool
from sqlalchemy import event, text
from contextlib import asynccontextmanager

# 向後相容：保留同步接口供緊急使用
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

# 使用與現有資料庫相同的路徑
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_FILE = PROJECT_ROOT / "test_case_repo.db"
DATABASE_URL = f"sqlite+aiosqlite:///{DB_FILE}"
SYNC_DATABASE_URL = f"sqlite:///{DB_FILE}"  # 向後相容

# ===================== 異步資料庫引擎（主要使用） =====================

# 創建異步引擎
engine = create_async_engine(
    DATABASE_URL,
    poolclass=NullPool,  # SQLite 使用 NullPool
    echo=False,  # 可設為 True 用於調試
    future=True,
    connect_args={
        "check_same_thread": False,
    }
)

# 異步會話工廠
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False
)

# SQLAlchemy Base
Base = declarative_base()

# SQLite 優化參數設定（異步版本）
@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    """為異步連接設定 SQLite 優化參數"""
    cursor = dbapi_conn.cursor()
    try:
        # 啟用 WAL 模式以改善並發
        cursor.execute("PRAGMA journal_mode=WAL")
        # 設定 busy timeout 為 30 秒
        cursor.execute("PRAGMA busy_timeout=30000")
        # 設定同步模式為 NORMAL（平衡性能與安全）
        cursor.execute("PRAGMA synchronous=NORMAL")
        # 啟用外鍵約束
        cursor.execute("PRAGMA foreign_keys=ON")
        # 優化記憶體使用
        cursor.execute("PRAGMA cache_size=-64000")  # 64MB cache
        # 設定 temp store 在記憶體中
        cursor.execute("PRAGMA temp_store=MEMORY")
        logger.debug("SQLite 異步連接優化參數設定完成")
    finally:
        cursor.close()


# ===================== 異步會話管理 =====================

@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """取得異步資料庫會話"""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception as e:
            logger.error(f"資料庫會話錯誤: {e}")
            await session.rollback()
            raise
        finally:
            await session.close()


# FastAPI 異步依賴注入
async def get_db():
    """FastAPI 依賴注入用的異步會話生成器"""
    async with get_async_session() as session:
        yield session


# ===================== 資料庫管理函數 =====================

async def cleanup_database() -> None:
    """清理異步資料庫連接"""
    await engine.dispose()
    logger.info("異步資料庫連接已清理")


async def health_check() -> bool:
    """異步資料庫健康檢查"""
    try:
        async with get_async_session() as session:
            result = await session.execute(text("SELECT 1"))
            return result.scalar() == 1
    except Exception as e:
        logger.error(f"異步資料庫健康檢查失敗: {e}")
        return False


async def execute_raw_sql(sql: str, params: dict = None) -> any:
    """執行原始 SQL（異步版本）"""
    async with get_async_session() as session:
        result = await session.execute(text(sql), params or {})
        await session.commit()
        return result


# ===================== 向後相容性支援 =====================

# 同步引擎（僅供緊急向後相容使用）
_sync_engine = None
_SyncSessionLocal = None

def get_sync_engine():
    """取得同步引擎（向後相容）"""
    global _sync_engine, _SyncSessionLocal
    try:
        from sqlalchemy.engine import Engine as _SyncType
        if _sync_engine is not None and isinstance(engine, _SyncType) and _sync_engine is not engine:  # type: ignore[name-defined]
            # 若先前已建立但測試期間替換了 engine，則切換到新的同步 engine
            _sync_engine = engine  # type: ignore[assignment]
            _SyncSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_sync_engine)
            return _sync_engine
    except Exception:
        pass

    if _sync_engine is None:
        # 測試友善：若有人以 monkeypatch 將本模組的 engine（通常為異步引擎）替換成同步 Engine，則直接沿用
        try:
            from sqlalchemy.engine import Engine as _SyncType
            # 這裡的 `engine` 變數是本模組頂層變數，測試可 monkeypatch 為同步 Engine
            if isinstance(engine, _SyncType):  # type: ignore[name-defined]
                _sync_engine = engine  # type: ignore[assignment]
                _SyncSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_sync_engine)
                return _sync_engine
        except Exception:
            pass

        _sync_engine = create_engine(
            SYNC_DATABASE_URL,
            connect_args={
                "check_same_thread": False,
                "timeout": 30
            },
            pool_pre_ping=True,
            pool_recycle=3600
        )
        _SyncSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_sync_engine)
        
        # 同步版本的 PRAGMA 設定
        @event.listens_for(_sync_engine, "connect")
        def set_sync_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
            
    return _sync_engine


def get_sync_db():
    """同步版本的會話生成器（向後相容）"""
    engine = get_sync_engine()
    db = _SyncSessionLocal()
    try:
        yield db
    finally:
        db.close()


# ===================== 模組初始化 =====================

# 添加必要的導入
import asyncio

# 在模組載入時記錄模式
logger.info("資料庫模組已升級為異步模式（aiosqlite）")
