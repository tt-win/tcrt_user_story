"""Smart Suite Recommendation (§4.5).

Deterministic rule-based scanner with optional LLM enrichment that proposes
Suite groupings from the team's storage repo. Smart Scan API requests persist a
scan run and execute this scanner in the background.

Pipeline:
1. Load optional `tcrt-automation.yml` manifest from repo root.
2. Resolve effective scan config (manifest > provider.smart_scan > defaults).
3. Filter `automation_scripts` cache to test entry points via glob rules.
4. Bucket entry points by directory → rule-based suite proposals.
5. (Optional) LLM enrichment: if OpenRouter key is configured AND the provider
   config opts in via `smart_scan.enable_llm`, send `ref_path + test_names +
   format + count` (NO source bodies) to LLM for better names/descriptions.
   Falls back to rule-based on failure / timeout.
6. Light in-memory cache keyed by (team_id, manifest_etag, scan_config_hash,
   entry_points_hash) reuses prior LLM results for unchanged scans.
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json as _json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import ActionType, AuditSeverity, ResourceType, audit_service
from app.config import get_settings
from app.models.database_models import (
    AutomationProviderSlot,
    AutomationScript,
    AutomationSmartScanRun,
    AutomationSmartScanStatus,
)
from app.services.automation.provider_credential_service import decrypt_credentials
from app.services.automation.provider_registry import (
    ProviderNotConfiguredError,
    get_active_provider_record,
    instantiate_provider,
)
from app.services.automation.scan_filters import (
    DEFAULT_EXCLUDE_PATTERNS,
    DEFAULT_INCLUDE_PATTERNS,
    DEFAULT_SCAN_PATH,
    matches_exclude,
    matches_include,
)


_LLM_TIMEOUT_SECONDS_DEFAULT = 10
_OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
_LLM_PROMPT_VERSION = "smart-scan.v1"
_llm_cache: dict[str, list[dict[str, Any]]] = {}  # cache_key → enriched proposals


logger = logging.getLogger(__name__)


# Default scan conventions live in scan_filters (shared with script_service so a
# single `scan.include` / `scan.exclude` manifest block drives both stages).
DEFAULT_MAX_SCAN_BYTES = 262144
STANDARD_REPO_PATHS = ("tests", "pages", "flows", "fixtures", "resources", "config")
SUPPORT_PATH_TAGS = {"pages": "Page Objects", "flows": "Flows", "fixtures": "Fixtures",
                     "resources": "Resources", "config": "Config", "scripts": "Helper scripts",
                     "reports": "Reports"}


class SmartScanError(ValueError):
    pass


@dataclass
class RepoContractValidation:
    manifest_found: bool
    manifest_path: str
    contract_status: str  # "ok" / "missing" / "partial"
    effective_tests_path: str
    standard_paths_present: list[str]
    standard_paths_missing: list[str]
    support_paths: list[dict[str, str]]
    violations: list[str]


@dataclass
class MarkerHit:
    """Parsed @pytest.mark.tcrt(...) or `// tcrt: ...` marker."""
    tc_ids: list[str]
    link_type: str  # "primary" | "covers" | "references"
    source_line: int
    raw: str


@dataclass
class TestEntry:
    """A single test function / class / JS test discovered inside an entry-point file."""
    name: str
    kind: str  # "function" | "class"
    line: int
    docstring: str | None = None
    markers: list[MarkerHit] = field(default_factory=list)


@dataclass
class EntryPoint:
    script_id: int | None
    name: str
    ref_path: str
    ref_repo: str
    ref_branch: str
    etag: str | None
    script_format: str
    detected_format: str
    test_names: list[str] = field(default_factory=list)
    test_count: int = 0
    content_unverified: bool = False
    test_entries: list[TestEntry] = field(default_factory=list)
    marker_warnings: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SuiteProposal:
    name: str
    description: str
    script_paths: list[str] = field(default_factory=list)
    ref_repo: str = ""
    enrichment_source: str = "rule-based"
    confidence: float = 0.7


@dataclass
class SmartScanResult:
    contract: RepoContractValidation
    entry_points: list[EntryPoint]
    excluded: list[dict[str, str]]  # [{ref_path, reason}]
    proposals: list[SuiteProposal]
    scan_config_hash: str


class SmartScanService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def scan(self, *, team_id: int) -> SmartScanResult:
        provider_record, storage = await self._load_storage_provider(team_id)
        provider_config = _load_provider_config(provider_record.config_json)

        manifest, manifest_path = await _try_load_manifest(storage, provider_config)
        scan_config = _resolve_scan_config(manifest, provider_config)
        scripts = await self._load_team_scripts(team_id)

        contract = self._validate_repo_contract(
            manifest=manifest,
            manifest_path=manifest_path,
            scan_config=scan_config,
            scripts=scripts,
        )

        entry_points, excluded = await self._detect_entry_points(scripts, scan_config, storage)
        proposals = self._group_by_directory(entry_points)

        # §4.5.8 / §4.5.9: optional LLM enrichment with in-memory cache.
        proposals = await _maybe_llm_enrich(
            team_id=team_id,
            scan_config=scan_config,
            entry_points=entry_points,
            proposals=proposals,
        )

        return SmartScanResult(
            contract=contract,
            entry_points=entry_points,
            excluded=excluded,
            proposals=proposals,
            scan_config_hash=_build_scan_config_hash(
                manifest_path=manifest_path,
                scan_config=scan_config,
                scripts=scripts,
            ),
        )

    # ------------------------------------------------------------------ helpers

    async def _load_storage_provider(self, team_id: int):
        try:
            record = await get_active_provider_record(team_id, AutomationProviderSlot.STORAGE, self.session)
        except ProviderNotConfiguredError as exc:
            raise SmartScanError(
                f"Smart Scan requires an active Storage provider for team {team_id}"
            ) from exc
        config = _load_provider_config(record.config_json)
        instance = instantiate_provider(
            record.provider_type,
            config,
            decrypt_credentials(record.credentials_encrypted),
        )
        return record, instance

    async def _load_team_scripts(self, team_id: int) -> list[AutomationScript]:
        result = await self.session.execute(
            select(AutomationScript).where(AutomationScript.team_id == team_id)
        )
        return list(result.scalars().all())

    def _validate_repo_contract(
        self,
        *,
        manifest: dict | None,
        manifest_path: str,
        scan_config: dict[str, Any],
        scripts: list[AutomationScript],
    ) -> RepoContractValidation:
        existing_dirs: set[str] = set()
        for script in scripts:
            parts = (script.ref_path or "").split("/")
            if len(parts) > 1:
                existing_dirs.add(parts[0])

        present = sorted(d for d in STANDARD_REPO_PATHS if d in existing_dirs)
        missing = sorted(d for d in STANDARD_REPO_PATHS if d not in existing_dirs)
        support = [
            {"path": d, "label": SUPPORT_PATH_TAGS[d]}
            for d in sorted(existing_dirs)
            if d in SUPPORT_PATH_TAGS and d != "tests"
        ]
        violations: list[str] = []
        if manifest is not None and not isinstance(manifest, dict):
            violations.append("Manifest file is not a YAML object")

        if not missing:
            contract_status = "ok"
        elif len(missing) >= len(STANDARD_REPO_PATHS) - 1:
            contract_status = "missing"
        else:
            contract_status = "partial"

        return RepoContractValidation(
            manifest_found=manifest is not None,
            manifest_path=manifest_path,
            contract_status=contract_status,
            effective_tests_path=scan_config.get("scan_path", DEFAULT_SCAN_PATH),
            standard_paths_present=present,
            standard_paths_missing=missing,
            support_paths=support,
            violations=violations,
        )

    async def _detect_entry_points(
        self,
        scripts: list[AutomationScript],
        scan_config: dict[str, Any],
        storage: Any,
    ) -> tuple[list[EntryPoint], list[dict[str, str]]]:
        scan_path = (scan_config.get("scan_path") or DEFAULT_SCAN_PATH).strip("/").lower()
        include = list(scan_config.get("include_patterns") or DEFAULT_INCLUDE_PATTERNS)
        exclude = list(scan_config.get("exclude_patterns") or DEFAULT_EXCLUDE_PATTERNS)
        max_scan_bytes = int(scan_config.get("max_scan_bytes") or DEFAULT_MAX_SCAN_BYTES)

        entry_points: list[EntryPoint] = []
        excluded: list[dict[str, str]] = []

        for script in scripts:
            ref_path = (script.ref_path or "").strip()
            if not ref_path:
                continue
            normalised = ref_path.lower()
            filename = ref_path.rsplit("/", 1)[-1]
            suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

            # Path-level filter: must live under the tests path (if configured)
            if scan_path and not normalised.startswith(scan_path):
                excluded.append({"ref_path": ref_path, "reason": "outside tests path"})
                continue
            if filename in {"__init__.py", "conftest.py"}:
                excluded.append({"ref_path": ref_path, "reason": "conftest_or_init"})
                continue
            if suffix != "py":
                excluded.append({"ref_path": ref_path, "reason": "unsupported_extension"})
                continue
            # Exclude globs on basename or any part of the path
            if matches_exclude(ref_path, exclude):
                excluded.append({"ref_path": ref_path, "reason": "helper_path"})
                continue
            # Include glob on filename
            if not matches_include(filename, include):
                excluded.append({"ref_path": ref_path, "reason": "filename did not match entry-point pattern"})
                continue

            content = await _load_script_content(storage, script)
            content_unverified = False
            test_names: list[str] = []
            test_count = 0
            test_entries: list[TestEntry] = []
            marker_warnings: list[dict[str, Any]] = []
            if content is None:
                content_unverified = True
            elif len(content.encode("utf-8")) > max_scan_bytes:
                content_unverified = True
            else:
                detected_entries, detected_warnings = _extract_test_entries(ref_path, content)
                if not detected_entries:
                    excluded.append({"ref_path": ref_path, "reason": "false_positive"})
                    continue
                test_entries = detected_entries
                marker_warnings = detected_warnings
                test_names = [entry.name for entry in detected_entries]
                test_count = len(detected_entries)

            script_format = script.script_format.value if hasattr(script.script_format, "value") else str(script.script_format)
            entry_points.append(EntryPoint(
                script_id=int(script.id),
                name=script.name,
                ref_path=ref_path,
                ref_repo=script.ref_repo or "",
                ref_branch=script.ref_branch,
                etag=script.cached_content_etag,
                script_format=script_format,
                detected_format=script_format,
                test_names=test_names,
                test_count=test_count,
                content_unverified=content_unverified,
                test_entries=test_entries,
                marker_warnings=marker_warnings,
            ))
        return entry_points, excluded

    def _group_by_directory(self, entry_points: list[EntryPoint]) -> list[SuiteProposal]:
        if not entry_points:
            return []
        # Bucket by (repo, directory immediately after the tests root). A suite is
        # single-repo (B1), so the repo is always part of the grouping key.
        buckets: dict[tuple[str, str], list[EntryPoint]] = {}
        for ep in entry_points:
            parts = ep.ref_path.split("/")
            # parts[0] is "tests" (or whatever), parts[1] is the bucket
            dir_key = parts[1] if len(parts) > 2 else "_root"
            buckets.setdefault((ep.ref_repo or "", dir_key), []).append(ep)

        dirs_by_repo: dict[str, set[str]] = {}
        for repo, dir_key in buckets:
            dirs_by_repo.setdefault(repo, set()).add(dir_key)

        proposals: list[SuiteProposal] = []
        for repo in sorted(dirs_by_repo):
            # Suffix the repo only when several are in play, so single-repo
            # (and legacy) scans keep their original suite names.
            suffix = f" ({repo})" if repo and len(dirs_by_repo) > 1 else ""
            dirs = dirs_by_repo[repo]
            # Flat layout (only _root) for this repo: single "Full Regression" suite
            if dirs == {"_root"}:
                members = buckets[(repo, "_root")]
                proposals.append(SuiteProposal(
                    name=f"Full Regression{suffix}",
                    description=f"All {len(members)} entry-point tests under the tests path.",
                    script_paths=[ep.ref_path for ep in members],
                    ref_repo=repo,
                ))
                continue
            for dir_key in sorted(dirs):
                members = buckets[(repo, dir_key)]
                display = "Root" if dir_key == "_root" else dir_key.replace("_", " ").replace("-", " ").title()
                proposals.append(SuiteProposal(
                    name=f"{display} Suite{suffix}",
                    description=f"{len(members)} tests grouped from `{dir_key}/`.",
                    script_paths=[ep.ref_path for ep in members],
                    ref_repo=repo,
                ))
        return proposals


# ---------------------------------------------------------------- module helpers


def _load_provider_config(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        import json

        data = json.loads(value)
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


async def _try_load_manifest(storage, provider_config: dict[str, Any]) -> tuple[dict | None, str]:
    manifest_path = (provider_config.get("manifest_path") or "tcrt-automation.yml").strip()
    try:
        content = await storage.read_script(manifest_path)
    except Exception:  # noqa: BLE001
        return None, manifest_path
    try:
        import yaml

        payload = yaml.safe_load(getattr(content, "content", "") or "") or {}
    except Exception:  # noqa: BLE001
        return None, manifest_path
    if not isinstance(payload, dict):
        return None, manifest_path
    return payload, manifest_path


def _resolve_scan_config(manifest: dict | None, provider_config: dict[str, Any]) -> dict[str, Any]:
    """Order of precedence: manifest > provider.smart_scan > provider defaults."""
    base: dict[str, Any] = {
        "scan_path": provider_config.get("scan_path") or DEFAULT_SCAN_PATH,
        "include_patterns": list(DEFAULT_INCLUDE_PATTERNS),
        "exclude_patterns": list(DEFAULT_EXCLUDE_PATTERNS),
        "enable_llm": False,
        "llm_timeout_seconds": _LLM_TIMEOUT_SECONDS_DEFAULT,
        "manifest_path": "tcrt-automation.yml",
        "max_scan_bytes": DEFAULT_MAX_SCAN_BYTES,
    }
    provider_smart = (provider_config.get("smart_scan") or {}) if isinstance(provider_config.get("smart_scan"), dict) else {}
    for key in (
        "scan_path", "include_patterns", "exclude_patterns",
        "enable_llm", "llm_timeout_seconds", "manifest_path", "max_scan_bytes",
    ):
        if key in provider_smart and provider_smart[key] is not None:
            base[key] = provider_smart[key]
    if manifest:
        scan_section = manifest.get("scan") if isinstance(manifest.get("scan"), dict) else {}
        paths_section = manifest.get("paths") if isinstance(manifest.get("paths"), dict) else {}
        if isinstance(paths_section.get("tests"), str):
            base["scan_path"] = paths_section["tests"]
        if scan_section.get("scan_path"):
            base["scan_path"] = scan_section["scan_path"]
        # Canonical keys are `include`/`exclude`; `*_patterns` kept as aliases.
        include = scan_section.get("include") or scan_section.get("include_patterns")
        if include:
            base["include_patterns"] = include
        exclude = scan_section.get("exclude") or scan_section.get("exclude_patterns")
        if exclude:
            base["exclude_patterns"] = exclude
    return base


async def _maybe_llm_enrich(
    *,
    team_id: int,
    scan_config: dict[str, Any],
    entry_points: list["EntryPoint"],
    proposals: list["SuiteProposal"],
) -> list["SuiteProposal"]:
    """Optionally enrich proposals via OpenRouter LLM. Pure no-op when:
    - `enable_llm` is False in scan_config, OR
    - No OpenRouter API key is configured, OR
    - The HTTP call times out / fails.

    The deterministic rule-based result is always preserved on the way out.
    """
    if not scan_config.get("enable_llm"):
        return proposals
    api_key = (get_settings().openrouter.api_key or "").strip()
    if not api_key:
        return proposals
    if not proposals:
        return proposals

    cache_key = _build_llm_cache_key(team_id=team_id, scan_config=scan_config, entry_points=entry_points)
    if cache_key in _llm_cache:
        cached = _llm_cache[cache_key]
        return _apply_llm_overrides(proposals, cached)

    timeout = float(scan_config.get("llm_timeout_seconds") or _LLM_TIMEOUT_SECONDS_DEFAULT)
    try:
        overrides = await asyncio.wait_for(
            _call_openrouter(api_key=api_key, proposals=proposals),
            timeout=timeout,
        )
    except (asyncio.TimeoutError, httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
        logger.warning("Smart Scan LLM enrich failed (falling back to rule-based): %s", exc)
        return proposals
    except Exception as exc:  # noqa: BLE001
        logger.warning("Smart Scan LLM enrich unexpected error: %s", exc)
        return proposals

    _llm_cache[cache_key] = overrides
    return _apply_llm_overrides(proposals, overrides)


def _build_llm_cache_key(
    *,
    team_id: int,
    scan_config: dict[str, Any],
    entry_points: list["EntryPoint"],
) -> str:
    payload = {
        "team_id": team_id,
        "scan_config": {k: scan_config.get(k) for k in ("scan_path", "include_patterns", "exclude_patterns")},
        "entry_points": sorted(ep.ref_path for ep in entry_points),
        "prompt_version": _LLM_PROMPT_VERSION,
    }
    return hashlib.sha256(_json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _build_scan_config_hash(
    *,
    manifest_path: str,
    scan_config: dict[str, Any],
    scripts: list[AutomationScript],
) -> str:
    payload = {
        "manifest_path": manifest_path,
        "scan_config": scan_config,
        "scripts": sorted(
            (script.ref_path or "", script.ref_branch or "", script.cached_content_etag or "")
            for script in scripts
        ),
        "prompt_version": _LLM_PROMPT_VERSION,
    }
    return hashlib.sha256(_json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


async def _load_script_content(storage: Any, script: AutomationScript) -> str | None:
    if script.cached_content:
        return script.cached_content
    # Bind to the script's own repo when the provider holds several.
    if hasattr(storage, "for_repo"):
        storage = storage.for_repo(script.ref_repo)
    try:
        content = await storage.read_script(
            script.ref_path,
            ref=script.ref_branch,
            etag=script.cached_content_etag,
        )
    except TypeError:
        try:
            content = await storage.read_script(script.ref_path)
        except Exception:  # noqa: BLE001
            return None
    except Exception:  # noqa: BLE001
        return None
    value = getattr(content, "content", None)
    return value if isinstance(value, str) else None


_VALID_LINK_TYPES = frozenset({"primary", "covers", "references"})
_TC_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _extract_test_entries(
    ref_path: str, content: str
) -> tuple[list[TestEntry], list[dict[str, Any]]]:
    """Detect test functions/classes plus tcrt markers from source.

    Python-only. Returns (entries, warnings). Fail-open: parse errors flow
    into warnings, never raise; entries with bad markers still appear with
    empty markers list.
    """
    return _extract_py_test_entries(content)


def _extract_py_test_entries(
    content: str,
) -> tuple[list[TestEntry], list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        warnings.append(
            {
                "type": "parse_error",
                "line": getattr(exc, "lineno", 0) or 0,
                "detail": "python_syntax_error",
            }
        )
        return [], warnings

    entries: list[TestEntry] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            markers = _parse_py_markers(node.decorator_list, warnings)
            entries.append(
                TestEntry(
                    name=node.name,
                    kind="function",
                    line=node.lineno,
                    docstring=ast.get_docstring(node),
                    markers=markers,
                )
            )
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            markers = _parse_py_markers(node.decorator_list, warnings)
            entries.append(
                TestEntry(
                    name=node.name,
                    kind="class",
                    line=node.lineno,
                    docstring=ast.get_docstring(node),
                    markers=markers,
                )
            )
    entries.sort(key=lambda e: (e.line, e.name))
    return entries, warnings


def _parse_py_markers(
    decorator_list: list[Any], warnings: list[dict[str, Any]]
) -> list[MarkerHit]:
    """Return MarkerHit list for any @pytest.mark.tcrt(...) decorators.

    Non-literal args, invalid link_type, malformed TC ids → fail-open: marker
    is dropped, a warning entry is appended, scanning continues.
    """
    markers: list[MarkerHit] = []
    for dec in decorator_list:
        if not _is_pytest_tcrt_call(dec):
            continue
        line = getattr(dec, "lineno", 0)
        tc_ids: list[str] = []
        all_literal = True
        for arg in dec.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                tc_ids.append(arg.value)
            else:
                warnings.append({"type": "non_literal_marker", "line": line})
                all_literal = False
                break
        if not all_literal:
            continue

        link_type = "covers"
        bad_kw = False
        for kw in dec.keywords:
            if kw.arg == "link_type":
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    link_type = kw.value.value.lower()
                else:
                    warnings.append({"type": "non_literal_marker", "line": line})
                    bad_kw = True
                    break
            else:
                # Unknown kwarg — warn but don't drop the marker; future-friendly.
                warnings.append(
                    {"type": "unknown_marker_kwarg", "line": line, "kwarg": kw.arg or ""}
                )
        if bad_kw:
            continue

        if link_type not in _VALID_LINK_TYPES:
            warnings.append(
                {"type": "invalid_link_type", "line": line, "value": link_type}
            )
            continue

        valid_tcs: list[str] = []
        invalid_seen = False
        for tc in tc_ids:
            if _TC_ID_PATTERN.match(tc):
                valid_tcs.append(tc)
            else:
                warnings.append(
                    {"type": "invalid_tc_format", "line": line, "tc_id": tc}
                )
                invalid_seen = True
        if invalid_seen or not valid_tcs:
            continue

        if hasattr(ast, "unparse"):
            try:
                raw = ast.unparse(dec)
            except Exception:  # noqa: BLE001
                raw = "@pytest.mark.tcrt(...)"
        else:
            raw = "@pytest.mark.tcrt(...)"
        markers.append(
            MarkerHit(
                tc_ids=valid_tcs,
                link_type=link_type,
                source_line=line,
                raw=raw,
            )
        )
    return markers


def _is_pytest_tcrt_call(node: Any) -> bool:
    """Strict structural match for `pytest.mark.tcrt(...)` Call node."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "tcrt":
        return False
    inner = func.value
    if not isinstance(inner, ast.Attribute) or inner.attr != "mark":
        return False
    root = inner.value
    return isinstance(root, ast.Name) and root.id == "pytest"


# Back-compat: callers expecting list[str] still work; derives names from entries.
def _extract_test_metadata(ref_path: str, content: str) -> list[str]:
    entries, _ = _extract_test_entries(ref_path, content)
    return sorted({entry.name for entry in entries})


async def _call_openrouter(
    *, api_key: str, proposals: list["SuiteProposal"]
) -> list[dict[str, Any]]:
    """Send a tiny refinement prompt and return per-proposal overrides.

    The prompt is intentionally schema-strict: we ask for a JSON object with a
    list of `{index, name, description}` so we can robustly merge back without
    blowing up on free-form LLM output.
    """
    proposals_payload = [
        {
            "index": idx,
            "current_name": p.name,
            "current_description": p.description,
            "sample_paths": p.script_paths[:5],
            "total_paths": len(p.script_paths),
        }
        for idx, p in enumerate(proposals)
    ]
    system_prompt = (
        "You refine QA automation suite names and descriptions. Reply with a "
        "single JSON object: {\"proposals\": [{\"index\": <int>, \"name\": <str>, "
        "\"description\": <str>}, ...]}. Keep names under 60 chars. Use English. "
        "Do not invent paths. If unsure for a proposal, keep current values."
    )
    user_prompt = _json.dumps({"proposals": proposals_payload}, ensure_ascii=False)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": "google/gemini-3-flash-preview",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 800,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(_LLM_TIMEOUT_SECONDS_DEFAULT)) as client:
        response = await client.post(_OPENROUTER_CHAT_COMPLETIONS_URL, json=body, headers=headers)
    response.raise_for_status()
    payload = response.json()
    choices = payload.get("choices") or []
    if not choices:
        return []
    content = (choices[0].get("message") or {}).get("content", "")
    try:
        parsed = _json.loads(content)
    except Exception:
        return []
    overrides = parsed.get("proposals") if isinstance(parsed, dict) else None
    if not isinstance(overrides, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for item in overrides:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        name = str(item.get("name") or "").strip()
        description = str(item.get("description") or "").strip()
        cleaned.append({"index": idx, "name": name, "description": description})
    return cleaned


def _apply_llm_overrides(
    proposals: list["SuiteProposal"], overrides: list[dict[str, Any]]
) -> list["SuiteProposal"]:
    if not overrides:
        return proposals
    by_index = {o["index"]: o for o in overrides if isinstance(o.get("index"), int)}
    result: list[SuiteProposal] = []
    for idx, p in enumerate(proposals):
        override = by_index.get(idx)
        if not override:
            result.append(p)
            continue
        new_name = override.get("name") or p.name
        new_desc = override.get("description") or p.description
        result.append(SuiteProposal(
            name=new_name[:200],
            description=new_desc,
            script_paths=p.script_paths,
            enrichment_source="llm",
            confidence=0.85,
        ))
    return result


def smart_scan_result_to_dict(result: SmartScanResult) -> dict[str, Any]:
    return {
        "scan_config_hash": result.scan_config_hash,
        "contract": {
            "manifest_found": result.contract.manifest_found,
            "manifest_path": result.contract.manifest_path,
            "contract_status": result.contract.contract_status,
            "effective_tests_path": result.contract.effective_tests_path,
            "standard_paths_present": result.contract.standard_paths_present,
            "standard_paths_missing": result.contract.standard_paths_missing,
            "support_paths": result.contract.support_paths,
            "violations": result.contract.violations,
        },
        "entry_points": [
            {
                "script_id": ep.script_id,
                "name": ep.name,
                "ref_path": ep.ref_path,
                "ref_repo": ep.ref_repo,
                "ref_branch": ep.ref_branch,
                "etag": ep.etag,
                "script_format": ep.script_format,
                "detected_format": ep.detected_format,
                "test_names": ep.test_names,
                "test_count": ep.test_count,
                "content_unverified": ep.content_unverified,
                "test_entries": [
                    {
                        "name": entry.name,
                        "kind": entry.kind,
                        "line": entry.line,
                        "docstring": entry.docstring,
                        "markers": [
                            {
                                "tc_ids": list(marker.tc_ids),
                                "link_type": marker.link_type,
                                "source_line": marker.source_line,
                                "raw": marker.raw,
                            }
                            for marker in entry.markers
                        ],
                    }
                    for entry in ep.test_entries
                ],
                "marker_warnings": list(ep.marker_warnings),
            }
            for ep in result.entry_points
        ],
        "excluded": result.excluded,
        "proposals": [
            {
                "name": p.name,
                "description": p.description,
                "script_paths": p.script_paths,
                "ref_repo": p.ref_repo,
                "enrichment_source": p.enrichment_source,
                "confidence": p.confidence,
            }
            for p in result.proposals
        ],
    }


async def create_smart_scan_run(
    session: AsyncSession,
    *,
    team_id: int,
    actor: str | None,
) -> AutomationSmartScanRun:
    provider = await get_active_provider_record(team_id, AutomationProviderSlot.STORAGE, session)
    pending_hash = hashlib.sha256(
        _json.dumps(
            {"team_id": team_id, "provider_id": provider.id, "config_json": provider.config_json},
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    run = AutomationSmartScanRun(
        team_id=team_id,
        provider_id=provider.id,
        status=AutomationSmartScanStatus.QUEUED,
        scan_config_hash=pending_hash,
        progress_json=_json.dumps({"step": "queued", "complete": 0, "total": 3}),
        created_by=actor,
    )
    session.add(run)
    await session.flush()
    return run


async def execute_smart_scan_run(scan_run_id: int) -> None:
    """Execute a persisted Smart Scan run inside the main DB boundary."""

    from app.db_access.main import get_main_access_boundary

    boundary = get_main_access_boundary()

    async def _execute(session: AsyncSession) -> None:
        run = await session.get(AutomationSmartScanRun, scan_run_id)
        if run is None:
            return
        run.status = AutomationSmartScanStatus.SCANNING
        run.progress_json = _json.dumps({"step": "scanning", "complete": 1, "total": 3})
        run.updated_at = _utcnow()
        await session.flush()

        try:
            result = await SmartScanService(session).scan(team_id=run.team_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Smart Scan run %s failed: %s", scan_run_id, exc, exc_info=True)
            run.status = AutomationSmartScanStatus.FAILED
            run.error_summary = str(exc)[:1000]
            run.progress_json = _json.dumps({"step": "failed", "complete": 1, "total": 3})
            run.finished_at = _utcnow()
            run.updated_at = run.finished_at
            return

        payload = smart_scan_result_to_dict(result)
        run.status = AutomationSmartScanStatus.READY
        run.scan_config_hash = result.scan_config_hash
        run.progress_json = _json.dumps({"step": "ready", "complete": 3, "total": 3})
        run.result_json = _json.dumps(payload, ensure_ascii=False)
        run.error_summary = None
        run.finished_at = _utcnow()
        run.updated_at = run.finished_at
        await _log_smart_scan_complete(run=run, payload=payload)

    try:
        await boundary.run_write(_execute)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Smart Scan run %s crashed outside transaction: %s", scan_run_id, exc, exc_info=True)


async def _log_smart_scan_complete(*, run: AutomationSmartScanRun, payload: dict[str, Any]) -> None:
    try:
        actor_id = int(run.created_by or 0)
    except ValueError:
        actor_id = 0
    try:
        await audit_service.log_action(
            user_id=actor_id,
            username="automation-smart-scan",
            role="system",
            action_type=ActionType.READ,
            resource_type=ResourceType.AUTOMATION_SCRIPT,
            resource_id=str(run.id),
            team_id=run.team_id,
            details={
                "scan_run_id": run.id,
                "repo_contract_status": (payload.get("contract") or {}).get("contract_status"),
                "entry_points_found": len(payload.get("entry_points") or []),
                "entry_points_excluded": len(payload.get("excluded") or []),
                "groups_suggested": len(payload.get("proposals") or []),
            },
            action_brief=f"Smart Scan completed: {run.id}",
            severity=AuditSeverity.INFO,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to write Smart Scan audit log: %s", exc, exc_info=True)


def _utcnow() -> datetime:
    return datetime.utcnow()
