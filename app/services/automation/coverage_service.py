from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database_models import (
    AutomationRun,
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
        uncovered_limit: int = 50,
        stale_days: int = 30,
    ) -> dict[str, Any]:
        total_cases = await self._count_total_cases(team_id)
        with_primary = await self._count_cases_by_link_type(team_id, AutomationScriptLinkType.PRIMARY)
        with_covers = await self._count_cases_by_link_type(team_id, AutomationScriptLinkType.COVERS)
        with_any = await self._count_cases_with_coverage(team_id)
        uncovered_count = max(total_cases - with_any, 0)
        return {
            "total_test_cases": total_cases,
            "with_primary_link": with_primary,
            "with_covers_link": with_covers,
            "with_any_link": with_any,
            "uncovered_count": uncovered_count,
            "uncovered_sample": await self._list_uncovered_cases(team_id, uncovered_limit),
            "stale_scripts": await self._list_stale_scripts(team_id, stale_days),
            "by_format": await self._count_scripts_by_format(team_id),
            "trend": await self._build_trend(team_id, total_cases),
        }

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

    async def _list_stale_scripts(self, team_id: int, stale_days: int) -> list[dict[str, Any]]:
        now = _utcnow()
        cutoff = now - timedelta(days=stale_days)
        last_run_at = func.max(
            func.coalesce(AutomationRun.finished_at, AutomationRun.started_at, AutomationRun.created_at)
        ).label("last_run_at")
        last_run_subquery = (
            select(AutomationRun.automation_script_id.label("script_id"), last_run_at)
            .where(
                AutomationRun.team_id == team_id,
                AutomationRun.automation_script_id.is_not(None),
            )
            .group_by(AutomationRun.automation_script_id)
            .subquery()
        )

        result = await self.session.execute(
            select(
                AutomationScript.id,
                AutomationScript.name,
                AutomationScript.script_format,
                AutomationScript.ref_path,
                last_run_subquery.c.last_run_at,
            )
            .outerjoin(last_run_subquery, last_run_subquery.c.script_id == AutomationScript.id)
            .where(
                AutomationScript.team_id == team_id,
                (last_run_subquery.c.last_run_at.is_(None)) | (last_run_subquery.c.last_run_at < cutoff),
            )
            .order_by(last_run_subquery.c.last_run_at.asc(), AutomationScript.ref_path.asc())
            .limit(50)
        )
        stale_scripts = []
        for row in result.all():
            last_run = row.last_run_at
            stale_scripts.append(
                {
                    "script_id": row.id,
                    "name": row.name,
                    "script_format": _enum_value(row.script_format),
                    "ref_path": row.ref_path,
                    "last_run_at": last_run,
                    "days_since_last_run": None if last_run is None else max((now - last_run).days, 0),
                }
            )
        return stale_scripts

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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)
