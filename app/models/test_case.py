"""
測試案例資料模型

基於真實的 Lark 表格結構設計，支援擴展性和靈活的欄位映射
"""

from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional, List, Dict, Any, Union, ClassVar
from datetime import datetime

from .lark_types import (
    LarkUser, LarkAttachment, LarkRecord,
    Priority, TestResultStatus,
    parse_lark_user, parse_lark_attachments, parse_lark_records
)


class SimpleAttachment(BaseModel):
    """簡化的附件資料模型，用於前端傳送"""
    file_token: str = Field(..., description="檔案 Token")
    name: str = Field(..., description="檔案名稱")
    size: int = Field(..., description="檔案大小（位元組）")
    type: Optional[str] = Field(None, description="MIME 類型")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "file_token": "NjGkb2iGvonNi3x5cURlPjv2gic",
                "name": "image.png",
                "size": 139246,
                "type": "image/png"
            }
        }
    )


class TestCase(BaseModel):
    """測試案例資料模型"""
    
    # Lark 記錄元資料
    record_id: Optional[str] = Field(None, description="Lark 記錄 ID")
    
    # 核心測試案例欄位
    test_case_number: str = Field(..., description="測試案例編號")
    title: str = Field(..., description="測試案例標題")
    priority: Priority = Field(Priority.MEDIUM, description="優先級")
    
    # 測試內容欄位
    precondition: Optional[str] = Field(None, description="前置條件")
    steps: Optional[str] = Field(None, description="測試步驟")
    expected_result: Optional[str] = Field(None, description="預期結果")
    
    # 執行與管理欄位
    assignee: Optional[LarkUser] = Field(None, description="指派人員")
    test_result: Optional[TestResultStatus] = Field(None, description="測試結果")
    attachments: List[LarkAttachment] = Field(default_factory=list, description="附件列表")
    
    # 關聯欄位
    user_story_map: List[LarkRecord] = Field(default_factory=list, description="User Story Map 關聯")
    tcg: List[LarkRecord] = Field(default_factory=list, description="TCG 關聯")
    parent_record: List[LarkRecord] = Field(default_factory=list, description="父記錄關聯")
    
    # 系統欄位
    team_id: Optional[int] = Field(None, description="所屬團隊 ID")
    created_at: Optional[datetime] = Field(None, description="建立時間")
    updated_at: Optional[datetime] = Field(None, description="更新時間")
    last_sync_at: Optional[datetime] = Field(None, description="最後同步時間")
    
    # 原始 Lark 資料
    raw_fields: Dict[str, Any] = Field(default_factory=dict, description="原始 Lark 欄位資料")
    
    # 欄位映射（使用實際欄位名稱）
    FIELD_IDS: ClassVar[Dict[str, str]] = {
        'test_case_number': 'Test Case Number',
        'title': 'Title',
        'priority': 'Priority',
        'precondition': 'Precondition',
        'steps': 'Steps',
        'expected_result': 'Expected Result',
        'attachments': 'Attachment',
        'assignee': 'Assignee',
        'test_result': 'Test Result',
        'user_story_map': 'User Story Map',
        'tcg': 'TCG',
        'parent_record': '父記錄'
    }
    
    model_config = ConfigDict(
        use_enum_values=True,
        validate_assignment=True,
        json_schema_extra={
            "example": {
                "test_case_number": "TCG-93178.010.010",
                "title": "測試案例標題",
                "priority": "Medium"
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
    def from_lark_record(cls, record: Dict[str, Any], team_id: Optional[int] = None) -> 'TestCase':
        """從 Lark 記錄資料建立 TestCase 實例"""
        record_id = record.get('record_id')
        fields = record.get('fields', {})
        
        # 解析基本欄位
        test_case_data = {
            'record_id': record_id,
            'team_id': team_id,
            'raw_fields': fields.copy(),
            'test_case_number': fields.get(cls.FIELD_IDS['test_case_number'], ''),
            'title': fields.get(cls.FIELD_IDS['title'], ''),
            'precondition': fields.get(cls.FIELD_IDS['precondition']),
            'steps': fields.get(cls.FIELD_IDS['steps']),
            'expected_result': fields.get(cls.FIELD_IDS['expected_result'])
        }
        
        # 解析優先級
        priority_raw = fields.get(cls.FIELD_IDS['priority'])
        if priority_raw and priority_raw in [p.value for p in Priority]:
            test_case_data['priority'] = Priority(priority_raw)
        
        # 解析測試結果
        test_result_raw = fields.get(cls.FIELD_IDS['test_result'])
        if test_result_raw and test_result_raw in [s.value for s in TestResultStatus]:
            test_case_data['test_result'] = TestResultStatus(test_result_raw)
        
        # 解析人員欄位
        assignee_raw = fields.get(cls.FIELD_IDS['assignee'])
        test_case_data['assignee'] = parse_lark_user(assignee_raw)
        
        # 解析附件欄位
        attachments_raw = fields.get(cls.FIELD_IDS['attachments'])
        test_case_data['attachments'] = parse_lark_attachments(attachments_raw)
        
        # 解析關聯記錄欄位
        test_case_data['user_story_map'] = parse_lark_records(
            fields.get(cls.FIELD_IDS['user_story_map'])
        )
        test_case_data['tcg'] = parse_lark_records(
            fields.get(cls.FIELD_IDS['tcg'])
        )
        test_case_data['parent_record'] = parse_lark_records(
            fields.get(cls.FIELD_IDS['parent_record'])
        )
        
        # 解析系統時間戳欄位
        created_time = record.get('created_time')
        if created_time:
            # Lark 時間戳是以毫秒為單位的 Unix 時間戳
            test_case_data['created_at'] = datetime.fromtimestamp(created_time / 1000)
        
        last_modified_time = record.get('last_modified_time')
        if last_modified_time:
            # Lark 時間戳是以毫秒為單位的 Unix 時間戳
            test_case_data['updated_at'] = datetime.fromtimestamp(last_modified_time / 1000)
        
        return cls(**test_case_data)
    
    def to_lark_fields(self) -> Dict[str, Any]:
        """轉換為 Lark API 所需的欄位格式"""
        lark_fields = {}
        
        if self.test_case_number:
            lark_fields[self.FIELD_IDS['test_case_number']] = self.test_case_number
        if self.title:
            lark_fields[self.FIELD_IDS['title']] = self.title
        if self.precondition:
            lark_fields[self.FIELD_IDS['precondition']] = self.precondition
        if self.steps:
            lark_fields[self.FIELD_IDS['steps']] = self.steps
        if self.expected_result:
            lark_fields[self.FIELD_IDS['expected_result']] = self.expected_result
        if self.priority:
            priority_value = self.priority.value if hasattr(self.priority, 'value') else self.priority
            lark_fields[self.FIELD_IDS['priority']] = priority_value
        if self.test_result:
            test_result_value = self.test_result.value if hasattr(self.test_result, 'value') else self.test_result
            lark_fields[self.FIELD_IDS['test_result']] = test_result_value
        
        # 處理 TCG 欄位
        if self.tcg is not None:
            # TCG 欄位是 Duplex Link 類型，需要字串陣列
            tcg_record_ids = []
            for tcg_record in self.tcg:
                # 使用 record_ids[0] 而不是 record_id
                record_id = tcg_record.record_ids[0] if tcg_record.record_ids else None
                if record_id:
                    tcg_record_ids.append(record_id)
            lark_fields[self.FIELD_IDS['tcg']] = tcg_record_ids
        
        # 處理附件欄位
        if self.attachments is not None:
            # 附件欄位是 Attachment 類型，需要 [{"file_token": token}] 陣列
            attachment_items = []
            for attachment in self.attachments:
                token = getattr(attachment, 'file_token', None)
                if token:
                    attachment_items.append({'file_token': token})
            # 允許傳空陣列以清空附件
            lark_fields[self.FIELD_IDS['attachments']] = attachment_items
        
        return lark_fields
    
    # 便利方法
    def get_tcg_number(self) -> Optional[str]:
        """取得 TCG 編號"""
        if self.tcg:
            return self.tcg[0].display_text
        return None
    
    def get_tcg_numbers(self) -> List[str]:
        """取得所有 TCG 編號列表"""
        tcg_numbers = []
        for tcg_record in self.tcg:
            if tcg_record.text_arr:
                tcg_numbers.extend(tcg_record.text_arr)
            elif tcg_record.text:
                tcg_numbers.append(tcg_record.text)
        return tcg_numbers
    
    def get_tcg_display(self) -> str:
        """取得 TCG 顯示文字（多個 TCG 用逗號分隔）"""
        tcg_numbers = self.get_tcg_numbers()
        return ", ".join(tcg_numbers) if tcg_numbers else ""
    
    def get_user_story(self) -> Optional[str]:
        """取得 User Story"""
        if self.user_story_map:
            return self.user_story_map[0].display_text
        return None
    
    def has_attachments(self) -> bool:
        """檢查是否有附件"""
        return len(self.attachments) > 0
    
    def get_attachment_count(self) -> int:
        """取得附件數量"""
        return len(self.attachments)
    
    def is_passed(self) -> bool:
        """檢查是否測試通過"""
        return self.test_result == TestResultStatus.PASSED
    
    def is_failed(self) -> bool:
        """檢查是否測試失敗"""
        return self.test_result == TestResultStatus.FAILED
    
    def needs_retest(self) -> bool:
        """檢查是否需要重測"""
        return self.test_result == TestResultStatus.RETEST
    
    def get_steps_list(self) -> List[str]:
        """將測試步驟拆解為列表"""
        if not self.steps:
            return []
        
        lines = self.steps.strip().split('\n')
        steps = []
        for line in lines:
            line = line.strip()
            if line and (line[0].isdigit() or line.startswith('-') or line.startswith('•')):
                steps.append(line)
        
        return steps if steps else [self.steps]


# API 交互模型
class TestCaseCreate(BaseModel):
    """建立測試案例請求模型"""
    test_case_number: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    priority: Optional[Priority] = Priority.MEDIUM
    precondition: Optional[str] = None
    steps: Optional[str] = None
    expected_result: Optional[str] = None
    assignee: Optional[LarkUser] = None
    test_result: Optional[TestResultStatus] = None
    attachments: Optional[List[SimpleAttachment]] = None
    user_story_map: Optional[List[LarkRecord]] = None
    tcg: Optional[List[LarkRecord]] = None
    parent_record: Optional[LarkRecord] = None


class TestCaseUpdate(BaseModel):
    """更新測試案例請求模型"""
    test_case_number: Optional[str] = Field(None, min_length=1)
    title: Optional[str] = Field(None, min_length=1)
    priority: Optional[Priority] = None
    precondition: Optional[str] = None
    steps: Optional[str] = None
    expected_result: Optional[str] = None
    assignee: Optional[LarkUser] = None
    test_result: Optional[TestResultStatus] = None
    attachments: Optional[List[SimpleAttachment]] = None
    user_story_map: Optional[List[LarkRecord]] = None
    tcg: Optional[Union[str, List[LarkRecord]]] = None
    parent_record: Optional[LarkRecord] = None


class TestCaseResponse(TestCase):
    """測試案例回應模型"""
    pass


class TestCaseBatchOperation(BaseModel):
    """測試案例批次操作模型"""
    operation: str = Field(..., description="操作類型：delete, update_tcg, update_priority, update_assignee")
    record_ids: List[str] = Field(..., description="要操作的記錄 ID 列表")
    update_data: Optional[Dict[str, Any]] = Field(None, description="更新資料（刪除操作時不需要）")


class TestCaseBatchResponse(BaseModel):
    """測試案例批次操作回應模型"""
    success: bool = Field(..., description="操作是否成功")
    processed_count: int = Field(..., description="處理的記錄數")
    success_count: int = Field(..., description="成功的記錄數")
    error_count: int = Field(..., description="失敗的記錄數")
    error_messages: List[str] = Field([], description="錯誤訊息列表")


# 欄位映射類別
class TestCaseFieldMapping:
    """測試案例欄位映射定義"""
    
    @classmethod
    def get_all_field_ids(cls) -> Dict[str, str]:
        """取得所有欄位的 ID 映射"""
        return TestCase.FIELD_IDS
