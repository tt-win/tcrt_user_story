"""Skill helpers: factory file parsing + thin re-exports for agent/tests.

Runtime agent path uses ``content_store`` (DB). Factory loaders remain for seed and
offline unit tests that only need bundled recipes.
"""

from __future__ import annotations

from app.services.assistant.content_store import (
    format_catalog_markdown,
    load_factory_skills,
    load_factory_system_prompt,
)


def load_skills():
    """Factory skills only (seed / offline tests). Prefer content_store for runtime."""
    return tuple(load_factory_skills())


def list_skill_catalog() -> list[dict]:
    return [
        {
            "skill_id": s.skill_id,
            "name": s.name,
            "description": s.description,
            "triggers": list(s.triggers),
        }
        for s in load_factory_skills()
    ]


def get_skill(skill_id: str):
    needle = (skill_id or "").strip()
    for s in load_factory_skills():
        if s.skill_id == needle:
            return {
                "skill_id": s.skill_id,
                "name": s.name,
                "description": s.description,
                "triggers": list(s.triggers),
                "body": s.body,
            }
    return None


def format_skill_catalog_for_prompt() -> str:
    return format_catalog_markdown(list_skill_catalog())


def clear_skills_cache() -> None:
    # DB cache lives in content_store; factory loaders are pure disk reads.
    from app.services.assistant.content_store import invalidate_content_cache

    invalidate_content_cache()


__all__ = [
    "load_skills",
    "list_skill_catalog",
    "get_skill",
    "format_skill_catalog_for_prompt",
    "clear_skills_cache",
    "load_factory_system_prompt",
]
