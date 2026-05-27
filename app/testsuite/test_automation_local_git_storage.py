"""Smoke tests for the LocalGit storage provider.

Uses a real tmpdir git repo because the provider shells out to `git` CLI —
mocking the subprocess would be more fragile than just exercising the happy
path on a tiny disposable repo. Skips automatically if git is not available
(the suite still passes in air-gapped CI without git).
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from app.services.automation.providers.local_git_storage import (
    LocalGitStorageProvider,
)

GIT_BIN = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT_BIN is None, reason="git CLI not available")


def _run(args, cwd):
    subprocess.run(args, cwd=str(cwd), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.fixture
def local_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run([GIT_BIN, "init", "-q", "-b", "main"], cwd=repo)
    _run([GIT_BIN, "config", "user.email", "ci@example.com"], cwd=repo)
    _run([GIT_BIN, "config", "user.name", "CI Bot"], cwd=repo)

    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_login.py").write_text("def test_login(): pass\n")
    (tests_dir / "test_logout.py").write_text("def test_logout(): pass\n")
    (repo / "README.md").write_text("# test repo\n")

    _run([GIT_BIN, "add", "-A"], cwd=repo)
    _run([GIT_BIN, "commit", "-q", "-m", "seed"], cwd=repo)
    return repo


@pytest.mark.asyncio
async def test_local_git_list_scripts_returns_tests_recursively(local_repo):
    provider = LocalGitStorageProvider(
        config={"working_dir": str(local_repo), "default_branch": "main"},
        credentials={},
    )
    items = await provider.list_scripts("tests")
    paths = sorted(item.path for item in items)
    assert "tests/test_login.py" in paths
    assert "tests/test_logout.py" in paths


@pytest.mark.asyncio
async def test_local_git_read_script_returns_file_content(local_repo):
    provider = LocalGitStorageProvider(
        config={"working_dir": str(local_repo), "default_branch": "main"},
        credentials={},
    )
    content = await provider.read_script("tests/test_login.py")
    assert "def test_login" in content.content


@pytest.mark.asyncio
async def test_local_git_health_check_passes_on_valid_repo(local_repo):
    provider = LocalGitStorageProvider(
        config={"working_dir": str(local_repo), "default_branch": "main"},
        credentials={},
    )
    status = await provider.health_check()
    assert status.status == "OK"


@pytest.mark.asyncio
async def test_local_git_health_check_fails_on_non_repo(tmp_path):
    not_a_repo = tmp_path / "empty"
    not_a_repo.mkdir()
    provider = LocalGitStorageProvider(
        config={"working_dir": str(not_a_repo), "default_branch": "main"},
        credentials={},
    )
    status = await provider.health_check()
    assert status.status == "FAILED"


@pytest.mark.asyncio
async def test_local_git_create_pull_request_returns_none(local_repo):
    """LocalGit intentionally has no PR primitive (§10.3)."""
    provider = LocalGitStorageProvider(
        config={"working_dir": str(local_repo), "default_branch": "main"},
        credentials={},
    )
    pr = await provider.create_pull_request("feature", "title", "body")
    assert pr is None
