"""App token pins API - /api/app/teams/{team_id}/pins.

Team-scoped, shared pin list writable by any app token (or legacy machine
credential) with access to the team. Fully independent of the per-user
`/api/pins` (JWT) feature and its `user_pins` table — see
app/api/pins.py for that human-facing counterpart.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.mcp import _ensure_team_exists
from app.audit import ActionType
from app.auth.app_token_dependencies import (
    AppTokenErrorCodes,
    get_current_app_token_principal,
    log_app_token_audit,
    require_app_team_access,
)
from app.database import get_db
from app.db_access.main import create_main_access_boundary_for_session
from app.models.app_token import (
    READ_SCOPES,
    SCOPE_TEST_CASE_WRITE,
    SCOPE_TEST_RUN_WRITE,
    AppTokenPrincipal,
)
from app.models.database_models import AppTokenPin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/app", tags=["app-pins"])

# 允許釘選的物件類型（與 app/api/pins.py 的 ENTITY_TYPES 及前端 PinStore 的 key 一致）
ENTITY_TYPES = {"test_case_set", "test_run_set", "test_run", "adhoc_run"}
_TEST_CASE_ENTITY_TYPES = {"test_case_set"}


class AppPinCreate(BaseModel):
    entity_type: str
    entity_id: int


def _validate_entity_type(entity_type: str) -> None:
    if entity_type not in ENTITY_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": AppTokenErrorCodes.VALIDATION_ERROR,
                "message": f"Invalid entity_type: {entity_type}",
            },
        )


def _required_scope_for(entity_type: str) -> str:
    return SCOPE_TEST_CASE_WRITE if entity_type in _TEST_CASE_ENTITY_TYPES else SCOPE_TEST_RUN_WRITE


async def _require_pin_read_scope(
    request: Request,
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
) -> AppTokenPrincipal:
    if not principal.has_any_scope(*READ_SCOPES):
        await log_app_token_audit(
            request, principal, allowed=False, reason="missing_read_scope"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": AppTokenErrorCodes.SCOPE_DENIED,
                "message": "App token missing required read scope",
            },
        )
    return principal


async def _require_pin_write_scope(
    entity_type: str,
    team_id: int,
    request: Request,
    principal: AppTokenPrincipal,
) -> None:
    required_scope = _required_scope_for(entity_type)
    if not principal.has_scope(required_scope):
        await log_app_token_audit(
            request,
            principal,
            allowed=False,
            reason=f"scope_denied:{required_scope}",
            team_id=team_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": AppTokenErrorCodes.SCOPE_DENIED,
                "message": f"App token missing required scope: {required_scope}",
            },
        )


@router.get("/teams/{team_id}/pins")
async def list_app_team_pins(
    team_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(_require_pin_read_scope),
) -> dict:
    """List a team's shared pins, grouped by entity_type."""
    await _ensure_team_exists(db, team_id)
    await require_app_team_access(team_id, request, principal)

    main_boundary = create_main_access_boundary_for_session(db)

    def _load(sync_db: Session):
        rows = (
            sync_db.query(AppTokenPin.entity_type, AppTokenPin.entity_id)
            .filter(AppTokenPin.owner_team_id == team_id)
            .all()
        )
        grouped: dict = {et: [] for et in ENTITY_TYPES}
        for entity_type, entity_id in rows:
            grouped.setdefault(entity_type, []).append(entity_id)
        return grouped

    result = await main_boundary.run_sync_read(_load)
    await log_app_token_audit(
        request,
        principal,
        allowed=True,
        reason="pin_listed",
        action_type=ActionType.READ,
        team_id=team_id,
        extra_details={"pin_count": sum(len(ids) for ids in result.values())},
    )
    return result


@router.post("/teams/{team_id}/pins", status_code=status.HTTP_201_CREATED)
async def create_app_team_pin(
    team_id: int,
    body: AppPinCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
) -> dict:
    """Pin an entity for a team (idempotent; requires test_case:write or test_run:write)."""
    _validate_entity_type(body.entity_type)
    await require_app_team_access(team_id, request, principal)
    await _require_pin_write_scope(body.entity_type, team_id, request, principal)

    main_boundary = create_main_access_boundary_for_session(db)
    credential_id = principal.credential_id

    def _create(sync_db: Session):
        existing = (
            sync_db.query(AppTokenPin)
            .filter(
                AppTokenPin.owner_team_id == team_id,
                AppTokenPin.entity_type == body.entity_type,
                AppTokenPin.entity_id == body.entity_id,
            )
            .first()
        )
        if existing:
            return {"success": True, "already_pinned": True}
        sync_db.add(
            AppTokenPin(
                owner_team_id=team_id,
                entity_type=body.entity_type,
                entity_id=body.entity_id,
                created_by_credential_id=credential_id,
            )
        )
        return {"success": True, "already_pinned": False}

    try:
        result = await main_boundary.run_sync_write(_create)
    except IntegrityError:
        def _already_pinned(sync_db: Session) -> bool:
            return (
                sync_db.query(AppTokenPin.id)
                .filter(
                    AppTokenPin.owner_team_id == team_id,
                    AppTokenPin.entity_type == body.entity_type,
                    AppTokenPin.entity_id == body.entity_id,
                )
                .first()
                is not None
            )

        if not await main_boundary.run_sync_read(_already_pinned):
            raise
        result = {"success": True, "already_pinned": True}
    await log_app_token_audit(
        request,
        principal,
        allowed=True,
        reason="pin_created",
        action_type=ActionType.CREATE,
        team_id=team_id,
        extra_details={
            "entity_type": body.entity_type,
            "entity_id": body.entity_id,
            "already_pinned": result["already_pinned"],
        },
    )
    return result


@router.delete("/teams/{team_id}/pins/{entity_type}/{entity_id}")
async def delete_app_team_pin(
    team_id: int,
    entity_type: str,
    entity_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
) -> dict:
    """Unpin an entity for a team (idempotent; requires test_case:write or test_run:write)."""
    _validate_entity_type(entity_type)
    await require_app_team_access(team_id, request, principal)
    await _require_pin_write_scope(entity_type, team_id, request, principal)

    main_boundary = create_main_access_boundary_for_session(db)

    def _delete(sync_db: Session):
        deleted = (
            sync_db.query(AppTokenPin)
            .filter(
                AppTokenPin.owner_team_id == team_id,
                AppTokenPin.entity_type == entity_type,
                AppTokenPin.entity_id == entity_id,
            )
            .delete()
        )
        return {"success": True, "deleted": deleted}

    result = await main_boundary.run_sync_write(_delete)
    await log_app_token_audit(
        request,
        principal,
        allowed=True,
        reason="pin_deleted",
        action_type=ActionType.DELETE,
        team_id=team_id,
        extra_details={
            "entity_type": entity_type,
            "entity_id": entity_id,
            "deleted": result["deleted"],
        },
    )
    return result
