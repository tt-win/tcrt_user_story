from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database_models import (
    AutomationScript,
    AutomationScriptCaseLink,
    AutomationScriptLinkType,
    TestCaseLocal,
)


class AutomationCoverageService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def compute_coverage(
        self,
        *,
        team_id: int,
        uncovered_limit: int = 500,
    ) -> dict[str, Any]:
        total_cases = await self._count_total_cases(team_id)
        with_primary = await self._count_cases_by_link_type(team_id, AutomationScriptLinkType.PRIMARY)
        with_covers = await self._count_cases_by_link_type(team_id, AutomationScriptLinkType.COVERS)
        with_any = await self._count_cases_with_coverage(team_id)
        uncovered_count = max(total_cases - with_any, 0)
        by_group = await self._build_group_rollup(team_id)
        return {
            "total_test_cases": total_cases,
            "with_primary_link": with_primary,
            "with_covers_link": with_covers,
            "with_any_link": with_any,
            "uncovered_count": uncovered_count,
            "uncovered_sample": await self._list_uncovered_cases(team_id, uncovered_limit),
            "by_group": by_group,
            "by_format": await self._count_scripts_by_format(team_id),
            "trend": await self._build_trend(team_id, total_cases),
        }

    async def _build_group_rollup(self, team_id: int) -> list[dict[str, Any]]:
        """Per-ticket-group coverage rollup (total / covered / primary).

        Group key = the test case number's prefix before the first dot
        (``TCG-114460.030.050`` → ``TCG-114460``); dotless numbers group as
        themselves. Coverage counts PRIMARY/COVERS links only. The per-case
        list + links are served by ``list_cases`` (paginated), not here, so the
        summary payload stays small regardless of case count.
        """
        cases_result = await self.session.execute(
            select(TestCaseLocal.id, TestCaseLocal.test_case_number).where(TestCaseLocal.team_id == team_id)
        )
        cases = cases_result.all()

        covering_types_by_case = await self._covering_types_by_case(team_id)

        groups: dict[str, dict[str, int]] = {}
        for case in cases:
            number = case.test_case_number or ""
            group_key = number.split(".", 1)[0] if number else "(no number)"
            bucket = groups.setdefault(group_key, {"total": 0, "covered": 0, "primary": 0})
            bucket["total"] += 1
            covering = covering_types_by_case.get(int(case.id))
            if covering:
                bucket["covered"] += 1
                if AutomationScriptLinkType.PRIMARY.value in covering:
                    bucket["primary"] += 1

        return [
            {
                "group": key,
                "total": bucket["total"],
                "covered": bucket["covered"],
                "primary": bucket["primary"],
            }
            for key, bucket in sorted(groups.items())
        ]

    async def _covering_types_by_case(self, team_id: int) -> dict[int, set[str]]:
        """Map case_id → set of coverage link types (PRIMARY/COVERS) present."""
        result = await self.session.execute(
            select(AutomationScriptCaseLink.test_case_id, AutomationScriptCaseLink.link_type).where(
                AutomationScriptCaseLink.team_id == team_id,
                AutomationScriptCaseLink.link_type.in_(_COVERAGE_LINK_TYPES),
            )
        )
        covering: dict[int, set[str]] = {}
        for row in result.all():
            covering.setdefault(int(row.test_case_id), set()).add(_enum_value(row.link_type))
        return covering

    async def list_cases(
        self,
        *,
        team_id: int,
        status: str = "all",
        group: str | None = None,
        q: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        """Paginated, filterable, searchable case list with per-case coverage
        status + linked scripts. Server-side filtering keeps the browser fast
        when a team has thousands of manual cases.

        ``status``: all | covered | uncovered | primary.
        ``group``: ticket-prefix group key (``TCG-114460``) — matches the case
        number itself or any ``<group>.*`` child. ``q``: substring of number/title.
        """
        covered_exists = (
            select(AutomationScriptCaseLink.id)
            .where(
                AutomationScriptCaseLink.team_id == team_id,
                AutomationScriptCaseLink.test_case_id == TestCaseLocal.id,
                AutomationScriptCaseLink.link_type.in_(_COVERAGE_LINK_TYPES),
            )
            .exists()
        )
        primary_exists = (
            select(AutomationScriptCaseLink.id)
            .where(
                AutomationScriptCaseLink.team_id == team_id,
                AutomationScriptCaseLink.test_case_id == TestCaseLocal.id,
                AutomationScriptCaseLink.link_type == AutomationScriptLinkType.PRIMARY,
            )
            .exists()
        )

        conditions = [TestCaseLocal.team_id == team_id]
        if group:
            conditions.append(
                or_(
                    TestCaseLocal.test_case_number == group,
                    TestCaseLocal.test_case_number.like(f"{group}.%"),
                )
            )
        if q:
            like = f"%{q.strip()}%"
            conditions.append(
                or_(TestCaseLocal.test_case_number.ilike(like), TestCaseLocal.title.ilike(like))
            )
        if status == "covered":
            conditions.append(covered_exists)
        elif status == "uncovered":
            conditions.append(~covered_exists)
        elif status == "primary":
            conditions.append(primary_exists)

        total = int(
            (
                await self.session.execute(
                    select(func.count(TestCaseLocal.id)).where(*conditions)
                )
            ).scalar_one()
            or 0
        )

        rows = (
            await self.session.execute(
                select(TestCaseLocal.id, TestCaseLocal.test_case_number, TestCaseLocal.title)
                .where(*conditions)
                .order_by(TestCaseLocal.test_case_number, TestCaseLocal.id)
                .offset(max(skip, 0))
                .limit(limit)
            )
        ).all()

        case_ids = [int(r.id) for r in rows]
        links_by_case, covering_by_case = await self._links_for_cases(team_id, case_ids)

        items: list[dict[str, Any]] = []
        for r in rows:
            cid = int(r.id)
            covering = covering_by_case.get(cid)
            if covering and AutomationScriptLinkType.PRIMARY.value in covering:
                case_status = "primary"
            elif covering:
                case_status = "covers"
            else:
                case_status = "uncovered"
            items.append(
                {
                    "test_case_id": cid,
                    "test_case_number": r.test_case_number,
                    "title": r.title,
                    "status": case_status,
                    "links": links_by_case.get(cid, []),
                }
            )
        return items, total

    async def _links_for_cases(
        self, team_id: int, case_ids: list[int]
    ) -> tuple[dict[int, list[dict[str, Any]]], dict[int, set[str]]]:
        """Linked scripts + coverage-type set for a specific page of cases."""
        if not case_ids:
            return {}, {}
        result = await self.session.execute(
            select(
                AutomationScriptCaseLink.test_case_id,
                AutomationScriptCaseLink.link_type,
                AutomationScript.id.label("script_id"),
                AutomationScript.name.label("script_name"),
                AutomationScript.ref_repo,
                AutomationScript.ref_path,
            )
            .join(AutomationScript, AutomationScript.id == AutomationScriptCaseLink.automation_script_id)
            .where(
                AutomationScriptCaseLink.team_id == team_id,
                AutomationScriptCaseLink.test_case_id.in_(case_ids),
            )
            .order_by(AutomationScriptCaseLink.link_type, AutomationScript.name)
        )
        links_by_case: dict[int, list[dict[str, Any]]] = {}
        covering_by_case: dict[int, set[str]] = {}
        for row in result.all():
            cid = int(row.test_case_id)
            link_type = _enum_value(row.link_type)
            links_by_case.setdefault(cid, []).append(
                {
                    "script_id": int(row.script_id),
                    "script_name": row.script_name,
                    "ref_repo": row.ref_repo or "",
                    "ref_path": row.ref_path,
                    "link_type": link_type,
                }
            )
            if link_type in _COVERAGE_LINK_TYPE_VALUES:
                covering_by_case.setdefault(cid, set()).add(link_type)
        return links_by_case, covering_by_case

    async def _count_total_cases(self, team_id: int) -> int:
        result = await self.session.execute(
            select(func.count(TestCaseLocal.id)).where(TestCaseLocal.team_id == team_id)
        )
        return int(result.scalar_one() or 0)

    async def _count_cases_by_link_type(self, team_id: int, link_type: AutomationScriptLinkType) -> int:
        result = await self.session.execute(
            select(func.count(func.distinct(AutomationScriptCaseLink.test_case_id))).where(
                AutomationScriptCaseLink.team_id == team_id,
                AutomationScriptCaseLink.link_type == link_type,
            )
        )
        return int(result.scalar_one() or 0)

    async def _count_cases_with_coverage(self, team_id: int) -> int:
        result = await self.session.execute(
            select(func.count(func.distinct(AutomationScriptCaseLink.test_case_id))).where(
                AutomationScriptCaseLink.team_id == team_id,
                AutomationScriptCaseLink.link_type.in_(_COVERAGE_LINK_TYPES),
            )
        )
        return int(result.scalar_one() or 0)

    async def _list_uncovered_cases(self, team_id: int, limit: int) -> list[dict[str, Any]]:
        covered_exists = (
            select(AutomationScriptCaseLink.id)
            .where(
                AutomationScriptCaseLink.team_id == team_id,
                AutomationScriptCaseLink.test_case_id == TestCaseLocal.id,
                AutomationScriptCaseLink.link_type.in_(_COVERAGE_LINK_TYPES),
            )
            .exists()
        )
        result = await self.session.execute(
            select(TestCaseLocal.id, TestCaseLocal.test_case_number, TestCaseLocal.title)
            .where(TestCaseLocal.team_id == team_id, ~covered_exists)
            .order_by(TestCaseLocal.test_case_number, TestCaseLocal.id)
            .limit(limit)
        )
        return [
            {
                "test_case_id": row.id,
                "test_case_number": row.test_case_number,
                "title": row.title,
            }
            for row in result.all()
        ]

    async def _count_scripts_by_format(self, team_id: int) -> dict[str, int]:
        result = await self.session.execute(
            select(AutomationScript.script_format, func.count(AutomationScript.id).label("script_count"))
            .where(AutomationScript.team_id == team_id)
            .group_by(AutomationScript.script_format)
        )
        return {_enum_value(row.script_format): int(row.script_count or 0) for row in result.all()}

    async def _build_trend(self, team_id: int, total_cases: int) -> list[dict[str, Any]]:
        today = _utcnow().date()
        first_day = today - timedelta(days=29)
        result = await self.session.execute(
            select(
                AutomationScriptCaseLink.test_case_id,
                AutomationScriptCaseLink.link_type,
                AutomationScriptCaseLink.created_at,
            ).where(
                AutomationScriptCaseLink.team_id == team_id,
                AutomationScriptCaseLink.link_type.in_(_COVERAGE_LINK_TYPES),
            )
        )

        first_any_by_case: dict[int, datetime] = {}
        first_primary_by_case: dict[int, datetime] = {}
        for row in result.all():
            created_at = row.created_at or datetime.combine(first_day, time.min)
            case_id = int(row.test_case_id)
            current_any = first_any_by_case.get(case_id)
            if current_any is None or created_at < current_any:
                first_any_by_case[case_id] = created_at
            if _enum_value(row.link_type) == AutomationScriptLinkType.PRIMARY.value:
                current_primary = first_primary_by_case.get(case_id)
                if current_primary is None or created_at < current_primary:
                    first_primary_by_case[case_id] = created_at

        trend = []
        for offset in range(30):
            day = first_day + timedelta(days=offset)
            end_of_day = datetime.combine(day, time.max)
            with_any = sum(1 for created_at in first_any_by_case.values() if created_at <= end_of_day)
            with_primary = sum(1 for created_at in first_primary_by_case.values() if created_at <= end_of_day)
            trend.append(
                {
                    "date": day,
                    "with_primary_link": with_primary,
                    "with_any_link": with_any,
                    "uncovered_count": max(total_cases - with_any, 0),
                    "coverage_rate": round((with_any / total_cases) * 100, 2) if total_cases else 0.0,
                }
            )
        return trend


_COVERAGE_LINK_TYPES = (
    AutomationScriptLinkType.PRIMARY,
    AutomationScriptLinkType.COVERS,
)
_COVERAGE_LINK_TYPE_VALUES = {item.value for item in _COVERAGE_LINK_TYPES}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)
