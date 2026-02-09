"""
測試執行配置模型

用於管理團隊的多個測試執行輪次，每個測試執行對應一個 Lark 表格
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime
from enum import Enum
import re
import json

from .test_run_scope import CleanupSummary


class TestRunStatus(str, Enum):
    """測試執行狀態"""
    ACTIVE = "active"          # 進行中
    COMPLETED = "completed"    # 已完成
    DRAFT = "draft"           # 草稿
    ARCHIVED = "archived"     # 已歸檔


def _normalize_test_case_set_ids(values: Optional[List[int]]) -> Optional[List[int]]:
    if values is None:
        return None
    if not isinstance(values, list):
        raise ValueError('test_case_set_ids must be a list')
    normalized: List[int] = []
    seen = set()
    for raw in values:
        try:
            set_id = int(raw)
        except (TypeError, ValueError):
            raise ValueError(f'Invalid test_case_set_id: {raw}')
        if set_id <= 0:
            raise ValueError(f'Invalid test_case_set_id: {raw}')
        if set_id in seen:
            continue
        seen.add(set_id)
        normalized.append(set_id)
    return normalized


class TestRunConfig(BaseModel):
    """測試執行配置"""
    id: Optional[int] = Field(None, description="配置 ID")
    team_id: int = Field(..., description="所屬團隊 ID")
    name: str = Field(..., description="測試執行名稱", max_length=100)
    description: Optional[str] = Field(None, description="測試執行描述")
    set_id: Optional[int] = Field(None, description="所屬 Test Run Set ID")
    set_name: Optional[str] = Field(None, description="所屬 Test Run Set 名稱")
    test_case_set_ids: List[int] = Field(default_factory=list, description="允許的 Test Case Set IDs")
    
    # 測試執行元資料
    test_version: Optional[str] = Field(None, description="測試版本")
    test_environment: Optional[str] = Field(None, description="測試環境")
    build_number: Optional[str] = Field(None, description="建置編號")
    
    # TP 開發單票號
    related_tp_tickets: Optional[List[str]] = Field(None, description="相關 JIRA Tickets 票號")
    
    # 狀態與時間
    status: TestRunStatus = Field(TestRunStatus.ACTIVE, description="執行狀態")
    start_date: Optional[datetime] = Field(None, description="開始日期")
    end_date: Optional[datetime] = Field(None, description="結束日期")
    
    # 統計資訊
    total_test_cases: int = Field(0, description="總測試案例數")
    executed_cases: int = Field(0, description="已執行案例數")
    passed_cases: int = Field(0, description="通過案例數")
    failed_cases: int = Field(0, description="失敗案例數")
    
    # 通知設定
    notifications_enabled: bool = Field(False, description="是否啟用通知")
    notify_chat_ids: Optional[List[str]] = Field(None, description="通知群組 Chat IDs")
    notify_chat_names_snapshot: Optional[List[str]] = Field(None, description="群組名稱快照（UI 顯示用）")

    @validator('test_case_set_ids', pre=True, always=True)
    def validate_test_case_set_ids(cls, v, values):
        if v is None and values.get('test_case_set_id') is not None:
            v = [values.get('test_case_set_id')]
        return _normalize_test_case_set_ids(v)
    
    # 系統欄位
    created_at: Optional[datetime] = Field(None, description="建立時間")
    updated_at: Optional[datetime] = Field(None, description="更新時間")
    last_sync_at: Optional[datetime] = Field(None, description="最後同步時間")
    
    # 不再強制要求 table_id
    
    @validator('name')
    def validate_name(cls, v):
        if not v or len(v.strip()) < 2:
            raise ValueError('Name must be at least 2 characters long')
        return v.strip()

    @validator('test_case_set_ids', pre=True, always=True)
    def validate_test_case_set_ids(cls, v):
        normalized = _normalize_test_case_set_ids(v)
        return normalized or []
    
    @validator('related_tp_tickets')
    def validate_tp_tickets(cls, v):
        if v is None:
            return v
        
        # 檢查資料型態
        if not isinstance(v, list):
            raise ValueError('TP tickets must be a list')
            
        # 檢查數量限制
        if len(v) > 100:
            raise ValueError('最多支援 100 個 TP 票號')
            
        # 驗證每個 TP 票號格式
        pattern = re.compile(r'^TP-\d+$')
        seen_tickets = set()
        
        for ticket in v:
            if not isinstance(ticket, str):
                raise ValueError(f'TP ticket must be string, got: {type(ticket)}')
            if not pattern.match(ticket):
                raise ValueError(f'Invalid TP ticket format: {ticket} (expected: TP-XXXXX)')
            if ticket in seen_tickets:
                raise ValueError(f'Duplicate TP ticket: {ticket}')
            seen_tickets.add(ticket)
            
        return v
    
    @validator('notify_chat_ids')
    def validate_notify_chat_ids(cls, v):
        if v is None:
            return v
        
        # 檢查資料型態
        if not isinstance(v, list):
            raise ValueError('notify_chat_ids must be a list')
        
        # 去除空值並 strip
        cleaned_ids = []
        for chat_id in v:
            if not isinstance(chat_id, str):
                raise ValueError(f'chat_id must be string, got: {type(chat_id)}')
            cleaned_id = chat_id.strip()
            if cleaned_id:
                cleaned_ids.append(cleaned_id)
        
        # 檢查數量限制
        if len(cleaned_ids) > 100:
            raise ValueError('最多支援 100 個群組')
        
        # 檢查長度限制
        for chat_id in cleaned_ids:
            if len(chat_id) < 5 or len(chat_id) > 128:
                raise ValueError(f'chat_id 長度必須在 5-128 字元之間: {chat_id}')
        
        # 去重
        unique_ids = list(dict.fromkeys(cleaned_ids))  # 保持順序的去重
        
        return unique_ids if unique_ids else None
    
    @validator('notify_chat_names_snapshot')
    def validate_notify_chat_names_snapshot(cls, v, values):
        if v is None:
            return v
            
        if not isinstance(v, list):
            raise ValueError('notify_chat_names_snapshot must be a list')
        
        # 檢查是否與 notify_chat_ids 長度一致
        notify_chat_ids = values.get('notify_chat_ids')
        if notify_chat_ids and len(v) != len(notify_chat_ids):
            raise ValueError('notify_chat_names_snapshot 長度必須與 notify_chat_ids 一致')
            
        return v
    
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
    team_id: Optional[int] = Field(None, description="所屬團隊 ID（由路徑參數指定）")
    name: str = Field(..., description="測試執行名稱", max_length=100)
    description: Optional[str] = Field(None, description="測試執行描述")
    set_id: Optional[int] = Field(None, description="建立時指定的 Test Run Set ID")
    test_case_set_id: Optional[int] = Field(None, description="相容欄位：單一 Test Case Set ID（已棄用）")
    test_case_set_ids: Optional[List[int]] = Field(None, description="允許的 Test Case Set IDs")
    test_version: Optional[str] = Field(None, description="測試版本")
    test_environment: Optional[str] = Field(None, description="測試環境")
    build_number: Optional[str] = Field(None, description="建置編號")
    
    # TP 開發單票號
    related_tp_tickets: Optional[List[str]] = Field(None, description="相關 JIRA Tickets 票號")
    
    status: TestRunStatus = Field(TestRunStatus.DRAFT, description="初始狀態")
    start_date: Optional[datetime] = Field(None, description="開始日期")
    
    # 通知設定
    notifications_enabled: bool = Field(False, description="是否啟用通知")
    notify_chat_ids: Optional[List[str]] = Field(None, description="通知群組 Chat IDs")
    notify_chat_names_snapshot: Optional[List[str]] = Field(None, description="群組名稱快照（UI 顯示用）")
    
    @validator('notify_chat_ids')
    def validate_notify_chat_ids(cls, v):
        """沿用基礎模型的驗證邏輯"""
        if v is None:
            return v
        
        if not isinstance(v, list):
            raise ValueError('notify_chat_ids must be a list')
        
        cleaned_ids = []
        for chat_id in v:
            if not isinstance(chat_id, str):
                raise ValueError(f'chat_id must be string, got: {type(chat_id)}')
            cleaned_id = chat_id.strip()
            if cleaned_id:
                cleaned_ids.append(cleaned_id)
        
        if len(cleaned_ids) > 100:
            raise ValueError('最多支援 100 個群組')
        
        for chat_id in cleaned_ids:
            if len(chat_id) < 5 or len(chat_id) > 128:
                raise ValueError(f'chat_id 長度必須在 5-128 字元之間: {chat_id}')
        
        unique_ids = list(dict.fromkeys(cleaned_ids))
        return unique_ids if unique_ids else None
    
    @validator('notify_chat_names_snapshot')
    def validate_notify_chat_names_snapshot(cls, v, values):
        """沿用基礎模型的驗證邏輯"""
        if v is None:
            return v
            
        if not isinstance(v, list):
            raise ValueError('notify_chat_names_snapshot must be a list')
        
        notify_chat_ids = values.get('notify_chat_ids')
        if notify_chat_ids and len(v) != len(notify_chat_ids):
            raise ValueError('notify_chat_names_snapshot 長度必須與 notify_chat_ids 一致')
            
        return v
    
    @validator('related_tp_tickets')
    def validate_tp_tickets(cls, v):
        """TP 票號驗證邏輯 - 複用基礎模型驗證"""
        if v is None:
            return v
        
        # 檢查資料型態
        if not isinstance(v, list):
            raise ValueError('TP tickets must be a list')
            
        # 檢查數量限制
        if len(v) > 100:
            raise ValueError('最多支援 100 個 TP 票號')
            
        # 驗證每個 TP 票號格式
        pattern = re.compile(r'^TP-\d+$')
        seen_tickets = set()
        
        for ticket in v:
            if not isinstance(ticket, str):
                raise ValueError(f'TP ticket must be string, got: {type(ticket)}')
            if not pattern.match(ticket):
                raise ValueError(f'Invalid TP ticket format: {ticket} (expected: TP-XXXXX)')
            if ticket in seen_tickets:
                raise ValueError(f'Duplicate TP ticket: {ticket}')
            seen_tickets.add(ticket)
            
        return v


class TestRunConfigUpdate(BaseModel):
    """更新測試執行配置的資料模型"""
    name: Optional[str] = Field(None, description="測試執行名稱", max_length=100)
    description: Optional[str] = Field(None, description="測試執行描述")
    test_case_set_id: Optional[int] = Field(None, description="相容欄位：單一 Test Case Set ID（已棄用）")
    test_case_set_ids: Optional[List[int]] = Field(None, description="允許的 Test Case Set IDs")
    test_version: Optional[str] = Field(None, description="測試版本")
    test_environment: Optional[str] = Field(None, description="測試環境")
    build_number: Optional[str] = Field(None, description="建置編號")
    
    # TP 開發單票號
    related_tp_tickets: Optional[List[str]] = Field(None, description="相關 JIRA Tickets 票號")
    
    status: Optional[TestRunStatus] = Field(None, description="執行狀態")
    start_date: Optional[datetime] = Field(None, description="開始日期")
    end_date: Optional[datetime] = Field(None, description="結束日期")
    
    # 通知設定
    notifications_enabled: Optional[bool] = Field(None, description="是否啟用通知")
    notify_chat_ids: Optional[List[str]] = Field(None, description="通知群組 Chat IDs")
    notify_chat_names_snapshot: Optional[List[str]] = Field(None, description="群組名稱快照（UI 顯示用）")

    @validator('test_case_set_ids', pre=True, always=True)
    def validate_test_case_set_ids(cls, v, values):
        if v is None and values.get('test_case_set_id') is not None:
            v = [values.get('test_case_set_id')]
        return _normalize_test_case_set_ids(v)
    
    @validator('notify_chat_ids')
    def validate_notify_chat_ids(cls, v):
        """沿用基礎模型的驗證邏輯"""
        if v is None:
            return v
        
        if not isinstance(v, list):
            raise ValueError('notify_chat_ids must be a list')
        
        cleaned_ids = []
        for chat_id in v:
            if not isinstance(chat_id, str):
                raise ValueError(f'chat_id must be string, got: {type(chat_id)}')
            cleaned_id = chat_id.strip()
            if cleaned_id:
                cleaned_ids.append(cleaned_id)
        
        if len(cleaned_ids) > 100:
            raise ValueError('最多支援 100 個群組')
        
        for chat_id in cleaned_ids:
            if len(chat_id) < 5 or len(chat_id) > 128:
                raise ValueError(f'chat_id 長度必須在 5-128 字元之間: {chat_id}')
        
        unique_ids = list(dict.fromkeys(cleaned_ids))
        return unique_ids if unique_ids else None
    
    @validator('notify_chat_names_snapshot')
    def validate_notify_chat_names_snapshot(cls, v, values):
        """沿用基礎模型的驗證邏輯"""
        if v is None:
            return v
            
        if not isinstance(v, list):
            raise ValueError('notify_chat_names_snapshot must be a list')
        
        notify_chat_ids = values.get('notify_chat_ids')
        if notify_chat_ids and len(v) != len(notify_chat_ids):
            raise ValueError('notify_chat_names_snapshot 長度必須與 notify_chat_ids 一致')
            
        return v
    
    @validator('related_tp_tickets')
    def validate_tp_tickets(cls, v):
        """TP 票號驗證邏輯 - 複用基礎模型驗證"""
        if v is None:
            return v
        
        # 檢查資料型態
        if not isinstance(v, list):
            raise ValueError('TP tickets must be a list')
            
        # 檢查數量限制
        if len(v) > 100:
            raise ValueError('最多支援 100 個 TP 票號')
            
        # 驗證每個 TP 票號格式
        pattern = re.compile(r'^TP-\d+$')
        seen_tickets = set()
        
        for ticket in v:
            if not isinstance(ticket, str):
                raise ValueError(f'TP ticket must be string, got: {type(ticket)}')
            if not pattern.match(ticket):
                raise ValueError(f'Invalid TP ticket format: {ticket} (expected: TP-XXXXX)')
            if ticket in seen_tickets:
                raise ValueError(f'Duplicate TP ticket: {ticket}')
            seen_tickets.add(ticket)
            
        return v


class TestRunConfigResponse(TestRunConfig):
    """測試執行配置回應模型
    
    繼承自 TestRunConfig，自動包含所有欄位包括 related_tp_tickets
    此模型用於 API 回應，提供完整的配置資訊
    """
    cleanup_summary: Optional[CleanupSummary] = Field(None, description="因範圍調整觸發的清理摘要")


class TestRunConfigSummary(BaseModel):
    """測試執行配置摘要（用於列表顯示）"""
    id: int = Field(..., description="配置 ID")
    name: str = Field(..., description="測試執行名稱")
    set_id: Optional[int] = Field(None, description="所屬 Test Run Set ID")
    set_name: Optional[str] = Field(None, description="所屬 Test Run Set 名稱")
    test_case_set_ids: List[int] = Field(default_factory=list, description="允許的 Test Case Set IDs")
    test_environment: Optional[str] = Field(None, description="測試環境")
    build_number: Optional[str] = Field(None, description="建置編號")
    test_version: Optional[str] = Field(None, description="測試版本")

    # TP 開發單票號 (摘要顯示)
    related_tp_tickets: Optional[List[str]] = Field(None, description="相關 JIRA Tickets 票號")
    tp_tickets_count: int = Field(0, description="TP 票號數量")

    status: TestRunStatus = Field(..., description="執行狀態")
    execution_rate: float = Field(..., description="執行率")
    pass_rate: float = Field(..., description="通過率")
    total_test_cases: int = Field(..., description="總案例數")
    executed_cases: int = Field(..., description="已執行案例數")
    passed_cases: int = Field(..., description="通過案例數")
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
    
    # TP 票號統計資訊
    configs_with_tp_tickets: int = Field(..., description="包含 TP 票號的配置數")
    total_tp_tickets: int = Field(..., description="TP 票號總數")
    average_tp_per_config: float = Field(..., description="每個配置平均 TP 票號數")
    
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
        
        # 計算 TP 票號統計
        configs_with_tp_tickets = len([c for c in configs if c.related_tp_tickets and len(c.related_tp_tickets) > 0])
        total_tp_tickets = sum(len(c.related_tp_tickets) for c in configs if c.related_tp_tickets)
        average_tp_per_config = (total_tp_tickets / total_configs) if total_configs > 0 else 0.0
        
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
            configs_with_tp_tickets=configs_with_tp_tickets,
            total_tp_tickets=total_tp_tickets,
            average_tp_per_config=average_tp_per_config,
            overall_execution_rate=overall_execution_rate,
            overall_pass_rate=overall_pass_rate
        )


class TPTicketDataConverter:
    """TP 票號資料轉換服務
    
    提供 TP 票號 List 與 JSON 之間的轉換功能，以及搜尋索引更新
    """
    
    @staticmethod
    def list_to_json(tp_tickets: Optional[List[str]]) -> Optional[str]:
        """將 TP 票號列表轉換為 JSON 字串
        
        Args:
            tp_tickets: TP 票號列表，例如 ['TP-123', 'TP-456']
            
        Returns:
            JSON 字串，例如 '["TP-123", "TP-456"]'
            如果輸入為 None 或空列表，返回 None
        """
        if not tp_tickets:
            return None
        
        try:
            return json.dumps(tp_tickets, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Failed to convert TP tickets to JSON: {e}")
    
    @staticmethod
    def json_to_list(json_data: Optional[str]) -> Optional[List[str]]:
        """將 JSON 字串轉換為 TP 票號列表
        
        Args:
            json_data: JSON 字串，例如 '["TP-123", "TP-456"]'
            
        Returns:
            TP 票號列表，例如 ['TP-123', 'TP-456']
            如果輸入為 None 或無效 JSON，返回 None
        """
        if not json_data:
            return None
            
        if isinstance(json_data, str) and json_data.strip() == '':
            return None
        
        try:
            tickets = json.loads(json_data)
            if not isinstance(tickets, list):
                return None
            return tickets
        except (json.JSONDecodeError, TypeError):
            return None
    
    @staticmethod
    def create_search_index(tp_tickets: Optional[List[str]]) -> Optional[str]:
        """建立 TP 票號搜尋索引
        
        將 TP 票號列表轉換為搜尋友善的字串格式，用於資料庫搜尋
        
        Args:
            tp_tickets: TP 票號列表，例如 ['TP-123', 'TP-456']
            
        Returns:
            搜尋索引字串，例如 'TP-123 TP-456'
            如果輸入為 None 或空列表，返回 None
        """
        if not tp_tickets:
            return None
        
        # 將 TP 票號用空格連接，便於 LIKE 查詢和全文搜尋
        return ' '.join(tp_tickets)
    
    @staticmethod
    def batch_convert_to_database_format(configs_data: List[dict]) -> List[dict]:
        """批次轉換配置資料為資料庫格式
        
        將包含 related_tp_tickets 列表的配置資料轉換為資料庫儲存格式
        
        Args:
            configs_data: 配置資料列表，每個元素包含 related_tp_tickets 列表
            
        Returns:
            轉換後的配置資料列表，包含 JSON 格式和搜尋索引
        """
        converted_configs = []
        
        for config in configs_data:
            converted_config = config.copy()
            tp_tickets = config.get('related_tp_tickets')
            
            # 轉換為 JSON 格式
            converted_config['related_tp_tickets_json'] = TPTicketDataConverter.list_to_json(tp_tickets)
            
            # 建立搜尋索引
            converted_config['tp_tickets_search'] = TPTicketDataConverter.create_search_index(tp_tickets)
            
            # 移除原始的 related_tp_tickets 欄位（避免資料庫錯誤）
            if 'related_tp_tickets' in converted_config:
                del converted_config['related_tp_tickets']
                
            converted_configs.append(converted_config)
        
        return converted_configs
    
    @staticmethod
    def batch_convert_from_database_format(db_records: List[dict]) -> List[dict]:
        """批次轉換資料庫記錄為應用程式格式
        
        將資料庫中的 JSON 格式轉換回 related_tp_tickets 列表
        
        Args:
            db_records: 資料庫記錄列表，包含 related_tp_tickets_json 欄位
            
        Returns:
            轉換後的記錄列表，包含 related_tp_tickets 列表
        """
        converted_records = []
        
        for record in db_records:
            converted_record = record.copy()
            json_data = record.get('related_tp_tickets_json')
            
            # 從 JSON 轉換為列表
            converted_record['related_tp_tickets'] = TPTicketDataConverter.json_to_list(json_data)
            
            converted_records.append(converted_record)
        
        return converted_records
    
    @staticmethod
    def validate_and_convert(tp_tickets: Optional[List[str]]) -> tuple[Optional[str], Optional[str]]:
        """驗證並轉換 TP 票號資料
        
        執行完整的驗證和轉換流程，適用於 API 端點
        
        Args:
            tp_tickets: TP 票號列表
            
        Returns:
            tuple (json_data, search_index)
            
        Raises:
            ValueError: 當 TP 票號格式不正確時
        """
        if tp_tickets is None:
            return None, None
        
        # 使用現有的 validator 進行驗證
        # 建立臨時的 TestRunConfig 模型實例來驗證
        try:
            temp_config = TestRunConfigCreate(
                name="temp", 
                team_id=1,
                related_tp_tickets=tp_tickets
            )
            
            # 如果驗證通過，進行轉換
            json_data = TPTicketDataConverter.list_to_json(tp_tickets)
            search_index = TPTicketDataConverter.create_search_index(tp_tickets)
            
            return json_data, search_index
            
        except ValueError as e:
            raise ValueError(f"TP ticket validation failed: {e}")
