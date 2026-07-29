"""Safe read-model assembly for the role-aware homepage dashboard."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
import logging
from typing import Any, Optional
from urllib.parse import quote

from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.audit import ActionType, ResourceType
from app.audit.database import AuditLogTable
from app.auth.models import UserRole
from app.db_access import (
    AuditAccessBoundary,
    MainAccessBoundary,
    get_audit_access_boundary,
    get_main_access_boundary,
)
from app.models.database_models import (
    ScheduledService,
    SystemAutomationProvider,
    Team,
    TestCaseLocal,
    TestRunConfig,
    TestRunItem,
    TestRunItemResultHistory,
    User,
)
from app.models.dashboard import DashboardCurrentUser, DashboardQuickAction, DashboardResponse
from app.services.system_settings_service import (
    AUTOMATION_HUB_ENTRY_ENABLED_KEY,
    get_bool,
)


logger = logging.getLogger(__name__)

_ACTIVE_TEAM = "active"
_ACTIVE_RUN = "active"
_DRAFT_RUN = "draft"
_TERMINAL_OUTCOME_RESULTS = {
    "Passed",
    "Failed",
    "Retest",
    "Not Available",
    "Not Required",
    "Skip",
}
_KNOWN_RESULTS = _TERMINAL_OUTCOME_RESULTS | {"Pending"}
_SYSTEM_OUTCOME_CODES = {"success", "failed", "error", "running", "skipped", "unknown"}
_SYSTEM_OUTCOME_ALIASES = {"completed": "success", "interrupted": "error"}
_AUDIT_ACTION_CODES = frozenset(action.value for action in ActionType)
_AUDIT_RESOURCE_CODES = frozenset(resource.value for resource in ResourceType)
_AUDIT_RESUME_RESOURCE_CODES = frozenset(
    {
        ResourceType.TEST_CASE.value,
        ResourceType.USER_STORY_MAP.value,
        ResourceType.AUTOMATION_PROVIDER.value,
        ResourceType.AUTOMATION_SCRIPT.value,
        ResourceType.AUTOMATION_SCRIPT_LINK.value,
        ResourceType.AUTOMATION_SCRIPT_GROUP.value,
        ResourceType.AUTOMATION_RUN.value,
        ResourceType.AUTOMATION_WEBHOOK.value,
        ResourceType.AUTOMATION_ENVIRONMENT.value,
    }
)
_AUTOMATION_AUDIT_RESOURCE_CODES = frozenset(
    resource
    for resource in _AUDIT_RESUME_RESOURCE_CODES
    if resource.startswith("automation_")
)
_MAX_ASSIGNED = 50
_MAX_ASSIGNED_RUNS = 50
_MAX_ASSIGNED_PREVIEW = 5
_MAX_RESUME = 10
_MAX_ACTIVITY = 20
_MAX_AUDIT = 10
_MAX_AUDIT_SCAN = 50
_MAX_HISTORY = 250


class DashboardService:
    """Assemble minimal role-specific data without trusting client scope."""

    def __init__(
        self,
        main_boundary: MainAccessBoundary | None = None,
        audit_boundary: AuditAccessBoundary | None = None,
    ) -> None:
        self.main_boundary = main_boundary or get_main_access_boundary()
        self.audit_boundary = audit_boundary or get_audit_access_boundary()

    async def build(self, current_user: User) -> DashboardResponse:
        if _role_value(current_user) == UserRole.SUPER_ADMIN.value:
            return await self._build_system(current_user)
        return await self._build_personal(current_user)

    async def _build_personal(self, current_user: User) -> DashboardResponse:
        payload = await self.main_boundary.run_sync_read(
            lambda session: _build_personal_main(session, current_user)
        )
        try:
            automation_hub_enabled = await self.main_boundary.run_read(
                _read_automation_hub_entry_enabled
            )
        except Exception:  # noqa: BLE001 - match the existing fail-open entry toggle
            logger.warning("Dashboard Automation Hub entry setting unavailable", exc_info=True)
            automation_hub_enabled = True
        audit_payload = await self._build_audit_fallback(
            current_user.id,
            payload.pop("visible_team_ids", []),
            {
                int(team["id"]): str(team.get("name") or "")
                for team in payload.get("teams", {}).get("items", [])
            },
        )
        audit_resume_items = audit_payload.pop("resume_items", [])
        payload["audit"] = audit_payload
        if _is_write_capable(current_user):
            if not automation_hub_enabled:
                audit_resume_items = [
                    item
                    for item in audit_resume_items
                    if item.get("kind") != "automation_hub"
                ]
            payload["resume"] = _merge_resume_sections(
                payload.get("resume"),
                audit_resume_items,
                audit_payload.get("state", "unavailable"),
            )
        quick_actions = [
            DashboardQuickAction(
                key="dashboard.quickAction.testRuns",
                href="/test-run-management",
                icon="fa-play-circle",
            ),
            DashboardQuickAction(
                key="dashboard.quickAction.testCases",
                href="/test-case-sets",
                icon="fa-list-check",
            ),
            DashboardQuickAction(
                key="dashboard.quickAction.userStoryMap",
                href="/user-story-map/{team_id}",
                icon="fa-project-diagram",
            ),
        ]
        if automation_hub_enabled:
            quick_actions.append(
                DashboardQuickAction(
                    key="dashboard.quickAction.automationHub",
                    href="/automation-hub",
                    icon="fa-robot",
                )
            )
        return DashboardResponse(
            dashboard_type="personal",
            current_user=_current_user_projection(current_user),
            sections=payload,
            quick_actions=quick_actions,
        )

    async def _build_audit_fallback(
        self,
        user_id: int,
        visible_team_ids: list[int],
        team_names: dict[int, str] | None = None,
    ) -> dict[str, Any]:
        if not visible_team_ids:
            return {"state": "ready", "items": [], "resume_items": []}
        visible_team_names = team_names or {}
        try:
            async def _read(session: AsyncSession) -> dict[str, Any]:
                result = await session.execute(
                    select(
                        AuditLogTable.id,
                        AuditLogTable.timestamp,
                        cast(AuditLogTable.action_type, String).label("action_type"),
                        cast(AuditLogTable.resource_type, String).label("resource_type"),
                        AuditLogTable.resource_id,
                        AuditLogTable.team_id,
                    )
                    .where(
                        AuditLogTable.user_id == user_id,
                        AuditLogTable.team_id.in_(visible_team_ids),
                    )
                    .order_by(AuditLogTable.timestamp.desc(), AuditLogTable.id.desc())
                    .limit(_MAX_AUDIT_SCAN)
                )
                rows = list(result)
                return {
                    "state": "ready",
                    "items": [
                        {
                            "timestamp": row.timestamp,
                            "action": _safe_allowlisted_code(
                                row.action_type, _AUDIT_ACTION_CODES
                            ),
                            "resource": _safe_allowlisted_code(
                                row.resource_type, _AUDIT_RESOURCE_CODES
                            ),
                        }
                        for row in rows[:_MAX_AUDIT]
                    ],
                    "resume_items": _build_audit_resume_items(
                        rows,
                        visible_team_names,
                    ),
                }

            return await self.audit_boundary.run_read(_read)
        except Exception:  # noqa: BLE001 - audit is an optional, separate boundary
            logger.warning("Dashboard audit fallback unavailable", exc_info=True)
            return {"state": "unavailable", "items": [], "resume_items": []}

    async def _build_system(self, current_user: User) -> DashboardResponse:
        sections = await self.main_boundary.run_sync_read(_build_system_main)
        return DashboardResponse(
            dashboard_type="system_administration",
            current_user=_current_user_projection(current_user),
            sections=sections,
            quick_actions=[
                DashboardQuickAction(
                    key="dashboard.systemAction.organization",
                    href="/organization-management",
                    icon="fa-users-cog",
                ),
                DashboardQuickAction(
                    key="dashboard.systemAction.audit",
                    href="/audit-logs",
                    icon="fa-clipboard-list",
                ),
                DashboardQuickAction(
                    key="dashboard.systemAction.logs",
                    href="/system-logs",
                    icon="fa-terminal",
                ),
                DashboardQuickAction(
                    key="dashboard.systemAction.teams",
                    href="/team-management",
                    icon="fa-users",
                ),
            ],
        )


def _build_personal_main(sync_db: Session, current_user: User) -> dict[str, Any]:
    teams = _load_visible_active_teams(sync_db, current_user)
    team_ids = [team["id"] for team in teams]
    sections: dict[str, Any] = {
        "teams": {"state": "ready", "items": teams},
        "resume": {"state": "ready", "items": []},
        "assigned": {"state": "ready", "items": []},
        "activity": {"state": "ready", "items": []},
        "outcomes": {"state": "ready", "window_days": 7, "total": 0, "counts": {}, "items": []},
        "visible_team_ids": team_ids,
    }
    if not team_ids:
        return sections

    try:
        assignee_condition = _assigned_identity_condition(sync_db, current_user)
        assigned_rows = _load_assigned_rows(
            sync_db,
            current_user,
            team_ids,
            assignee_condition=assignee_condition,
        )
        assigned_runs = _load_assigned_run_groups(
            sync_db,
            team_ids,
            assignee_condition,
        )
        preview_rows = _load_assigned_preview_rows(
            sync_db,
            team_ids,
            assignee_condition,
            [row.config_id for row in assigned_runs],
        )
        previews_by_run: dict[tuple[int, int], list[dict[str, Any]]] = {}
        for row in preview_rows:
            previews_by_run.setdefault((row.team_id, row.config_id), []).append(
                _assigned_preview_projection(row)
            )
        can_write = _is_write_capable(current_user)
        sections["assigned"]["items"] = [
            _assigned_run_projection(
                row,
                can_write,
                previews_by_run.get((row.team_id, row.config_id), []),
            )
            for row in assigned_runs
        ]
    except Exception:  # noqa: BLE001 - preserve independent section availability
        logger.warning("Dashboard assigned section unavailable", exc_info=True)
        assigned_rows = []
        sections["assigned"] = {"state": "unavailable", "items": []}

    try:
        history_payload = _load_history_sections(sync_db, current_user, team_ids, assigned_rows)
        sections["activity"] = history_payload["activity"]
        sections["outcomes"] = history_payload["outcomes"]
        if _is_write_capable(current_user):
            sections["resume"] = _build_resume_section(
                assigned_rows,
                history_payload["latest_transition"],
                state=history_payload["state"],
            )
    except Exception:  # noqa: BLE001 - old enum data must not hide assigned work
        logger.warning("Dashboard history sections unavailable", exc_info=True)
        sections["activity"] = {"state": "unavailable", "items": []}
        sections["outcomes"] = {
            "state": "unavailable",
            "window_days": 7,
            "total": 0,
            "counts": {},
            "items": [],
        }
        sections["resume"] = {"state": "unavailable", "items": []}
    return sections


def _load_visible_active_teams(sync_db: Session, current_user: User) -> list[dict[str, Any]]:
    rows = sync_db.execute(
        select(Team.id, Team.name)
        .where(cast(Team.status, String) == _ACTIVE_TEAM)
        .order_by(func.lower(Team.name).asc(), Team.id.asc())
    ).all()
    return [{"id": row.id, "name": row.name or "", "can_write": _is_write_capable(current_user)} for row in rows]


def _assigned_identity_condition(sync_db: Session, current_user: User) -> Any:
    assignee_condition = TestRunItem.assignee_user_id == current_user.id
    legacy_condition = _legacy_identity_condition(sync_db, current_user)
    if legacy_condition is not None:
        assignee_condition = or_(
            assignee_condition,
            and_(TestRunItem.assignee_user_id.is_(None), legacy_condition),
        )
    return assignee_condition


def _load_assigned_rows(
    sync_db: Session,
    current_user: User,
    team_ids: list[int],
    *,
    assignee_condition: Any | None = None,
) -> list[Any]:
    if assignee_condition is None:
        assignee_condition = _assigned_identity_condition(sync_db, current_user)

    rows = sync_db.execute(
        select(
            TestRunItem.id.label("item_id"),
            TestRunItem.team_id,
            Team.name.label("team_name"),
            TestRunItem.config_id,
            TestRunConfig.name.label("run_name"),
            cast(TestRunConfig.status, String).label("run_status"),
        )
        .select_from(TestRunItem)
        .join(TestRunConfig, TestRunConfig.id == TestRunItem.config_id)
        .join(Team, Team.id == TestRunItem.team_id)
        .where(
            TestRunItem.team_id.in_(team_ids),
            cast(Team.status, String) == _ACTIVE_TEAM,
            cast(TestRunConfig.status, String).in_([_ACTIVE_RUN, _DRAFT_RUN]),
            assignee_condition,
        )
        .order_by(TestRunItem.updated_at.desc(), TestRunItem.id.desc())
        .limit(_MAX_ASSIGNED)
    ).all()
    return list(rows)


def _load_assigned_run_groups(
    sync_db: Session,
    team_ids: list[int],
    assignee_condition: Any,
) -> list[Any]:
    run_status = cast(TestRunConfig.status, String)
    item_count = func.count(TestRunItem.id)
    latest_item_at = func.max(TestRunItem.updated_at)
    rows = sync_db.execute(
        select(
            TestRunItem.team_id,
            Team.name.label("team_name"),
            TestRunItem.config_id,
            TestRunConfig.name.label("run_name"),
            run_status.label("run_status"),
            item_count.label("item_count"),
            latest_item_at.label("latest_item_at"),
        )
        .select_from(TestRunItem)
        .join(TestRunConfig, TestRunConfig.id == TestRunItem.config_id)
        .join(Team, Team.id == TestRunItem.team_id)
        .where(
            TestRunItem.team_id.in_(team_ids),
            cast(Team.status, String) == _ACTIVE_TEAM,
            run_status.in_([_ACTIVE_RUN, _DRAFT_RUN]),
            assignee_condition,
        )
        .group_by(
            TestRunItem.team_id,
            Team.name,
            TestRunItem.config_id,
            TestRunConfig.name,
            run_status,
        )
        .order_by(latest_item_at.desc(), TestRunItem.config_id.desc())
        .limit(_MAX_ASSIGNED_RUNS)
    ).all()
    return list(rows)


def _load_assigned_preview_rows(
    sync_db: Session,
    team_ids: list[int],
    assignee_condition: Any,
    config_ids: list[int],
) -> list[Any]:
    if not config_ids:
        return []

    preview_rank = func.row_number().over(
        partition_by=(TestRunItem.team_id, TestRunItem.config_id),
        order_by=(TestRunItem.updated_at.desc(), TestRunItem.id.desc()),
    ).label("preview_rank")
    ranked = (
        select(
            TestRunItem.id.label("item_id"),
            TestRunItem.team_id,
            TestRunItem.config_id,
            TestRunItem.test_case_number,
            TestCaseLocal.title.label("test_case_title"),
            cast(TestRunItem.test_result, String).label("test_result"),
            preview_rank,
        )
        .select_from(TestRunItem)
        .join(TestRunConfig, TestRunConfig.id == TestRunItem.config_id)
        .join(Team, Team.id == TestRunItem.team_id)
        .outerjoin(
            TestCaseLocal,
            and_(
                TestCaseLocal.team_id == TestRunItem.team_id,
                TestCaseLocal.test_case_number == TestRunItem.test_case_number,
            ),
        )
        .where(
            TestRunItem.team_id.in_(team_ids),
            TestRunItem.config_id.in_(config_ids),
            cast(Team.status, String) == _ACTIVE_TEAM,
            cast(TestRunConfig.status, String).in_([_ACTIVE_RUN, _DRAFT_RUN]),
            assignee_condition,
        )
        .subquery()
    )
    rows = sync_db.execute(
        select(
            ranked.c.item_id,
            ranked.c.team_id,
            ranked.c.config_id,
            ranked.c.test_case_number,
            ranked.c.test_case_title,
            ranked.c.test_result,
        )
        .where(ranked.c.preview_rank <= _MAX_ASSIGNED_PREVIEW)
        .order_by(ranked.c.config_id.asc(), ranked.c.preview_rank.asc())
    ).all()
    return list(rows)


def _legacy_identity_condition(sync_db: Session, current_user: User):
    """Return a collision-safe fallback predicate for an unlinked legacy item.

    A legacy snapshot may contain either a Lark ID or an email.  It is only a
    safe identity if the value uniquely resolves to the bearer, and if a
    second machine identity on the same Item does not contradict that bearer.
    """

    lark_user_id = _trim_to_none(getattr(current_user, "lark_user_id", None))
    email = _normalized_email(getattr(current_user, "email", None))
    lark_is_unique = bool(
        lark_user_id
        and _identity_uniquely_resolves_to_current_user(
            sync_db,
            current_user.id,
            func.trim(User.lark_user_id) == lark_user_id,
        )
    )
    email_is_unique = bool(
        email
        and _identity_uniquely_resolves_to_current_user(
            sync_db,
            current_user.id,
            func.lower(func.trim(User.email)) == email,
        )
    )

    blank_lark = _sql_blank(TestRunItem.assignee_id)
    blank_email = _sql_blank(TestRunItem.assignee_email)
    candidates = []
    if lark_is_unique:
        lark_match = [func.trim(TestRunItem.assignee_id) == lark_user_id]
        if email:
            lark_match.append(
                or_(
                    blank_email,
                    func.lower(func.trim(TestRunItem.assignee_email)) == email,
                )
                if email_is_unique
                else blank_email
            )
        candidates.append(and_(*lark_match))
    if email_is_unique:
        email_match = [func.lower(func.trim(TestRunItem.assignee_email)) == email]
        if lark_user_id:
            email_match.append(
                or_(blank_lark, func.trim(TestRunItem.assignee_id) == lark_user_id)
                if lark_is_unique
                else blank_lark
            )
        candidates.append(and_(*email_match))
    return or_(*candidates) if candidates else None


def _identity_uniquely_resolves_to_current_user(
    sync_db: Session,
    current_user_id: int,
    predicate: Any,
) -> bool:
    candidate_ids = sync_db.execute(
        select(User.id).where(predicate).order_by(User.id.asc()).limit(2)
    ).scalars().all()
    return candidate_ids == [current_user_id]


def _sql_blank(column: Any):
    return or_(column.is_(None), func.trim(column) == "")


def _resume_run_projection(row: Any, transition: Any) -> dict[str, Any]:
    return {
        "kind": "test_run",
        "team": {"id": row.team_id, "name": row.team_name or ""},
        "run": {"id": row.config_id, "name": row.run_name or "", "status": row.run_status},
        "last_activity_at": transition.changed_at,
        "link": _run_link(row.team_id, row.config_id),
    }


def _build_audit_resume_items(
    rows: list[Any],
    team_names: dict[int, str],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen_resources: set[tuple[str, int, str]] = set()
    for row in rows:
        resource_type = _safe_allowlisted_code(
            getattr(row, "resource_type", None),
            _AUDIT_RESUME_RESOURCE_CODES,
        )
        team_id = getattr(row, "team_id", None)
        if resource_type is None or not isinstance(team_id, int) or team_id not in team_names:
            continue
        action = _safe_allowlisted_code(
            getattr(row, "action_type", None),
            _AUDIT_ACTION_CODES,
        )
        resource_id = _trim_to_none(getattr(row, "resource_id", None)) or ""
        kind = _audit_resume_kind(resource_type)
        is_test_case_batch = kind == "test_case" and _is_test_case_batch_resource_id(
            resource_id
        )
        map_id = _safe_user_story_map_id(resource_id) if kind == "user_story_map" else None
        if kind == "automation_hub":
            identity_resource = "hub"
        elif is_test_case_batch:
            identity_resource = "management"
        elif kind == "test_case" and _safe_test_case_resource_id(resource_id):
            identity_resource = resource_id
        elif kind == "user_story_map" and map_id is not None:
            identity_resource = map_id
        else:
            continue
        identity = (kind, team_id, identity_resource)

        is_tombstone = False
        if kind == "automation_hub":
            if action not in {
                ActionType.CREATE.value,
                ActionType.UPDATE.value,
                ActionType.DELETE.value,
            }:
                continue
        elif kind == "test_case":
            if is_test_case_batch:
                if action not in {
                    ActionType.CREATE.value,
                    ActionType.UPDATE.value,
                    ActionType.DELETE.value,
                }:
                    continue
            elif action == ActionType.DELETE.value:
                is_tombstone = True
            elif action not in {ActionType.CREATE.value, ActionType.UPDATE.value}:
                continue
        elif kind == "user_story_map":
            is_map_level_event = ":" not in resource_id
            if is_map_level_event and action == ActionType.DELETE.value:
                is_tombstone = True
            elif action not in {
                ActionType.CREATE.value,
                ActionType.UPDATE.value,
                ActionType.DELETE.value,
            }:
                continue

        if identity in seen_resources:
            continue
        seen_resources.add(identity)
        if is_tombstone:
            continue

        if kind == "automation_hub":
            link = f"/automation-hub?team_id={team_id}"
            resource = {"id": "automation_hub"}
        elif kind == "test_case":
            if is_test_case_batch:
                link = f"/test-case-management?team_id={team_id}"
                resource = {"id": ""}
            else:
                link = (
                    f"/test-case-management?team_id={team_id}"
                    f"&tc={quote(resource_id, safe='')}&mode=edit"
                )
                resource = {"id": resource_id}
        elif kind == "user_story_map":
            link = f"/user-story-map/{team_id}/{map_id}"
            resource = {"id": map_id}
        else:
            continue

        items.append(
            {
                "kind": kind,
                "team": {"id": team_id, "name": team_names[team_id]},
                "resource": resource,
                "last_activity_at": getattr(row, "timestamp", None),
                "link": link,
            }
        )
        if len(items) >= _MAX_RESUME:
            break
    return items


def _audit_resume_kind(resource_type: str) -> str:
    if resource_type == ResourceType.TEST_CASE.value:
        return "test_case"
    if resource_type == ResourceType.USER_STORY_MAP.value:
        return "user_story_map"
    if resource_type in _AUTOMATION_AUDIT_RESOURCE_CODES:
        return "automation_hub"
    return ""


def _safe_test_case_resource_id(value: str) -> bool:
    return bool(
        value
        and len(value) <= 100
        and value[0].isalnum()
        and all(character.isalnum() or character in {".", "_", "-"} for character in value)
    )


def _is_test_case_batch_resource_id(value: str) -> bool:
    return value.startswith(("batch_", "bulk_"))


def _safe_user_story_map_id(value: str) -> Optional[str]:
    map_id = value.split(":", 1)[0]
    if not map_id.isdigit() or int(map_id) <= 0:
        return None
    return str(int(map_id))


def _merge_resume_sections(
    main_section: dict[str, Any] | None,
    audit_items: list[dict[str, Any]],
    audit_state: str,
) -> dict[str, Any]:
    main = main_section or {"state": "unavailable", "items": []}
    items = [*main.get("items", []), *audit_items]
    items.sort(
        key=lambda item: (
            item.get("last_activity_at") or datetime.min,
            _resume_identity(item),
        ),
        reverse=True,
    )
    main_state = main.get("state", "unavailable")
    if main_state == "ready" and audit_state == "ready":
        state = "ready"
    elif main_state == "unavailable" and audit_state == "unavailable":
        state = "unavailable"
    else:
        state = "partial"
    return {"state": state, "items": items[:_MAX_RESUME]}


def _resume_identity(item: dict[str, Any]) -> str:
    team_id = item.get("team", {}).get("id", "")
    kind = item.get("kind", "")
    if kind == "test_run":
        resource_id = item.get("run", {}).get("id", "")
    else:
        resource_id = item.get("resource", {}).get("id", "")
    return f"{kind}:{team_id}:{resource_id}"


def _assigned_preview_projection(row: Any) -> dict[str, Any]:
    return {
        "test_case": {
            "number": row.test_case_number,
            "title": row.test_case_title or "",
        },
        "test_result": row.test_result,
        "item_link": _run_link(row.team_id, row.config_id, row.test_case_number),
    }


def _assigned_run_projection(
    row: Any,
    can_write: bool,
    preview_items: list[dict[str, Any]],
) -> dict[str, Any]:
    is_active = row.run_status == _ACTIVE_RUN
    return {
        "team": {"id": row.team_id, "name": row.team_name or ""},
        "run": {"id": row.config_id, "name": row.run_name or "", "status": row.run_status},
        "item_count": int(row.item_count or 0),
        "preview_items": preview_items,
        "action_mode": "execute" if can_write and is_active else "view",
        "run_link": _run_link(row.team_id, row.config_id),
    }


def _load_history_sections(
    sync_db: Session,
    current_user: User,
    team_ids: list[int],
    assigned_rows: list[Any],
) -> dict[str, Any]:
    cutoff = datetime.utcnow() - timedelta(days=7)
    rows = sync_db.execute(
        select(
            TestRunItemResultHistory.id,
            TestRunItemResultHistory.item_id,
            TestRunItemResultHistory.team_id,
            TestRunItemResultHistory.config_id,
            Team.name.label("team_name"),
            TestRunConfig.name.label("run_name"),
            TestRunItem.test_case_number,
            TestCaseLocal.title.label("test_case_title"),
            cast(TestRunItemResultHistory.prev_result, String).label("prev_result"),
            cast(TestRunItemResultHistory.new_result, String).label("new_result"),
            TestRunItemResultHistory.prev_executed_at,
            TestRunItemResultHistory.new_executed_at,
            TestRunItemResultHistory.change_source,
            TestRunItemResultHistory.changed_at,
        )
        .select_from(TestRunItemResultHistory)
        .join(TestRunItem, TestRunItem.id == TestRunItemResultHistory.item_id)
        .join(Team, Team.id == TestRunItemResultHistory.team_id)
        .join(TestRunConfig, TestRunConfig.id == TestRunItemResultHistory.config_id)
        .outerjoin(
            TestCaseLocal,
            and_(
                TestCaseLocal.team_id == TestRunItem.team_id,
                TestCaseLocal.test_case_number == TestRunItem.test_case_number,
            ),
        )
        .where(
            TestRunItemResultHistory.team_id.in_(team_ids),
            TestRunItemResultHistory.changed_by_id == str(current_user.id),
        )
        .order_by(TestRunItemResultHistory.changed_at.desc(), TestRunItemResultHistory.id.desc())
        .limit(_MAX_HISTORY + 1)
    ).all()

    truncated = len(rows) > _MAX_HISTORY
    if truncated:
        rows = rows[:_MAX_HISTORY]
    unknown_seen = False
    unknown_item_ids: set[int] = set()
    actual_transitions: list[Any] = []
    activity_items: list[dict[str, Any]] = []
    for row in rows:
        if _has_unknown_result(row.prev_result, row.new_result):
            unknown_seen = True
            unknown_item_ids.add(row.item_id)
            continue
        if row.item_id in unknown_item_ids:
            continue
        actual = _is_execution_transition(row)
        if actual:
            actual_transitions.append(row)
        if len(activity_items) < _MAX_ACTIVITY:
            activity_items.append(
                {
                    "item_id": row.item_id,
                    "team": {"id": row.team_id, "name": row.team_name or ""},
                    "run": {"id": row.config_id, "name": row.run_name or ""},
                    "test_case": {
                        "number": row.test_case_number,
                        "title": row.test_case_title or "",
                    },
                    "kind": "execution" if actual else "comment",
                    "test_result": row.new_result if actual else None,
                    "timestamp": row.changed_at,
                    "run_link": _run_link(
                        row.team_id,
                        row.config_id,
                        row.test_case_number,
                    ),
                }
            )

    latest_transition: dict[int, Any] = {}
    for row in actual_transitions:
        latest_transition.setdefault(row.item_id, row)

    outcome_rows = [row for row in actual_transitions if row.changed_at and row.changed_at >= cutoff]
    latest_outcomes: dict[int, Any] = {}
    for row in outcome_rows:
        latest_outcomes.setdefault(row.item_id, row)
    counts = Counter(
        row.new_result for row in latest_outcomes.values() if row.new_result in _TERMINAL_OUTCOME_RESULTS
    )

    assigned_ids = {row.item_id for row in assigned_rows}
    latest_transition = {item_id: row for item_id, row in latest_transition.items() if item_id in assigned_ids}
    state = "partial" if unknown_seen or truncated else "ready"
    return {
        "activity": {"state": state, "items": activity_items},
        "outcomes": {
            "state": state,
            "window_days": 7,
            "total": sum(counts.values()),
            "counts": dict(sorted(counts.items())),
            "items": [],
        },
        "latest_transition": latest_transition,
        "state": state,
    }


def _build_resume_section(
    assigned_rows: list[Any],
    transitions: dict[int, Any],
    *,
    state: str,
) -> dict[str, Any]:
    candidates: list[tuple[Any, Any]] = []
    for row in assigned_rows:
        transition = transitions.get(row.item_id)
        if row.run_status == _ACTIVE_RUN and transition is not None:
            candidates.append((row, transition))
    candidates.sort(
        key=lambda pair: (pair[1].changed_at or datetime.min, pair[0].item_id), reverse=True
    )
    items: list[dict[str, Any]] = []
    seen_runs: set[tuple[int, int]] = set()
    for row, transition in candidates:
        run_key = (row.team_id, row.config_id)
        if run_key in seen_runs:
            continue
        seen_runs.add(run_key)
        items.append(_resume_run_projection(row, transition))
        if len(items) >= _MAX_RESUME:
            break
    return {"state": state, "items": items}


async def _read_automation_hub_entry_enabled(session: AsyncSession) -> bool:
    return await get_bool(session, AUTOMATION_HUB_ENTRY_ENABLED_KEY, True)


def _build_system_main(sync_db: Session) -> dict[str, Any]:
    sections: dict[str, Any] = {}
    try:
        sections["overview"] = {
            "state": "ready",
            "active_teams": _count(sync_db, Team.id, cast(Team.status, String) == _ACTIVE_TEAM),
            "active_users": _count(sync_db, User.id, User.is_active.is_(True)),
            "active_runs": _count(sync_db, TestRunConfig.id, cast(TestRunConfig.status, String) == _ACTIVE_RUN),
        }
    except Exception:  # noqa: BLE001
        logger.warning("Dashboard system overview unavailable", exc_info=True)
        sections["overview"] = {"state": "unavailable"}

    try:
        services = sync_db.execute(
            select(
                ScheduledService.service_key,
                ScheduledService.enabled,
                ScheduledService.is_running,
                ScheduledService.last_run_started_at,
                ScheduledService.last_run_finished_at,
                ScheduledService.last_run_status,
            )
            .order_by(ScheduledService.service_key.asc())
            .limit(50)
        ).all()
        service_items = [
            {
                "service_key": _safe_identifier(row.service_key),
                "enabled": bool(row.enabled),
                "running": bool(row.is_running),
                "last_run_at": row.last_run_finished_at or row.last_run_started_at,
                "outcome": _safe_system_outcome(row.last_run_status),
            }
            for row in services
        ]
        sections["scheduled_services"] = {"state": "ready", "items": service_items}
    except Exception:  # noqa: BLE001
        logger.warning("Dashboard scheduled services unavailable", exc_info=True)
        sections["scheduled_services"] = {"state": "unavailable", "items": []}

    try:
        slots = {
            row.provider_slot
            for row in sync_db.execute(
                select(cast(SystemAutomationProvider.provider_slot, String).label("provider_slot"))
                .where(SystemAutomationProvider.is_active.is_(True))
            )
        }
        sections["providers"] = {
            "state": "ready",
            "ci_configured": "ci" in slots,
            "result_configured": "result" in slots,
        }
    except Exception:  # noqa: BLE001
        logger.warning("Dashboard provider summary unavailable", exc_info=True)
        sections["providers"] = {"state": "unavailable"}

    try:
        attention_services = [
            item
            for item in sections.get("scheduled_services", {}).get("items", [])
            if item["outcome"] in {"failed", "error"}
        ]
        latest = max(
            (item["last_run_at"] for item in attention_services if item["last_run_at"] is not None),
            default=None,
        )
        sections["attention"] = {
            "state": "ready",
            "count": len(attention_services),
            "latest_at": latest,
        }
    except Exception:  # noqa: BLE001
        sections["attention"] = {"state": "unavailable"}
    return sections


def _count(sync_db: Session, column: Any, *conditions: Any) -> int:
    return int(sync_db.execute(select(func.count(column)).where(*conditions)).scalar_one() or 0)


def _current_user_projection(user: User) -> DashboardCurrentUser:
    return DashboardCurrentUser(id=user.id, display_name=user.username)


def _is_write_capable(user: User) -> bool:
    return _role_value(user) in {UserRole.USER.value, UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value}


def _role_value(user: User) -> str:
    role = user.role.value if hasattr(user.role, "value") else str(user.role or "")
    return role.strip().lower()


def _is_execution_transition(row: Any) -> bool:
    return _different(row.prev_result, row.new_result) or _different(
        row.prev_executed_at, row.new_executed_at
    )


def _different(previous: object, current: object) -> bool:
    return previous != current


def _has_unknown_result(*values: object) -> bool:
    return any(value is not None and value not in _KNOWN_RESULTS for value in values)


def _run_link(team_id: int, config_id: int, test_case_number: str | None = None) -> str:
    run_link = f"/test-run-execution?team_id={team_id}&config_id={config_id}"
    if test_case_number is None:
        return run_link
    return f"{run_link}&tc={quote(test_case_number or '', safe='')}"


def _safe_allowlisted_code(value: object, allowlist: frozenset[str]) -> Optional[str]:
    text = _trim_to_none(value)
    return text if text in allowlist else None


def _safe_identifier(value: object) -> str:
    return (_trim_to_none(value) or "")[:128]


def _safe_system_outcome(value: object) -> str:
    normalized = (_trim_to_none(value) or "unknown").lower()
    normalized = _SYSTEM_OUTCOME_ALIASES.get(normalized, normalized)
    return normalized if normalized in _SYSTEM_OUTCOME_CODES else "unknown"


def _trim_to_none(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalized_email(value: object) -> Optional[str]:
    text = _trim_to_none(value)
    return text.lower() if text else None
