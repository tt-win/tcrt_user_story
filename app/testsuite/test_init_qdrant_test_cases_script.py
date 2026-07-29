"""Tests for the guarded Qdrant Test Case initialization script."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.init_qdrant_test_cases import PROJECT_ROOT, main


def _write_env(path: Path, *, include_api_key: bool = True) -> str:
    secret = "embedding-secret-value"
    lines = [
        "DATABASE_URL=postgresql+asyncpg://db-user:db-password@db.example:5432/tcrt_main",
        "KNOWLEDGE_GRAPH_ENABLED=true",
        "QDRANT_URL=https://q-user:q-password@qdrant.example:6333?token=hidden",
        "QDRANT_COLLECTION_TEST_CASES=test_cases_init",
        "EMBEDDING_PROVIDER=openrouter",
        "EMBEDDING_MODEL=example/embedding-model",
        "EMBEDDING_DIMENSIONS=1024",
        "KNOWLEDGE_BACKFILL_BATCH_SIZE=50",
    ]
    if include_api_key:
        lines.append(f"EMBEDDING_API_KEY={secret}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return secret


def test_dry_run_redacts_credentials_and_does_not_execute(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env_path = tmp_path / ".env"
    secret = _write_env(env_path)
    called = False

    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[object]:
        nonlocal called
        called = True
        return subprocess.CompletedProcess([], 0)

    rc = main(["--dry-run"], env_path=env_path, run_command=fake_run)

    output = capsys.readouterr()
    assert rc == 0
    assert called is False
    assert "db.example:5432/tcrt_main" in output.out
    assert "qdrant.example:6333" in output.out
    assert "test_cases_init" in output.out
    assert "db-password" not in output.out
    assert "q-password" not in output.out
    assert "token=hidden" not in output.out
    assert secret not in output.out
    assert output.err == ""


def test_yes_executes_canonical_backfill_with_dotenv_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = tmp_path / ".env"
    _write_env(env_path)
    monkeypatch.setenv("QDRANT_URL", "https://ambient.example:6333")
    captured: dict[str, object] = {}

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[object]:
        captured["command"] = command
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0)

    rc = main(["--yes"], env_path=env_path, run_command=fake_run)

    assert rc == 0
    assert captured["command"] == [
        sys.executable,
        "-m",
        "app.services.knowledge",
        "backfill",
        "--entity",
        "test_cases",
    ]
    assert captured["cwd"] == PROJECT_ROOT
    assert captured["check"] is False
    child_env = captured["env"]
    assert isinstance(child_env, dict)
    assert child_env["QDRANT_URL"].startswith("https://q-user:q-password@qdrant.example")
    assert child_env["QDRANT_URL"] != "https://ambient.example:6333"


def test_execution_requires_yes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    env_path = tmp_path / ".env"
    _write_env(env_path)
    called = False

    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[object]:
        nonlocal called
        called = True
        return subprocess.CompletedProcess([], 0)

    rc = main([], env_path=env_path, run_command=fake_run)

    output = capsys.readouterr()
    assert rc == 2
    assert called is False
    assert "--dry-run" in output.err
    assert "--yes" in output.err


def test_missing_project_env_is_rejected(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = main(["--dry-run"], env_path=tmp_path / ".env")

    output = capsys.readouterr()
    assert rc == 2
    assert "找不到專案環境檔" in output.err


def test_missing_required_values_are_reported_without_values(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("KNOWLEDGE_GRAPH_ENABLED=true\n", encoding="utf-8")

    rc = main(["--dry-run"], env_path=env_path)

    output = capsys.readouterr()
    assert rc == 2
    assert "DATABASE_URL" in output.err
    assert "QDRANT_URL" in output.err
    assert "EMBEDDING_MODEL" in output.err


def test_openrouter_requires_embedding_api_key(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env_path = tmp_path / ".env"
    _write_env(env_path, include_api_key=False)

    rc = main(["--dry-run"], env_path=env_path)

    output = capsys.readouterr()
    assert rc == 2
    assert "EMBEDDING_API_KEY" in output.err
