"""TCRT-side proxy that forwards Jenkins-uploaded allure-results to a local
Allure Docker Service instance.

Architectural rationale
-----------------------
Jenkins agents often live on a different host from TCRT, so the natural
"Jenkins curls Allure directly" pattern breaks when the operator wants Allure
to stay reachable only on TCRT's loopback (e.g. ``127.0.0.1:5050``). Instead,
Jenkins ships the raw ``allure-results`` directory as a single ``tar.gz`` to a
TCRT webhook endpoint and TCRT — co-located with Allure — does the three-step
handshake (project ensure / send-results / generate-report) over loopback.

The resulting per-run ``report_url`` is written back onto ``AutomationRun`` and
returned to the caller so the run-status webhook can include it; either way
the TCRT UI sees the link the next time the user looks at the run.
"""
from __future__ import annotations

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
    AutomationScript,
    AutomationScriptGroup,
    Team,
)


logger = logging.getLogger(__name__)


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
            # 1. Idempotent project ensure. Allure returns 4xx if the project
            # already exists; that's expected and not an error for us.
            await _ensure_project(client, api_root, project_id, auth_headers)

            # 2. Upload each result file.
            await _send_results(client, api_root, project_id, result_files, auth_headers)

            # 3. Generate the report and capture the URL Allure assigns.
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
        # Treat 2xx as created, 4xx as "already exists" (Allure returns 405
        # for duplicate project ids in current versions). Only 5xx is a real
        # error here — but we still don't raise, because send-results below
        # is the authoritative signal for "project not usable".
        if resp.status_code >= 500:
            logger.warning(
                "Allure project ensure for %s returned %s", project_id, resp.status_code
            )
    except httpx.HTTPError as exc:
        logger.info("Allure project ensure for %s failed (non-fatal): %s", project_id, exc)


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
                    params={"project_id": project_id},
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


async def _generate_report(
    client: httpx.AsyncClient,
    api_root: str,
    project_id: str,
    run: AutomationRun,
    auth_headers: dict[str, str],
) -> str:
    exec_name = f"tcrt-{run.tcrt_correlation_id or run.id}"
    try:
        resp = await client.get(
            f"{api_root}/allure-docker-service/generate-report",
            params={"project_id": project_id, "execution_name": exec_name},
            headers=auth_headers,
        )
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
    team_result = await session.execute(
        select(Team.name).where(Team.id == run.team_id)
    )
    team_name = team_result.scalar_one_or_none() or ""
    team_slug = _slugify(team_name) or "team"

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

    try:
        return cfg.project_id_template.format(
            team_id=run.team_id,
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
