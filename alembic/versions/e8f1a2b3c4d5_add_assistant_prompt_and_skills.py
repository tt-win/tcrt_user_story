"""add assistant prompt documents and skills tables

Revision ID: e8f1a2b3c4d5
Revises: c9d2e4f6a8b1
Create Date: 2026-07-22 19:00:00.000000
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision: str = "e8f1a2b3c4d5"
down_revision: Union[str, Sequence[str], None] = "c9d2e4f6a8b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)
_SCALAR_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")


def _medium_text() -> sa.types.TypeEngine:
    return sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def _repo_prompts_root() -> Path:
    return Path(__file__).resolve().parents[2] / "prompts" / "assistant"


def _parse_frontmatter(raw: str) -> tuple[dict[str, object], str]:
    match = _FRONTMATTER_RE.match(raw)
    if not match:
        return {}, raw.strip()
    meta: dict[str, object] = {}
    current_list_key: str | None = None
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


def _seed_defaults(bind) -> None:
    root = _repo_prompts_root()
    now = datetime.utcnow()
    prompts = sa.table(
        "assistant_prompt_documents",
        sa.column("doc_key", sa.String),
        sa.column("content", sa.Text),
        sa.column("version", sa.Integer),
        sa.column("updated_at", sa.DateTime),
        sa.column("updated_by", sa.String),
    )
    skills = sa.table(
        "assistant_skills",
        sa.column("skill_id", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("body", sa.Text),
        sa.column("triggers_json", sa.Text),
        sa.column("is_enabled", sa.Boolean),
        sa.column("is_builtin", sa.Boolean),
        sa.column("sort_order", sa.Integer),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
        sa.column("updated_by", sa.String),
    )

    system_path = root / "system.md"
    if system_path.is_file():
        bind.execute(
            prompts.insert().values(
                doc_key="system",
                content=system_path.read_text(encoding="utf-8"),
                version=1,
                updated_at=now,
                updated_by="migration-seed",
            )
        )

    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        return
    order = 0
    for path in sorted(skills_dir.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(raw)
        skill_id = str(meta.get("id") or path.stem).strip()
        name = str(meta.get("name") or skill_id).strip()
        description = str(meta.get("description") or "").strip()
        if not skill_id or not description or not body:
            continue
        triggers = meta.get("triggers") or []
        if isinstance(triggers, str):
            triggers_list = [p.strip() for p in triggers.split(",") if p.strip()]
        elif isinstance(triggers, list):
            triggers_list = [str(x).strip() for x in triggers if str(x).strip()]
        else:
            triggers_list = []
        bind.execute(
            skills.insert().values(
                skill_id=skill_id,
                name=name,
                description=description,
                body=body,
                triggers_json=json.dumps(triggers_list, ensure_ascii=False),
                is_enabled=True,
                is_builtin=True,
                sort_order=order,
                created_at=now,
                updated_at=now,
                updated_by="migration-seed",
            )
        )
        order += 10


def upgrade() -> None:
    op.create_table(
        "assistant_prompt_documents",
        sa.Column("doc_key", sa.String(length=64), primary_key=True),
        sa.Column("content", _medium_text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
    )
    op.create_table(
        "assistant_skills",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("skill_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        # Model aliases Text → MediumText; MySQL must create MEDIUMTEXT or bootstrap gate fails.
        sa.Column("description", _medium_text(), nullable=False),
        sa.Column("body", _medium_text(), nullable=False),
        sa.Column("triggers_json", _medium_text(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.UniqueConstraint("skill_id", name="uq_assistant_skills_skill_id"),
    )
    op.create_index(
        "ix_assistant_skills_enabled_sort",
        "assistant_skills",
        ["is_enabled", "sort_order"],
    )
    try:
        _seed_defaults(op.get_bind())
    except Exception:
        pass


def downgrade() -> None:
    op.drop_index("ix_assistant_skills_enabled_sort", table_name="assistant_skills")
    op.drop_table("assistant_skills")
    op.drop_table("assistant_prompt_documents")
