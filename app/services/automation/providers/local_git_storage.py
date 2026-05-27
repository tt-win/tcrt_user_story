from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.services.automation.providers.base import (
    BranchRef,
    CommitRef,
    HealthStatus,
    PullRequestRef,
    ScriptContent,
    ScriptRef,
)
from app.services.automation.providers.github_storage import infer_script_format


class LocalGitStorageConfig(BaseModel):
    working_dir: str
    remote_name: str = "origin"
    default_branch: str = "main"
    ssh_key_path: str | None = None


class LocalGitStorageCredentials(BaseModel):
    pass


class LocalGitStorageProvider:
    display_name = "Local Git Working Copy"

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        self.config = LocalGitStorageConfig.model_validate(config)
        self.root = Path(self.config.working_dir).expanduser().resolve()

    @classmethod
    def config_schema(cls) -> type[BaseModel]:
        return LocalGitStorageConfig

    @classmethod
    def credential_schema(cls) -> type[BaseModel]:
        return LocalGitStorageCredentials

    def _resolve(self, path: str) -> Path:
        resolved = (self.root / path).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"Path escapes working directory: {path}") from exc
        return resolved

    async def _git(self, *args: str) -> str:
        env = None
        if self.config.ssh_key_path:
            env = os.environ.copy()
            env["GIT_SSH_COMMAND"] = f"ssh -i {self.config.ssh_key_path}"
        process = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(self.root),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(stderr.decode("utf-8", errors="replace").strip())
        return stdout.decode("utf-8", errors="replace").strip()

    async def list_scripts(
        self,
        path: str,
        ref: str | None = None,
        recursive: bool = True,
    ) -> list[ScriptRef]:
        target = self._resolve(path)
        if not target.exists():
            return []
        files = target.rglob("*") if recursive and target.is_dir() else target.glob("*") if target.is_dir() else [target]
        refs: list[ScriptRef] = []
        for file_path in files:
            if not file_path.is_file():
                continue
            relative = file_path.relative_to(self.root).as_posix()
            refs.append(
                ScriptRef(
                    path=relative,
                    name=file_path.name,
                    script_format=infer_script_format(relative),
                    ref=ref or self.config.default_branch,
                    size=file_path.stat().st_size,
                )
            )
        return refs

    async def read_script(
        self,
        path: str,
        ref: str | None = None,
        etag: str | None = None,
    ) -> ScriptContent:
        current_etag = await self._git("rev-parse", f"{ref or self.config.default_branch}:{path}")
        if etag and etag == current_etag:
            return ScriptContent(
                path=path,
                content="",
                etag=current_etag,
                ref=ref or self.config.default_branch,
                not_modified=True,
            )
        target = self._resolve(path)
        content = target.read_text(encoding="utf-8")
        return ScriptContent(
            path=path,
            content=content,
            etag=current_etag,
            ref=ref or self.config.default_branch,
        )

    async def write_script(
        self,
        path: str,
        content: str,
        message: str,
        branch: str | None = None,
    ) -> CommitRef:
        ref = branch or self.config.default_branch
        await self._git("checkout", ref)
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        await self._git("add", path)
        try:
            await self._git("commit", "-m", message)
        except RuntimeError as exc:
            if "nothing to commit" not in str(exc):
                raise
        sha = await self._git("rev-parse", "HEAD")
        await self._git("push", self.config.remote_name, ref)
        return CommitRef(sha=sha, branch=ref, message=message)

    async def list_branches(self) -> list[BranchRef]:
        output = await self._git("branch", "--format=%(refname:short)")
        return [BranchRef(name=line) for line in output.splitlines() if line]

    async def create_pull_request(self, branch: str, title: str, body: str) -> PullRequestRef | None:
        return None

    async def health_check(self) -> HealthStatus:
        try:
            inside = await self._git("rev-parse", "--is-inside-work-tree")
            if inside == "true":
                return HealthStatus(status="OK", message=f"Local git repository: {self.root}")
            return HealthStatus(status="FAILED", message=f"Not a git repository: {self.root}")
        except Exception as exc:
            return HealthStatus(status="FAILED", message=str(exc))
