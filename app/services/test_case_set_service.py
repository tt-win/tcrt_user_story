"""
測試案例集合 (Test Case Set) 服務層
"""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from ..models.database_models import TestCaseSet, TestCaseSection, TestCaseLocal
from ..models.test_case_set import (
    TestCaseSetCreate, TestCaseSetUpdate, TestCaseSet as TestCaseSetModel
)
from ..database import run_sync
from ..services.test_run_scope_service import TestRunScopeService

logger = logging.getLogger(__name__)


class TestCaseSetService:
    """Test Case Set 業務邏輯"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, team_id: int, name: str, description: str = None, is_default: bool = False) -> TestCaseSet:
        """建立新的 Test Case Set"""
        def _create(sync_db: Session) -> TestCaseSet:
            # 檢查名稱全域唯一性
            existing = sync_db.query(TestCaseSet).filter(TestCaseSet.name == name).first()
            if existing:
                raise ValueError(f"Test Case Set 名稱已存在: {name}")

            new_set = TestCaseSet(
                team_id=team_id,
                name=name,
                description=description,
                is_default=is_default
            )

            try:
                sync_db.add(new_set)
                sync_db.flush()  # 先 flush 以獲取 ID

                # 建立預設的 Unassigned Section
                unassigned_section = TestCaseSection(
                    test_case_set_id=new_set.id,
                    name="Unassigned",
                    description="未分配的測試案例",
                    level=1,
                    sort_order=0,
                    parent_section_id=None
                )
                sync_db.add(unassigned_section)
                sync_db.commit()
            except Exception:
                sync_db.rollback()
                raise

            refreshed_set = sync_db.get(TestCaseSet, new_set.id)
            return refreshed_set or new_set

        return await run_sync(self.db, _create)

    async def get_by_id(self, set_id: int, team_id: int = None) -> TestCaseSet:
        """根據 ID 取得 Test Case Set"""
        def _get(sync_db: Session) -> TestCaseSet:
            query = sync_db.query(TestCaseSet).filter(TestCaseSet.id == set_id)
            if team_id:
                query = query.filter(TestCaseSet.team_id == team_id)
            return query.first()

        return await run_sync(self.db, _get)

    async def list_by_team(self, team_id: int) -> list[TestCaseSet]:
        """列出指定團隊的所有 Test Case Sets (默認 Set 始終在前)"""
        def _list(sync_db: Session) -> list[TestCaseSet]:
            return sync_db.query(TestCaseSet).filter(
                TestCaseSet.team_id == team_id
            ).order_by(
                TestCaseSet.is_default.desc(),  # 默認 Set 優先 (true 在前)
                TestCaseSet.name.asc()  # 其他 Set 按名稱排序
            ).all()

        return await run_sync(self.db, _list)

    async def get_or_create_default(self, team_id: int) -> TestCaseSet:
        """取得或建立團隊的預設 Test Case Set"""
        def _get_or_create(sync_db: Session) -> TestCaseSet:
            default_set = sync_db.query(TestCaseSet).filter(
                and_(TestCaseSet.team_id == team_id, TestCaseSet.is_default == True)
            ).first()

            if not default_set:
                default_set = TestCaseSet(
                    team_id=team_id,
                    name=f"Default-{team_id}",
                    description="團隊預設測試案例集合",
                    is_default=True
                )
                sync_db.add(default_set)
                sync_db.flush()
                unassigned_section = TestCaseSection(
                    test_case_set_id=default_set.id,
                    name="Unassigned",
                    description="未分配的測試案例",
                    level=1,
                    sort_order=0,
                    parent_section_id=None
                )
                sync_db.add(unassigned_section)
                sync_db.commit()

            return default_set

        return await run_sync(self.db, _get_or_create)

    async def update(self, set_id: int, team_id: int, name: str = None, description: str = None) -> TestCaseSet:
        """更新 Test Case Set"""
        def _update(sync_db: Session) -> TestCaseSet:
            test_set = sync_db.query(TestCaseSet).filter(
                TestCaseSet.id == set_id,
                TestCaseSet.team_id == team_id
            ).first()
            if not test_set:
                raise ValueError(f"Test Case Set 不存在: {set_id}")

            # 如果修改名稱，檢查新名稱的唯一性
            if name and name != test_set.name:
                existing = sync_db.query(TestCaseSet).filter(TestCaseSet.name == name).first()
                if existing:
                    raise ValueError(f"Test Case Set 名稱已存在: {name}")
                test_set.name = name

            if description is not None:
                test_set.description = description

            sync_db.commit()
            return test_set

        return await run_sync(self.db, _update)

    async def delete(self, set_id: int, team_id: int) -> dict:
        """刪除 Test Case Set，並將其中的 Test Case 移至預設 Set 的 Unassigned Section"""
        def _delete(sync_db: Session) -> dict:
            test_set = sync_db.query(TestCaseSet).filter(
                TestCaseSet.id == set_id,
                TestCaseSet.team_id == team_id
            ).first()
            if not test_set:
                raise ValueError(f"Test Case Set 不存在: {set_id}")

            # 防止刪除預設 Set
            if test_set.is_default:
                raise ValueError("無法刪除預設 Test Case Set")

            # 獲取預設 Set
            default_set = sync_db.query(TestCaseSet).filter(
                and_(TestCaseSet.team_id == team_id, TestCaseSet.is_default == True)
            ).first()

            if not default_set:
                raise ValueError("找不到預設 Test Case Set")

            # 獲取預設 Set 中的 Unassigned Section
            unassigned_section = sync_db.query(TestCaseSection).filter(
                and_(
                    TestCaseSection.test_case_set_id == default_set.id,
                    TestCaseSection.name == "Unassigned"
                )
            ).first()

            if not unassigned_section:
                raise ValueError("找不到預設 Set 的 Unassigned Section")

            cleanup_summary = TestRunScopeService.cleanup_set_deletion(
                sync_db,
                team_id=team_id,
                set_id=set_id,
            )
            scope_updates = TestRunScopeService.remove_set_from_all_scopes(
                sync_db,
                team_id=team_id,
                set_id=set_id,
            )

            # 將所有 Test Case 移至預設 Set 的 Unassigned Section
            moved_test_case_count = sync_db.query(TestCaseLocal).filter(
                TestCaseLocal.test_case_set_id == set_id
            ).count()

            sync_db.query(TestCaseLocal).filter(
                TestCaseLocal.test_case_set_id == set_id
            ).update({
                TestCaseLocal.test_case_set_id: default_set.id,
                TestCaseLocal.test_case_section_id: unassigned_section.id
            }, synchronize_session=False)

            # 刪除該 Set 的所有 Sections
            sections = sync_db.query(TestCaseSection).filter(
                TestCaseSection.test_case_set_id == set_id
            ).all()

            for section in sections:
                sync_db.delete(section)

            # 刪除 Test Case Set
            sync_db.delete(test_set)
            sync_db.commit()
            return {
                "cleanup_summary": cleanup_summary,
                "moved_test_case_count": moved_test_case_count,
                "default_set_id": default_set.id,
                "default_section_id": unassigned_section.id,
                "updated_scope_config_count": len(scope_updates),
            }

        return await run_sync(self.db, _delete)

    async def validate_name_unique(self, name: str, exclude_set_id: int = None) -> bool:
        """驗證 Test Case Set 名稱全域唯一性"""
        def _validate(sync_db: Session) -> bool:
            query = sync_db.query(TestCaseSet).filter(TestCaseSet.name == name)
            if exclude_set_id:
                query = query.filter(TestCaseSet.id != exclude_set_id)
            return query.first() is None

        return await run_sync(self.db, _validate)

    async def get_test_case_count(self, set_id: int) -> int:
        """取得 Set 中的 Test Case 數量"""
        def _count(sync_db: Session) -> int:
            return sync_db.query(TestCaseLocal).filter(
                TestCaseLocal.test_case_set_id == set_id
            ).count()

        return await run_sync(self.db, _count)

    async def get_set_with_sections(self, set_id: int, team_id: int = None) -> dict:
        """取得 Test Case Set 及其所有 Sections"""
        def _get(sync_db: Session) -> dict:
            test_set = sync_db.query(TestCaseSet).filter(TestCaseSet.id == set_id).first()
            if team_id:
                test_set = sync_db.query(TestCaseSet).filter(
                    TestCaseSet.id == set_id,
                    TestCaseSet.team_id == team_id
                ).first()
            if not test_set:
                return None

            # 建立樹狀結構
            sections = (
                sync_db.query(TestCaseSection)
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

            test_case_count = sync_db.query(TestCaseLocal).filter(
                TestCaseLocal.test_case_set_id == set_id
            ).count()

            return {
                'set': test_set,
                'sections': root_sections,
                'section_dict': section_dict,
                'test_case_count': test_case_count
            }

        return await run_sync(self.db, _get)
