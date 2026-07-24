"""DB-backed assistant system prompt + skill recipes (spec assistant-prompt-skills-admin).

Factory files under ``prompts/assistant/`` are seed-only. Runtime reads/writes go to main DB.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_access.main import MainAccessBoundary
from app.models.database_models import AssistantPromptDocument, AssistantSkillRow

logger = logging.getLogger(__name__)

SYSTEM_DOC_KEY = "system"
SKILL_CATALOG_TOKEN = "{{SKILL_CATALOG}}"
SYSTEM_MIN_CHARS = 200
SYSTEM_MAX_CHARS = 65536
SKILL_BODY_MAX_CHARS = 32768
SKILL_MAX_COUNT = 200
TRIGGER_MAX_COUNT = 20
TRIGGER_MAX_LEN = 64
SKILL_ID_RE = re.compile(r"^[a-z](?:[a-z0-9-]{0,62}[a-z0-9])?$")

_PROMPTS_ROOT = Path(__file__).resolve().parents[3] / "prompts" / "assistant"
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)
_SCALAR_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")

# process-local cache: (expires_at, payload)
_cache_system: Optional[tuple[float, str]] = None
_cache_catalog: Optional[tuple[float, str]] = None
_CACHE_TTL_SECONDS = 5.0


class ContentStoreError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def content_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def invalidate_content_cache() -> None:
    global _cache_system, _cache_catalog
    _cache_system = None
    _cache_catalog = None


def factory_prompts_root() -> Path:
    return _PROMPTS_ROOT


def _parse_frontmatter(raw: str) -> tuple[dict[str, object], str]:
    match = _FRONTMATTER_RE.match(raw)
    if not match:
        return {}, raw.strip()
    meta: dict[str, object] = {}
    current_list_key: Optional[str] = None
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current_list_key is not None:
            value = stripped[2:].strip().strip("\"'")
            existing = meta.get(current_list_key)
            if isinstance(existing, list):
                existing.append(value)
            continue
        scalar = _SCALAR_RE.match(stripped)
        if not scalar:
            current_list_key = None
            continue
        key, value = scalar.group(1), scalar.group(2).strip()
        if value in ("", "|", ">"):
            meta[key] = []
            current_list_key = key
            continue
        current_list_key = None
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            meta[key] = (
                [part.strip().strip("\"'") for part in inner.split(",") if part.strip()]
                if inner
                else []
            )
        else:
            meta[key] = value.strip("\"'")
    return meta, match.group(2).strip()


@dataclass(frozen=True)
class FactorySkill:
    skill_id: str
    name: str
    description: str
    body: str
    triggers: tuple[str, ...]
    sort_order: int


def load_factory_system_prompt() -> Optional[str]:
    path = _PROMPTS_ROOT / "system.md"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def load_factory_skills() -> list[FactorySkill]:
    skills_dir = _PROMPTS_ROOT / "skills"
    if not skills_dir.is_dir():
        return []
    out: list[FactorySkill] = []
    order = 0
    for path in sorted(skills_dir.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(raw)
        # Accept either `id` or `skill_id` in frontmatter (legacy recipes used either).
        skill_id = str(meta.get("id") or meta.get("skill_id") or path.stem).strip()
        name = str(meta.get("name") or skill_id).strip()
        description = str(meta.get("description") or "").strip()
        if not skill_id or not description or not body:
            continue
        triggers_raw = meta.get("triggers") or []
        if isinstance(triggers_raw, str):
            triggers = tuple(p.strip() for p in triggers_raw.split(",") if p.strip())
        elif isinstance(triggers_raw, list):
            triggers = tuple(str(x).strip() for x in triggers_raw if str(x).strip())
        else:
            triggers = ()
        out.append(
            FactorySkill(
                skill_id=skill_id,
                name=name,
                description=description,
                body=body,
                triggers=triggers,
                sort_order=order,
            )
        )
        order += 10
    return out


def factory_skill_ids() -> set[str]:
    return {s.skill_id for s in load_factory_skills()}


def validate_skill_id(skill_id: str) -> None:
    if not SKILL_ID_RE.match(skill_id or ""):
        raise ContentStoreError("invalid_skill_id", "skill_id must be a lowercase slug (a-z, 0-9, hyphen), max 64")


def validate_system_content(content: str) -> None:
    if content is None:
        raise ContentStoreError("invalid_content", "content is required")
    n = len(content)
    if n < SYSTEM_MIN_CHARS:
        raise ContentStoreError("invalid_content", f"content must be at least {SYSTEM_MIN_CHARS} characters")
    if n > SYSTEM_MAX_CHARS:
        raise ContentStoreError("invalid_content", f"content must be at most {SYSTEM_MAX_CHARS} characters")
    count = content.count(SKILL_CATALOG_TOKEN)
    if count != 1:
        raise ContentStoreError(
            "invalid_catalog_token",
            f"content must contain exactly one {SKILL_CATALOG_TOKEN} token (found {count})",
        )


def validate_skill_fields(*, name: str, description: str, body: str, triggers: list[str]) -> None:
    if not (name or "").strip():
        raise ContentStoreError("invalid_name", "name is required")
    if len(name) > 200:
        raise ContentStoreError("invalid_name", "name too long")
    if not (description or "").strip():
        raise ContentStoreError("invalid_description", "description is required")
    if not (body or "").strip():
        raise ContentStoreError("invalid_body", "body is required")
    if len(body) > SKILL_BODY_MAX_CHARS:
        raise ContentStoreError("invalid_body", f"body must be at most {SKILL_BODY_MAX_CHARS} characters")
    if len(triggers) > TRIGGER_MAX_COUNT:
        raise ContentStoreError("invalid_triggers", f"at most {TRIGGER_MAX_COUNT} triggers")
    for t in triggers:
        if len(t) > TRIGGER_MAX_LEN:
            raise ContentStoreError("invalid_triggers", f"each trigger must be ≤{TRIGGER_MAX_LEN} chars")


def _triggers_from_row(row: AssistantSkillRow) -> list[str]:
    raw = row.triggers_json
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x) for x in data]
    except json.JSONDecodeError:
        pass
    return []


def _skill_to_dict(row: AssistantSkillRow, *, include_body: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "skill_id": row.skill_id,
        "name": row.name,
        "description": row.description,
        "triggers": _triggers_from_row(row),
        "is_enabled": bool(row.is_enabled),
        "is_builtin": bool(row.is_builtin),
        "sort_order": int(row.sort_order or 0),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "updated_by": row.updated_by,
    }
    if include_body:
        out["body"] = row.body
        out["id"] = row.id
        out["created_at"] = row.created_at.isoformat() if row.created_at else None
    return out


def format_catalog_markdown(skills: list[dict[str, Any]]) -> str:
    if not skills:
        return "(no skills registered)"
    lines = ["| skill_id | when to use |", "| --- | --- |"]
    for skill in skills:
        desc = str(skill.get("description") or "").replace("|", "\\|").replace("\n", " ")
        lines.append(f"| `{skill['skill_id']}` | {desc} |")
    return "\n".join(lines)


# Injected when a DB-seeded system prompt lacks tool-routing guidance.
# ensure_seeded is insert-only, so factory system.md changes do not auto-roll out.
# Soft routing: LLM picks the simplest path; knowledge graph is optional for semantic cases.
_TOOL_ROUTING_BLOCK = """
## Tool routing (overrides earlier rigid knowledge-first rules if any)

Pick the simplest tool that answers the question:
- Known test case number + need full content (steps / expected_result / precondition): use `get_test_case_global`.
- Exact keyword or number search / list / which team has this case: use `search_test_cases_global`.
- Semantic or fuzzy discovery (feature ownership when keywords are unclear): use `search_knowledge`; if degraded or empty, then `search_test_cases_global`.
- Do **not** route simple number/title lookups through the knowledge graph first.
- Label team attribution with `team_name` / `team_id` when present.
""".strip()


def ensure_tool_routing_rules(template: str) -> str:
    """Ensure stale DB prompts carry soft tool-routing (not forced knowledge-first)."""
    soft_markers = ("get_test_case_global", "依問題類型", "simplest tool")
    if any(m in template for m in soft_markers) and "get_test_case_global" in template:
        return template
    # Always append soft routing so it overrides older forced knowledge-first text in context.
    return f"{template.rstrip()}\n\n{_TOOL_ROUTING_BLOCK}\n"


# Backward-compatible alias used by older tests/call sites.
def ensure_knowledge_search_rules(template: str) -> str:
    return ensure_tool_routing_rules(template)


def assemble_system_prompt_text(template: str, catalog_md: str) -> str:
    template = ensure_tool_routing_rules(template)
    if SKILL_CATALOG_TOKEN in template:
        return template.replace(SKILL_CATALOG_TOKEN, catalog_md, 1)
    logger.warning("system prompt missing %s; appending catalog block", SKILL_CATALOG_TOKEN)
    return f"{template.rstrip()}\n\n## Skill catalog\n\n{catalog_md}\n"


async def ensure_seeded(boundary: MainAccessBoundary) -> dict[str, int]:
    """Insert-if-missing factory system + skills. Idempotent under unique constraints."""

    factory_system = load_factory_system_prompt()
    factory_skills = load_factory_skills()
    now = datetime.utcnow()

    async def _op(session: AsyncSession) -> tuple[int, int]:
        p_ins = 0
        s_ins = 0
        # Per-row savepoints so a concurrent unique race cannot roll back the whole seed batch.
        if factory_system:
            existing = await session.get(AssistantPromptDocument, SYSTEM_DOC_KEY)
            if existing is None:
                try:
                    async with session.begin_nested():
                        session.add(
                            AssistantPromptDocument(
                                doc_key=SYSTEM_DOC_KEY,
                                content=factory_system,
                                version=1,
                                updated_at=now,
                                updated_by="ensure-seeded",
                            )
                        )
                        await session.flush()
                    p_ins = 1
                except IntegrityError:
                    pass
        for fs in factory_skills:
            result = await session.execute(
                select(AssistantSkillRow.id).where(AssistantSkillRow.skill_id == fs.skill_id).limit(1)
            )
            if result.scalar_one_or_none() is not None:
                continue
            try:
                async with session.begin_nested():
                    session.add(
                        AssistantSkillRow(
                            skill_id=fs.skill_id,
                            name=fs.name,
                            description=fs.description,
                            body=fs.body,
                            triggers_json=json.dumps(list(fs.triggers), ensure_ascii=False),
                            is_enabled=True,
                            is_builtin=True,
                            sort_order=fs.sort_order,
                            created_at=now,
                            updated_at=now,
                            updated_by="ensure-seeded",
                        )
                    )
                    await session.flush()
                s_ins += 1
            except IntegrityError:
                continue
        return p_ins, s_ins

    try:
        inserted_prompts, inserted_skills = await boundary.run_write(_op)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ensure_seeded failed: %s", type(exc).__name__)
        return {"prompts": 0, "skills": 0}
    if inserted_prompts or inserted_skills:
        invalidate_content_cache()
    return {"prompts": inserted_prompts, "skills": inserted_skills}


async def get_system_prompt_row(boundary: MainAccessBoundary) -> Optional[dict[str, Any]]:
    await ensure_seeded(boundary)

    async def _op(session: AsyncSession) -> Optional[dict[str, Any]]:
        row = await session.get(AssistantPromptDocument, SYSTEM_DOC_KEY)
        if row is None:
            return None
        return {
            "doc_key": row.doc_key,
            "content": row.content,
            "version": int(row.version or 1),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "updated_by": row.updated_by,
            "content_sha256": content_sha256(row.content),
            "content_length": len(row.content),
        }

    return await boundary.run_read(_op)


async def update_system_prompt(
    boundary: MainAccessBoundary,
    *,
    content: str,
    expected_version: int,
    updated_by: Optional[str],
) -> dict[str, Any]:
    validate_system_content(content)

    async def _op(session: AsyncSession) -> dict[str, Any]:
        row = await session.get(AssistantPromptDocument, SYSTEM_DOC_KEY)
        if row is None:
            raise ContentStoreError("not_found", "system prompt not found; run restore/seed")
        if int(row.version or 0) != int(expected_version):
            raise ContentStoreError("prompt_stale", "version mismatch; re-read and retry")
        row.content = content
        row.version = int(row.version or 0) + 1
        row.updated_at = datetime.utcnow()
        row.updated_by = updated_by
        await session.flush()
        return {
            "doc_key": row.doc_key,
            "content": row.content,
            "version": int(row.version),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "updated_by": row.updated_by,
            "content_sha256": content_sha256(row.content),
            "content_length": len(row.content),
        }

    result = await boundary.run_write(_op)
    invalidate_content_cache()
    return result


async def list_skills_admin(boundary: MainAccessBoundary) -> list[dict[str, Any]]:
    await ensure_seeded(boundary)

    async def _op(session: AsyncSession) -> list[dict[str, Any]]:
        result = await session.execute(
            select(AssistantSkillRow).order_by(AssistantSkillRow.sort_order, AssistantSkillRow.skill_id)
        )
        rows = result.scalars().all()
        return [_skill_to_dict(r, include_body=False) for r in rows]

    return await boundary.run_read(_op)


async def list_enabled_skills(boundary: MainAccessBoundary) -> list[dict[str, Any]]:
    await ensure_seeded(boundary)

    async def _op(session: AsyncSession) -> list[dict[str, Any]]:
        result = await session.execute(
            select(AssistantSkillRow)
            .where(AssistantSkillRow.is_enabled.is_(True))
            .order_by(AssistantSkillRow.sort_order, AssistantSkillRow.skill_id)
        )
        rows = result.scalars().all()
        return [_skill_to_dict(r, include_body=False) for r in rows]

    return await boundary.run_read(_op)


async def get_skill_admin(boundary: MainAccessBoundary, skill_id: str) -> Optional[dict[str, Any]]:
    await ensure_seeded(boundary)

    async def _op(session: AsyncSession) -> Optional[dict[str, Any]]:
        result = await session.execute(
            select(AssistantSkillRow).where(AssistantSkillRow.skill_id == skill_id).limit(1)
        )
        row = result.scalar_one_or_none()
        return _skill_to_dict(row, include_body=True) if row else None

    return await boundary.run_read(_op)


async def get_skill_enabled(boundary: MainAccessBoundary, skill_id: str) -> Optional[dict[str, Any]]:
    """Agent-facing: only enabled skills; disabled looks like missing."""
    await ensure_seeded(boundary)

    async def _op(session: AsyncSession) -> Optional[dict[str, Any]]:
        result = await session.execute(
            select(AssistantSkillRow)
            .where(
                AssistantSkillRow.skill_id == skill_id,
                AssistantSkillRow.is_enabled.is_(True),
            )
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return {
            "skill_id": row.skill_id,
            "name": row.name,
            "description": row.description,
            "triggers": _triggers_from_row(row),
            "body": row.body,
        }

    return await boundary.run_read(_op)


async def create_skill(
    boundary: MainAccessBoundary,
    *,
    skill_id: str,
    name: str,
    description: str,
    body: str,
    triggers: Optional[list[str]] = None,
    is_enabled: bool = True,
    sort_order: int = 0,
    updated_by: Optional[str] = None,
) -> dict[str, Any]:
    # Normalize before validate so UI casing/underscores do not hard-fail.
    skill_id = (
        str(skill_id or "")
        .strip()
        .lower()
        .replace("_", "-")
        .replace(" ", "-")
    )
    validate_skill_id(skill_id)
    triggers = list(triggers or [])
    validate_skill_fields(name=name, description=description, body=body, triggers=triggers)
    if skill_id in factory_skill_ids():
        raise ContentStoreError("skill_id_reserved", "skill_id is reserved by factory catalog")

    async def _op(session: AsyncSession) -> dict[str, Any]:
        total = await session.scalar(select(func.count()).select_from(AssistantSkillRow))
        if int(total or 0) >= SKILL_MAX_COUNT:
            raise ContentStoreError("skill_limit", f"at most {SKILL_MAX_COUNT} skills")
        existing = await session.execute(
            select(AssistantSkillRow.id).where(AssistantSkillRow.skill_id == skill_id).limit(1)
        )
        if existing.scalar_one_or_none() is not None:
            raise ContentStoreError("skill_exists", "skill_id already exists")
        now = datetime.utcnow()
        row = AssistantSkillRow(
            skill_id=skill_id,
            name=name.strip(),
            description=description.strip(),
            body=body,
            triggers_json=json.dumps(triggers, ensure_ascii=False),
            is_enabled=bool(is_enabled),
            is_builtin=False,
            sort_order=int(sort_order),
            created_at=now,
            updated_at=now,
            updated_by=updated_by,
        )
        session.add(row)
        await session.flush()
        # Materialize while session is live (avoid expire_on_commit surprises).
        return {
            "skill_id": row.skill_id,
            "name": row.name,
            "description": row.description,
            "triggers": list(triggers),
            "is_enabled": bool(row.is_enabled),
            "is_builtin": bool(row.is_builtin),
            "sort_order": int(row.sort_order or 0),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "updated_by": row.updated_by,
            "body": row.body,
            "id": row.id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    try:
        result = await boundary.run_write(_op)
    except IntegrityError as exc:
        raise ContentStoreError("skill_exists", "skill_id already exists") from exc
    invalidate_content_cache()
    return result


async def update_skill(
    boundary: MainAccessBoundary,
    skill_id: str,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    body: Optional[str] = None,
    triggers: Optional[list[str]] = None,
    is_enabled: Optional[bool] = None,
    sort_order: Optional[int] = None,
    updated_by: Optional[str] = None,
) -> dict[str, Any]:
    # Pre-read + validate outside the write tx so domain errors never look like 500s.
    existing = await get_skill_admin(boundary, skill_id)
    if existing is None:
        raise ContentStoreError("not_found", "skill not found")
    new_name = name if name is not None else existing["name"]
    new_desc = description if description is not None else existing["description"]
    new_body = body if body is not None else existing["body"]
    new_triggers = triggers if triggers is not None else list(existing.get("triggers") or [])
    validate_skill_fields(name=new_name, description=new_desc, body=new_body, triggers=new_triggers)

    async def _op(session: AsyncSession) -> dict[str, Any]:
        result = await session.execute(
            select(AssistantSkillRow).where(AssistantSkillRow.skill_id == skill_id).limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise ContentStoreError("not_found", "skill not found")
        row.name = new_name.strip()
        row.description = new_desc.strip()
        row.body = new_body
        row.triggers_json = json.dumps(new_triggers, ensure_ascii=False)
        if is_enabled is not None:
            row.is_enabled = bool(is_enabled)
        if sort_order is not None:
            row.sort_order = int(sort_order)
        row.updated_at = datetime.utcnow()
        row.updated_by = updated_by
        await session.flush()
        return {
            "skill_id": row.skill_id,
            "name": row.name,
            "description": row.description,
            "triggers": list(new_triggers),
            "is_enabled": bool(row.is_enabled),
            "is_builtin": bool(row.is_builtin),
            "sort_order": int(row.sort_order or 0),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "updated_by": row.updated_by,
            "body": row.body,
            "id": row.id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    result = await boundary.run_write(_op)
    invalidate_content_cache()
    return result


async def delete_skill(boundary: MainAccessBoundary, skill_id: str) -> None:
    """Permanently delete a skill row (custom or builtin).

    Builtin skills CAN be deleted — the caller is Super Admin and the
    UI is expected to show a strong confirmation. On the next
    ``restore(overwrite-builtins)`` a deleted builtin row is re-inserted
    by :func:`restore`, so the deletion is reversible via the factory
    restore flow.
    """
    async def _op(session: AsyncSession) -> None:
        result = await session.execute(
            select(AssistantSkillRow).where(AssistantSkillRow.skill_id == skill_id).limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise ContentStoreError("not_found", "skill not found")
        await session.delete(row)

    await boundary.run_write(_op)
    invalidate_content_cache()


async def reset_skill_to_factory(
    boundary: MainAccessBoundary, skill_id: str, *, updated_by: Optional[str]
) -> dict[str, Any]:
    factory = {s.skill_id: s for s in load_factory_skills()}
    fs = factory.get(skill_id)
    if fs is None:
        raise ContentStoreError("not_factory", "skill_id is not in factory catalog")

    async def _op(session: AsyncSession) -> dict[str, Any]:
        result = await session.execute(
            select(AssistantSkillRow).where(AssistantSkillRow.skill_id == skill_id).limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise ContentStoreError("not_found", "skill not found")
        if not row.is_builtin:
            raise ContentStoreError("not_builtin", "only builtin skills can be reset to factory")
        row.name = fs.name
        row.description = fs.description
        row.body = fs.body
        row.triggers_json = json.dumps(list(fs.triggers), ensure_ascii=False)
        row.sort_order = fs.sort_order
        # keep is_enabled
        row.updated_at = datetime.utcnow()
        row.updated_by = updated_by
        await session.flush()
        return _skill_to_dict(row, include_body=True)

    result = await boundary.run_write(_op)
    invalidate_content_cache()
    return result


async def restore(
    boundary: MainAccessBoundary,
    *,
    mode: str,
    confirm: bool = False,
    updated_by: Optional[str] = None,
) -> dict[str, Any]:
    if mode not in ("missing-only", "overwrite-builtins"):
        raise ContentStoreError("invalid_mode", "mode must be missing-only or overwrite-builtins")
    if mode == "overwrite-builtins" and not confirm:
        raise ContentStoreError("confirm_required", "overwrite-builtins requires confirm=true")

    if mode == "missing-only":
        stats = await ensure_seeded(boundary)
        return {"mode": mode, **stats}

    factory_system = load_factory_system_prompt()
    factory_skills = load_factory_skills()
    now = datetime.utcnow()

    async def _op(session: AsyncSession) -> dict[str, int]:
        p_upd = 0
        s_upd = 0
        s_ins = 0
        if factory_system:
            row = await session.get(AssistantPromptDocument, SYSTEM_DOC_KEY)
            if row is None:
                session.add(
                    AssistantPromptDocument(
                        doc_key=SYSTEM_DOC_KEY,
                        content=factory_system,
                        version=1,
                        updated_at=now,
                        updated_by=updated_by or "restore",
                    )
                )
                p_upd = 1
            else:
                row.content = factory_system
                row.version = int(row.version or 0) + 1
                row.updated_at = now
                row.updated_by = updated_by or "restore"
                p_upd = 1
        for fs in factory_skills:
            result = await session.execute(
                select(AssistantSkillRow).where(AssistantSkillRow.skill_id == fs.skill_id).limit(1)
            )
            row = result.scalar_one_or_none()
            if row is None:
                session.add(
                    AssistantSkillRow(
                        skill_id=fs.skill_id,
                        name=fs.name,
                        description=fs.description,
                        body=fs.body,
                        triggers_json=json.dumps(list(fs.triggers), ensure_ascii=False),
                        is_enabled=True,
                        is_builtin=True,
                        sort_order=fs.sort_order,
                        created_at=now,
                        updated_at=now,
                        updated_by=updated_by or "restore",
                    )
                )
                s_ins += 1
            elif row.is_builtin:
                row.name = fs.name
                row.description = fs.description
                row.body = fs.body
                row.triggers_json = json.dumps(list(fs.triggers), ensure_ascii=False)
                row.sort_order = fs.sort_order
                # keep is_enabled
                row.updated_at = now
                row.updated_by = updated_by or "restore"
                s_upd += 1
        return {"prompts": p_upd, "skills_updated": s_upd, "skills_inserted": s_ins}

    stats = await boundary.run_write(_op)
    invalidate_content_cache()
    return {"mode": mode, **stats}


async def assemble_system_prompt_for_agent(boundary: MainAccessBoundary) -> str:
    """Turn-start: load template + enabled catalog from DB (short process cache)."""
    global _cache_system
    now = time.monotonic()
    if _cache_system and _cache_system[0] > now:
        return _cache_system[1]

    await ensure_seeded(boundary)

    async def _op(session: AsyncSession) -> tuple[str, str]:
        row = await session.get(AssistantPromptDocument, SYSTEM_DOC_KEY)
        if row is None or not row.content:
            factory = load_factory_system_prompt() or "You are the TCRT assistant.\n\n{{SKILL_CATALOG}}\n"
            template = factory
        else:
            template = row.content
        result = await session.execute(
            select(AssistantSkillRow)
            .where(AssistantSkillRow.is_enabled.is_(True))
            .order_by(AssistantSkillRow.sort_order, AssistantSkillRow.skill_id)
        )
        skills = [_skill_to_dict(r, include_body=False) for r in result.scalars().all()]
        catalog = format_catalog_markdown(skills)
        return template, catalog

    try:
        template, catalog = await boundary.run_read(_op)
    except Exception as exc:  # noqa: BLE001
        logger.warning("DB prompt load failed (%s); factory fallback", type(exc).__name__)
        template = load_factory_system_prompt() or "You are the TCRT assistant.\n\n{{SKILL_CATALOG}}\n"
        catalog = format_catalog_markdown(
            [
                {
                    "skill_id": s.skill_id,
                    "name": s.name,
                    "description": s.description,
                }
                for s in load_factory_skills()
            ]
        )
    assembled = assemble_system_prompt_text(template, catalog)
    _cache_system = (now + _CACHE_TTL_SECONDS, assembled)
    return assembled
