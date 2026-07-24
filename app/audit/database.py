"""
審計系統資料庫連接

提供獨立的審計資料庫連接，確保審計記錄的完整性和效能隔離。
支援 SQLite 和 PostgreSQL，具備自動重連和連線池管理功能。
"""

import json
import logging
from enum import Enum
from typing import Any, Optional, AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import Column, DateTime, Enum as SQLEnum, Float, Index, Integer, String, SmallInteger, Text as SqlText, event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import func

from ..config import get_settings
from ..db_types import MediumText as Text
from ..db_sqlite_pragma import apply_sqlite_pragma
from ..db_url import normalize_async_database_url
from .models import ActionType, AuditSeverity, ResourceType

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
            if self.config.database_url.startswith('sqlite'):
                await self._initialize_sqlite()
            else:
                await self._initialize_server_database()
            
            self._is_initialized = True
            logger.info("審計資料庫初始化成功")
            
        except Exception as e:
            logger.error(f"審計資料庫初始化失敗: {e}")
            raise
            
    async def _initialize_server_database(self) -> None:
        """初始化非 SQLite 的審計資料庫連接"""
        logger.info("初始化非 SQLite 審計資料庫連接")
        
        self._engine = create_async_engine(
            normalize_async_database_url(self.config.database_url),
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

        async_url = normalize_async_database_url(self.config.database_url)

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
            if self._engine is None or self._engine.sync_engine.dialect.name != "sqlite":
                return
            apply_sqlite_pragma(dbapi_conn, label="審計資料庫")

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
                
    async def execute_raw_sql(self, sql: str, params: Optional[dict] = None):
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
    action_type = Column(
        SQLEnum(
            ActionType,
            values_callable=lambda values: [item.value for item in values],
            native_enum=False,
        ),
        nullable=False,
        index=True,
    )
    resource_type = Column(
        SQLEnum(
            ResourceType,
            values_callable=lambda values: [item.value for item in values],
            native_enum=False,
        ),
        nullable=False,
        index=True,
    )
    resource_id = Column(String(100), nullable=False, index=True)
    team_id = Column(Integer, nullable=True, index=True)

    # 詳細資訊
    details = Column(Text, nullable=True)  # JSON 字串格式
    action_brief = Column(String(500), nullable=True)
    severity = Column(
        SQLEnum(
            AuditSeverity,
            values_callable=lambda values: [item.value for item in values],
            native_enum=False,
        ),
        nullable=False,
        default=AuditSeverity.INFO,
        index=True,
    )

    # 來源資訊
    ip_address = Column(String(45), nullable=True)  # 支援 IPv6
    user_agent = Column(String(500), nullable=True)

    # Event envelope columns
    event_code = Column(String(128), nullable=True, index=True)
    impact = Column(String(32), nullable=True)
    outcome = Column(String(32), nullable=True)
    schema_version = Column(SmallInteger, nullable=False, default=0)
    
    def __repr__(self):
        return (f"<AuditLog(id={self.id}, user={self.username}, "
                f"action={self.action_type}, resource={self.resource_type}:{self.resource_id})>")


# ---------------------------------------------------------------------------
# Knowledge graph / RAG query log (openspec: log-knowledge-graph-queries)
# ---------------------------------------------------------------------------


class KnowledgeQuerySource(str, Enum):
    """Knowledge graph / RAG 查詢來源標籤。"""

    ASSISTANT = "assistant"
    QA_HELPER = "qa_helper"
    API = "api"


class KnowledgeQueryOperation(str, Enum):
    """Knowledge graph / RAG 查詢類型。"""

    SEARCH = "search"
    IMPACT = "impact"


class KnowledgeQueryStatus(str, Enum):
    """Knowledge graph / RAG 查詢結果狀態。"""

    SUCCESS = "success"
    DEGRADED = "degraded"


def _knowledge_query_enum_values(enum_cls: Any) -> list[str]:
    return [item.value for item in enum_cls]


class KnowledgeQueryLogTable(AuditBase):
    """知識圖譜 / RAG 查詢的觀測性記錄表。

    設計目標：純觀測性疊加。不存結果全文 snippet；跨 SQLite / MySQL 8 / PostgreSQL 16
    可攜（JSON 採 ``MediumText``+``json.dumps``、列舉採 ``native_enum=False``）；time-stamp
    採 client-side ``default=func.now()`` 且 migration 不寫 ``server_default``，避免
    alembic ``compare_server_default`` 判 drift。
    """

    __tablename__ = "knowledge_query_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=func.now(), index=True)
    query_id = Column(String(64), nullable=True, index=True)

    source = Column(
        SQLEnum(
            KnowledgeQuerySource,
            values_callable=lambda values: _knowledge_query_enum_values(KnowledgeQuerySource),
            native_enum=False,
        ),
        nullable=False,
    )
    operation = Column(
        SQLEnum(
            KnowledgeQueryOperation,
            values_callable=lambda values: _knowledge_query_enum_values(KnowledgeQueryOperation),
            native_enum=False,
        ),
        nullable=False,
    )
    status = Column(
        SQLEnum(
            KnowledgeQueryStatus,
            values_callable=lambda values: _knowledge_query_enum_values(KnowledgeQueryStatus),
            native_enum=False,
        ),
        nullable=False,
    )

    # 發起者
    user_id = Column(Integer, nullable=True)
    username = Column(String(100), nullable=True)
    conversation_id = Column(String(64), nullable=True)
    turn_key = Column(String(128), nullable=True)
    llm_tool_call_id = Column(String(128), nullable=True)

    # 查詢內容
    query_text = Column(Text, nullable=True)
    primary_team_id = Column(Integer, nullable=True)
    allowed_team_ids = Column(Text, nullable=True)  # JSON 序列化 list[int]
    top_k = Column(Integer, nullable=True)
    score_threshold = Column(Float, nullable=True)
    fallback_recommended = Column(SmallInteger, nullable=True)
    degrade_reason = Column(String(128), nullable=True)

    # 結果統計與診斷
    duration_ms = Column(Integer, nullable=True)
    result_count = Column(Integer, nullable=True)
    process = Column(Text, nullable=True)  # JSON 序列化 dict：dual_route、per-collection 計數、graph 展開/逾時、斷路器狀態
    results_summary = Column(Text, nullable=True)  # JSON 序列化 list[dict]，每筆精簡
    error = Column(Text, nullable=True)
    schema_version = Column(SmallInteger, nullable=False, default=1)

    def __repr__(self) -> str:
        return (
            f"<KnowledgeQueryLog(id={self.id}, source={self.source}, operation={self.operation}, "
            f"status={self.status}, ts={self.timestamp})>"
        )

    def to_dict(self) -> dict[str, Any]:
        ts = self.timestamp
        if hasattr(ts, "isoformat"):
            ts = ts.isoformat()
        return {
            "id": self.id,
            "timestamp": ts,
            "query_id": self.query_id,
            "source": self.source.value if hasattr(self.source, "value") else self.source,
            "operation": self.operation.value if hasattr(self.operation, "value") else self.operation,
            "status": self.status.value if hasattr(self.status, "value") else self.status,
            "user_id": self.user_id,
            "username": self.username,
            "conversation_id": self.conversation_id,
            "turn_key": self.turn_key,
            "llm_tool_call_id": self.llm_tool_call_id,
            "query_text": self.query_text,
            "primary_team_id": self.primary_team_id,
            "allowed_team_ids": _safe_json_loads(str(self.allowed_team_ids) if self.allowed_team_ids is not None else None),
            "top_k": self.top_k,
            "score_threshold": self.score_threshold,
            "fallback_recommended": self.fallback_recommended,
            "degrade_reason": self.degrade_reason,
            "duration_ms": self.duration_ms,
            "result_count": self.result_count,
            "process": _safe_json_loads(str(self.process) if self.process is not None else None),
            "results_summary": _safe_json_loads(str(self.results_summary) if self.results_summary is not None else None),
            "error": self.error,
            "schema_version": self.schema_version,
        }


def _safe_json_loads(raw: Optional[str]) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


# 索引定義（提升查詢效能）
# 複合索引
Index('idx_audit_time_team', AuditLogTable.timestamp, AuditLogTable.team_id)
Index('idx_audit_user_time', AuditLogTable.user_id, AuditLogTable.timestamp)
Index('idx_audit_resource', AuditLogTable.resource_type, AuditLogTable.resource_id)
Index('idx_audit_severity_time', AuditLogTable.severity, AuditLogTable.timestamp)
Index('idx_audit_username_time', AuditLogTable.username, AuditLogTable.timestamp)
Index('idx_audit_role_time', AuditLogTable.role, AuditLogTable.timestamp)
Index('idx_audit_action_time', AuditLogTable.action_type, AuditLogTable.timestamp)
Index('ix_audit_logs_event_code_timestamp', AuditLogTable.event_code, AuditLogTable.timestamp)

# Knowledge query log 複合索引：對應 admin /api/admin/knowledge-query-logs 常見查詢模式
Index('ix_knowledge_query_logs_source_timestamp', KnowledgeQueryLogTable.source, KnowledgeQueryLogTable.timestamp)
Index('ix_knowledge_query_logs_status_timestamp', KnowledgeQueryLogTable.status, KnowledgeQueryLogTable.timestamp)
Index('ix_knowledge_query_logs_primary_team_timestamp', KnowledgeQueryLogTable.primary_team_id, KnowledgeQueryLogTable.timestamp)
Index('ix_knowledge_query_logs_user_timestamp', KnowledgeQueryLogTable.user_id, KnowledgeQueryLogTable.timestamp)


async def create_audit_tables() -> None:
    """創建審計資料表（僅供開發/測試使用）"""
    if not audit_db_manager.engine:
        await audit_db_manager.initialize()
        
    engine = audit_db_manager.engine
    assert engine is not None
    async with engine.begin() as conn:
        await conn.run_sync(AuditBase.metadata.create_all)
        logger.info("審計資料表創建完成")


async def drop_audit_tables() -> None:
    """刪除審計資料表（僅供測試使用）"""
    if not audit_db_manager.engine:
        await audit_db_manager.initialize()
        
    engine = audit_db_manager.engine
    assert engine is not None
    async with engine.begin() as conn:
        await conn.run_sync(AuditBase.metadata.drop_all)
        logger.info("審計資料表刪除完成")
