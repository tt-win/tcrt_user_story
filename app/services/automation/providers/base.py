from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class FrozenProviderModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class ScriptRef(FrozenProviderModel):
    path: str
    name: str
    script_format: str = "OTHER"
    ref: str | None = None
    size: int | None = None
    last_modified: str | None = None
    etag: str | None = None
    web_url: str | None = None


class ScriptContent(FrozenProviderModel):
    path: str
    content: str
    etag: str | None = None
    ref: str | None = None
    web_url: str | None = None
    not_modified: bool = False


class CommitRef(FrozenProviderModel):
    sha: str
    branch: str | None = None
    message: str | None = None
    url: str | None = None


class BranchRef(FrozenProviderModel):
    name: str
    sha: str | None = None
    protected: bool = False


class PullRequestRef(FrozenProviderModel):
    number: int
    url: str
    title: str
    branch: str


class WorkflowRef(FrozenProviderModel):
    id: str
    name: str
    path: str | None = None
    state: str | None = None
    url: str | None = None


class RunnerRef(FrozenProviderModel):
    id: int | str
    name: str
    os: str = ""
    status: str = "unknown"
    busy: bool = False
    labels: list[str] = Field(default_factory=list)


class ExternalRunRef(FrozenProviderModel):
    acknowledged: bool = True
    external_run_id: str | None = None
    external_run_url: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class RunStatusSnapshot(FrozenProviderModel):
    status: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "UNKNOWN"]
    external_run_id: str
    external_run_url: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    error_summary: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ArtifactRef(FrozenProviderModel):
    id: str | int
    name: str
    url: str | None = None
    size_in_bytes: int | None = None


class HealthStatus(FrozenProviderModel):
    status: Literal["OK", "FAILED", "LIMITED"]
    message: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class ProviderWithSchemas(Protocol):
    @classmethod
    def config_schema(cls) -> type[BaseModel]: ...

    @classmethod
    def credential_schema(cls) -> type[BaseModel]: ...


@runtime_checkable
class StorageProvider(ProviderWithSchemas, Protocol):
    async def list_scripts(
        self,
        path: str,
        ref: str | None = None,
        recursive: bool = True,
    ) -> list[ScriptRef]: ...

    async def read_script(
        self,
        path: str,
        ref: str | None = None,
        etag: str | None = None,
    ) -> ScriptContent: ...

    async def write_script(
        self,
        path: str,
        content: str,
        message: str,
        branch: str | None = None,
    ) -> CommitRef: ...

    async def list_branches(self) -> list[BranchRef]: ...

    async def create_pull_request(self, branch: str, title: str, body: str) -> PullRequestRef | None: ...

    async def health_check(self) -> HealthStatus: ...


@runtime_checkable
class CIProvider(ProviderWithSchemas, Protocol):
    async def list_workflows(self) -> list[WorkflowRef]: ...

    async def list_runners(self) -> list[RunnerRef]: ...

    async def trigger_run(self, workflow_id: str, branch: str, inputs: dict[str, str]) -> ExternalRunRef: ...

    async def get_run_status(self, external_run_id: str) -> RunStatusSnapshot: ...

    async def cancel_run(self, external_run_id: str) -> None: ...

    async def get_run_url(self, external_run_id: str) -> str: ...

    async def list_artifacts(self, external_run_id: str) -> list[ArtifactRef]: ...

    async def create_suite_job(
        self,
        suite_id: str,
        suite_name: str,
        test_paths: list[str],
        default_runner_label: str,
        # Optional git checkout context (url/branch/token) — used by Jenkins
        # provider to bake `GIT_URL` / `GIT_BRANCH` defaults into job XML.
        # GH Actions provider can ignore (workflows use actions/checkout).
        git_context: dict[str, Any] | None = None,
        # Appended to the derived job name to produce a trigger-scoped variant
        # (e.g. "_hook" for the webhook job). Empty = the primary job. Providers
        # treat it as an opaque string with no business meaning.
        job_suffix: str = "",
    ) -> str: ...

    async def update_suite_job(
        self,
        suite_id: str,
        suite_name: str,
        test_paths: list[str],
        default_runner_label: str,
        git_context: dict[str, Any] | None = None,
        # The job/workflow name the suite currently maps to. When a rename
        # changes the derived name, providers use this to relocate the existing
        # job instead of orphaning it.
        existing_job_name: str | None = None,
        job_suffix: str = "",
    ) -> str: ...

    async def delete_suite_job(self, suite_id: str, job_name: str) -> None: ...

    # Delete a team's list view (e.g. after a team rename moved its jobs to the
    # new-name view). Providers without a view concept may no-op.
    async def delete_view(self, team_id: int | None = None, team_name: str | None = None) -> None: ...

    async def list_suite_jobs(self) -> list[WorkflowRef]: ...

    async def health_check(self) -> HealthStatus: ...


@runtime_checkable
class ResultProvider(ProviderWithSchemas, Protocol):
    async def get_run_report_url(self, ci_external_run_id: str) -> str | None: ...

    async def get_dashboard_url(self) -> str | None: ...

    async def health_check(self) -> HealthStatus: ...
