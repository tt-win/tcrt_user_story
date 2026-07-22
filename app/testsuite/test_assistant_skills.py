"""Factory skill files + registry local tools — every skill path exercised."""

from __future__ import annotations

import re
from pathlib import Path
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.assistant.content_store import (  # noqa: E402
    _parse_frontmatter,
    load_factory_skills,
)
from app.services.assistant.skills import (  # noqa: E402
    format_skill_catalog_for_prompt,
    get_skill,
    list_skill_catalog,
    load_skills,
)
from app.services.assistant.tool_registry import get_tool_registry  # noqa: E402

_SKILLS_DIR = PROJECT_ROOT / "prompts" / "assistant" / "skills"
# Backtick token that looks like a tool name (snake_case with action-ish prefix or multi-part).
# Tool names are multi-segment snake_case (e.g. list_test_cases), not params like set_id.
_TOOLISH_RE = re.compile(
    r"`("
    r"(?:list|get|create|update|delete|batch|add|archive|run|cancel|reconcile|pin|unpin|"
    r"move|bulk|find|count|preview|upload|restart|generate)_[a-z0-9]+(?:_[a-z0-9]+)+"
    r"|batch_execute_actions|set_test_run_status"
    r")`"
)


def _disk_skill_files() -> list[Path]:
    return sorted(_SKILLS_DIR.glob("*.md"))


def test_factory_skills_load_with_unique_ids():
    skills = load_skills()
    assert skills, "expected factory skills under prompts/assistant/skills/"
    ids = [s.skill_id for s in skills]
    assert len(ids) == len(set(ids))
    disk = _disk_skill_files()
    assert len(skills) == len(disk), (
        f"loader dropped skills: disk={len(disk)} loaded={len(skills)} "
        f"disk_stems={[p.stem for p in disk]} loaded={ids}"
    )


def test_every_disk_skill_file_loads_with_matching_id():
    """Each *.md is loadable; frontmatter id/skill_id matches stem (or explicit id)."""
    loaded = {s.skill_id: s for s in load_factory_skills()}
    for path in _disk_skill_files():
        raw = path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(raw)
        expected_id = str(meta.get("id") or meta.get("skill_id") or path.stem).strip()
        assert body.strip(), f"{path.name}: empty body"
        assert str(meta.get("description") or "").strip(), f"{path.name}: empty description"
        assert expected_id in loaded, f"{path.name}: skill_id {expected_id!r} not loaded"
        skill = loaded[expected_id]
        assert skill.name.strip()
        assert skill.body.strip()
        # Prefer explicit id; skill_id alone is accepted via loader fallback.
        if meta.get("id") is not None:
            assert str(meta["id"]).strip() == expected_id


def test_skill_catalog_prompt_contains_all_skill_ids():
    catalog = format_skill_catalog_for_prompt()
    for skill in load_factory_skills():
        assert skill.skill_id in catalog, f"catalog missing {skill.skill_id}"


def test_get_skill_returns_body_for_every_factory_id():
    for skill in load_factory_skills():
        got = get_skill(skill.skill_id)
        assert got is not None, skill.skill_id
        assert got["skill_id"] == skill.skill_id
        assert got["body"].strip()
        assert got["name"].strip()
        assert got["description"].strip()


def test_get_skill_unknown_returns_none():
    assert get_skill("does-not-exist") is None


def test_every_skill_body_tool_refs_exist_in_registry():
    """Any toolish backtick name in a skill body must exist in the live registry."""
    registry = get_tool_registry()
    known = set(registry.names())
    failures: list[str] = []
    for skill in load_factory_skills():
        for match in _TOOLISH_RE.finditer(skill.body):
            name = match.group(1)
            if name not in known:
                failures.append(f"{skill.skill_id}: unknown tool `{name}`")
    assert not failures, "stale tool references:\n" + "\n".join(failures)


def test_registry_exposes_local_skill_tools():
    registry = get_tool_registry()
    list_tool = registry.get("list_skills")
    get_tool = registry.get("get_skill")
    assert list_tool is not None and list_tool.execution_mode == "local"
    assert get_tool is not None and get_tool.execution_mode == "local"
    discovery_names = {t.name for t in registry.discovery_only()}
    assert "list_skills" in discovery_names
    assert "get_skill" in discovery_names


def test_batch_update_results_schema_allows_assignee_only():
    tool = get_tool_registry().get("batch_update_results")
    assert tool is not None
    props = tool.body_schema["properties"]["updates"]["items"]["properties"]
    assert "assignee_name" in props
    assert tool.body_schema["properties"]["updates"]["items"]["required"] == ["id"]


def test_list_skill_catalog_nonempty_and_covers_all():
    catalog = list_skill_catalog()
    assert catalog
    catalog_ids = {row["skill_id"] for row in catalog}
    factory_ids = {s.skill_id for s in load_factory_skills()}
    assert catalog_ids == factory_ids


@pytest.mark.asyncio
async def test_local_list_and_get_skill_for_every_id():
    """Drive ToolExecutor local handlers (same path as agent list_skills/get_skill)."""
    from app.config import AssistantConfig
    from app.db_access.main import get_main_access_boundary
    from app.main import app
    from app.services.assistant.tool_executor import ToolExecutor

    cfg = AssistantConfig()
    registry = get_tool_registry()
    executor = ToolExecutor(
        app=app,
        main_boundary=get_main_access_boundary(),
        config=cfg,
        registry=registry,
    )
    list_tool = registry.get("list_skills")
    get_tool = registry.get("get_skill")
    assert list_tool and get_tool

    status, payload = await executor._run_local_read_tool(list_tool, {})
    assert status == 200
    listed = payload.get("skills") or []
    listed_ids = {row["skill_id"] for row in listed}
    factory_ids = {s.skill_id for s in load_factory_skills()}
    assert factory_ids.issubset(listed_ids), (
        f"enabled list missing factory skills: {sorted(factory_ids - listed_ids)}"
    )
    assert payload.get("count") == len(listed)

    for skill_id in sorted(factory_ids):
        st, body = await executor._run_local_read_tool(get_tool, {"skill_id": skill_id})
        assert st == 200, f"{skill_id}: {body}"
        assert body.get("skill_id") == skill_id
        assert (body.get("body") or "").strip(), skill_id
        assert (body.get("name") or "").strip(), skill_id


@pytest.mark.asyncio
async def test_local_get_skill_unknown_returns_404():
    from app.config import AssistantConfig
    from app.db_access.main import get_main_access_boundary
    from app.main import app
    from app.services.assistant.tool_executor import ToolExecutor

    executor = ToolExecutor(
        app=app,
        main_boundary=get_main_access_boundary(),
        config=AssistantConfig(),
        registry=get_tool_registry(),
    )
    get_tool = get_tool_registry().get("get_skill")
    st, body = await executor._run_local_read_tool(get_tool, {"skill_id": "no-such-skill"})
    assert st == 404
    assert "detail" in body
