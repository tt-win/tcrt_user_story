from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import yaml
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import ActionType, AuditSeverity, ResourceType, audit_service
from app.models.database_models import (
    AutomationProviderSlot,
    AutomationScript,
    AutomationScriptCaseLink,
    AutomationScriptFormat,
    AutomationScriptLinkType,
    TeamAutomationProvider,
    TestCaseLocal,
)
from app.services.automation.provider_registry import (
    get_active_provider_record,
    instantiate_provider,
)
from app.services.automation.providers.base import StorageProvider
from app.services.automation.scan_filters import (
    DEFAULT_EXCLUDE_PATTERNS,
    DEFAULT_INCLUDE_PATTERNS,
    DEFAULT_SCAN_PATH,
    matches_scan_filters,
)
from app.services.automation.smart_scan_service import (
    MarkerHit,
    TestEntry,
    _extract_test_entries,
)


logger = logging.getLogger(__name__)


# Sentinel value stored in AutomationScriptCaseLink.created_by to mark records
# derived from in-code `@pytest.mark.tcrt` / `// tcrt:` markers.
MARKER_SYNC_CREATED_BY = "marker-sync"
AI_SUGGEST_PREFIX = "ai-suggest:"


def is_marker_sync_link(created_by: str | None) -> bool:
    return created_by == MARKER_SYNC_CREATED_BY


def is_ai_suggest_link(created_by: str | None) -> bool:
    return bool(created_by) and created_by.startswith(AI_SUGGEST_PREFIX)


def parse_ai_suggest_user_id(created_by: str | None) -> str | None:
    """Extract user id from `ai-suggest:<id>`; returns None if not the prefix."""
    if not created_by or not created_by.startswith(AI_SUGGEST_PREFIX):
        return None
    return created_by[len(AI_SUGGEST_PREFIX):] or None


def build_marker_note(*, test_name: str, line: int, marker_raw: str) -> str:
    """Serialize the JSON payload stored in AutomationScriptCaseLink.note."""
    payload = {"test_name": test_name, "line": line, "marker_raw": marker_raw}
    return json.dumps(payload, ensure_ascii=False)


def parse_marker_note(note: str | None) -> dict[str, Any] | None:
    """Inverse of build_marker_note. Returns None on parse failure."""
    if not note:
        return None
    try:
        payload = json.loads(note)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


DEFAULT_MANIFEST_PATH = "tcrt-automation.yml"
# DEFAULT_SCAN_PATH / DEFAULT_INCLUDE_PATTERNS / DEFAULT_EXCLUDE_PATTERNS now live
# in scan_filters and are shared with smart_scan_service.
MAX_CACHED_CONTENT_BYTES = 1024 * 1024


class AutomationScriptServiceError(ValueError):
    """Base error raised by automation script service."""


class AutomationScriptNotFoundError(AutomationScriptServiceError):
    pass


class RepoContractRequiredError(AutomationScriptServiceError):
    pass


@dataclass(frozen=True)
class RepoContract:
    manifest_path: str = DEFAULT_MANIFEST_PATH
    manifest_found: bool = False
    manifest_etag: str | None = None
    contract_status: str = "MISSING"
    framework: str | None = None
    effective_tests_path: str = DEFAULT_SCAN_PATH
    include_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_INCLUDE_PATTERNS))
    exclude_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE_PATTERNS))
    support_paths: dict[str, str] = field(default_factory=dict)
    missing_paths: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_path": self.manifest_path,
            "manifest_found": self.manifest_found,
            "manifest_etag": self.manifest_etag,
            "contract_status": self.contract_status,
            "framework": self.framework,
            "effective_tests_path": self.effective_tests_path,
            "include_patterns": self.include_patterns,
            "exclude_patterns": self.exclude_patterns,
            "support_paths": self.support_paths,
            "missing_paths": self.missing_paths,
            "violations": self.violations,
        }


@dataclass(frozen=True)
class ScriptSyncSummary:
    provider_id: int
    branch: str
    scanned_path: str
    added: int
    updated: int
    removed: int
    total: int
    repo_contract: RepoContract

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "branch": self.branch,
            "scanned_path": self.scanned_path,
            "added": self.added,
            "updated": self.updated,
            "removed": self.removed,
            "total": self.total,
            "repo_contract": self.repo_contract.to_dict(),
        }


@dataclass
class MarkerSyncSummary:
    """Result of `sync_markers_for_team` reconcile pass."""
    team_id: int
    scripts_scanned: int = 0
    scripts_skipped_no_content: int = 0
    links_created: int = 0
    links_updated: int = 0
    links_removed: int = 0
    # Per-script warnings: script_id → list of warning dicts (from parser + reconcile)
    per_script_warnings: dict[int, list[dict[str, Any]]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "scripts_scanned": self.scripts_scanned,
            "scripts_skipped_no_content": self.scripts_skipped_no_content,
            "links_created": self.links_created,
            "links_updated": self.links_updated,
            "links_removed": self.links_removed,
            "per_script_warnings": {
                str(sid): warnings for sid, warnings in self.per_script_warnings.items()
            },
        }


class AutomationScriptService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_scripts(
        self,
        *,
        team_id: int,
        provider_id: int | None = None,
        script_format: AutomationScriptFormat | None = None,
        linked_test_case_id: int | None = None,
        q: str | None = None,
        cursor: int | None = None,
        limit: int = 50,
    ) -> tuple[list[AutomationScript], int | None, int]:
        limit = max(1, min(limit, 200))
        conditions = [AutomationScript.team_id == team_id]
        if provider_id is not None:
            conditions.append(AutomationScript.provider_id == provider_id)
        if script_format is not None:
            conditions.append(AutomationScript.script_format == script_format)
        if cursor is not None:
            conditions.append(AutomationScript.id > cursor)
        if q:
            query = f"%{q.strip()}%"
            conditions.append(or_(AutomationScript.name.ilike(query), AutomationScript.ref_path.ilike(query)))

        stmt = select(AutomationScript).where(and_(*conditions)).order_by(AutomationScript.id).limit(limit + 1)
        count_stmt = select(func.count(AutomationScript.id)).where(and_(*conditions))
        if linked_test_case_id is not None:
            stmt = stmt.join(AutomationScriptCaseLink).where(
                AutomationScriptCaseLink.test_case_id == linked_test_case_id
            )
            count_stmt = count_stmt.join(AutomationScriptCaseLink).where(
                AutomationScriptCaseLink.test_case_id == linked_test_case_id
            )

        rows = list((await self.session.execute(stmt)).scalars().all())
        total = int((await self.session.execute(count_stmt)).scalar_one())
        next_cursor = rows[-1].id if len(rows) > limit else None
        return rows[:limit], next_cursor, total

    async def get_script(self, *, team_id: int, script_id: int) -> AutomationScript:
        result = await self.session.execute(
            select(AutomationScript).where(AutomationScript.id == script_id, AutomationScript.team_id == team_id)
        )
        script = result.scalar_one_or_none()
        if script is None:
            raise AutomationScriptNotFoundError(f"Automation script {script_id} not found")
        return script

    async def sync_scripts(
        self,
        *,
        team_id: int,
        provider_id: int | None = None,
        branch: str | None = None,
        actor: str | None = None,
        storage_provider: StorageProvider | None = None,
        fetch_content: bool = False,
        reconcile_markers: bool = False,
    ) -> ScriptSyncSummary:
        provider_record = await self._get_storage_provider_record(team_id, provider_id)
        provider_config = _load_json(provider_record.config_json)
        provider = storage_provider
        if provider is None:
            credentials_encrypted = provider_record.credentials_encrypted
            from app.services.automation.provider_credential_service import decrypt_credentials

            provider = instantiate_provider(
                provider_record.provider_type,
                provider_config,
                decrypt_credentials(credentials_encrypted),
            )

        resolved_branch = branch or _default_branch(provider_config)
        repo_contract = await self.resolve_repo_contract(provider, provider_config, resolved_branch)
        refs = await provider.list_scripts(repo_contract.effective_tests_path, ref=resolved_branch, recursive=True)
        refs = [ref for ref in refs if _matches_scan_filters(ref.path, repo_contract)]

        existing_result = await self.session.execute(
            select(AutomationScript).where(
                AutomationScript.team_id == team_id,
                AutomationScript.provider_id == provider_record.id,
                AutomationScript.ref_branch == resolved_branch,
            )
        )
        existing_by_path = {script.ref_path: script for script in existing_result.scalars().all()}
        seen_paths: set[str] = set()
        now = _utcnow()
        added = 0
        updated = 0

        for ref in refs:
            seen_paths.add(ref.path)
            script = existing_by_path.get(ref.path)
            if script is None:
                content = (
                    await self._safe_fetch_content(provider, ref.path, resolved_branch)
                    if fetch_content
                    else None
                )
                self.session.add(
                    AutomationScript(
                        team_id=team_id,
                        provider_id=provider_record.id,
                        name=ref.name or ref.path.rsplit("/", 1)[-1],
                        script_format=_normalize_script_format(ref.script_format),
                        ref_path=ref.path,
                        ref_branch=resolved_branch,
                        cached_content=content,
                        cached_content_etag=ref.etag,
                        last_synced_at=now,
                        tags_json="[]",
                        created_by=actor,
                        updated_by=actor,
                        created_at=now,
                        updated_at=now,
                    )
                )
                added += 1
                continue

            changed = False
            next_format = _normalize_script_format(ref.script_format)
            if script.script_format != next_format:
                script.script_format = next_format
                changed = True
            # Re-fetch content when the file changed or has never been cached.
            if fetch_content and (
                script.cached_content is None
                or (ref.etag and script.cached_content_etag != ref.etag)
            ):
                content = await self._safe_fetch_content(provider, ref.path, resolved_branch)
                if content is not None and content != script.cached_content:
                    script.cached_content = content
                    changed = True
            if ref.etag and script.cached_content_etag != ref.etag:
                script.cached_content_etag = ref.etag
                changed = True
            script.last_synced_at = now
            script.updated_by = actor
            script.updated_at = now
            if changed:
                updated += 1

        stale_ids = [script.id for path, script in existing_by_path.items() if path not in seen_paths]
        removed = 0
        if stale_ids:
            await self.session.execute(delete(AutomationScript).where(AutomationScript.id.in_(stale_ids)))
            removed = len(stale_ids)

        await self.session.flush()

        if reconcile_markers:
            await self.sync_markers_for_team(team_id=team_id, actor=actor)

        return ScriptSyncSummary(
            provider_id=provider_record.id,
            branch=resolved_branch,
            scanned_path=repo_contract.effective_tests_path,
            added=added,
            updated=updated,
            removed=removed,
            total=len(refs),
            repo_contract=repo_contract,
        )

    async def _safe_fetch_content(
        self, provider: StorageProvider, path: str, branch: str | None
    ) -> str | None:
        """Best-effort fetch of a script's body for marker parsing/caching.

        Returns None on any failure or when the body is empty / oversize, so a
        flaky read never aborts the whole sync.
        """
        try:
            content = await provider.read_script(path, ref=branch)
        except Exception:  # noqa: BLE001
            return None
        body = getattr(content, "content", None)
        if not isinstance(body, str) or not body:
            return None
        if len(body.encode("utf-8")) > MAX_CACHED_CONTENT_BYTES:
            return None
        return body

    async def sync_single_content(
        self,
        *,
        team_id: int,
        script_id: int,
        actor: str | None = None,
        storage_provider: StorageProvider | None = None,
    ) -> AutomationScript:
        script = await self.get_script(team_id=team_id, script_id=script_id)
        provider_record = await self._get_storage_provider_record(team_id, script.provider_id)
        provider_config = _load_json(provider_record.config_json)
        if storage_provider is None:
            from app.services.automation.provider_credential_service import decrypt_credentials

            provider = instantiate_provider(
                provider_record.provider_type,
                provider_config,
                decrypt_credentials(provider_record.credentials_encrypted),
            )
        else:
            provider = storage_provider

        content = await provider.read_script(script.ref_path, ref=script.ref_branch, etag=script.cached_content_etag)
        now = _utcnow()
        if not content.not_modified:
            encoded_size = len(content.content.encode("utf-8"))
            script.cached_content = None if encoded_size > MAX_CACHED_CONTENT_BYTES else content.content
            script.cached_content_etag = content.etag
        script.last_synced_at = now
        script.updated_by = actor
        script.updated_at = now
        await self.session.flush()
        return script

    async def update_metadata(
        self,
        *,
        team_id: int,
        script_id: int,
        actor: str | None = None,
        name: str | None = None,
        description: str | None = None,
        script_format: AutomationScriptFormat | None = None,
        tags: list[str] | None = None,
        preferred_runner_label: str | None = None,
    ) -> AutomationScript:
        script = await self.get_script(team_id=team_id, script_id=script_id)
        if name is not None:
            script.name = name
        if description is not None:
            script.description = description
        if script_format is not None:
            script.script_format = script_format
        if tags is not None:
            script.tags_json = json.dumps(tags, ensure_ascii=False)
        if preferred_runner_label is not None:
            script.preferred_runner_label = preferred_runner_label
        script.updated_by = actor
        script.updated_at = _utcnow()
        await self.session.flush()
        return script

    async def delete_script_cache(self, *, team_id: int, script_id: int) -> None:
        script = await self.get_script(team_id=team_id, script_id=script_id)
        await self.session.delete(script)
        await self.session.flush()

    async def resolve_repo_contract(
        self,
        provider: StorageProvider,
        provider_config: dict[str, Any],
        branch: str,
    ) -> RepoContract:
        smart_scan = provider_config.get("smart_scan") if isinstance(provider_config.get("smart_scan"), dict) else {}
        manifest_path = str(smart_scan.get("manifest_path") or DEFAULT_MANIFEST_PATH)
        use_manifest = bool(smart_scan.get("use_manifest", True))
        require_manifest = bool(
            smart_scan.get("require_manifest", False) or smart_scan.get("enforce_repo_contract", False)
        )

        fallback = _repo_contract_from_provider_config(provider_config, manifest_path=manifest_path)
        if not use_manifest:
            return fallback

        try:
            manifest_content = await provider.read_script(manifest_path, ref=branch)
        except FileNotFoundError:
            if require_manifest:
                raise RepoContractRequiredError(f"Required automation repo manifest not found: {manifest_path}")
            return fallback
        except Exception as exc:
            if require_manifest:
                raise RepoContractRequiredError(f"Unable to read automation repo manifest: {exc}") from exc
            return RepoContract(
                manifest_path=manifest_path,
                manifest_found=False,
                contract_status="INVALID",
                effective_tests_path=fallback.effective_tests_path,
                include_patterns=fallback.include_patterns,
                exclude_patterns=fallback.exclude_patterns,
                violations=[str(exc)],
            )

        try:
            payload = yaml.safe_load(manifest_content.content) or {}
        except yaml.YAMLError as exc:
            if require_manifest:
                raise RepoContractRequiredError(f"Invalid automation repo manifest: {exc}") from exc
            return RepoContract(
                manifest_path=manifest_path,
                manifest_found=True,
                manifest_etag=manifest_content.etag,
                contract_status="INVALID",
                effective_tests_path=fallback.effective_tests_path,
                include_patterns=fallback.include_patterns,
                exclude_patterns=fallback.exclude_patterns,
                violations=[str(exc)],
            )

        if not isinstance(payload, dict):
            if require_manifest:
                raise RepoContractRequiredError("Automation repo manifest must be a YAML mapping")
            return fallback

        return _repo_contract_from_manifest(payload, manifest_path=manifest_path, manifest_etag=manifest_content.etag)

    async def sync_markers_for_team(
        self,
        *,
        team_id: int,
        actor: str | None = None,
        script_ids: list[int] | None = None,
    ) -> MarkerSyncSummary:
        """Reconcile in-code markers with `automation_script_case_links`.

        For each script with cached_content, parse markers via
        `_extract_test_entries`. Then per (script, tc_id) pair:
          - Resolve tc_id → test_case_id via `test_cases.test_case_number`
          - Upsert link with created_by="marker-sync" (idempotent)
          - If an existing link from human / AI has a different link_type,
            preserve it but record a `link_type_conflict` warning
          - Sweep: delete marker-sync links no longer referenced by markers

        Scripts without `cached_content` (oversize / never fetched) are skipped;
        their marker-sync links are untouched.
        """
        conditions = [AutomationScript.team_id == team_id]
        if script_ids:
            conditions.append(AutomationScript.id.in_(script_ids))
        scripts_result = await self.session.execute(
            select(AutomationScript).where(and_(*conditions))
        )
        scripts = list(scripts_result.scalars().all())

        # Build test_case_number → id index, scoped to this team.
        case_result = await self.session.execute(
            select(TestCaseLocal.id, TestCaseLocal.test_case_number).where(
                TestCaseLocal.team_id == team_id
            )
        )
        case_by_number: dict[str, int] = {
            number: case_id for case_id, number in case_result.all()
        }

        summary = MarkerSyncSummary(team_id=team_id)
        touched_script_ids: set[int] = set()
        for script in scripts:
            warnings: list[dict[str, Any]] = []
            if not script.cached_content:
                summary.scripts_skipped_no_content += 1
                summary.per_script_warnings[script.id] = []
                continue

            summary.scripts_scanned += 1
            entries, parse_warnings = _extract_test_entries(
                script.ref_path or "", script.cached_content
            )
            warnings.extend(parse_warnings)

            # Collapse (tc_id → desired link_type, first marker hit wins) for this file.
            # In practice multiple markers on different tests can mention the same TC; we
            # keep the link_type from the first encounter and record the line via the
            # `test_name`/`line` recorded in `note`.
            desired: dict[str, dict[str, Any]] = {}
            for entry in entries:
                for marker in entry.markers:
                    for tc_id in marker.tc_ids:
                        if tc_id in desired:
                            continue
                        desired[tc_id] = {
                            "link_type": marker.link_type,
                            "test_name": entry.name,
                            "line": entry.line,
                            "marker_raw": marker.raw,
                            "source_line": marker.source_line,
                        }

            # Load existing links for this script once.
            existing_result = await self.session.execute(
                select(AutomationScriptCaseLink).where(
                    AutomationScriptCaseLink.automation_script_id == script.id
                )
            )
            existing_links = list(existing_result.scalars().all())
            existing_by_case_id: dict[int, AutomationScriptCaseLink] = {
                link.test_case_id: link for link in existing_links
            }

            seen_case_ids: set[int] = set()
            for tc_id, plan in desired.items():
                case_id = case_by_number.get(tc_id)
                if case_id is None:
                    warnings.append(
                        {
                            "type": "unknown_tc",
                            "tc_id": tc_id,
                            "line": plan["source_line"],
                            "test_name": plan["test_name"],
                        }
                    )
                    continue
                seen_case_ids.add(case_id)
                desired_link_type = _link_type_from_string(plan["link_type"])
                note = build_marker_note(
                    test_name=plan["test_name"],
                    line=plan["line"],
                    marker_raw=plan["marker_raw"],
                )

                existing = existing_by_case_id.get(case_id)
                if existing is None:
                    new_link = AutomationScriptCaseLink(
                        team_id=team_id,
                        automation_script_id=script.id,
                        test_case_id=case_id,
                        link_type=desired_link_type,
                        note=note,
                        created_by=MARKER_SYNC_CREATED_BY,
                        created_at=_utcnow(),
                    )
                    self.session.add(new_link)
                    summary.links_created += 1
                    touched_script_ids.add(script.id)
                    await self._audit_marker_link(
                        action=ActionType.CREATE,
                        team_id=team_id,
                        script=script,
                        test_case_id=case_id,
                        test_case_number=tc_id,
                        link_type=desired_link_type,
                        reason="marker_added",
                        actor=actor,
                        note=note,
                    )
                    continue

                if is_marker_sync_link(existing.created_by):
                    # Same source — refresh link_type / note if drifted.
                    changed = False
                    if existing.link_type != desired_link_type:
                        existing.link_type = desired_link_type
                        changed = True
                    if existing.note != note:
                        existing.note = note
                        changed = True
                    if changed:
                        summary.links_updated += 1
                        touched_script_ids.add(script.id)
                        await self._audit_marker_link(
                            action=ActionType.UPDATE,
                            team_id=team_id,
                            script=script,
                            test_case_id=case_id,
                            test_case_number=tc_id,
                            link_type=desired_link_type,
                            reason="marker_updated",
                            actor=actor,
                            note=note,
                        )
                else:
                    # Human or AI-confirmed link — never overwrite.
                    if existing.link_type != desired_link_type:
                        warnings.append(
                            {
                                "type": "link_type_conflict",
                                "tc_id": tc_id,
                                "test_case_id": case_id,
                                "test_name": plan["test_name"],
                                "line": plan["source_line"],
                                "human_link_type": _link_type_to_user_string(
                                    existing.link_type
                                ),
                                "marker_link_type": _link_type_to_user_string(
                                    desired_link_type
                                ),
                                "existing_created_by": existing.created_by,
                            }
                        )

            # Cleanup pass: drop marker-sync links not present in `desired`.
            for link in existing_links:
                if not is_marker_sync_link(link.created_by):
                    continue
                if link.test_case_id in seen_case_ids:
                    continue
                summary.links_removed += 1
                touched_script_ids.add(script.id)
                resolved_number = next(
                    (n for n, cid in case_by_number.items() if cid == link.test_case_id),
                    None,
                )
                await self._audit_marker_link(
                    action=ActionType.DELETE,
                    team_id=team_id,
                    script=script,
                    test_case_id=link.test_case_id,
                    test_case_number=resolved_number,
                    link_type=link.link_type,
                    reason="marker_removed",
                    actor=actor,
                    note=link.note,
                )
                await self.session.delete(link)

            summary.per_script_warnings[script.id] = warnings

        await self.session.flush()
        # Refresh linked_test_case_count for any touched script.
        for script_id in touched_script_ids:
            await self._refresh_script_link_count(script_id)
        await self.session.flush()
        return summary

    async def _audit_marker_link(
        self,
        *,
        action: ActionType,
        team_id: int,
        script: AutomationScript,
        test_case_id: int,
        test_case_number: str | None,
        link_type: AutomationScriptLinkType,
        reason: str,
        actor: str | None,
        note: str | None,
    ) -> None:
        try:
            await audit_service.log_action(
                user_id=int(actor) if actor and actor.isdigit() else 0,
                username=actor or "automation-marker-sync",
                role="system",
                action_type=action,
                resource_type=ResourceType.AUTOMATION_SCRIPT_LINK,
                resource_id=f"{script.id}:{test_case_id}",
                team_id=team_id,
                details={
                    "source": MARKER_SYNC_CREATED_BY,
                    "reason": reason,
                    "script_id": script.id,
                    "script_name": script.name,
                    "test_case_id": test_case_id,
                    "test_case_number": test_case_number,
                    "link_type": _link_type_to_user_string(link_type),
                },
                action_brief=f"marker-sync {action.value}: script={script.id} tc={test_case_number}",
                severity=AuditSeverity.INFO,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to write marker-sync audit log: %s", exc, exc_info=True)

    async def _refresh_script_link_count(self, script_id: int) -> None:
        count_result = await self.session.execute(
            select(func.count(AutomationScriptCaseLink.id)).where(
                AutomationScriptCaseLink.automation_script_id == script_id
            )
        )
        count = int(count_result.scalar_one())
        await self.session.execute(
            select(AutomationScript).where(AutomationScript.id == script_id)
        )
        # Use a direct UPDATE to avoid loading the full row twice.
        from sqlalchemy import update as sa_update

        await self.session.execute(
            sa_update(AutomationScript)
            .where(AutomationScript.id == script_id)
            .values(linked_test_case_count=count)
        )

    async def _get_storage_provider_record(
        self,
        team_id: int,
        provider_id: int | None,
    ) -> TeamAutomationProvider:
        if provider_id is None:
            return await get_active_provider_record(team_id, AutomationProviderSlot.STORAGE, self.session)
        result = await self.session.execute(
            select(TeamAutomationProvider).where(
                TeamAutomationProvider.id == provider_id,
                TeamAutomationProvider.team_id == team_id,
                TeamAutomationProvider.provider_slot == AutomationProviderSlot.STORAGE,
            )
        )
        provider = result.scalar_one_or_none()
        if provider is None:
            raise AutomationScriptServiceError(f"Storage provider {provider_id} not found for team {team_id}")
        return provider


def _serialize_test_entries(
    ref_path: str | None, content: str | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse `@pytest.mark.tcrt` / `// tcrt:` markers from cached content.

    Returns (test_entries, marker_warnings) in the same shape the Suites tab
    Test view consumes. Empty when no content is cached yet.
    """
    if not content:
        return [], []
    entries, warnings = _extract_test_entries(ref_path or "", content)
    serialized = [
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
        for entry in entries
    ]
    return serialized, list(warnings)


def script_to_dict(script: AutomationScript) -> dict[str, Any]:
    test_entries, marker_warnings = _serialize_test_entries(
        script.ref_path, script.cached_content
    )
    return {
        "id": script.id,
        "team_id": script.team_id,
        "provider_id": script.provider_id,
        "name": script.name,
        "description": script.description,
        "script_format": script.script_format,
        "ref_path": script.ref_path,
        "ref_branch": script.ref_branch,
        "tags": _load_tags(script.tags_json),
        "preferred_runner_label": script.preferred_runner_label,
        "cached_content": script.cached_content,
        "cached_content_etag": script.cached_content_etag,
        "last_synced_at": script.last_synced_at,
        "linked_test_case_count": script.linked_test_case_count,
        "test_entries": test_entries,
        "marker_warnings": marker_warnings,
        "created_by": script.created_by,
        "updated_by": script.updated_by,
        "created_at": script.created_at,
        "updated_at": script.updated_at,
    }


def _repo_contract_from_provider_config(provider_config: dict[str, Any], *, manifest_path: str) -> RepoContract:
    smart_scan = provider_config.get("smart_scan") if isinstance(provider_config.get("smart_scan"), dict) else {}
    scan_path = str(smart_scan.get("scan_path") or provider_config.get("scan_path") or DEFAULT_SCAN_PATH)
    return RepoContract(
        manifest_path=manifest_path,
        manifest_found=False,
        contract_status="MISSING",
        effective_tests_path=_normalize_repo_path(scan_path),
        include_patterns=list(smart_scan.get("include_patterns") or DEFAULT_INCLUDE_PATTERNS),
        exclude_patterns=list(smart_scan.get("exclude_patterns") or DEFAULT_EXCLUDE_PATTERNS),
    )


def _repo_contract_from_manifest(
    payload: dict[str, Any],
    *,
    manifest_path: str,
    manifest_etag: str | None,
) -> RepoContract:
    paths = payload.get("paths") if isinstance(payload.get("paths"), dict) else {}
    scan = payload.get("scan") if isinstance(payload.get("scan"), dict) else {}
    tests_path = paths.get("tests") if isinstance(paths.get("tests"), str) else DEFAULT_SCAN_PATH
    support_paths = {
        key: _normalize_repo_path(value)
        for key, value in paths.items()
        if key != "tests" and isinstance(value, str) and value.strip()
    }
    missing_paths = [key for key in ("pages", "flows", "fixtures", "resources", "config") if key not in support_paths]
    violations: list[str] = []
    if payload.get("version") not in (1, "1"):
        violations.append("unsupported_manifest_version")
    if not isinstance(paths.get("tests"), str):
        violations.append("missing_paths_tests")
    return RepoContract(
        manifest_path=manifest_path,
        manifest_found=True,
        manifest_etag=manifest_etag,
        contract_status="WARNING" if violations or missing_paths else "VALID",
        framework=str(payload.get("framework")) if payload.get("framework") else None,
        effective_tests_path=_normalize_repo_path(tests_path),
        include_patterns=list(scan.get("include") or scan.get("include_patterns") or DEFAULT_INCLUDE_PATTERNS),
        exclude_patterns=list(scan.get("exclude") or scan.get("exclude_patterns") or DEFAULT_EXCLUDE_PATTERNS),
        support_paths=support_paths,
        missing_paths=missing_paths,
        violations=violations,
    )


def _matches_scan_filters(path: str, repo_contract: RepoContract) -> bool:
    return matches_scan_filters(
        path, repo_contract.include_patterns, repo_contract.exclude_patterns
    )


def _normalize_repo_path(path: str) -> str:
    normalized = path.strip().strip("/")
    return f"{normalized}/" if normalized else DEFAULT_SCAN_PATH


def _default_branch(provider_config: dict[str, Any]) -> str:
    return str(provider_config.get("default_branch") or "main")


def _normalize_script_format(raw_format: str | AutomationScriptFormat | None) -> AutomationScriptFormat:
    if isinstance(raw_format, AutomationScriptFormat):
        return raw_format
    try:
        return AutomationScriptFormat(str(raw_format))
    except ValueError:
        return AutomationScriptFormat.OTHER


def _link_type_from_string(value: str) -> AutomationScriptLinkType:
    """Marker `link_type` strings map onto enum values; falls back to COVERS."""
    normalized = (value or "").lower()
    for member in AutomationScriptLinkType:
        if member.value.lower() == normalized:
            return member
    return AutomationScriptLinkType.COVERS


def _link_type_to_user_string(value: AutomationScriptLinkType | str) -> str:
    """Lower-case form used in marker syntax / UI / warnings."""
    raw = value.value if hasattr(value, "value") else str(value)
    return raw.lower()


def _load_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_tags(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [str(item) for item in payload]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
