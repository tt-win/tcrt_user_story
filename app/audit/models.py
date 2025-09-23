"""
審計系統資料模型

定義審計記錄的資料結構、查詢條件、匯出格式等。
遵循隱私最小化原則，不記錄敏感資訊。
"""

from enum import Enum
from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel, Field, validator


class ActionType(str, Enum):
    """操作類型枚舉"""
    CREATE = "CREATE"
    READ = "READ"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


class ResourceType(str, Enum):
    """資源類型枚舉"""
    TEAM_SETTING = "team_setting"
    TEST_RUN = "test_run" 
    TEST_CASE = "test_case"


class AuditSeverity(str, Enum):
    """審計嚴重性等級"""
    INFO = "info"          # 一般資訊性操作
    WARNING = "warning"    # 需要注意的操作
    CRITICAL = "critical"  # 關鍵操作（刪除、權限變更等）


# ===================== 審計記錄模型 =====================

class AuditLogBase(BaseModel):
    """審計記錄基礎模型"""
    user_id: int = Field(..., description="操作者使用者 ID")
    username: str = Field(..., max_length=100, description="操作者使用者名稱")
    action_type: ActionType = Field(..., description="操作類型")
    resource_type: ResourceType = Field(..., description="資源類型")
    resource_id: str = Field(..., max_length=100, description="資源 ID")
    team_id: int = Field(..., description="相關團隊 ID")
    details: Optional[Dict[str, Any]] = Field(None, description="操作詳情（JSON，已遮罩敏感資料）")
    severity: AuditSeverity = Field(AuditSeverity.INFO, description="嚴重性等級")
    ip_address: Optional[str] = Field(None, max_length=45, description="來源 IP 位址")
    user_agent: Optional[str] = Field(None, max_length=500, description="使用者代理")


class AuditLogCreate(AuditLogBase):
    """建立審計記錄請求模型"""
    pass


class AuditLog(AuditLogBase):
    """審計記錄完整模型"""
    id: int
    timestamp: datetime = Field(..., description="操作時間 (UTC)")
    
    class Config:
        from_attributes = True


class AuditLogSummary(BaseModel):
    """審計記錄摘要模型（列表用）"""
    id: int
    timestamp: datetime
    username: str
    action_type: ActionType
    resource_type: ResourceType
    resource_id: str
    team_id: int
    severity: AuditSeverity
    ip_address: Optional[str] = None


# ===================== 查詢條件模型 =====================

class AuditLogQuery(BaseModel):
    """審計記錄查詢條件模型"""
    # 時間範圍
    start_time: Optional[datetime] = Field(None, description="開始時間 (UTC)")
    end_time: Optional[datetime] = Field(None, description="結束時間 (UTC)")
    
    # 過濾條件
    user_id: Optional[int] = Field(None, description="操作者 ID")
    username: Optional[str] = Field(None, description="操作者名稱（模糊搜尋）")
    action_type: Optional[ActionType] = Field(None, description="操作類型")
    resource_type: Optional[ResourceType] = Field(None, description="資源類型")
    resource_id: Optional[str] = Field(None, description="資源 ID")
    team_id: Optional[int] = Field(None, description="團隊 ID")
    severity: Optional[AuditSeverity] = Field(None, description="嚴重性等級")
    
    # 分頁
    page: int = Field(1, ge=1, description="頁碼")
    page_size: int = Field(50, ge=1, le=1000, description="每頁筆數")
    
    # 排序
    sort_by: str = Field("timestamp", description="排序欄位")
    sort_order: str = Field("desc", pattern="^(asc|desc)$", description="排序順序")
    
    @validator('end_time')
    def validate_time_range(cls, v, values):
        """驗證時間範圍有效性"""
        if v and values.get('start_time') and v <= values['start_time']:
            raise ValueError('結束時間必須晚於開始時間')
        return v


class AuditLogResponse(BaseModel):
    """審計記錄查詢回應模型"""
    items: List[AuditLogSummary] = Field(..., description="審計記錄列表")
    total: int = Field(..., description="總筆數")
    page: int = Field(..., description="當前頁碼")
    page_size: int = Field(..., description="每頁筆數")
    total_pages: int = Field(..., description="總頁數")


# ===================== 匯出相關模型 =====================

class ExportFormat(str, Enum):
    """匯出格式枚舉"""
    CSV = "csv"
    JSON = "json"


class AuditLogExportRequest(BaseModel):
    """審計記錄匯出請求模型"""
    query: AuditLogQuery = Field(..., description="查詢條件")
    format: ExportFormat = Field(ExportFormat.CSV, description="匯出格式")
    include_details: bool = Field(False, description="是否包含詳細資訊")
    timezone: Optional[str] = Field(None, description="時區轉換（如 'Asia/Taipei'）")
    filename: Optional[str] = Field(None, description="自訂檔名")
    
    # CSV 專用選項
    include_bom: bool = Field(True, description="CSV 是否包含 UTF-8 BOM")
    delimiter: str = Field(",", description="CSV 分隔符")


class ExportResponse(BaseModel):
    """匯出回應模型"""
    download_url: str = Field(..., description="下載連結")
    filename: str = Field(..., description="檔案名稱")
    format: ExportFormat = Field(..., description="匯出格式")
    record_count: int = Field(..., description="匯出記錄數")
    expires_at: datetime = Field(..., description="連結過期時間")


# ===================== 統計分析模型 =====================

class AuditStatistics(BaseModel):
    """審計統計模型"""
    total_records: int = Field(..., description="總記錄數")
    time_range: Dict[str, datetime] = Field(..., description="時間範圍")
    
    # 按類型統計
    by_action_type: Dict[str, int] = Field(..., description="按操作類型統計")
    by_resource_type: Dict[str, int] = Field(..., description="按資源類型統計") 
    by_severity: Dict[str, int] = Field(..., description="按嚴重性統計")
    by_team: Dict[str, int] = Field(..., description="按團隊統計")
    
    # 最活躍使用者
    top_users: List[Dict[str, Any]] = Field(..., description="最活躍使用者")


class AuditTrendData(BaseModel):
    """審計趨勢資料模型"""
    date: str = Field(..., description="日期")
    count: int = Field(..., description="記錄數")
    action_breakdown: Dict[str, int] = Field(..., description="操作類型分佈")


class AuditAnalysisRequest(BaseModel):
    """審計分析請求模型"""
    start_time: datetime = Field(..., description="分析開始時間")
    end_time: datetime = Field(..., description="分析結束時間")
    team_ids: Optional[List[int]] = Field(None, description="限制分析的團隊 ID")
    group_by_day: bool = Field(True, description="是否按天分組")


# ===================== 審計配置模型 =====================

class AuditConfig(BaseModel):
    """審計系統配置模型"""
    enabled: bool = Field(True, description="是否啟用審計")
    batch_size: int = Field(100, description="批次寫入大小")
    cleanup_days: int = Field(365, description="記錄保留天數")
    max_detail_size: int = Field(10240, description="詳情欄位最大大小（字節）")
    excluded_fields: List[str] = Field(
        default=["password", "token", "secret", "key"],
        description="排除記錄的敏感欄位"
    )


# ===================== 錯誤與狀態模型 =====================

class AuditError(BaseModel):
    """審計系統錯誤模型"""
    code: str = Field(..., description="錯誤代碼")
    message: str = Field(..., description="錯誤訊息")
    timestamp: datetime = Field(..., description="錯誤發生時間")
    details: Optional[Dict[str, Any]] = Field(None, description="錯誤詳情")


class AuditHealthStatus(BaseModel):
    """審計系統健康狀態模型"""
    status: str = Field(..., description="狀態：healthy/degraded/unhealthy")
    database_connected: bool = Field(..., description="資料庫連線狀態")
    last_write_time: Optional[datetime] = Field(None, description="最後寫入時間")
    pending_records: int = Field(0, description="待寫入記錄數")
    error_count: int = Field(0, description="錯誤計數")
    uptime: float = Field(..., description="運行時間（秒）")