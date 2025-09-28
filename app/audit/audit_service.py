"""
審計系統核心服務

提供審計記錄的創建、查詢、匯出和統計功能。
實作批次寫入、非同步處理和敏感資料遮罩。
"""

import logging
import json
import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy import select, func, and_, desc, asc
from sqlalchemy.exc import SQLAlchemyError
from contextlib import asynccontextmanager

from .models import (
    AuditLog, AuditLogCreate, AuditLogQuery, AuditLogResponse, AuditLogSummary,
    AuditStatistics, ActionType, ResourceType, AuditSeverity
)
from .database import get_audit_session, AuditLogTable, audit_db_manager
from ..config import get_settings

logger = logging.getLogger(__name__)


class AuditService:
    """審計系統核心服務類"""
    
    def __init__(self):
        self.config = get_settings().audit
        self._batch_buffer: List[AuditLogCreate] = []
        self._batch_lock = asyncio.Lock()
        self._last_flush = datetime.utcnow()
        
    # ===================== 記錄創建 =====================
    
    async def log_action(
        self,
        user_id: int,
        username: str,
        role: str,
        action_type: ActionType,
        resource_type: ResourceType,
        resource_id: str,
        team_id: int,
        details: Optional[Dict[str, Any]] = None,
        action_brief: Optional[str] = None,
        severity: AuditSeverity = AuditSeverity.INFO,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> None:
        """記錄操作審計"""
        if not self.config.enabled:
            return
            
        try:
            # 遮罩敏感資料
            masked_details = self._mask_sensitive_data(details) if details else None
            
            # 創建審計記錄
            audit_log = AuditLogCreate(
                user_id=user_id,
                username=username,
                role=role,
                action_type=action_type,
                resource_type=resource_type,
                resource_id=resource_id,
                team_id=team_id,
                details=masked_details,
                action_brief=action_brief,
                severity=severity,
                ip_address=ip_address,
                user_agent=user_agent
            )
            
            # 加入批次緩衝區
            async with self._batch_lock:
                self._batch_buffer.append(audit_log)
                
                # 檢查是否需要立即寫入
                should_flush = (
                    len(self._batch_buffer) >= self.config.batch_size or
                    severity == AuditSeverity.CRITICAL or
                    (datetime.utcnow() - self._last_flush).seconds > 30
                )
                
                if should_flush:
                    await self._flush_batch()
                    
        except Exception as e:
            logger.error(f"記錄審計失敗: {e}", exc_info=True)
            
    async def log_create(self, user_id: int, username: str, resource_type: ResourceType,
                        resource_id: str, team_id: int, role: str,
                        details: Optional[Dict] = None,
                        action_brief: Optional[str] = None,
                        ip_address: Optional[str] = None, user_agent: Optional[str] = None) -> None:
        """記錄創建操作"""
        await self.log_action(
            user_id=user_id,
            username=username,
            role=role,
            action_type=ActionType.CREATE,
            resource_type=resource_type,
            resource_id=resource_id,
            team_id=team_id,
            details=details,
            action_brief=action_brief,
            severity=AuditSeverity.INFO,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
    async def log_update(self, user_id: int, username: str, resource_type: ResourceType,
                        resource_id: str, team_id: int, role: str,
                        details: Optional[Dict] = None,
                        action_brief: Optional[str] = None,
                        ip_address: Optional[str] = None, user_agent: Optional[str] = None) -> None:
        """記錄更新操作"""
        await self.log_action(
            user_id=user_id,
            username=username,
            role=role,
            action_type=ActionType.UPDATE,
            resource_type=resource_type,
            resource_id=resource_id,
            team_id=team_id,
            details=details,
            action_brief=action_brief,
            severity=AuditSeverity.INFO,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
    async def log_delete(self, user_id: int, username: str, resource_type: ResourceType,
                        resource_id: str, team_id: int, role: str,
                        details: Optional[Dict] = None,
                        action_brief: Optional[str] = None,
                        ip_address: Optional[str] = None, user_agent: Optional[str] = None) -> None:
        """記錄刪除操作（高危險性）"""
        await self.log_action(
            user_id=user_id,
            username=username,
            role=role,
            action_type=ActionType.DELETE,
            resource_type=resource_type,
            resource_id=resource_id,
            team_id=team_id,
            details=details,
            action_brief=action_brief,
            severity=AuditSeverity.CRITICAL,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
    async def log_read(self, user_id: int, username: str, resource_type: ResourceType,
                      resource_id: str, team_id: int, role: str,
                      details: Optional[Dict] = None,
                      ip_address: Optional[str] = None, user_agent: Optional[str] = None) -> None:
        """記錄讀取操作"""
        await self.log_action(
            user_id=user_id,
            username=username,
            role=role,
            action_type=ActionType.READ,
            resource_type=resource_type,
            resource_id=resource_id,
            team_id=team_id,
            details=details,
            severity=AuditSeverity.INFO,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
    # ===================== 查詢功能 =====================
    
    async def query_logs(self, query: AuditLogQuery) -> AuditLogResponse:
        """查詢審計記錄"""
        try:
            async with audit_db_manager.get_session() as session:
                conditions = self._build_conditions(query)

                # 總數查詢
                count_query = select(func.count()).select_from(AuditLogTable)
                if conditions:
                    count_query = count_query.where(and_(*conditions))
                    
                total_result = await session.execute(count_query)
                total = total_result.scalar()
                
                # 分頁查詢
                base_query = select(AuditLogTable)
                if conditions:
                    base_query = base_query.where(and_(*conditions))
                    
                # 排序
                if query.sort_order == 'asc':
                    base_query = base_query.order_by(asc(getattr(AuditLogTable, query.sort_by)))
                else:
                    base_query = base_query.order_by(desc(getattr(AuditLogTable, query.sort_by)))
                    
                # 分頁
                offset = (query.page - 1) * query.page_size
                base_query = base_query.offset(offset).limit(query.page_size)
                
                result = await session.execute(base_query)
                records = result.scalars().all()
                
                # 轉換為回應模型
                items = [
                    AuditLogSummary(
                        id=record.id,
                        timestamp=record.timestamp,
                        username=record.username,
                        role=record.role,
                        action_type=record.action_type,
                        resource_type=record.resource_type,
                        resource_id=record.resource_id,
                        team_id=record.team_id,
                        severity=record.severity,
                        action_brief=getattr(record, 'action_brief', None),
                        ip_address=record.ip_address
                    )
                    for record in records
                ]
                
                total_pages = (total + query.page_size - 1) // query.page_size

                return AuditLogResponse(
                    items=items,
                    total=total,
                    page=query.page,
                    page_size=query.page_size,
                    total_pages=total_pages
                )

        except Exception as e:
            logger.error(f"查詢審計記錄失敗: {e}", exc_info=True)
            raise

    def _build_conditions(self, query: AuditLogQuery) -> List[Any]:
        """依據查詢條件組裝 SQLAlchemy 條件"""
        conditions: List[Any] = []

        if query.start_time:
            conditions.append(AuditLogTable.timestamp >= query.start_time)
        if query.end_time:
            conditions.append(AuditLogTable.timestamp <= query.end_time)
        if query.user_id:
            conditions.append(AuditLogTable.user_id == query.user_id)
        if query.username:
            conditions.append(AuditLogTable.username.ilike(f"%{query.username}%"))
        if query.action_type:
            conditions.append(AuditLogTable.action_type == query.action_type)
        if query.resource_type:
            conditions.append(AuditLogTable.resource_type == query.resource_type)
        if query.resource_id:
            conditions.append(AuditLogTable.resource_id == query.resource_id)
        if query.team_id:
            conditions.append(AuditLogTable.team_id == query.team_id)
        if query.severity:
            conditions.append(AuditLogTable.severity == query.severity)
        if getattr(query, "role", None):
            conditions.append(AuditLogTable.role == query.role)

        return conditions

    async def fetch_logs_for_export(self, query: AuditLogQuery) -> List[AuditLog]:
        """取得符合條件的審計記錄（無分頁）供匯出使用"""
        try:
            async with audit_db_manager.get_session() as session:
                conditions = self._build_conditions(query)
                stmt = select(AuditLogTable)
                if conditions:
                    stmt = stmt.where(and_(*conditions))
                stmt = stmt.order_by(desc(AuditLogTable.timestamp))

                result = await session.execute(stmt)
                records = result.scalars().all()

                export_items: List[AuditLog] = []
                for record in records:
                    details = None
                    if record.details:
                        try:
                            details = json.loads(record.details)
                        except json.JSONDecodeError:
                            details = None

                    export_items.append(
                        AuditLog(
                            id=record.id,
                            timestamp=record.timestamp,
                            user_id=record.user_id,
                            username=record.username,
                            role=record.role,
                            action_type=record.action_type,
                            resource_type=record.resource_type,
                            resource_id=record.resource_id,
                            team_id=record.team_id,
                            details=details,
                            action_brief=getattr(record, 'action_brief', None),
                            severity=record.severity,
                            ip_address=record.ip_address,
                            user_agent=record.user_agent,
                        )
                    )

                return export_items
        except Exception as e:
            logger.error(f"匯出審計記錄失敗: {e}", exc_info=True)
            raise
            
    async def get_log_detail(self, log_id: int) -> Optional[AuditLog]:
        """取得審計記錄詳情"""
        try:
            async with audit_db_manager.get_session() as session:
                result = await session.execute(
                    select(AuditLogTable).where(AuditLogTable.id == log_id)
                )
                record = result.scalar_one_or_none()
                
                if not record:
                    return None
                    
                # 解析 JSON 詳情
                details = None
                if record.details:
                    try:
                        details = json.loads(record.details)
                    except json.JSONDecodeError:
                        logger.warning(f"審計記錄 {log_id} 的詳情 JSON 格式錯誤")
                        
                return AuditLog(
                    id=record.id,
                    timestamp=record.timestamp,
                    user_id=record.user_id,
                    username=record.username,
                    role=record.role,
                    action_type=record.action_type,
                    resource_type=record.resource_type,
                    resource_id=record.resource_id,
                    team_id=record.team_id,
                    details=details,
                    action_brief=getattr(record, 'action_brief', None),
                    severity=record.severity,
                    ip_address=record.ip_address,
                    user_agent=record.user_agent
                )
                
        except Exception as e:
            logger.error(f"取得審計記錄詳情失敗: {e}", exc_info=True)
            raise
            
    # ===================== 統計分析 =====================
    
    async def get_statistics(
        self,
        start_time: datetime,
        end_time: datetime,
        team_ids: Optional[List[int]] = None
    ) -> AuditStatistics:
        """取得審計統計資訊"""
        try:
            async with audit_db_manager.get_session() as session:
                conditions = [
                    AuditLogTable.timestamp >= start_time,
                    AuditLogTable.timestamp <= end_time
                ]
                
                if team_ids:
                    conditions.append(AuditLogTable.team_id.in_(team_ids))
                    
                base_where = and_(*conditions)
                
                # 總記錄數
                total_result = await session.execute(
                    select(func.count()).select_from(AuditLogTable).where(base_where)
                )
                total_records = total_result.scalar()
                
                # 按操作類型統計
                action_result = await session.execute(
                    select(AuditLogTable.action_type, func.count())
                    .where(base_where)
                    .group_by(AuditLogTable.action_type)
                )
                by_action_type = {str(action): count for action, count in action_result.fetchall()}
                
                # 按資源類型統計
                resource_result = await session.execute(
                    select(AuditLogTable.resource_type, func.count())
                    .where(base_where)
                    .group_by(AuditLogTable.resource_type)
                )
                by_resource_type = {str(resource): count for resource, count in resource_result.fetchall()}
                
                # 按嚴重性統計
                severity_result = await session.execute(
                    select(AuditLogTable.severity, func.count())
                    .where(base_where)
                    .group_by(AuditLogTable.severity)
                )
                by_severity = {str(severity): count for severity, count in severity_result.fetchall()}
                
                # 按團隊統計
                team_result = await session.execute(
                    select(AuditLogTable.team_id, func.count())
                    .where(base_where)
                    .group_by(AuditLogTable.team_id)
                )
                by_team = {str(team_id): count for team_id, count in team_result.fetchall()}
                
                # 最活躍使用者（前10名）
                user_result = await session.execute(
                    select(AuditLogTable.username, func.count())
                    .where(base_where)
                    .group_by(AuditLogTable.username)
                    .order_by(desc(func.count()))
                    .limit(10)
                )
                top_users = [
                    {"username": username, "count": count}
                    for username, count in user_result.fetchall()
                ]
                
                return AuditStatistics(
                    total_records=total_records,
                    time_range={"start": start_time, "end": end_time},
                    by_action_type=by_action_type,
                    by_resource_type=by_resource_type,
                    by_severity=by_severity,
                    by_team=by_team,
                    top_users=top_users
                )
                
        except Exception as e:
            logger.error(f"取得審計統計失敗: {e}", exc_info=True)
            raise
            
    # ===================== 清理維護 =====================
    
    async def cleanup_old_records(self) -> int:
        """清理過期記錄"""
        if self.config.cleanup_days <= 0:
            return 0
            
        cutoff_date = datetime.utcnow() - timedelta(days=self.config.cleanup_days)
        
        try:
            async with audit_db_manager.get_session() as session:
                # 先查詢要刪除的記錄數
                count_result = await session.execute(
                    select(func.count()).select_from(AuditLogTable)
                    .where(AuditLogTable.timestamp < cutoff_date)
                )
                count_to_delete = count_result.scalar()
                
                if count_to_delete == 0:
                    return 0
                    
                # 執行刪除
                result = await session.execute(
                    AuditLogTable.__table__.delete().where(AuditLogTable.timestamp < cutoff_date)
                )
                await session.commit()
                
                deleted_count = result.rowcount
                logger.info(f"已清理 {deleted_count} 筆過期審計記錄")
                return deleted_count
                
        except Exception as e:
            logger.error(f"清理過期記錄失敗: {e}", exc_info=True)
            raise
            
    async def force_flush(self) -> int:
        """強制刷新批次緩衝區"""
        async with self._batch_lock:
            count = len(self._batch_buffer)
            if count > 0:
                await self._flush_batch()
            return count
            
    # ===================== 私有方法 =====================
    
    def _mask_sensitive_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """遮罩敏感資料"""
        if not isinstance(data, dict):
            return data
            
        masked = {}
        for key, value in data.items():
            if any(sensitive in key.lower() for sensitive in self.config.excluded_fields):
                masked[key] = "***MASKED***"
            elif isinstance(value, dict):
                masked[key] = self._mask_sensitive_data(value)
            elif isinstance(value, list):
                masked[key] = [
                    self._mask_sensitive_data(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                masked[key] = value
                
        return masked
        
    async def _flush_batch(self) -> None:
        """批次寫入審計記錄"""
        if not self._batch_buffer:
            return
            
        records_to_write = self._batch_buffer[:]
        self._batch_buffer.clear()
        self._last_flush = datetime.utcnow()
        
        try:
            async with audit_db_manager.get_session() as session:
                # 轉換為資料表記錄
                db_records = []
                for record in records_to_write:
                    details_json = None
                    if record.details:
                        try:
                            details_json = json.dumps(record.details, ensure_ascii=False)
                            # 檢查大小限制
                            if len(details_json.encode('utf-8')) > self.config.max_detail_size:
                                details_json = json.dumps({"error": "詳情過大已截斷"}, ensure_ascii=False)
                        except Exception as e:
                            logger.warning(f"序列化審計詳情失敗: {e}")
                            details_json = json.dumps({"error": "詳情序列化失敗"}, ensure_ascii=False)
                            
                    db_record = AuditLogTable(
                        timestamp=datetime.utcnow(),
                        user_id=record.user_id,
                        username=record.username,
                        role=record.role,
                        action_type=record.action_type,
                        resource_type=record.resource_type,
                        resource_id=record.resource_id,
                        team_id=record.team_id,
                        details=details_json,
                        action_brief=record.action_brief,
                        severity=record.severity,
                        ip_address=record.ip_address,
                        user_agent=record.user_agent
                    )
                    db_records.append(db_record)
                    
                session.add_all(db_records)
                await session.commit()
                
                logger.debug(f"已寫入 {len(db_records)} 筆審計記錄")
                
        except Exception as e:
            logger.error(f"批次寫入審計記錄失敗: {e}", exc_info=True)
            # 失敗的記錄放回緩衝區（避免遺失）
            async with self._batch_lock:
                self._batch_buffer = records_to_write + self._batch_buffer


# 全域審計服務實例
audit_service = AuditService()


# 便利函數
async def log_audit_action(
    user_id: int,
    username: str,
    role: str,
    action_type: ActionType,
    resource_type: ResourceType,
    resource_id: str,
    team_id: int,
    details: Optional[Dict[str, Any]] = None,
    severity: AuditSeverity = AuditSeverity.INFO,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None
) -> None:
    """記錄審計操作（便利函數）"""
    await audit_service.log_action(
        user_id=user_id,
        username=username,
        role=role,
        action_type=action_type,
        resource_type=resource_type,
        resource_id=resource_id,
        team_id=team_id,
        details=details,
        severity=severity,
        ip_address=ip_address,
        user_agent=user_agent
    )
