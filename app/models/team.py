from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum


class TeamStatus(str, Enum):
    """團隊狀態"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class JiraConfig(BaseModel):
    """JIRA 配置"""
    project_key: Optional[str] = Field(None, description="JIRA 專案 Key")
    default_assignee: Optional[str] = Field(None, description="預設指派人")
    issue_type: str = Field("Bug", description="預設 Issue 類型")
    
    @field_validator('project_key')
    @classmethod
    def validate_project_key(cls, v):
        if v and (len(v) < 2 or len(v) > 10):
            raise ValueError('Project key must be between 2 and 10 characters')
        return v


class TeamSettings(BaseModel):
    """團隊設定"""
    default_priority: str = Field("Medium", description="預設優先級")
    custom_fields: Dict[str, Any] = Field(default_factory=dict, description="自訂欄位")


class Team(BaseModel):
    """團隊資料模型"""
    id: Optional[int] = Field(None, description="團隊 ID")
    name: str = Field(..., min_length=1, max_length=100, description="團隊名稱")
    description: Optional[str] = Field(None, max_length=500, description="團隊描述")

    # JIRA 相關配置
    jira_config: Optional[JiraConfig] = Field(None, description="JIRA 配置")
    
    # 團隊設定
    settings: TeamSettings = Field(default_factory=TeamSettings, description="團隊設定")
    
    # 狀態與時間
    status: TeamStatus = Field(TeamStatus.ACTIVE, description="團隊狀態")
    created_at: Optional[datetime] = Field(None, description="建立時間")
    updated_at: Optional[datetime] = Field(None, description="更新時間")
    
    # 統計資訊
    test_case_count: int = Field(0, description="測試案例數量")
    last_sync_at: Optional[datetime] = Field(None, description="最後同步時間")
    
    model_config = ConfigDict(
        use_enum_values=True,
        validate_assignment=True,
        extra="forbid",
        json_schema_extra={
            "example": {
                "name": "Frontend Team",
                "description": "前端開發測試團隊",
                "jira_config": {
                    "project_key": "FE",
                    "default_assignee": "john.doe",
                    "issue_type": "Bug"
                },
                "settings": {
                    "default_priority": "High"
                },
                "status": "active"
            }
        }
    )
    
    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        if not v.strip():
            raise ValueError('Team name cannot be empty')
        return v.strip()
    
    def is_jira_configured(self) -> bool:
        """檢查 JIRA 是否已配置"""
        return bool(self.jira_config and self.jira_config.project_key)


class TeamCreate(BaseModel):
    """建立團隊請求模型"""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    jira_config: Optional[JiraConfig] = None
    settings: Optional[TeamSettings] = None


class TeamUpdate(BaseModel):
    """更新團隊請求模型"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    jira_config: Optional[JiraConfig] = None
    settings: Optional[TeamSettings] = None
    status: Optional[TeamStatus] = None


class TeamResponse(BaseModel):
    """團隊回應模型"""
    id: int
    name: str
    description: Optional[str]
    status: str
    test_case_count: int
    last_sync_at: Optional[datetime]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    is_lark_configured: bool
    is_jira_configured: bool