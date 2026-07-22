"""Super Admin CRUD for assistant system prompt + skills (spec assistant-prompt-skills-admin)."""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.audit import ActionType, AuditSeverity, ResourceType, audit_service
from app.auth.dependencies import require_super_admin
from app.db_access.main import MainAccessBoundary, get_main_access_boundary
from app.models.database_models import User
from app.services.assistant import content_store as store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/assistant", tags=["admin-assistant"])


class SystemPromptPut(BaseModel):
    content: str
    expected_version: int = Field(..., ge=1)


class SkillCreate(BaseModel):
    skill_id: str
    name: str
    description: str
    body: str
    triggers: list[str] = Field(default_factory=list)
    is_enabled: bool = True
    sort_order: int = 0


class SkillUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    body: Optional[str] = None
    triggers: Optional[list[str]] = None
    is_enabled: Optional[bool] = None
    sort_order: Optional[int] = None


class RestoreBody(BaseModel):
    mode: str = Field(..., pattern="^(missing-only|overwrite-builtins)$")
    confirm: bool = False


def _http_from_store(exc: store.ContentStoreError) -> HTTPException:
    code_map = {
        "prompt_stale": 409,
        "builtin_delete_forbidden": 409,
        "skill_exists": 409,
        "not_found": 404,
        "confirm_required": 400,
        "invalid_mode": 400,
        "skill_id_reserved": 422,
        "invalid_skill_id": 422,
        "invalid_content": 422,
        "invalid_catalog_token": 422,
        "invalid_name": 422,
        "invalid_description": 422,
        "invalid_body": 422,
        "invalid_triggers": 422,
        "skill_limit": 422,
        "not_factory": 422,
        "not_builtin": 422,
    }
    status = code_map.get(exc.code, 400)
    return HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message})


async def _audit(
    *,
    request: Request,
    user: User,
    action_type: ActionType,
    resource_id: str,
    brief: str,
    details: dict[str, Any],
    severity: AuditSeverity = AuditSeverity.INFO,
) -> None:
    try:
        await audit_service.log_action(
            user_id=user.id,
            username=user.username,
            role=str(user.role.value if hasattr(user.role, "value") else user.role),
            action_type=action_type,
            resource_type=ResourceType.SYSTEM,
            resource_id=resource_id,
            team_id=None,
            severity=severity,
            action_brief=brief,
            details=details,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("assistant admin audit failed: %s", exc)


@router.get("/system-prompt")
async def get_system_prompt(
    current_user: User = Depends(require_super_admin()),
    boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    row = await store.get_system_prompt_row(boundary)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "system prompt missing"})
    return row


@router.put("/system-prompt")
async def put_system_prompt(
    body: SystemPromptPut,
    request: Request,
    current_user: User = Depends(require_super_admin()),
    boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    try:
        result = await store.update_system_prompt(
            boundary,
            content=body.content,
            expected_version=body.expected_version,
            updated_by=current_user.username,
        )
    except store.ContentStoreError as exc:
        raise _http_from_store(exc) from exc
    await _audit(
        request=request,
        user=current_user,
        action_type=ActionType.UPDATE,
        resource_id="assistant-system-prompt",
        brief="Updated assistant system prompt",
        details={
            "version": result["version"],
            "content_sha256": result["content_sha256"],
            "content_length": result["content_length"],
            "preview": body.content[:200],
        },
        severity=AuditSeverity.WARNING,
    )
    return result


@router.get("/skills")
async def list_skills(
    current_user: User = Depends(require_super_admin()),
    boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    del current_user
    skills = await store.list_skills_admin(boundary)
    return {"skills": skills, "count": len(skills)}


@router.get("/skills/{skill_id}")
async def get_skill(
    skill_id: str,
    current_user: User = Depends(require_super_admin()),
    boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    del current_user
    row = await store.get_skill_admin(boundary, skill_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "skill not found"})
    return row


@router.post("/skills", status_code=201)
async def create_skill(
    payload: SkillCreate,
    request: Request,
    current_user: User = Depends(require_super_admin()),
    boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    try:
        result = await store.create_skill(
            boundary,
            skill_id=payload.skill_id,
            name=payload.name,
            description=payload.description,
            body=payload.body,
            triggers=payload.triggers,
            is_enabled=payload.is_enabled,
            sort_order=payload.sort_order,
            updated_by=current_user.username,
        )
    except store.ContentStoreError as exc:
        raise _http_from_store(exc) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("create_skill failed skill_id=%s", payload.skill_id)
        raise HTTPException(
            status_code=500,
            detail={"code": "internal_error", "message": f"create failed: {type(exc).__name__}"},
        ) from exc
    await _audit(
        request=request,
        user=current_user,
        action_type=ActionType.CREATE,
        resource_id=f"assistant-skill:{payload.skill_id}",
        brief=f"Created assistant skill {payload.skill_id}",
        details={
            "skill_id": payload.skill_id,
            "body_sha256": store.content_sha256(payload.body),
            "body_length": len(payload.body),
            "preview": payload.body[:200],
        },
    )
    return result


@router.put("/skills/{skill_id}")
async def update_skill(
    skill_id: str,
    payload: SkillUpdate,
    request: Request,
    current_user: User = Depends(require_super_admin()),
    boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    try:
        result = await store.update_skill(
            boundary,
            skill_id,
            name=payload.name,
            description=payload.description,
            body=payload.body,
            triggers=payload.triggers,
            is_enabled=payload.is_enabled,
            sort_order=payload.sort_order,
            updated_by=current_user.username,
        )
    except store.ContentStoreError as exc:
        raise _http_from_store(exc) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("update_skill failed skill_id=%s", skill_id)
        raise HTTPException(
            status_code=500,
            detail={"code": "internal_error", "message": f"update failed: {type(exc).__name__}"},
        ) from exc
    details: dict[str, Any] = {"skill_id": skill_id}
    if payload.body is not None:
        details["body_sha256"] = store.content_sha256(payload.body)
        details["body_length"] = len(payload.body)
        details["preview"] = payload.body[:200]
    if payload.is_enabled is not None:
        details["is_enabled"] = payload.is_enabled
    await _audit(
        request=request,
        user=current_user,
        action_type=ActionType.UPDATE,
        resource_id=f"assistant-skill:{skill_id}",
        brief=f"Updated assistant skill {skill_id}",
        details=details,
    )
    return result


@router.delete("/skills/{skill_id}")
async def delete_skill(
    skill_id: str,
    request: Request,
    current_user: User = Depends(require_super_admin()),
    boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    try:
        await store.delete_skill(boundary, skill_id)
    except store.ContentStoreError as exc:
        raise _http_from_store(exc) from exc
    await _audit(
        request=request,
        user=current_user,
        action_type=ActionType.DELETE,
        resource_id=f"assistant-skill:{skill_id}",
        brief=f"Deleted assistant skill {skill_id}",
        details={"skill_id": skill_id},
        severity=AuditSeverity.WARNING,
    )
    return {"ok": True, "skill_id": skill_id}


@router.post("/skills/{skill_id}/reset")
async def reset_skill(
    skill_id: str,
    request: Request,
    current_user: User = Depends(require_super_admin()),
    boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    try:
        result = await store.reset_skill_to_factory(
            boundary, skill_id, updated_by=current_user.username
        )
    except store.ContentStoreError as exc:
        raise _http_from_store(exc) from exc
    await _audit(
        request=request,
        user=current_user,
        action_type=ActionType.UPDATE,
        resource_id=f"assistant-skill:{skill_id}",
        brief=f"Reset assistant skill {skill_id} to factory",
        details={"skill_id": skill_id, "action": "reset_factory"},
        severity=AuditSeverity.WARNING,
    )
    return result


@router.post("/restore")
async def restore(
    body: RestoreBody,
    request: Request,
    current_user: User = Depends(require_super_admin()),
    boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    try:
        result = await store.restore(
            boundary,
            mode=body.mode,
            confirm=body.confirm,
            updated_by=current_user.username,
        )
    except store.ContentStoreError as exc:
        raise _http_from_store(exc) from exc
    await _audit(
        request=request,
        user=current_user,
        action_type=ActionType.UPDATE,
        resource_id="assistant-restore",
        brief=f"Assistant restore mode={body.mode}",
        details={"mode": body.mode, "result": result},
        severity=AuditSeverity.WARNING,
    )
    return result
