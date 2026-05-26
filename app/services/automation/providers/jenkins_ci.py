from __future__ import annotations

import re
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any, Literal
from xml.sax.saxutils import escape

import httpx
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel

from app.config import get_settings
from app.services.automation.providers.base import (
    ArtifactRef,
    ExternalRunRef,
    HealthStatus,
    RunStatusSnapshot,
    RunnerRef,
    WorkflowRef,
)


class JenkinsCIConfig(BaseModel):
    base_url: str
    auth_method: Literal["api_token", "trigger_token"] = "api_token"
    default_job_name: str | None = None
    default_runner_label: str = "any"
    csrf_protection_enabled: bool = True
    auto_manage_views: bool = False
    # The UI substitutes `{team_name}` with the current team name on the
    # provider create form, so a new provider for team "ARD" gets pre-filled
    # as "TCRT_ARD". Stored value is the concrete name the user chose.
    view_name_template: str = "TCRT_{team_name}"
    job_name_template: str = "tcrt-suite-{suite_id}-{suite_slug}"


class JenkinsCICredentials(BaseModel):
    username: str | None = None
    api_token: str | None = None
    job_token: str | None = None


class JenkinsCIProvider:
    display_name = "Jenkins"

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        self.config = JenkinsCIConfig.model_validate(config)
        self.credentials = JenkinsCICredentials.model_validate(credentials)
        template_dir = Path(__file__).resolve().parent.parent / "templates"
        self.templates = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape(enabled_extensions=("xml.j2",)),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    @classmethod
    def config_schema(cls) -> type[BaseModel]:
        return JenkinsCIConfig

    @classmethod
    def credential_schema(cls) -> type[BaseModel]:
        return JenkinsCICredentials

    def _auth(self) -> httpx.BasicAuth | None:
        if self.config.auth_method != "api_token":
            return None
        if not self.credentials.username or not self.credentials.api_token:
            raise ValueError("Jenkins api_token auth requires username and api_token")
        return httpx.BasicAuth(self.credentials.username, self.credentials.api_token)

    async def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.config.base_url.rstrip("/"),
            auth=self._auth(),
            timeout=30,
            follow_redirects=False,
        )

    async def _fetch_crumb(self, client: httpx.AsyncClient) -> dict[str, str]:
        """Fetch a CSRF crumb from Jenkins using the SAME client (so the
        session cookie that Jenkins binds the crumb to is preserved for the
        follow-up write request).

        Returns the {header_name: crumb_value} dict, or {} if Jenkins doesn't
        require CSRF (404 on /crumbIssuer or `csrf_protection_enabled=False`).
        """
        if not self.config.csrf_protection_enabled or self.config.auth_method != "api_token":
            return {}
        response = await client.get("/crumbIssuer/api/json")
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        data = response.json()
        return {data.get("crumbRequestField", "Jenkins-Crumb"): data.get("crumb", "")}

    async def _request(self, method: str, path: str, *, write: bool = False, **kwargs: Any) -> httpx.Response:
        headers = kwargs.pop("headers", {}) or {}
        async with await self._client() as client:
            if write:
                # Crumb MUST be fetched on the same client so the session
                # cookie Jenkins sets (`JSESSIONID`) is reused on the write
                # request — Jenkins ties each crumb to the session it issued.
                headers.update(await self._fetch_crumb(client))
            response = await client.request(method, path, headers=headers, **kwargs)
            if response.status_code == 403 and write and self.config.csrf_protection_enabled:
                # One retry with a fresh crumb on the SAME session — handles
                # crumb expiry while keeping the cookie jar intact.
                headers.update(await self._fetch_crumb(client))
                response = await client.request(method, path, headers=headers, **kwargs)
            if response.is_error:
                # Surface the Jenkins-side error body in the exception message;
                # Stapler stack traces, plugin complaints and XML parse errors
                # all land in the response body and are otherwise lost when
                # raise_for_status() reports only the generic status line.
                snippet = (response.text or "").strip()
                if snippet:
                    snippet = re.sub(r"<[^>]+>", " ", snippet)
                    snippet = re.sub(r"\s+", " ", snippet).strip()[:400]
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    if snippet:
                        raise httpx.HTTPStatusError(
                            f"{exc} | jenkins: {snippet}",
                            request=exc.request,
                            response=exc.response,
                        ) from exc
                    raise
            return response

    async def _job_exists(self, job_name: str) -> bool:
        try:
            await self._request("GET", f"/job/{_quote_job(job_name)}/api/json", params={"tree": "name"})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return False
            raise
        return True

    async def list_workflows(self) -> list[WorkflowRef]:
        response = await self._request("GET", "/api/json", params={"tree": "jobs[name,url,buildable]"})
        workflows = []
        for item in response.json().get("jobs", []):
            if item.get("buildable") is False:
                continue
            workflows.append(
                WorkflowRef(
                    id=item.get("name", ""),
                    name=item.get("name", ""),
                    state="buildable" if item.get("buildable") else "unknown",
                    url=item.get("url"),
                )
            )
        return workflows

    async def list_runners(self) -> list[RunnerRef]:
        response = await self._request(
            "GET",
            "/computer/api/json",
            params={"tree": "computer[displayName,idle,offline,assignedLabels[name]]"},
        )
        runners = []
        for index, item in enumerate(response.json().get("computer", [])):
            labels = [label.get("name", "") for label in item.get("assignedLabels", []) if label.get("name")]
            runners.append(
                RunnerRef(
                    id=index,
                    name=item.get("displayName", ""),
                    os="",
                    status="offline" if item.get("offline") else "online",
                    busy=not bool(item.get("idle")),
                    labels=labels,
                )
            )
        return runners

    async def trigger_run(self, workflow_id: str, branch: str, inputs: dict[str, str]) -> ExternalRunRef:
        job_name = workflow_id or self.config.default_job_name
        if not job_name:
            raise ValueError("Jenkins workflow_id or default_job_name is required")
        tcrt_run_id = inputs.get("tcrt_run_id") or str(uuid.uuid4())
        params = {**inputs, "tcrt_run_id": tcrt_run_id}
        runner_label = inputs.get("runner_label") or self.config.default_runner_label
        # Jenkins has NO node called "any" — the conventional way to say
        # "any agent" is an empty label expression. Translate the UI sentinel
        # value here so the pipeline doesn't wait forever for a non-existent
        # `any` label.
        params["NODE_LABEL"] = _normalize_runner_label(runner_label)
        # Git checkout params — Jenkins job XML has these as job parameters
        # (GIT_URL/GIT_BRANCH plain, GIT_TOKEN as PasswordParameter so it's
        # masked in console output). The caller may inject them via
        # `inputs["git_url"]`, etc. — `trigger_script` in run_service builds
        # this from the script's storage provider.
        for src, dst in (
            ("git_url", "GIT_URL"),
            ("git_branch", "GIT_BRANCH"),
            ("git_token", "GIT_TOKEN"),
        ):
            if inputs.get(src) is not None:
                params[dst] = inputs[src]
                # Don't echo the source key as a build param too.
                params.pop(src, None)
        if self.config.auth_method == "trigger_token" and self.credentials.job_token:
            params["token"] = self.credentials.job_token

        response = await self._request(
            "POST",
            f"/job/{_quote_job(job_name)}/buildWithParameters",
            write=True,
            params=params,
        )
        queue_id = _extract_queue_id(response.headers.get("Location", ""))
        return ExternalRunRef(
            external_run_id=f"queue:{queue_id}" if queue_id else None,
            external_run_url=response.headers.get("Location"),
            raw={"tcrt_run_id": tcrt_run_id, "job_name": job_name, "runner_label": runner_label},
        )

    async def get_run_status(self, external_run_id: str) -> RunStatusSnapshot:
        if external_run_id.startswith("queue:"):
            queue_id = external_run_id.split(":", 1)[1]
            try:
                response = await self._request("GET", f"/queue/item/{queue_id}/api/json")
            except httpx.HTTPStatusError as exc:
                # Jenkins drops queue items ~5min after an executor picks them
                # up. If our DB still has `queue:NNNN` at that point (e.g. the
                # sync loop missed the executable transition before the GC),
                # the build URL is unrecoverable from here — surface UNKNOWN
                # so the run leaves the sync queue instead of looping on 404.
                if exc.response.status_code == 404:
                    return RunStatusSnapshot(
                        status="UNKNOWN",
                        external_run_id=external_run_id,
                        raw={"error": "queue_item_not_found", "queue_id": queue_id},
                    )
                raise
            queue_item = response.json()
            executable = queue_item.get("executable")
            if not executable:
                in_queue_since = queue_item.get("inQueueSince")
                timed_out = bool(in_queue_since and (time.time() * 1000 - int(in_queue_since)) > 60_000)
                status_value = "UNKNOWN" if queue_item.get("cancelled") or timed_out else "QUEUED"
                return RunStatusSnapshot(
                    status=status_value,
                    external_run_id=external_run_id,
                    external_run_url=queue_item.get("url"),
                    raw=queue_item,
                )
            build_url = executable.get("url")
            build_id = str(executable.get("number"))
            return await self._get_build_status(build_url, build_id)
        build_url, build_id = _parse_build_ref(external_run_id)
        return await self._get_build_status(build_url, build_id)

    async def _get_build_status(self, build_url: str, build_id: str) -> RunStatusSnapshot:
        response = await self._request("GET", f"{build_url.rstrip('/')}/api/json")
        data = response.json()
        duration_ms = data.get("duration") or data.get("estimatedDuration")
        return RunStatusSnapshot(
            status=_map_jenkins_status(data.get("result"), data.get("building")),
            external_run_id=f"{build_url.rstrip('/')}#{build_id}",
            external_run_url=build_url,
            duration_ms=duration_ms,
            error_summary=data.get("description"),
            raw=data,
        )

    async def cancel_run(self, external_run_id: str) -> None:
        if external_run_id.startswith("queue:"):
            queue_id = external_run_id.split(":", 1)[1]
            await self._request("POST", "/queue/cancelItem", write=True, params={"id": queue_id})
            return
        build_url, _ = _parse_build_ref(external_run_id)
        base = build_url.rstrip("/")
        # /stop is the graceful interrupt and is usually enough. But a pipeline
        # blocked at `[Pipeline] node` (waiting for an agent) doesn't always
        # release its flyweight executor on /stop alone — it sits in
        # "Stopping" state indefinitely and the leaked flyweight blocks
        # *future* builds of the same job from even starting their pipeline
        # coordinator. /term is the documented escalation and is a no-op
        # against an already-terminated build, so we always send it as a
        # follow-up to guarantee the executor slot is reclaimed.
        await self._request("POST", f"{base}/stop", write=True)
        try:
            await self._request("POST", f"{base}/term", write=True)
        except httpx.HTTPStatusError as exc:
            # /term returns 404 on Jenkins versions where the endpoint isn't
            # available or when /stop already finished the build cleanly —
            # either way there's nothing left to terminate.
            if exc.response.status_code != 404:
                raise

    async def get_run_url(self, external_run_id: str) -> str:
        if external_run_id.startswith("queue:"):
            queue_id = external_run_id.split(":", 1)[1]
            return f"{self.config.base_url.rstrip('/')}/queue/item/{queue_id}/"
        build_url, _ = _parse_build_ref(external_run_id)
        return build_url

    async def list_artifacts(self, external_run_id: str) -> list[ArtifactRef]:
        if external_run_id.startswith("queue:"):
            snapshot = await self.get_run_status(external_run_id)
            if snapshot.status in {"QUEUED", "CANCELLED", "UNKNOWN"}:
                return []
            external_run_id = snapshot.external_run_id
        build_url, _ = _parse_build_ref(external_run_id)
        response = await self._request("GET", f"{build_url.rstrip('/')}/api/json", params={"tree": "artifacts[*]"})
        return [
            ArtifactRef(
                id=item.get("relativePath") or item.get("fileName"),
                name=item.get("fileName", ""),
                url=f"{build_url.rstrip('/')}/artifact/{item.get('relativePath')}",
            )
            for item in response.json().get("artifacts", [])
        ]

    async def create_suite_job(
        self,
        suite_id: str,
        suite_name: str,
        test_paths: list[str],
        default_runner_label: str,
        git_context: dict[str, Any] | None = None,
        team_id: int | None = None,
        team_name: str | None = None,
    ) -> str:
        job_name = self._suite_job_name(suite_id, suite_name)
        config_xml = self._render_suite_job(
            suite_id,
            suite_name,
            test_paths,
            default_runner_label,
            git_context,
            team_id=team_id,
            team_name=team_name,
        )
        await self._request(
            "POST",
            "/createItem",
            write=True,
            params={"name": job_name},
            content=config_xml.encode("utf-8"),
            headers={"Content-Type": "application/xml"},
        )
        if self.config.auto_manage_views:
            await self._ensure_view_contains_job(job_name)
        return job_name

    async def update_suite_job(
        self,
        suite_id: str,
        suite_name: str,
        test_paths: list[str],
        default_runner_label: str,
        git_context: dict[str, Any] | None = None,
        team_id: int | None = None,
        team_name: str | None = None,
    ) -> str:
        job_name = self._suite_job_name(suite_id, suite_name)
        # Probe before POST: Jenkins's `/job/{name}/config.xml` endpoint
        # returns 500 (Stapler dispatch error) rather than 404 when the job
        # doesn't exist on some versions, which would otherwise cause the
        # caller's "404 → fall through to create" recovery to mis-route a
        # genuine first-time setup into a real error.
        if not await self._job_exists(job_name):
            request = httpx.Request("POST", f"{self.config.base_url.rstrip('/')}/job/{_quote_job(job_name)}/config.xml")
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("Job not found", request=request, response=response)
        config_xml = self._render_suite_job(
            suite_id,
            suite_name,
            test_paths,
            default_runner_label,
            git_context,
            team_id=team_id,
            team_name=team_name,
        )
        await self._request(
            "POST",
            f"/job/{_quote_job(job_name)}/config.xml",
            write=True,
            content=config_xml.encode("utf-8"),
            headers={"Content-Type": "application/xml"},
        )
        if self.config.auto_manage_views:
            await self._ensure_view_contains_job(job_name)
        return job_name

    async def delete_suite_job(self, suite_id: str, job_name: str) -> None:
        try:
            await self._request("POST", f"/job/{_quote_job(job_name)}/doDelete", write=True)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise

    async def list_suite_jobs(self) -> list[WorkflowRef]:
        workflows = await self.list_workflows()
        return [workflow for workflow in workflows if workflow.name.startswith("tcrt-suite-")]

    async def health_check(self) -> HealthStatus:
        if self.config.auth_method == "trigger_token":
            return HealthStatus(
                status="LIMITED",
                message="trigger_token mode cannot verify user API; only trigger is testable",
            )

        try:
            response = await self._request("GET", "/me/api/json")
            auth_name = response.json().get("fullName") or response.json().get("id") or "unknown"
        except Exception as exc:
            return HealthStatus(status="FAILED", message=str(exc))

        runners = []
        runner_error = None
        try:
            runners = await self.list_runners()
        except Exception as exc:
            runner_error = str(exc)

        online_runners = [r for r in runners if r.status == "online"]
        label = self.config.default_runner_label

        details: dict[str, Any] = {
            "auth_user": auth_name,
            "total_runners": len(runners),
            "online_runners": len(online_runners),
            "offline_runners": sum(1 for r in runners if r.status == "offline"),
        }
        if runner_error:
            details["runner_error"] = runner_error

        if not runners and not runner_error:
            details["warning"] = "No agents/nodes found on this Jenkins instance"
            return HealthStatus(
                status="LIMITED",
                message=f"Jenkins authenticated as {auth_name}, but no agents found. Check agent configuration.",
                details=details,
            )

        if runner_error:
            details["warning"] = f"Failed to query runners: {runner_error}"
            return HealthStatus(
                status="LIMITED",
                message=f"Jenkins authenticated as {auth_name}, but cannot verify agents: {runner_error}",
                details=details,
            )

        if not online_runners:
            details["warning"] = f"No online agents (all {len(runners)} are offline)"
            return HealthStatus(
                status="LIMITED",
                message=f"Jenkins authenticated as {auth_name}, but all {len(runners)} agents are offline",
                details=details,
            )

        if label and label not in ("any", ""):
            matching = [r for r in online_runners if label in r.labels]
            details["matching_runners"] = len(matching)
            details["checked_label"] = label
            if not matching:
                runner_labels = sorted({l for r in online_runners for l in r.labels})
                details["available_labels"] = runner_labels
                return HealthStatus(
                    status="LIMITED",
                    message=f"Jenkins authenticated as {auth_name}, but no online agent matches label '{label}'. Available labels: {runner_labels[:10]}",
                    details=details,
                )

        return HealthStatus(
            status="OK",
            message=f"Jenkins authenticated as {auth_name}. {len(online_runners)}/{len(runners)} agents online"
            + (f", label '{label}' matched" if label and label not in ("any", "") else ""),
            details=details,
        )

    async def _ensure_view_contains_job(self, job_name: str) -> None:
        view_name = self.config.view_name_template
        try:
            await self._request("GET", f"/view/{urllib.parse.quote(view_name)}/api/json")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
            await self._request(
                "POST",
                "/createView",
                write=True,
                params={"name": view_name},
                content=self._render_list_view_config(view_name).encode("utf-8"),
                headers={"Content-Type": "application/xml"},
            )
        await self._request(
            "POST",
            f"/view/{urllib.parse.quote(view_name)}/addJobToView",
            write=True,
            params={"name": job_name},
        )

    def _render_suite_job(
        self,
        suite_id: str,
        suite_name: str,
        test_paths: list[str],
        default_runner_label: str,
        git_context: dict[str, Any] | None = None,
        team_id: int | None = None,
        team_name: str | None = None,
    ) -> str:
        template = self.templates.get_template("jenkins-suite-config.xml.j2")
        # See trigger_run: "any" is a TCRT-side sentinel meaning "any node"
        # but Jenkins treats it as a literal label search. Translate before
        # baking into the job XML's <defaultValue> + Groovy fallback.
        effective_label = _normalize_runner_label(
            default_runner_label or self.config.default_runner_label
        )
        # Default git URL / branch are baked into job XML so users can also
        # trigger directly from Jenkins UI (without TCRT) and still get a
        # checkout. trigger_run overrides at build time.
        git_ctx = git_context or {}
        suite_slug = _slugify(suite_name) or "suite"
        team_slug = _slugify(team_name or "") or "team"

        # Resolve Allure org-level settings from config.yaml at render time so
        # the generated job XML carries concrete <defaultValue>s — Jenkins jobs
        # then don't need any agent-level env vars to upload reports.
        allure_cfg = get_settings().automation_provider.allure
        allure_project_id = ""
        if allure_cfg.base_url and allure_cfg.project_id_template:
            try:
                allure_project_id = allure_cfg.project_id_template.format(
                    team_id=team_id if team_id is not None else "",
                    team_slug=team_slug,
                    suite_id=suite_id,
                    suite_slug=suite_slug,
                )
            except (KeyError, IndexError):
                # Bad placeholder in user's template — fall through to empty
                # project_id, which disables the Allure step at runtime.
                allure_project_id = ""

        return template.render(
            suite_id=suite_id,
            suite_name=suite_name,
            test_paths=test_paths,
            default_runner_label=effective_label,
            default_git_url=git_ctx.get("url", ""),
            default_git_branch=git_ctx.get("branch", "main"),
            allure_base_url=allure_cfg.base_url,
            allure_project_id=allure_project_id,
            allure_api_token=allure_cfg.api_token,
        )

    def _render_list_view_config(self, view_name: str) -> str:
        escaped_name = escape(view_name)
        return f"""<?xml version='1.1' encoding='UTF-8'?>
<hudson.model.ListView>
  <name>{escaped_name}</name>
  <filterExecutors>false</filterExecutors>
  <filterQueue>false</filterQueue>
  <properties class="hudson.model.View$PropertyList"/>
  <jobNames>
    <comparator class="java.lang.String$CaseInsensitiveComparator"/>
  </jobNames>
  <jobFilters/>
  <columns>
    <hudson.views.StatusColumn/>
    <hudson.views.WeatherColumn/>
    <hudson.views.JobColumn/>
    <hudson.views.LastSuccessColumn/>
    <hudson.views.LastFailureColumn/>
    <hudson.views.LastDurationColumn/>
    <hudson.views.BuildButtonColumn/>
  </columns>
</hudson.model.ListView>"""

    def _suite_job_name(self, suite_id: str, suite_name: str) -> str:
        suite_slug = _slugify(suite_name) or "suite"
        return self.config.job_name_template.format(suite_id=suite_id, suite_slug=suite_slug)


def _slugify(value: str) -> str:
    """Normalize free-form names to URL/identifier-safe slugs.

    Used for both Jenkins job names and Allure project ids derived from team /
    suite names. Returns an empty string for blank input — callers must handle
    that case (e.g. fall back to a literal "team" / "suite").
    """
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", (value or "").strip()).strip("-").lower()


# Map common human-readable display names (what shows up in Jenkins UI) to
# the actual routing labels (what `agent { label "..." }` expects). When users
# pick a node from TCRT's discover dropdown, the chip's text might be the
# displayName for friendliness; this map flips it back to the routing label so
# Jenkins can actually schedule the build.
_JENKINS_LABEL_ALIASES: dict[str, str] = {
    # Jenkins built-in node — UI shows "Built-In Node" / "Built In Node" /
    # legacy "Master Node", all route via the same internal label.
    "built-in node": "built-in",
    "built in node": "built-in",
    "built_in_node": "built-in",
    "master node": "built-in",
    "the master": "built-in",
}


def _normalize_runner_label(label: str | None) -> str:
    """Translate TCRT-side runner-label sentinels into Jenkins-routable values.

    Two classes of translation:
    1. `"any"` / empty / None → `""` — Jenkins' empty-label expression matches
       any online node; there's no actual node called "any".
    2. Display-name aliases → routing slug (see ``_JENKINS_LABEL_ALIASES``) —
       Jenkins UI shows e.g. "Built-In Node" but the routing label is
       "built-in". Users picking the friendly name in the discover dropdown
       would otherwise see ``agent { label "Built-In Node" }`` which Jenkins
       can't find.

    Callers should use this helper anywhere a runner label flows into job XML
    or into a build trigger's NODE_LABEL parameter.
    """
    if label is None:
        return ""
    stripped = str(label).strip()
    if not stripped or stripped.lower() == "any":
        return ""
    alias = _JENKINS_LABEL_ALIASES.get(stripped.lower())
    if alias is not None:
        return alias
    return stripped


def _quote_job(job_name: str) -> str:
    return "/job/".join(urllib.parse.quote(part) for part in job_name.split("/"))


def _extract_queue_id(location: str) -> str | None:
    match = re.search(r"/queue/item/(\d+)/?", location)
    return match.group(1) if match else None


def _parse_build_ref(external_run_id: str) -> tuple[str, str]:
    if "#" in external_run_id:
        build_url, build_id = external_run_id.rsplit("#", 1)
        return build_url, build_id
    return external_run_id, external_run_id.rstrip("/").rsplit("/", 1)[-1]


def _map_jenkins_status(result: str | None, building: bool | None) -> str:
    if building:
        return "RUNNING"
    if result == "SUCCESS":
        return "SUCCEEDED"
    if result in {"FAILURE", "UNSTABLE"}:
        return "FAILED"
    if result == "ABORTED":
        return "CANCELLED"
    if result is None:
        return "QUEUED"
    return "UNKNOWN"
