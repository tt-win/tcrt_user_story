"""
測試案例集合 (Test Case Set) 服務層
"""

import logging
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from ..models.database_models import TestCaseSet, TestCaseSection, TestCaseLocal
from ..models.test_case_set import (
    TestCaseSetCreate, TestCaseSetUpdate, TestCaseSet as TestCaseSetModel
)

logger = logging.getLogger(__name__)


class TestCaseSetService:
    """Test Case Set 業務邏輯"""

    def __init__(self, db: Session):
        self.db = db

    def create(self, team_id: int, name: str, description: str = None, is_default: bool = False) -> TestCaseSet:
        """建立新的 Test Case Set"""
        # 檢查名稱全域唯一性
        existing = self.db.query(TestCaseSet).filter(TestCaseSet.name == name).first()
        if existing:
            raise ValueError(f"Test Case Set 名稱已存在: {name}")

        new_set = TestCaseSet(
            team_id=team_id,
            name=name,
            description=description,
            is_default=is_default
        )

        try:
            self.db.add(new_set)
            self.db.flush()  # 先 flush 以獲取 ID

            # 建立預設的 Unassigned Section
            unassigned_section = TestCaseSection(
                test_case_set_id=new_set.id,
                name="Unassigned",
                description="未分配的測試案例",
                level=1,
                sort_order=0,
                parent_section_id=None
            )
            self.db.add(unassigned_section)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        refreshed_set = self.db.get(TestCaseSet, new_set.id)
        return refreshed_set or new_set

    def get_by_id(self, set_id: int, team_id: int = None) -> TestCaseSet:
        """根據 ID 取得 Test Case Set"""
        query = self.db.query(TestCaseSet).filter(TestCaseSet.id == set_id)
        if team_id:
            query = query.filter(TestCaseSet.team_id == team_id)
        return query.first()

    def list_by_team(self, team_id: int) -> list[TestCaseSet]:
        """列出指定團隊的所有 Test Case Sets (默認 Set 始終在前)"""
        return self.db.query(TestCaseSet).filter(
            TestCaseSet.team_id == team_id
        ).order_by(
            TestCaseSet.is_default.desc(),  # 默認 Set 優先 (true 在前)
            TestCaseSet.name.asc()  # 其他 Set 按名稱排序
        ).all()

    def get_or_create_default(self, team_id: int) -> TestCaseSet:
        """取得或建立團隊的預設 Test Case Set"""
        default_set = self.db.query(TestCaseSet).filter(
            and_(TestCaseSet.team_id == team_id, TestCaseSet.is_default == True)
        ).first()

        if not default_set:
            default_set = self.create(
                team_id=team_id,
                name=f"Default-{team_id}",
                description="團隊預設測試案例集合",
                is_default=True
            )

        return default_set

    def update(self, set_id: int, team_id: int, name: str = None, description: str = None) -> TestCaseSet:
        """更新 Test Case Set"""
        test_set = self.get_by_id(set_id, team_id)
        if not test_set:
            raise ValueError(f"Test Case Set 不存在: {set_id}")

        # 如果修改名稱，檢查新名稱的唯一性
        if name and name != test_set.name:
            existing = self.db.query(TestCaseSet).filter(TestCaseSet.name == name).first()
            if existing:
                raise ValueError(f"Test Case Set 名稱已存在: {name}")
            test_set.name = name

        if description is not None:
            test_set.description = description

        self.db.commit()
        return test_set

    def delete(self, set_id: int, team_id: int) -> bool:
        """刪除 Test Case Set，並將其中的 Test Case 移至預設 Set 的 Unassigned Section"""
        test_set = self.get_by_id(set_id, team_id)
        if not test_set:
            raise ValueError(f"Test Case Set 不存在: {set_id}")

        # 防止刪除預設 Set
        if test_set.is_default:
            raise ValueError("無法刪除預設 Test Case Set")

        # 獲取預設 Set
        default_set = self.db.query(TestCaseSet).filter(
            and_(TestCaseSet.team_id == team_id, TestCaseSet.is_default == True)
        ).first()

        if not default_set:
            raise ValueError("找不到預設 Test Case Set")

        # 獲取預設 Set 中的 Unassigned Section
        unassigned_section = self.db.query(TestCaseSection).filter(
            and_(
                TestCaseSection.test_case_set_id == default_set.id,
                TestCaseSection.name == "Unassigned"
            )
        ).first()

        if not unassigned_section:
            raise ValueError("找不到預設 Set 的 Unassigned Section")

        # 將所有 Test Case 移至預設 Set 的 Unassigned Section
        self.db.query(TestCaseLocal).filter(
            TestCaseLocal.test_case_set_id == set_id
        ).update({
            TestCaseLocal.test_case_set_id: default_set.id,
            TestCaseLocal.test_case_section_id: unassigned_section.id
        }, synchronize_session=False)

        # 刪除該 Set 的所有 Sections
        sections = self.db.query(TestCaseSection).filter(
            TestCaseSection.test_case_set_id == set_id
        ).all()

        for section in sections:
            self.db.delete(section)

        # 刪除 Test Case Set
        self.db.delete(test_set)
        self.db.commit()
        return True

    def validate_name_unique(self, name: str, exclude_set_id: int = None) -> bool:
        """驗證 Test Case Set 名稱全域唯一性"""
        query = self.db.query(TestCaseSet).filter(TestCaseSet.name == name)
        if exclude_set_id:
            query = query.filter(TestCaseSet.id != exclude_set_id)
        return query.first() is None

    def get_test_case_count(self, set_id: int) -> int:
        """取得 Set 中的 Test Case 數量"""
        return self.db.query(TestCaseLocal).filter(
            TestCaseLocal.test_case_set_id == set_id
        ).count()

    def get_set_with_sections(self, set_id: int, team_id: int = None) -> dict:
        """取得 Test Case Set 及其所有 Sections"""
        test_set = self.get_by_id(set_id, team_id)
        if not test_set:
            return None

        # 建立樹狀結構
        sections = (
            self.db.query(TestCaseSection)
            .filter(TestCaseSection.test_case_set_id == set_id)
            .order_by(
                TestCaseSection.parent_section_id.nullsfirst(),
                TestCaseSection.sort_order,
                TestCaseSection.id,
            )
            .all()
        )

        # 按層級和排序組織
        section_dict = {s.id: {'data': s, 'children': []} for s in sections}
        root_sections = []

        for section in sections:
            if section.parent_section_id is None:
                root_sections.append(section)
            else:
                if section.parent_section_id in section_dict:
                    section_dict[section.parent_section_id]['children'].append(section)

        return {
            'set': test_set,
            'sections': root_sections,
            'section_dict': section_dict,
            'test_case_count': self.get_test_case_count(set_id)
        }
