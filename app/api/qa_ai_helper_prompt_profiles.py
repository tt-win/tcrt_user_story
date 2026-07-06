"""Team Prompt Profile CRUD API for QA AI Helper."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.db_access.main import MainAccessBoundary, get_main_access_boundary
from app.models.database_models import (
    QAAIHelperPromptProfile,
    QAAIHelperSeedSet,
    QAAIHelperSession,
    QAAIHelperTestcaseDraftSet,
    Team,
    User,
)
from app.models.qa_ai_helper import (
    QAAIHelperPromptProfileCreateRequest,
    QAAIHelperPromptProfileListResponse,
    QAAIHelperPromptProfileResponse,
    QAAIHelperPromptProfileSetDefaultRequest,
    QAAIHelperPromptProfileUpdateRequest,
)
from app.api.qa_ai_helper import _verify_team_write_access

router = APIRouter(
    prefix="/teams/{team_id}/qa-ai-helper/prompt-profiles",
    tags=["qa-ai-helper"],
)


async def require_team_admin(
    team_id: int,
    current_user: User = Depends(get_current_user),
) -> User:
    """Prompt profiles affect all team members' output, so management requires Admin / Super Admin."""
    role = current_user.role
    role_value = role.value if hasattr(role, "value") else str(role)
    if role_value.lower() not in {UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "INSUFFICIENT_PERMISSION", "message": "風格設定僅 Admin 以上可管理"},
        )
    return current_user


async def _ensure_team_exists(session: AsyncSession, team_id: int) -> None:
    result = await session.execute(select(Team.id).where(Team.id == team_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TEAM_NOT_FOUND", "message": f"Team {team_id} not found"},
        )


async def _get_profile_or_404(
    session: AsyncSession, team_id: int, profile_id: int
) -> QAAIHelperPromptProfile:
    result = await session.execute(
        select(QAAIHelperPromptProfile).where(
            QAAIHelperPromptProfile.id == profile_id,
            QAAIHelperPromptProfile.team_id == team_id,
        )
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PROMPT_PROFILE_NOT_FOUND", "message": "找不到 prompt profile"},
        )
    return profile


async def _ensure_name_available(
    session: AsyncSession,
    team_id: int,
    name: str,
    *,
    exclude_profile_id: int | None = None,
) -> None:
    query = select(QAAIHelperPromptProfile.id).where(
        QAAIHelperPromptProfile.team_id == team_id,
        QAAIHelperPromptProfile.name == name,
    )
    if exclude_profile_id is not None:
        query = query.where(QAAIHelperPromptProfile.id != exclude_profile_id)
    result = await session.execute(query)
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "PROMPT_PROFILE_NAME_DUPLICATE", "message": f"名稱 '{name}' 已被使用"},
        )


async def _clear_team_default(session: AsyncSession, team_id: int) -> None:
    await session.execute(
        update(QAAIHelperPromptProfile)
        .where(QAAIHelperPromptProfile.team_id == team_id, QAAIHelperPromptProfile.is_default.is_(True))
        .values(is_default=False)
    )


@router.get("", response_model=QAAIHelperPromptProfileListResponse)
async def list_prompt_profiles(
    team_id: int,
    current_user: User = Depends(get_current_user),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> QAAIHelperPromptProfileListResponse:
    await _verify_team_write_access(team_id=team_id, current_user=current_user)

    async def _list(session: AsyncSession) -> QAAIHelperPromptProfileListResponse:
        await _ensure_team_exists(session, team_id)
        result = await session.execute(
            select(QAAIHelperPromptProfile)
            .where(QAAIHelperPromptProfile.team_id == team_id)
            .order_by(QAAIHelperPromptProfile.name)
        )
        profiles = result.scalars().all()
        return QAAIHelperPromptProfileListResponse(
            profiles=[QAAIHelperPromptProfileResponse.model_validate(p) for p in profiles]
        )

    return await main_boundary.run_read(_list)


@router.post("", response_model=QAAIHelperPromptProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_prompt_profile(
    team_id: int,
    payload: QAAIHelperPromptProfileCreateRequest,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> QAAIHelperPromptProfileResponse:
    async def _create(session: AsyncSession) -> QAAIHelperPromptProfileResponse:
        await _ensure_team_exists(session, team_id)
        await _ensure_name_available(session, team_id, payload.name)

        if payload.is_default:
            await _clear_team_default(session, team_id)

        now = datetime.utcnow()
        profile = QAAIHelperPromptProfile(
            team_id=team_id,
            name=payload.name,
            description=payload.description,
            seed_instructions=payload.seed_instructions,
            testcase_instructions=payload.testcase_instructions,
            is_default=payload.is_default,
            created_by_user_id=current_user.id,
            updated_by_user_id=current_user.id,
            created_at=now,
            updated_at=now,
        )
        session.add(profile)
        await session.flush()
        await session.refresh(profile)
        return QAAIHelperPromptProfileResponse.model_validate(profile)

    return await main_boundary.run_write(_create)


@router.put("/{profile_id}", response_model=QAAIHelperPromptProfileResponse)
async def update_prompt_profile(
    team_id: int,
    profile_id: int,
    payload: QAAIHelperPromptProfileUpdateRequest,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> QAAIHelperPromptProfileResponse:
    async def _update(session: AsyncSession) -> QAAIHelperPromptProfileResponse:
        await _ensure_team_exists(session, team_id)
        profile = await _get_profile_or_404(session, team_id, profile_id)
        await _ensure_name_available(session, team_id, payload.name, exclude_profile_id=profile_id)

        profile.name = payload.name
        profile.description = payload.description
        profile.seed_instructions = payload.seed_instructions
        profile.testcase_instructions = payload.testcase_instructions
        profile.updated_by_user_id = current_user.id
        profile.updated_at = datetime.utcnow()
        await session.flush()
        await session.refresh(profile)
        return QAAIHelperPromptProfileResponse.model_validate(profile)

    return await main_boundary.run_write(_update)


@router.delete("/{profile_id}")
async def delete_prompt_profile(
    team_id: int,
    profile_id: int,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> dict[str, bool]:
    async def _delete(session: AsyncSession) -> dict[str, bool]:
        await _ensure_team_exists(session, team_id)
        profile = await _get_profile_or_404(session, team_id, profile_id)

        for model in (QAAIHelperSession, QAAIHelperSeedSet, QAAIHelperTestcaseDraftSet):
            await session.execute(
                update(model)
                .where(model.prompt_profile_id == profile_id)
                .values(prompt_profile_id=None)
            )

        await session.delete(profile)
        await session.flush()
        return {"success": True}

    return await main_boundary.run_write(_delete)


@router.post("/{profile_id}/set-default", response_model=QAAIHelperPromptProfileResponse)
async def set_default_prompt_profile(
    team_id: int,
    profile_id: int,
    payload: QAAIHelperPromptProfileSetDefaultRequest,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> QAAIHelperPromptProfileResponse:
    async def _set_default(session: AsyncSession) -> QAAIHelperPromptProfileResponse:
        await _ensure_team_exists(session, team_id)
        profile = await _get_profile_or_404(session, team_id, profile_id)

        if payload.is_default:
            await _clear_team_default(session, team_id)
            profile.is_default = True
        else:
            profile.is_default = False

        profile.updated_by_user_id = current_user.id
        profile.updated_at = datetime.utcnow()
        await session.flush()
        await session.refresh(profile)
        return QAAIHelperPromptProfileResponse.model_validate(profile)

    return await main_boundary.run_write(_set_default)
