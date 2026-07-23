"""Pydantic schemas for observability event details."""

from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class EmptyDetails(BaseModel):
    """Empty details schema for events with no details."""
    pass


# ============================================================
# Audit event detail schemas
# ============================================================

class TokenRotateDetails(BaseModel):
    """Details for token rotation events."""
    actor: str = Field(..., description="Actor who rotated the token")
    token_id: Optional[int] = Field(None, description="Token ID")
    token_name: Optional[str] = Field(None, description="Token name")


class TokenRevokeDetails(BaseModel):
    """Details for token revocation events."""
    actor: str = Field(..., description="Actor who revoked the token")
    token_id: Optional[int] = Field(None, description="Token ID")
    token_name: Optional[str] = Field(None, description="Token name")


class MCPDenyDetails(BaseModel):
    """Details for MCP access denied events."""
    resource: str = Field(..., description="Resource that was denied")
    client_ip: Optional[str] = Field(None, description="Client IP address")
    reason: Optional[str] = Field(None, description="Deny reason")


class AppTokenDenyDetails(BaseModel):
    """Details for app token access denied events."""
    resource: str = Field(..., description="Resource that was denied")
    client_ip: Optional[str] = Field(None, description="Client IP address")
    token_id: Optional[int] = Field(None, description="Token ID")
    reason: Optional[str] = Field(None, description="Deny reason")


class TeamChangeDetails(BaseModel):
    """Details for team change events."""
    team_id: int = Field(..., description="Team ID")
    team_name: str = Field(..., description="Team name")
    changes: Dict[str, Any] = Field(default_factory=dict, description="Changed fields")


class UserChangeDetails(BaseModel):
    """Details for user change events."""
    user_id: int = Field(..., description="User ID")
    username: str = Field(..., description="Username")
    changes: Dict[str, Any] = Field(default_factory=dict, description="Changed fields")


class PermissionChangeDetails(BaseModel):
    """Details for permission change events."""
    target_type: str = Field(..., description="Target type (user/team/role)")
    target_id: int = Field(..., description="Target ID")
    permission: str = Field(..., description="Permission name")


class TestCaseChangeDetails(BaseModel):
    """Details for test case change events."""
    test_case_id: str = Field(..., description="Test case ID")
    section_id: Optional[int] = Field(None, description="Section ID")


class TestRunChangeDetails(BaseModel):
    """Details for test run change events."""
    test_run_id: int = Field(..., description="Test run ID")
    config_id: Optional[int] = Field(None, description="Config ID")


class ProviderConfigDetails(BaseModel):
    """Details for automation provider configuration events."""
    provider_type: str = Field(..., description="Provider type")
    slot: str = Field(..., description="Provider slot (ci/result/storage)")


class ProviderCredsDetails(BaseModel):
    """Details for automation provider credential rotation."""
    provider_type: str = Field(..., description="Provider type")
    slot: str = Field(..., description="Provider slot")


class ScriptChangeDetails(BaseModel):
    """Details for automation script change events."""
    script_id: int = Field(..., description="Script ID")
    script_name: str = Field(..., description="Script name")


class WebhookChangeDetails(BaseModel):
    """Details for automation webhook change events."""
    webhook_id: int = Field(..., description="Webhook ID")
    url: str = Field(..., description="Webhook URL")


class ConfigChangeDetails(BaseModel):
    """Details for system config change events."""
    key: str = Field(..., description="Config key")
    old_value: Optional[str] = Field(None, description="Old value")
    new_value: Optional[str] = Field(None, description="New value")


class AuditGenericDetails(BaseModel):
    """Generic details for legacy audit events."""
    action: Optional[str] = Field(None, description="Action type")
    resource: Optional[str] = Field(None, description="Resource type")
    extra: Dict[str, Any] = Field(default_factory=dict, description="Extra fields")


# ============================================================
# Ops event detail schemas
# ============================================================

class RunCancelDetails(BaseModel):
    """Details for automation run cancel events."""
    run_id: int = Field(..., description="Automation run ID")
    external_run_id: Optional[str] = Field(None, description="External CI run ID")
    actor: Optional[str] = Field(None, description="Actor who cancelled")


class RunSyncDetails(BaseModel):
    """Details for automation run sync events."""
    run_id: int = Field(..., description="Automation run ID")
    external_run_id: Optional[str] = Field(None, description="External CI run ID")


class RunReconcileDetails(BaseModel):
    """Details for automation run reconcile events."""
    run_id: int = Field(..., description="Automation run ID")
    external_run_id: Optional[str] = Field(None, description="External CI run ID")
    actor: Optional[str] = Field(None, description="Actor who triggered reconcile")


class ResultProviderInstantiateDetails(BaseModel):
    """Details for result provider instantiation failures."""
    team_id: int = Field(..., description="Team ID")
    error: str = Field(..., description="Error message")


class CIArtifactDownloadDetails(BaseModel):
    """Details for CI artifact download failures."""
    team_id: int = Field(..., description="Team ID")
    run_id: int = Field(..., description="Automation run ID")
    external_run_id: str = Field(..., description="External CI run ID")
    error: str = Field(..., description="Error message")


class AllureProxySkipDetails(BaseModel):
    """Details for Allure proxy skip events."""
    team_id: int = Field(..., description="Team ID")
    run_id: int = Field(..., description="Automation run ID")
    reason: str = Field(default="base_url_not_configured", description="Skip reason")


class AllureProxyUploadDetails(BaseModel):
    """Details for Allure proxy upload events."""
    team_id: int = Field(..., description="Team ID")
    run_id: int = Field(..., description="Automation run ID")
    project_id: str = Field(..., description="Allure project ID")
    error: str = Field(default="", description="Error message (empty on success)")


class ResultProviderReportURLDetails(BaseModel):
    """Details for result provider report URL lookup failures."""
    team_id: int = Field(..., description="Team ID")
    run_id: int = Field(..., description="Automation run ID")
    external_run_id: str = Field(..., description="External CI run ID")
    error: str = Field(..., description="Error message")


__all__ = [
    # Audit schemas
    "TokenRotateDetails",
    "TokenRevokeDetails",
    "MCPDenyDetails",
    "AppTokenDenyDetails",
    "TeamChangeDetails",
    "UserChangeDetails",
    "PermissionChangeDetails",
    "TestCaseChangeDetails",
    "TestRunChangeDetails",
    "ProviderConfigDetails",
    "ProviderCredsDetails",
    "ScriptChangeDetails",
    "WebhookChangeDetails",
    "ConfigChangeDetails",
    "AuditGenericDetails",
    # Ops schemas
    "RunCancelDetails",
    "RunSyncDetails",
    "RunReconcileDetails",
    "ResultProviderInstantiateDetails",
    "CIArtifactDownloadDetails",
    "AllureProxySkipDetails",
    "AllureProxyUploadDetails",
    "ResultProviderReportURLDetails",
]