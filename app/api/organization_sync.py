#!/usr/bin/env python3
"""
全域組織架構同步 API 端點

提供不依賴特定團隊的組織架構同步功能，
適用於系統級別的組織數據維護。
"""

import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.audit import ActionType, AuditSeverity, ResourceType, audit_service
from app.auth.dependencies import require_super_admin
from app.db_access.main import MainAccessBoundary, get_main_access_boundary
from app.models.database_models import (
    MCPMachineCredential,
    MCPMachineCredentialStatus,
    Team,
    User,
)
from ..services.lark_org_sync_service import get_lark_org_sync_service
from ..services.scheduler import task_scheduler

# 創建路由器
router = APIRouter(prefix="/organization", tags=["organization"])
logger = logging.getLogger(__name__)


class MCPMachineTokenCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="token 名稱（唯一）")
    description: Optional[str] = Field(None, max_length=2000, description="用途描述")
    allow_all_teams: bool = Field(False, description="是否允許存取所有團隊")
    team_scope_ids: List[int] = Field(default_factory=list, description="允許存取的 team_id 清單")
    expires_in_days: Optional[int] = Field(
        None,
        ge=1,
        le=3650,
        description="有效天數（空值代表不過期）",
    )


class ScheduledServiceUpdateRequest(BaseModel):
    enabled: bool = Field(..., description="是否啟用排程")
    run_at_time: str = Field(..., description="每日執行時間（HH:MM）")


def _scheduler_api_error(exc: Exception) -> HTTPException:
    message = str(exc)
    if "HH:MM" in message:
        return HTTPException(
            status_code=400,
            detail={
                "code": "SCHEDULE_INVALID_TIME",
                "message": "排程時間格式錯誤，請使用 HH:MM",
            },
        )
    if "不支援的排程服務" in message:
        return HTTPException(
            status_code=404,
            detail={
                "code": "SCHEDULE_SERVICE_NOT_FOUND",
                "message": message,
            },
        )
    return HTTPException(
        status_code=500,
        detail={
            "code": "SCHEDULE_SERVICE_UPDATE_FAILED",
            "message": "更新排程服務失敗",
        },
    )


def _normalize_team_scope_ids(raw_ids: List[int]) -> List[int]:
    normalized: List[int] = []
    seen = set()
    for raw in raw_ids or []:
        try:
            team_id = int(raw)
        except (TypeError, ValueError):
            continue
        if team_id <= 0 or team_id in seen:
            continue
        seen.add(team_id)
        normalized.append(team_id)
    return normalized


def _resolve_role_value(raw_role: object) -> str:
    if hasattr(raw_role, "value"):
        return str(getattr(raw_role, "value"))
    return str(raw_role or "")


@router.post("/mcp/machine-tokens")
async def create_mcp_machine_token(
    payload: MCPMachineTokenCreateRequest,
    request: Request,
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
    current_user: User = Depends(require_super_admin()),
):
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(
            status_code=400,
            detail={"code": "MCP_MACHINE_TOKEN_NAME_REQUIRED", "message": "請填寫 token 名稱"},
        )

    team_scope_ids = _normalize_team_scope_ids(payload.team_scope_ids)
    if not payload.allow_all_teams and not team_scope_ids:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "MCP_MACHINE_TOKEN_SCOPE_REQUIRED",
                "message": "未啟用全部團隊時，至少需指定一個 team scope",
            },
        )

    if not payload.allow_all_teams and team_scope_ids:

        async def _load_existing_team_ids(session):
            existing_rows = await session.execute(select(Team.id).where(Team.id.in_(team_scope_ids)))
            return {int(team_id) for (team_id,) in existing_rows.all()}

        existing_ids = await main_boundary.run_read(_load_existing_team_ids)
        missing_ids = [team_id for team_id in team_scope_ids if team_id not in existing_ids]
        if missing_ids:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "MCP_MACHINE_TOKEN_SCOPE_INVALID_TEAM",
                    "message": f"找不到 team_id: {', '.join(str(tid) for tid in missing_ids)}",
                },
            )

    expires_at: Optional[datetime] = None
    if payload.expires_in_days:
        expires_at = datetime.utcnow() + timedelta(days=int(payload.expires_in_days))

    raw_token = secrets.token_hex(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    async def _create_machine_credential(session):
        machine_credential = MCPMachineCredential(
            name=name,
            description=(payload.description or "").strip() or None,
            token_hash=token_hash,
            permission="mcp_read",
            status=MCPMachineCredentialStatus.ACTIVE,
            allow_all_teams=bool(payload.allow_all_teams),
            team_scope_json=None if payload.allow_all_teams else json.dumps(team_scope_ids, ensure_ascii=False),
            expires_at=expires_at,
            created_by_user_id=getattr(current_user, "id", None),
        )
        session.add(machine_credential)
        await session.flush()
        await session.refresh(machine_credential)
        return {
            "credential_id": machine_credential.id,
            "name": machine_credential.name,
            "permission": machine_credential.permission,
            "allow_all_teams": bool(machine_credential.allow_all_teams),
            "expires_at": machine_credential.expires_at,
            "created_at": machine_credential.created_at,
        }

    try:
        machine_credential_payload = await main_boundary.run_write(_create_machine_credential)
    except IntegrityError as exc:
        raw_message = str(getattr(exc, "orig", exc)).lower()
        if "mcp_machine_credentials.name" in raw_message:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "MCP_MACHINE_TOKEN_NAME_EXISTS",
                    "message": f"machine token 名稱已存在: {name}",
                },
            ) from exc
        raise HTTPException(
            status_code=500,
            detail={
                "code": "MCP_MACHINE_TOKEN_CREATE_FAILED",
                "message": "建立 machine token 失敗",
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={
                "code": "MCP_MACHINE_TOKEN_CREATE_FAILED",
                "message": "建立 machine token 失敗",
            },
        ) from exc

    response_payload = {
        "success": True,
        "data": {
            "credential_id": machine_credential_payload["credential_id"],
            "name": machine_credential_payload["name"],
            "permission": machine_credential_payload["permission"],
            "allow_all_teams": machine_credential_payload["allow_all_teams"],
            "team_scope_ids": [] if payload.allow_all_teams else team_scope_ids,
            "expires_at": machine_credential_payload["expires_at"].isoformat()
            if machine_credential_payload["expires_at"]
            else None,
            "created_at": machine_credential_payload["created_at"].isoformat()
            if machine_credential_payload["created_at"]
            else None,
            "raw_token": raw_token,
        },
    }

    try:
        await audit_service.log_action(
            user_id=getattr(current_user, "id", 0) or 0,
            username=getattr(current_user, "username", "unknown"),
            role=_resolve_role_value(getattr(current_user, "role", "")),
            action_type=ActionType.CREATE,
            resource_type=ResourceType.SYSTEM,
            resource_id=f"mcp_machine_credential:{machine_credential_payload['credential_id']}",
            team_id=0,
            details={
                "credential_id": machine_credential_payload["credential_id"],
                "name": machine_credential_payload["name"],
                "permission": machine_credential_payload["permission"],
                "allow_all_teams": machine_credential_payload["allow_all_teams"],
                "team_scope_ids": [] if payload.allow_all_teams else team_scope_ids,
                "expires_at": machine_credential_payload["expires_at"].isoformat()
                if machine_credential_payload["expires_at"]
                else None,
            },
            action_brief=f"建立 MCP machine token: {machine_credential_payload['name']}",
            severity=AuditSeverity.INFO,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("MCP machine token 審計紀錄寫入失敗: %s", exc, exc_info=True)

    return response_payload


@router.get("/sync/status")
async def get_organization_sync_status():
    """
    獲取組織架構同步狀態

    Returns:
        當前同步狀態和最後一次同步結果
    """
    try:
        sync_service = get_lark_org_sync_service()
        status = sync_service.get_sync_status()

        return {"success": True, "data": status}

    except Exception as e:
        logger.error(f"獲取組織同步狀態失敗: {e}")
        raise HTTPException(status_code=500, detail=f"獲取同步狀態失敗: {str(e)}")


@router.get("/stats")
async def get_organization_stats():
    """
    獲取組織架構統計信息

    Returns:
        部門和用戶統計數據
    """
    try:
        sync_service = get_lark_org_sync_service()
        stats = await sync_service.get_organization_stats()

        return {"success": True, "data": stats}

    except Exception as e:
        logger.error(f"獲取組織統計信息失敗: {e}")
        raise HTTPException(status_code=500, detail=f"獲取統計信息失敗: {str(e)}")


@router.post("/sync")
async def trigger_organization_sync(
    background_tasks: BackgroundTasks, sync_type: str = Query("full", description="同步類型: full, departments, users")
):
    """
    觸發組織架構背景同步（無需團隊依賴）

    Args:
        sync_type: 同步類型（full: 完整同步, departments: 僅部門, users: 僅用戶）
        background_tasks: 背景任務管理器

    Returns:
        同步開始確認
    """
    try:
        # 獲取組織同步服務
        sync_service = get_lark_org_sync_service()

        # 檢查是否已在同步中
        current_status = sync_service.get_sync_status()
        if current_status.get("is_syncing", False):
            return {"success": False, "message": "同步正在進行中，請稍後再試", "data": {"is_syncing": True}}

        # 驗證同步類型
        if sync_type not in ["full", "departments", "users"]:
            raise HTTPException(status_code=400, detail="無效的同步類型，支援: full, departments, users")

        # 執行背景同步
        async def run_background_sync():
            try:
                if sync_type == "departments":
                    result = await sync_service.sync_departments_only()
                elif sync_type == "users":
                    result = await sync_service.sync_users_only()
                elif sync_type == "full":
                    result = await sync_service.sync_full_organization()

                logger.info(f"背景組織同步完成: {result}")
            except Exception as e:
                logger.error(f"背景組織同步異常: {e}")

        background_tasks.add_task(run_background_sync)

        return {
            "success": True,
            "message": f"{sync_type} 組織同步已在背景開始",
            "data": {"sync_type": sync_type, "is_syncing": True},
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"觸發背景組織同步時發生異常: {e}")
        raise HTTPException(status_code=500, detail=f"觸發背景同步失敗: {str(e)}")


@router.post("/sync/background")
async def trigger_organization_sync_background(
    sync_type: str = Query("full", description="同步類型: full, departments, users"),
    background_tasks: BackgroundTasks = None,
):
    """
    觸發背景組織架構同步（無需團隊依賴）

    Args:
        sync_type: 同步類型（full: 完整同步, departments: 僅部門, users: 僅用戶）
        background_tasks: 背景任務管理器

    Returns:
        同步開始確認
    """
    try:
        if not background_tasks:
            raise HTTPException(status_code=400, detail="背景任務不可用")

        # 獲取組織同步服務
        sync_service = get_lark_org_sync_service()

        # 檢查是否已在同步中
        current_status = sync_service.get_sync_status()
        if current_status.get("is_syncing", False):
            return {"success": False, "message": "同步正在進行中，請稍後再試", "data": {"is_syncing": True}}

        # 執行背景同步
        async def run_background_sync():
            try:
                if sync_type == "departments":
                    result = await sync_service.sync_departments_only()
                elif sync_type == "users":
                    result = await sync_service.sync_users_only()
                elif sync_type == "full":
                    result = await sync_service.sync_full_organization()
                else:
                    logger.error(f"無效的同步類型: {sync_type}")
                    return

                logger.info(f"背景組織同步完成: {result}")
            except Exception as e:
                logger.error(f"背景組織同步異常: {e}")

        background_tasks.add_task(run_background_sync)

        return {
            "success": True,
            "message": f"{sync_type} 組織同步已在背景開始",
            "data": {"sync_type": sync_type, "is_syncing": True},
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"觸發背景組織同步時發生異常: {e}")
        raise HTTPException(status_code=500, detail=f"觸發背景同步失敗: {str(e)}")


@router.delete("/cleanup")
async def cleanup_organization_data(days_threshold: int = Query(30, description="清理超過指定天數的舊數據")):
    """
    清理組織架構舊數據

    Args:
        days_threshold: 天數閾值，清理超過此天數的非活躍數據

    Returns:
        清理操作結果
    """
    try:
        sync_service = get_lark_org_sync_service()
        cleanup_result = await sync_service.cleanup_old_data(days_threshold=days_threshold)

        if "error" in cleanup_result:
            raise HTTPException(status_code=500, detail=cleanup_result["error"])

        return {
            "success": True,
            "data": cleanup_result,
            "message": f"清理完成，共清理 {cleanup_result.get('total_cleaned', 0)} 筆舊數據",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"清理組織數據時發生異常: {e}")
        raise HTTPException(status_code=500, detail=f"清理數據失敗: {str(e)}")


@router.get("/scheduled-services")
async def list_scheduled_services(
    current_user: User = Depends(require_super_admin()),
):
    """列出可排程服務與目前執行狀態。"""
    _ = current_user
    try:
        services = await task_scheduler.list_services()
        return {
            "success": True,
            "data": {
                "scheduler_running": task_scheduler.running,
                "services": services,
            },
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("載入排程服務失敗: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "SCHEDULE_SERVICE_LIST_FAILED",
                "message": "載入排程服務失敗",
            },
        ) from exc


@router.put("/scheduled-services/{service_key}")
async def update_scheduled_service(
    service_key: str,
    payload: ScheduledServiceUpdateRequest,
    current_user: User = Depends(require_super_admin()),
):
    """更新可排程服務設定。"""
    _ = current_user
    try:
        service_payload = await task_scheduler.update_service_schedule(
            service_key=service_key,
            enabled=payload.enabled,
            run_at_time=payload.run_at_time,
        )
        return {
            "success": True,
            "data": service_payload,
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("更新排程服務失敗: %s", exc, exc_info=True)
        raise _scheduler_api_error(exc) from exc
