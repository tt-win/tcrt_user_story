"""
測試案例集合 (Test Case Set) API 路由
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
from sqlalchemy.orm import Session
from typing import List, Optional
import logging

from ..database import get_sync_db
from ..auth.dependencies import get_current_user
from ..auth.models import User
from ..models.database_models import TestCaseSet as TestCaseSetDB, Team as TeamDB
from ..models.test_case_set import (
    TestCaseSet,
    TestCaseSetCreate,
    TestCaseSetUpdate,
    TestCaseSetWithSections,
    TestCaseSetNameValidationResponse,
)
from ..services.test_case_set_service import TestCaseSetService
from ..audit import audit_service, ActionType, ResourceType, AuditSeverity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/teams", tags=["test-case-sets"])

# 註: 所有路由都應用 /teams 前綴


async def log_set_action(
    action_type: ActionType,
    current_user: User,
    team_id: int,
    set_id: int,
    action_brief: str,
    details: dict = None,
) -> None:
    """記錄 Test Case Set 操作的審計日誌"""
    try:
        role_value = (
            current_user.role.value
            if hasattr(current_user.role, "value")
            else str(current_user.role)
        )
        await audit_service.log_action(
            user_id=current_user.id,
            username=current_user.username,
            role=role_value,
            action_type=action_type,
            resource_type=ResourceType.TEST_CASE_SET,
            resource_id=str(set_id),
            team_id=team_id,
            details=details,
            action_brief=action_brief,
            severity=AuditSeverity.CRITICAL if action_type == ActionType.DELETE else AuditSeverity.INFO,
        )
    except Exception as exc:
        logger.warning("寫入 Test Case Set 審計記錄失敗: %s", exc, exc_info=True)


async def verify_team_write_permission(
    team_id: int = Path(...),
    db: Session = Depends(get_sync_db),
) -> TeamDB:
    """驗證團隊存在"""
    try:
        team = db.query(TeamDB).filter(TeamDB.id == team_id).first()
        if not team:
            logger.warning(f"Team {team_id} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Team {team_id} not found",
            )
        return team
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying team permission: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="驗證團隊失敗",
        )


@router.post("/{team_id}/test-case-sets", response_model=TestCaseSet, status_code=status.HTTP_201_CREATED)
async def create_test_case_set(
    team_id: int,
    request: TestCaseSetCreate,
    current_user: User = Depends(get_current_user),
    team: TeamDB = Depends(verify_team_write_permission),
    db: Session = Depends(get_sync_db),
) -> TestCaseSet:
    """建立新的 Test Case Set"""
    try:
        service = TestCaseSetService(db)
        new_set = service.create(
            team_id=team_id,
            name=request.name,
            description=request.description,
        )

        await log_set_action(
            ActionType.CREATE,
            current_user,
            team_id,
            new_set.id,
            f"建立 Test Case Set: {request.name}",
            {"name": request.name, "description": request.description},
        )

        # 計算並添加 test_case_count
        result = TestCaseSet.from_orm(new_set)
        result.test_case_count = service.get_test_case_count(new_set.id)
        return result

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"建立 Test Case Set 失敗: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="建立 Test Case Set 失敗",
        )


@router.get("/{team_id}/test-case-sets", response_model=List[TestCaseSet])
async def list_test_case_sets(
    team_id: int,
    current_user: User = Depends(get_current_user),
    team: TeamDB = Depends(verify_team_write_permission),
    db: Session = Depends(get_sync_db),
) -> List[TestCaseSet]:
    """列出指定團隊的所有 Test Case Sets"""
    try:
        service = TestCaseSetService(db)
        sets = service.list_by_team(team_id)

        # 為每個 Set 計算 test_case_count
        result = []
        for s in sets:
            set_dict = TestCaseSet.from_orm(s).model_dump()
            set_dict['test_case_count'] = service.get_test_case_count(s.id)
            result.append(TestCaseSet(**set_dict))

        return result

    except Exception as e:
        logger.error(f"查詢 Test Case Sets 失敗: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="查詢 Test Case Sets 失敗",
        )


@router.get("/{team_id}/test-case-sets/{set_id}")
async def get_test_case_set(
    team_id: int,
    set_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_sync_db),
):
    """取得單個 Test Case Set 及其 Sections"""
    try:
        logger.info(f"Getting test case set {set_id} for team {team_id}")

        # 驗證團隊存在
        team = db.query(TeamDB).filter(TeamDB.id == team_id).first()
        if not team:
            logger.warning(f"Team {team_id} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Team {team_id} not found",
            )

        service = TestCaseSetService(db)
        set_data = service.get_set_with_sections(set_id, team_id)

        if not set_data:
            logger.warning(f"Test Case Set {set_id} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Test Case Set {set_id} not found",
            )

        logger.info(f"Set data retrieved, sections count: {len(set_data.get('sections', []))}")

        # 查詢每個 section 的 test case 數量
        from ..models.database_models import TestCaseLocal
        section_test_case_counts = {}
        all_test_cases = db.query(TestCaseLocal).filter(
            TestCaseLocal.test_case_set_id == set_id
        ).all()

        for tc in all_test_cases:
            section_id = tc.test_case_section_id
            if section_id not in section_test_case_counts:
                section_test_case_counts[section_id] = 0
            section_test_case_counts[section_id] += 1

        # 構建 sections 樹狀結構
        def build_section_tree(section, section_dict, test_case_counts):
            # 獲取子節點列表
            children_data = section_dict.get(section.id, {}).get('children', [])
            if children_data:
                children_data = sorted(
                    children_data,
                    key=lambda child: (child.sort_order or 0, child.id or 0)
                )

            section_data = {
                'id': section.id,
                'name': section.name,
                'test_case_set_id': section.test_case_set_id,
                'parent_section_id': section.parent_section_id,
                'level': section.level,
                'sort_order': section.sort_order,
                'test_case_count': test_case_counts.get(section.id, 0),
                'child_sections': []
            }

            # 遞迴添加子節點
            for child_section in children_data:
                section_data['child_sections'].append(build_section_tree(child_section, section_dict, test_case_counts))

            return section_data

        root_sections_ordered = sorted(
            set_data['sections'],
            key=lambda s: (s.sort_order or 0, s.id or 0)
        )

        sections_list = []
        for root_section in root_sections_ordered:
            sections_list.append(build_section_tree(root_section, set_data['section_dict'], section_test_case_counts))

        # 構建完整的回應
        test_set = set_data['set']
        response = {
            'id': test_set.id,
            'team_id': test_set.team_id,
            'name': test_set.name,
            'description': test_set.description,
            'is_default': test_set.is_default,
            'created_at': test_set.created_at.isoformat() if test_set.created_at else None,
            'updated_at': test_set.updated_at.isoformat() if test_set.updated_at else None,
            'test_case_count': set_data['test_case_count'],
            'sections': sections_list
        }

        logger.info(f"Successfully built response with {len(sections_list)} root sections")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查詢 Test Case Set 失敗: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查詢 Test Case Set 失敗",
        )


@router.put("/{team_id}/test-case-sets/{set_id}", response_model=TestCaseSet)
async def update_test_case_set(
    team_id: int,
    set_id: int,
    request: TestCaseSetUpdate,
    current_user: User = Depends(get_current_user),
    team: TeamDB = Depends(verify_team_write_permission),
    db: Session = Depends(get_sync_db),
) -> TestCaseSet:
    """更新 Test Case Set"""
    try:
        service = TestCaseSetService(db)
        updated_set = service.update(
            set_id=set_id,
            team_id=team_id,
            name=request.name,
            description=request.description,
        )

        await log_set_action(
            ActionType.UPDATE,
            current_user,
            team_id,
            set_id,
            f"更新 Test Case Set: {updated_set.name}",
            request.dict(exclude_none=True),
        )

        # 計算並添加 test_case_count
        result = TestCaseSet.from_orm(updated_set)
        result.test_case_count = service.get_test_case_count(set_id)
        return result

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"更新 Test Case Set 失敗: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新 Test Case Set 失敗",
        )


@router.delete("/{team_id}/test-case-sets/{set_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_test_case_set(
    team_id: int,
    set_id: int,
    current_user: User = Depends(get_current_user),
    team: TeamDB = Depends(verify_team_write_permission),
    db: Session = Depends(get_sync_db),
) -> None:
    """刪除 Test Case Set"""
    try:
        service = TestCaseSetService(db)
        service.delete(set_id, team_id)

        await log_set_action(
            ActionType.DELETE,
            current_user,
            team_id,
            set_id,
            f"刪除 Test Case Set: {set_id}",
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"刪除 Test Case Set 失敗: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="刪除 Test Case Set 失敗",
        )


@router.post("/test-case-sets/validate-name", response_model=TestCaseSetNameValidationResponse)
async def validate_test_case_set_name(
    name: str = Query(..., description="Test Case Set 名稱"),
    exclude_set_id: Optional[int] = Query(None, description="要排除的 Set ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_sync_db),
) -> TestCaseSetNameValidationResponse:
    """驗證 Test Case Set 名稱全域唯一性"""
    try:
        service = TestCaseSetService(db)
        is_valid = service.validate_name_unique(name, exclude_set_id)

        return TestCaseSetNameValidationResponse(
            is_valid=is_valid,
            message=None if is_valid else f"Test Case Set 名稱已存在: {name}",
        )

    except Exception as e:
        logger.error(f"驗證 Test Case Set 名稱失敗: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="驗證名稱失敗",
        )
