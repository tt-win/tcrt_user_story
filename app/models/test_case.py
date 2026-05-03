"""
測試案例資料模型

基於真實的 Lark 表格結構設計，支援擴展性和靈活的欄位映射
"""

from enum import Enum
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional, List, Dict, Any, Union, ClassVar
from datetime import datetime

from .lark_types import (
    LarkUser,
    LarkAttachment,
    LarkRecord,
    Priority,
    TestResultStatus,
    parse_lark_user,
    parse_lark_attachments,
    parse_lark_records,
)
from .test_run_scope import CleanupSummary


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
                "type": "image/png",
            }
        }
    )


class TestDataCategory(str, Enum):
    """Test Data 類別：給 LLM / 自動化工具對齊語義。"""

    TEXT = "text"               # 一般字串輸入（預設）
    NUMBER = "number"           # 整數 / 浮點數
    CREDENTIAL = "credential"   # 帳號 / 密碼 / token（敏感）
    EMAIL = "email"             # email 地址
    URL = "url"                 # URL / endpoint
    IDENTIFIER = "identifier"   # ID / 編號（環境相依）
    DATE = "date"               # 日期 / 時間 / timestamp
    JSON = "json"               # JSON payload / 結構化
    OTHER = "other"             # 無法歸類（fallback）


class TestDataItem(BaseModel):
    """測試資料項目模型

    Response/read 路徑保持寬鬆（不驗證長度），避免舊資料解析失敗；
    input normalization 與限制請呼叫 normalize_test_data_items()。
    """

    id: Optional[str] = Field(None, description="Test Data 唯一識別碼，未提供則由 server 產生")
    name: str = Field(..., min_length=1, description="顯示名稱")
    category: TestDataCategory = Field(TestDataCategory.TEXT, description="類別；舊資料或未提供時預設 text")
    value: str = Field(..., description="內容值（允許空字串）")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "name": "valid_email",
                "category": "email",
                "value": "qa@example.com",
            }
        }
    )

    @field_validator("category", mode="before")
    @classmethod
    def _default_category(cls, v):
        # 容忍舊資料：None / 空字串 / 未知值一律退回 text
        if v is None or v == "":
            return TestDataCategory.TEXT
        if isinstance(v, TestDataCategory):
            return v
        try:
            return TestDataCategory(str(v).lower())
        except ValueError:
            return TestDataCategory.TEXT


# Test Data 寫入限制
MAX_TEST_DATA_NAME_LEN = 500
MAX_TEST_DATA_VALUE_LEN = 100_000
MAX_TEST_DATA_ITEMS = 100

import re as _re
import uuid as _uuid

# C0 控制字元（保留 \t \n \r）
_TD_CONTROL_CHARS_RE = _re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# 雙向控制字元 (Trojan Source 攻擊向量)
_TD_BIDI_OVERRIDE_RE = _re.compile(r"[\u202a-\u202e\u2066-\u2069]")
# 純 NULL byte（value 的唯一移除目標）
_TD_NULL_BYTE_RE = _re.compile(r"\x00")


def normalize_test_data_items(items: Optional[List["TestDataItem"]]) -> List["TestDataItem"]:
    """在寫入 DB 前對 test_data 做正規化與驗證。

    規則：
    - name：strip 前後空白、移除 NULL/C0 控制字元/bidi override/換行；非空；長度上限
    - value：僅移除 NULL byte（保留 Unicode、emoji、RTL、換行、tab 等所有測試可能需要的字元）；長度上限
    - id：未提供則產生 UUID4
    - 清單上限、同清單內 name 唯一（case-sensitive）

    違規時 raise ValueError，由 API 層轉為 400。
    """
    if not items:
        return []

    if len(items) > MAX_TEST_DATA_ITEMS:
        raise ValueError(f"test_data 數量超過上限 {MAX_TEST_DATA_ITEMS}")

    seen_names: set[str] = set()
    normalized: List[TestDataItem] = []

    for idx, item in enumerate(items):
        raw_name = item.name or ""
        name = _TD_CONTROL_CHARS_RE.sub("", raw_name)
        name = _TD_BIDI_OVERRIDE_RE.sub("", name)
        name = name.replace("\n", " ").replace("\r", " ").strip()
        if not name:
            raise ValueError(f"test_data[{idx}].name 不可為空白")
        if len(name) > MAX_TEST_DATA_NAME_LEN:
            raise ValueError(f"test_data[{idx}].name 長度超過 {MAX_TEST_DATA_NAME_LEN}")
        if name in seen_names:
            raise ValueError(f"test_data name '{name}' 在同一 test case 內重複")
        seen_names.add(name)

        raw_value = item.value if item.value is not None else ""
        value = _TD_NULL_BYTE_RE.sub("", raw_value)
        if len(value) > MAX_TEST_DATA_VALUE_LEN:
            raise ValueError(f"test_data[{idx}].value 長度超過 {MAX_TEST_DATA_VALUE_LEN}")

        item_id = (item.id or "").strip() or str(_uuid.uuid4())

        normalized.append(TestDataItem(id=item_id, name=name, category=item.category, value=value))

    return normalized


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

    # 測試結果檔案欄位
    test_results_files: List[LarkAttachment] = Field(
        default_factory=list, description="測試結果檔案（來自 Test Run 執行結果）"
    )

    # 關聯欄位
    user_story_map: List[LarkRecord] = Field(default_factory=list, description="User Story Map 關聯")
    tcg: List[str] = Field(default_factory=list, description="JIRA Tickets 列表")
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
        "test_case_number": "Test Case Number",
        "title": "Title",
        "priority": "Priority",
        "precondition": "Precondition",
        "steps": "Steps",
        "expected_result": "Expected Result",
        "attachments": "Attachment",
        "assignee": "Assignee",
        "test_result": "Test Result",
        "test_results_files": "Test Results Files",  # 新增測試結果檔案欄位
        "user_story_map": "User Story Map",
        "tcg": "TCG",
        "parent_record": "父記錄",
    }

    model_config = ConfigDict(
        use_enum_values=True,
        validate_assignment=True,
        json_schema_extra={
            "example": {"test_case_number": "TCG-93178.010.010", "title": "測試案例標題", "priority": "Medium"}
        },
    )

    @field_validator("test_case_number")
    @classmethod
    def validate_test_case_number(cls, v):
        # 顯示時允許空值；建立/更新時由 TestCaseCreate/TestCaseUpdate 另行約束
        if v is None:
            return ""
        return str(v).strip()

    @field_validator("title")
    @classmethod
    def validate_title(cls, v):
        # 顯示時允許空值；建立/更新時由 TestCaseCreate/TestCaseUpdate 另行約束
        if v is None:
            return ""
        return str(v).strip()

    @classmethod
    def from_lark_record(cls, record: Dict[str, Any], team_id: Optional[int] = None) -> "TestCase":
        """從 Lark 記錄資料建立 TestCase 實例"""
        record_id = record.get("record_id")
        fields = record.get("fields", {})

        # 解析基本欄位
        test_case_data = {
            "record_id": record_id,
            "team_id": team_id,
            "raw_fields": fields.copy(),
            "test_case_number": fields.get(cls.FIELD_IDS["test_case_number"], ""),
            "title": fields.get(cls.FIELD_IDS["title"], ""),
            "precondition": fields.get(cls.FIELD_IDS["precondition"]),
            "steps": fields.get(cls.FIELD_IDS["steps"]),
            "expected_result": fields.get(cls.FIELD_IDS["expected_result"]),
        }

        # 解析優先級
        priority_raw = fields.get(cls.FIELD_IDS["priority"])
        if priority_raw and priority_raw in [p.value for p in Priority]:
            test_case_data["priority"] = Priority(priority_raw)

        # 解析測試結果
        test_result_raw = fields.get(cls.FIELD_IDS["test_result"])
        if test_result_raw and test_result_raw in [s.value for s in TestResultStatus]:
            test_case_data["test_result"] = TestResultStatus(test_result_raw)

        # 解析人員欄位
        assignee_raw = fields.get(cls.FIELD_IDS["assignee"])
        test_case_data["assignee"] = parse_lark_user(assignee_raw)

        # 解析附件欄位
        attachments_raw = fields.get(cls.FIELD_IDS["attachments"])
        test_case_data["attachments"] = parse_lark_attachments(attachments_raw)

        # 解析測試結果檔案欄位
        test_results_files_raw = fields.get(cls.FIELD_IDS["test_results_files"])
        test_case_data["test_results_files"] = parse_lark_attachments(test_results_files_raw)

        # 解析關聯記錄欄位
        test_case_data["user_story_map"] = parse_lark_records(fields.get(cls.FIELD_IDS["user_story_map"]))
        test_case_data["tcg"] = parse_lark_records(fields.get(cls.FIELD_IDS["tcg"]))
        test_case_data["parent_record"] = parse_lark_records(fields.get(cls.FIELD_IDS["parent_record"]))

        # 解析系統時間戳欄位
        created_time = record.get("created_time")
        if created_time:
            # Lark 時間戳是以毫秒為單位的 Unix 時間戳
            test_case_data["created_at"] = datetime.fromtimestamp(created_time / 1000)

        last_modified_time = record.get("last_modified_time")
        if last_modified_time:
            # Lark 時間戳是以毫秒為單位的 Unix 時間戳
            test_case_data["updated_at"] = datetime.fromtimestamp(last_modified_time / 1000)

        return cls(**test_case_data)

    def to_lark_fields(self) -> Dict[str, Any]:
        """轉換為 Lark API 所需的欄位格式"""
        lark_fields = {}

        if self.test_case_number:
            lark_fields[self.FIELD_IDS["test_case_number"]] = self.test_case_number
        if self.title:
            lark_fields[self.FIELD_IDS["title"]] = self.title
        if self.precondition:
            lark_fields[self.FIELD_IDS["precondition"]] = self.precondition
        if self.steps:
            lark_fields[self.FIELD_IDS["steps"]] = self.steps
        if self.expected_result:
            lark_fields[self.FIELD_IDS["expected_result"]] = self.expected_result
        if self.priority:
            priority_value = self.priority.value if hasattr(self.priority, "value") else self.priority
            lark_fields[self.FIELD_IDS["priority"]] = priority_value
        if self.test_result:
            test_result_value = self.test_result.value if hasattr(self.test_result, "value") else self.test_result
            lark_fields[self.FIELD_IDS["test_result"]] = test_result_value

        # 處理 TCG 欄位
        if self.tcg is not None:
            # TCG 欄位是 Duplex Link 類型，需要字串陣列
            tcg_record_ids = []
            for tcg_record in self.tcg:
                # 使用 record_ids[0] 而不是 record_id
                record_id = tcg_record.record_ids[0] if tcg_record.record_ids else None
                if record_id:
                    tcg_record_ids.append(record_id)
            lark_fields[self.FIELD_IDS["tcg"]] = tcg_record_ids

        # 處理附件欄位
        if self.attachments is not None:
            # 附件欄位是 Attachment 類型，需要 [{"file_token": token}] 陣列
            attachment_items = []
            for attachment in self.attachments:
                token = getattr(attachment, "file_token", None)
                if token:
                    attachment_items.append({"file_token": token})
            # 允許傳空陣列以清空附件
            lark_fields[self.FIELD_IDS["attachments"]] = attachment_items

        # 處理測試結果檔案欄位
        if self.test_results_files is not None:
            # 測試結果檔案欄位也是 Attachment 類型
            result_file_items = []
            for result_file in self.test_results_files:
                token = getattr(result_file, "file_token", None)
                if token:
                    result_file_items.append({"file_token": token})
            lark_fields[self.FIELD_IDS["test_results_files"]] = result_file_items

        return lark_fields

    def to_lark_sync_fields(self) -> Dict[str, Any]:
        """轉換為 Lark 同步所需的欄位格式（僅包含基本欄位和 TCG）"""
        lark_fields = {}

        if self.test_case_number:
            lark_fields[self.FIELD_IDS["test_case_number"]] = self.test_case_number
        if self.title:
            lark_fields[self.FIELD_IDS["title"]] = self.title
        if self.precondition:
            lark_fields[self.FIELD_IDS["precondition"]] = self.precondition
        if self.steps:
            lark_fields[self.FIELD_IDS["steps"]] = self.steps
        if self.expected_result:
            lark_fields[self.FIELD_IDS["expected_result"]] = self.expected_result
        if self.priority:
            priority_value = self.priority.value if hasattr(self.priority, "value") else self.priority
            lark_fields[self.FIELD_IDS["priority"]] = priority_value
        if self.test_result:
            test_result_value = self.test_result.value if hasattr(self.test_result, "value") else self.test_result
            lark_fields[self.FIELD_IDS["test_result"]] = test_result_value

        # 處理 TCG 欄位
        if self.tcg is not None:
            # TCG 欄位是 Duplex Link 類型，需要字串陣列
            tcg_record_ids = []
            for tcg_record in self.tcg:
                # 使用 record_ids[0] 而不是 record_id
                record_id = tcg_record.record_ids[0] if tcg_record.record_ids else None
                if record_id:
                    tcg_record_ids.append(record_id)
            lark_fields[self.FIELD_IDS["tcg"]] = tcg_record_ids

        # 注意：不包含 assignee, attachments, test_results_files, user_story_map, parent_record

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

        lines = self.steps.strip().split("\n")
        steps = []
        for line in lines:
            line = line.strip()
            if line and (line[0].isdigit() or line.startswith("-") or line.startswith("•")):
                steps.append(line)

        return steps if steps else [self.steps]

    def has_test_results_files(self) -> bool:
        """檢查是否有測試結果檔案"""
        return len(self.test_results_files) > 0

    def get_test_results_file_count(self) -> int:
        """取得測試結果檔案數量"""
        return len(self.test_results_files)

    def get_test_results_screenshots(self) -> List[LarkAttachment]:
        """取得測試結果檔案中的截圖"""
        return [file for file in self.test_results_files if file.is_image]


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
    tcg: Optional[List[str]] = None
    parent_record: Optional[LarkRecord] = None
    # 新增：暫存上傳的識別碼，若提供則在建立後搬移暫存附件並寫入 DB
    temp_upload_id: Optional[str] = Field(None, description="暫存附件上傳識別碼（例如 UUID）")
    # 新增：Test Case Set ID（如果不提供，將使用預設 Set）
    test_case_set_id: Optional[int] = Field(None, description="所屬 Test Case Set ID")
    # 新增：Test Case Section ID（如果不提供，將使用 Unassigned Section）
    test_case_section_id: Optional[int] = Field(None, description="所屬 Test Case Section ID")
    # 新增：Test Data 列表
    test_data: Optional[List[TestDataItem]] = Field(None, description="Test Data 列表")


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
    tcg: Optional[Union[str, List[str]]] = None
    parent_record: Optional[LarkRecord] = None
    # 新增：暫存上傳識別碼，若提供則在更新後搬移暫存附件並合併至既有附件
    temp_upload_id: Optional[str] = Field(None, description="暫存附件上傳識別碼（例如 UUID）")
    # 新增：Test Case Set/Section 更新
    test_case_set_id: Optional[int] = Field(None, description="所屬 Test Case Set ID")
    test_case_section_id: Optional[int] = Field(None, description="所屬 Test Case Section ID")
    # 新增：Test Data 列表
    test_data: Optional[List[TestDataItem]] = Field(None, description="Test Data 列表")


class TestCaseResponse(TestCase):
    """測試案例回應模型"""

    test_case_set_id: Optional[int] = Field(None, description="所屬 Test Case Set ID")
    test_case_section_id: Optional[int] = Field(None, description="所屬 Test Case Section ID")
    section_name: Optional[str] = Field(None, description="所屬 Test Case Section 名稱")
    section_path: Optional[str] = Field(None, description="所屬 Test Case Section 路徑（含層級）")
    section_level: Optional[int] = Field(None, description="所屬 Test Case Section 層級")
    cleanup_summary: Optional[CleanupSummary] = Field(
        None, description="因 Test Case Set 調整觸發的 Test Run 項目清理摘要"
    )
    # 新增：Test Data 列表
    test_data: Optional[List[TestDataItem]] = Field(None, description="Test Data 列表")


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
    cleanup_summary: Optional[CleanupSummary] = Field(None, description="批次操作造成的 Test Run 項目清理摘要")


# 欄位映射類別
class TestCaseFieldMapping:
    """測試案例欄位映射定義"""

    @classmethod
    def get_all_field_ids(cls) -> Dict[str, str]:
        """取得所有欄位的 ID 映射"""
        return TestCase.FIELD_IDS
