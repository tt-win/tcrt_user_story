"""Event catalog for TCRT observability.

This module provides the event catalog that defines all valid event codes,
their schemas, and metadata for both audit and ops events.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel

from .enums import Impact, OpLevel, Outcome
from .schemas import (
    # Audit schemas
    TokenRotateDetails,
    TokenRevokeDetails,
    MCPDenyDetails,
    AppTokenDenyDetails,
    TeamChangeDetails,
    UserChangeDetails,
    PermissionChangeDetails,
    TestCaseChangeDetails,
    TestRunChangeDetails,
    ProviderConfigDetails,
    ProviderCredsDetails,
    ScriptChangeDetails,
    WebhookChangeDetails,
    ConfigChangeDetails,
    AuditGenericDetails,
    # Ops schemas
    RunCancelDetails,
    RunSyncDetails,
    RunReconcileDetails,
    ResultProviderInstantiateDetails,
    CIArtifactDownloadDetails,
    AllureProxySkipDetails,
    AllureProxyUploadDetails,
    ResultProviderReportURLDetails,
)


@dataclass(frozen=True)
class EventDef:
    """Definition of an event in the catalog."""
    event_code: str
    domain: str  # "audit" or "ops"
    write_audit: bool
    write_ops: bool
    default_impact: Optional[Impact] = None
    ops_level_by_outcome: dict[Outcome, OpLevel] = field(default_factory=dict)
    details_schema: type[BaseModel] = AuditGenericDetails
    brief_template: str = ""

    def validate_ops_outcome(self, outcome: Outcome) -> None:
        """Validate that outcome is allowed for ops events."""
        if self.write_ops and self.ops_level_by_outcome:
            if outcome not in self.ops_level_by_outcome:
                raise ValueError(
                    f"Event {self.event_code} does not support outcome {outcome.value} "
                    f"(allowed: {[o.value for o in self.ops_level_by_outcome]})"
                )

    def get_ops_level(self, outcome: Outcome) -> Optional[OpLevel]:
        """Get ops log level for outcome."""
        return self.ops_level_by_outcome.get(outcome)


class EventCatalog:
    """Thread-safe event catalog for TCRT observability events."""
    
    def __init__(self) -> None:
        self._events: dict[str, EventDef] = {}
        self._lock = threading.RLock()
        self._register_mvp_events()
    
    def _register_mvp_events(self) -> None:
        """Register all MVP events from the spec."""
        # Audit events
        audit_events = [
            EventDef(
                event_code="tcrt.audit.auth.token_rotate",
                domain="audit",
                write_audit=True,
                write_ops=False,
                default_impact=Impact.PRIVILEGED,
                details_schema=TokenRotateDetails,
                brief_template="App token rotated by {actor}",
            ),
            EventDef(
                event_code="tcrt.audit.auth.token_revoke",
                domain="audit",
                write_audit=True,
                write_ops=False,
                default_impact=Impact.PRIVILEGED,
                details_schema=TokenRevokeDetails,
                brief_template="App token revoked by {actor}",
            ),
            EventDef(
                event_code="tcrt.audit.auth.mcp_deny",
                domain="audit",
                write_audit=True,
                write_ops=False,
                default_impact=Impact.SENSITIVE,
                details_schema=MCPDenyDetails,
                brief_template="MCP access denied for {resource}",
            ),
            EventDef(
                event_code="tcrt.audit.auth.app_token_deny",
                domain="audit",
                write_audit=True,
                write_ops=False,
                default_impact=Impact.SENSITIVE,
                details_schema=AppTokenDenyDetails,
                brief_template="App token access denied for {resource}",
            ),
            EventDef(
                event_code="tcrt.audit.team.create",
                domain="audit",
                write_audit=True,
                write_ops=False,
                default_impact=Impact.SENSITIVE,
                details_schema=TeamChangeDetails,
                brief_template="Team created: {team_name}",
            ),
            EventDef(
                event_code="tcrt.audit.team.update",
                domain="audit",
                write_audit=True,
                write_ops=False,
                default_impact=Impact.SENSITIVE,
                details_schema=TeamChangeDetails,
                brief_template="Team updated: {team_name}",
            ),
            EventDef(
                event_code="tcrt.audit.team.delete",
                domain="audit",
                write_audit=True,
                write_ops=False,
                default_impact=Impact.PRIVILEGED,
                details_schema=TeamChangeDetails,
                brief_template="Team deleted: {team_name}",
            ),
            EventDef(
                event_code="tcrt.audit.user.create",
                domain="audit",
                write_audit=True,
                write_ops=False,
                default_impact=Impact.SENSITIVE,
                details_schema=UserChangeDetails,
                brief_template="User created: {username}",
            ),
            EventDef(
                event_code="tcrt.audit.user.update",
                domain="audit",
                write_audit=True,
                write_ops=False,
                default_impact=Impact.SENSITIVE,
                details_schema=UserChangeDetails,
                brief_template="User updated: {username}",
            ),
            EventDef(
                event_code="tcrt.audit.user.delete",
                domain="audit",
                write_audit=True,
                write_ops=False,
                default_impact=Impact.PRIVILEGED,
                details_schema=UserChangeDetails,
                brief_template="User deleted: {username}",
            ),
            EventDef(
                event_code="tcrt.audit.permission.grant",
                domain="audit",
                write_audit=True,
                write_ops=False,
                default_impact=Impact.SENSITIVE,
                details_schema=PermissionChangeDetails,
                brief_template="Permission granted: {permission} to {target}",
            ),
            EventDef(
                event_code="tcrt.audit.permission.revoke",
                domain="audit",
                write_audit=True,
                write_ops=False,
                default_impact=Impact.SENSITIVE,
                details_schema=PermissionChangeDetails,
                brief_template="Permission revoked: {permission} from {target}",
            ),
            EventDef(
                event_code="tcrt.audit.test_case.create",
                domain="audit",
                write_audit=True,
                write_ops=False,
                default_impact=Impact.ROUTINE,
                details_schema=TestCaseChangeDetails,
                brief_template="Test case created: {id}",
            ),
            EventDef(
                event_code="tcrt.audit.test_case.update",
                domain="audit",
                write_audit=True,
                write_ops=False,
                default_impact=Impact.ROUTINE,
                details_schema=TestCaseChangeDetails,
                brief_template="Test case updated: {id}",
            ),
            EventDef(
                event_code="tcrt.audit.test_case.delete",
                domain="audit",
                write_audit=True,
                write_ops=False,
                default_impact=Impact.NOTABLE,
                details_schema=TestCaseChangeDetails,
                brief_template="Test case deleted: {id}",
            ),
            EventDef(
                event_code="tcrt.audit.test_run.create",
                domain="audit",
                write_audit=True,
                write_ops=False,
                default_impact=Impact.ROUTINE,
                details_schema=TestRunChangeDetails,
                brief_template="Test run created: {id}",
            ),
            EventDef(
                event_code="tcrt.audit.test_run.update",
                domain="audit",
                write_audit=True,
                write_ops=False,
                default_impact=Impact.ROUTINE,
                details_schema=TestRunChangeDetails,
                brief_template="Test run updated: {id}",
            ),
            EventDef(
                event_code="tcrt.audit.test_run.delete",
                domain="audit",
                write_audit=True,
                write_ops=False,
                default_impact=Impact.NOTABLE,
                details_schema=TestRunChangeDetails,
                brief_template="Test run deleted: {id}",
            ),
            EventDef(
                event_code="tcrt.audit.automation.provider.configure",
                domain="audit",
                write_audit=True,
                write_ops=False,
                default_impact=Impact.SENSITIVE,
                details_schema=ProviderConfigDetails,
                brief_template="Automation provider configured: {type}",
            ),
            EventDef(
                event_code="tcrt.audit.automation.provider.rotate_creds",
                domain="audit",
                write_audit=True,
                write_ops=False,
                default_impact=Impact.PRIVILEGED,
                details_schema=ProviderCredsDetails,
                brief_template="Automation provider credentials rotated: {type}",
            ),
            EventDef(
                event_code="tcrt.audit.automation.script.create",
                domain="audit",
                write_audit=True,
                write_ops=False,
                default_impact=Impact.ROUTINE,
                details_schema=ScriptChangeDetails,
                brief_template="Automation script created: {id}",
            ),
            EventDef(
                event_code="tcrt.audit.automation.script.update",
                domain="audit",
                write_audit=True,
                write_ops=False,
                default_impact=Impact.ROUTINE,
                details_schema=ScriptChangeDetails,
                brief_template="Automation script updated: {id}",
            ),
            EventDef(
                event_code="tcrt.audit.automation.script.delete",
                domain="audit",
                write_audit=True,
                write_ops=False,
                default_impact=Impact.NOTABLE,
                details_schema=ScriptChangeDetails,
                brief_template="Automation script deleted: {id}",
            ),
            EventDef(
                event_code="tcrt.audit.automation.webhook.create",
                domain="audit",
                write_audit=True,
                write_ops=False,
                default_impact=Impact.SENSITIVE,
                details_schema=WebhookChangeDetails,
                brief_template="Automation webhook created: {id}",
            ),
            EventDef(
                event_code="tcrt.audit.automation.webhook.delete",
                domain="audit",
                write_audit=True,
                write_ops=False,
                default_impact=Impact.PRIVILEGED,
                details_schema=WebhookChangeDetails,
                brief_template="Automation webhook deleted: {id}",
            ),
            EventDef(
                event_code="tcrt.audit.system.config_change",
                domain="audit",
                write_audit=True,
                write_ops=False,
                default_impact=Impact.SENSITIVE,
                details_schema=ConfigChangeDetails,
                brief_template="System config changed: {key}",
            ),
            EventDef(
                event_code="tcrt.audit.legacy.generic",
                domain="audit",
                write_audit=True,
                write_ops=False,
                default_impact=Impact.ROUTINE,
                details_schema=AuditGenericDetails,
                brief_template="{action} {resource}",
            ),
        ]
        
        # Ops events
        ops_events = [
            EventDef(
                event_code="tcrt.ops.automation.run.cancel",
                domain="ops",
                write_audit=False,
                write_ops=True,
                ops_level_by_outcome={
                    Outcome.SUCCESS: OpLevel.INFO,
                    Outcome.FAILURE: OpLevel.ERROR,
                },
                details_schema=RunCancelDetails,
                brief_template="Cancel automation run {run_id}",
            ),
            EventDef(
                event_code="tcrt.ops.automation.run.sync",
                domain="ops",
                write_audit=False,
                write_ops=True,
                ops_level_by_outcome={
                    Outcome.SUCCESS: OpLevel.DEBUG,
                    Outcome.FAILURE: OpLevel.INFO,
                },
                details_schema=RunSyncDetails,
                brief_template="Sync automation run {run_id}",
            ),
            EventDef(
                event_code="tcrt.ops.automation.run.reconcile",
                domain="ops",
                write_audit=False,
                write_ops=True,
                ops_level_by_outcome={
                    Outcome.SUCCESS: OpLevel.DEBUG,
                    Outcome.FAILURE: OpLevel.INFO,
                },
                details_schema=RunReconcileDetails,
                brief_template="Reconcile automation run {run_id}",
            ),
            EventDef(
                event_code="tcrt.ops.automation.result_provider.instantiate",
                domain="ops",
                write_audit=False,
                write_ops=True,
                ops_level_by_outcome={
                    Outcome.FAILURE: OpLevel.ERROR,
                },
                details_schema=ResultProviderInstantiateDetails,
                brief_template="Result provider instantiate failed: {error}",
            ),
            EventDef(
                event_code="tcrt.ops.automation.ci_artifact.download",
                domain="ops",
                write_audit=False,
                write_ops=True,
                ops_level_by_outcome={
                    Outcome.FAILURE: OpLevel.INFO,
                },
                details_schema=CIArtifactDownloadDetails,
                brief_template="CI artifact download failed for run {run_id}: {error}",
            ),
            EventDef(
                event_code="tcrt.ops.automation.allure_proxy.skip",
                domain="ops",
                write_audit=False,
                write_ops=True,
                ops_level_by_outcome={
                    Outcome.PARTIAL: OpLevel.DEBUG,
                },
                details_schema=AllureProxySkipDetails,
                brief_template="Allure proxy skipped (not configured)",
            ),
            EventDef(
                event_code="tcrt.ops.automation.allure_proxy.upload",
                domain="ops",
                write_audit=False,
                write_ops=True,
                ops_level_by_outcome={
                    Outcome.SUCCESS: OpLevel.DEBUG,
                    Outcome.PARTIAL: OpLevel.INFO,
                    Outcome.FAILURE: OpLevel.ERROR,
                },
                details_schema=AllureProxyUploadDetails,
                brief_template="Allure proxy upload {outcome} for run {run_id}",
            ),
            EventDef(
                event_code="tcrt.ops.automation.result_provider.report_url",
                domain="ops",
                write_audit=False,
                write_ops=True,
                ops_level_by_outcome={
                    Outcome.FAILURE: OpLevel.INFO,
                },
                details_schema=ResultProviderReportURLDetails,
                brief_template="Result provider report URL lookup failed for run {run_id}: {error}",
            ),
        ]
        
        for event in audit_events + ops_events:
            self.register(event)
    
    def register(self, event_def: EventDef) -> None:
        """Register an event definition. Raises if duplicate."""
        with self._lock:
            if event_def.event_code in self._events:
                raise ValueError(f"Duplicate event_code: {event_def.event_code}")
            self._events[event_def.event_code] = event_def
    
    def get(self, event_code: str) -> EventDef:
        """Get event definition by code. Raises KeyError if not found."""
        with self._lock:
            if event_code not in self._events:
                raise KeyError(f"Unknown event_code: {event_code}")
            return self._events[event_code]
    
    def __contains__(self, event_code: str) -> bool:
        with self._lock:
            return event_code in self._events
    
    def __iter__(self):
        with self._lock:
            return iter(self._events.values())
    
    def all_codes(self) -> list[str]:
        with self._lock:
            return sorted(self._events.keys())


# Global catalog instance
_catalog: Optional[EventCatalog] = None
_catalog_lock = threading.Lock()


def get_catalog() -> EventCatalog:
    """Get the global event catalog instance (singleton)."""
    global _catalog
    with _catalog_lock:
        if _catalog is None:
            _catalog = EventCatalog()
        return _catalog


def get_event_def(event_code: str) -> EventDef:
    """Get event definition from global catalog."""
    return get_catalog().get(event_code)


def register_event(event_def: EventDef) -> None:
    """Register an event in the global catalog."""
    get_catalog().register(event_def)


def legacy_event_code(action: str, resource: str) -> str:
    """Generate legacy audit event code from action and resource.
    
    Maps to the generic legacy event code in the catalog since we don't
    pre-register all action+resource combinations.
    """
    return "tcrt.audit.legacy.generic"