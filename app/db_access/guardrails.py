from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
from typing import Iterable, Sequence

import yaml


DEFAULT_SCAN_PATHS: tuple[str, ...] = (
    "app/api",
    "app/auth",
    "app/services",
    "scripts",
    "ai",
)


@dataclass(frozen=True)
class GuardrailRule:
    rule_id: str
    message: str
    inline_rule: str
    allowed_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class GuardrailViolation:
    rule_id: str
    file_path: str
    line: int
    column: int
    snippet: str
    message: str


GUARDRAIL_RULES: tuple[GuardrailRule, ...] = (
    GuardrailRule(
        rule_id="no-direct-sessionlocal",
        message="請改用受管 boundary，不要直接呼叫 SessionLocal()。",
        inline_rule=(
            "id: no-direct-sessionlocal\n"
            "language: python\n"
            "severity: error\n"
            "message: Use managed boundary instead of SessionLocal().\n"
            "rule:\n"
            "  pattern: SessionLocal()"
        ),
    ),
    GuardrailRule(
        rule_id="no-direct-usm-session-factory",
        message="請改用 UsmAccessBoundary，不要直接呼叫 USMAsyncSessionLocal()。",
        inline_rule=(
            "id: no-direct-usm-session-factory\n"
            "language: python\n"
            "severity: error\n"
            "message: Use managed boundary instead of USMAsyncSessionLocal().\n"
            "rule:\n"
            "  pattern: USMAsyncSessionLocal()"
        ),
    ),
    GuardrailRule(
        rule_id="no-direct-get-async-session",
        message="請透過 MainAccessBoundary，而不是直接呼叫 get_async_session()。",
        inline_rule=(
            "id: no-direct-get-async-session\n"
            "language: python\n"
            "severity: error\n"
            "message: Use MainAccessBoundary instead of get_async_session().\n"
            "rule:\n"
            "  pattern: get_async_session()"
        ),
    ),
    GuardrailRule(
        rule_id="no-direct-get-audit-session",
        message="請透過 AuditAccessBoundary，而不是直接呼叫 get_audit_session()。",
        inline_rule=(
            "id: no-direct-get-audit-session\n"
            "language: python\n"
            "severity: error\n"
            "message: Use AuditAccessBoundary instead of get_audit_session().\n"
            "rule:\n"
            "  pattern: get_audit_session()"
        ),
    ),
    GuardrailRule(
        rule_id="no-direct-commit",
        message="受管模組外禁止直接 commit()。",
        inline_rule=(
            "id: no-direct-commit\n"
            "language: python\n"
            "severity: error\n"
            "message: Do not commit directly outside managed boundaries.\n"
            "rule:\n"
            "  pattern: $SESSION.commit()"
        ),
        allowed_paths=(
            "app/api/user_story_maps.py",
            "app/services/system_init_service.py",
        ),
    ),
    GuardrailRule(
        rule_id="no-direct-rollback",
        message="受管模組外禁止直接 rollback()。",
        inline_rule=(
            "id: no-direct-rollback\n"
            "language: python\n"
            "severity: error\n"
            "message: Do not rollback directly outside managed boundaries.\n"
            "rule:\n"
            "  pattern: $SESSION.rollback()"
        ),
        allowed_paths=("app/services/system_init_service.py",),
    ),
    GuardrailRule(
        rule_id="no-direct-execute-text",
        message="受管模組外禁止直接 execute(text(...))。",
        inline_rule=(
            "id: no-direct-execute-text\n"
            "language: python\n"
            "severity: error\n"
            "message: Move raw SQL behind a managed boundary or adapter.\n"
            "rule:\n"
            "  pattern: $SESSION.execute(text($SQL))"
        ),
    ),
)


def scan_db_access_guardrails(
    repo_root: Path,
    *,
    scan_paths: Sequence[str] | None = None,
    policy_path: Path | None = None,
) -> list[GuardrailViolation]:
    resolved_root = repo_root.resolve()
    policy = _load_policy(policy_path or resolved_root / "config" / "db_access_policy.yaml")
    shared_allowed_paths = tuple(_iter_allowed_exception_paths(policy))
    paths = tuple(scan_paths or DEFAULT_SCAN_PATHS)

    violations: list[GuardrailViolation] = []
    for rule in GUARDRAIL_RULES:
        matches = _run_ast_grep_scan(
            repo_root=resolved_root,
            inline_rule=rule.inline_rule,
            scan_paths=paths,
        )
        for match in matches:
            relative_file = _to_relative_repo_path(resolved_root, Path(match["file"]))
            if _is_allowed_path(relative_file, shared_allowed_paths):
                continue
            if _is_allowed_path(relative_file, rule.allowed_paths):
                continue
            start = match["range"]["start"]
            violations.append(
                GuardrailViolation(
                    rule_id=rule.rule_id,
                    file_path=relative_file,
                    line=int(start["line"]),
                    column=int(start["column"]),
                    snippet=str(match.get("lines") or "").strip(),
                    message=rule.message,
                )
            )
    return sorted(
        violations,
        key=lambda item: (item.file_path, item.line, item.column, item.rule_id),
    )


def format_guardrail_violations(violations: Sequence[GuardrailViolation]) -> str:
    if not violations:
        return "DB access guardrails passed."
    lines = ["DB access guardrail violations:"]
    for violation in violations:
        lines.append(
            f"- [{violation.rule_id}] {violation.file_path}:{violation.line}:{violation.column} {violation.message}"
        )
        if violation.snippet:
            lines.append(f"  {violation.snippet}")
    return "\n".join(lines)


def _load_policy(policy_path: Path) -> dict:
    return yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}


def _iter_allowed_exception_paths(policy: dict) -> Iterable[str]:
    allowed_exceptions = policy.get("allowed_exceptions") or {}
    for entries in allowed_exceptions.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, str) and entry:
                yield entry


def _run_ast_grep_scan(
    *,
    repo_root: Path,
    inline_rule: str,
    scan_paths: Sequence[str],
) -> list[dict]:
    command = [
        "ast-grep",
        "scan",
        "--inline-rules",
        inline_rule,
        "--globs",
        "**/*.py",
        "--json=stream",
        *scan_paths,
    ]
    result = subprocess.run(
        command,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(
            f"ast-grep scan failed with exit code {result.returncode}: {result.stderr.strip()}"
        )
    matches: list[dict] = []
    for raw_line in result.stdout.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        matches.append(json.loads(stripped))
    return matches


def _to_relative_repo_path(repo_root: Path, file_path: Path) -> str:
    return file_path.resolve().relative_to(repo_root).as_posix()


def _is_allowed_path(relative_path: str, allowed_paths: Sequence[str]) -> bool:
    for allowed in allowed_paths:
        normalized = allowed.strip().replace("\\", "/")
        if not normalized:
            continue
        if normalized.endswith("/"):
            if relative_path.startswith(normalized):
                return True
            continue
        if relative_path == normalized:
            return True
        if relative_path.startswith(f"{normalized}/"):
            return True
    return False
