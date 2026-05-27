from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.automation_scripts import require_team_admin, require_team_read
from app.audit import ActionType, AuditSeverity, ResourceType, audit_service
from app.db_access.main import MainAccessBoundary, get_main_access_boundary
from app.models.automation_link import (
    AutomationScriptLinkCreate,
    AutomationScriptLinkResponse,
    AutomationScriptLinkUpdate,
    LinkedAutomationSummary,
)
from app.models.database_models import TestCaseLocal, User
from app.services.automation.linkage_service import (
    AutomationLinkageService,
    AutomationLinkAlreadyExistsError,
    AutomationLinkNotFoundError,
    PrimaryAutomationLinkConflictError,
    link_to_dict,
)
from app.services.automation.webhook_service import dispatch_event_async


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/teams/{team_id}", tags=["automation-links"])


@router.post(
    "/automation-scripts/{script_id}/links",
    response_model=AutomationScriptLinkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_automation_script_link(
    team_id: int,
    script_id: int,
    payload: AutomationScriptLinkCreate,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationScriptLinkResponse:
    async def _create(session: AsyncSession) -> AutomationScriptLinkResponse:
        service = AutomationLinkageService(session)
        link = await service.create_link(
            team_id=team_id,
            script_id=script_id,
            test_case_id=payload.test_case_id,
            link_type=payload.link_type,
            note=payload.note,
            actor=str(current_user.id),
        )
        return AutomationScriptLinkResponse(**link_to_dict(link))

    response = await _run_link_write(main_boundary, _create)
    await _log_link_action(
        ActionType.CREATE,
        current_user,
        team_id,
        str(response.id),
        f"建立 Automation Script Link: {response.id}",
        {
            "script_id": script_id,
            "test_case_id": response.test_case_id,
            "link_type": response.link_type,
        },
        request,
    )
    asyncio.create_task(dispatch_event_async(
        team_id,
        "script.linked",
        {
            "link_id": response.id,
            "script_id": script_id,
            "test_case_id": response.test_case_id,
            "link_type": str(response.link_type),
            "actor_user_id": current_user.id,
        },
    ))
    return response


@router.patch(
    "/automation-scripts/{script_id}/links/{link_id}",
    response_model=AutomationScriptLinkResponse,
)
async def update_automation_script_link(
    team_id: int,
    script_id: int,
    link_id: int,
    payload: AutomationScriptLinkUpdate,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationScriptLinkResponse:
    async def _update(session: AsyncSession) -> AutomationScriptLinkResponse:
        service = AutomationLinkageService(session)
        link = await service.update_link(
            team_id=team_id,
            script_id=script_id,
            link_id=link_id,
            link_type=payload.link_type,
            note=payload.note,
        )
        return AutomationScriptLinkResponse(**link_to_dict(link))

    response = await _run_link_write(main_boundary, _update)
    await _log_link_action(
        ActionType.UPDATE,
        current_user,
        team_id,
        str(link_id),
        f"更新 Automation Script Link: {link_id}",
        {"script_id": script_id, "updated_fields": sorted(payload.model_fields_set)},
        request,
    )
    return response


@router.delete(
    "/automation-scripts/{script_id}/links/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_automation_script_link(
    team_id: int,
    script_id: int,
    link_id: int,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> Response:
    async def _delete(session: AsyncSession) -> None:
        service = AutomationLinkageService(session)
        await service.delete_link(team_id=team_id, script_id=script_id, link_id=link_id)

    await _run_link_write(main_boundary, _delete)
    await _log_link_action(
        ActionType.DELETE,
        current_user,
        team_id,
        str(link_id),
        f"刪除 Automation Script Link: {link_id}",
        {"script_id": script_id},
        request,
    )
    asyncio.create_task(dispatch_event_async(
        team_id,
        "script.unlinked",
        {
            "link_id": link_id,
            "script_id": script_id,
            "actor_user_id": current_user.id,
        },
    ))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/automation-scripts/{script_id}/links",
    response_model=list[AutomationScriptLinkResponse],
)
async def list_automation_script_links(
    team_id: int,
    script_id: int,
    current_user: User = Depends(require_team_read),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> list[AutomationScriptLinkResponse]:
    """List all manual case links for a given script, with `created_by` source."""

    async def _list(session: AsyncSession) -> list[AutomationScriptLinkResponse]:
        service = AutomationLinkageService(session)
        try:
            links = await service.list_links_for_script(team_id=team_id, script_id=script_id)
        except AutomationLinkNotFoundError as exc:
            raise _not_found(str(exc)) from exc
        return [AutomationScriptLinkResponse(**link_to_dict(link)) for link in links]

    return await main_boundary.run_read(_list)


@router.get(
    "/test-cases/{case_identifier}/linked-automation",
    response_model=list[LinkedAutomationSummary],
)
async def list_linked_automation_for_test_case(
    team_id: int,
    case_identifier: str,
    current_user: User = Depends(require_team_read),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> list[LinkedAutomationSummary]:
    async def _list(session: AsyncSession) -> list[LinkedAutomationSummary]:
        case_id = await _resolve_case_id(session, team_id, case_identifier)
        service = AutomationLinkageService(session)
        summaries = await service.list_linked_automation(team_id=team_id, test_case_id=case_id)
        return [LinkedAutomationSummary(**item) for item in summaries]

    try:
        return await main_boundary.run_read(_list)
    except AutomationLinkNotFoundError as exc:
        raise _not_found(str(exc)) from exc


async def _resolve_case_id(session: AsyncSession, team_id: int, case_identifier: str) -> int:
    """Accept either local int id (as string) or lark_record_id; return local int id."""
    cleaned = (case_identifier or "").strip()
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TEST_CASE_NOT_FOUND", "message": "Missing test case identifier"},
        )
    if cleaned.isdigit():
        local_id = int(cleaned)
        result = await session.execute(
            select(TestCaseLocal.id).where(
                TestCaseLocal.id == local_id,
                TestCaseLocal.team_id == team_id,
            )
        )
        if result.scalar_one_or_none() is not None:
            return local_id
    result = await session.execute(
        select(TestCaseLocal.id).where(
            TestCaseLocal.lark_record_id == cleaned,
            TestCaseLocal.team_id == team_id,
        )
    )
    resolved = result.scalar_one_or_none()
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "TEST_CASE_NOT_FOUND",
                "message": f"Test case {case_identifier} not found in team {team_id}",
            },
        )
    return int(resolved)


async def _run_link_write(main_boundary: MainAccessBoundary, operation):
    try:
        return await main_boundary.run_write(operation)
    except AutomationLinkNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except AutomationLinkAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "AUTOMATION_LINK_ALREADY_EXISTS", "message": str(exc)},
        ) from exc
    except PrimaryAutomationLinkConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "PRIMARY_AUTOMATION_LINK_EXISTS", "message": str(exc)},
        ) from exc


def _not_found(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "AUTOMATION_LINK_NOT_FOUND", "message": message},
    )


async def _log_link_action(
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
            resource_type=ResourceType.AUTOMATION_SCRIPT_LINK,
            resource_id=resource_id,
            team_id=team_id,
            details=details,
            action_brief=action_brief,
            severity=AuditSeverity.CRITICAL if action_type == ActionType.DELETE else AuditSeverity.INFO,
            ip_address=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent") if request else None,
        )
    except Exception as exc:
        logger.warning("Failed to write automation link audit log: %s", exc, exc_info=True)
