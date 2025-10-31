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
import logging

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
DATABASE_PATH = "userstorymap.db"

# 使用絕對路徑
import os as _os
_ABSOLUTE_DB_PATH = _os.path.abspath(DATABASE_PATH)
DATABASE_URL = f"sqlite+aiosqlite:///{_ABSOLUTE_DB_PATH}"

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


def _ensure_node_type_nullable(connection):
    """確保 node_type 欄位允許 NULL，以移除舊的 NOT NULL 約束"""
    try:
        result = connection.exec_driver_sql("PRAGMA table_info(user_story_map_nodes)")
        rows = result.fetchall()
    except Exception as exc:
        logging.warning("無法檢查 user_story_map_nodes 欄位資訊: %s", exc)
        return

    node_type_info = None
    for row in rows:
        # PRAGMA 回傳格式: (cid, name, type, notnull, dflt_value, pk)
        name = row[1] if len(row) > 1 else None
        if name == "node_type":
            node_type_info = row
            break

    if not node_type_info:
        return

    notnull_flag = node_type_info[3] if len(node_type_info) > 3 else 0
    if notnull_flag == 0:
        return

    logging.info("調整 user_story_map_nodes.node_type 欄位為可為 NULL")

    # 獲取現有表格的欄位
    result = connection.exec_driver_sql("PRAGMA table_info(user_story_map_nodes__legacy)")
    existing_columns = [row[1] for row in result.fetchall()]  # row[1] 是欄位名稱

    # 建立欄位映射，為新欄位提供默認值
    select_columns = []
    insert_columns = []
    for column in UserStoryMapNodeDB.__table__.columns:
        insert_columns.append(column.name)
        if column.name in existing_columns:
            select_columns.append(column.name)
        else:
            # 為新欄位提供默認值
            if column.name in ['children_ids', 'related_ids', 'jira_tickets', 'team_tags', 'aggregated_tickets']:
                select_columns.append("'[]'")  # JSON array default
            elif column.name in ['position_x', 'position_y', 'level']:
                select_columns.append("'0'")  # Numeric defaults
            elif column.name in ['created_at', 'updated_at']:
                select_columns.append("datetime('now')")  # Current timestamp
            else:
                select_columns.append("NULL")  # NULL for other new columns

    select_csv = ", ".join(select_columns)
    insert_csv = ", ".join(insert_columns)

    try:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF;")
        connection.exec_driver_sql("ALTER TABLE user_story_map_nodes RENAME TO user_story_map_nodes__legacy;")

        # 刪除舊表格的所有索引，以避免重建時衝突
        result = connection.exec_driver_sql("PRAGMA index_list(user_story_map_nodes__legacy)")
        indexes = result.fetchall()
        for index_row in indexes:
            index_name = index_row[1]  # PRAGMA index_list 格式: (seq, name, unique, origin, partial)
            if index_name.startswith('sqlite_autoindex_'):
                continue  # 跳過自動索引
            try:
                connection.exec_driver_sql(f"DROP INDEX IF EXISTS {index_name}")
            except Exception as idx_exc:
                logging.warning("無法刪除索引 %s: %s", index_name, idx_exc)

        # 使用最新定義重新建立資料表（包含允許 NULL 的 node_type）
        Base.metadata.tables["user_story_map_nodes"].create(connection)
        connection.exec_driver_sql(
            f"INSERT INTO user_story_map_nodes ({insert_csv}) "
            f"SELECT {select_csv} FROM user_story_map_nodes__legacy;"
        )
        connection.exec_driver_sql("DROP TABLE user_story_map_nodes__legacy;")
        logging.info("user_story_map_nodes.node_type 約束調整完成")
    except Exception as exc:
        logging.error("調整 user_story_map_nodes.node_type 約束失敗: %s", exc)
        try:
            connection.exec_driver_sql("DROP TABLE IF EXISTS user_story_map_nodes;")
            connection.exec_driver_sql("ALTER TABLE user_story_map_nodes__legacy RENAME TO user_story_map_nodes;")
        except Exception as rollback_exc:
            logging.error("回復 user_story_map_nodes 結構失敗: %s", rollback_exc)
        raise
    finally:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON;")


def _add_missing_columns(connection):
    """添加缺失的欄位到現有表格"""
    # 檢查並添加 i_want 和 so_that 欄位
    result = connection.exec_driver_sql("PRAGMA table_info(user_story_map_nodes)")
    existing_columns = {row[1] for row in result.fetchall()}  # row[1] 是欄位名稱

    if 'i_want' not in existing_columns:
        connection.exec_driver_sql("ALTER TABLE user_story_map_nodes ADD COLUMN i_want TEXT")
        logging.info("已添加 i_want 欄位")

    if 'so_that' not in existing_columns:
        connection.exec_driver_sql("ALTER TABLE user_story_map_nodes ADD COLUMN so_that TEXT")
        logging.info("已添加 so_that 欄位")


async def init_usm_db():
    """初始化 User Story Map 資料庫"""
    async with usm_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)
        await conn.run_sync(_ensure_node_type_nullable)


async def get_usm_db():
    """獲取 User Story Map 資料庫 session"""
    async with USMAsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
