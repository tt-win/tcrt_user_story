"""Org-scoped Automation Provider router (CI / Result).

Per simplify-provider-scope-with-org-level-ci-result change: CI (Jenkins) and
Result (Allure) providers moved from per-team to org-level. This router
exposes CRUD + health-check + discover-runners endpoints under
``/api/system/automation-providers`` and is gated by ``require_super_admin``.

Storage providers stay on the team router (``app.api.automation_providers``).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.automation_providers import collect_runner_labels
from app.audit import ActionType, AuditSeverity, ResourceType, audit_service
from app.auth.dependencies import require_super_admin
from app.db_access.main import MainAccessBoundary, get_main_access_boundary
from app.models.automation_provider import (
    AutomationProviderCreate,
    AutomationProviderHealthResponse,
    AutomationProviderResponse,
    AutomationProviderTypeInfo,
    AutomationProviderUpdate,
    AutomationProviderValidationResponse,
)
from app.models.database_models import (
    AutomationProviderSlot,
    SystemAutomationProvider,
    User,
)
from app.services.automation.provider_credential_service import (
    CredentialEncryptionError,
    decrypt_credentials,
    encrypt_credentials,
    encrypted_credentials_fingerprint,
    merge_credentials,
    normalize_credentials_payload,
)
from app.services.automation.provider_registry import (
    ProviderNotConfiguredError,
    ProviderRegistryError,
    get_active_provider_record,
    instantiate_provider,
    list_provider_type_info,
    validate_provider_payload,
)


logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/system/automation-providers",
    tags=["system-automation-providers"],
    dependencies=[Depends(require_super_admin())],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _provider_to_response(provider: SystemAutomationProvider) -> AutomationProviderResponse:
    config = json.loads(provider.config_json or "{}")
    return AutomationProviderResponse(
        id=provider.id,
        team_id=None,
        provider_slot=provider.provider_slot,
        provider_type=provider.provider_type,
        name=provider.name,
        config=config,
        is_active=provider.is_active,
        credentials_set=bool(provider.credentials_encrypted),
        credentials_fingerprint=encrypted_credentials_fingerprint(provider.credentials_encrypted),
        last_health_check_at=provider.last_health_check_at,
        last_health_status=provider.last_health_status,
        created_by=provider.created_by,
        updated_by=provider.updated_by,
        created_at=provider.created_at,
        updated_at=provider.updated_at,
    )


def _require_ci_or_result_slot(slot: AutomationProviderSlot, provider_type: str) -> None:
    """System router accepts only CI / Result providers; storage stays on
    team router."""
    if slot not in (AutomationProviderSlot.CI, AutomationProviderSlot.RESULT) or not (
        provider_type.startswith("ci:") or provider_type.startswith("result:")
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "WRONG_PROVIDER_SCOPE",
                "message": (
                    "Storage providers are managed per-team. "
                    "Please configure them under each team's Git 來源設定 page."
                ),
            },
        )


def _validate_slot_matches_provider_type(slot: AutomationProviderSlot, provider_type: str) -> None:
    provider_slot = provider_type.split(":", 1)[0] if ":" in provider_type else ""
    if provider_slot != slot.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "PROVIDER_SLOT_MISMATCH",
                "message": f"provider_type {provider_type} does not match slot {slot.value}",
            },
        )


async def _get_provider_row(session: AsyncSession, provider_id: int) -> SystemAutomationProvider:
    result = await session.execute(
        select(SystemAutomationProvider).where(SystemAutomationProvider.id == provider_id)
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "PROVIDER_NOT_FOUND",
                "message": f"System automation provider {provider_id} not found",
            },
        )
    return provider


async def _log_action(
    action_type: ActionType,
    current_user: User,
    provider_id: int,
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
            resource_type=ResourceType.SYSTEM_AUTOMATION_PROVIDER,
            resource_id=str(provider_id),
            team_id=None,
            details=details,
            action_brief=action_brief,
            severity=AuditSeverity.CRITICAL if action_type == ActionType.DELETE else AuditSeverity.INFO,
            ip_address=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent") if request else None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to write system automation provider audit log: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/types", response_model=list[AutomationProviderTypeInfo])
async def get_provider_types() -> list[AutomationProviderTypeInfo]:
    # Only expose CI / Result types here; storage types stay on team router.
    return [
        AutomationProviderTypeInfo(**item)
        for item in list_provider_type_info()
        if str(item.get("provider_type", "")).startswith(("ci:", "result:"))
    ]


@router.post("/validate", response_model=AutomationProviderValidationResponse)
async def validate_provider_config(
    payload: AutomationProviderCreate,
) -> AutomationProviderValidationResponse:
    _require_ci_or_result_slot(payload.provider_slot, payload.provider_type)
    _validate_slot_matches_provider_type(payload.provider_slot, payload.provider_type)
    try:
        validate_provider_payload(payload.provider_type, payload.config, payload.credentials)
    except ProviderRegistryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_PROVIDER_TYPE", "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_PROVIDER_CONFIG", "message": str(exc)},
        ) from exc
    return AutomationProviderValidationResponse(valid=True, message="Provider configuration is valid")


@router.get("", response_model=list[AutomationProviderResponse])
async def list_system_providers(
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> list[AutomationProviderResponse]:
    async def _list(session: AsyncSession) -> list[AutomationProviderResponse]:
        result = await session.execute(
            select(SystemAutomationProvider).order_by(
                SystemAutomationProvider.provider_slot, SystemAutomationProvider.name
            )
        )
        return [_provider_to_response(provider) for provider in result.scalars().all()]

    return await main_boundary.run_read(_list)


@router.post("", response_model=AutomationProviderResponse, status_code=status.HTTP_201_CREATED)
async def create_system_provider(
    payload: AutomationProviderCreate,
    request: Request,
    current_user: User = Depends(require_super_admin()),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationProviderResponse:
    _require_ci_or_result_slot(payload.provider_slot, payload.provider_type)
    _validate_slot_matches_provider_type(payload.provider_slot, payload.provider_type)
    credentials = normalize_credentials_payload(payload.credentials)
    try:
        validate_provider_payload(payload.provider_type, payload.config, credentials)
        encrypted_credentials = encrypt_credentials(credentials)
    except ProviderRegistryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_PROVIDER_TYPE", "message": str(exc)},
        ) from exc
    except CredentialEncryptionError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "CREDENTIAL_ENCRYPTION_UNAVAILABLE", "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_PROVIDER_CONFIG", "message": str(exc)},
        ) from exc

    async def _create(session: AsyncSession) -> AutomationProviderResponse:
        now = datetime.utcnow()
        provider = SystemAutomationProvider(
            provider_slot=payload.provider_slot,
            provider_type=payload.provider_type,
            name=payload.name,
            config_json=json.dumps(payload.config, ensure_ascii=False, sort_keys=True),
            credentials_encrypted=encrypted_credentials,
            is_active=payload.is_active,
            created_by=str(current_user.id),
            updated_by=str(current_user.id),
            created_at=now,
            updated_at=now,
        )
        session.add(provider)
        await session.flush()
        await session.refresh(provider)
        return _provider_to_response(provider)

    try:
        response = await main_boundary.run_write(_create)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "PROVIDER_ALREADY_EXISTS", "message": "Provider name already exists in this slot"},
        ) from exc

    await _log_action(
        ActionType.CREATE,
        current_user,
        response.id,
        f"建立 System Automation Provider: {response.name}",
        {"provider_type": response.provider_type, "provider_slot": response.provider_slot},
        request,
    )
    return response


@router.get("/{provider_id}", response_model=AutomationProviderResponse)
async def get_system_provider(
    provider_id: int,
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationProviderResponse:
    async def _get(session: AsyncSession) -> AutomationProviderResponse:
        provider = await _get_provider_row(session, provider_id)
        return _provider_to_response(provider)

    return await main_boundary.run_read(_get)


@router.put("/{provider_id}", response_model=AutomationProviderResponse)
async def update_system_provider(
    provider_id: int,
    payload: AutomationProviderUpdate,
    request: Request,
    current_user: User = Depends(require_super_admin()),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationProviderResponse:
    async def _update(session: AsyncSession) -> AutomationProviderResponse:
        provider = await _get_provider_row(session, provider_id)
        next_slot = payload.provider_slot or provider.provider_slot
        next_provider_type = payload.provider_type or provider.provider_type
        next_config = payload.config if payload.config is not None else json.loads(provider.config_json or "{}")
        credential_updates = normalize_credentials_payload(payload.credentials)
        if credential_updates is None and payload.clear_credentials:
            next_credentials: dict[str, Any] = {}
        else:
            stored_credentials = decrypt_credentials(provider.credentials_encrypted)
            next_credentials = merge_credentials(stored_credentials, credential_updates)
        validation_credentials = None if payload.clear_credentials and credential_updates is None else next_credentials
        _require_ci_or_result_slot(next_slot, next_provider_type)
        _validate_slot_matches_provider_type(next_slot, next_provider_type)
        validate_provider_payload(next_provider_type, next_config, validation_credentials)

        if credential_updates is not None:
            provider.credentials_encrypted = encrypt_credentials(next_credentials)
        elif payload.clear_credentials:
            provider.credentials_encrypted = None

        provider.provider_slot = next_slot
        provider.provider_type = next_provider_type
        provider.config_json = json.dumps(next_config, ensure_ascii=False, sort_keys=True)
        if payload.name is not None:
            provider.name = payload.name
        if payload.is_active is not None:
            provider.is_active = payload.is_active
        provider.updated_by = str(current_user.id)
        provider.updated_at = datetime.utcnow()
        await session.flush()
        await session.refresh(provider)
        return _provider_to_response(provider)

    try:
        response = await main_boundary.run_write(_update)
    except CredentialEncryptionError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "CREDENTIAL_ENCRYPTION_UNAVAILABLE", "message": str(exc)},
        ) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "PROVIDER_ALREADY_EXISTS", "message": "Provider name already exists in this slot"},
        ) from exc
    except ProviderRegistryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_PROVIDER_TYPE", "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_PROVIDER_CONFIG", "message": str(exc)},
        ) from exc

    await _log_action(
        ActionType.UPDATE,
        current_user,
        response.id,
        f"更新 System Automation Provider: {response.name}",
        {"provider_type": response.provider_type, "provider_slot": response.provider_slot},
        request,
    )
    return response


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_system_provider(
    provider_id: int,
    request: Request,
    current_user: User = Depends(require_super_admin()),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> Response:
    async def _delete(session: AsyncSession) -> str:
        provider = await _get_provider_row(session, provider_id)
        provider_name = provider.name
        await session.delete(provider)
        return provider_name

    provider_name = await main_boundary.run_write(_delete)
    await _log_action(
        ActionType.DELETE,
        current_user,
        provider_id,
        f"刪除 System Automation Provider: {provider_name}",
        {"provider_name": provider_name},
        request,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{provider_id}/test-connection", response_model=AutomationProviderHealthResponse)
async def test_system_provider_connection(
    provider_id: int,
    request: Request,
    current_user: User = Depends(require_super_admin()),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationProviderHealthResponse:
    async def _load(session: AsyncSession) -> tuple[str, dict[str, Any], str | None]:
        provider = await _get_provider_row(session, provider_id)
        return provider.provider_type, json.loads(provider.config_json or "{}"), provider.credentials_encrypted

    provider_type, config, credentials_encrypted = await main_boundary.run_read(_load)

    try:
        provider_instance = instantiate_provider(provider_type, config, decrypt_credentials(credentials_encrypted))
        health = await provider_instance.health_check()
    except CredentialEncryptionError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "CREDENTIAL_DECRYPTION_UNAVAILABLE", "message": str(exc)},
        ) from exc
    except Exception as exc:  # noqa: BLE001
        health = type("HealthFailure", (), {"status": "FAILED", "message": str(exc), "details": {}})()

    checked_at = datetime.utcnow()

    async def _update_status(session: AsyncSession) -> None:
        provider = await _get_provider_row(session, provider_id)
        provider.last_health_check_at = checked_at
        provider.last_health_status = health.status
        provider.updated_at = checked_at

    await main_boundary.run_write(_update_status)
    await _log_action(
        ActionType.READ,
        current_user,
        provider_id,
        f"測試 System Automation Provider 連線: {provider_id}",
        {"status": health.status, "message": health.message},
        request,
    )
    return AutomationProviderHealthResponse(
        status=health.status,
        message=health.message,
        details=getattr(health, "details", None) or {},
        checked_at=checked_at,
    )


@router.post("/test-config", response_model=AutomationProviderHealthResponse)
async def test_unsaved_system_provider_config(
    payload: AutomationProviderCreate,
) -> AutomationProviderHealthResponse:
    """Run health_check against an UNSAVED system provider payload."""
    _require_ci_or_result_slot(payload.provider_slot, payload.provider_type)
    try:
        validate_provider_payload(payload.provider_type, payload.config, payload.credentials)
    except ProviderRegistryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_PROVIDER_TYPE", "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_PROVIDER_CONFIG", "message": str(exc)},
        ) from exc

    try:
        instance = instantiate_provider(
            payload.provider_type, payload.config, payload.credentials or {}
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "TEST_CONFIG_INSTANTIATE_FAILED",
                "message": f"Failed to build provider instance: {exc}",
            },
        ) from exc

    try:
        health = await instance.health_check()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ad-hoc health_check failed for %s: %s", payload.provider_type, exc)
        health = type("HealthFailure", (), {"status": "FAILED", "message": str(exc), "details": {}})()

    return AutomationProviderHealthResponse(
        status=health.status,
        message=health.message,
        details=getattr(health, "details", None) or {},
        checked_at=datetime.utcnow(),
    )


@router.post("/{provider_id}/discover-runners")
async def discover_runners_for_saved_system_provider(
    provider_id: int,
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> dict[str, Any]:
    """Discover runners against a SAVED CI provider using its stored credentials.

    The edit/Add modal never echoes credentials back to the client (security),
    so when a user re-opens an existing CI provider to discover runners, the
    `credentials` form fields are empty. This endpoint accepts the saved row's
    id and reuses the encrypted credentials in DB instead of needing the
    client to re-type them.
    """
    async def _load(session: AsyncSession) -> tuple[str, dict[str, Any], str | None]:
        provider = await _get_provider_row(session, provider_id)
        if not provider.provider_type.startswith("ci:"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "DISCOVER_RUNNERS_NOT_CI",
                    "message": f"Provider {provider_id} is not a CI provider",
                },
            )
        return provider.provider_type, json.loads(provider.config_json or "{}"), provider.credentials_encrypted

    provider_type, config, credentials_encrypted = await main_boundary.run_read(_load)

    try:
        instance = instantiate_provider(
            provider_type, config, decrypt_credentials(credentials_encrypted)
        )
    except CredentialEncryptionError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "CREDENTIAL_DECRYPTION_UNAVAILABLE", "message": str(exc)},
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "DISCOVER_RUNNERS_INSTANTIATE_FAILED",
                "message": f"Failed to build provider instance: {exc}",
            },
        ) from exc

    try:
        runners = await instance.list_runners()
    except Exception as exc:  # noqa: BLE001
        logger.warning("list_runners failed for saved provider %s: %s", provider_id, exc)
        return {
            "configured": True,
            "provider_id": provider_id,
            "provider_type": provider_type,
            "default_runner_label": config.get("default_runner_label"),
            "labels": [],
            "runners": [],
            "error": str(exc),
        }

    default_label = config.get("default_runner_label")
    runner_dicts, labels = collect_runner_labels(runners, default_label)
    return {
        "configured": True,
        "provider_id": provider_id,
        "provider_type": provider_type,
        "default_runner_label": default_label,
        "labels": labels,
        "runners": runner_dicts,
    }


@router.post("/discover-runners")
async def discover_runners_for_unsaved_system_provider(
    payload: AutomationProviderCreate,
) -> dict[str, Any]:
    """Discover runners against an UNSAVED CI provider payload."""
    if not payload.provider_type.startswith("ci:"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "DISCOVER_RUNNERS_NOT_CI",
                "message": f"Runner discovery is only available for CI providers, not {payload.provider_type}",
            },
        )
    try:
        validate_provider_payload(payload.provider_type, payload.config, payload.credentials)
    except ProviderRegistryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_PROVIDER_TYPE", "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_PROVIDER_CONFIG", "message": str(exc)},
        ) from exc

    try:
        instance = instantiate_provider(
            payload.provider_type, payload.config, payload.credentials or {}
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "DISCOVER_RUNNERS_INSTANTIATE_FAILED",
                "message": f"Failed to build provider instance: {exc}",
            },
        ) from exc

    try:
        runners = await instance.list_runners()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ad-hoc list_runners failed for %s: %s", payload.provider_type, exc)
        return {
            "configured": True,
            "provider_type": payload.provider_type,
            "default_runner_label": (payload.config or {}).get("default_runner_label"),
            "labels": [],
            "runners": [],
            "error": str(exc),
        }

    default_label = (payload.config or {}).get("default_runner_label")
    runner_dicts, labels = collect_runner_labels(runners, default_label)

    return {
        "configured": True,
        "provider_type": payload.provider_type,
        "default_runner_label": default_label,
        "labels": labels,
        "runners": runner_dicts,
    }


@router.get("/active-ci/runners")
async def list_active_ci_runners(
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> dict[str, Any]:
    """List runners/agents on the active org-level CI provider."""
    async def _load(session: AsyncSession) -> dict[str, Any]:
        try:
            provider_record = await get_active_provider_record(
                team_id=0,  # ignored for system-scoped slots
                slot=AutomationProviderSlot.CI,
                session=session,
            )
        except ProviderNotConfiguredError:
            return {
                "configured": False,
                "provider_id": None,
                "provider_type": None,
                "default_runner_label": None,
                "labels": [],
                "runners": [],
            }
        config = json.loads(provider_record.config_json or "{}")
        try:
            instance = instantiate_provider(
                provider_record.provider_type,
                config,
                decrypt_credentials(provider_record.credentials_encrypted),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to instantiate CI provider for runner listing: %s", exc)
            return {
                "configured": True,
                "provider_id": provider_record.id,
                "provider_type": provider_record.provider_type,
                "default_runner_label": config.get("default_runner_label"),
                "labels": [],
                "runners": [],
                "error": str(exc),
            }
        try:
            runners = await instance.list_runners()
        except Exception as exc:  # noqa: BLE001
            logger.warning("list_runners failed: %s", exc)
            return {
                "configured": True,
                "provider_id": provider_record.id,
                "provider_type": provider_record.provider_type,
                "default_runner_label": config.get("default_runner_label"),
                "labels": [],
                "runners": [],
                "error": str(exc),
            }

        default_label = config.get("default_runner_label")
        runner_dicts, labels = collect_runner_labels(runners, default_label)
        return {
            "configured": True,
            "provider_id": provider_record.id,
            "provider_type": provider_record.provider_type,
            "default_runner_label": default_label,
            "labels": labels,
            "runners": runner_dicts,
        }

    return await main_boundary.run_read(_load)

