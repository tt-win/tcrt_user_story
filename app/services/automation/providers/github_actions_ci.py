from __future__ import annotations

import time
import uuid
from pathlib import Path
from re import sub
from typing import Any, Literal

import httpx
import jwt
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel

from app.services.automation.providers.base import (
    ArtifactRef,
    ExternalRunRef,
    HealthStatus,
    RunStatusSnapshot,
    RunnerRef,
    WorkflowRef,
)
from app.services.automation.providers.github_storage import GitHubStorageProvider, poll_with_timeout


class GitHubActionsCIConfig(BaseModel):
    owner: str
    repo: str
    default_branch: str = "main"
    auth_method: Literal["pat", "github_app"] = "pat"
    api_base_url: str = "https://api.github.com"
    default_runner_label: str = "ubuntu-latest"


class GitHubActionsCICredentials(BaseModel):
    pat: str | None = None
    app_id: str | None = None
    installation_id: str | None = None
    private_key_pem: str | None = None


class GitHubActionsCIProvider:
    display_name = "GitHub Actions"

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        self.config = GitHubActionsCIConfig.model_validate(config)
        self.credentials = GitHubActionsCICredentials.model_validate(credentials)
        self._installation_token: str | None = None
        self._installation_token_expires_at = 0.0
        template_dir = Path(__file__).resolve().parent.parent / "templates"
        self.templates = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape(disabled_extensions=("j2",)),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    @classmethod
    def config_schema(cls) -> type[BaseModel]:
        return GitHubActionsCIConfig

    @classmethod
    def credential_schema(cls) -> type[BaseModel]:
        return GitHubActionsCICredentials

    async def _installation_access_token(self) -> str:
        if self._installation_token and time.time() < self._installation_token_expires_at - 60:
            return self._installation_token
        if not self.credentials.app_id or not self.credentials.installation_id or not self.credentials.private_key_pem:
            raise ValueError("GitHub App auth requires app_id, installation_id, and private_key_pem")

        now = int(time.time())
        app_jwt = jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": self.credentials.app_id},
            self.credentials.private_key_pem,
            algorithm="RS256",
        )
        async with httpx.AsyncClient(base_url=self.config.api_base_url, timeout=30) as client:
            response = await client.post(
                f"/app/installations/{self.credentials.installation_id}/access_tokens",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {app_jwt}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            response.raise_for_status()
            data = response.json()
        self._installation_token = data["token"]
        self._installation_token_expires_at = time.time() + 3600
        return self._installation_token

    async def _auth_header(self) -> str:
        if self.config.auth_method == "github_app":
            return f"Bearer {await self._installation_access_token()}"
        if not self.credentials.pat:
            raise ValueError("GitHub PAT auth requires pat")
        return f"token {self.credentials.pat}"

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": await self._auth_header(),
            "X-GitHub-Api-Version": "2022-11-28",
        }
        headers.update(kwargs.pop("headers", {}) or {})
        async with httpx.AsyncClient(base_url=self.config.api_base_url, timeout=30) as client:
            response = await client.request(method, path, headers=headers, **kwargs)
            response.raise_for_status()
            return response

    def _repo_path(self, suffix: str) -> str:
        return f"/repos/{self.config.owner}/{self.config.repo}{suffix}"

    def _storage_provider(self) -> GitHubStorageProvider:
        return GitHubStorageProvider(config=self.config.model_dump(), credentials=self.credentials.model_dump())

    async def list_workflows(self) -> list[WorkflowRef]:
        response = await self._request("GET", self._repo_path("/actions/workflows"))
        return [
            WorkflowRef(
                id=str(item.get("id")),
                name=item.get("name", ""),
                path=item.get("path"),
                state=item.get("state"),
                url=item.get("html_url"),
            )
            for item in response.json().get("workflows", [])
        ]

    async def list_runners(self) -> list[RunnerRef]:
        response = await self._request("GET", self._repo_path("/actions/runners"))
        runners = []
        for item in response.json().get("runners", []):
            labels = [label.get("name", "") for label in item.get("labels", []) if label.get("name")]
            runners.append(
                RunnerRef(
                    id=item.get("id"),
                    name=item.get("name", ""),
                    os=item.get("os", ""),
                    status=item.get("status", "unknown"),
                    busy=bool(item.get("busy")),
                    labels=labels,
                )
            )
        return runners

    async def trigger_run(self, workflow_id: str, branch: str, inputs: dict[str, str]) -> ExternalRunRef:
        tcrt_run_id = inputs.get("tcrt_run_id") or str(uuid.uuid4())
        payload_inputs = {**inputs, "tcrt_run_id": tcrt_run_id}
        started_after = time.time() - 5
        correlation_raw = {
            "tcrt_run_id": tcrt_run_id,
            "correlation_strategy": "recent_workflow_dispatch_run",
            "correlation_verified": False,
            "correlation_note": (
                "GitHub Actions run list APIs do not expose workflow_dispatch input values; "
                "the adapter can only match by workflow, branch, event, and creation time."
            ),
        }
        try:
            await self._request(
                "POST",
                self._repo_path(f"/actions/workflows/{workflow_id}/dispatches"),
                json={"ref": branch or self.config.default_branch, "inputs": payload_inputs},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 422:
                raise RuntimeError(
                    "GitHub Actions workflow_dispatch trigger failed; verify the workflow exists on "
                    "the target ref and declares on.workflow_dispatch."
                ) from exc
            raise

        async def find_run() -> ExternalRunRef | None:
            response = await self._request(
                "GET",
                self._repo_path(f"/actions/workflows/{workflow_id}/runs"),
                params={"event": "workflow_dispatch", "branch": branch or self.config.default_branch, "per_page": 20},
            )
            for run in response.json().get("workflow_runs", []):
                created_at = run.get("created_at") or ""
                if created_at and _github_timestamp_to_epoch(created_at) >= started_after:
                    return ExternalRunRef(
                        external_run_id=str(run.get("id")),
                        external_run_url=run.get("html_url"),
                        raw={**correlation_raw, "matched_run_created_at": created_at},
                    )
            return None

        matched = await poll_with_timeout(2, 60, find_run)
        if matched:
            return matched
        return ExternalRunRef(
            acknowledged=True,
            external_run_id=None,
            raw={**correlation_raw, "status": "UNKNOWN"},
        )

    async def get_run_status(self, external_run_id: str) -> RunStatusSnapshot:
        response = await self._request("GET", self._repo_path(f"/actions/runs/{external_run_id}"))
        data = response.json()
        return RunStatusSnapshot(
            status=_map_github_run_status(data.get("status"), data.get("conclusion")),
            external_run_id=str(data.get("id", external_run_id)),
            external_run_url=data.get("html_url"),
            started_at=data.get("run_started_at"),
            finished_at=data.get("updated_at") if data.get("status") == "completed" else None,
            raw=data,
        )

    async def cancel_run(self, external_run_id: str) -> None:
        await self._request("POST", self._repo_path(f"/actions/runs/{external_run_id}/cancel"))

    async def get_run_url(self, external_run_id: str) -> str:
        return f"https://github.com/{self.config.owner}/{self.config.repo}/actions/runs/{external_run_id}"

    async def list_artifacts(self, external_run_id: str) -> list[ArtifactRef]:
        response = await self._request("GET", self._repo_path(f"/actions/runs/{external_run_id}/artifacts"))
        return [
            ArtifactRef(
                id=item.get("id"),
                name=item.get("name", ""),
                url=item.get("archive_download_url"),
                size_in_bytes=item.get("size_in_bytes"),
            )
            for item in response.json().get("artifacts", [])
        ]

    async def create_suite_job(
        self,
        suite_id: str,
        suite_name: str,
        test_paths: list[str],
        default_runner_label: str,
        # GH Actions workflows use `actions/checkout@v4` to pull the repo,
        # so the git_context plumbing from the Jenkins side isn't needed
        # here — accept and ignore for protocol compatibility.
        git_context: dict[str, Any] | None = None,
    ) -> str:
        path = self._suite_workflow_path(suite_id, suite_name)
        content = self._render_suite_workflow(suite_id, suite_name, test_paths, default_runner_label)
        await self._storage_provider().write_script(
            path,
            content,
            f"Create TCRT suite workflow {suite_name}",
            self.config.default_branch,
        )
        return path

    async def update_suite_job(
        self,
        suite_id: str,
        suite_name: str,
        test_paths: list[str],
        default_runner_label: str,
        git_context: dict[str, Any] | None = None,
    ) -> str:
        path = self._suite_workflow_path(suite_id, suite_name)
        content = self._render_suite_workflow(suite_id, suite_name, test_paths, default_runner_label)
        await self._storage_provider().write_script(
            path,
            content,
            f"Update TCRT suite workflow {suite_name}",
            self.config.default_branch,
        )
        return path

    async def delete_suite_job(self, suite_id: str, job_name: str) -> None:
        path = job_name if job_name.endswith((".yml", ".yaml")) else self._suite_workflow_path(suite_id, job_name)
        await self._storage_provider().delete_file(
            path,
            f"Delete TCRT suite workflow {job_name}",
            self.config.default_branch,
        )

    async def list_suite_jobs(self) -> list[WorkflowRef]:
        workflows = await self.list_workflows()
        return [
            workflow
            for workflow in workflows
            if workflow.name.lower().startswith("tcrt suite -")
            or (workflow.path and "/tcrt-suite-" in workflow.path)
        ]

    async def health_check(self) -> HealthStatus:
        try:
            response = await self._request("GET", "/user")
            login = response.json().get("login", "unknown")
        except Exception as exc:
            return HealthStatus(status="FAILED", message=str(exc))

        runners: list[Any] = []
        runner_error = None
        try:
            runners = await self.list_runners()
        except Exception as exc:
            runner_error = str(exc)

        details: dict[str, Any] = {
            "auth_user": login,
            "total_runners": len(runners),
            "online_runners": sum(1 for r in runners if r.status == "online"),
        }

        if runner_error:
            details["runner_error"] = runner_error

        if not runners:
            if not runner_error:
                details["note"] = "No self-hosted runners; GitHub-hosted runners (ubuntu-latest, etc.) are used"
            else:
                details["warning"] = f"Runner query failed: {runner_error}"

        return HealthStatus(
            status="OK",
            message=f"GitHub Actions authenticated as {login}",
            details=details,
        )

    def _render_suite_workflow(
        self,
        suite_id: str,
        suite_name: str,
        test_paths: list[str],
        default_runner_label: str,
    ) -> str:
        template = self.templates.get_template("github-actions-suite.yml.j2")
        return template.render(
            suite_id=suite_id,
            suite_name=suite_name,
            test_paths=test_paths,
            default_runner_label=default_runner_label or self.config.default_runner_label,
            tcrt_webhook_url_placeholder="${{ secrets.TCRT_WEBHOOK_URL }}",
        )

    def _suite_workflow_path(self, suite_id: str, suite_name: str) -> str:
        slug = sub(r"[^a-zA-Z0-9_-]+", "-", suite_name.strip()).strip("-").lower() or "suite"
        return f".github/workflows/tcrt-suite-{suite_id}-{slug}.yml"


def _map_github_run_status(status_value: str | None, conclusion: str | None) -> str:
    if status_value in {"queued", "requested", "waiting", "pending"}:
        return "QUEUED"
    if status_value in {"in_progress"}:
        return "RUNNING"
    if status_value == "completed":
        if conclusion == "success":
            return "SUCCEEDED"
        if conclusion == "cancelled":
            return "CANCELLED"
        if conclusion in {"failure", "timed_out", "action_required", "neutral", "skipped", "startup_failure"}:
            return "FAILED"
    return "UNKNOWN"


def _github_timestamp_to_epoch(value: str) -> float:
    from datetime import datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
