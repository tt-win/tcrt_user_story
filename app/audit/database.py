"""
審計系統資料庫連接

提供獨立的審計資料庫連接，確保審計記錄的完整性和效能隔離。
支援 SQLite 和 PostgreSQL，具備自動重連和連線池管理功能。
"""

import logging
from typing import Optional, AsyncGenerator
from sqlalchemy import create_engine, text, MetaData, event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import QueuePool, NullPool
from sqlalchemy.exc import SQLAlchemyError
from contextlib import asynccontextmanager

from ..config import get_settings

logger = logging.getLogger(__name__)


class AuditDatabaseManager:
    """審計資料庫管理器"""
    
    def __init__(self):
        self._engine: Optional[AsyncEngine] = None
        self._session_factory: Optional[async_sessionmaker] = None
        self._is_initialized = False
        self.config = get_settings().audit
        
    async def initialize(self) -> None:
        """初始化資料庫連接"""
        if self._is_initialized:
            logger.warning("審計資料庫已初始化，跳過重複初始化")
            return
            
        try:
            # 根據設定決定資料庫類型
            if self.config.database_url.startswith('postgresql'):
                await self._initialize_postgresql()
            else:
                await self._initialize_sqlite()
            await self._ensure_schema()
            
            self._is_initialized = True
            logger.info("審計資料庫初始化成功")
            
        except Exception as e:
            logger.error(f"審計資料庫初始化失敗: {e}")
            raise
            
    async def _initialize_postgresql(self) -> None:
        """初始化 PostgreSQL 連接"""
        logger.info("初始化 PostgreSQL 審計資料庫連接")
        
        # PostgreSQL 使用連線池
        self._engine = create_async_engine(
            self.config.database_url,
            poolclass=QueuePool,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=3600,  # 1小時回收連接
            echo=self.config.debug_sql,
            future=True
        )
        
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False
        )
        
    async def _initialize_sqlite(self) -> None:
        """初始化 SQLite 連接"""
        logger.info("初始化 SQLite 審計資料庫連接")

        # 將 sqlite:// 轉換為 aiosqlite://
        async_url = self.config.database_url.replace("sqlite://", "sqlite+aiosqlite://")

        # SQLite 使用 NullPool 避免連線池問題，並添加超時參數
        self._engine = create_async_engine(
            async_url,
            poolclass=NullPool,
            echo=self.config.debug_sql,
            future=True,
            connect_args={
                "check_same_thread": False,
                "timeout": 30,  # 30 秒超時，避免 database is locked 錯誤
            }
        )

        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False
        )

        # 為 SQLite 添加優化 PRAGMA 設定
        @event.listens_for(self._engine.sync_engine, "connect")
        def set_audit_sqlite_pragma(dbapi_conn, connection_record):
            """為審計數據庫設定 SQLite 優化參數"""
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
                logger.debug("SQLite 審計數據庫優化參數設定完成")
            except Exception as e:
                logger.warning(f"設定審計 SQLite PRAGMA 失敗: {e}")
            finally:
                cursor.close()

    async def _ensure_schema(self) -> None:
        """確保資料表與必要欄位存在"""
        if not self._engine:
            return

        async with self._engine.begin() as conn:
            await conn.run_sync(AuditBase.metadata.create_all)

            def ensure_role_column(sync_conn):
                dialect = sync_conn.dialect.name
                if dialect == 'sqlite':
                    rows = sync_conn.execute(text("PRAGMA table_info(audit_logs)")).fetchall()
                    column_names = {row[1] for row in rows}
                    if 'role' not in column_names:
                        sync_conn.execute(text("ALTER TABLE audit_logs ADD COLUMN role VARCHAR(50) DEFAULT 'user'"))
                    if 'action_brief' not in column_names:
                        sync_conn.execute(text("ALTER TABLE audit_logs ADD COLUMN action_brief VARCHAR(500)"))
                else:
                    rows = sync_conn.execute(
                        text("SELECT column_name FROM information_schema.columns WHERE table_name = 'audit_logs' AND table_schema = current_schema()")
                    ).fetchall()
                    column_names = {row[0] for row in rows}
                    if 'role' not in column_names:
                        sync_conn.execute(text("ALTER TABLE audit_logs ADD COLUMN role VARCHAR(50) DEFAULT 'user'"))
                    if 'action_brief' not in column_names:
                        sync_conn.execute(text("ALTER TABLE audit_logs ADD COLUMN action_brief VARCHAR(500)"))

            await conn.run_sync(ensure_role_column)
        
    async def cleanup(self) -> None:
        """清理資料庫連接"""
        if self._engine:
            logger.info("關閉審計資料庫連接")
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            self._is_initialized = False
            
    async def health_check(self) -> bool:
        """健康檢查"""
        if not self._is_initialized or not self._engine:
            return False
            
        try:
            async with self._engine.begin() as conn:
                result = await conn.execute(text("SELECT 1"))
                return result.scalar() == 1
        except Exception as e:
            logger.error(f"審計資料庫健康檢查失敗: {e}")
            return False
            
    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """取得資料庫會話"""
        if not self._is_initialized:
            await self.initialize()
            
        if not self._session_factory:
            raise RuntimeError("審計資料庫會話工廠未初始化")
            
        async with self._session_factory() as session:
            try:
                yield session
            except SQLAlchemyError as e:
                logger.error(f"審計資料庫操作錯誤: {e}")
                await session.rollback()
                raise
            except Exception as e:
                logger.error(f"審計資料庫會話錯誤: {e}")
                await session.rollback()
                raise
            finally:
                await session.close()
                
    async def execute_raw_sql(self, sql: str, params: Optional[dict] = None) -> any:
        """執行原始 SQL（僅供維護用）"""
        if not self._engine:
            raise RuntimeError("審計資料庫引擎未初始化")
            
        async with self._engine.begin() as conn:
            result = await conn.execute(text(sql), params or {})
            return result
            
    @property
    def engine(self) -> Optional[AsyncEngine]:
        """取得資料庫引擎（供遷移使用）"""
        return self._engine
        
    @property
    def is_initialized(self) -> bool:
        """是否已初始化"""
        return self._is_initialized


# 全域審計資料庫管理器實例
audit_db_manager = AuditDatabaseManager()


# 便利函數
@asynccontextmanager
async def get_audit_session() -> AsyncGenerator[AsyncSession, None]:
    """取得審計資料庫會話（依賴注入用）"""
    async with audit_db_manager.get_session() as session:
        yield session


async def init_audit_database() -> None:
    """初始化審計資料庫（應用啟動時調用）"""
    await audit_db_manager.initialize()


async def cleanup_audit_database() -> None:
    """清理審計資料庫（應用關閉時調用）"""
    await audit_db_manager.cleanup()


async def audit_health_check() -> bool:
    """審計資料庫健康檢查（自動初始化）"""
    # 自動初始化審計資料庫
    if not audit_db_manager.is_initialized:
        try:
            await audit_db_manager.initialize()
        except Exception as e:
            logger.error(f"審計資料庫自動初始化失敗: {e}")
            return False
    
    return await audit_db_manager.health_check()


# 資料庫表格定義
from sqlalchemy import Column, Integer, String, DateTime, Text, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from .models import ActionType, ResourceType, AuditSeverity

AuditBase = declarative_base()


class AuditLogTable(AuditBase):
    """審計記錄資料表"""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=func.now(), index=True)

    # 操作者資訊
    user_id = Column(Integer, nullable=False, index=True)
    username = Column(String(100), nullable=False, index=True)
    role = Column(String(50), nullable=False, default='user', index=True)

    # 操作資訊
    action_type = Column(SQLEnum(ActionType), nullable=False, index=True)
    resource_type = Column(SQLEnum(ResourceType), nullable=False, index=True)
    resource_id = Column(String(100), nullable=False, index=True)
    team_id = Column(Integer, nullable=False, index=True)

    # 詳細資訊
    details = Column(Text, nullable=True)  # JSON 字串格式
    action_brief = Column(String(500), nullable=True)
    severity = Column(SQLEnum(AuditSeverity), nullable=False, default=AuditSeverity.INFO, index=True)

    # 來源資訊
    ip_address = Column(String(45), nullable=True)  # 支援 IPv6
    user_agent = Column(String(500), nullable=True)
    
    def __repr__(self):
        return (f"<AuditLog(id={self.id}, user={self.username}, "
                f"action={self.action_type}, resource={self.resource_type}:{self.resource_id})>")


# 索引定義（提升查詢效能）
from sqlalchemy import Index

# 複合索引
Index('idx_audit_time_team', AuditLogTable.timestamp, AuditLogTable.team_id)
Index('idx_audit_user_time', AuditLogTable.user_id, AuditLogTable.timestamp)
Index('idx_audit_resource', AuditLogTable.resource_type, AuditLogTable.resource_id)
Index('idx_audit_severity_time', AuditLogTable.severity, AuditLogTable.timestamp)
Index('idx_audit_username_time', AuditLogTable.username, AuditLogTable.timestamp)
Index('idx_audit_role_time', AuditLogTable.role, AuditLogTable.timestamp)
Index('idx_audit_action_time', AuditLogTable.action_type, AuditLogTable.timestamp)


async def create_audit_tables() -> None:
    """創建審計資料表（僅供開發/測試使用）"""
    if not audit_db_manager.engine:
        await audit_db_manager.initialize()
        
    async with audit_db_manager.engine.begin() as conn:
        await conn.run_sync(AuditBase.metadata.create_all)
        logger.info("審計資料表創建完成")


async def drop_audit_tables() -> None:
    """刪除審計資料表（僅供測試使用）"""
    if not audit_db_manager.engine:
        await audit_db_manager.initialize()
        
    async with audit_db_manager.engine.begin() as conn:
        await conn.run_sync(AuditBase.metadata.drop_all)
        logger.info("審計資料表刪除完成")
