"""Test Run Set 資料模型"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, validator

from .test_run_config import TestRunConfigSummary


class TestRunSetStatus(str, Enum):
    """Test Run Set 狀態枚舉"""

    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class TestRunSetBase(BaseModel):
    """Test Run Set 基礎欄位"""

    name: str = Field(..., max_length=120, description="Test Run Set 名稱")
    description: Optional[str] = Field(None, description="Test Run Set 描述")
    related_tp_tickets: Optional[List[str]] = Field(
        default=None,
        description="相關 TP 開發單票號",
    )

    @validator("name")
    def validate_name(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("名稱不可為空白")
        return value.strip()

    @validator("related_tp_tickets")
    def validate_related_tp_tickets(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return value

        if not isinstance(value, list):
            raise ValueError("TP tickets must be a list")

        if len(value) > 100:
            raise ValueError("最多支援 100 個 TP 票號")

        from re import compile

        pattern = compile(r"^TP-\d+$")
        seen = set()
        normalized: List[str] = []
        for ticket in value:
            if not isinstance(ticket, str):
                raise ValueError(f'TP ticket must be string, got: {type(ticket)}')
            ticket = ticket.strip().upper()
            if not pattern.match(ticket):
                raise ValueError(f'Invalid TP ticket format: {ticket} (expected: TP-XXXXX)')
            if ticket in seen:
                continue
            seen.add(ticket)
            normalized.append(ticket)
        return normalized


class TestRunSetCreate(TestRunSetBase):
    """建立 Test Run Set 的資料模型"""

    initial_config_ids: Optional[List[int]] = Field(
        default=None,
        description="建立時要加入的 Test Run Config IDs",
    )

    @validator("initial_config_ids")
    def validate_initial_config_ids(cls, value: Optional[List[int]]) -> Optional[List[int]]:
        if value is None:
            return value
        unique_ids = list(dict.fromkeys(value))
        return unique_ids


class TestRunSetUpdate(BaseModel):
    """更新 Test Run Set 資料模型"""

    name: Optional[str] = Field(None, max_length=120, description="Test Run Set 名稱")
    description: Optional[str] = Field(None, description="Test Run Set 描述")
    status: Optional[TestRunSetStatus] = Field(None, description="Test Run Set 狀態")
    related_tp_tickets: Optional[List[str]] = Field(
        default=None,
        description="相關 TP 開發單票號",
    )

    @validator("name")
    def validate_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if not value.strip():
            raise ValueError("名稱不可為空白")
        return value.strip()

    @validator("related_tp_tickets")
    def validate_related_tp_tickets(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        return TestRunSetBase.validate_related_tp_tickets(value)  # type: ignore[arg-type]


class TestRunSet(BaseModel):
    """Test Run Set 完整資料模型"""

    id: int = Field(..., description="Test Run Set ID")
    team_id: int = Field(..., description="所屬團隊 ID")
    name: str = Field(..., max_length=120, description="Test Run Set 名稱")
    description: Optional[str] = Field(None, description="Test Run Set 描述")
    status: TestRunSetStatus = Field(TestRunSetStatus.ACTIVE, description="Test Run Set 狀態")
    archived_at: Optional[datetime] = Field(None, description="歸檔時間")
    related_tp_tickets: Optional[List[str]] = Field(default=None, description="相關 TP 開發單票號")
    created_at: datetime = Field(..., description="建立時間")
    updated_at: datetime = Field(..., description="更新時間")


class TestRunSetSummary(BaseModel):
    """Test Run Set 摘要資訊"""

    id: int = Field(..., description="Test Run Set ID")
    name: str = Field(..., description="Test Run Set 名稱")
    status: TestRunSetStatus = Field(..., description="Test Run Set 狀態")
    test_run_count: int = Field(0, description="包含的 Test Run 數量")
    related_tp_tickets: Optional[List[str]] = Field(default=None, description="相關 TP 開發單票號")
    created_at: datetime = Field(..., description="建立時間")
    updated_at: datetime = Field(..., description="更新時間")


class TestRunSetDetail(TestRunSet):
    """Test Run Set 詳細資訊，包含底下 Test Runs"""

    test_runs: List[TestRunConfigSummary] = Field(default_factory=list, description="所屬 Test Runs 摘要清單")


class TestRunSetOverview(BaseModel):
    """提供前端使用的 Test Run Set 總覽資訊"""

    sets: List[TestRunSetDetail] = Field(default_factory=list, description="Test Run Set 詳細清單")
    unassigned: List[TestRunConfigSummary] = Field(default_factory=list, description="未歸組 Test Run 摘要清單")


class TestRunSetMembershipCreate(BaseModel):
    """新增既有 Test Run 到 Set 的資料模型"""

    config_ids: List[int] = Field(..., description="要加入的 Test Run Config IDs")

    @validator("config_ids")
    def validate_config_ids(cls, value: List[int]) -> List[int]:
        if not value:
            raise ValueError("至少需要一個 Test Run Config ID")
        unique_ids = list(dict.fromkeys(value))
        return unique_ids


class TestRunSetMembershipMove(BaseModel):
    """搬移或移出的操作資料模型"""

    target_set_id: Optional[int] = Field(
        None,
        description="目標 Test Run Set ID；若為空表示移出成未歸組",
    )
