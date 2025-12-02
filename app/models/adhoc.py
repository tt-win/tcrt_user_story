from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.models.lark_types import Priority, TestResultStatus
from app.models.test_run_config import TestRunStatus

# Item Models
class AdHocRunItemBase(BaseModel):
    test_case_number: Optional[str] = None
    title: Optional[str] = None
    priority: Optional[Priority] = Priority.MEDIUM
    precondition: Optional[str] = None
    steps: Optional[str] = None
    expected_result: Optional[str] = None
    jira_tickets: Optional[str] = None
    comments: Optional[str] = None
    bug_list: Optional[str] = None
    test_result: Optional[TestResultStatus] = None
    assignee_name: Optional[str] = None
    executed_at: Optional[datetime] = None
    meta_json: Optional[str] = None

class AdHocRunItemCreate(AdHocRunItemBase):
    row_index: int

class AdHocRunItemUpdate(AdHocRunItemBase):
    row_index: Optional[int] = None
    # Attachments handled separately usually, but can be included in updates if simplified
    attachments_json: Optional[str] = None
    execution_results_json: Optional[str] = None

class AdHocRunItemResponse(AdHocRunItemBase):
    id: int
    sheet_id: int
    row_index: int
    attachments_json: Optional[str] = None
    execution_results_json: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Sheet Models
class AdHocRunSheetBase(BaseModel):
    name: str
    sort_order: Optional[int] = 0

class AdHocRunSheetCreate(AdHocRunSheetBase):
    pass

class AdHocRunSheetUpdate(AdHocRunSheetBase):
    pass

class AdHocRunSheetResponse(AdHocRunSheetBase):
    id: int
    adhoc_run_id: int
    created_at: datetime
    updated_at: datetime
    items: List[AdHocRunItemResponse] = []

    class Config:
        from_attributes = True

# Run Models
class AdHocRunBase(BaseModel):
    name: str
    description: Optional[str] = None
    status: Optional[TestRunStatus] = TestRunStatus.ACTIVE
    jira_ticket: Optional[str] = None
    
    # Enhanced Basic Settings
    test_version: Optional[str] = None
    test_environment: Optional[str] = None
    build_number: Optional[str] = None
    related_tp_tickets_json: Optional[str] = None # Stored as JSON string
    notifications_enabled: Optional[bool] = False
    notify_chat_ids_json: Optional[str] = None
    notify_chat_names_snapshot: Optional[str] = None

class AdHocRunCreate(AdHocRunBase):
    team_id: int

class AdHocRunUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TestRunStatus] = None
    jira_ticket: Optional[str] = None
    test_version: Optional[str] = None
    test_environment: Optional[str] = None
    build_number: Optional[str] = None
    related_tp_tickets_json: Optional[str] = None
    notifications_enabled: Optional[bool] = None
    notify_chat_ids_json: Optional[str] = None
    notify_chat_names_snapshot: Optional[str] = None

class AdHocRunResponse(AdHocRunBase):
    id: int
    team_id: int
    created_at: datetime
    updated_at: datetime
    total_test_cases: Optional[int] = 0
    executed_cases: Optional[int] = 0
    sheets: List[AdHocRunSheetResponse] = []

    class Config:
        from_attributes = True

# Batch Update Request
class AdHocBatchUpdateRequest(BaseModel):
    items: List[Dict[str, Any]] # dict of changes keyed by item ID or new items
