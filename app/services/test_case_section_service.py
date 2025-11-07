"""
測試案例區段 (Test Case Section) 服務層
"""

import logging
from typing import Optional, Union
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from ..models.database_models import TestCaseSection, TestCaseLocal, TestCaseSet

logger = logging.getLogger(__name__)


class TestCaseSectionService:
    """Test Case Section 業務邏輯"""

    def __init__(self, db: Session):
        self.db = db

    def create(self, test_case_set_id: int, name: str, description: str = None,
               parent_section_id: int = None) -> TestCaseSection:
        """建立新的 Test Case Section"""
        # 驗證 parent section 存在
        if parent_section_id:
            parent = self.get_by_id(parent_section_id)
            if not parent:
                raise ValueError(f"父 Section 不存在: {parent_section_id}")
            if parent.test_case_set_id != test_case_set_id:
                raise ValueError("父 Section 必須屬於同一個 Test Case Set")
            parent_level = parent.level
        else:
            parent_level = 0

        # 檢查層級限制 (最多 5 層)
        new_level = parent_level + 1
        if new_level > 5:
            raise ValueError("Section 最多只能 5 層深")

        # 檢查同層級名稱唯一性
        existing = self.db.query(TestCaseSection).filter(
            and_(
                TestCaseSection.test_case_set_id == test_case_set_id,
                TestCaseSection.parent_section_id == parent_section_id,
                TestCaseSection.name == name
            )
        ).first()

        if existing:
            raise ValueError(f"此層級下已存在相同名稱的 Section: {name}")

        # 計算 sort_order (使用同層級現有最大值 + 1，避免刪除後的空缺導致重複序號)
        max_sort = self.db.query(func.max(TestCaseSection.sort_order)).filter(
            and_(
                TestCaseSection.test_case_set_id == test_case_set_id,
                TestCaseSection.parent_section_id == parent_section_id
            )
        ).scalar()
        next_sort = (max_sort if max_sort is not None else -1) + 1

        new_section = TestCaseSection(
            test_case_set_id=test_case_set_id,
            name=name,
            description=description,
            parent_section_id=parent_section_id,
            level=new_level,
            sort_order=next_sort
        )

        self.db.add(new_section)
        self.db.commit()

        return new_section

    def get_by_id(self, section_id: int) -> TestCaseSection:
        """根據 ID 取得 Section"""
        return self.db.query(TestCaseSection).filter(
            TestCaseSection.id == section_id
        ).first()

    def get_by_set(self, test_case_set_id: int) -> list[TestCaseSection]:
        """取得 Set 下所有 Sections，按 sort_order 和 id 排序"""
        return (
            self.db.query(TestCaseSection)
            .filter(TestCaseSection.test_case_set_id == test_case_set_id)
            .order_by(
                TestCaseSection.sort_order,
                TestCaseSection.id
            )
            .all()
        )

    def get_tree_structure(self, test_case_set_id: int) -> list:
        """取得 Section 樹狀結構"""
        # 按照 sort_order, id 順序取得所有 sections
        sections = (
            self.db.query(TestCaseSection)
            .filter(TestCaseSection.test_case_set_id == test_case_set_id)
            .order_by(
                TestCaseSection.sort_order,
                TestCaseSection.id
            )
            .all()
        )

        # 一次性查詢所有 section 的 test case 數量（避免 N+1 查詢）
        test_case_counts = {}
        if sections:
            section_ids = [s.id for s in sections]
            counts_result = (
                self.db.query(
                    TestCaseLocal.test_case_section_id,
                    func.count(TestCaseLocal.id).label('count')
                ).filter(
                    TestCaseLocal.test_case_section_id.in_(section_ids)
                ).group_by(TestCaseLocal.test_case_section_id).all()
            )
            test_case_counts = {section_id: count for section_id, count in counts_result}

        # 建立字典以便查詢
        section_dict = {
            s.id: {
                'id': s.id,
                'name': s.name,
                'description': s.description,
                'level': s.level,
                'sort_order': s.sort_order,
                'parent_section_id': s.parent_section_id,
                'test_case_set_id': s.test_case_set_id,
                'test_case_count': test_case_counts.get(s.id, 0),
                'children': [],
            }
            for s in sections
        }

        # 建立樹狀結構
        root_sections = []
        for section in sections:
            node = section_dict[section.id]
            if section.parent_section_id is None:
                root_sections.append(node)
            else:
                if section.parent_section_id in section_dict:
                    section_dict[section.parent_section_id]['children'].append(node)

        # 排序所有層級（根據 sort_order 和 id）
        self._sort_children(root_sections)

        return root_sections

    def update(self, section_id: int, name: str = None, description: str = None) -> TestCaseSection:
        """更新 Section"""
        section = self.get_by_id(section_id)
        if not section:
            raise ValueError(f"Section 不存在: {section_id}")

        # 特殊檢查：不允許重命名 Unassigned
        if section.name == "Unassigned" and name and name != "Unassigned":
            raise ValueError("無法重命名 'Unassigned' Section")

        # 如果修改名稱，檢查同層級唯一性
        if name and name != section.name:
            existing = self.db.query(TestCaseSection).filter(
                and_(
                    TestCaseSection.test_case_set_id == section.test_case_set_id,
                    TestCaseSection.parent_section_id == section.parent_section_id,
                    TestCaseSection.name == name,
                    TestCaseSection.id != section_id
                )
            ).first()

            if existing:
                raise ValueError(f"此層級下已存在相同名稱的 Section: {name}")

            section.name = name

        if description is not None:
            section.description = description

        self.db.commit()
        return section

    def delete(self, section_id: int) -> bool:
        """刪除 Section 及其所有子 Sections 和 Test Cases"""
        section = self.get_by_id(section_id)
        if not section:
            raise ValueError(f"Section 不存在: {section_id}")

        # 特殊檢查：不允許刪除 Unassigned
        if section.name == "Unassigned":
            raise ValueError("無法刪除 'Unassigned' Section")

        # 取得所有子 Sections ID
        child_ids = self._get_all_child_section_ids(section_id)
        all_ids = [section_id] + child_ids

        # 將這些 Sections 中的 Test Cases 移到 Unassigned
        unassigned = self.db.query(TestCaseSection).filter(
            and_(
                TestCaseSection.test_case_set_id == section.test_case_set_id,
                TestCaseSection.name == "Unassigned"
            )
        ).first()

        if unassigned:
            self.db.query(TestCaseLocal).filter(
                TestCaseLocal.test_case_section_id.in_(all_ids)
            ).update({TestCaseLocal.test_case_section_id: unassigned.id})

        # 刪除 Sections (級聯刪除)
        self.db.delete(section)
        self.db.commit()

        return True

    def reorder(self, test_case_set_id: int, orders: list[dict]) -> bool:
        """重新排序 Sections

        orders: [
            {"id": 1, "sort_order": 0, "parent_section_id": null},
            ...
        ]
        """
        for order_item in orders:
            section = self.get_by_id(order_item['id'])
            if not section or section.test_case_set_id != test_case_set_id:
                raise ValueError(f"無效的 Section ID: {order_item['id']}")

            section.sort_order = order_item.get('sort_order', 0)

            # 如果移動到不同的父 Section，需要驗證並更新層級
            new_parent_id = self._normalize_parent_id(order_item.get('parent_section_id'))

            if new_parent_id != section.parent_section_id:
                if new_parent_id is not None:
                    if not self._can_move_to_parent(section.id, new_parent_id, test_case_set_id):
                        raise ValueError(f"無法移動 Section {section.id} 到父 Section {new_parent_id}")
                    parent = self.get_by_id(new_parent_id)
                    if not parent:
                        raise ValueError(f"父 Section 不存在: {new_parent_id}")
                    section.parent_section_id = new_parent_id
                    section.level = parent.level + 1
                    self._update_child_levels(section.id)
                else:
                    section.parent_section_id = None
                    section.level = 1
                    self._update_child_levels(section.id)

        self.db.commit()
        return True

    def move(self, section_id: int, new_parent_id: int = None) -> TestCaseSection:
        """移動 Section 到新的父 Section"""
        section = self.get_by_id(section_id)
        if not section:
            raise ValueError(f"Section 不存在: {section_id}")

        if new_parent_id:
            parent = self.get_by_id(new_parent_id)
            if not parent:
                raise ValueError(f"父 Section 不存在: {new_parent_id}")
            if parent.test_case_set_id != section.test_case_set_id:
                raise ValueError("父 Section 必須屬於同一個 Test Case Set")

            # 檢查層級限制和防止循環參考
            if not self._can_move_to_parent(section_id, new_parent_id, section.test_case_set_id):
                raise ValueError("無法執行此移動操作")

            section.parent_section_id = new_parent_id
            section.level = parent.level + 1
            self._update_child_levels(section.id)
        else:
            section.parent_section_id = None
            section.level = 1
            self._update_child_levels(section.id)

        self.db.commit()
        return section

    # ==================== 私有方法 ====================

    def _get_test_case_count(self, section_id: int) -> int:
        """取得該 Section 直接下的 Test Case 數量 (不含子 Sections)"""
        return self.db.query(TestCaseLocal).filter(
            TestCaseLocal.test_case_section_id == section_id
        ).count()

    def _get_all_child_section_ids(self, section_id: int) -> list:
        """遞迴取得所有子 Sections ID"""
        child_ids = []
        children = self.db.query(TestCaseSection).filter(
            TestCaseSection.parent_section_id == section_id
        ).all()

        for child in children:
            child_ids.append(child.id)
            child_ids.extend(self._get_all_child_section_ids(child.id))

        return child_ids

    def _normalize_parent_id(self, value):
        """將輸入的 parent_section_id 轉換為 int 或 None"""
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            if stripped == "" or stripped.lower() == "null":
                return None
            try:
                return int(stripped)
            except ValueError as exc:
                raise ValueError(f"無效的父 Section ID: {value}") from exc
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"無效的父 Section ID: {value}") from exc

    def _update_child_levels(self, section_id: int) -> None:
        """根據父節點層級遞迴更新所有子節點層級"""
        root = self.get_by_id(section_id)
        if not root:
            return
        queue = [(root.id, root.level)]
        while queue:
            current_id, current_level = queue.pop(0)
            children = self.db.query(TestCaseSection).filter(
                TestCaseSection.parent_section_id == current_id
            ).all()
            for child in children:
                child.level = current_level + 1
                queue.append((child.id, child.level))

    def _can_move_to_parent(self, section_id: int, new_parent_id: int, test_case_set_id: int) -> bool:
        """檢查是否可以移動到新的父 Section"""
        # 防止循環參考 (子移到父)
        if new_parent_id == section_id:
            return False

        # 檢查新父是否為此 Section 的子
        descendants = self._get_all_child_section_ids(section_id)
        if new_parent_id in descendants:
            return False

        # 檢查層級限制
        new_parent = self.get_by_id(new_parent_id)
        if new_parent and new_parent.level >= 4:  # 最多 5 層，所以父親最多 4 層
            return False

        return True

    def _sort_children(self, nodes: list):
        """遞迴排序子元素（按 sort_order, id 排序）"""
        def sort_key(node):
            # 先按 sort_order，再按 id 排序，確保順序穩定
            order = node.get('sort_order')
            node_id = node.get('id') or 0
            return (order if order is not None else 999999, node_id)

        nodes.sort(key=sort_key)
        for node in nodes:
            if node.get('children'):
                self._sort_children(node['children'])
