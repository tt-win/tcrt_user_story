"""Contract checks for the canonical portable tcrt-app skill."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "tools" / "skills" / "tcrt-app"
SKILL = SKILL_ROOT / "SKILL.md"
USAGE = SKILL_ROOT / "references" / "api-usage-guide.md"
REFERENCE = SKILL_ROOT / "references" / "api-reference.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_canonical_skill_files_are_not_ignored() -> None:
    for path in (SKILL, USAGE, REFERENCE):
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(path)],
            cwd=ROOT,
            check=False,
        )
        assert result.returncode == 1
    assert (SKILL_ROOT / ".env").exists()
    ignored_env = subprocess.run(
        ["git", "check-ignore", "-q", str(SKILL_ROOT / ".env")],
        cwd=ROOT,
        check=False,
    )
    assert ignored_env.returncode == 0


def test_workflow_guide_has_exact_creation_and_transfer_contracts() -> None:
    text = _text(USAGE)
    required = (
        "/test-case-sets",
        "roots_only=true&include_empty=true",
        'name=="Unassigned"',
        "/test-cases/batch",
        "/impact-preview/move-test-set",
        "/test-cases/move-test-set",
        "impact_fingerprint",
        '"update_data":{"section_id":31}',
        "include_archived=true",
        "/members/batch-move",
        "expected_memberships",
        "expected_source_set_id",
        "final state verified; original outcome and cleanup count unknown",
    )
    for phrase in required:
        assert phrase in text


def test_workflow_guide_has_identity_and_unsupported_boundaries() -> None:
    text = _text(USAGE)
    for phrase in (
        '"assignee":{"id":"ou_..."',
        '"assignee_name":"Alice"',
        "assignee_user_id",
        "App Token 沒有 contact lookup",
        "Section tree cross-Set move/reorder",
        "Run Item cross-config move/copy",
        "Batch permanent delete Test Runs/Sets",
        "bulk-clone` directly-to-target-set",
    ):
        assert phrase in text


def test_reference_does_not_claim_case_moves_are_unavailable() -> None:
    text = _text(REFERENCE)
    assert "Moving/copying/reordering cases between sets or sections is not exposed" not in text
    assert "/test-cases/impact-preview/move-test-set" in text
    assert "/test-cases/move-test-set" in text
    assert "APP_TOKEN_IMPACT_CHANGED" in text
    assert "APP_TOKEN_STATE_CHANGED" in text


@pytest.mark.parametrize(
    "script,command",
    [
        ("scripts/tcrt_api.sh", ["sh"]),
        ("scripts/tcrt_api.py", [sys.executable]),
    ],
)
def test_clients_reject_non_origin_base_urls(script: str, command: list[str]) -> None:
    result = subprocess.run(
        [*command, str(SKILL_ROOT / script), "check"],
        cwd=SKILL_ROOT,
        env={
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "TCRT_BASE_URL": "https://user:secret@example.com/api?token=bad",
            "TCRT_APP_TOKEN": "test-token-must-not-appear",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "must be an http/https origin" in result.stderr
    assert "test-token-must-not-appear" not in result.stdout + result.stderr


def test_skill_provenance_guidance_is_safe_and_powershell_specific() -> None:
    text = _text(SKILL)
    assert "[tcrt-app] TCRT_BASE_URL=<origin>" in text
    assert "Never echo a\n`TCRT_*` variable" in text
    assert "PowerShell prompt" in text
    assert "not `cmd.exe`" in text
