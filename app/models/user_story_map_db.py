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
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os

Base = declarative_base()


class UserStoryMapDB(Base):
    """User Story Map 表格"""
    __tablename__ = "user_story_maps"
    __table_args__ = {"sqlite_autoincrement": True}

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
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True)
    map_id = Column(Integer, ForeignKey("user_story_maps.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id = Column(String(100), nullable=False, index=True)
    title = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    node_type = Column(String(50), nullable=False, index=True)
    parent_id = Column(String(100), nullable=True, index=True)
    children_ids = Column(JSON, default=list)
    related_ids = Column(JSON, default=list)
    comment = Column(Text, nullable=True)
    jira_tickets = Column(JSON, default=list)
    product = Column(String(255), nullable=True, index=True)
    team = Column(String(255), nullable=True, index=True)
    position_x = Column(Float, default=0)
    position_y = Column(Float, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# Database setup
DATABASE_DIR = "data"
DATABASE_PATH = os.path.join(DATABASE_DIR, "userstorymap.db")
DATABASE_URL = f"sqlite+aiosqlite:///{DATABASE_PATH}"

# Create async engine
usm_engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)

# Create session factory
USMAsyncSessionLocal = sessionmaker(
    usm_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_usm_db():
    """初始化 User Story Map 資料庫"""
    # 確保資料目錄存在
    os.makedirs(DATABASE_DIR, exist_ok=True)
    
    async with usm_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_usm_db():
    """獲取 User Story Map 資料庫 session"""
    async with USMAsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
