"""Team app token management API (JWT-authenticated admin endpoints)."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import ActionType, AuditSeverity, ResourceType, audit_service
from app.auth.app_token_dependencies import (
    generate_app_token,
)
from app.auth.dependencies import get_current_user, require_super_admin
from app.auth.models import PermissionType, UserRole
from app.auth.permission_service import permission_service
from app.database import get_db
from app.db_access.main import create_main_access_boundary_for_session
from app.models.app_token import ALL_APP_TOKEN_SCOPES, APP_TOKEN_DEFAULT_EXPIRY_DAYS
from app.models.database_models import (
    Team,
    TeamAppToken,
    TeamAppTokenStatus,
    User,
)
from app.models.team import TeamStatus
from app.services.observability import Impact, Outcome

logger = logging.getLogger(__name__)

router = APIRouter(tags=["app-tokens"])


class AppTokenCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    scopes: List[str] = Field(..., min_length=1)
    expires_in_days: Optional[int] = Field(
        None,
        ge=0,
        le=3650,
        description="Days until expiry; omit for 90-day default, 0 for non-expiring",
    )


class SuperAdminAppTokenCreateRequest(AppTokenCreateRequest):
    owner_team_id: int = Field(..., gt=0)


class AppTokenResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    owner_team_id: int
    owner_team_name: Optional[str] = None
    token_prefix: str
    status: str
    scopes: List[str] = Field(default_factory=list)
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    created_by_user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    revoked_at: Optional[datetime] = None


class AppTokenCreateResponse(AppTokenResponse):
    raw_token: str = Field(..., description="One-time display of the raw token")


class AppTokenRotateResponse(BaseModel):
    id: int
    name: str
    token_prefix: str
    status: str
    raw_token: str = Field(..., description="One-time display of the new raw token")
    updated_at: datetime


class AppTokenListResponse(BaseModel):
    items: List[AppTokenResponse] = Field(default_factory=list)
    total: int


def _validate_scopes(scopes: List[str]) -> List[str]:
    invalid = [s for s in scopes if s not in ALL_APP_TOKEN_SCOPES]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "APP_TOKEN_VALIDATION_ERROR",
                "message": f"Invalid scopes: {invalid}",
            },
        )
    return scopes


def _compute_expires_at(expires_in_days: Optional[int]) -> Optional[datetime]:
    if expires_in_days is None:
        return datetime.utcnow() + timedelta(days=APP_TOKEN_DEFAULT_EXPIRY_DAYS)
    if expires_in_days == 0:
        return None
    return datetime.utcnow() + timedelta(days=expires_in_days)


def _to_response(
    token: TeamAppToken,
    owner_team_name: Optional[str] = None,
) -> AppTokenResponse:
    scopes = []
    if token.scopes_json:
        try:
            parsed = json.loads(token.scopes_json)
            if isinstance(parsed, list):
                scopes = [str(s) for s in parsed]
        except (TypeError, ValueError):
            pass
    status_value = token.status.value if hasattr(token.status, "value") else str(token.status)
    return AppTokenResponse(
        id=token.id,
        name=token.name,
        description=token.description,
        owner_team_id=token.owner_team_id,
        owner_team_name=owner_team_name,
        token_prefix=token.token_prefix,
        status=status_value,
        scopes=scopes,
        expires_at=token.expires_at,
        last_used_at=token.last_used_at,
        created_by_user_id=token.created_by_user_id,
        created_at=token.created_at,
        updated_at=token.updated_at,
        revoked_at=token.revoked_at,
    )


async def _require_team_admin(
    team_id: int,
    current_user: User,
    db: AsyncSession,
) -> User:
    permission_check = await permission_service.check_team_permission(
        current_user.id,
        team_id,
        PermissionType.ADMIN,
        current_user.role,
    )
    if not permission_check.has_permission:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "INSUFFICIENT_PERMISSION", "message": "Team admin permission required"},
        )
    return current_user

async def _audit_token_action(
    request: Request,
    user: User,
    action_type: ActionType,
    token: TeamAppToken,
    action_brief: str,
    severity: AuditSeverity = AuditSeverity.INFO,
    event_code: str = "tcrt.audit.legacy.generic",
    outcome: Outcome = Outcome.SUCCESS,
    impact: Impact = Impact.ROUTINE,
    global_scope: bool = False,
) -> None:
    try:
        await audit_service.log_action(
            user_id=user.id,
            username=user.username,
            role=user.role.value if hasattr(user.role, "value") else str(user.role),
            action_type=action_type,
            resource_type=ResourceType.AUTH,
            resource_id=f"team_app_token:{token.id}",
            team_id=token.owner_team_id,
            details={
                "app_token_id": token.id,
                "app_token_name": token.name,
                "owner_team_id": token.owner_team_id,
                "action": action_brief,
                "token_prefix": token.token_prefix,
                "management_scope": "global" if global_scope else "team",
            },
            action_brief=action_brief,
            severity=severity,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            event_code=event_code,
            impact=impact,
            outcome=outcome,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("App token management audit failed: %s", exc, exc_info=True)


async def _create_app_token(
    team_id: int,
    body: AppTokenCreateRequest,
    request: Request,
    current_user: User,
    db: AsyncSession,
    *,
    global_scope: bool = False,
) -> AppTokenCreateResponse:
    _validate_scopes(body.scopes)

    raw_token, token_hash, token_prefix = generate_app_token()
    expires_at = _compute_expires_at(body.expires_in_days)

    token = TeamAppToken(
        name=body.name,
        description=body.description,
        owner_team_id=team_id,
        token_hash=token_hash,
        token_prefix=token_prefix,
        status=TeamAppTokenStatus.ACTIVE,
        scopes_json=json.dumps(body.scopes),
        expires_at=expires_at,
        created_by_user_id=current_user.id,
    )

    boundary = create_main_access_boundary_for_session(db)

    async def _save(session: AsyncSession):
        session.add(token)
        await session.flush()
        return token

    saved = await boundary.run_write(_save)
    brief = (
        f"Super Admin created app token '{body.name}' for team {team_id}"
        if global_scope
        else f"Created app token '{body.name}'"
    )
    await _audit_token_action(
        request,
        current_user,
        ActionType.CREATE,
        saved,
        brief,
        event_code="tcrt.audit.auth.token_create",
        outcome=Outcome.SUCCESS,
        impact=Impact.SENSITIVE,
        global_scope=global_scope,
    )

    return AppTokenCreateResponse(
        id=saved.id,
        name=saved.name,
        description=saved.description,
        owner_team_id=saved.owner_team_id,
        token_prefix=saved.token_prefix,
        status=saved.status.value,
        scopes=body.scopes,
        expires_at=saved.expires_at,
        last_used_at=saved.last_used_at,
        created_by_user_id=saved.created_by_user_id,
        created_at=saved.created_at,
        updated_at=saved.updated_at,
        revoked_at=saved.revoked_at,
        raw_token=raw_token,
    )


@router.post(
    "/teams/{team_id}/app-tokens",
    response_model=AppTokenCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_team_app_token(
    team_id: int,
    body: AppTokenCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new team app token. Returns the raw token once."""
    await _require_team_admin(team_id, current_user, db)
    return await _create_app_token(team_id, body, request, current_user, db)


@router.post(
    "/app-tokens",
    response_model=AppTokenCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_any_app_token(
    body: SuperAdminAppTokenCreateRequest,
    request: Request,
    current_user: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Super Admin: create an app token for an explicit active team."""
    boundary = create_main_access_boundary_for_session(db)

    async def _load_active_team(session: AsyncSession):
        result = await session.execute(
            select(Team.id).where(
                Team.id == body.owner_team_id,
                Team.status == TeamStatus.ACTIVE,
            )
        )
        return result.scalar_one_or_none()

    active_team_id = await boundary.run_read(_load_active_team)
    if active_team_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "APP_TOKEN_RESOURCE_NOT_FOUND",
                "message": "Active owner team not found",
            },
        )
    return await _create_app_token(
        body.owner_team_id,
        body,
        request,
        current_user,
        db,
        global_scope=True,
    )


@router.get("/teams/{team_id}/app-tokens", response_model=AppTokenListResponse)
async def list_team_app_tokens(
    team_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List team app tokens (metadata only)."""
    await _require_team_admin(team_id, current_user, db)

    boundary = create_main_access_boundary_for_session(db)

    async def _list(session: AsyncSession):
        result = await session.execute(
            select(TeamAppToken, Team.name)
            .outerjoin(Team, Team.id == TeamAppToken.owner_team_id)
            .where(TeamAppToken.owner_team_id == team_id)
            .order_by(TeamAppToken.created_at.desc())
        )
        return result.all()

    rows = await boundary.run_read(_list)
    return AppTokenListResponse(
        items=[_to_response(token, team_name) for token, team_name in rows],
        total=len(rows),
    )


async def _rotate_app_token(
    token_id: int,
    request: Request,
    current_user: User,
    db: AsyncSession,
    *,
    owner_team_id: Optional[int] = None,
    global_scope: bool = False,
) -> AppTokenRotateResponse:
    raw_token, token_hash, token_prefix = generate_app_token()

    boundary = create_main_access_boundary_for_session(db)

    async def _rotate(session: AsyncSession):
        conditions = [TeamAppToken.id == token_id]
        if owner_team_id is not None:
            conditions.append(TeamAppToken.owner_team_id == owner_team_id)
        result = await session.execute(select(TeamAppToken).where(*conditions))
        token = result.scalar_one_or_none()
        if not token:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "APP_TOKEN_RESOURCE_NOT_FOUND", "message": "App token not found"},
            )
        if token.status != TeamAppTokenStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "APP_TOKEN_VALIDATION_ERROR",
                    "message": "Cannot rotate a non-active token",
                },
            )
        token.token_hash = token_hash
        token.token_prefix = token_prefix
        token.updated_at = datetime.utcnow()
        await session.flush()
        return token

    token = await boundary.run_write(_rotate)
    action_brief = (
        f"Super Admin rotated app token '{token.name}' globally"
        if global_scope
        else f"Rotated app token '{token.name}'"
    )
    await _audit_token_action(
        request,
        current_user,
        ActionType.UPDATE,
        token,
        action_brief,
        severity=AuditSeverity.WARNING,
        event_code="tcrt.audit.auth.token_rotate",
        outcome=Outcome.SUCCESS,
        impact=Impact.PRIVILEGED,
        global_scope=global_scope,
    )
    return AppTokenRotateResponse(
        id=token.id,
        name=token.name,
        token_prefix=token.token_prefix,
        status=token.status.value,
        raw_token=raw_token,
        updated_at=token.updated_at,
    )


@router.delete("/teams/{team_id}/app-tokens/{token_id}", response_model=AppTokenResponse)
async def revoke_team_app_token(
    team_id: int,
    token_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a team app token. Idempotent for already-revoked tokens."""
    await _require_team_admin(team_id, current_user, db)

    boundary = create_main_access_boundary_for_session(db)

    async def _revoke(session: AsyncSession):
        result = await session.execute(
            select(TeamAppToken).where(
                TeamAppToken.id == token_id,
                TeamAppToken.owner_team_id == team_id,
            )
        )
        token = result.scalar_one_or_none()
        if not token:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "APP_TOKEN_RESOURCE_NOT_FOUND", "message": "App token not found"},
            )
        if token.status == TeamAppTokenStatus.ACTIVE:
            token.status = TeamAppTokenStatus.REVOKED
            token.revoked_at = datetime.utcnow()
            await session.flush()
        return token

    token = await boundary.run_write(_revoke)
    await _audit_token_action(
        request,
        current_user,
        ActionType.DELETE,
        token,
        f"Revoked app token '{token.name}'",
        event_code="tcrt.audit.auth.token_revoke",
        outcome=Outcome.SUCCESS,
        impact=Impact.PRIVILEGED,
    )
    return _to_response(token)


@router.post(
    "/teams/{team_id}/app-tokens/{token_id}/rotate",
    response_model=AppTokenRotateResponse,
)
async def rotate_team_app_token(
    team_id: int,
    token_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rotate a team app token. Old raw token is immediately invalidated."""
    await _require_team_admin(team_id, current_user, db)
    return await _rotate_app_token(
        token_id,
        request,
        current_user,
        db,
        owner_team_id=team_id,
    )


@router.post(
    "/app-tokens/{token_id}/rotate",
    response_model=AppTokenRotateResponse,
)
async def rotate_any_app_token(
    token_id: int,
    request: Request,
    current_user: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Super Admin: rotate any active team app token."""
    return await _rotate_app_token(
        token_id,
        request,
        current_user,
        db,
        global_scope=True,
    )


@router.get("/app-tokens", response_model=AppTokenListResponse)
async def list_all_app_tokens(
    current_user: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Super Admin: list all team app tokens (metadata only)."""
    boundary = create_main_access_boundary_for_session(db)

    async def _list(session: AsyncSession):
        result = await session.execute(
            select(TeamAppToken, Team.name)
            .outerjoin(Team, Team.id == TeamAppToken.owner_team_id)
            .order_by(TeamAppToken.created_at.desc())
        )
        return result.all()

    rows = await boundary.run_read(_list)
    return AppTokenListResponse(
        items=[_to_response(token, team_name) for token, team_name in rows],
        total=len(rows),
    )


@router.delete("/app-tokens/{token_id}", response_model=AppTokenResponse)
async def revoke_any_app_token(
    token_id: int,
    request: Request,
    current_user: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Super Admin: revoke any team app token."""
    boundary = create_main_access_boundary_for_session(db)

    async def _revoke(session: AsyncSession):
        result = await session.execute(
            select(TeamAppToken).where(TeamAppToken.id == token_id)
        )
        token = result.scalar_one_or_none()
        if not token:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "APP_TOKEN_RESOURCE_NOT_FOUND", "message": "App token not found"},
            )
        if token.status == TeamAppTokenStatus.ACTIVE:
            token.status = TeamAppTokenStatus.REVOKED
            token.revoked_at = datetime.utcnow()
            await session.flush()
        return token

    token = await boundary.run_write(_revoke)
    await _audit_token_action(
        request,
        current_user,
        ActionType.DELETE,
        token,
        f"Super Admin revoked app token '{token.name}'",
        event_code="tcrt.audit.auth.token_revoke",
        outcome=Outcome.SUCCESS,
        impact=Impact.PRIVILEGED,
        global_scope=True,
    )
    return _to_response(token)
