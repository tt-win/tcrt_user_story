from pydantic import BaseModel, Field, HttpUrl, field_validator, ConfigDict
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum


class TeamStatus(str, Enum):
    """團隊狀態"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class LarkRepoConfig(BaseModel):
    """Lark Repository 配置"""
    wiki_token: str = Field(..., description="Lark Wiki Token")
    test_case_table_id: str = Field(..., description="測試案例表格 ID")
    # 移除 test_run_table_id，改用 TestRunConfig 管理多個 test run
    
    @field_validator('wiki_token')
    @classmethod
    def validate_wiki_token(cls, v):
        if not v or len(v) < 10:
            raise ValueError('Wiki token must be at least 10 characters long')
        return v
    
    @field_validator('test_case_table_id')
    @classmethod
    def validate_test_case_table_id(cls, v):
        if not v or not v.startswith('tbl'):
            raise ValueError('Test case table ID must start with "tbl"')
        return v
    


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
    enable_notifications: bool = Field(True, description="啟用通知")
    auto_create_bugs: bool = Field(False, description="自動建立 Bug")
    default_priority: str = Field("Medium", description="預設優先級")
    custom_fields: Dict[str, Any] = Field(default_factory=dict, description="自訂欄位")


class Team(BaseModel):
    """團隊資料模型"""
    id: Optional[int] = Field(None, description="團隊 ID")
    name: str = Field(..., min_length=1, max_length=100, description="團隊名稱")
    description: Optional[str] = Field(None, max_length=500, description="團隊描述")
    
    # Lark 相關配置
    lark_config: LarkRepoConfig = Field(..., description="Lark Repository 配置")
    
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
                "lark_config": {
                    "wiki_token": "Q4XxwaS2Cif80DkAku9lMKuAgof",
                    "test_case_table_id": "tblEAg8srqYs0rzi",
                    "test_run_table_id": "tblRun123456789"
                },
                "jira_config": {
                    "project_key": "FE",
                    "default_assignee": "john.doe",
                    "issue_type": "Bug"
                },
                "settings": {
                    "enable_notifications": True,
                    "auto_create_bugs": False,
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
    
    def is_lark_configured(self) -> bool:
        """檢查 Lark 是否已配置"""
        return bool(self.lark_config.wiki_token and self.lark_config.test_case_table_id)
    
    def is_jira_configured(self) -> bool:
        """檢查 JIRA 是否已配置"""
        return bool(self.jira_config and self.jira_config.project_key)
    
    def get_lark_url(self) -> str:
        """取得 Lark 表格 URL"""
        if not self.is_lark_configured():
            return ""
        return f"https://larksuite.com/wiki/{self.lark_config.wiki_token}?table={self.lark_config.test_case_table_id}"


class TeamCreate(BaseModel):
    """建立團隊請求模型"""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    lark_config: LarkRepoConfig
    jira_config: Optional[JiraConfig] = None
    settings: Optional[TeamSettings] = None


class TeamUpdate(BaseModel):
    """更新團隊請求模型"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    lark_config: Optional[LarkRepoConfig] = None
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