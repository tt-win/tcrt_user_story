# MVP Event Catalog — `audit-ops-event-envelope`

## Naming Convention
```
tcrt.<domain>.<entity>.<verb>[.<qualifier>]
domain ∈ {audit, ops}
```

## Domain: `audit` (write_audit=True, write_ops=False)

| event_code | impact | outcome values | details_schema | brief_template | Notes |
|------------|--------|----------------|----------------|----------------|-------|
| `tcrt.audit.auth.token_rotate` | `privileged` | `success \| denied \| failure` | `TokenRotateDetails` | "App token rotated by {actor}" | Adapter legacy code |
| `tcrt.audit.auth.token_revoke` | `privileged` | `success \| denied \| failure` | `TokenRevokeDetails` | "App token revoked by {actor}" | Adapter legacy code |
| `tcrt.audit.auth.mcp_deny` | `sensitive` | `denied` | `MCPDenyDetails` | "MCP access denied for {resource}" | Adapter legacy code |
| `tcrt.audit.auth.app_token_deny` | `sensitive` | `denied` | `AppTokenDenyDetails` | "App token access denied for {resource}" | Adapter legacy code |
| `tcrt.audit.team.create` | `sensitive` | `success \| denied \| failure` | `TeamChangeDetails` | "Team created: {team_name}" | |
| `tcrt.audit.team.update` | `sensitive` | `success \| denied \| failure` | `TeamChangeDetails` | "Team updated: {team_name}" | |
| `tcrt.audit.team.delete` | `privileged` | `success \| denied \| failure` | `TeamChangeDetails` | "Team deleted: {team_name}" | |
| `tcrt.audit.user.create` | `sensitive` | `success \| denied \| failure` | `UserChangeDetails` | "User created: {username}" | |
| `tcrt.audit.user.update` | `sensitive` | `success \| denied \| failure` | `UserChangeDetails` | "User updated: {username}" | |
| `tcrt.audit.user.delete` | `privileged` | `success \| denied \| failure` | `UserChangeDetails` | "User deleted: {username}" | |
| `tcrt.audit.permission.grant` | `sensitive` | `success \| denied \| failure` | `PermissionChangeDetails` | "Permission granted: {permission} to {target}" | |
| `tcrt.audit.permission.revoke` | `sensitive` | `success \| denied \| failure` | `PermissionChangeDetails` | "Permission revoked: {permission} from {target}" | |
| `tcrt.audit.test_case.create` | `routine` | `success \| failure` | `TestCaseChangeDetails` | "Test case created: {id}" | |
| `tcrt.audit.test_case.update` | `routine` | `success \| failure` | `TestCaseChangeDetails` | "Test case updated: {id}" | |
| `tcrt.audit.test_case.delete` | `notable` | `success \| denied \| failure` | `TestCaseChangeDetails` | "Test case deleted: {id}" | DELETE → notable |
| `tcrt.audit.test_run.create` | `routine` | `success \| failure` | `TestRunChangeDetails` | "Test run created: {id}" | |
| `tcrt.audit.test_run.update` | `routine` | `success \| failure` | `TestRunChangeDetails` | "Test run updated: {id}" | |
| `tcrt.audit.test_run.delete` | `notable` | `success \| denied \| failure` | `TestRunChangeDetails` | "Test run deleted: {id}" | |
| `tcrt.audit.automation.provider.configure` | `sensitive` | `success \| denied \| failure` | `ProviderConfigDetails` | "Automation provider configured: {type}" | |
| `tcrt.audit.automation.provider.rotate_creds` | `privileged` | `success \| denied \| failure` | `ProviderCredsDetails` | "Automation provider credentials rotated: {type}" | |
| `tcrt.audit.automation.script.create` | `routine` | `success \| failure` | `ScriptChangeDetails` | "Automation script created: {id}" | |
| `tcrt.audit.automation.script.update` | `routine` | `success \| failure` | `ScriptChangeDetails` | "Automation script updated: {id}" | |
| `tcrt.audit.automation.script.delete` | `notable` | `success \| denied \| failure` | `ScriptChangeDetails` | "Automation script deleted: {id}" | |
| `tcrt.audit.automation.webhook.create` | `sensitive` | `success \| denied \| failure` | `WebhookChangeDetails` | "Automation webhook created: {id}" | |
| `tcrt.audit.automation.webhook.delete` | `privileged` | `success \| denied \| failure` | `WebhookChangeDetails` | "Automation webhook deleted: {id}" | |
| `tcrt.audit.system.config_change` | `sensitive` | `success \| failure` | `ConfigChangeDetails` | "System config changed: {key}" | |
| `tcrt.audit.legacy.{action}_{resource}` | per legacy map | `success` (default) | `{}` | "{action} {resource}" | Adapter fallback; catalog pre-seeded |

**Legacy impact map (adapter only):**
- `critical` → `privileged`
- `warning` → `sensitive`
- `info` → `routine`
- `notable` **never** reverse-mapped (catalog-only)

---

## Domain: `ops` (write_audit=False, write_ops=True)

### Automation Run Sync & Cancel
| event_code | outcome values | ops_level_by_outcome | details_schema | brief_template |
|------------|----------------|----------------------|----------------|----------------|
| `tcrt.ops.automation.run.cancel` | `success \| failure` | `success: INFO, failure: ERROR` | `RunCancelDetails` | "Cancel automation run {run_id}" |
| `tcrt.ops.automation.run.sync` | `success \| failure` | `success: DEBUG, failure: INFO` | `RunSyncDetails` | "Sync automation run {run_id}" |
| `tcrt.ops.automation.run.reconcile` | `success \| failure` | `success: DEBUG, failure: INFO` | `RunReconcileDetails` | "Reconcile automation run {run_id}" |

### CI Artifact Download (Jenkins → TCRT)
| event_code | outcome values | ops_level_by_outcome | details_schema | brief_template |
|------------|----------------|----------------------|----------------|----------------|
| `tcrt.ops.automation.ci_artifact.download` | `success \| failure` | `success: DEBUG, failure: INFO` | `CIArtifactDownloadDetails` | "Download CI artifacts for run {run_id}" |

**Note:** Failure is *expected* when Jenkins hasn't archived artifacts yet → `INFO` (not WARNING).

### Result Provider (Allure / custom)
| event_code | outcome values | ops_level_by_outcome | details_schema | brief_template |
|------------|----------------|----------------------|----------------|----------------|
| `tcrt.ops.automation.result_provider.instantiate` | `success \| failure` | `success: DEBUG, failure: ERROR` | `ResultProviderInstantiateDetails` | "Instantiate result provider for team {team_id}" |
| `tcrt.ops.automation.result_provider.report_url` | `success \| failure` | `success: DEBUG, failure: INFO` | `ResultProviderReportURLDetails` | "Lookup report URL for run {run_id}" |

**Note:** Provider not configured → no emit (returns `None` silently).

### Allure Proxy
| event_code | outcome values | ops_level_by_outcome | details_schema | brief_template |
|------------|----------------|----------------------|----------------|----------------|
| `tcrt.ops.automation.allure_proxy.ensure_project` | `success \| failure` | `success: DEBUG, failure: WARNING` | `AllureProjectDetails` | "Ensure Allure project {project_id}" |
| `tcrt.ops.automation.allure_proxy.clean_results` | `success \| failure` | `success: DEBUG, failure: INFO` | `AllureCleanDetails` | "Clean Allure results for project {project_id}" |
| `tcrt.ops.automation.allure_proxy.send_results` | `success \| partial \| failure` | `success: DEBUG, partial: INFO, failure: WARNING` | `AllureSendDetails` | "Send Allure results for project {project_id}" |
| `tcrt.ops.automation.allure_proxy.assert_project` | `success \| failure` | `success: DEBUG, failure: WARNING` | `AllureProjectDetails` | "Assert Allure project exists {project_id}" |
| `tcrt.ops.automation.allure_proxy.generate_report` | `success \| processing \| failure` | `success: DEBUG, processing: INFO, failure: ERROR` | `AllureGenerateDetails` | "Generate Allure report for project {project_id}" |
| `tcrt.ops.automation.allure_proxy.upload` | `success \| partial \| failure` | `success: DEBUG, partial: INFO, failure: ERROR` | `AllureUploadDetails` | "Upload Allure results for run {run_id}" |

**Key mappings (per design D8):**
- `upload` outcome `partial` → **INFO** (fall through to legacy URL template)
- `upload` outcome `failure` → **ERROR** (terminal, no fallback)
- `generate_report` outcome `processing` → **INFO** (transient, retried)
- `clean_results` 5xx → **INFO** (best-effort, non-fatal)

### Allure Project Lifecycle (delete/rename)
| event_code | outcome values | ops_level_by_outcome | details_schema | brief_template |
|------------|----------------|----------------------|----------------|----------------|
| `tcrt.ops.automation.allure_proxy.delete_project` | `success \| not_found \| failure` | `success: INFO, not_found: DEBUG, failure: WARNING` | `AllureProjectDeleteDetails` | "Delete Allure project {project_id}" |
| `tcrt.ops.automation.allure_proxy.reclaim_team` | `success \| failure` | `success: INFO, failure: WARNING` | `AllureTeamReclaimDetails` | "Reclaim Allure projects for team {team_id}" |
| `tcrt.ops.automation.allure_proxy.reclaim_rename` | `success \| failure` | `success: INFO, failure: WARNING` | `AllureRenameReclaimDetails` | "Reclaim renamed Allure project {old_id} → {new_id}" |

---

## EventCode → Details Schema (Pydantic models)

```python
# app/services/observability/schemas.py (to be created)

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

# Audit domain
class TokenRotateDetails(BaseModel):
    token_id: int
    actor: str
    old_token_prefix: str

class TokenRevokeDetails(BaseModel):
    token_id: int
    actor: str

class MCPDenyDetails(BaseModel):
    resource: str
    reason: str
    client_ip: Optional[str] = None

class AppTokenDenyDetails(BaseModel):
    token_id: int
    resource: str
    reason: str

class TeamChangeDetails(BaseModel):
    team_id: int
    team_name: str
    changes: dict = {}

class UserChangeDetails(BaseModel):
    user_id: int
    username: str
    changes: dict = {}

class PermissionChangeDetails(BaseModel):
    target_type: str  # "user" | "team" | "role"
    target_id: int
    permission: str

class TestCaseChangeDetails(BaseModel):
    test_case_id: str
    section_id: Optional[int] = None

class TestRunChangeDetails(BaseModel):
    test_run_id: int
    config_id: Optional[int] = None

class ProviderConfigDetails(BaseModel):
    provider_type: str
    slot: str  # "ci" | "result" | "storage"

class ProviderCredsDetails(BaseModel):
    provider_type: str
    slot: str

class ScriptChangeDetails(BaseModel):
    script_id: int
    script_name: str

class WebhookChangeDetails(BaseModel):
    webhook_id: int
    url: str

class ConfigChangeDetails(BaseModel):
    key: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None

# Ops domain
class RunCancelDetails(BaseModel):
    run_id: int
    external_run_id: str
    actor: Optional[str] = None

class RunSyncDetails(BaseModel):
    run_id: int
    external_run_id: str
    status_before: str
    status_after: str

class RunReconcileDetails(BaseModel):
    run_id: int
    external_run_id: Optional[str] = None
    actor: Optional[str] = None

class CIArtifactDownloadDetails(BaseModel):
    run_id: int
    external_run_id: str
    provider_type: str
    error: Optional[str] = None

class ResultProviderInstantiateDetails(BaseModel):
    team_id: int
    provider_type: str
    error: Optional[str] = None

class ResultProviderReportURLDetails(BaseModel):
    run_id: int
    external_run_id: str
    provider_type: str
    error: Optional[str] = None

class AllureProjectDetails(BaseModel):
    project_id: str
    team_id: int
    suite_id: str

class AllureCleanDetails(BaseModel):
    project_id: str
    error: Optional[str] = None

class AllureSendDetails(BaseModel):
    project_id: str
    file_count: int
    error: Optional[str] = None

class AllureGenerateDetails(BaseModel):
    project_id: str
    execution_name: str
    error: Optional[str] = None

class AllureUploadDetails(BaseModel):
    run_id: int
    project_id: str
    archive_bytes: int
    strategy: str  # "ci_pull" | "legacy_template"
    error: Optional[str] = None

class AllureProjectDeleteDetails(BaseModel):
    project_id: str
    team_id: int
    suite_id: str

class AllureTeamReclaimDetails(BaseModel):
    team_id: int
    deleted_count: int

class AllureRenameReclaimDetails(BaseModel):
    team_id: int
    suite_id: int
    old_project_id: str
    new_project_id: str
```