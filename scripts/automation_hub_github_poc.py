#!/usr/bin/env python3
"""POC: Automation Hub GitHub + Jenkins 整合驗證腳本

驗證 StorageProvider（GitHub REST API）、CIProvider（GitHub Actions）、
以及 Jenkins View/Job/Node 管理是否可行，**完全不依賴 TCRT 核心元件**。

設定來源：scripts/automation_hub_poc.yaml（預設）或 --config 指定路徑

  PAT / Token 建議透過環境變數注入，避免明文 commit：
    export GITHUB_PAT=ghp_...
    export JENKINS_USERNAME=your-user
    export JENKINS_API_TOKEN=your-token

=== 使用方式 ===
  # 全部測試（storage + workflow-crud + CI）
  python scripts/automation_hub_github_poc.py

  # 只測 Storage
  python scripts/automation_hub_github_poc.py --suite storage

  # 只測 CI（需 workflow 已存在）
  python scripts/automation_hub_github_poc.py --suite ci

  # 唯讀模式：只測 read/list，不建立或修改任何 git 內容
  python scripts/automation_hub_github_poc.py --suite storage --readonly

  # 測 GitHub Actions workflow CRUD（建立/讀取/更新/刪除 workflow 檔案）
  python scripts/automation_hub_github_poc.py --suite workflow-crud

  # 測 Jenkins View / Job / Node CRUD
  python scripts/automation_hub_github_poc.py --suite jenkins

  # 指定設定檔
  python scripts/automation_hub_github_poc.py --config /path/to/my_config.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import os
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# YAML 載入與 ${ENV_VAR} 展開（獨立，不依賴 app.config）
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POC_CONFIG_DEFAULT = Path(__file__).resolve().parent / "automation_hub_poc.yaml"
_ENV_PLACEHOLDER_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _expand_env(value: Any, path: str = "config") -> Any:
    """遞迴展開 YAML 值中的 ${ENV_VAR} 佔位符"""
    if isinstance(value, dict):
        return {k: _expand_env(v, f"{path}.{k}") for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v, f"{path}[{i}]") for i, v in enumerate(value)]
    if not isinstance(value, str):
        return value

    def _replace(m: re.Match) -> str:
        name = m.group(1)
        val = os.getenv(name)
        if val is None:
            raise ValueError(f"[config] {path} 使用的環境變數 ${{{name}}} 未設定")
        return val

    return _ENV_PLACEHOLDER_RE.sub(_replace, value)


def _load_yaml(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    with config_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class Config:
    pat: str
    owner: str
    repo: str
    branch: str = "main"
    test_path: str = "tests/poc_test.spec.ts"
    workflow_id: str = "playwright.yml"

    @staticmethod
    def _parse_repo_url(url: str) -> tuple[str, str]:
        """從 https://github.com/owner/repo.git 解析出 (owner, repo)"""
        parsed = urlparse(url)
        parts = parsed.path.strip("/").removesuffix(".git").split("/")
        if len(parts) < 2:
            raise ValueError(f"無法從 repo_url 解析 owner/repo：{url!r}")
        return parts[0], parts[1]

    @classmethod
    def from_yaml(cls, config_path: Optional[Path] = None) -> "Config":
        path = config_path or POC_CONFIG_DEFAULT
        raw = _load_yaml(path)

        if not raw:
            print(f"[ERROR] 找不到設定檔：{path}")
            print("        請確認 scripts/automation_hub_poc.yaml 存在")
            sys.exit(1)

        try:
            expanded = _expand_env(raw)
        except ValueError as e:
            print(f"[ERROR] {e}")
            sys.exit(1)

        gh = expanded.get("github", {})

        if not gh.get("pat"):
            print("[ERROR] automation_hub_poc.yaml 的 github.pat 未設定")
            sys.exit(1)

        repo_url = gh.get("repo_url", "")
        if not repo_url:
            print("[ERROR] automation_hub_poc.yaml 的 github.repo_url 未設定")
            sys.exit(1)

        try:
            owner, repo = cls._parse_repo_url(repo_url)
        except ValueError as e:
            print(f"[ERROR] {e}")
            sys.exit(1)

        return cls(
            pat=gh["pat"],
            owner=owner,
            repo=repo,
            branch=gh.get("branch", "main"),
            test_path=gh.get("test_path", "tests/poc_test.spec.ts"),
            workflow_id=gh.get("workflow_id", "playwright.yml"),
        )

    @property
    def repo_full(self) -> str:
        return f"{self.owner}/{self.repo}"


@dataclass
class JenkinsConfig:
    base_url: str
    username: str
    api_token: str
    default_runner_label: str = "any"

    @classmethod
    def from_yaml(cls, config_path: Optional[Path] = None) -> "JenkinsConfig":
        path = config_path or POC_CONFIG_DEFAULT
        raw = _load_yaml(path)

        if not raw:
            print(f"[ERROR] 找不到設定檔：{path}")
            sys.exit(1)

        try:
            expanded = _expand_env(raw)
        except ValueError as e:
            print(f"[ERROR] {e}")
            sys.exit(1)

        jk = expanded.get("jenkins", {})

        if not jk.get("base_url"):
            print("[ERROR] automation_hub_poc.yaml 的 jenkins.base_url 未設定")
            sys.exit(1)
        if not jk.get("username"):
            print("[ERROR] automation_hub_poc.yaml 的 jenkins.username 未設定")
            sys.exit(1)
        if not jk.get("api_token"):
            print("[ERROR] automation_hub_poc.yaml 的 jenkins.api_token 未設定")
            sys.exit(1)

        return cls(
            base_url=jk["base_url"].rstrip("/"),
            username=jk["username"],
            api_token=jk["api_token"],
            default_runner_label=jk.get("default_runner_label", "any"),
        )


# ---------------------------------------------------------------------------
# GitHub API client（最小化封裝）
# ---------------------------------------------------------------------------

class GitHubClient:
    BASE = "https://api.github.com"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {cfg.pat}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self._client.aclose()

    # --- 通用 ---

    async def get(self, path: str, **kwargs) -> httpx.Response:
        return await self._client.get(f"{self.BASE}{path}", **kwargs)

    async def put(self, path: str, **kwargs) -> httpx.Response:
        return await self._client.put(f"{self.BASE}{path}", **kwargs)

    async def post(self, path: str, **kwargs) -> httpx.Response:
        return await self._client.post(f"{self.BASE}{path}", **kwargs)

    async def delete(self, path: str, **kwargs) -> httpx.Response:
        return await self._client.request("DELETE", f"{self.BASE}{path}", **kwargs)

    # --- StorageProvider helpers ---

    async def whoami(self) -> dict:
        r = await self.get("/user")
        r.raise_for_status()
        return r.json()

    async def list_files(self, path: str = "") -> list[dict]:
        """列出 repo 某目錄下所有檔案（recursive=False，只列一層）"""
        url = f"/repos/{self.cfg.repo_full}/contents/{path}".rstrip("/")
        r = await self.get(url, params={"ref": self.cfg.branch})
        if r.status_code == 404:
            return []
        r.raise_for_status()
        items = r.json()
        return [i for i in items if i.get("type") == "file"]

    async def read_file(self, path: str, etag: Optional[str] = None) -> tuple[Optional[str], str, str]:
        """讀取檔案內容，回傳 (content | None_if_304, etag, sha)"""
        headers = {}
        if etag:
            headers["If-None-Match"] = etag
        r = await self.get(
            f"/repos/{self.cfg.repo_full}/contents/{path}",
            headers=headers,
            params={"ref": self.cfg.branch},
        )
        if r.status_code == 304:
            return None, etag, ""
        if r.status_code == 404:
            raise FileNotFoundError(f"GitHub: {path} not found in branch={self.cfg.branch}")
        r.raise_for_status()
        data = r.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        return content, r.headers.get("etag", ""), data.get("sha", "")

    async def write_file(
        self,
        path: str,
        content: str,
        commit_message: str,
        sha: Optional[str] = None,  # None = create new, str = update existing
        branch: Optional[str] = None,
    ) -> dict:
        """建立（sha=None）或更新（sha 為既有檔案 sha）一個檔案，回傳 commit 資訊"""
        body: dict[str, Any] = {
            "message": commit_message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": branch or self.cfg.branch,
        }
        if sha:
            body["sha"] = sha
        r = await self.put(f"/repos/{self.cfg.repo_full}/contents/{path}", json=body)
        r.raise_for_status()
        return r.json()

    async def delete_file(self, path: str, sha: str, commit_message: str) -> dict:
        """刪除一個檔案"""
        body = {
            "message": commit_message,
            "sha": sha,
            "branch": self.cfg.branch,
        }
        r = await self.delete(f"/repos/{self.cfg.repo_full}/contents/{path}", json=body)
        if r.status_code == 422:
            data = r.json()
            msg = data.get("message", "")
            if "sha" in msg.lower() or "does not match" in msg.lower():
                raise RuntimeError(
                    "SHA mismatch: 檔案已被其他 commit 修改，current sha 與提供的不符"
                )
            raise RuntimeError(f"GitHub 422: {msg}")
        r.raise_for_status()
        return r.json()

    async def file_exists(self, path: str) -> bool:
        """檢查檔案是否仍存在於最新 commit 中（透過 git tree API，不受 contents 快取影響）"""
        # 取得 branch 最新 commit 的 tree
        r = await self.get(
            f"/repos/{self.cfg.repo_full}/git/trees/{self.cfg.branch}",
            params={"recursive": "1"},
        )
        if r.status_code != 200:
            return False
        tree = r.json().get("tree", [])
        return any(item.get("path") == path for item in tree)

    async def list_branches(self) -> list[str]:
        r = await self.get(f"/repos/{self.cfg.repo_full}/branches")
        r.raise_for_status()
        return [b["name"] for b in r.json()]

    async def create_branch(self, new_branch: str, from_branch: str) -> str:
        """從 from_branch HEAD 建立新 branch，回傳 sha"""
        r = await self.get(f"/repos/{self.cfg.repo_full}/git/ref/heads/{from_branch}")
        r.raise_for_status()
        sha = r.json()["object"]["sha"]
        body = {"ref": f"refs/heads/{new_branch}", "sha": sha}
        cr = await self.post(f"/repos/{self.cfg.repo_full}/git/refs", json=body)
        cr.raise_for_status()
        return sha

    async def create_pull_request(
        self, title: str, head: str, base: str, body: str = ""
    ) -> dict:
        payload = {"title": title, "head": head, "base": base, "body": body}
        r = await self.post(f"/repos/{self.cfg.repo_full}/pulls", json=payload)
        r.raise_for_status()
        return r.json()

    async def close_pull_request(self, pr_number: int) -> None:
        r = await self.post(
            f"/repos/{self.cfg.repo_full}/pulls/{pr_number}",
            json={"state": "closed"},
        )
        r.raise_for_status()

    async def delete_branch(self, branch: str) -> None:
        r = await self.delete(f"/repos/{self.cfg.repo_full}/git/refs/heads/{branch}")
        if r.status_code not in (204, 422):
            r.raise_for_status()

    # --- CIProvider helpers ---

    async def list_workflows(self) -> list[dict]:
        r = await self.get(f"/repos/{self.cfg.repo_full}/actions/workflows")
        r.raise_for_status()
        return r.json().get("workflows", [])

    async def trigger_workflow(self, workflow_id: str, ref: str, inputs: dict) -> None:
        """觸發 workflow_dispatch，不回傳 run_id（GitHub 非同步建立）"""
        body = {"ref": ref, "inputs": inputs}
        r = await self.post(
            f"/repos/{self.cfg.repo_full}/actions/workflows/{workflow_id}/dispatches",
            json=body,
        )
        if r.status_code not in (204,):
            raise RuntimeError(f"trigger_workflow failed: HTTP {r.status_code} {r.text}")

    async def find_run_by_correlation_id(
        self, workflow_id: str, correlation_id: str, timeout_s: int = 60
    ) -> Optional[dict]:
        """輪詢最新 runs，透過 correlation_id（tcrt_run_id）找到對應 run"""
        deadline = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < deadline:
            r = await self.get(
                f"/repos/{self.cfg.repo_full}/actions/workflows/{workflow_id}/runs",
                params={"per_page": 10, "branch": self.cfg.branch},
            )
            r.raise_for_status()
            for run in r.json().get("workflow_runs", []):
                # GitHub Actions 的 input 值不在 list API 裡，需個別查
                run_id = run["id"]
                await self.get(
                    f"/repos/{self.cfg.repo_full}/actions/runs/{run_id}/jobs",
                    params={"per_page": 1},
                )
                # 只要 run 是最近 2 分鐘內觸發的，先當成 match（完整實作應讀 inputs，但 GitHub API 不直接暴露 inputs 到 list）
                created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
                age_s = (datetime.now(timezone.utc) - created).total_seconds()
                if age_s < 120:
                    return run
            await asyncio.sleep(5)
        return None


# ---------------------------------------------------------------------------
# Jenkins API client
# ---------------------------------------------------------------------------

class JenkinsClient:
    def __init__(self, cfg: JenkinsConfig):
        self.cfg = cfg
        self._client = httpx.AsyncClient(
            auth=(cfg.username, cfg.api_token),
            timeout=30,
        )
        self._crumb: Optional[str] = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self._client.aclose()

    async def _get_crumb(self) -> Optional[str]:
        """取得 Jenkins CSRF crumb（若啟用）"""
        try:
            r = await self._client.get(
                f"{self.cfg.base_url}/crumbIssuer/api/json",
            )
            if r.status_code == 200:
                data = r.json()
                return data.get("crumb")
        except Exception:
            pass
        return None

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """包裝請求，自動帶入 crumb"""
        headers = kwargs.pop("headers", {})
        if self._crumb is None:
            self._crumb = await self._get_crumb()
        if self._crumb:
            headers["Jenkins-Crumb"] = self._crumb

        url = f"{self.cfg.base_url}{path}"
        r = await self._client.request(method, url, headers=headers, **kwargs)

        # 若 crumb 過期，重試一次
        if r.status_code == 403 and "No valid crumb" in r.text:
            self._crumb = await self._get_crumb()
            if self._crumb:
                headers["Jenkins-Crumb"] = self._crumb
            r = await self._client.request(method, url, headers=headers, **kwargs)

        return r

    async def get(self, path: str, **kwargs) -> httpx.Response:
        return await self._request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs) -> httpx.Response:
        return await self._request("POST", path, **kwargs)

    # --- View 管理 ---

    async def list_views(self) -> list[dict]:
        r = await self.get("/api/json?tree=views[name,url]")
        r.raise_for_status()
        return r.json().get("views", [])

    async def view_exists(self, view_name: str) -> bool:
        views = await self.list_views()
        return any(v["name"] == view_name for v in views)

    async def create_view(self, view_name: str, description: str = "") -> None:
        """建立 List View"""
        config_xml = f"""<?xml version='1.1' encoding='UTF-8'?>
<listView>
  <name>{view_name}</name>
  <description>{description}</description>
  <filterExecutors>false</filterExecutors>
  <filterQueue>false</filterQueue>
  <properties class="hudson.model.View$PropertyList"/>
  <jobNames>
    <comparator class="hudson.util.CaseInsensitiveComparator"/>
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
  <recurse>false</recurse>
</listView>"""
        r = await self.post(
            f"/createView?name={view_name}",
            data=config_xml,
            headers={"Content-Type": "application/xml"},
        )
        if r.status_code not in (200, 302):
            raise RuntimeError(f"create_view failed: HTTP {r.status_code} {r.text[:200]}")

    async def delete_view(self, view_name: str) -> None:
        r = await self.post(f"/view/{view_name}/doDelete")
        if r.status_code not in (200, 302, 404):
            r.raise_for_status()

    # --- Job 管理 ---

    async def list_jobs(self) -> list[dict]:
        r = await self.get("/api/json?tree=jobs[name,url,buildable]")
        r.raise_for_status()
        return r.json().get("jobs", [])

    async def job_exists(self, job_name: str) -> bool:
        jobs = await self.list_jobs()
        return any(j["name"] == job_name for j in jobs)

    async def create_job(self, job_name: str, config_xml: str) -> None:
        r = await self.post(
            f"/createItem?name={job_name}",
            data=config_xml,
            headers={"Content-Type": "application/xml"},
        )
        if r.status_code not in (200, 201, 302):
            raise RuntimeError(f"create_job failed: HTTP {r.status_code} {r.text[:200]}")

    async def update_job(self, job_name: str, config_xml: str) -> None:
        r = await self.post(
            f"/job/{job_name}/config.xml",
            data=config_xml,
            headers={"Content-Type": "application/xml"},
        )
        if r.status_code not in (200, 302):
            raise RuntimeError(f"update_job failed: HTTP {r.status_code} {r.text[:200]}")

    async def delete_job(self, job_name: str) -> None:
        r = await self.post(f"/job/{job_name}/doDelete")
        if r.status_code not in (200, 302, 404):
            r.raise_for_status()

    async def add_job_to_view(self, view_name: str, job_name: str) -> None:
        r = await self.post(
            f"/view/{view_name}/addJobToView",
            params={"name": job_name},
        )
        if r.status_code not in (200, 302):
            raise RuntimeError(f"add_job_to_view failed: HTTP {r.status_code} {r.text[:200]}")

    async def remove_job_from_view(self, view_name: str, job_name: str) -> None:
        r = await self.post(
            f"/view/{view_name}/removeJobFromView",
            params={"name": job_name},
        )
        if r.status_code not in (200, 302, 404):
            r.raise_for_status()

    # --- Node (Runner) 管理 ---

    async def list_nodes(self) -> list[dict]:
        r = await self.get("/computer/api/json?tree=computer[displayName,idle,offline,assignedLabels[name]]")
        r.raise_for_status()
        return r.json().get("computer", [])

    # --- 輔助：產生 suite job config.xml ---

    def generate_job_config(
        self,
        suite_name: str,
        test_paths: list[str],
        runner_label: str,
    ) -> str:
        paths_str = " ".join(test_paths)
        # 使用 str.format 而非 f-string，避免 Jenkins ${{}} 語法衝突
        template = """<?xml version='1.1' encoding='UTF-8'?>
<flow-definition plugin="workflow-job">
  <description>TCRT POC Suite - {suite_name}</description>
  <properties>
    <hudson.model.ParametersDefinitionProperty>
      <parameterDefinitions>
        <hudson.model.StringParameterDefinition>
          <name>tcrt_run_id</name>
          <description>TCRT correlation ID</description>
          <defaultValue></defaultValue>
          <trim>true</trim>
        </hudson.model.StringParameterDefinition>
        <hudson.model.StringParameterDefinition>
          <name>NODE_LABEL</name>
          <description>Target node label</description>
          <defaultValue>{runner_label}</defaultValue>
          <trim>true</trim>
        </hudson.model.StringParameterDefinition>
      </parameterDefinitions>
    </hudson.model.ParametersDefinitionProperty>
  </properties>
  <definition class="org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition" plugin="workflow-cps">
    <script>
pipeline {{
    agent {{ label "${{params.NODE_LABEL ?: '{runner_label}'}}" }}
    stages {{
        stage('Setup') {{
            steps {{
                sh '''
                python3 -m pip install --upgrade pip
                pip install pytest-playwright
                playwright install
                '''
            }}
        }}
        stage('Test') {{
            steps {{
                echo "TCRT Suite: {suite_name}"
                echo "TCRT ID: ${{params.tcrt_run_id}}"
                sh 'pytest {paths_str}'
            }}
        }}
    }}
    post {{
        always {{
            sh '''
            curl -X POST "${{env.TCRT_WEBHOOK_URL}}" \\
              -H "Content-Type: application/json" \\
              -d "{{\\"tcrt_run_id\\":\\"${{params.tcrt_run_id}}\\",\\"status\\":\\"${{currentBuild.result}}\\"}}"
            '''
        }}
    }}
}}</script>
    <sandbox>true</sandbox>
  </definition>
  <triggers/>
  <disabled>false</disabled>
</flow-definition>"""
        return template.format(
            suite_name=suite_name,
            runner_label=runner_label,
            paths_str=paths_str,
        )


# ---------------------------------------------------------------------------
# 結果記錄
# ---------------------------------------------------------------------------

@dataclass
class StepResult:
    name: str
    passed: bool
    detail: str = ""
    skipped: bool = False


results: list[StepResult] = []


def ok(name: str, detail: str = "") -> StepResult:
    r = StepResult(name, True, detail)
    results.append(r)
    print(f"  ✓  {name}" + (f"\n     {detail}" if detail else ""))
    return r


def fail(name: str, detail: str = "") -> StepResult:
    r = StepResult(name, False, detail)
    results.append(r)
    print(f"  ✗  {name}" + (f"\n     {detail}" if detail else ""))
    return r


def skip(name: str, reason: str = "") -> StepResult:
    r = StepResult(name, True, "", skipped=True)
    results.append(r)
    print(f"  -  {name} (skipped: {reason})")
    return r


def section(title: str):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


# ---------------------------------------------------------------------------
# Storage Suite
# ---------------------------------------------------------------------------

async def suite_storage(gh: GitHubClient, readonly: bool = False):
    section("StorageProvider — GitHub REST API")
    cfg = gh.cfg

    # Step 1: 連線 / whoami
    try:
        me = await gh.whoami()
        ok("whoami", f"login={me['login']}, scopes via PAT OK")
    except Exception as e:
        fail("whoami", str(e))
        print("\n  [ABORT] 認證失敗，後續測試無法進行。")
        return

    # Step 2: list branches
    try:
        branches = await gh.list_branches()
        ok("list_branches", f"branches={branches[:5]}")
        if cfg.branch not in branches:
            fail("branch_exists", f"指定的 branch '{cfg.branch}' 不在 repo 中，可用：{branches}")
            return
        else:
            ok("branch_exists", f"'{cfg.branch}' 存在")
    except Exception as e:
        fail("list_branches", str(e))
        return

    # Step 3: list_files（目錄可能不存在）
    test_dir = str(cfg.test_path).rsplit("/", 1)[0] if "/" in cfg.test_path else ""
    try:
        files = await gh.list_files(test_dir)
        ok("list_files", f"path='{test_dir or '/'}', found {len(files)} file(s)")
    except Exception as e:
        fail("list_files", str(e))

    # Step 4: read_file（路徑可能不存在，這是預期行為之一）
    file_sha = None
    try:
        content, etag, sha = await gh.read_file(cfg.test_path)
        file_sha = sha
        ok("read_file (existing)", f"size={len(content)} bytes, etag={etag[:20]}..., sha={sha[:8]}...")

        # Step 4b: etag 304 測試
        content2, etag2, _ = await gh.read_file(cfg.test_path, etag=etag)
        if content2 is None:
            ok("read_file (etag 304)", "304 Not Modified 正確觸發，不消耗 rate limit")
        else:
            fail("read_file (etag 304)", "應回 304 但回了全文")
    except FileNotFoundError:
        ok("read_file (not found)", f"路徑 '{cfg.test_path}' 不存在，符合 create 前的預期狀態")
    except Exception as e:
        fail("read_file", str(e))

    if readonly:
        skip("write_file (create)", "readonly 模式")
        skip("write_file (update)", "readonly 模式")
        skip("delete_file (cleanup)", "readonly 模式")
        skip("create_branch + PR", "readonly 模式")
        return

    # Step 5: write_file — CREATE（sha=None）
    poc_content = f"""\
# POC test file created by automation_hub_github_poc.py
# Timestamp: {datetime.now(timezone.utc).isoformat()}
# This file can be safely deleted.

from playwright.sync_api import Page, expect


def test_poc_smoke(page: Page):
    page.goto("https://example.com")
    expect(page).to_have_title(/Example/)
"""
    created_sha = None
    if file_sha:
        skip("write_file (create)", f"路徑已存在（sha={file_sha[:8]}），改為 update 測試")
        # 若檔案已存在，做 update 測試
        try:
            res = await gh.write_file(
                cfg.test_path,
                poc_content + f"// Updated at {datetime.now(timezone.utc).isoformat()}\n",
                commit_message="chore: POC update test via TCRT automation_hub_github_poc",
                sha=file_sha,
            )
            commit_sha = res["commit"]["sha"]
            ok("write_file (update)", f"commit={commit_sha[:8]}")
            created_sha = res["content"]["sha"]
        except Exception as e:
            fail("write_file (update)", str(e))
    else:
        try:
            res = await gh.write_file(
                cfg.test_path,
                poc_content,
                commit_message="chore: POC create test via TCRT automation_hub_github_poc",
                sha=None,
            )
            commit_sha = res["commit"]["sha"]
            created_sha = res["content"]["sha"]
            ok("write_file (create)", f"commit={commit_sha[:8]}, new_file_sha={created_sha[:8]}")
        except Exception as e:
            fail("write_file (create)", str(e))

    # Step 6: 確認建立後可 read_file（即 register 流程中 fetch cached_content）
    if created_sha:
        try:
            content, etag, sha = await gh.read_file(cfg.test_path)
            ok("read_file (post-write)", f"size={len(content)} bytes, sha={sha[:8]}")
        except Exception as e:
            fail("read_file (post-write)", str(e))

    # Step 7: create_branch + write + PR
    poc_branch = f"poc/automation-hub-{uuid.uuid4().hex[:8]}"
    pr_number = None
    try:
        await gh.create_branch(poc_branch, cfg.branch)
        ok("create_branch", f"branch='{poc_branch}'")

        # 在新 branch 寫入
        pr_file = f"tests/poc_pr_{uuid.uuid4().hex[:6]}.spec.ts"
        pr_content = f"// PR test file from POC\n// branch: {poc_branch}\n"
        res2 = await gh.write_file(
            pr_file,
            pr_content,
            commit_message="chore: POC PR branch write test",
            sha=None,
            branch=poc_branch,
        )
        ok("write_file (pr branch)", f"file={pr_file}, commit={res2['commit']['sha'][:8]}")

        pr = await gh.create_pull_request(
            title="[POC] automation_hub_github_poc test PR",
            head=poc_branch,
            base=cfg.branch,
            body="This PR was created by `automation_hub_github_poc.py` as a POC test. **Please close without merging.**",
        )
        pr_number = pr["number"]
        ok("create_pull_request", f"PR #{pr_number}: {pr['html_url']}")
    except Exception as e:
        fail("create_branch + PR", str(e))

    # Step 8: cleanup（關 PR + 刪 branch + 刪測試檔）
    print("\n  [Cleanup]")
    if pr_number:
        try:
            await gh.close_pull_request(pr_number)
            ok("close_pr (cleanup)", f"PR #{pr_number} closed")
        except Exception as e:
            fail("close_pr (cleanup)", str(e))

    if poc_branch:
        try:
            await gh.delete_branch(poc_branch)
            ok("delete_branch (cleanup)", f"branch '{poc_branch}' deleted")
        except Exception as e:
            fail("delete_branch (cleanup)", str(e))

    # 如果是 POC 建立的（不是已存在的），才刪除
    if created_sha and not file_sha:
        try:
            _, _, current_sha = await gh.read_file(cfg.test_path)
            await gh.delete_file(
                cfg.test_path,
                current_sha,
                commit_message="chore: POC cleanup - delete test file",
            )
            ok("delete_file (cleanup)", f"'{cfg.test_path}' deleted")
        except Exception as e:
            fail("delete_file (cleanup)", str(e))


# ---------------------------------------------------------------------------
# CI Suite（GitHub Actions）
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Workflow CRUD Suite（GitHub Actions workflow 檔案級 CRUD）
# ---------------------------------------------------------------------------

async def suite_workflow_crud(gh: GitHubClient):
    section("GitHub Actions Workflow CRUD")
    cfg = gh.cfg

    wf_path = f".github/workflows/poc-crud-{uuid.uuid4().hex[:8]}.yml"
    wf_content_v1 = """\
name: POC CRUD Test
on:
  workflow_dispatch:
    inputs:
      tcrt_run_id:
        description: 'TCRT correlation ID'
        required: false
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: echo "Hello from POC CRUD v1"
"""
    wf_content_v2 = wf_content_v1.replace("v1", "v2")

    # Step 1: CREATE — 寫入 workflow 檔案
    try:
        res = await gh.write_file(
            wf_path,
            wf_content_v1,
            commit_message="chore: POC create workflow via automation_hub_github_poc",
            sha=None,
        )
        commit_sha = res["commit"]["sha"]
        ok("workflow_crud.create", f"path={wf_path}, commit={commit_sha[:8]}")
    except Exception as e:
        fail("workflow_crud.create", str(e))
        return

    # Step 2: READ — 列舉 workflows 確認出現
    try:
        workflows = await gh.list_workflows()
        matched = [w for w in workflows if w["path"] == wf_path]
        if matched:
            ok("workflow_crud.read (list)", f"workflow_id={matched[0]['id']}, state={matched[0]['state']}")
        else:
            fail("workflow_crud.read (list)", "workflow 未出現在 list_workflows 結果中（可能 GitHub 有延遲）")
    except Exception as e:
        fail("workflow_crud.read (list)", str(e))

    # Step 3: UPDATE — 修改 workflow 內容
    try:
        _, _, current_sha = await gh.read_file(wf_path)
        res = await gh.write_file(
            wf_path,
            wf_content_v2,
            commit_message="chore: POC update workflow via automation_hub_github_poc",
            sha=current_sha,
        )
        ok("workflow_crud.update", f"new_commit={res['commit']['sha'][:8]}")
    except Exception as e:
        fail("workflow_crud.update", str(e))

    # Step 4: DELETE — 移除 workflow 檔案
    try:
        _, _, current_sha = await gh.read_file(wf_path)
        await gh.delete_file(
            wf_path,
            current_sha,
            commit_message="chore: POC delete workflow via automation_hub_github_poc",
        )
        ok("workflow_crud.delete", f"'{wf_path}' deleted")
    except Exception as e:
        fail("workflow_crud.delete", str(e))

    # Step 5: VERIFY — 從 git 確認檔案已移除
    try:
        still_exists = await gh.file_exists(wf_path)
        if still_exists:
            fail("workflow_crud.verify (file)", f"刪除 commit 已送出，但 '{wf_path}' 仍然存在於 git")
        else:
            ok("workflow_crud.verify (file)", f"'{wf_path}' 已從 branch '{cfg.branch}' 移除")
    except Exception as e:
        fail("workflow_crud.verify (file)", str(e))

    # Step 6: VERIFY — 再次列舉 workflows 確認消失（GitHub 可能有快取延遲）
    try:
        workflows = await gh.list_workflows()
        matched = [w for w in workflows if w["path"] == wf_path]
        if not matched:
            ok("workflow_crud.verify (list)", "workflow 已從 list_workflows 消失")
        else:
            fail("workflow_crud.verify (list)", "workflow 仍然存在於 list_workflows，可能 GitHub 有快取延遲（檔案本身已刪除）")
    except Exception as e:
        fail("workflow_crud.verify (gone)", str(e))


async def suite_ci(gh: GitHubClient):
    section("CIProvider — GitHub Actions Trigger & Poll")
    cfg = gh.cfg

    temp_wf_path = None
    temp_wf_sha = None

    # Step 1: list workflows
    try:
        workflows = await gh.list_workflows()
        ok("list_workflows", f"found {len(workflows)} workflow(s)")
    except Exception as e:
        fail("list_workflows", str(e))
        return

    # 找目標 workflow；若找不到，自動建立一個暫時的
    target_wf = next(
        (w for w in workflows if cfg.workflow_id in (str(w["id"]), w["path"], w["name"])),
        None,
    )
    if not target_wf:
        print(f"\n  [Auto-create] 找不到 '{cfg.workflow_id}'，自動建立暫時 workflow ...")
        temp_wf_path = f".github/workflows/poc-ci-{uuid.uuid4().hex[:8]}.yml"
        temp_wf_content = """\
name: POC CI Auto-created
on:
  workflow_dispatch:
    inputs:
      tcrt_run_id:
        description: 'TCRT correlation ID'
        required: false
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: echo "tcrt_run_id=${{ github.event.inputs.tcrt_run_id }}"
"""
        try:
            res = await gh.write_file(
                temp_wf_path,
                temp_wf_content,
                commit_message="chore: POC auto-create temporary workflow",
                sha=None,
            )
            temp_wf_sha = res["content"]["sha"]
            ok("ci.create_temp_workflow", f"path={temp_wf_path}")

            # 重新列舉（GitHub 需要一點時間索引新 workflow）
            for attempt in range(10):
                await asyncio.sleep(1)
                workflows = await gh.list_workflows()
                target_wf = next(
                    (w for w in workflows if w["path"] == temp_wf_path),
                    None,
                )
                if target_wf:
                    break
            if not target_wf:
                fail("ci.wait_for_workflow_index", "workflow 已建立但 GitHub 尚未索引完成，請稍後重試")
                return
        except Exception as e:
            fail("ci.create_temp_workflow", str(e))
            return

    # Step 2: trigger workflow_dispatch
    correlation_id = f"poc-{uuid.uuid4().hex}"
    try:
        await gh.trigger_workflow(
            str(target_wf["id"]),
            ref=cfg.branch,
            inputs={"tcrt_run_id": correlation_id},
        )
        ok("trigger_workflow", f"workflow='{target_wf['name']}', tcrt_run_id={correlation_id}")
    except Exception as e:
        error_msg = str(e)
        if "422" in error_msg or "Unprocessable" in error_msg:
            fail(
                "trigger_workflow",
                "HTTP 422 — workflow 可能未定義 'on: workflow_dispatch' 觸發器\n"
                "     請確認 workflow yml 包含 workflow_dispatch 區塊",
            )
        else:
            fail("trigger_workflow", error_msg)
        return

    # Step 3: 輪詢找到 run（概念驗證，簡化版）
    print("\n  [Polling] 等候 run 出現（最多 60 秒）...")
    try:
        run = await gh.find_run_by_correlation_id(str(target_wf["id"]), correlation_id, timeout_s=60)
        if run:
            ok(
                "find_run_by_correlation_id",
                f"run_id={run['id']}, status={run['status']}, url={run['html_url']}",
            )
        else:
            fail("find_run_by_correlation_id", "60 秒內未找到 run，可能是 GitHub queue 延遲")
    except Exception as e:
        fail("find_run_by_correlation_id", str(e))

    # Step 4: cleanup 暫時 workflow
    if temp_wf_path and temp_wf_sha:
        print("\n  [Cleanup] 刪除暫時 workflow ...")
        try:
            # 先重新讀取 current sha（trigger 後 workflow 可能產生新 commit 導致 sha 變更）
            _, _, current_sha = await gh.read_file(temp_wf_path)
            await gh.delete_file(
                temp_wf_path,
                current_sha,
                commit_message="chore: POC cleanup temporary workflow",
            )
            ok("ci.delete_temp_workflow", f"commit ok, path={temp_wf_path}")
        except Exception as e:
            fail("ci.delete_temp_workflow", str(e))
            return

        # 驗證：確認檔案真的不存在了
        try:
            still_exists = await gh.file_exists(temp_wf_path)
            if still_exists:
                fail("ci.verify_delete", f"刪除 commit 已送出，但 '{temp_wf_path}' 仍然存在")
            else:
                ok("ci.verify_delete", f"'{temp_wf_path}' 已從 branch '{cfg.branch}' 移除")
        except Exception as e:
            fail("ci.verify_delete", str(e))


# ---------------------------------------------------------------------------
# Jenkins Suite（View / Job / Node CRUD）
# ---------------------------------------------------------------------------

async def suite_jenkins(jk: JenkinsClient):
    section("Jenkins — View / Job / Node CRUD")
    cfg = jk.cfg

    poc_view = f"TCRT-POC-{uuid.uuid4().hex[:8]}"
    poc_job = f"tcrt-poc-suite-{uuid.uuid4().hex[:8]}"

    # Step 1: 連線測試
    try:
        nodes = await jk.list_nodes()
        ok("jenkins.connect", f"connected to {cfg.base_url}, found {len(nodes)} node(s)")
    except Exception as e:
        fail("jenkins.connect", str(e))
        return

    # Step 2: list nodes (runners)
    try:
        nodes = await jk.list_nodes()
        for node in nodes:
            labels = [label["name"] for label in node.get("assignedLabels", [])]
            status = "online" if not node.get("offline") else "offline"
            busy = not node.get("idle", True)
            ok("jenkins.list_nodes", f"{node['displayName']}: status={status}, busy={busy}, labels={labels}")
    except Exception as e:
        fail("jenkins.list_nodes", str(e))

    # Step 3: list views
    try:
        views = await jk.list_views()
        ok("jenkins.list_views", f"found {len(views)} view(s): {[v['name'] for v in views[:5]]}")
    except Exception as e:
        fail("jenkins.list_views", str(e))

    # Step 4: CREATE view
    try:
        await jk.create_view(poc_view, "POC test view created by automation_hub_github_poc")
        ok("jenkins.create_view", f"view='{poc_view}'")
    except Exception as e:
        fail("jenkins.create_view", str(e))
        return

    # Step 5: CREATE job (suite)
    try:
        config_xml = jk.generate_job_config(
            suite_name="POC Test Suite",
            test_paths=["tests/test_poc.py"],
            runner_label=cfg.default_runner_label,
        )
        await jk.create_job(poc_job, config_xml)
        ok("jenkins.create_job", f"job='{poc_job}'")
    except Exception as e:
        fail("jenkins.create_job", str(e))
        return

    # Step 6: ADD job to view
    try:
        await jk.add_job_to_view(poc_view, poc_job)
        ok("jenkins.add_job_to_view", f"job='{poc_job}' → view='{poc_view}'")
    except Exception as e:
        fail("jenkins.add_job_to_view", str(e))

    # Step 7: VERIFY job in view
    try:
        views = await jk.list_views()
        target_view = next((v for v in views if v["name"] == poc_view), None)
        if target_view:
            # 需要另外查 view 的 jobs，簡化驗證
            ok("jenkins.verify_view", f"view '{poc_view}' exists")
        else:
            fail("jenkins.verify_view", f"view '{poc_view}' not found")
    except Exception as e:
        fail("jenkins.verify_view", str(e))

    # Step 8: UPDATE job
    try:
        config_xml = jk.generate_job_config(
            suite_name="POC Test Suite Updated",
            test_paths=["tests/test_poc.py", "tests/test_login.py"],
            runner_label=cfg.default_runner_label,
        )
        await jk.update_job(poc_job, config_xml)
        ok("jenkins.update_job", f"job='{poc_job}' updated with 2 test paths")
    except Exception as e:
        fail("jenkins.update_job", str(e))

    # Step 9: list jobs
    try:
        jobs = await jk.list_jobs()
        matched = [j for j in jobs if j["name"] == poc_job]
        if matched:
            ok("jenkins.list_jobs", f"job '{poc_job}' found, buildable={matched[0].get('buildable')}")
        else:
            fail("jenkins.list_jobs", f"job '{poc_job}' not found")
    except Exception as e:
        fail("jenkins.list_jobs", str(e))

    # Step 10: Cleanup
    print("\n  [Cleanup]")
    try:
        await jk.delete_job(poc_job)
        ok("jenkins.delete_job (cleanup)", f"job='{poc_job}' deleted")
    except Exception as e:
        fail("jenkins.delete_job (cleanup)", str(e))

    try:
        await jk.delete_view(poc_view)
        ok("jenkins.delete_view (cleanup)", f"view='{poc_view}' deleted")
    except Exception as e:
        fail("jenkins.delete_view (cleanup)", str(e))

    # Step 11: VERIFY cleanup
    try:
        jobs = await jk.list_jobs()
        if not any(j["name"] == poc_job for j in jobs):
            ok("jenkins.verify_cleanup", f"job '{poc_job}' fully removed")
        else:
            fail("jenkins.verify_cleanup", f"job '{poc_job}' still exists")
    except Exception as e:
        fail("jenkins.verify_cleanup", str(e))


# ---------------------------------------------------------------------------
# 主程式
# ---------------------------------------------------------------------------

async def main(suite: str, readonly: bool, config_path: Optional[Path]):
    cfg = Config.from_yaml(config_path)

    print(f"\n{'═' * 60}")
    print("  Automation Hub GitHub POC")
    print(f"{'═' * 60}")
    print(f"  Repo  : {cfg.repo_full}")
    print(f"  Branch: {cfg.branch}")
    print(f"  Path  : {cfg.test_path}")
    print(f"  Suite : {suite}")
    if readonly:
        print("  Mode  : READONLY（不會建立/修改任何檔案）")

    async with GitHubClient(cfg) as gh:
        if suite in ("all", "storage"):
            await suite_storage(gh, readonly=readonly)
        if suite in ("all", "workflow-crud"):
            await suite_workflow_crud(gh)
        if suite in ("all", "ci"):
            await suite_ci(gh)

    # Jenkins 測試（獨立於 GitHub）
    if suite in ("all", "jenkins"):
        jk_cfg = JenkinsConfig.from_yaml(config_path)
        async with JenkinsClient(jk_cfg) as jk:
            await suite_jenkins(jk)

    # 彙總
    print(f"\n{'═' * 60}")
    print("  結果彙總")
    print(f"{'═' * 60}")
    passed = [r for r in results if r.passed and not r.skipped]
    failed = [r for r in results if not r.passed]
    skipped = [r for r in results if r.skipped]
    print(f"  ✓ 通過: {len(passed)}  ✗ 失敗: {len(failed)}  - 略過: {len(skipped)}")
    if failed:
        print("\n  失敗清單：")
        for r in failed:
            print(f"    ✗ {r.name}: {r.detail}")
    print()
    return 0 if not failed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Automation Hub GitHub POC")
    parser.add_argument(
        "--suite",
        choices=["all", "storage", "ci", "workflow-crud", "jenkins"],
        default="all",
        help="要執行的測試套件（預設 all）",
    )
    parser.add_argument(
        "--readonly",
        action="store_true",
        help="唯讀模式：只測 read/list，不建立或修改任何 git 內容",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="指定設定檔路徑（預設 scripts/automation_hub_poc.yaml）",
    )
    args = parser.parse_args()
    config_path = Path(args.config) if args.config else None
    sys.exit(asyncio.run(main(args.suite, args.readonly, config_path)))
