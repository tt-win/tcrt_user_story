"""MCP 專用 machine token 驗證與授權依賴。"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import ActionType, AuditSeverity, ResourceType, audit_service
from app.database import get_db
from app.models.database_models import MCPMachineCredential, MCPMachineCredentialStatus
from app.models.mcp import MCPMachinePrincipal


logger = logging.getLogger(__name__)

MCP_READ_PERMISSION = "mcp_read"
_machine_bearer = HTTPBearer(auto_error=False)


def _parse_team_scope_ids(team_scope_json: Optional[str]) -> list[int]:
    if not team_scope_json:
        return []
    try:
        parsed = json.loads(team_scope_json)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []

    team_ids: list[int] = []
    seen: set[int] = set()
    for value in parsed:
        try:
            team_id = int(value)
        except (TypeError, ValueError):
            continue
        if team_id <= 0 or team_id in seen:
            continue
        seen.add(team_id)
        team_ids.append(team_id)
    return team_ids


def _resolve_resource_type(path: str) -> ResourceType:
    if "/test-cases" in path:
        return ResourceType.TEST_CASE
    if "/test-runs" in path:
        return ResourceType.TEST_RUN
    if path.startswith("/api/mcp/teams"):
        return ResourceType.TEAM_SETTING
    return ResourceType.SYSTEM


def _extract_team_id(request: Request) -> int:
    raw_value = (request.path_params or {}).get("team_id")
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return 0


async def _log_mcp_access(
    request: Request,
    principal: Optional[MCPMachinePrincipal],
    *,
    allowed: bool,
    reason: str,
    team_id: Optional[int] = None,
) -> None:
    try:
        resolved_team_id = team_id if team_id is not None else _extract_team_id(request)
        endpoint_path = request.url.path
        query_text = request.url.query
        resource_path = endpoint_path if not query_text else f"{endpoint_path}?{query_text}"
        username = f"mcp:{principal.credential_name}" if principal else "mcp:anonymous"
        user_id = principal.credential_id if principal else 0
        severity = AuditSeverity.INFO if allowed else AuditSeverity.WARNING
        allow_value = principal.allow_all_teams if principal else False
        scope_value = principal.team_scope_ids if principal else []
        details = {
            "mcp_access": "allow" if allowed else "deny",
            "reason": reason,
            "endpoint": endpoint_path,
            "method": request.method,
            "query": query_text,
            "machine_credential_id": principal.credential_id if principal else None,
            "machine_credential_name": principal.credential_name if principal else None,
            "requested_team_id": resolved_team_id if resolved_team_id > 0 else None,
            "allow_all_teams": allow_value,
            "team_scope_ids": scope_value,
        }
        await audit_service.log_action(
            user_id=user_id,
            username=username,
            role="machine",
            action_type=ActionType.READ,
            resource_type=_resolve_resource_type(endpoint_path),
            resource_id=resource_path,
            team_id=resolved_team_id if resolved_team_id > 0 else 0,
            details=details,
            action_brief=f"MCP machine {'allowed' if allowed else 'denied'}: {reason}",
            severity=severity,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("MCP 審計寫入失敗: %s", exc, exc_info=True)


async def log_mcp_allow(
    request: Request,
    principal: MCPMachinePrincipal,
    *,
    reason: str = "mcp_read_allowed",
    team_id: Optional[int] = None,
) -> None:
    await _log_mcp_access(
        request,
        principal,
        allowed=True,
        reason=reason,
        team_id=team_id,
    )


async def get_current_machine_principal(
    request: Request,
    db: AsyncSession = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_machine_bearer),
) -> MCPMachinePrincipal:
    if not credentials or not credentials.credentials:
        await _log_mcp_access(
            request,
            None,
            allowed=False,
            reason="missing_machine_token",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "MCP_AUTH_REQUIRED", "message": "缺少 machine token"},
        )

    token = credentials.credentials.strip()
    if not token:
        await _log_mcp_access(
            request,
            None,
            allowed=False,
            reason="empty_machine_token",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "MCP_AUTH_REQUIRED", "message": "缺少 machine token"},
        )

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    result = await db.execute(
        select(MCPMachineCredential).where(MCPMachineCredential.token_hash == token_hash)
    )
    credential = result.scalar_one_or_none()

    if not credential:
        await _log_mcp_access(
            request,
            None,
            allowed=False,
            reason="invalid_machine_token",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_MACHINE_TOKEN", "message": "machine token 無效"},
        )

    credential_status = (
        credential.status.value
        if hasattr(credential.status, "value")
        else str(credential.status or "")
    )
    if credential_status != MCPMachineCredentialStatus.ACTIVE.value:
        principal = MCPMachinePrincipal(
            credential_id=credential.id,
            credential_name=credential.name,
            permission=credential.permission or "",
            allow_all_teams=bool(credential.allow_all_teams),
            team_scope_ids=_parse_team_scope_ids(credential.team_scope_json),
        )
        await _log_mcp_access(
            request,
            principal,
            allowed=False,
            reason="machine_token_revoked",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "MACHINE_TOKEN_REVOKED", "message": "machine token 已停用"},
        )

    now = datetime.utcnow()
    if credential.expires_at and credential.expires_at <= now:
        principal = MCPMachinePrincipal(
            credential_id=credential.id,
            credential_name=credential.name,
            permission=credential.permission or "",
            allow_all_teams=bool(credential.allow_all_teams),
            team_scope_ids=_parse_team_scope_ids(credential.team_scope_json),
        )
        await _log_mcp_access(
            request,
            principal,
            allowed=False,
            reason="machine_token_expired",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "MACHINE_TOKEN_EXPIRED", "message": "machine token 已過期"},
        )

    permission_value = (credential.permission or "").strip().lower()
    team_scope_ids = _parse_team_scope_ids(credential.team_scope_json)
    principal = MCPMachinePrincipal(
        credential_id=credential.id,
        credential_name=credential.name,
        permission=credential.permission or "",
        allow_all_teams=bool(credential.allow_all_teams),
        team_scope_ids=team_scope_ids,
    )

    if permission_value != MCP_READ_PERMISSION:
        await _log_mcp_access(
            request,
            principal,
            allowed=False,
            reason="missing_mcp_read_permission",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "INSUFFICIENT_MACHINE_PERMISSION",
                "message": "machine token 缺少 mcp_read 權限",
            },
        )

    credential.last_used_at = now
    try:
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.warning("更新 machine token last_used_at 失敗: %s", exc, exc_info=True)

    request.state.mcp_machine_principal = principal
    return principal


async def require_mcp_team_access(
    team_id: int,
    request: Request,
    principal: MCPMachinePrincipal = Depends(get_current_machine_principal),
) -> MCPMachinePrincipal:
    if not principal.can_access_team(team_id):
        await _log_mcp_access(
            request,
            principal,
            allowed=False,
            reason="team_scope_denied",
            team_id=team_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "TEAM_SCOPE_DENIED",
                "message": "無權限存取此 team 的 MCP 資料",
            },
        )

    await _log_mcp_access(
        request,
        principal,
        allowed=True,
        reason="team_scope_allowed",
        team_id=team_id,
    )
    return principal
