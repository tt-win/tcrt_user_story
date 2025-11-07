"""
測試案例集合 (Test Case Set) 和區段 (Section) 資料模型
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime


class TestCaseSectionBase(BaseModel):
    """測試案例區段基礎模型"""
    name: str = Field(..., description="區段名稱", min_length=1, max_length=100)
    description: Optional[str] = Field(None, description="區段描述")
    parent_section_id: Optional[int] = Field(None, description="父區段 ID")
    sort_order: int = Field(0, description="同層級排序")


class TestCaseSectionCreate(TestCaseSectionBase):
    """建立測試案例區段請求"""
    pass


class TestCaseSectionUpdate(BaseModel):
    """更新測試案例區段請求"""
    name: Optional[str] = Field(None, description="區段名稱")
    description: Optional[str] = Field(None, description="區段描述")
    parent_section_id: Optional[int] = Field(None, description="父區段 ID")
    sort_order: Optional[int] = Field(None, description="同層級排序")


class TestCaseSection(TestCaseSectionBase):
    """測試案例區段回應模型"""
    id: int = Field(..., description="區段 ID")
    test_case_set_id: int = Field(..., description="所屬 Test Case Set ID")
    level: int = Field(..., description="巢狀深度 (1-5)")
    created_at: datetime = Field(..., description="建立時間")
    updated_at: datetime = Field(..., description="更新時間")

    model_config = ConfigDict(from_attributes=True)


class TestCaseSectionWithChildren(TestCaseSection):
    """包含子區段的區段模型"""
    child_sections: List['TestCaseSectionWithChildren'] = Field(default_factory=list, description="子區段列表")
    test_case_count: int = Field(0, description="該區段下的測試案例數量")


# 更新前向引用
TestCaseSectionWithChildren.model_rebuild()


class TestCaseSetBase(BaseModel):
    """測試案例集合基礎模型"""
    name: str = Field(..., description="集合名稱 (全域唯一)", min_length=1, max_length=100)
    description: Optional[str] = Field(None, description="集合描述")


class TestCaseSetCreate(TestCaseSetBase):
    """建立測試案例集合請求"""
    pass


class TestCaseSetUpdate(BaseModel):
    """更新測試案例集合請求"""
    name: Optional[str] = Field(None, description="集合名稱")
    description: Optional[str] = Field(None, description="集合描述")


class TestCaseSet(TestCaseSetBase):
    """測試案例集合回應模型"""
    id: int = Field(..., description="集合 ID")
    team_id: int = Field(..., description="所屬團隊 ID")
    is_default: bool = Field(False, description="是否為預設集合")
    created_at: datetime = Field(..., description="建立時間")
    updated_at: datetime = Field(..., description="更新時間")
    test_case_count: int = Field(0, description="該集合下的測試案例總數")

    model_config = ConfigDict(from_attributes=True)


class TestCaseSetWithSections(TestCaseSet):
    """包含區段的集合模型"""
    sections: List[TestCaseSectionWithChildren] = Field(default_factory=list, description="區段列表")
    test_case_count: int = Field(0, description="該集合下的測試案例總數")


class TestCaseSetValidateName(BaseModel):
    """驗證集合名稱唯一性的請求"""
    name: str = Field(..., description="集合名稱")
    exclude_set_id: Optional[int] = Field(None, description="要排除的集合 ID (更新時)")


class TestCaseSetNameValidationResponse(BaseModel):
    """名稱驗證回應"""
    is_valid: bool = Field(..., description="名稱是否有效")
    message: Optional[str] = Field(None, description="驗證訊息")


class TestCaseSectionReorderRequest(BaseModel):
    """區段排序請求"""
    sections: List[Dict[str, Any]] = Field(..., description="區段排序資訊")
    # 預期格式: [{"id": 1, "sort_order": 0, "parent_section_id": null}, ...]


class MoveTestCasesRequest(BaseModel):
    """移動 Test Cases 到不同 Section 的請求"""
    test_case_ids: List[int] = Field(..., description="Test Case IDs")
    target_section_id: Optional[int] = Field(None, description="目標 Section ID")


class CopyAcrossTestCaseSetsRequest(BaseModel):
    """跨 Test Case Set 複製 Test Cases 的請求"""
    test_case_ids: List[int] = Field(..., description="Test Case IDs")
    target_test_case_set_id: int = Field(..., description="目標 Test Case Set ID")
    target_section_id: Optional[int] = Field(None, description="目標 Section ID")
    copy_mode: str = Field("copy", description="操作模式: copy 或 move")
