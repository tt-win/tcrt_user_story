from __future__ import annotations

import asyncio
import base64
import time
from typing import Any, Literal

import httpx
import jwt
from pydantic import BaseModel, Field

from app.services.automation.providers.base import (
    BranchRef,
    CommitRef,
    HealthStatus,
    PullRequestRef,
    ScriptContent,
    ScriptRef,
)


def infer_script_format(path: str) -> str:
    if path.endswith(".spec.ts") or path.endswith(".test.ts") or path.endswith(".spec.js") or path.endswith(".test.js"):
        return "PLAYWRIGHT_JS"
    if path.endswith(".py"):
        filename = path.rsplit("/", 1)[-1]
        return "PYTEST" if filename.startswith("test_") or filename.endswith("_test.py") else "PLAYWRIGHT_PY_ASYNC"
    return "OTHER"


class GitHubStorageConfig(BaseModel):
    owner: str = Field(
        ...,
        description=(
            "GitHub organization or user account name — the part BEFORE the slash in the repo URL. "
            "Example: for https://github.com/octocat/Hello-World, fill `octocat`."
        ),
    )
    repo: str = Field(
        ...,
        description=(
            "Repository name only — the part AFTER the slash. Do NOT include the owner prefix "
            "or `.git` suffix. Example: for https://github.com/octocat/Hello-World, fill `Hello-World`."
        ),
    )
    default_branch: str = Field(
        default="main",
        description="Branch to scan scripts from. Usually `main` or `master`.",
    )
    auth_method: Literal["pat", "github_app"] = Field(
        default="pat",
        description="`pat` = Personal Access Token (simpler); `github_app` = GitHub App installation (better for orgs).",
    )
    api_base_url: str = Field(
        default="https://api.github.com",
        description="Override only for GitHub Enterprise Server (e.g. `https://github.acme.com/api/v3`).",
    )
    scan_path: str = Field(
        default="tests/",
        description="Subdirectory inside the repo to scan for test scripts. Trailing slash optional.",
    )


class GitHubStorageCredentials(BaseModel):
    pat: str | None = None
    app_id: str | None = None
    installation_id: str | None = None
    private_key_pem: str | None = None


class GitHubStorageProvider:
    display_name = "GitHub Repository"

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        self.config = GitHubStorageConfig.model_validate(config)
        self.credentials = GitHubStorageCredentials.model_validate(credentials)
        self._installation_token: str | None = None
        self._installation_token_expires_at = 0.0

    @classmethod
    def config_schema(cls) -> type[BaseModel]:
        return GitHubStorageConfig

    @classmethod
    def credential_schema(cls) -> type[BaseModel]:
        return GitHubStorageCredentials

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

    async def _request(
        self,
        method: str,
        path: str,
        *,
        raise_for_status: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": await self._auth_header(),
            "X-GitHub-Api-Version": "2022-11-28",
        }
        headers.update(kwargs.pop("headers", {}) or {})
        async with httpx.AsyncClient(base_url=self.config.api_base_url, timeout=30) as client:
            response = await client.request(method, path, headers=headers, **kwargs)
            if raise_for_status:
                response.raise_for_status()
            return response

    def _repo_path(self, suffix: str) -> str:
        return f"/repos/{self.config.owner}/{self.config.repo}{suffix}"

    async def _get_content(
        self,
        path: str,
        ref: str | None = None,
        etag: str | None = None,
    ) -> tuple[httpx.Response, Any | None]:
        params = {"ref": ref or self.config.default_branch}
        headers = {"If-None-Match": etag} if etag else {}
        response = await self._request(
            "GET",
            self._repo_path(f"/contents/{path.strip('/')}"),
            params=params,
            headers=headers,
            raise_for_status=False,
        )
        if response.status_code == 304:
            return response, None
        if response.status_code == 404:
            raise FileNotFoundError(path)
        response.raise_for_status()
        return response, response.json()

    async def list_scripts(
        self,
        path: str,
        ref: str | None = None,
        recursive: bool = True,
    ) -> list[ScriptRef]:
        async def walk(current_path: str) -> list[ScriptRef]:
            try:
                _, data = await self._get_content(current_path, ref)
            except FileNotFoundError:
                return []
            entries = data if isinstance(data, list) else [data]
            scripts: list[ScriptRef] = []
            for item in entries:
                item_type = item.get("type")
                item_path = item.get("path", "")
                if item_type == "dir" and recursive:
                    scripts.extend(await walk(item_path))
                elif item_type == "file":
                    scripts.append(
                        ScriptRef(
                            path=item_path,
                            name=item.get("name") or item_path.rsplit("/", 1)[-1],
                            script_format=infer_script_format(item_path),
                            ref=ref or self.config.default_branch,
                            size=item.get("size"),
                            etag=item.get("sha"),
                            web_url=item.get("html_url"),
                        )
                    )
            return scripts

        return await walk(path)

    async def read_script(
        self,
        path: str,
        ref: str | None = None,
        etag: str | None = None,
    ) -> ScriptContent:
        response, data = await self._get_content(path, ref, etag)
        if response.status_code == 304:
            return ScriptContent(
                path=path,
                content="",
                etag=etag,
                ref=ref or self.config.default_branch,
                not_modified=True,
            )
        if isinstance(data, list) or data.get("type") != "file":
            raise ValueError(f"GitHub path is not a file: {path}")
        raw_content = data.get("content") or ""
        content = base64.b64decode(raw_content.encode("ascii")).decode("utf-8")
        return ScriptContent(
            path=data.get("path", path),
            content=content,
            etag=response.headers.get("etag") or data.get("sha"),
            ref=ref or self.config.default_branch,
            web_url=data.get("html_url"),
        )

    async def write_script(
        self,
        path: str,
        content: str,
        message: str,
        branch: str | None = None,
    ) -> CommitRef:
        ref = branch or self.config.default_branch
        body: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": ref,
        }
        try:
            _, existing = await self._get_content(path, ref)
            if isinstance(existing, dict) and existing.get("sha"):
                body["sha"] = existing["sha"]
        except FileNotFoundError:
            pass

        response = await self._request("PUT", self._repo_path(f"/contents/{path.strip('/')}"), json=body)
        data = response.json()
        commit = data.get("commit", {})
        return CommitRef(
            sha=commit.get("sha") or data.get("content", {}).get("sha") or "",
            branch=ref,
            message=message,
            url=commit.get("html_url"),
        )

    async def delete_file(self, path: str, message: str, branch: str | None = None) -> None:
        ref = branch or self.config.default_branch
        _, existing = await self._get_content(path, ref)
        if not isinstance(existing, dict) or not existing.get("sha"):
            raise ValueError(f"GitHub path is not a deletable file: {path}")
        response = await self._request(
            "DELETE",
            self._repo_path(f"/contents/{path.strip('/')}"),
            json={"message": message, "sha": existing["sha"], "branch": ref},
            raise_for_status=False,
        )
        if response.status_code == 422:
            try:
                error_message = str(response.json().get("message", ""))
            except ValueError:
                error_message = response.text
            if "sha" in error_message.lower() and "mismatch" in error_message.lower():
                raise RuntimeError("GitHub delete failed because the file SHA no longer matches") from None
        response.raise_for_status()

    async def file_exists(self, path: str, ref: str | None = None) -> bool:
        response = await self._request(
            "GET",
            self._repo_path(f"/git/trees/{ref or self.config.default_branch}"),
            params={"recursive": "1"},
            raise_for_status=False,
        )
        if response.status_code == 404:
            return False
        response.raise_for_status()
        normalized = path.strip("/")
        return any(
            item.get("type") == "blob" and item.get("path") == normalized
            for item in response.json().get("tree", [])
        )

    async def list_branches(self) -> list[BranchRef]:
        response = await self._request("GET", self._repo_path("/branches"))
        return [
            BranchRef(
                name=item.get("name", ""),
                sha=(item.get("commit") or {}).get("sha"),
                protected=bool(item.get("protected")),
            )
            for item in response.json()
        ]

    async def create_pull_request(self, branch: str, title: str, body: str) -> PullRequestRef | None:
        response = await self._request(
            "POST",
            self._repo_path("/pulls"),
            json={"head": branch, "base": self.config.default_branch, "title": title, "body": body},
        )
        data = response.json()
        return PullRequestRef(
            number=int(data["number"]),
            url=data["html_url"],
            title=data["title"],
            branch=branch,
        )

    async def health_check(self) -> HealthStatus:
        try:
            response = await self._request("GET", "/user")
            login = response.json().get("login", "unknown")
            return HealthStatus(status="OK", message=f"GitHub authenticated as {login}")
        except Exception as exc:
            return HealthStatus(status="FAILED", message=str(exc))


async def poll_with_timeout(interval_seconds: float, timeout_seconds: float, action):
    deadline = time.monotonic() + timeout_seconds
    while True:
        result = await action()
        if result:
            return result
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(interval_seconds)
