"""
測試案例區段 (Test Case Section) API 路由
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
import logging

from ..database import get_sync_db
from ..auth.dependencies import get_current_user
from ..auth.models import PermissionType, User
from ..models.database_models import TestCaseSet as TestCaseSetDB, Team as TeamDB
from ..models.test_case_set import (
    TestCaseSection,
    TestCaseSectionCreate,
    TestCaseSectionUpdate,
    TestCaseSectionWithChildren,
    TestCaseSectionReorderRequest,
)
from ..services.test_case_section_service import TestCaseSectionService
from ..services.test_case_set_service import TestCaseSetService
from ..audit import audit_service, ActionType, ResourceType, AuditSeverity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/test-case-sets", tags=["test-case-sections"])


async def log_section_action(
    action_type: ActionType,
    current_user: User,
    team_id: int,
    section_id: int,
    action_brief: str,
    details: dict = None,
) -> None:
    """記錄 Test Case Section 操作的審計日誌"""
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
            resource_type=ResourceType.TEST_CASE_SECTION,
            resource_id=str(section_id),
            team_id=team_id,
            details=details,
            action_brief=action_brief,
            severity=AuditSeverity.CRITICAL if action_type == ActionType.DELETE else AuditSeverity.INFO,
        )
    except Exception as exc:
        logger.warning("寫入 Test Case Section 審計記錄失敗: %s", exc, exc_info=True)


async def verify_test_case_set_access(
    set_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_sync_db),
) -> TestCaseSetDB:
    """驗證使用者對 Test Case Set 的訪問權限"""
    test_set = db.query(TestCaseSetDB).filter(TestCaseSetDB.id == set_id).first()
    if not test_set:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test Case Set {set_id} not found",
        )

    # 簡化權限檢查 - 只確認使用者已認證即可
    # 後續可根據需要添加更詳細的權限檢查
    return test_set


@router.post("/{set_id}/sections", response_model=TestCaseSection, status_code=status.HTTP_201_CREATED)
async def create_section(
    set_id: int,
    request: TestCaseSectionCreate,
    current_user: User = Depends(get_current_user),
    test_set: TestCaseSetDB = Depends(verify_test_case_set_access),
    db: Session = Depends(get_sync_db),
) -> TestCaseSection:
    """建立新的 Test Case Section"""
    try:
        service = TestCaseSectionService(db)
        new_section = service.create(
            test_case_set_id=set_id,
            name=request.name,
            description=request.description,
            parent_section_id=request.parent_section_id,
        )

        await log_section_action(
            ActionType.CREATE,
            current_user,
            test_set.team_id,
            new_section.id,
            f"建立 Test Case Section: {request.name}",
            {"name": request.name, "description": request.description},
        )

        return TestCaseSection.from_orm(new_section)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"建立 Test Case Section 失敗: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="建立 Test Case Section 失敗",
        )


@router.get("/{set_id}/sections", response_model=List[Dict[str, Any]])
async def get_sections_tree(
    set_id: int,
    current_user: User = Depends(get_current_user),
    test_set: TestCaseSetDB = Depends(verify_test_case_set_access),
    db: Session = Depends(get_sync_db),
) -> List[Dict[str, Any]]:
    """取得 Test Case Set 的 Sections 樹狀結構"""
    try:
        service = TestCaseSectionService(db)
        tree = service.get_tree_structure(set_id)
        return tree

    except Exception as e:
        logger.error(f"查詢 Test Case Sections 失敗: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="查詢 Test Case Sections 失敗",
        )


@router.get("/{set_id}/sections/{section_id}", response_model=TestCaseSection)
async def get_section(
    set_id: int,
    section_id: int,
    current_user: User = Depends(get_current_user),
    test_set: TestCaseSetDB = Depends(verify_test_case_set_access),
    db: Session = Depends(get_sync_db),
) -> TestCaseSection:
    """取得單個 Test Case Section"""
    try:
        service = TestCaseSectionService(db)
        section = service.get_by_id(section_id)

        if not section or section.test_case_set_id != set_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Test Case Section {section_id} not found",
            )

        return TestCaseSection.from_orm(section)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查詢 Test Case Section 失敗: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="查詢 Test Case Section 失敗",
        )


@router.put("/{set_id}/sections/{section_id}", response_model=TestCaseSection)
async def update_section(
    set_id: int,
    section_id: int,
    request: TestCaseSectionUpdate,
    current_user: User = Depends(get_current_user),
    test_set: TestCaseSetDB = Depends(verify_test_case_set_access),
    db: Session = Depends(get_sync_db),
) -> TestCaseSection:
    """更新 Test Case Section"""
    try:
        service = TestCaseSectionService(db)
        section = service.get_by_id(section_id)

        if not section or section.test_case_set_id != set_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Test Case Section {section_id} not found",
            )

        updated_section = service.update(
            section_id=section_id,
            name=request.name,
            description=request.description,
        )

        await log_section_action(
            ActionType.UPDATE,
            current_user,
            test_set.team_id,
            section_id,
            f"更新 Test Case Section: {updated_section.name}",
            request.dict(exclude_none=True),
        )

        return TestCaseSection.from_orm(updated_section)

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"更新 Test Case Section 失敗: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新 Test Case Section 失敗",
        )


@router.delete("/{set_id}/sections/{section_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_section(
    set_id: int,
    section_id: int,
    current_user: User = Depends(get_current_user),
    test_set: TestCaseSetDB = Depends(verify_test_case_set_access),
    db: Session = Depends(get_sync_db),
) -> None:
    """刪除 Test Case Section"""
    try:
        service = TestCaseSectionService(db)
        section = service.get_by_id(section_id)

        if not section or section.test_case_set_id != set_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Test Case Section {section_id} not found",
            )

        service.delete(section_id)

        await log_section_action(
            ActionType.DELETE,
            current_user,
            test_set.team_id,
            section_id,
            f"刪除 Test Case Section: {section.name}",
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"刪除 Test Case Section 失敗: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="刪除 Test Case Section 失敗",
        )


@router.post("/{set_id}/sections/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_sections(
    set_id: int,
    request: TestCaseSectionReorderRequest,
    current_user: User = Depends(get_current_user),
    test_set: TestCaseSetDB = Depends(verify_test_case_set_access),
    db: Session = Depends(get_sync_db),
) -> None:
    """重新排序 Sections"""
    try:
        service = TestCaseSectionService(db)
        service.reorder(set_id, request.sections)

        await log_section_action(
            ActionType.UPDATE,
            current_user,
            test_set.team_id,
            -1,  # 使用 -1 表示批量操作
            "重新排序 Test Case Sections",
            {"sections_count": len(request.sections)},
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"重新排序 Test Case Sections 失敗: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="重新排序 Test Case Sections 失敗",
        )


@router.post("/{set_id}/sections/{section_id}/move", response_model=TestCaseSection)
async def move_section(
    set_id: int,
    section_id: int,
    new_parent_id: Optional[int] = Query(None),
    current_user: User = Depends(get_current_user),
    test_set: TestCaseSetDB = Depends(verify_test_case_set_access),
    db: Session = Depends(get_sync_db),
) -> TestCaseSection:
    """移動 Section 到新的父 Section"""
    try:
        service = TestCaseSectionService(db)
        section = service.get_by_id(section_id)

        if not section or section.test_case_set_id != set_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Test Case Section {section_id} not found",
            )

        updated_section = service.move(section_id, new_parent_id)

        await log_section_action(
            ActionType.UPDATE,
            current_user,
            test_set.team_id,
            section_id,
            f"移動 Test Case Section: {updated_section.name}",
            {"new_parent_id": new_parent_id},
        )

        return TestCaseSection.from_orm(updated_section)

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"移動 Test Case Section 失敗: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="移動 Test Case Section 失敗",
        )
