from typing import List, Optional

from pydantic import BaseModel, Field


class ImpactedTestRun(BaseModel):
    config_id: int = Field(..., description="受影響的 Test Run Config ID")
    config_name: str = Field(..., description="受影響的 Test Run 名稱")
    removed_item_count: int = Field(..., description="該 Test Run 被移除的項目數")


class CleanupSummary(BaseModel):
    removed_item_count: int = Field(0, description="總移除項目數")
    impacted_test_runs: List[ImpactedTestRun] = Field(default_factory=list, description="受影響 Test Runs")
    trigger: Optional[str] = Field(None, description="觸發來源")
    affected_test_case_set_ids: List[int] = Field(default_factory=list, description="受影響的 Test Case Set IDs")
    target_test_case_set_id: Optional[int] = Field(None, description="目標 Test Case Set ID（move cleanup）")
    source_test_case_set_id: Optional[int] = Field(None, description="來源 Test Case Set ID（delete cleanup）")


class ImpactPreviewResponse(BaseModel):
    impacted_item_count: int = Field(0, description="預估受影響項目數")
    impacted_test_runs: List[ImpactedTestRun] = Field(default_factory=list, description="受影響 Test Runs")
    trigger: str = Field(..., description="預估來源")
    target_test_case_set_id: Optional[int] = Field(None, description="目標 Test Case Set ID（move preview）")
    source_test_case_set_id: Optional[int] = Field(None, description="來源 Test Case Set ID（delete preview）")
