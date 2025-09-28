"""全域審計記錄 Middleware"""

import logging
from typing import Optional, Dict

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.audit import audit_service, ActionType, ResourceType, AuditSeverity


logger = logging.getLogger(__name__)


class AuditMiddleware(BaseHTTPMiddleware):
    """攔截 API 請求並記錄 CRUD 操作至審計系統"""

    METHOD_ACTION_MAP = {
        "POST": ActionType.CREATE,
        "PUT": ActionType.UPDATE,
        "PATCH": ActionType.UPDATE,
        "DELETE": ActionType.DELETE,
        "GET": ActionType.READ,
    }

    RESOURCE_PATH_MAP = (
        ("/api/test-run-configs", ResourceType.TEST_RUN),
        ("/api/test-runs", ResourceType.TEST_RUN),
        ("/api/testcases", ResourceType.TEST_CASE),
        ("/api/teams", ResourceType.TEAM_SETTING),
        ("/api/users", ResourceType.USER),
        ("/api/permissions", ResourceType.PERMISSION),
        ("/api/attachments", ResourceType.ATTACHMENT),
        ("/api/auth", ResourceType.AUTH),
    )

    AUTO_LOG_RESOURCE_TYPES: tuple[ResourceType, ...] = ()

    def _resolve_resource_type(self, path: str) -> ResourceType:
        for prefix, resource in self.RESOURCE_PATH_MAP:
            if path.startswith(prefix):
                return resource
        return ResourceType.SYSTEM

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        try:
            await self._maybe_record_audit(request, response)
        except Exception as exc:  # noqa: BLE001
            logger.warning("寫入審計記錄失敗: %s", exc, exc_info=True)

        return response

    async def _maybe_record_audit(self, request: Request, response: Response) -> None:
        path = request.url.path
        method = request.method.upper()

        if not path.startswith("/api"):
            return

        # Login/Logout 由對應端點自行處理
        if path.startswith("/api/auth/login") or path.startswith("/api/auth/logout"):
            return

        action_type = self.METHOD_ACTION_MAP.get(method)
        if not action_type:
            return

        status_code = response.status_code
        if status_code >= 400:
            return

        current_user = getattr(request.state, "current_user", None)
        if not current_user:
            return

        role_value = getattr(current_user.role, "value", None) or str(current_user.role)
        user_id = getattr(current_user, "id", None)
        username = getattr(current_user, "username", "")
        if user_id is None:
            return

        path_params: Dict[str, str] = getattr(request, "path_params", {}) or {}
        team_id_value = path_params.get("team_id") or 0
        try:
            team_id = int(team_id_value)
        except (TypeError, ValueError):
            team_id = 0

        resource_id = self._resolve_resource_id(path_params, path)
        resource_type = self._resolve_resource_type(path)

        if resource_type not in self.AUTO_LOG_RESOURCE_TYPES:
            return

        severity = AuditSeverity.CRITICAL if action_type == ActionType.DELETE else AuditSeverity.INFO

        details = {
            "method": method,
            "path": path,
            "query": request.url.query,
            "status": status_code,
        }

        client_host = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")

        await audit_service.log_action(
            user_id=user_id,
            username=username,
            role=role_value,
            action_type=action_type,
            resource_type=resource_type,
            resource_id=resource_id,
            team_id=team_id,
            details=details,
            severity=severity,
            ip_address=client_host,
            user_agent=user_agent,
        )

    @staticmethod
    def _resolve_resource_id(path_params: Dict[str, str], fallback_path: str) -> str:
        candidate_keys = (
            "record_id",
            "config_id",
            "test_case_number",
            "item_id",
            "user_id",
            "team_id",
            "id",
        )
        for key in candidate_keys:
            value = path_params.get(key)
            if value is not None:
                return str(value)
        return fallback_path
