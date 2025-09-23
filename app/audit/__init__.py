"""
審計系統套件

提供審計記錄、查詢、匯出功能。
審計系統使用獨立資料庫確保資料完整性與效能隔離。
"""

# 資料模型
from .models import (
    ActionType,
    ResourceType, 
    AuditSeverity,
    AuditLog,
    AuditLogCreate,
    AuditLogQuery,
    AuditLogResponse,
    AuditLogSummary,
    AuditStatistics,
    ExportFormat,
    AuditLogExportRequest,
    ExportResponse
)

# 資料庫連接
from .database import (
    audit_db_manager,
    get_audit_session,
    init_audit_database,
    cleanup_audit_database,
    audit_health_check,
    AuditLogTable,
    create_audit_tables,
    drop_audit_tables
)

# 核心服務
from .audit_service import (
    audit_service,
    log_audit_action,
    AuditService
)

__all__ = [
    # 資料模型
    'ActionType',
    'ResourceType',
    'AuditSeverity',
    'AuditLog',
    'AuditLogCreate', 
    'AuditLogQuery',
    'AuditLogResponse',
    'AuditLogSummary',
    'AuditStatistics',
    'ExportFormat',
    'AuditLogExportRequest',
    'ExportResponse',
    
    # 資料庫
    'audit_db_manager',
    'get_audit_session',
    'init_audit_database',
    'cleanup_audit_database', 
    'audit_health_check',
    'AuditLogTable',
    'create_audit_tables',
    'drop_audit_tables',
    
    # 服務
    'audit_service',
    'log_audit_action',
    'AuditService',
]
