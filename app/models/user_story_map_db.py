"""
User Story Map 資料庫模型

獨立的資料庫 (userstorymap.db) 用於存儲 User Story Map 資料
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    Float,
    JSON,
    event,
    text,
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from datetime import datetime
import logging

from app.config import get_settings
from app.db_url import normalize_async_database_url

Base = declarative_base()


class UserStoryMapDB(Base):
    """User Story Map 表格"""
    __tablename__ = "user_story_maps"

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    nodes = Column(JSON, default=list)  # 存儲節點資料
    edges = Column(JSON, default=list)  # 存儲連接線資料
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserStoryMapNodeDB(Base):
    """User Story Map 節點表格 (用於搜尋)"""
    __tablename__ = "user_story_map_nodes"

    id = Column(Integer, primary_key=True)
    map_id = Column(Integer, ForeignKey("user_story_maps.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id = Column(String(100), nullable=False, index=True)
    title = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    node_type = Column(String(50), nullable=True, index=True)
    parent_id = Column(String(100), nullable=True, index=True)
    children_ids = Column(JSON, default=list)
    related_ids = Column(JSON, default=list)
    comment = Column(Text, nullable=True)
    jira_tickets = Column(JSON, default=list)
    product = Column(String(255), nullable=True, index=True)
    team = Column(String(255), nullable=True, index=True)
    team_tags = Column(JSON, default=list)
    aggregated_tickets = Column(JSON, default=list)
    position_x = Column(Float, default=0)
    position_y = Column(Float, default=0)
    level = Column(Integer, default=0)
    # BDD fields for User Story nodes
    as_a = Column(Text, nullable=True)  # As a
    i_want = Column(Text, nullable=True)  # I want
    so_that = Column(Text, nullable=True)  # So that
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# Database setup
DATABASE_URL = normalize_async_database_url(get_settings().usm.database_url)

_usm_engine_kwargs = {
    "echo": get_settings().usm.debug_sql,
}
if DATABASE_URL.startswith("sqlite+aiosqlite://"):
    _usm_engine_kwargs.update(
        poolclass=NullPool,
        connect_args={
            "check_same_thread": False,
            "timeout": 30,
        },
    )
else:
    _usm_engine_kwargs.update(
        pool_pre_ping=True,
        pool_recycle=3600,
    )

# Create async engine with proper SQLite configuration
usm_engine = create_async_engine(DATABASE_URL, **_usm_engine_kwargs)

# Create session factory
USMAsyncSessionLocal = sessionmaker(
    usm_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# SQLite 優化參數設定（異步版本）
@event.listens_for(usm_engine.sync_engine, "connect")
def set_usm_sqlite_pragma(dbapi_conn, connection_record):
    """為 USM 數據庫異步連接設定 SQLite 優化參數"""
    if usm_engine.sync_engine.dialect.name != "sqlite":
        return
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
        logging.debug("SQLite USM 數據庫優化參數設定完成")
    except Exception as e:
        logging.warning(f"設定 USM SQLite PRAGMA 失敗: {e}")
    finally:
        cursor.close()

async def init_usm_db():
    """初始化 User Story Map 資料庫連線；schema 由 migration 管理"""
    async with usm_engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def get_usm_db():
    """獲取 User Story Map 資料庫 session"""
    async with USMAsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
