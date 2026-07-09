"""MCP 專用 machine token 驗證與授權依賴。"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer

from app.audit import ActionType, AuditSeverity, ResourceType, audit_service
from app.auth.app_token_dependencies import get_current_app_token_principal
from app.models.app_token import READ_SCOPES, AppTokenPrincipal
from app.models.mcp import MCPMachinePrincipal


logger = logging.getLogger(__name__)

MCP_READ_PERMISSION = "mcp_read"
AUDIT_RESOURCE_ID_MAX_LEN = 100
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


def _build_audit_resource_id(endpoint_path: str, query_text: str) -> str:
    """建立符合審計欄位長度限制的 resource_id。"""
    resource_path = endpoint_path if not query_text else f"{endpoint_path}?{query_text}"
    if len(resource_path) <= AUDIT_RESOURCE_ID_MAX_LEN:
        return resource_path

    digest = hashlib.sha1(resource_path.encode("utf-8")).hexdigest()[:12]
    suffix = f"#h={digest}"
    prefix_len = max(1, AUDIT_RESOURCE_ID_MAX_LEN - len(suffix))
    return f"{resource_path[:prefix_len]}{suffix}"


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
        resource_path = _build_audit_resource_id(endpoint_path, query_text)
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
    app_principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
) -> MCPMachinePrincipal:
    """Compatibility wrapper: resolve via app-token auth and convert to MCPMachinePrincipal.

    This allows both legacy machine tokens and new app tokens to access
    /api/mcp/* read endpoints during the compatibility period.
    """
    if not app_principal.scopes or not app_principal.has_any_scope(*READ_SCOPES):
        await _log_mcp_access(
            request,
            None,
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

    principal = MCPMachinePrincipal(
        credential_id=app_principal.credential_id,
        credential_name=app_principal.credential_name,
        permission=app_principal.legacy_permission or "",
        allow_all_teams=app_principal.allow_all_teams,
        team_scope_ids=app_principal.team_scope_ids,
    )

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
