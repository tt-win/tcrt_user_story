"""App token automation API - trigger, cancel, reconcile via app token."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import ActionType
from app.auth.app_token_dependencies import (
    AppTokenErrorCodes,
    get_current_app_token_principal,
    log_app_token_audit,
    require_app_team_access,
)
from app.database import get_db
from app.db_access.main import create_main_access_boundary_for_session
from app.models.app_token import AppTokenPrincipal, SCOPE_AUTOMATION_EXECUTE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/app", tags=["app-automation"])


async def _audit_triggered_run(
    *,
    async_db: AsyncSession,
    request: Request,
    principal: AppTokenPrincipal,
    run_id: int,
    team_id: int,
    set_id: int,
) -> None:
    """Write a per-run audit entry matching the JWT `_audit_run_for_test_run_set` shape.

    Best-effort: failures are logged as warnings and MUST NOT roll back the
    trigger, since the run is already queued on CI by the time this runs.
    """
    from app.models.database_models import AutomationRun, AutomationScriptGroup

    row = (
        await async_db.execute(
            select(AutomationRun, AutomationScriptGroup)
            .join(AutomationScriptGroup, AutomationScriptGroup.id == AutomationRun.script_group_id)
            .where(AutomationRun.id == run_id)
        )
    ).first()
    if row is None:
        return
    run_db, suite_db = row
    await log_app_token_audit(
        request, principal, allowed=True,
        reason="automation_trigger",
        action_type=ActionType.CREATE, team_id=team_id,
        extra_details={
            "test_run_set_id": run_db.test_run_set_id,
            "script_group_id": run_db.script_group_id,
            "suite_name": suite_db.name,
            "workflow_id": run_db.workflow_id,
            "branch": run_db.branch,
            "trigger_source": "app-token",
            "environment": run_db.environment,
        },
    )


async def _check_automation_scope(
    request: Request, principal: AppTokenPrincipal, team_id: int
):
    if not principal.has_scope(SCOPE_AUTOMATION_EXECUTE):
        await log_app_token_audit(
            request, principal, allowed=False,
            reason="scope_denied:automation:execute", team_id=team_id
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": AppTokenErrorCodes.SCOPE_DENIED,
                "message": "Missing automation:execute scope",
            },
        )


@router.post("/teams/{team_id}/test-run-sets/{set_id}/run-automation")
async def app_trigger_test_run_set_automation(
    team_id: int,
    set_id: int,
    request: Request,
    payload: Optional[Dict[str, Any]] = Body(default=None),
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """Trigger automation for a Test Run Set via app token (requires automation:execute)."""
    await require_app_team_access(team_id, request, principal)
    await _check_automation_scope(request, principal, team_id)

    from app.services.test_run_set_automation_service import (
        TestRunSetAutomationError,
        TestRunSetAutomationService,
        TestRunSetEmptySuitesError,
        TestRunSetNotFoundError,
        TestRunSetSuiteCrossTeamError,
        TestRunSetSuiteNotFoundError,
        TestRunSetSuiteNotInSetError,
    )
    from app.services.automation.script_group_service import (
        AutomationScriptGroupCIApiError,
        AutomationEnvironmentIncompleteError,
        AutomationEnvironmentRequiredError,
    )
    from app.services.automation.provider_registry import (
        ProviderNotConfiguredError,
        ProviderRegistryError,
    )

    suite_id = payload.get("suite_id") if payload else None
    environment = payload.get("environment") if payload else None

    boundary = create_main_access_boundary_for_session(db)

    async def _run_async(async_db: AsyncSession) -> dict[str, list[int]]:
        service = TestRunSetAutomationService(async_db)
        return await service.trigger_automation_suites(
            team_id=team_id,
            set_id=set_id,
            suite_id=suite_id,
            actor=principal.audit_actor,
            environment=environment,
        )

    try:
        result = await boundary.run_write(_run_async)
    except TestRunSetNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TEST_RUN_SET_NOT_FOUND", "message": str(exc)},
        )
    except TestRunSetEmptySuitesError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "NO_AUTOMATION_SUITES", "message": str(exc)},
        )
    except (TestRunSetSuiteCrossTeamError, TestRunSetSuiteNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_SUITE_INVALID", "message": str(exc)},
        )
    except TestRunSetSuiteNotInSetError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_SUITE_NOT_IN_SET", "message": str(exc)},
        )
    except AutomationEnvironmentRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "ENVIRONMENT_REQUIRED", "message": str(exc), "available": exc.available},
        )
    except AutomationEnvironmentIncompleteError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "ENVIRONMENT_INCOMPLETE", "message": str(exc), "missing": exc.missing},
        )
    except AutomationScriptGroupCIApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "AUTOMATION_RUN_CI_API_FAILED", "message": str(exc)},
        )
    except ProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_PROVIDER_NOT_CONFIGURED", "message": str(exc)},
        )
    except ProviderRegistryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_PROVIDER_INVALID", "message": str(exc)},
        )
    except TestRunSetAutomationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_RUN_OPERATION_FAILED", "message": str(exc)},
        )

    # Best-effort per-run audit (mirrors JWT `_audit_run_for_test_run_set`).
    # Failures MUST NOT roll back the trigger; the runs are already QUEUED on CI.
    for run_id in result.get("run_ids", []):
        try:
            await boundary.run_write(
                lambda async_db, rid=run_id: _audit_triggered_run(
                    async_db=async_db,
                    request=request,
                    principal=principal,
                    run_id=rid,
                    team_id=team_id,
                    set_id=set_id,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to write app-token automation audit log for run %s: %s",
                run_id, exc, exc_info=True,
            )
    return result


@router.post("/teams/{team_id}/test-run-sets/{set_id}/runs/{run_id}/cancel")
async def app_cancel_test_run_set_run(
    team_id: int,
    set_id: int,
    run_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """Cancel an automation run via app token (requires automation:execute)."""
    await require_app_team_access(team_id, request, principal)
    await _check_automation_scope(request, principal, team_id)

    from app.services.automation.run_service import (
        AutomationRunAlreadyTerminalError,
        AutomationRunExternalIdMissingError,
        AutomationRunNotFoundError,
        AutomationRunService,
        AutomationRunServiceError,
    )
    from app.services.automation.provider_registry import (
        ProviderNotConfiguredError,
        ProviderRegistryError,
    )

    boundary = create_main_access_boundary_for_session(db)

    async def _cancel(async_db: AsyncSession):
        run_service = AutomationRunService(async_db)
        try:
            run = await run_service.get_run(team_id=team_id, run_id=run_id)
        except AutomationRunNotFoundError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        if run.test_run_set_id != set_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found in this set")
        return await run_service.cancel_run(
            team_id=team_id, run_id=run_id, actor=principal.audit_actor
        )

    try:
        run = await boundary.run_write(_cancel)
    except HTTPException:
        raise
    except AutomationRunAlreadyTerminalError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "AUTOMATION_RUN_ALREADY_TERMINAL", "message": str(exc)},
        ) from exc
    except AutomationRunExternalIdMissingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_RUN_EXTERNAL_ID_MISSING", "message": str(exc)},
        ) from exc
    except ProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_PROVIDER_NOT_CONFIGURED", "message": str(exc)},
        ) from exc
    except (AutomationRunServiceError, ProviderRegistryError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_RUN_OPERATION_FAILED", "message": str(exc)},
        ) from exc

    await log_app_token_audit(
        request, principal, allowed=True,
        reason="automation_cancel",
        action_type=ActionType.UPDATE, team_id=team_id,
        extra_details={"test_run_set_id": set_id, "run_id": run_id, "status": run.status},
    )
    return {"id": run.id, "status": run.status, "external_run_id": run.external_run_id}


@router.post("/teams/{team_id}/test-run-sets/{set_id}/runs/{run_id}/reconcile")
async def app_reconcile_test_run_set_run(
    team_id: int,
    set_id: int,
    run_id: int,
    request: Request,
    payload: Optional[Dict[str, Any]] = Body(default=None),
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """Reconcile an automation run via app token (requires automation:execute)."""
    await require_app_team_access(team_id, request, principal)
    await _check_automation_scope(request, principal, team_id)

    from app.services.automation.run_service import (
        AutomationRunNotFoundError,
        AutomationRunService,
        AutomationRunServiceError,
    )
    from app.services.automation.provider_registry import (
        ProviderNotConfiguredError,
        ProviderRegistryError,
    )

    boundary = create_main_access_boundary_for_session(db)

    async def _reconcile(async_db: AsyncSession):
        run_service = AutomationRunService(async_db)
        try:
            run = await run_service.get_run(team_id=team_id, run_id=run_id)
        except AutomationRunNotFoundError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        if run.test_run_set_id != set_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found in this set")
        payload_dict = payload or {}
        return await run_service.reconcile_run(
            team_id=team_id,
            run_id=run_id,
            external_run_id=payload_dict.get("external_run_id"),
            actor=principal.audit_actor,
        )

    try:
        run = await boundary.run_write(_reconcile)
    except HTTPException:
        raise
    except ProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_PROVIDER_NOT_CONFIGURED", "message": str(exc)},
        ) from exc
    except (AutomationRunServiceError, ProviderRegistryError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_RUN_OPERATION_FAILED", "message": str(exc)},
        ) from exc

    await log_app_token_audit(
        request, principal, allowed=True,
        reason="automation_reconcile",
        action_type=ActionType.UPDATE, team_id=team_id,
        extra_details={"test_run_set_id": set_id, "run_id": run_id, "status": run.status},
    )
    return {"id": run.id, "status": run.status, "external_run_id": run.external_run_id}
