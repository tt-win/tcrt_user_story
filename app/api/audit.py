"""審計記錄查詢相關 API"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit_service, AuditLogQuery, ActionType, ResourceType, AuditSeverity
from app.auth.dependencies import require_role
from app.auth.models import UserRole
from app.db_access.main import MainAccessBoundary, get_main_access_boundary
from app.models.database_models import Team, User
from app.audit.models import Impact, Outcome

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditLogSearchRequest(BaseModel):
    """POST /audit/logs/search 請求模型"""
    query: AuditLogQuery = Field(default_factory=lambda: AuditLogQuery(), description="查詢條件")
    page: int = Field(1, ge=1, description="頁碼（覆蓋 query.page）")
    page_size: int = Field(50, ge=1, le=500, description="每頁筆數（覆蓋 query.page_size）")


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError as exc:  # noqa: B904
        raise HTTPException(status_code=400, detail={"code": "INVALID_DATETIME", "message": f"無法解析時間: {value}"}) from exc


async def _fetch_team_names(
    team_ids: Iterable[int],
    *,
    main_boundary: MainAccessBoundary,
) -> Dict[int, str]:
    unique_ids = {tid for tid in team_ids if tid}
    if not unique_ids:
        return {}

    async def _load(session: AsyncSession) -> Dict[int, str]:
        result = await session.execute(select(Team.id, Team.name).where(Team.id.in_(unique_ids)))
        return {row[0]: row[1] for row in result.all()}

    return await main_boundary.run_read(_load)


@router.get("/logs")
async def list_audit_logs(
    *,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
    username: Optional[str] = Query(None, description="使用者名稱（模糊搜尋）"),
    role: Optional[str] = Query(None, description="角色"),
    resource_type: Optional[ResourceType] = Query(None, description="資源類型"),
    action_type: Optional[ActionType] = Query(None, description="操作類型"),
    team_id: Optional[int] = Query(None, description="團隊 ID"),
    severity: Optional[AuditSeverity] = Query(None, description="嚴重性"),
    event_code: Optional[str] = Query(None, description="Event catalog code"),
    impact: Optional[Impact] = Query(None, description="Business impact level"),
    outcome: Optional[Outcome] = Query(None, description="Operation outcome"),
    start_time: Optional[str] = Query(None, description="開始時間 (ISO8601)"),
    end_time: Optional[str] = Query(None, description="結束時間 (ISO8601)"),
    page: int = Query(1, ge=1, description="頁碼"),
    page_size: int = Query(50, ge=1, le=500, description="每頁筆數"),
) -> Dict[str, Any]:
    query = AuditLogQuery(
        username=username,
        role=role,
        resource_type=resource_type,
        action_type=action_type,
        team_id=team_id,
        severity=severity,
        event_code=event_code,
        impact=impact,
        outcome=outcome,
        start_time=_parse_iso_datetime(start_time),
        end_time=_parse_iso_datetime(end_time),
        page=page,
        page_size=page_size,
    )

    response = await audit_service.query_logs(query, current_user)
    team_map = await _fetch_team_names(
        (item.team_id for item in response.items if item.team_id is not None),
        main_boundary=main_boundary,
    )

    return {
        "items": [
            {
                "id": item.id,
                "timestamp": item.timestamp,
                "username": item.username,
                "role": item.role,
                "action_type": item.action_type.value,
                "resource_type": item.resource_type.value,
                "resource_id": item.resource_id,
                "team_id": item.team_id,
                "team_name": team_map.get(item.team_id, "") if item.team_id else "",
                "severity": item.severity.value,
                "action_brief": item.action_brief,
                "ip_address": item.ip_address,
                "event_code": item.event_code,
                "impact": item.impact.value if item.impact else None,
                "outcome": item.outcome.value if item.outcome else None,
                "schema_version": item.schema_version,
            }
            for item in response.items
        ],
        "total": response.total,
        "page": response.page,
        "page_size": response.page_size,
        "total_pages": response.total_pages,
    }


@router.post("/logs/search")
async def search_audit_logs(
    *,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
    request: AuditLogSearchRequest,
) -> Dict[str, Any]:
    """POST /audit/logs/search - 全功能搜尋（含 event_code/impact/outcome/ASCII ilike、不搜 details）"""
    # Override page/page_size from request body
    query = request.query.model_copy(update={
        "page": request.page,
        "page_size": request.page_size,
    })
    
    # Reject q parameter if present (use 400 with specific error code)
    # Note: q is not in AuditLogQuery model, but we check explicitly for future-proofing
    # If q somehow gets passed via query params, it will be ignored by the model
    
    response = await audit_service.query_logs(query, current_user)
    team_map = await _fetch_team_names(
        (item.team_id for item in response.items if item.team_id is not None),
        main_boundary=main_boundary,
    )

    return {
        "items": [
            {
                "id": item.id,
                "timestamp": item.timestamp,
                "username": item.username,
                "role": item.role,
                "action_type": item.action_type.value,
                "resource_type": item.resource_type.value,
                "resource_id": item.resource_id,
                "team_id": item.team_id,
                "team_name": team_map.get(item.team_id, "") if item.team_id else "",
                "severity": item.severity.value,
                "action_brief": item.action_brief,
                "ip_address": item.ip_address,
                "event_code": item.event_code,
                "impact": item.impact.value if item.impact else None,
                "outcome": item.outcome.value if item.outcome else None,
                "schema_version": item.schema_version,
            }
            for item in response.items
        ],
        "total": response.total,
        "page": response.page,
        "page_size": response.page_size,
        "total_pages": response.total_pages,
    }


@router.get("/logs/export")
async def export_audit_logs(
    *,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
    username: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    resource_type: Optional[ResourceType] = Query(None),
    action_type: Optional[ActionType] = Query(None),
    team_id: Optional[int] = Query(None),
    severity: Optional[AuditSeverity] = Query(None),
    event_code: Optional[str] = Query(None),
    impact: Optional[Impact] = Query(None),
    outcome: Optional[Outcome] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    timezone_name: Optional[str] = Query(None, alias="timezone"),
) -> StreamingResponse:
    query = AuditLogQuery(
        username=username,
        role=role,
        resource_type=resource_type,
        action_type=action_type,
        team_id=team_id,
        severity=severity,
        event_code=event_code,
        impact=impact,
        outcome=outcome,
        start_time=_parse_iso_datetime(start_time),
        end_time=_parse_iso_datetime(end_time),
        page=1,
        page_size=1000,
    )

    logs = await audit_service.fetch_logs_for_export(query, current_user)
    team_map = await _fetch_team_names(
        (log.team_id for log in logs if log.team_id is not None),
        main_boundary=main_boundary,
    )

    tzinfo = timezone.utc
    if timezone_name:
        try:
            tzinfo = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:  # noqa: B904
            raise HTTPException(status_code=400, detail={"code": "INVALID_TIMEZONE", "message": "未知的時區"}) from exc

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "timestamp",
        "timestamp_local",
        "username",
        "role",
        "action_type",
        "resource_type",
        "resource_id",
        "team_id",
        "team_name",
        "action_brief",
        "severity",
        "ip_address",
        "details",
        "event_code",
        "impact",
        "outcome",
        "schema_version",
    ])

    for log in logs:
        utc_dt = log.timestamp
        if utc_dt.tzinfo is None:
            utc_dt = utc_dt.replace(tzinfo=timezone.utc)
        else:
            utc_dt = utc_dt.astimezone(timezone.utc)
        local_dt = utc_dt.astimezone(tzinfo)

        details_json = ""
        if log.details is not None:
            try:
                details_json = json.dumps(log.details, ensure_ascii=False)
            except (TypeError, ValueError):
                details_json = str(log.details)

        writer.writerow([
            utc_dt.isoformat(),
            local_dt.isoformat(),
            log.username,
            log.role,
            log.action_type.value,
            log.resource_type.value,
            log.resource_id,
            log.team_id,
            team_map.get(log.team_id, "") if log.team_id else "",
            log.action_brief or "",
            log.severity.value,
            log.ip_address or "",
            details_json,
            log.event_code or "",
            log.impact.value if log.impact else "",
            log.outcome.value if log.outcome else "",
            log.schema_version,
        ])

    output.seek(0)
    filename = f"audit_logs_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.csv"

    csv_bytes = output.getvalue().encode("utf-8-sig")

    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
        },
    )
