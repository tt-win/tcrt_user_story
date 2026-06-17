"""TCRT-side proxy that forwards Jenkins-uploaded allure-results to a local
Allure Docker Service instance.

Architectural rationale
-----------------------
Jenkins agents often live on a different host from TCRT, so the natural
"Jenkins curls Allure directly" pattern breaks when the operator wants Allure
to stay reachable only on TCRT's loopback (e.g. ``127.0.0.1:5050``). Instead,
Jenkins ships the raw ``allure-results`` directory as a single ``tar.gz`` to a
TCRT webhook endpoint and TCRT — co-located with Allure — does the handshake
(project ensure / clean-results / send-results / generate-report) over loopback.
Each report is scoped to a single run (clean-results clears only the staging
dir, leaving prior report builds + trend history intact).

The resulting per-run ``report_url`` is written back onto ``AutomationRun`` and
returned to the caller so the run-status webhook can include it; either way
the TCRT UI sees the link the next time the user looks at the run.
"""
from __future__ import annotations

import asyncio
import io
import logging
import re
import tarfile
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import AllureConfig, get_settings
from app.models.database_models import (
    AutomationRun,
    AutomationRunTrigger,
    AutomationScript,
    AutomationScriptGroup,
    Team,
)


logger = logging.getLogger(__name__)

# Webhook-triggered runs report to a dedicated Allure project (this suffix on
# the suite slug) so their trend history stays isolated from Test-Run-Set runs
# of the same suite. Reclaim (delete / rename) covers both variants.
_WEBHOOK_PROJECT_SUFFIX = "-webhook"


def _suite_slug_variants(base_slug: str) -> list[str]:
    """Both project-slug variants for a suite: primary + webhook."""
    return [base_slug, f"{base_slug}{_WEBHOOK_PROJECT_SUFFIX}"]


class AllureProxyError(Exception):
    """Base error for the Allure proxy flow."""


class AllureProxyNotConfiguredError(AllureProxyError):
    """``automation_provider.allure.base_url`` is empty — integration disabled."""


_MAX_ARCHIVE_BYTES = 50 * 1024 * 1024  # 50 MB — Allure result dirs are usually << 5 MB


def _slugify(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", (value or "").strip()).strip("-").lower()


async def upload_run_results(
    *,
    session: AsyncSession,
    run: AutomationRun,
    archive_bytes: bytes,
) -> str:
    """Forward an ``allure-results.tgz`` to the local Allure server.

    On success, sets ``run.report_url`` (caller still owns commit/flush) and
    returns the URL. Raises ``AllureProxyNotConfiguredError`` if the operator
    hasn't set ``base_url``; ``AllureProxyError`` for any handshake failure.
    """
    if len(archive_bytes) > _MAX_ARCHIVE_BYTES:
        raise AllureProxyError(
            f"Archive too large ({len(archive_bytes)} bytes > {_MAX_ARCHIVE_BYTES})"
        )

    cfg = get_settings().automation_provider.allure
    if not cfg.base_url:
        raise AllureProxyNotConfiguredError(
            "automation_provider.allure.base_url is not set"
        )

    project_id = await _resolve_project_id(session=session, run=run, cfg=cfg)
    if not project_id:
        raise AllureProxyError(
            "Could not derive Allure project_id — check project_id_template placeholders"
        )

    api_root = cfg.base_url.rstrip("/")
    auth_headers: dict[str, str] = {}
    if cfg.api_token:
        auth_headers["Authorization"] = f"Bearer {cfg.api_token}"

    # Extract archive once so we can stream files to Allure without holding the
    # whole decompressed payload in memory longer than necessary.
    with TemporaryDirectory() as tmpdir:
        result_files = _extract_archive(archive_bytes, Path(tmpdir))
        if not result_files:
            raise AllureProxyError("Archive contains no allure-results files")

        async with httpx.AsyncClient(timeout=60) as client:
            # 1. Idempotent project ensure. Some Allure Docker Service builds
            # still fail project creation here but can create via
            # send-results?force_project_creation=true below, so this stays
            # best-effort and the post-upload verification is authoritative.
            await _ensure_project(client, api_root, project_id, auth_headers)

            # 2. Empty the results staging dir so this report reflects ONLY the
            # current run (send-results appends; without this every report
            # rebuilds from the union of all runs ever sent). Generated report
            # builds + trend history live elsewhere and are untouched.
            await _clean_results(client, api_root, project_id, auth_headers)

            # 3. Upload each result file.
            await _send_results(client, api_root, project_id, result_files, auth_headers)

            # 4. Confirm the project really exists before asking Allure to
            # generate a report. This turns broken Allure volume / project
            # setup into a clear error instead of a later generate-report 404.
            await _assert_project_exists(client, api_root, project_id, auth_headers)

            # 5. Generate the report and capture the URL Allure assigns.
            report_url = await _generate_report(
                client, api_root, project_id, run, auth_headers
            )

    run.report_url = report_url
    return report_url


def _extract_archive(archive_bytes: bytes, dest: Path) -> list[Path]:
    """Detect ``.tgz`` or ``.zip`` from magic bytes, extract, and return the
    list of regular files inside the resulting ``allure-results/`` layer.

    Two archive shapes the proxy accepts:
      - ``.tgz`` from the CI-pushes-to-TCRT path (webhook upload) — tar
        usually wraps an ``allure-results/`` directory.
      - ``.zip`` from the TCRT-pulls-from-Jenkins path — Jenkins's bulk
        ``/artifact/*zip*/archive.zip`` namespaces everything under an
        ``archive/`` prefix, so the result files end up at
        ``archive/allure-results/<name>``.

    We tolerate both nestings (and "no wrapper, bare contents") so the call
    site doesn't need to know which CI produced the archive.
    """
    if archive_bytes[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
                # Guard against zipslip — ZipFile.extractall in modern
                # Python validates member names, but we double-check by
                # rejecting any absolute-path / parent-traversal entries
                # before extracting.
                for member in zf.infolist():
                    if member.filename.startswith("/") or ".." in Path(member.filename).parts:
                        raise AllureProxyError(
                            f"Refusing to extract unsafe zip member: {member.filename}"
                        )
                zf.extractall(dest)
        except zipfile.BadZipFile as exc:
            raise AllureProxyError(f"Invalid allure-results zip: {exc}") from exc
    elif archive_bytes[:3] == b"\x1f\x8b\x08":
        try:
            with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
                # ``filter='data'`` (Python 3.12+) blocks absolute paths /
                # symlinks / device files — safe extraction even for
                # untrusted CI uploads.
                tar.extractall(dest, filter="data")
        except (tarfile.ReadError, tarfile.CompressionError, EOFError) as exc:
            raise AllureProxyError(f"Invalid allure-results tarball: {exc}") from exc
    else:
        raise AllureProxyError(
            "Archive format not recognised (expected .tgz or .zip)"
        )

    # Find the first 'allure-results' directory anywhere in the extraction —
    # handles both Jenkins zip (archive/allure-results/) and CI-pushed tarball
    # (allure-results/) without a per-shape branch.
    candidates = [p for p in dest.rglob("allure-results") if p.is_dir()]
    root = candidates[0] if candidates else dest
    return sorted(p for p in root.iterdir() if p.is_file())


async def _ensure_project(
    client: httpx.AsyncClient,
    api_root: str,
    project_id: str,
    auth_headers: dict[str, str],
) -> None:
    try:
        resp = await client.post(
            f"{api_root}/allure-docker-service/projects",
            json={"id": project_id},
            headers={**auth_headers, "Content-Type": "application/json"},
        )
        if resp.status_code < 400:
            return
        try:
            if await _project_exists(client, api_root, project_id, auth_headers):
                return
        except AllureProxyError as exc:
            logger.warning(
                "Allure project lookup after ensure for %s failed "
                "(will retry via send-results): %s",
                project_id,
                exc,
            )
        logger.warning(
            "Allure project ensure for %s returned %s: %s",
            project_id,
            resp.status_code,
            _response_snippet(resp),
        )
    except httpx.HTTPError as exc:
        logger.warning(
            "Allure project ensure for %s failed (will retry via send-results): %s",
            project_id,
            exc,
        )


async def _clean_results(
    client: httpx.AsyncClient,
    api_root: str,
    project_id: str,
    auth_headers: dict[str, str],
) -> None:
    """Empty the project's *results* staging dir before this run's upload.

    Scopes the next ``generate-report`` to exactly one run. This clears only
    the raw results staging area — already-generated report builds (prior
    ``report_url``s stay valid) and the trend history are stored separately and
    survive, so past executions remain viewable and the trend graph keeps
    accumulating across runs.

    Best-effort: a failed clean only risks a stale-contaminated report, which
    shouldn't sink the whole upload — log and continue, matching the rest of
    the handshake.
    """
    try:
        resp = await client.get(
            f"{api_root}/allure-docker-service/clean-results",
            params={"project_id": project_id},
            headers=auth_headers,
        )
        if resp.status_code >= 500:
            logger.warning(
                "Allure clean-results for %s returned %s", project_id, resp.status_code
            )
    except httpx.HTTPError as exc:
        logger.warning(
            "Allure clean-results for %s failed (non-fatal): %s", project_id, exc
        )


async def _send_results(
    client: httpx.AsyncClient,
    api_root: str,
    project_id: str,
    files: list[Path],
    auth_headers: dict[str, str],
) -> None:
    for path in files:
        with path.open("rb") as fh:
            try:
                resp = await client.post(
                    f"{api_root}/allure-docker-service/send-results",
                    params={
                        "project_id": project_id,
                        "force_project_creation": "true",
                    },
                    files={"files[]": (path.name, fh, "application/octet-stream")},
                    headers=auth_headers,
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                # Per-file failures are not fatal — Allure can still generate
                # a partial report from what made it through. Log and continue
                # so a single corrupt result doesn't sink the whole upload.
                logger.warning(
                    "Allure send-results failed for %s: %s", path.name, exc
                )


async def _assert_project_exists(
    client: httpx.AsyncClient,
    api_root: str,
    project_id: str,
    auth_headers: dict[str, str],
) -> None:
    if await _project_exists(client, api_root, project_id, auth_headers):
        return
    raise AllureProxyError(
        f"Allure project {project_id!r} was not created; check the "
        "Allure Docker Service projects volume and project permissions"
    )


async def _project_exists(
    client: httpx.AsyncClient,
    api_root: str,
    project_id: str,
    auth_headers: dict[str, str],
) -> bool:
    try:
        resp = await client.get(
            f"{api_root}/allure-docker-service/projects/{project_id}",
            headers=auth_headers,
        )
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        raise AllureProxyError(
            f"Allure project lookup failed for {project_id!r}: {exc}"
        ) from exc


def _response_snippet(resp: httpx.Response) -> str:
    body = resp.text.strip()
    if len(body) > 300:
        body = f"{body[:300]}..."
    return body or "<empty response>"


# Allure Docker Service ingests uploaded results asynchronously. A
# generate-report call that lands while ingestion is still running is rejected
# with HTTP 400 + a body like "Processing files for project_id '…'. Try
# later!" — a transient state, not a real failure. It's easy to hit when
# several runs of the same suite ("Run Automation Suites") finish back-to-back
# and pile onto the same Allure project. We retry generate-report — and ONLY
# generate-report, never re-sending results, since a re-send restarts ingestion
# and would livelock the poll — until the project goes quiet.
_GENERATE_RETRY_DELAYS = (2.0, 3.0, 5.0, 8.0, 8.0, 8.0)  # ~34s over 7 attempts
_PROCESSING_MARKERS = ("try later", "processing files")


def _is_processing_response(resp: httpx.Response) -> bool:
    """True when Allure says it's still ingesting results (transient).

    Allure signals "busy" with a 400 (sometimes 202/503 across versions)
    whose body carries a processing marker. Match on the marker rather than
    the bare status so a genuine 400 (bad project, etc.) still fails fast.
    """
    if resp.status_code not in (400, 202, 503):
        return False
    body = (resp.text or "").lower()
    return any(marker in body for marker in _PROCESSING_MARKERS)


async def _generate_report(
    client: httpx.AsyncClient,
    api_root: str,
    project_id: str,
    run: AutomationRun,
    auth_headers: dict[str, str],
) -> str:
    exec_name = f"tcrt-{run.tcrt_correlation_id or run.id}"
    processing_snippet = ""
    for attempt, delay in enumerate((0.0, *_GENERATE_RETRY_DELAYS)):
        if delay:
            await asyncio.sleep(delay)
        try:
            resp = await client.get(
                f"{api_root}/allure-docker-service/generate-report",
                params={"project_id": project_id, "execution_name": exec_name},
                headers=auth_headers,
            )
        except httpx.HTTPError as exc:
            raise AllureProxyError(f"Allure generate-report failed: {exc}") from exc

        if _is_processing_response(resp):
            processing_snippet = _response_snippet(resp)
            logger.info(
                "Allure still ingesting results for %s (attempt %d/%d), retrying: %s",
                project_id,
                attempt + 1,
                len(_GENERATE_RETRY_DELAYS) + 1,
                processing_snippet,
            )
            continue

        try:
            resp.raise_for_status()
            body = resp.json()
        except httpx.HTTPError as exc:
            raise AllureProxyError(f"Allure generate-report failed: {exc}") from exc
        except ValueError as exc:
            raise AllureProxyError(
                f"Allure generate-report returned non-JSON body: {exc}"
            ) from exc

        report_url = ((body or {}).get("data") or {}).get("report_url")
        if not report_url:
            raise AllureProxyError(
                "Allure generate-report response missing data.report_url"
            )
        return str(report_url)

    # Still ingesting after every retry. Raise so the run stays pending and the
    # backfill sweep retries the full upload on a later tick — better than
    # claiming a report we never confirmed.
    raise AllureProxyError(
        f"Allure still processing results after {len(_GENERATE_RETRY_DELAYS) + 1} "
        f"attempts: {processing_snippet}"
    )


async def _lookup_team_slug(session: AsyncSession, team_id: int) -> str:
    team_result = await session.execute(
        select(Team.name).where(Team.id == team_id)
    )
    return _slugify(team_result.scalar_one_or_none() or "") or "team"


def _format_project_id(
    cfg: AllureConfig,
    *,
    team_id: int,
    team_slug: str,
    suite_id: str,
    suite_slug: str,
) -> str:
    """Expand ``project_id_template`` or return "" on a bad placeholder."""
    try:
        return cfg.project_id_template.format(
            team_id=team_id,
            team_slug=team_slug,
            suite_id=suite_id,
            suite_slug=suite_slug,
        )
    except (KeyError, IndexError):
        logger.warning(
            "Bad allure.project_id_template placeholder in %r",
            cfg.project_id_template,
        )
        return ""


async def _resolve_project_id(
    *,
    session: AsyncSession,
    run: AutomationRun,
    cfg: AllureConfig,
) -> str:
    """Expand ``project_id_template`` from the run's team / suite / script.

    Returns an empty string when the template references a placeholder we
    can't resolve (caller treats empty as "skip"). The lookups are cheap
    single-row queries; we accept the extra round-trip in exchange for not
    coupling this module to script_group_service.
    """
    team_slug = await _lookup_team_slug(session, run.team_id)

    suite_id: str = ""
    suite_slug: str = "suite"
    if run.script_group_id:
        group_result = await session.execute(
            select(AutomationScriptGroup.name).where(
                AutomationScriptGroup.id == run.script_group_id
            )
        )
        group_name = group_result.scalar_one_or_none() or ""
        suite_id = str(run.script_group_id)
        suite_slug = _slugify(group_name) or "suite"
    elif run.automation_script_id:
        script_result = await session.execute(
            select(AutomationScript.ref_path).where(
                AutomationScript.id == run.automation_script_id
            )
        )
        script_path = script_result.scalar_one_or_none() or ""
        suite_id = f"script-{run.automation_script_id}"
        suite_slug = _slugify(script_path) or "script"

    # Webhook-triggered runs land in a dedicated project variant, keeping their
    # report / trend history separate from Test-Run-Set runs of the same suite.
    if run.triggered_by == AutomationRunTrigger.WEBHOOK:
        suite_slug = f"{suite_slug}{_WEBHOOK_PROJECT_SUFFIX}"

    return _format_project_id(
        cfg,
        team_id=run.team_id,
        team_slug=team_slug,
        suite_id=suite_id,
        suite_slug=suite_slug,
    )


async def delete_project_for_group(
    *,
    session: AsyncSession,
    team_id: int,
    group: AutomationScriptGroup,
) -> bool:
    """Best-effort: drop the Allure project that backs a deleted suite.

    Reclaims the suite's report storage — raw results, every generated report
    build, and the trend history — via Allure Docker Service
    ``DELETE /projects/{id}``. The project_id is derived exactly as
    ``_resolve_project_id`` does for a group run, so this targets the same
    project that uploads created for the suite.

    Non-fatal by design: a suite deletion must not be blocked by a disabled or
    unreachable report server, so any transport/HTTP error is logged and
    swallowed. Returns True only when Allure acknowledged the delete (2xx) or
    the project was already gone (404); False when skipped or failed.
    """
    cfg = get_settings().automation_provider.allure
    if not cfg.base_url:
        return False  # report integration disabled — nothing to reclaim

    team_slug = await _lookup_team_slug(session, team_id)
    base_slug = _slugify(group.name) or "suite"
    # Reclaim BOTH the primary and webhook project variants. A suite that never
    # ran via webhook has no webhook project, so that delete just 404s (treated
    # as success). Returns True if any variant was acknowledged / already gone.
    reclaimed = False
    for suite_slug in _suite_slug_variants(base_slug):
        project_id = _format_project_id(
            cfg,
            team_id=team_id,
            team_slug=team_slug,
            suite_id=str(group.id),
            suite_slug=suite_slug,
        )
        if project_id and await _delete_project_by_id(cfg, project_id):
            reclaimed = True
    return reclaimed


async def _delete_project_by_id(cfg: AllureConfig, project_id: str) -> bool:
    """Best-effort ``DELETE /projects/{id}`` against Allure. Never raises.

    True when Allure acknowledged the delete (2xx) or the project was already
    gone (404); False on transport/HTTP error or a 4xx/5xx body.
    """
    api_root = cfg.base_url.rstrip("/")
    auth_headers: dict[str, str] = {}
    if cfg.api_token:
        auth_headers["Authorization"] = f"Bearer {cfg.api_token}"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.delete(
                f"{api_root}/allure-docker-service/projects/{project_id}",
                headers=auth_headers,
            )
    except httpx.HTTPError as exc:
        logger.warning(
            "Allure project delete for %s failed (non-fatal): %s", project_id, exc
        )
        return False

    if resp.status_code == 404:
        return True  # already gone — treat as success
    if resp.status_code >= 400:
        logger.warning(
            "Allure project delete for %s returned %s: %s",
            project_id,
            resp.status_code,
            _response_snippet(resp),
        )
        return False
    return True


async def delete_renamed_project(
    *,
    session: AsyncSession,
    team_id: int,
    suite_id: int,
    old_name: str,
    new_name: str,
) -> str | None:
    """Best-effort: drop the Allure project stranded by a suite rename.

    The project_id embeds the suite-name slug and Allure has no rename API, so
    renaming a suite leaves its old project behind while new runs build a fresh
    one under the new name. Delete the old project and return its project_id so
    the caller can warn the user that the past reports / trend are gone.

    No-op (returns None) when Allure is disabled, the project_id can't be
    derived, the name slug is unchanged (old and new project_id are identical —
    deleting would nuke the live project), or the delete didn't succeed.
    """
    cfg = get_settings().automation_provider.allure
    if not cfg.base_url:
        return None

    team_slug = await _lookup_team_slug(session, team_id)
    old_base = _slugify(old_name) or "suite"
    new_base = _slugify(new_name) or "suite"
    # Reclaim the stranded old project for both variants (primary + webhook).
    # Only the primary project's id is returned, for the user-facing warning.
    discarded_primary: str | None = None
    for old_slug, new_slug in zip(_suite_slug_variants(old_base), _suite_slug_variants(new_base)):
        old_pid = _format_project_id(
            cfg, team_id=team_id, team_slug=team_slug, suite_id=str(suite_id), suite_slug=old_slug
        )
        new_pid = _format_project_id(
            cfg, team_id=team_id, team_slug=team_slug, suite_id=str(suite_id), suite_slug=new_slug
        )
        if not old_pid or old_pid == new_pid:
            continue  # slug unchanged → same project → nothing to reclaim
        if await _delete_project_by_id(cfg, old_pid) and old_slug == old_base:
            discarded_primary = old_pid
    return discarded_primary


async def delete_projects_for_team(
    *,
    session: AsyncSession,
    team_id: int,
) -> int:
    """Best-effort: reclaim Allure projects for ALL of a team's suites.

    A team delete drops its ``AutomationScriptGroup`` rows via DB cascade,
    bypassing ``delete_group`` (and thus ``delete_project_for_group``). Call
    this *before* the cascade — while the suites are still queryable — to
    reclaim their report storage. Returns the number of projects Allure
    acknowledged deleting.

    Never raises: each suite's reclaim is guarded so one failure can't abort
    the team deletion or skip the remaining suites.
    """
    cfg = get_settings().automation_provider.allure
    if not cfg.base_url:
        return 0  # report integration disabled — nothing to reclaim

    groups = (
        await session.execute(
            select(AutomationScriptGroup).where(
                AutomationScriptGroup.team_id == team_id
            )
        )
    ).scalars().all()

    deleted = 0
    for group in groups:
        try:
            if await delete_project_for_group(
                session=session, team_id=team_id, group=group
            ):
                deleted += 1
        except Exception:  # defensive: delete_project_for_group is best-effort
            logger.warning(
                "Allure reclaim for suite %s (team %s) failed (non-fatal)",
                group.id,
                team_id,
                exc_info=True,
            )
    return deleted


async def delete_projects_for_team_rename(
    *,
    session: AsyncSession,
    team_id: int,
    old_team_name: str,
    new_team_name: str,
) -> int:
    """Best-effort: reclaim Allure projects stranded by a team rename.

    The project_id embeds the team slug, so renaming a team moves every suite's
    project to a new id while the old ones linger. For each suite (both the
    primary and webhook variant) delete the project keyed by the OLD team slug.
    No-op when the slug is unchanged (e.g. only casing/spacing differs) — the
    project_id doesn't move, so deleting would nuke the live project.

    Never raises; returns the number of projects Allure acknowledged deleting.
    """
    cfg = get_settings().automation_provider.allure
    if not cfg.base_url:
        return 0

    old_slug = _slugify(old_team_name) or "team"
    new_slug = _slugify(new_team_name) or "team"
    if old_slug == new_slug:
        return 0  # team slug unchanged → project ids unaffected

    groups = (
        await session.execute(
            select(AutomationScriptGroup).where(AutomationScriptGroup.team_id == team_id)
        )
    ).scalars().all()

    deleted = 0
    for group in groups:
        base_suite_slug = _slugify(group.name) or "suite"
        for suite_slug in _suite_slug_variants(base_suite_slug):
            old_pid = _format_project_id(
                cfg, team_id=team_id, team_slug=old_slug, suite_id=str(group.id), suite_slug=suite_slug
            )
            new_pid = _format_project_id(
                cfg, team_id=team_id, team_slug=new_slug, suite_id=str(group.id), suite_slug=suite_slug
            )
            if not old_pid or old_pid == new_pid:
                continue
            try:
                if await _delete_project_by_id(cfg, old_pid):
                    deleted += 1
            except Exception:  # defensive: best-effort
                logger.warning(
                    "Allure reclaim (team %s rename) for %s failed (non-fatal)",
                    team_id,
                    old_pid,
                    exc_info=True,
                )
    return deleted
