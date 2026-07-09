"""
使用者釘選 (Pin) API 路由

Per-user 釘選：使用者可將 Test Case Set / Test Run Set / Test Run / Ad-hoc Run
釘選，前端在卡片與精簡列表中把釘選項目永遠置頂（釘選群組內依建立日期排序）。

刻意與四種物件的既有 list endpoint 解耦：釘選狀態由此獨立 endpoint 提供，
前端載入清單後再合併，既有 API 與 response model 完全不受影響。

列表回應同時併入該 team 的 AppTokenPin（team-scoped，由 /api/app/* app token
建立的共用釘選）；create/delete 僅操作 UserPin，不會寫入或刪除 AppTokenPin —
app token 建立的釘選只能透過 /api/app/teams/{team_id}/pins 管理。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..auth.models import User
from ..db_access import MainAccessBoundary, get_main_access_boundary
from ..models.database_models import AppTokenPin, UserPin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pins", tags=["pins"])

# 允許釘選的物件類型（與前端 PinStore 的 key 一致）
ENTITY_TYPES = {"test_case_set", "test_run_set", "test_run", "adhoc_run"}


class PinCreate(BaseModel):
    team_id: int
    entity_type: str
    entity_id: int


def _validate_entity_type(entity_type: str) -> None:
    if entity_type not in ENTITY_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid entity_type: {entity_type}",
        )


@router.get("")
async def list_pins(
    team_id: int = Query(...),
    current_user: User = Depends(get_current_user),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> dict:
    """取得目前使用者在某團隊的所有釘選（個人 + app token 團隊共用），依物件類型分組回傳
    id 陣列；另外以 `token_pinned` 標示哪些 id 是 app token 釘選（非個人釘選，前端不可
    透過一般取消釘選操作移除）。"""
    try:
        def _load(sync_db: Session):
            user_rows = (
                sync_db.query(UserPin.entity_type, UserPin.entity_id)
                .filter(UserPin.user_id == current_user.id, UserPin.team_id == team_id)
                .all()
            )
            token_rows = (
                sync_db.query(AppTokenPin.entity_type, AppTokenPin.entity_id)
                .filter(AppTokenPin.owner_team_id == team_id)
                .all()
            )

            grouped = {et: set() for et in ENTITY_TYPES}
            token_pinned = {et: [] for et in ENTITY_TYPES}
            for entity_type, entity_id in user_rows:
                if entity_type in grouped:
                    grouped[entity_type].add(entity_id)
            for entity_type, entity_id in token_rows:
                if entity_type in grouped:
                    grouped[entity_type].add(entity_id)
                    token_pinned[entity_type].append(entity_id)

            result = {et: sorted(ids) for et, ids in grouped.items()}
            result["token_pinned"] = token_pinned
            return result

        return await main_boundary.run_sync_read(_load)
    except Exception as e:
        logger.error(f"取得釘選失敗: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="取得釘選失敗",
        )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_pin(
    payload: PinCreate,
    current_user: User = Depends(get_current_user),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> dict:
    """釘選一個物件（若已存在則視為成功，冪等）。"""
    _validate_entity_type(payload.entity_type)
    try:
        def _create(sync_db: Session):
            existing = (
                sync_db.query(UserPin)
                .filter(
                    UserPin.user_id == current_user.id,
                    UserPin.entity_type == payload.entity_type,
                    UserPin.entity_id == payload.entity_id,
                )
                .first()
            )
            if existing:
                return {"success": True, "already_pinned": True}
            sync_db.add(
                UserPin(
                    user_id=current_user.id,
                    team_id=payload.team_id,
                    entity_type=payload.entity_type,
                    entity_id=payload.entity_id,
                )
            )
            return {"success": True, "already_pinned": False}

        return await main_boundary.run_sync_write(_create)
    except Exception as e:
        logger.error(f"釘選失敗: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="釘選失敗",
        )


@router.delete("/{entity_type}/{entity_id}")
async def delete_pin(
    entity_type: str,
    entity_id: int,
    team_id: int = Query(None),
    current_user: User = Depends(get_current_user),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> dict:
    """取消釘選（依 user_id + entity_type + entity_id 唯一鍵刪除）。"""
    _validate_entity_type(entity_type)
    try:
        def _delete(sync_db: Session):
            deleted = (
                sync_db.query(UserPin)
                .filter(
                    UserPin.user_id == current_user.id,
                    UserPin.entity_type == entity_type,
                    UserPin.entity_id == entity_id,
                )
                .delete()
            )
            return {"success": True, "deleted": deleted}

        return await main_boundary.run_sync_write(_delete)
    except Exception as e:
        logger.error(f"取消釘選失敗: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="取消釘選失敗",
        )
