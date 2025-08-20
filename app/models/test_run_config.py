"""
測試執行配置模型

用於管理團隊的多個測試執行輪次，每個測試執行對應一個 Lark 表格
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime
from enum import Enum


class TestRunStatus(str, Enum):
    """測試執行狀態"""
    ACTIVE = "active"          # 進行中
    COMPLETED = "completed"    # 已完成
    DRAFT = "draft"           # 草稿
    ARCHIVED = "archived"     # 已歸檔


class TestRunConfig(BaseModel):
    """測試執行配置"""
    id: Optional[int] = Field(None, description="配置 ID")
    team_id: int = Field(..., description="所屬團隊 ID")
    name: str = Field(..., description="測試執行名稱", max_length=100)
    description: Optional[str] = Field(None, description="測試執行描述")
    
    # Lark 表格配置
    table_id: str = Field(..., description="Lark 測試執行表格 ID")
    
    # 測試執行元資料
    test_version: Optional[str] = Field(None, description="測試版本")
    test_environment: Optional[str] = Field(None, description="測試環境")
    build_number: Optional[str] = Field(None, description="建置編號")
    
    # 狀態與時間
    status: TestRunStatus = Field(TestRunStatus.ACTIVE, description="執行狀態")
    start_date: Optional[datetime] = Field(None, description="開始日期")
    end_date: Optional[datetime] = Field(None, description="結束日期")
    
    # 統計資訊
    total_test_cases: int = Field(0, description="總測試案例數")
    executed_cases: int = Field(0, description="已執行案例數")
    passed_cases: int = Field(0, description="通過案例數")
    failed_cases: int = Field(0, description="失敗案例數")
    
    # 系統欄位
    created_at: Optional[datetime] = Field(None, description="建立時間")
    updated_at: Optional[datetime] = Field(None, description="更新時間")
    last_sync_at: Optional[datetime] = Field(None, description="最後同步時間")
    
    @validator('table_id')
    def validate_table_id(cls, v):
        if not v or not v.startswith('tbl'):
            raise ValueError('Table ID must start with "tbl"')
        return v
    
    @validator('name')
    def validate_name(cls, v):
        if not v or len(v.strip()) < 2:
            raise ValueError('Name must be at least 2 characters long')
        return v.strip()
    
    def get_execution_rate(self) -> float:
        """計算執行率"""
        if self.total_test_cases == 0:
            return 0.0
        return (self.executed_cases / self.total_test_cases) * 100
    
    def get_pass_rate(self) -> float:
        """計算通過率（基於已執行案例）"""
        if self.executed_cases == 0:
            return 0.0
        return (self.passed_cases / self.executed_cases) * 100
    
    def get_total_pass_rate(self) -> float:
        """計算總通過率（基於所有案例）"""
        if self.total_test_cases == 0:
            return 0.0
        return (self.passed_cases / self.total_test_cases) * 100
    
    def is_completed(self) -> bool:
        """檢查是否已完成"""
        return self.status == TestRunStatus.COMPLETED
    
    def is_in_progress(self) -> bool:
        """檢查是否進行中"""
        return self.status == TestRunStatus.ACTIVE


class TestRunConfigCreate(BaseModel):
    """建立測試執行配置的資料模型"""
    team_id: int = Field(..., description="所屬團隊 ID")
    name: str = Field(..., description="測試執行名稱", max_length=100)
    description: Optional[str] = Field(None, description="測試執行描述")
    table_id: str = Field(..., description="Lark 測試執行表格 ID")
    test_version: Optional[str] = Field(None, description="測試版本")
    test_environment: Optional[str] = Field(None, description="測試環境")
    build_number: Optional[str] = Field(None, description="建置編號")
    status: TestRunStatus = Field(TestRunStatus.DRAFT, description="初始狀態")
    start_date: Optional[datetime] = Field(None, description="開始日期")


class TestRunConfigUpdate(BaseModel):
    """更新測試執行配置的資料模型"""
    name: Optional[str] = Field(None, description="測試執行名稱", max_length=100)
    description: Optional[str] = Field(None, description="測試執行描述")
    table_id: Optional[str] = Field(None, description="Lark 測試執行表格 ID")
    test_version: Optional[str] = Field(None, description="測試版本")
    test_environment: Optional[str] = Field(None, description="測試環境")
    build_number: Optional[str] = Field(None, description="建置編號")
    status: Optional[TestRunStatus] = Field(None, description="執行狀態")
    start_date: Optional[datetime] = Field(None, description="開始日期")
    end_date: Optional[datetime] = Field(None, description="結束日期")


class TestRunConfigResponse(TestRunConfig):
    """測試執行配置回應模型"""
    pass


class TestRunConfigSummary(BaseModel):
    """測試執行配置摘要（用於列表顯示）"""
    id: int = Field(..., description="配置 ID")
    name: str = Field(..., description="測試執行名稱")
    test_version: Optional[str] = Field(None, description="測試版本")
    status: TestRunStatus = Field(..., description="執行狀態")
    execution_rate: float = Field(..., description="執行率")
    pass_rate: float = Field(..., description="通過率")
    total_test_cases: int = Field(..., description="總案例數")
    executed_cases: int = Field(..., description="已執行案例數")
    start_date: Optional[datetime] = Field(None, description="開始日期")
    end_date: Optional[datetime] = Field(None, description="結束日期")
    created_at: datetime = Field(..., description="建立時間")


class TestRunConfigStatistics(BaseModel):
    """測試執行統計資訊"""
    total_configs: int = Field(..., description="總配置數")
    active_configs: int = Field(..., description="進行中配置數")
    completed_configs: int = Field(..., description="已完成配置數")
    draft_configs: int = Field(..., description="草稿配置數")
    
    total_test_cases: int = Field(..., description="總測試案例數")
    total_executed_cases: int = Field(..., description="總已執行案例數")
    total_passed_cases: int = Field(..., description="總通過案例數")
    total_failed_cases: int = Field(..., description="總失敗案例數")
    
    overall_execution_rate: float = Field(..., description="整體執行率")
    overall_pass_rate: float = Field(..., description="整體通過率")
    
    @classmethod
    def from_configs(cls, configs: List[TestRunConfig]) -> 'TestRunConfigStatistics':
        """從配置列表建立統計資訊"""
        total_configs = len(configs)
        active_configs = len([c for c in configs if c.status == TestRunStatus.ACTIVE])
        completed_configs = len([c for c in configs if c.status == TestRunStatus.COMPLETED])
        draft_configs = len([c for c in configs if c.status == TestRunStatus.DRAFT])
        
        total_test_cases = sum(c.total_test_cases for c in configs)
        total_executed_cases = sum(c.executed_cases for c in configs)
        total_passed_cases = sum(c.passed_cases for c in configs)
        total_failed_cases = sum(c.failed_cases for c in configs)
        
        overall_execution_rate = (total_executed_cases / total_test_cases * 100) if total_test_cases > 0 else 0
        overall_pass_rate = (total_passed_cases / total_executed_cases * 100) if total_executed_cases > 0 else 0
        
        return cls(
            total_configs=total_configs,
            active_configs=active_configs,
            completed_configs=completed_configs,
            draft_configs=draft_configs,
            total_test_cases=total_test_cases,
            total_executed_cases=total_executed_cases,
            total_passed_cases=total_passed_cases,
            total_failed_cases=total_failed_cases,
            overall_execution_rate=overall_execution_rate,
            overall_pass_rate=overall_pass_rate
        )