from __future__ import annotations

import json
from typing import Any, TypeAlias

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_access.main import get_main_access_boundary
from app.models.database_models import (
    AutomationProviderSlot,
    SystemAutomationProvider,
    TeamAutomationProvider,
)
from app.services.automation.provider_credential_service import decrypt_credentials
from app.services.automation.providers.allure_result import AllureResultProvider
from app.services.automation.providers.base import CIProvider, ResultProvider, StorageProvider
from app.services.automation.providers.github_actions_ci import GitHubActionsCIProvider
from app.services.automation.providers.github_storage import GitHubStorageProvider
from app.services.automation.providers.jenkins_ci import JenkinsCIProvider
from app.services.automation.providers.local_git_storage import LocalGitStorageProvider


ProviderInstance: TypeAlias = StorageProvider | CIProvider | ResultProvider
ProviderClass: TypeAlias = type[StorageProvider] | type[CIProvider] | type[ResultProvider]


class ProviderRegistryError(ValueError):
    """Raised for invalid provider lookup or configuration."""


class ProviderNotConfiguredError(ProviderRegistryError):
    def __init__(self, team_id: int, slot: AutomationProviderSlot) -> None:
        self.team_id = team_id
        self.slot = slot
        super().__init__(f"Provider slot {slot.value} is not configured for team {team_id}")


PROVIDER_CLASSES: dict[str, ProviderClass] = {
    "storage:github": GitHubStorageProvider,
    "storage:local_git": LocalGitStorageProvider,
    "ci:github_actions": GitHubActionsCIProvider,
    "ci:jenkins": JenkinsCIProvider,
    "result:allure": AllureResultProvider,
}


def normalize_slot(slot: AutomationProviderSlot | str) -> AutomationProviderSlot:
    if isinstance(slot, AutomationProviderSlot):
        return slot
    try:
        return AutomationProviderSlot(slot.lower())
    except ValueError as exc:
        raise ProviderRegistryError(f"Unknown provider slot: {slot}") from exc


def get_provider_class(provider_type: str) -> ProviderClass:
    provider_class = PROVIDER_CLASSES.get(provider_type)
    if provider_class is None:
        available = ", ".join(sorted(PROVIDER_CLASSES))
        raise ProviderRegistryError(
            f"Unknown provider_type '{provider_type}'. Available provider types: {available}"
        )
    return provider_class


def list_provider_type_info() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for provider_type, provider_class in sorted(PROVIDER_CLASSES.items()):
        slot_value, _ = provider_type.split(":", 1)
        items.append(
            {
                "provider_type": provider_type,
                "provider_slot": slot_value,
                "display_name": getattr(provider_class, "display_name", provider_type),
                "config_schema": provider_class.config_schema().model_json_schema(),
                "credential_schema": provider_class.credential_schema().model_json_schema(),
            }
        )
    return items


def validate_provider_payload(provider_type: str, config: dict[str, Any], credentials: dict[str, Any] | None) -> None:
    provider_class = get_provider_class(provider_type)
    provider_class.config_schema().model_validate(config)
    if credentials:
        provider_class.credential_schema().model_validate(credentials)


def instantiate_provider(provider_type: str, config: dict[str, Any], credentials: dict[str, Any] | None = None) -> ProviderInstance:
    provider_class = get_provider_class(provider_type)
    return provider_class(config=config, credentials=credentials or {})  # type: ignore[call-arg]


def is_system_scoped_slot(slot: AutomationProviderSlot | str) -> bool:
    """Return True if this slot is managed at org-level (CI / Result).

    Storage is per-team; CI and Result are org-scoped (Super Admin manages a
    single shared config). Used by callers needing to distinguish audit
    resource type, lookup table, or UI entry point.
    """
    return normalize_slot(slot) in {AutomationProviderSlot.CI, AutomationProviderSlot.RESULT}


async def get_active_provider_record(
    team_id: int,
    slot: AutomationProviderSlot | str,
    session: AsyncSession,
) -> TeamAutomationProvider | SystemAutomationProvider:
    """Return the active provider record for a slot.

    Dispatches by slot scope:
    - STORAGE → query ``team_automation_providers`` filtered by ``team_id``.
    - CI / RESULT → query ``system_automation_providers`` (``team_id`` is
      accepted for backward-compatible signature but ignored).

    Raises ``ProviderNotConfiguredError`` when no active row exists.
    """
    normalized_slot = normalize_slot(slot)
    if is_system_scoped_slot(normalized_slot):
        result = await session.execute(
            select(SystemAutomationProvider)
            .where(
                SystemAutomationProvider.provider_slot == normalized_slot,
                SystemAutomationProvider.is_active.is_(True),
            )
            .order_by(desc(SystemAutomationProvider.updated_at), desc(SystemAutomationProvider.id))
            .limit(1)
        )
        provider = result.scalar_one_or_none()
        if provider is None:
            raise ProviderNotConfiguredError(team_id, normalized_slot)
        return provider

    result = await session.execute(
        select(TeamAutomationProvider)
        .where(
            TeamAutomationProvider.team_id == team_id,
            TeamAutomationProvider.provider_slot == normalized_slot,
            TeamAutomationProvider.is_active.is_(True),
        )
        .order_by(desc(TeamAutomationProvider.updated_at), desc(TeamAutomationProvider.id))
        .limit(1)
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        raise ProviderNotConfiguredError(team_id, normalized_slot)
    return provider


async def get_provider(
    team_id: int,
    slot: AutomationProviderSlot | str,
    session: AsyncSession | None = None,
) -> ProviderInstance:
    async def _load(current_session: AsyncSession) -> ProviderInstance:
        provider = await get_active_provider_record(team_id, slot, current_session)
        config = json.loads(provider.config_json or "{}")
        credentials = decrypt_credentials(provider.credentials_encrypted)
        return instantiate_provider(provider.provider_type, config, credentials)

    if session is not None:
        return await _load(session)

    boundary = get_main_access_boundary()
    return await boundary.run_read(_load)
