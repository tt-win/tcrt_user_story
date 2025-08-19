"""
測試執行資料模型

基於真實的 Lark 表格結構設計，支援執行記錄和雙附件系統
"""

from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional, List, Dict, Any, Tuple, ClassVar
from datetime import datetime

from .lark_types import (
    LarkUser, LarkAttachment, LarkFieldMapping,
    Priority, TestResultStatus,
    parse_lark_user, parse_lark_attachments
)


class TestRunFieldMapping:
    """測試執行欄位映射定義"""
    
    # 基於真實 Lark 表格欄位名稱映射
    FIELD_MAPPINGS = {
        'test_case_number': LarkFieldMapping(
            field_id='Test Case Number',
            field_name='Test Case Number',
            field_type='1',  # Text
            mapping_field='test_case_number'
        ),
        'title': LarkFieldMapping(
            field_id='Title',
            field_name='Title',
            field_type='1',  # Text
            mapping_field='title'
        ),
        'precondition': LarkFieldMapping(
            field_id='Precondition',
            field_name='Precondition',
            field_type='1',  # Text
            mapping_field='precondition'
        ),
        'steps': LarkFieldMapping(
            field_id='Steps',
            field_name='Steps',
            field_type='1',  # Text
            mapping_field='steps'
        ),
        'expected_result': LarkFieldMapping(
            field_id='Expected Result',
            field_name='Expected Result',
            field_type='1',  # Text
            mapping_field='expected_result'
        ),
        'attachments': LarkFieldMapping(
            field_id='Attachment',
            field_name='Attachment',
            field_type='17',  # Attachment
            mapping_field='attachments'
        ),
        'assignee': LarkFieldMapping(
            field_id='Assignee',
            field_name='Assignee',
            field_type='11',  # User
            mapping_field='assignee'
        ),
        'priority': LarkFieldMapping(
            field_id='Priority',
            field_name='Priority',
            field_type='3',  # SingleSelect
            mapping_field='priority'
        ),
        'test_result': LarkFieldMapping(
            field_id='Test Result',
            field_name='Test Result',
            field_type='3',  # SingleSelect
            mapping_field='test_result'
        ),
        'execution_results': LarkFieldMapping(
            field_id='Execution Result',
            field_name='Execution Result',
            field_type='17',  # Attachment
            mapping_field='execution_results'
        )
    }
    
    @classmethod
    def get_field_id(cls, model_field: str) -> Optional[str]:
        """取得模型欄位對應的 Lark 欄位 ID"""
        mapping = cls.FIELD_MAPPINGS.get(model_field)
        return mapping.field_id if mapping else None
    
    @classmethod
    def get_field_name(cls, model_field: str) -> Optional[str]:
        """取得模型欄位對應的 Lark 欄位名稱"""
        mapping = cls.FIELD_MAPPINGS.get(model_field)
        return mapping.field_name if mapping else None
    
    @classmethod
    def get_all_field_ids(cls) -> Dict[str, str]:
        """取得所有欄位的 ID 映射"""
        return {field: mapping.field_id for field, mapping in cls.FIELD_MAPPINGS.items()}


class TestRun(BaseModel):
    """
    測試執行資料模型
    
    基於真實 Lark 表格結構設計，包含雙重附件系統
    """
    
    # Lark 記錄元資料
    record_id: Optional[str] = Field(None, description="Lark 記錄 ID")
    
    # 核心測試執行欄位
    test_case_number: str = Field(..., description="測試案例編號")
    title: str = Field(..., description="測試標題")
    priority: Priority = Field(Priority.MEDIUM, description="優先級")
    
    # 測試內容欄位（從 TestCase 繼承相同的欄位）
    precondition: Optional[str] = Field(None, description="前置條件")
    steps: Optional[str] = Field(None, description="測試步驟")
    expected_result: Optional[str] = Field(None, description="預期結果")
    
    # 執行管理欄位
    assignee: Optional[LarkUser] = Field(None, description="執行人員")
    test_result: Optional[TestResultStatus] = Field(None, description="測試結果")
    
    # 附件欄位（TestRun 有雙重附件系統）
    attachments: List[LarkAttachment] = Field(default_factory=list, description="一般附件")
    execution_results: List[LarkAttachment] = Field(default_factory=list, description="執行結果附件（截圖等）")
    
    # 執行元資料
    executed_at: Optional[datetime] = Field(None, description="執行時間")
    execution_duration: Optional[int] = Field(None, description="執行時長（秒）")
    
    # 擴展欄位
    team_id: Optional[int] = Field(None, description="所屬團隊 ID")
    related_test_case_number: Optional[str] = Field(None, description="關聯測試案例編號")
    test_environment: Optional[str] = Field(None, description="測試環境")
    build_version: Optional[str] = Field(None, description="測試版本")
    
    # 系統欄位
    created_at: Optional[datetime] = Field(None, description="建立時間")
    updated_at: Optional[datetime] = Field(None, description="更新時間")
    last_sync_at: Optional[datetime] = Field(None, description="最後同步時間")
    
    # 原始 Lark 資料（用於除錯或進階功能）
    raw_fields: Dict[str, Any] = Field(default_factory=dict, description="原始 Lark 欄位資料")
    
    model_config = ConfigDict(
        use_enum_values=True,
        validate_assignment=True,
        json_schema_extra={
            "example": {
                "test_case_number": "TCG-100572.010.010",
                "title": "登入流程 - 帳號密碼驗證",
                "priority": "Medium",
                "precondition": "參考 TCG-100558.010.010 測試案例 - 登入頁面 - 正確顯示",
                "steps": "1. 開啟登入頁面",
                "expected_result": "1. 登入流程正確執行\n2. 登入後正確跳轉至主頁面且各項功能正常運作",
                "test_result": "Passed",
                "team_id": 1
            }
        }
    )
    
    @field_validator('test_case_number')
    @classmethod
    def validate_test_case_number(cls, v):
        if not v:
            raise ValueError('Test case number cannot be empty')
        return v.strip()
    
    @field_validator('title')
    @classmethod
    def validate_title(cls, v):
        if not v or not v.strip():
            raise ValueError('Title cannot be empty')
        return v.strip()
    
    @classmethod
    def from_lark_record(cls, record: Dict[str, Any], team_id: Optional[int] = None) -> 'TestRun':
        """
        從 Lark 記錄資料建立 TestRun 實例
        
        Args:
            record: Lark API 返回的記錄資料
            team_id: 所屬團隊 ID
            
        Returns:
            TestRun 實例
        """
        record_id = record.get('record_id')
        fields = record.get('fields', {})
        
        # 基礎欄位
        test_run_data = {
            'record_id': record_id,
            'team_id': team_id,
            'raw_fields': fields.copy()
        }
        
        # 解析基本欄位
        field_mappings = TestRunFieldMapping.FIELD_MAPPINGS
        
        test_run_data['test_case_number'] = fields.get(field_mappings['test_case_number'].field_id, '')
        test_run_data['title'] = fields.get(field_mappings['title'].field_id, '')
        test_run_data['precondition'] = fields.get(field_mappings['precondition'].field_id)
        test_run_data['steps'] = fields.get(field_mappings['steps'].field_id)
        test_run_data['expected_result'] = fields.get(field_mappings['expected_result'].field_id)
        
        # 解析優先級
        priority_raw = fields.get(field_mappings['priority'].field_id)
        if priority_raw and priority_raw in [p.value for p in Priority]:
            test_run_data['priority'] = Priority(priority_raw)
        
        # 解析測試結果
        test_result_raw = fields.get(field_mappings['test_result'].field_id)
        if test_result_raw and test_result_raw in [s.value for s in TestResultStatus]:
            test_run_data['test_result'] = TestResultStatus(test_result_raw)
        
        # 解析人員欄位
        assignee_raw = fields.get(field_mappings['assignee'].field_id)
        test_run_data['assignee'] = parse_lark_user(assignee_raw)
        
        # 解析附件欄位
        attachments_raw = fields.get(field_mappings['attachments'].field_id)
        test_run_data['attachments'] = parse_lark_attachments(attachments_raw)
        
        # 解析執行結果附件
        execution_results_raw = fields.get(field_mappings['execution_results'].field_id)
        test_run_data['execution_results'] = parse_lark_attachments(execution_results_raw)
        
        return cls(**test_run_data)
    
    def to_lark_fields(self) -> Dict[str, Any]:
        """
        轉換為 Lark API 所需的欄位格式
        
        Returns:
            Lark API 欄位資料
        """
        field_mappings = TestRunFieldMapping.FIELD_MAPPINGS
        lark_fields = {}
        
        # 基本欄位
        if self.test_case_number:
            lark_fields[field_mappings['test_case_number'].field_id] = self.test_case_number
        if self.title:
            lark_fields[field_mappings['title'].field_id] = self.title
        if self.precondition:
            lark_fields[field_mappings['precondition'].field_id] = self.precondition
        if self.steps:
            lark_fields[field_mappings['steps'].field_id] = self.steps
        if self.expected_result:
            lark_fields[field_mappings['expected_result'].field_id] = self.expected_result
        
        # 選擇欄位
        if self.priority:
            priority_value = self.priority.value if hasattr(self.priority, 'value') else self.priority
            lark_fields[field_mappings['priority'].field_id] = priority_value
        if self.test_result:
            test_result_value = self.test_result.value if hasattr(self.test_result, 'value') else self.test_result
            lark_fields[field_mappings['test_result'].field_id] = test_result_value
        
        # 人員欄位
        if self.assignee:
            lark_fields[field_mappings['assignee'].field_id] = [self.assignee.model_dump()]
        
        return lark_fields
    
    # TestRun 特有的便利方法
    def is_executed(self) -> bool:
        """檢查是否已執行（有測試結果）"""
        return self.test_result is not None
    
    def is_passed(self) -> bool:
        """檢查是否測試通過"""
        return self.test_result == TestResultStatus.PASSED
    
    def is_failed(self) -> bool:
        """檢查是否測試失敗"""
        return self.test_result == TestResultStatus.FAILED
    
    def needs_retest(self) -> bool:
        """檢查是否需要重測"""
        return self.test_result == TestResultStatus.RETEST
    
    def has_execution_results(self) -> bool:
        """檢查是否有執行結果附件"""
        return len(self.execution_results) > 0
    
    def get_execution_result_count(self) -> int:
        """取得執行結果附件數量"""
        return len(self.execution_results)
    
    def get_total_attachment_count(self) -> int:
        """取得總附件數量（一般附件 + 執行結果附件）"""
        return len(self.attachments) + len(self.execution_results)
    
    def get_execution_screenshots(self) -> List[LarkAttachment]:
        """取得執行結果中的截圖檔案"""
        return [att for att in self.execution_results if att.is_image]
    
    def get_steps_list(self) -> List[str]:
        """將測試步驟拆解為列表"""
        if not self.steps:
            return []
        
        # 簡單的步驟分解邏輯
        lines = self.steps.strip().split('\n')
        steps = []
        for line in lines:
            line = line.strip()
            if line and (line[0].isdigit() or line.startswith('-') or line.startswith('•')):
                steps.append(line)
        
        return steps if steps else [self.steps]
    
    def get_execution_summary(self) -> Dict[str, Any]:
        """取得執行摘要資訊"""
        result_value = None
        if self.test_result:
            result_value = self.test_result.value if hasattr(self.test_result, 'value') else self.test_result
        
        return {
            'test_case_number': self.test_case_number,
            'title': self.title,
            'result': result_value,
            'executor': self.assignee.display_name if self.assignee else None,
            'executed_at': self.executed_at,
            'screenshot_count': len(self.get_execution_screenshots()),
            'total_attachments': self.get_total_attachment_count()
        }


# API 交互模型
class TestRunCreate(BaseModel):
    """建立測試執行請求模型"""
    test_case_number: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    priority: Optional[Priority] = Priority.MEDIUM
    precondition: Optional[str] = None
    steps: Optional[str] = None
    expected_result: Optional[str] = None
    assignee_email: Optional[str] = None
    test_environment: Optional[str] = None
    build_version: Optional[str] = None
    related_test_case_number: Optional[str] = None


class TestRunUpdate(BaseModel):
    """更新測試執行請求模型"""
    title: Optional[str] = Field(None, min_length=1)
    priority: Optional[Priority] = None
    precondition: Optional[str] = None
    steps: Optional[str] = None
    expected_result: Optional[str] = None
    test_result: Optional[TestResultStatus] = None
    assignee_email: Optional[str] = None
    test_environment: Optional[str] = None
    build_version: Optional[str] = None
    execution_duration: Optional[int] = None


class TestRunResponse(BaseModel):
    """測試執行回應模型"""
    record_id: str
    test_case_number: str
    title: str
    priority: str
    test_result: Optional[str]
    assignee_name: Optional[str]
    attachment_count: int
    execution_result_count: int
    total_attachment_count: int
    executed_at: Optional[datetime]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    last_sync_at: Optional[datetime]


class TestRunFilter(BaseModel):
    """測試執行過濾條件"""
    title: Optional[str] = Field(None, description="標題搜尋（模糊）")
    test_case_number: Optional[str] = Field(None, description="測試案例編號")
    priority: Optional[Priority] = Field(None, description="優先級")
    test_result: Optional[TestResultStatus] = Field(None, description="測試結果")
    assignee_email: Optional[str] = Field(None, description="執行人員 Email")
    test_environment: Optional[str] = Field(None, description="測試環境")
    has_execution_results: Optional[bool] = Field(None, description="是否有執行結果")
    executed_only: Optional[bool] = Field(None, description="僅顯示已執行項目")


class TestRunStatistics(BaseModel):
    """測試執行統計資訊"""
    total_runs: int = Field(..., description="總執行數")
    executed_runs: int = Field(..., description="已執行數")
    passed_runs: int = Field(..., description="通過數")
    failed_runs: int = Field(..., description="失敗數")
    retest_runs: int = Field(..., description="重測數")
    not_available_runs: int = Field(..., description="不適用數")
    
    @property
    def execution_rate(self) -> float:
        """執行完成率（百分比）"""
        if self.total_runs == 0:
            return 0.0
        return round((self.executed_runs / self.total_runs) * 100, 2)
    
    @property
    def pass_rate(self) -> float:
        """通過率（基於已執行數，百分比）"""
        if self.executed_runs == 0:
            return 0.0
        return round((self.passed_runs / self.executed_runs) * 100, 2)
    
    @property
    def total_pass_rate(self) -> float:
        """總通過率（基於總執行數，百分比）"""
        if self.total_runs == 0:
            return 0.0
        return round((self.passed_runs / self.total_runs) * 100, 2)