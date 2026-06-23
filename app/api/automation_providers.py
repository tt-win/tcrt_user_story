from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import ActionType, AuditSeverity, ResourceType, audit_service
from app.db_access.main import MainAccessBoundary, get_main_access_boundary
from app.models.automation_provider import (
    AutomationProviderCreate,
    AutomationProviderHealthResponse,
    AutomationProviderResponse,
    AutomationProviderTypeInfo,
    AutomationProviderUpdate,
    AutomationProviderValidationResponse,
)
from app.models.database_models import AutomationProviderSlot, Team, TeamAutomationProvider, User
from app.services.automation.provider_credential_service import (
    CredentialEncryptionError,
    decrypt_credentials,
    encrypted_credentials_fingerprint,
    encrypt_credentials,
    merge_credentials,
    normalize_credentials_payload,
)
from app.services.automation.provider_registry import (
    ProviderRegistryError,
    instantiate_provider,
    list_provider_type_info,
    validate_provider_payload,
)
from app.auth.dependencies import get_current_user


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/teams/{team_id}/automation-providers", tags=["automation-providers"])


async def require_team_admin(
    team_id: int,
    current_user: User = Depends(get_current_user),
) -> User:
    """Storage provider config holds encrypted GitHub PATs / SSH keys etc.
    Git source settings are team-scoped, so Admin and Super Admin may manage
    them. CI / Result providers remain org-scoped on the system router."""
    from app.auth.models import UserRole

    user_role = current_user.role
    role_value = user_role.value if hasattr(user_role, "value") else str(user_role)
    allowed_roles = {UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value}
    if role_value.lower() not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "INSUFFICIENT_PERMISSION",
                "message": "Git 來源設定僅 Admin 以上可管理",
            },
        )
    return current_user


async def _ensure_team_exists(session: AsyncSession, team_id: int) -> None:
    result = await session.execute(select(Team.id).where(Team.id == team_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TEAM_NOT_FOUND", "message": f"Team {team_id} not found"},
        )


def _normalize_storage_config_for_response(provider_type: str, config: Any) -> Any:
    """Fold a legacy single-repo GitHub config (top-level owner/repo) into a
    `repos` list so the schema-driven edit form pre-fills it. Keeps every other
    key (e.g. smart_scan) intact — unlike model_dump, which would drop extras."""
    if (
        provider_type == "storage:github"
        and isinstance(config, dict)
        and not config.get("repos")
        and config.get("owner")
        and config.get("repo")
    ):
        return {**config, "repos": [{"owner": config["owner"], "repo": config["repo"]}]}
    return config


def _provider_to_response(provider: TeamAutomationProvider) -> AutomationProviderResponse:
    config = _normalize_storage_config_for_response(
        provider.provider_type, json.loads(provider.config_json or "{}")
    )
    return AutomationProviderResponse(
        id=provider.id,
        team_id=provider.team_id,
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


def _require_storage_slot(slot: AutomationProviderSlot, provider_type: str) -> None:
    """Team-scoped router only accepts storage providers; CI/Result moved to
    the org-level system router (see app.api.system_automation_providers).
    Reject any attempt to create / update non-storage rows here so the DB
    CHECK constraint never gets hit at the app boundary."""
    if slot != AutomationProviderSlot.STORAGE or not provider_type.startswith("storage:"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "WRONG_PROVIDER_SCOPE",
                "message": (
                    "CI / Result providers are managed at org level. "
                    "Please ask a Super Admin to configure them in Team Management "
                    "→ 同步組織架構 → Org Automation Infra."
                ),
            },
        )


async def _log_provider_action(
    action_type: ActionType,
    current_user: User,
    team_id: int,
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
            resource_type=ResourceType.AUTOMATION_PROVIDER,
            resource_id=str(provider_id),
            team_id=team_id,
            details=details,
            action_brief=action_brief,
            severity=AuditSeverity.CRITICAL if action_type == ActionType.DELETE else AuditSeverity.INFO,
            ip_address=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent") if request else None,
        )
    except Exception as exc:
        logger.warning("Failed to write automation provider audit log: %s", exc, exc_info=True)


@router.get("/types", response_model=list[AutomationProviderTypeInfo])
async def get_provider_types(
    current_user: User = Depends(get_current_user),
) -> list[AutomationProviderTypeInfo]:
    # Team router exposes only storage provider types; CI / Result are
    # managed on the system router (require_super_admin).
    return [
        AutomationProviderTypeInfo(**item)
        for item in list_provider_type_info()
        if str(item.get("provider_type", "")).startswith("storage:")
    ]


@router.post("/validate", response_model=AutomationProviderValidationResponse)
async def validate_provider_config(
    team_id: int,
    payload: AutomationProviderCreate,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationProviderValidationResponse:
    async def _validate(session: AsyncSession) -> None:
        await _ensure_team_exists(session, team_id)

    await main_boundary.run_read(_validate)
    _require_storage_slot(payload.provider_slot, payload.provider_type)
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
async def list_automation_providers(
    team_id: int,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> list[AutomationProviderResponse]:
    async def _list(session: AsyncSession) -> list[AutomationProviderResponse]:
        await _ensure_team_exists(session, team_id)
        result = await session.execute(
            select(TeamAutomationProvider)
            .where(TeamAutomationProvider.team_id == team_id)
            .order_by(TeamAutomationProvider.provider_slot, TeamAutomationProvider.name)
        )
        return [_provider_to_response(provider) for provider in result.scalars().all()]

    return await main_boundary.run_read(_list)


@router.post("", response_model=AutomationProviderResponse, status_code=status.HTTP_201_CREATED)
async def create_automation_provider(
    team_id: int,
    payload: AutomationProviderCreate,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationProviderResponse:
    _require_storage_slot(payload.provider_slot, payload.provider_type)
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
        await _ensure_team_exists(session, team_id)
        now = datetime.utcnow()
        provider = TeamAutomationProvider(
            team_id=team_id,
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

    await _log_provider_action(
        ActionType.CREATE,
        current_user,
        team_id,
        response.id,
        f"建立 Automation Provider: {response.name}",
        {"provider_type": response.provider_type, "provider_slot": response.provider_slot},
        request,
    )
    return response


@router.get("/{provider_id}", response_model=AutomationProviderResponse)
async def get_automation_provider(
    team_id: int,
    provider_id: int,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationProviderResponse:
    async def _get(session: AsyncSession) -> AutomationProviderResponse:
        provider = await _get_provider_row(session, team_id, provider_id)
        return _provider_to_response(provider)

    return await main_boundary.run_read(_get)


@router.put("/{provider_id}", response_model=AutomationProviderResponse)
async def update_automation_provider(
    team_id: int,
    provider_id: int,
    payload: AutomationProviderUpdate,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationProviderResponse:
    async def _update(session: AsyncSession) -> AutomationProviderResponse:
        provider = await _get_provider_row(session, team_id, provider_id)
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
        _require_storage_slot(next_slot, next_provider_type)
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

    await _log_provider_action(
        ActionType.UPDATE,
        current_user,
        team_id,
        response.id,
        f"更新 Automation Provider: {response.name}",
        {"provider_type": response.provider_type, "provider_slot": response.provider_slot},
        request,
    )
    return response


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_automation_provider(
    team_id: int,
    provider_id: int,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> Response:
    async def _delete(session: AsyncSession) -> str:
        provider = await _get_provider_row(session, team_id, provider_id)
        provider_name = provider.name
        await session.delete(provider)
        return provider_name

    provider_name = await main_boundary.run_write(_delete)
    await _log_provider_action(
        ActionType.DELETE,
        current_user,
        team_id,
        provider_id,
        f"刪除 Automation Provider: {provider_name}",
        {"provider_name": provider_name},
        request,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{provider_id}/test-connection", response_model=AutomationProviderHealthResponse)
async def test_automation_provider_connection(
    team_id: int,
    provider_id: int,
    request: Request,
    current_user: User = Depends(require_team_admin),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationProviderHealthResponse:
    async def _load_and_mark_running(session: AsyncSession) -> tuple[str, dict[str, Any], str | None]:
        provider = await _get_provider_row(session, team_id, provider_id)
        return provider.provider_type, json.loads(provider.config_json or "{}"), provider.credentials_encrypted

    provider_type, config, credentials_encrypted = await main_boundary.run_read(_load_and_mark_running)

    try:
        provider_instance = instantiate_provider(provider_type, config, decrypt_credentials(credentials_encrypted))
        health = await provider_instance.health_check()
    except CredentialEncryptionError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "CREDENTIAL_DECRYPTION_UNAVAILABLE", "message": str(exc)},
        ) from exc
    except Exception as exc:
        health = type("HealthFailure", (), {"status": "FAILED", "message": str(exc), "details": {}})()

    checked_at = datetime.utcnow()

    async def _update_status(session: AsyncSession) -> None:
        provider = await _get_provider_row(session, team_id, provider_id)
        provider.last_health_check_at = checked_at
        provider.last_health_status = health.status
        provider.updated_at = checked_at

    await main_boundary.run_write(_update_status)
    await _log_provider_action(
        ActionType.READ,
        current_user,
        team_id,
        provider_id,
        f"測試 Automation Provider 連線: {provider_id}",
        {"status": health.status, "message": health.message},
        request,
    )
    return AutomationProviderHealthResponse(
        status=health.status,
        message=health.message,
        details=health.details,
        checked_at=checked_at,
    )


@router.post("/test-config", response_model=AutomationProviderHealthResponse)
async def test_unsaved_provider_config(
    team_id: int,
    payload: AutomationProviderCreate,
    current_user: User = Depends(require_team_admin),
) -> AutomationProviderHealthResponse:
    """Run health_check against an UNSAVED provider payload.

    Used by the Add/Edit modal so the user can verify config + credentials
    before persisting. Validates schema, instantiates a transient provider
    in-memory, calls health_check(), returns the same response shape as
    the saved-provider `POST /{id}/test-connection` endpoint. No DB write.
    """
    _require_storage_slot(payload.provider_slot, payload.provider_type)
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
        logger.warning(
            "Ad-hoc health_check failed for %s (team %s): %s",
            payload.provider_type, team_id, exc,
        )
        health = type("HealthFailure", (), {"status": "FAILED", "message": str(exc), "details": {}})()

    return AutomationProviderHealthResponse(
        status=health.status,
        message=health.message,
        details=getattr(health, "details", None) or {},
        checked_at=datetime.utcnow(),
    )


# Note: /discover-runners and /active-ci/runners moved to the system router
# (app.api.system_automation_providers) since CI providers are now org-scoped.


_JENKINS_BUILTIN_NOISE_LABELS = {"built-in", "master"}


def collect_runner_labels(
    runners,
    default_label: str | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Public alias for :func:`_collect_runner_labels` so the system router
    (and tests) can import it without reaching into a private name."""
    return _collect_runner_labels(runners, default_label)


def _collect_runner_labels(
    runners,
    default_label: str | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Flatten runner objects → unique, human-facing label list.

    Show what humans see in the CI UI:
    - The runner's `name` (displayName) is the primary label — that's what
      operators recognise from Jenkins / GH Actions consoles.
    - Custom `assignedLabels` are surfaced too (so a "linux" agent tag can be
      picked).
    - Jenkins hardcoded canonical slugs for the built-in node (`built-in`,
      legacy `master`) are dropped — they're internal aliases for what the user
      already sees as "Built-In Node".
    - Self-aliases that mirror the displayName are deduped.
    - Final list is sorted case-insensitively.
    """
    runner_dicts: list[dict[str, Any]] = []
    seen_lower: set[str] = set()
    labels: list[str] = []
    for runner in runners:
        data = runner.model_dump() if hasattr(runner, "model_dump") else dict(runner.__dict__)
        runner_dicts.append(data)
        runner_name = (data.get("name") or "").strip()
        # Use the displayName as the primary user-facing label for this node.
        if runner_name and runner_name.lower() not in seen_lower:
            seen_lower.add(runner_name.lower())
            labels.append(runner_name)
        is_jenkins_builtin = "built-in" in runner_name.lower() or "built_in" in runner_name.lower()
        for raw in data.get("labels") or []:
            cleaned = str(raw).strip()
            if not cleaned:
                continue
            # Drop the Jenkins-hardcoded canonical slug for the built-in node
            # (it routes the same job as displayName but is meant for humans).
            if is_jenkins_builtin and cleaned.lower() in _JENKINS_BUILTIN_NOISE_LABELS:
                continue
            key = cleaned.lower()
            if key in seen_lower:
                continue
            seen_lower.add(key)
            labels.append(cleaned)
    if default_label:
        cleaned = str(default_label).strip()
        if cleaned and cleaned.lower() not in seen_lower:
            seen_lower.add(cleaned.lower())
            labels.append(cleaned)
    labels.sort(key=lambda s: s.lower())
    return runner_dicts, labels


async def _get_provider_row(
    session: AsyncSession,
    team_id: int,
    provider_id: int,
) -> TeamAutomationProvider:
    result = await session.execute(
        select(TeamAutomationProvider).where(
            TeamAutomationProvider.id == provider_id,
            TeamAutomationProvider.team_id == team_id,
        )
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PROVIDER_NOT_FOUND", "message": f"Provider {provider_id} not found"},
        )
    return provider
