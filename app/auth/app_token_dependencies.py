"""App token authentication, authorization, and audit dependencies for /api/app/*."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import logging
import re
import secrets
import time
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import ActionType, AuditSeverity, ResourceType, audit_service
from app.config import get_settings
from app.database import get_db
from app.db_access.main import create_main_access_boundary_for_session
from app.models.app_token import (
    APP_TOKEN_LAST_USED_THROTTLE_SECONDS,
    APP_TOKEN_PREFIX,
    APP_TOKEN_PREFIX_DISPLAY_LEN,
    APP_TOKEN_RANDOM_BYTES,
    ALL_APP_TOKEN_SCOPES,
    AppTokenPrincipal,
)
from app.models.database_models import (
    MCPMachineCredential,
    MCPMachineCredentialStatus,
    TeamAppToken,
    TeamAppTokenStatus,
)

logger = logging.getLogger(__name__)

MCP_READ_PERMISSION = "mcp_read"
AUDIT_RESOURCE_ID_MAX_LEN = 100
_app_bearer = HTTPBearer(auto_error=False)

# Per-IP token bucket for authentication *failures* on /api/app/* and /api/mcp/*.
# Successful auth never consumes a token, so legitimate traffic is never throttled;
# a source generating many failures depletes its bucket and receives HTTP 429.
# In-process state (per worker), matching the existing public-webhook limiter.
_auth_fail_buckets: dict[str, tuple[float, float]] = {}


def _auth_fail_rate_over_limit(client_ip: str) -> Optional[int]:
    """Peek the failure bucket without consuming. Returns Retry-After seconds if over limit."""
    auth_cfg = get_settings().auth
    capacity = max(1, auth_cfg.app_token_auth_fail_limit)
    window = max(1, auth_cfg.app_token_auth_fail_window_seconds)
    refill_per_second = capacity / window

    now = time.monotonic()
    tokens, updated_at = _auth_fail_buckets.get(client_ip, (float(capacity), now))
    elapsed = max(now - updated_at, 0)
    tokens = min(float(capacity), tokens + elapsed * refill_per_second)
    _auth_fail_buckets[client_ip] = (tokens, now)
    if tokens < 1:
        return max(1, int((1 - tokens) / refill_per_second))
    return None


def _record_auth_failure(client_ip: str) -> None:
    """Consume one token from the failure bucket for this IP."""
    auth_cfg = get_settings().auth
    capacity = max(1, auth_cfg.app_token_auth_fail_limit)
    now = time.monotonic()
    tokens, _updated_at = _auth_fail_buckets.get(client_ip, (float(capacity), now))
    _auth_fail_buckets[client_ip] = (max(0.0, tokens - 1), now)


class AppTokenErrorCodes:
    REQUIRED = "APP_TOKEN_REQUIRED"
    INVALID = "APP_TOKEN_INVALID"
    TEAM_SCOPE_DENIED = "APP_TOKEN_TEAM_SCOPE_DENIED"
    SCOPE_DENIED = "APP_TOKEN_SCOPE_DENIED"
    VALIDATION_ERROR = "APP_TOKEN_VALIDATION_ERROR"
    RESOURCE_NOT_FOUND = "APP_TOKEN_RESOURCE_NOT_FOUND"


def generate_app_token() -> tuple[str, str, str]:
    """Generate a new raw app token, its hash, and its display prefix.

    Returns (raw_token, token_hash, token_prefix).
    """
    random_part = secrets.token_hex(APP_TOKEN_RANDOM_BYTES)
    raw_token = f"{APP_TOKEN_PREFIX}{random_part}"
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    token_prefix = raw_token[:APP_TOKEN_PREFIX_DISPLAY_LEN]
    return raw_token, token_hash, token_prefix


def parse_scopes_json(scopes_json: Optional[str]) -> list[str]:
    if not scopes_json:
        return []
    try:
        parsed = json.loads(scopes_json)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(s) for s in parsed if isinstance(s, str) and s in ALL_APP_TOKEN_SCOPES]


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
    if "/test-case-sets" in path:
        return ResourceType.TEST_CASE_SET
    if "/test-case-sections" in path:
        return ResourceType.TEST_CASE_SECTION
    if "/attachments" in path:
        return ResourceType.ATTACHMENT
    if "/automation" in path:
        return ResourceType.AUTOMATION_RUN
    if path.startswith("/api/app/teams") or path.startswith("/api/mcp/teams"):
        return ResourceType.TEAM_SETTING
    return ResourceType.SYSTEM


def _extract_team_id(request: Request) -> int:
    raw_value = (request.path_params or {}).get("team_id")
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return 0


def _build_audit_resource_id(endpoint_path: str, query_text: str) -> str:
    resource_path = endpoint_path if not query_text else f"{endpoint_path}?{query_text}"
    if len(resource_path) <= AUDIT_RESOURCE_ID_MAX_LEN:
        return resource_path

    digest = hashlib.sha1(resource_path.encode("utf-8")).hexdigest()[:12]
    suffix = f"#h={digest}"
    prefix_len = max(1, AUDIT_RESOURCE_ID_MAX_LEN - len(suffix))
    return f"{resource_path[:prefix_len]}{suffix}"


_CREDENTIAL_VALUE_RE = re.compile(r"(?i)(password|secret|token|api[_-]?key|credential)")


def _redact_sensitive_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return "[REDACTED]"
    return value


def _redact_details(details: Dict[str, Any]) -> Dict[str, Any]:
    """Redact raw tokens, token hashes, credential-category test data, and local absolute paths."""
    redacted: Dict[str, Any] = {}
    for key, value in details.items():
        lower_key = key.lower()
        if lower_key in ("raw_token", "token_hash", "token", "secret"):
            redacted[key] = "[REDACTED]"
        elif _CREDENTIAL_VALUE_RE.search(lower_key) and isinstance(value, str):
            redacted[key] = "[REDACTED]"
        elif isinstance(value, dict):
            redacted[key] = _redact_details(value)
        elif isinstance(value, list):
            redacted[key] = [
                _redact_details(item) if isinstance(item, dict) else _redact_sensitive_value(item)
                for item in value
            ]
        elif isinstance(value, str) and value.startswith("/"):
            redacted[key] = "[REDACTED_PATH]"
        else:
            redacted[key] = value
    return redacted


async def log_app_token_audit(
    request: Request,
    principal: Optional[AppTokenPrincipal],
    *,
    allowed: bool,
    reason: str,
    action_type: ActionType = ActionType.READ,
    team_id: Optional[int] = None,
    extra_details: Optional[Dict[str, Any]] = None,
) -> None:
    """Write an allow/deny audit entry for an app-token request."""
    try:
        resolved_team_id = team_id if team_id is not None else _extract_team_id(request)
        endpoint_path = request.url.path
        query_text = request.url.query
        resource_path = _build_audit_resource_id(endpoint_path, query_text)
        actor = principal.audit_actor if principal else "app-token:anonymous"
        user_id = principal.credential_id if principal else 0
        severity = AuditSeverity.INFO if allowed else AuditSeverity.WARNING

        details: Dict[str, Any] = {
            "app_token_access": "allow" if allowed else "deny",
            "reason": reason,
            "endpoint": endpoint_path,
            "method": request.method,
            "query": query_text,
            "credential_id": principal.credential_id if principal else None,
            "credential_name": principal.credential_name if principal else None,
            "is_legacy": principal.is_legacy if principal else False,
            "requested_team_id": resolved_team_id if resolved_team_id > 0 else None,
            "allow_all_teams": principal.allow_all_teams if principal else False,
            "team_scope_ids": principal.team_scope_ids if principal else [],
            "scopes": principal.scopes if principal else [],
        }
        if extra_details:
            details.update(extra_details)

        details = _redact_details(details)

        await audit_service.log_action(
            user_id=user_id,
            username=actor,
            role="app-token",
            action_type=action_type,
            resource_type=_resolve_resource_type(endpoint_path),
            resource_id=resource_path,
            team_id=resolved_team_id if resolved_team_id > 0 else 0,
            details=details,
            action_brief=f"App token {'allowed' if allowed else 'denied'}: {reason}",
            severity=severity,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("App token audit write failed: %s", exc, exc_info=True)


async def get_current_app_token_principal(
    request: Request,
    db: AsyncSession = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_app_bearer),
) -> AppTokenPrincipal:
    """Authenticate an app/MCP credential, applying a per-IP failure rate limit.

    Peeks the failure bucket first (429 before any DB work or audit write when the IP
    is over its limit), then records a failure for every 401 so repeated invalid-token
    attempts from one source deplete the bucket while valid traffic is unaffected.
    """
    client_ip = request.client.host if request.client else "unknown"
    retry_after = _auth_fail_rate_over_limit(client_ip)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "APP_TOKEN_RATE_LIMITED",
                "message": "Too many authentication attempts",
            },
            headers={"Retry-After": str(retry_after)},
        )

    try:
        return await _authenticate_app_token(request, db, credentials)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            _record_auth_failure(client_ip)
        raise


async def _authenticate_app_token(
    request: Request,
    db: AsyncSession,
    credentials: Optional[HTTPAuthorizationCredentials],
) -> AppTokenPrincipal:
    """Resolve an app token (or legacy machine credential) into an AppTokenPrincipal."""
    if not credentials or not credentials.credentials:
        await log_app_token_audit(request, None, allowed=False, reason="missing_app_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": AppTokenErrorCodes.REQUIRED, "message": "Missing app token"},
        )

    token = credentials.credentials.strip()
    if not token:
        await log_app_token_audit(request, None, allowed=False, reason="empty_app_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": AppTokenErrorCodes.REQUIRED, "message": "Missing app token"},
        )

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    main_boundary = create_main_access_boundary_for_session(db)

    async def _resolve_principal(session: AsyncSession) -> AppTokenPrincipal:
        result = await session.execute(
            select(TeamAppToken).where(TeamAppToken.token_hash == token_hash)
        )
        app_token = result.scalar_one_or_none()

        if app_token:
            return await _resolve_app_token_principal(session, app_token, request)

        legacy_result = await session.execute(
            select(MCPMachineCredential).where(MCPMachineCredential.token_hash == token_hash)
        )
        legacy_cred = legacy_result.scalar_one_or_none()

        if legacy_cred:
            return await _resolve_legacy_principal(session, legacy_cred, request)

        await log_app_token_audit(request, None, allowed=False, reason="invalid_app_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": AppTokenErrorCodes.INVALID, "message": "Invalid app token"},
        )

    try:
        principal = await main_boundary.run_write(_resolve_principal)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("App token resolution failed: %s", exc, exc_info=True)
        raise

    # Legacy MCP machine credentials are confined to /api/mcp/*; reject them on the
    # /api/app/* namespace so a leaked read-only legacy token cannot reach the larger
    # app read surface. New team app tokens (is_legacy=False) are unaffected.
    if principal.is_legacy and request.url.path.startswith("/api/app/"):
        await log_app_token_audit(
            request, principal, allowed=False, reason="legacy_credential_on_app_namespace"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": AppTokenErrorCodes.INVALID, "message": "Invalid app token"},
        )

    request.state.app_token_principal = principal
    return principal


async def _resolve_app_token_principal(
    session: AsyncSession,
    app_token: TeamAppToken,
    request: Request,
) -> AppTokenPrincipal:
    status_value = (
        app_token.status.value
        if hasattr(app_token.status, "value")
        else str(app_token.status or "")
    )

    principal = AppTokenPrincipal(
        credential_id=app_token.id,
        credential_name=app_token.name,
        owner_team_id=app_token.owner_team_id,
        scopes=parse_scopes_json(app_token.scopes_json),
        allow_all_teams=False,
        team_scope_ids=[app_token.owner_team_id] if app_token.owner_team_id else [],
        is_legacy=False,
    )

    if status_value != TeamAppTokenStatus.ACTIVE.value:
        await log_app_token_audit(
            request, principal, allowed=False, reason="app_token_revoked"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": AppTokenErrorCodes.INVALID, "message": "Invalid app token"},
        )

    now = datetime.utcnow()
    if app_token.expires_at and app_token.expires_at <= now:
        await log_app_token_audit(
            request, principal, allowed=False, reason="app_token_expired"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": AppTokenErrorCodes.INVALID, "message": "Invalid app token"},
        )

    _update_last_used_throttled(session, app_token, now)
    await session.flush()
    return principal


async def _resolve_legacy_principal(
    session: AsyncSession,
    cred: MCPMachineCredential,
    request: Request,
) -> AppTokenPrincipal:
    status_value = (
        cred.status.value
        if hasattr(cred.status, "value")
        else str(cred.status or "")
    )

    permission = cred.permission or ""
    scopes: list[str] = []
    if permission.strip().lower() == MCP_READ_PERMISSION:
        scopes = [
            "test_case:read",
            "test_run:read",
        ]

    principal = AppTokenPrincipal(
        credential_id=cred.id,
        credential_name=cred.name,
        owner_team_id=None,
        scopes=scopes,
        allow_all_teams=bool(cred.allow_all_teams),
        team_scope_ids=_parse_team_scope_ids(cred.team_scope_json),
        is_legacy=True,
        legacy_permission=permission,
    )

    if status_value != MCPMachineCredentialStatus.ACTIVE.value:
        await log_app_token_audit(
            request, principal, allowed=False, reason="legacy_machine_token_revoked"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": AppTokenErrorCodes.INVALID, "message": "Invalid app token"},
        )

    now = datetime.utcnow()
    if cred.expires_at and cred.expires_at <= now:
        await log_app_token_audit(
            request, principal, allowed=False, reason="legacy_machine_token_expired"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": AppTokenErrorCodes.INVALID, "message": "Invalid app token"},
        )

    _update_last_used_throttled(session, cred, now)
    await session.flush()
    return principal


def _update_last_used_throttled(session: AsyncSession, credential: Any, now: datetime) -> None:
    last_used = getattr(credential, "last_used_at", None)
    if last_used is not None:
        elapsed = (now - last_used).total_seconds()
        if elapsed < APP_TOKEN_LAST_USED_THROTTLE_SECONDS:
            return
    credential.last_used_at = now


async def require_app_team_access(
    team_id: int,
    request: Request,
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
) -> AppTokenPrincipal:
    """Verify the principal can access the requested team's resources."""
    if not principal.can_access_team(team_id):
        await log_app_token_audit(
            request, principal, allowed=False, reason="team_scope_denied", team_id=team_id
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": AppTokenErrorCodes.TEAM_SCOPE_DENIED,
                "message": "App token does not have access to this team",
            },
        )
    return principal


async def require_app_scope(
    scope: str,
    request: Request,
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
) -> AppTokenPrincipal:
    """Verify the principal has the required operation scope."""
    if not principal.has_scope(scope):
        await log_app_token_audit(
            request, principal, allowed=False, reason=f"scope_denied:{scope}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": AppTokenErrorCodes.SCOPE_DENIED,
                "message": f"App token missing required scope: {scope}",
            },
        )
    return principal


def make_app_scope_dependency(scope: str):
    """Factory for creating a scope-checking dependency for a specific scope."""

    def _dependency(
        request: Request,
        principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
    ) -> AppTokenPrincipal:
        if not principal.has_scope(scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": AppTokenErrorCodes.SCOPE_DENIED,
                    "message": f"App token missing required scope: {scope}",
                },
            )
        return principal

    return _dependency


def make_app_team_access_dependency():
    """Factory for creating a team-access-checking dependency.

    The returned dependency extracts team_id from the path parameter.
    """

    def _dependency(
        request: Request,
        principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
    ) -> AppTokenPrincipal:
        team_id = _extract_team_id(request)
        if team_id > 0 and not principal.can_access_team(team_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": AppTokenErrorCodes.TEAM_SCOPE_DENIED,
                    "message": "App token does not have access to this team",
                },
            )
        return principal

    return _dependency
