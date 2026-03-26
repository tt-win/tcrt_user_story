from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from typing import Any, Optional
import urllib.parse

from app.config import PROJECT_ROOT, settings


class AttachmentPathResolutionError(ValueError):
    pass


def get_attachments_root_dir(project_root: Optional[Path] = None) -> Path:
    env_root = os.getenv("ATTACHMENTS_ROOT_DIR", "").strip()
    if env_root:
        return Path(env_root)
    configured_root = getattr(settings, "attachments", None)
    if configured_root:
        return settings.attachments.resolve_root_dir(project_root or PROJECT_ROOT)
    base_root = project_root or PROJECT_ROOT
    return base_root / "attachments"


def build_attachment_url(relative_path: str | None) -> str:
    rel = str(relative_path or "").strip()
    if not rel:
        return ""
    rel = rel.replace("\\", "/").lstrip("/")
    return f"/attachments/{urllib.parse.quote(rel, safe='/')}"


def get_attachment_access_url(metadata: dict[str, Any]) -> str:
    if not isinstance(metadata, dict):
        return ""
    local_url = build_attachment_url(metadata.get("relative_path"))
    if local_url:
        return local_url
    remote_url = str(metadata.get("url") or metadata.get("tmp_url") or "").strip()
    return remote_url


def ensure_relative_attachment_path(relative_path: str | Path) -> PurePosixPath:
    rel = str(relative_path or "").strip()
    if not rel:
        raise AttachmentPathResolutionError("缺少 relative_path")
    rel = urllib.parse.unquote(rel).replace("\\", "/")
    path = PurePosixPath(rel)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise AttachmentPathResolutionError(f"非法附件相對路徑: {relative_path}")
    return path


def resolve_relative_attachment_path(relative_path: str | Path, *, project_root: Optional[Path] = None) -> Path:
    root_dir = get_attachments_root_dir(project_root)
    rel_path = ensure_relative_attachment_path(relative_path)
    candidate = (root_dir / rel_path).resolve()
    _ensure_within_root(candidate, root_dir)
    return candidate


def extract_relative_attachment_path(metadata: dict[str, Any]) -> Optional[PurePosixPath]:
    rel = metadata.get("relative_path")
    if not rel:
        return None
    try:
        return ensure_relative_attachment_path(rel)
    except AttachmentPathResolutionError:
        return None


def resolve_attachment_metadata_path(
    metadata: dict[str, Any],
    *,
    project_root: Optional[Path] = None,
    allow_legacy_absolute: bool = True,
) -> Path:
    root_dir = get_attachments_root_dir(project_root)
    rel_path = extract_relative_attachment_path(metadata)
    if rel_path is not None:
        return resolve_relative_attachment_path(rel_path, project_root=project_root)

    if allow_legacy_absolute:
        absolute = metadata.get("absolute_path")
        if absolute:
            candidate = Path(str(absolute)).expanduser().resolve()
            _ensure_within_root(candidate, root_dir)
            return candidate

    raise AttachmentPathResolutionError("附件 metadata 缺少可用路徑")


def build_attachment_metadata(
    *,
    root_dir: Path,
    stored_path: Path,
    original_name: str,
    stored_name: str,
    size: int,
    content_type: str,
    uploaded_at: str,
) -> dict[str, Any]:
    resolved_root = root_dir.resolve()
    resolved_path = stored_path.resolve()
    _ensure_within_root(resolved_path, resolved_root)
    return {
        "name": original_name,
        "stored_name": stored_name,
        "size": int(size),
        "type": content_type or "application/octet-stream",
        "relative_path": str(resolved_path.relative_to(resolved_root).as_posix()),
        "uploaded_at": uploaded_at,
    }


def normalize_attachment_metadata(
    metadata: dict[str, Any],
    *,
    project_root: Optional[Path] = None,
    drop_absolute_path: bool = True,
    allow_missing_path: bool = False,
) -> dict[str, Any]:
    normalized = dict(metadata or {})
    try:
        resolved = resolve_attachment_metadata_path(normalized, project_root=project_root)
    except AttachmentPathResolutionError:
        if not allow_missing_path:
            raise
        if drop_absolute_path:
            normalized.pop("absolute_path", None)
        return normalized
    root_dir = get_attachments_root_dir(project_root).resolve()
    normalized["relative_path"] = str(resolved.relative_to(root_dir).as_posix())
    if drop_absolute_path:
        normalized.pop("absolute_path", None)
    return normalized


def _ensure_within_root(candidate: Path, root_dir: Path) -> None:
    try:
        candidate.resolve().relative_to(root_dir.resolve())
    except ValueError as exc:
        raise AttachmentPathResolutionError(f"附件路徑不在根目錄下: {candidate}") from exc
