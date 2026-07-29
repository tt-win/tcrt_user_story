"""Current-user homepage dashboard API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.auth.dependencies import get_current_user
from app.db_access import AuditAccessBoundary, MainAccessBoundary, get_audit_access_boundary, get_main_access_boundary
from app.models.dashboard import DashboardResponse
from app.models.database_models import User
from app.services.dashboard_service import DashboardService


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
async def get_dashboard(
    response: Response,
    current_user: User = Depends(get_current_user),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
    audit_boundary: AuditAccessBoundary = Depends(get_audit_access_boundary),
) -> DashboardResponse:
    """Return the only dashboard view authorized for the current bearer user."""

    response.headers["Cache-Control"] = "no-store"
    try:
        return await DashboardService(main_boundary, audit_boundary).build(current_user)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 - never pass a storage exception to the browser
        logger.exception("Dashboard assembly failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DASHBOARD_UNAVAILABLE", "message": "Dashboard is temporarily unavailable"},
        ) from None
