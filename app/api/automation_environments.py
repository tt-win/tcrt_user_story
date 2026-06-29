"""Automation environment config API (team-scoped).

Manages the per-team environment catalog, environment shared params and
per-script override values. Secret values are encrypted at rest and never
returned in plaintext. See manage-automation-environment-configs.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import ActionType, AuditSeverity, ResourceType, audit_service
from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.db_access.main import MainAccessBoundary, get_main_access_boundary
from app.models.automation_environment import (
    EnvParamInput,
    EnvParamResponse,
    EnvYamlImport,
    EnvironmentCreate,
    EnvironmentResponse,
    EnvironmentUpdate,
    ScriptEnvVarCell,
    ScriptEnvVarInput,
    ScriptEnvVarsResponse,
)
from app.models.database_models import Team, User
from app.services.automation.environment_service import EnvironmentService


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/teams/{team_id}/automation-environments", tags=["automation-environments"])
script_env_router = APIRouter(
    prefix="/teams/{team_id}/automation-scripts/{script_id}/env-vars",
    tags=["automation-environments"],
)


async def require_team_admin(
    team_id: int,
    current_user: User = Depends(get_current_user),
) -> User:
    """Environment values hold secrets, so management requires Admin / Super Admin."""
    role = current_user.role
    role_value = role.value if hasattr(role, "value") else str(role)
    if role_value.lower() not in {UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "INSUFFICIENT_PERMISSION", "message": "環境設定僅 Admin 以上可管理"},
        )
    return current_user


async def _ensure_team_exists(session: AsyncSession, team_id: int) -> None:
    result = await session.execute(select(Team.id).where(Team.id == team_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TEAM_NOT_FOUND", "message": f"Team {team_id} not found"},
        )


async def _log_env_action(
    *,
    action_type: ActionType,
    current_user: User,
    team_id: int,
    resource_id: str,
    action_brief: str,
    details: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    try:
        role_value = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
        await audit_service.log_action(
            user_id=current_user.id,
            username=current_user.username,
            role=role_value,
            action_type=action_type,
            resource_type=ResourceType.AUTOMATION_ENVIRONMENT,
            resource_id=resource_id,
            team_id=team_id,
            details=details,
            action_brief=action_brief,
            severity=AuditSeverity.CRITICAL if action_type == ActionType.DELETE else AuditSeverity.INFO,
            ip_address=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent") if request else None,
        )
    except Exception as exc:  # noqa: BLE001 — audit must never break the request
        logger.warning("Failed to write automation environment audit log: %s", exc, exc_info=True)


# ---------- environment catalog ----------

@router.get("", response_model=list[EnvironmentResponse])
async def list_environments(
    team_id: int,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> list[EnvironmentResponse]:
    async def _list(session: AsyncSession) -> list[EnvironmentResponse]:
        await _ensure_team_exists(session, team_id)
        return await EnvironmentService(session).list_environments(team_id)

    return await main_boundary.run_read(_list)


@router.post("", response_model=EnvironmentResponse, status_code=status.HTTP_201_CREATED)
async def create_environment(
    team_id: int,
    payload: EnvironmentCreate,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> EnvironmentResponse:
    async def _create(session: AsyncSession) -> EnvironmentResponse:
        await _ensure_team_exists(session, team_id)
        return await EnvironmentService(session).create_environment(
            team_id=team_id, name=payload.name, is_default=payload.is_default,
            params=payload.params, actor=str(current_user.id),
        )

    env = await main_boundary.run_write(_create)
    await _log_env_action(
        action_type=ActionType.CREATE, current_user=current_user, team_id=team_id,
        resource_id=str(env.id), action_brief=f"建立環境 {env.name}",
        details={"environment_name": env.name, "param_keys": [p.key for p in env.params]},
        request=request,
    )
    return env


@router.get("/declared-variables")
async def list_declared_variables(
    team_id: int,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> list[dict[str, Any]]:
    """Variable names declared (TCRT_VARS) across the team's scanned scripts,
    so the env-param editor can suggest them. Each: {name, secret, required, scripts}."""
    async def _list(session: AsyncSession) -> list[dict[str, Any]]:
        await _ensure_team_exists(session, team_id)
        return await EnvironmentService(session).list_declared_variables(team_id=team_id)

    return await main_boundary.run_read(_list)


@router.get("/{env_id}", response_model=EnvironmentResponse)
async def get_environment(
    team_id: int,
    env_id: int,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> EnvironmentResponse:
    async def _get(session: AsyncSession) -> EnvironmentResponse:
        await _ensure_team_exists(session, team_id)
        return await EnvironmentService(session).get_environment(team_id, env_id)

    return await main_boundary.run_read(_get)


@router.put("/{env_id}", response_model=EnvironmentResponse)
async def update_environment(
    team_id: int,
    env_id: int,
    payload: EnvironmentUpdate,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> EnvironmentResponse:
    async def _update(session: AsyncSession) -> EnvironmentResponse:
        await _ensure_team_exists(session, team_id)
        return await EnvironmentService(session).update_environment(
            team_id=team_id, env_id=env_id, name=payload.name,
            is_default=payload.is_default, actor=str(current_user.id),
        )

    env = await main_boundary.run_write(_update)
    await _log_env_action(
        action_type=ActionType.UPDATE, current_user=current_user, team_id=team_id,
        resource_id=str(env.id), action_brief=f"更新環境 {env.name}",
        details={"environment_name": env.name}, request=request,
    )
    return env


@router.delete("/{env_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_environment(
    team_id: int,
    env_id: int,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> Response:
    async def _delete(session: AsyncSession) -> str:
        await _ensure_team_exists(session, team_id)
        return await EnvironmentService(session).delete_environment(team_id=team_id, env_id=env_id)

    name = await main_boundary.run_write(_delete)
    await _log_env_action(
        action_type=ActionType.DELETE, current_user=current_user, team_id=team_id,
        resource_id=str(env_id), action_brief=f"刪除環境 {name}",
        details={"environment_name": name}, request=request,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{env_id}/default", response_model=EnvironmentResponse)
async def set_default_environment(
    team_id: int,
    env_id: int,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> EnvironmentResponse:
    async def _default(session: AsyncSession) -> EnvironmentResponse:
        await _ensure_team_exists(session, team_id)
        return await EnvironmentService(session).set_default(team_id=team_id, env_id=env_id, actor=str(current_user.id))

    env = await main_boundary.run_write(_default)
    await _log_env_action(
        action_type=ActionType.UPDATE, current_user=current_user, team_id=team_id,
        resource_id=str(env.id), action_brief=f"設定預設環境 {env.name}",
        details={"environment_name": env.name, "is_default": True}, request=request,
    )
    return env


# ---------- environment shared params ----------

@router.put("/{env_id}/params/{key}", response_model=EnvParamResponse)
async def set_param(
    team_id: int,
    env_id: int,
    key: str,
    payload: EnvParamInput,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> EnvParamResponse:
    async def _set(session: AsyncSession) -> EnvParamResponse:
        await _ensure_team_exists(session, team_id)
        return await EnvironmentService(session).set_param(
            team_id=team_id, env_id=env_id, key=key, value=payload.value,
            is_secret=payload.is_secret, actor=str(current_user.id),
        )

    result = await main_boundary.run_write(_set)
    await _log_env_action(
        action_type=ActionType.UPDATE, current_user=current_user, team_id=team_id,
        resource_id=str(env_id), action_brief=f"設定環境共用參數 {key}",
        details={"key": key, "is_secret": payload.is_secret, "scope": "shared"}, request=request,
    )
    return result


@router.delete("/{env_id}/params/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_param(
    team_id: int,
    env_id: int,
    key: str,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> Response:
    async def _del(session: AsyncSession) -> None:
        await _ensure_team_exists(session, team_id)
        await EnvironmentService(session).delete_param(team_id=team_id, env_id=env_id, key=key)

    await main_boundary.run_write(_del)
    await _log_env_action(
        action_type=ActionType.DELETE, current_user=current_user, team_id=team_id,
        resource_id=str(env_id), action_brief=f"刪除環境共用參數 {key}",
        details={"key": key, "scope": "shared"}, request=request,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- YAML import / export ----------

@router.post("/{env_id}/import")
async def import_params(
    team_id: int,
    env_id: int,
    payload: EnvYamlImport,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> dict[str, Any]:
    async def _import(session: AsyncSession) -> int:
        await _ensure_team_exists(session, team_id)
        return await EnvironmentService(session).import_params(
            team_id=team_id, env_id=env_id, yaml_text=payload.yaml, actor=str(current_user.id),
        )

    count = await main_boundary.run_write(_import)
    await _log_env_action(
        action_type=ActionType.UPDATE, current_user=current_user, team_id=team_id,
        resource_id=str(env_id), action_brief=f"匯入環境共用參數 ({count})",
        details={"imported": count, "scope": "shared"}, request=request,
    )
    return {"imported": count}


@router.get("/{env_id}/export")
async def export_params(
    team_id: int,
    env_id: int,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> dict[str, str]:
    async def _export(session: AsyncSession) -> str:
        await _ensure_team_exists(session, team_id)
        return await EnvironmentService(session).export_params(team_id=team_id, env_id=env_id)

    yaml_text = await main_boundary.run_read(_export)
    return {"yaml": yaml_text}


# ---------- per-script overrides ----------

@script_env_router.get("", response_model=ScriptEnvVarsResponse)
async def get_script_env_vars(
    team_id: int,
    script_id: int,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> ScriptEnvVarsResponse:
    async def _get(session: AsyncSession) -> ScriptEnvVarsResponse:
        await _ensure_team_exists(session, team_id)
        return await EnvironmentService(session).get_script_env_vars(team_id=team_id, script_id=script_id)

    return await main_boundary.run_read(_get)


@script_env_router.put("/{env_id}/{key}", response_model=ScriptEnvVarCell)
async def set_script_override(
    team_id: int,
    script_id: int,
    env_id: int,
    key: str,
    payload: ScriptEnvVarInput,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> ScriptEnvVarCell:
    async def _set(session: AsyncSession) -> ScriptEnvVarCell:
        await _ensure_team_exists(session, team_id)
        return await EnvironmentService(session).set_script_override(
            team_id=team_id, script_id=script_id, env_id=env_id, key=key,
            value=payload.value, is_secret=payload.is_secret, actor=str(current_user.id),
        )

    cell = await main_boundary.run_write(_set)
    await _log_env_action(
        action_type=ActionType.UPDATE, current_user=current_user, team_id=team_id,
        resource_id=str(env_id), action_brief=f"設定 script {script_id} 變數覆寫 {key}",
        details={"script_id": script_id, "key": key, "is_secret": payload.is_secret, "scope": "override"},
        request=request,
    )
    return cell


@script_env_router.delete("/{env_id}/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_script_override(
    team_id: int,
    script_id: int,
    env_id: int,
    key: str,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> Response:
    async def _del(session: AsyncSession) -> None:
        await _ensure_team_exists(session, team_id)
        await EnvironmentService(session).delete_script_override(
            team_id=team_id, script_id=script_id, env_id=env_id, key=key,
        )

    await main_boundary.run_write(_del)
    await _log_env_action(
        action_type=ActionType.DELETE, current_user=current_user, team_id=team_id,
        resource_id=str(env_id), action_brief=f"刪除 script {script_id} 變數覆寫 {key}",
        details={"script_id": script_id, "key": key, "scope": "override"}, request=request,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
