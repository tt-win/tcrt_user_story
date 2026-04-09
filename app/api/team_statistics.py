"""
團隊數據統計 API

提供全面的團隊統計分析，包括測試案例、測試執行、審計日誌等數據分析。
僅限 Admin 及以上角色存取。
"""

from fastapi import APIRouter, Query, HTTPException, Depends
from fastapi.responses import JSONResponse
from datetime import datetime, timezone, timedelta, date
from typing import List, Dict, Any, Optional
import logging
import json
import math
from collections import Counter, defaultdict
from sqlalchemy import case, func, select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.db_access.audit import AuditAccessBoundary, get_audit_access_boundary
from app.db_access.main import MainAccessBoundary, get_main_access_boundary
from app.models.database_models import (
    LarkUser,
    LarkDepartment,
    TestCaseLocal,
    TestRunConfig,
    TestRunItem,
    TestRunItemResultHistory,
    Team,
    User,
)
from app.models.lark_types import TestResultStatus
from app.models.team import TeamStatus
from app.audit.database import AuditLogTable
from app.audit.models import ActionType, ResourceType, AuditSeverity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/team_statistics", tags=["team_statistics"])

MAX_STAT_RANGE_DAYS = 90


def _to_non_negative_int(value: Any) -> int:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return number if number >= 0 else 0


def _parse_team_ids(raw_team_ids: Optional[str]) -> List[int]:
    if not raw_team_ids:
        return []
    values: List[int] = []
    seen = set()
    for part in str(raw_team_ids).split(","):
        text_value = part.strip()
        if not text_value:
            continue
        try:
            team_id = int(text_value)
        except ValueError:
            continue
        if team_id <= 0 or team_id in seen:
            continue
        values.append(team_id)
        seen.add(team_id)
    return values


def _to_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _p95(values: List[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return int(ordered[index])











def _resolve_date_range(
    days: int, start_date: Optional[date], end_date: Optional[date]
) -> tuple[str, str, datetime, datetime, int]:
    """解析日期範圍，支援 days 或自訂日期區間。"""
    if start_date or end_date:
        if not start_date or not end_date:
            raise HTTPException(status_code=400, detail={"error": "請同時提供開始與結束日期"})
        if end_date < start_date:
            raise HTTPException(status_code=400, detail={"error": "結束日期不可早於開始日期"})
        total_days = (end_date - start_date).days + 1
        if total_days < 1:
            raise HTTPException(status_code=400, detail={"error": "日期區間至少需要 1 天"})
        if total_days > MAX_STAT_RANGE_DAYS:
            raise HTTPException(status_code=400, detail={"error": f"日期區間不可超過 {MAX_STAT_RANGE_DAYS} 天"})
        start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
        end_dt = datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc)
        return start_date.isoformat(), end_date.isoformat(), start_dt, end_dt, total_days

    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=days)
    return start_dt.date().isoformat(), end_dt.date().isoformat(), start_dt, end_dt, days


def _extract_assignee_names(payload: Any) -> List[str]:
    """從 assignee_json 負載中提取姓名列表"""
    names: List[str] = []

    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            # 以逗號分隔的字串簡單拆解
            for part in payload.split(","):
                part = part.strip()
                if part:
                    names.append(part)
            return names

    if isinstance(payload, dict):
        for key in ("name", "display_name", "full_name", "username", "label"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                names.append(value.strip())
            elif isinstance(value, list):
                names.extend(_extract_assignee_names(value))
        # 一些結構會包含在 fields / options 中
        for nested_key in ("options", "options_value", "value", "values"):
            if nested_key in payload:
                names.extend(_extract_assignee_names(payload[nested_key]))
        return names

    if isinstance(payload, list):
        for item in payload:
            names.extend(_extract_assignee_names(item))

    return names


def _format_department_name(dept_id: Optional[str], path: Optional[str]) -> str:
    """將部門 ID 與路徑轉換為可閱讀名稱"""
    if not dept_id:
        return "未命名部門"

    if path:
        parts = [segment for segment in path.split("/") if segment and segment != "0"]
        if parts:
            readable_parts = [
                part if not part.startswith("od-") or len(part) <= 8 else f"{part[:3]}…{part[-4:]}"
                for part in parts[-3:]
            ]
            return " / ".join(readable_parts)

    if dept_id.startswith("od-") and len(dept_id) > 8:
        return f"{dept_id[:3]}…{dept_id[-4:]}"

    return dept_id


def _safe_json_loads(raw: Any) -> Optional[Dict[str, Any]]:
    """將字串安全轉為 JSON，失敗時回傳 None；如果已是 dict 則直接回傳"""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return None


def _enum_value(value: Any) -> str:
    """取得 Enum 的 value，若非 Enum 則轉為字串"""
    if hasattr(value, "value"):
        return value.value
    return str(value)


def _enum_storage_key(value: Any) -> str:
    """保留資料庫 enum 儲存鍵格式，避免 reporting 契約漂移。"""
    if value is None:
        return "unknown"
    if hasattr(value, "name"):
        return str(value.name)
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _day_to_label(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _build_date_labels(start_date_obj: date, end_date_obj: date) -> List[str]:
    date_cursor = start_date_obj
    labels: List[str] = []
    while date_cursor <= end_date_obj:
        labels.append(date_cursor.isoformat())
        date_cursor += timedelta(days=1)
    return labels


def _get_action_weight(resource_type: Any, details_raw: Any) -> int:
    """
    取得行為的權重（受影響筆數）。
    - Bulk/Batch 相關會使用 details 裡的 count / items 長度作為權重
    - USM 文字模式匯出（export_text）不列入統計，回傳 0
    """
    details = _safe_json_loads(details_raw)

    # 排除 USM 文字匯出
    if details:
        action = details.get("action") or details.get("operation")
        resource_value = _enum_value(resource_type)
        if action == "export_text" and resource_value == ResourceType.USER_STORY_MAP.value:
            return 0

    weight = 1
    if not details:
        return weight

    candidate_counts: List[int] = []
    for key in (
        "created_count",
        "updated_count",
        "success_count",
        "nodes_count",
        "count",
        "items_count",
        "total_count",
    ):
        val = details.get(key)
        if isinstance(val, int):
            candidate_counts.append(val)

    for list_key in ("created_items", "updated_items", "deleted_items"):
        val = details.get(list_key)
        if isinstance(val, list):
            candidate_counts.append(len(val))

    if candidate_counts:
        weight = max(1, max(candidate_counts))

    return weight


@router.get("/overview", include_in_schema=False)
async def get_overview(
    current_user: User = Depends(require_admin()),
    days: int = Query(30, ge=1, le=MAX_STAT_RANGE_DAYS, description="統計天數"),
    start_date: Optional[date] = Query(None, description="開始日期 (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="結束日期 (YYYY-MM-DD)"),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
    audit_boundary: AuditAccessBoundary = Depends(get_audit_access_boundary),
):
    """
    總覽儀表板 - 顯示關鍵指標

    Returns:
        - team_count: 團隊總數
        - user_count: 使用者總數（活躍）
        - test_case_total: 測試案例總數
        - test_run_total: 測試執行總數（Test Run Configs）
        - team_test_cases: 各團隊的 Test Case 總數列表
        - team_test_runs: 各團隊的 Test Run 總數列表
        - recent_activity: 最近活動摘要（前10筆）
    """
    try:
        start_date, end_date, _, _, range_days = _resolve_date_range(days, start_date, end_date)

        async def _load_main(session: AsyncSession) -> Dict[str, Any]:
            team_count_result = await session.execute(
                select(func.count(Team.id)).where(Team.status == TeamStatus.ACTIVE)
            )
            team_count = team_count_result.scalar() or 0

            user_count_result = await session.execute(select(func.count(User.id)).where(User.is_active == True))
            user_count = user_count_result.scalar() or 0

            test_case_count_result = await session.execute(select(func.count(TestCaseLocal.id)))
            test_case_total = test_case_count_result.scalar() or 0

            test_run_result = await session.execute(select(func.count(TestRunConfig.id)))
            test_run_total = test_run_result.scalar() or 0

            team_test_case_result = await session.execute(
                select(TestCaseLocal.team_id, Team.name, func.count(TestCaseLocal.id).label("test_case_count"))
                .join(Team, TestCaseLocal.team_id == Team.id)
                .where(Team.status == TeamStatus.ACTIVE)
                .group_by(TestCaseLocal.team_id, Team.name)
                .order_by(desc("test_case_count"))
            )
            team_test_cases = [
                {"team_id": row[0], "team_name": row[1], "test_case_count": row[2]}
                for row in team_test_case_result.all()
            ]

            team_test_run_result = await session.execute(
                select(TestRunConfig.team_id, Team.name, func.count(TestRunConfig.id).label("test_run_count"))
                .join(Team, TestRunConfig.team_id == Team.id)
                .where(Team.status == TeamStatus.ACTIVE)
                .group_by(TestRunConfig.team_id, Team.name)
                .order_by(desc("test_run_count"))
            )
            team_test_runs = [
                {"team_id": row[0], "team_name": row[1], "test_run_count": row[2]} for row in team_test_run_result.all()
            ]

            return {
                "team_count": team_count,
                "user_count": user_count,
                "test_case_total": test_case_total,
                "test_run_total": test_run_total,
                "team_test_cases": team_test_cases,
                "team_test_runs": team_test_runs,
            }

        async def _load_recent_activity(audit_session: AsyncSession) -> List[Dict[str, Any]]:
            recent_logs = await audit_session.execute(
                select(AuditLogTable).order_by(desc(AuditLogTable.timestamp)).limit(10)
            )
            recent_activity = [
                {
                    "id": log.id,
                    "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                    "username": log.username,
                    "action_type": log.action_type.value if log.action_type else None,
                    "resource_type": log.resource_type.value if log.resource_type else None,
                    "action_brief": log.action_brief,
                    "severity": log.severity.value if log.severity else "info",
                }
                for log in recent_logs.scalars()
            ]
            return recent_activity

        main_payload = await main_boundary.run_read(_load_main)
        recent_activity = await audit_boundary.run_read(_load_recent_activity)

        return JSONResponse(
            {
                **main_payload,
                "recent_activity": recent_activity,
                "date_range": {"start": start_date, "end": end_date, "days": range_days},
            }
        )

    except Exception as e:
        logger.error(f"獲取總覽統計失敗: {e}")
        raise HTTPException(status_code=500, detail={"error": "無法載入總覽統計"})


@router.get("/team_activity", include_in_schema=False)
async def get_team_activity(
    current_user: User = Depends(require_admin()),
    days: int = Query(30, ge=1, le=MAX_STAT_RANGE_DAYS, description="統計天數"),
    start_date: Optional[date] = Query(None, description="開始日期 (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="結束日期 (YYYY-MM-DD)"),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
    audit_boundary: AuditAccessBoundary = Depends(get_audit_access_boundary),
):
    """
    團隊活動分析 - 基於審計日誌

    Returns:
        - by_team: 各團隊操作統計 {team_id: {team_name, total, by_action}}
        - top_active_teams: 最活躍團隊列表（前10）
    """
    try:
        start_date, end_date, start_dt, end_dt, range_days = _resolve_date_range(days, start_date, end_date)

        async def _load_teams(session: AsyncSession) -> Dict[int, str]:
            teams_result = await session.execute(select(Team.id, Team.name).where(Team.status == TeamStatus.ACTIVE))
            return {row[0]: row[1] for row in teams_result}

        async def _load_activity(audit_session: AsyncSession) -> List[tuple[Any, Any, Any, Any]]:
            activity_result = await audit_session.execute(
                select(
                    AuditLogTable.team_id, AuditLogTable.action_type, AuditLogTable.resource_type, AuditLogTable.details
                ).where(
                    AuditLogTable.timestamp >= start_dt, AuditLogTable.timestamp <= end_dt, AuditLogTable.team_id > 0
                )
            )
            return activity_result.all()

        teams_dict = await main_boundary.run_read(_load_teams)
        activity_rows = await audit_boundary.run_read(_load_activity)

        # 整理數據 - 先為所有團隊初始化 0
        by_team = {}
        for team_id, team_name in teams_dict.items():
            by_team[team_id] = {"team_id": team_id, "team_name": team_name, "total": 0, "by_action": {}}

        # 填入審計日誌數據
        for team_id, action_type, resource_type, details in activity_rows:
            weight = _get_action_weight(resource_type, details)
            if weight <= 0:
                continue
            if team_id not in by_team:
                # 理論上不應該發生（除非有已刪除團隊的日誌），但也處理一下
                by_team[team_id] = {
                    "team_id": team_id,
                    "team_name": teams_dict.get(team_id, f"Team {team_id}"),
                    "total": 0,
                    "by_action": {},
                }
            by_team[team_id]["total"] += weight
            action_key = _enum_value(action_type)
            by_team[team_id]["by_action"][action_key] = by_team[team_id]["by_action"].get(action_key, 0) + weight

        # 排序取得最活躍團隊
        all_teams_activity = sorted(by_team.values(), key=lambda x: x["total"], reverse=True)
        top_active_teams = all_teams_activity[:10]

        return JSONResponse(
            {
                "by_team": by_team,
                "top_active_teams": top_active_teams,
                "all_teams_activity": all_teams_activity,
                "date_range": {"start": start_date, "end": end_date, "days": range_days},
            }
        )

    except Exception as e:
        logger.error(f"獲取團隊活動統計失敗: {e}")
        raise HTTPException(status_code=500, detail={"error": "無法載入團隊活動統計"})


@router.get("/test_case_trends", include_in_schema=False)
async def get_test_case_trends(
    current_user: User = Depends(require_admin()),
    days: int = Query(30, ge=1, le=MAX_STAT_RANGE_DAYS, description="統計天數"),
    start_date: Optional[date] = Query(None, description="開始日期 (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="結束日期 (YYYY-MM-DD)"),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    """
    測試案例趨勢分析

    Returns:
        - dates: 日期座標列表
        - per_team_daily: 團隊別每日新增/更新統計
        - overall: 全域彙總（每日新增/更新及總量）
    """
    try:
        start_date_str, end_date_str, _, _, range_days = _resolve_date_range(days, start_date, end_date)
        start_date_obj = date.fromisoformat(start_date_str)
        end_date_obj = date.fromisoformat(end_date_str)

        async def _load_trends(session: AsyncSession) -> Dict[str, Any]:
            created_day = func.date(TestCaseLocal.created_at)
            updated_day = func.date(TestCaseLocal.updated_at)
            created_rows_result = await session.execute(
                select(
                    TestCaseLocal.team_id,
                    created_day.label("day"),
                    func.count(TestCaseLocal.id).label("cnt"),
                )
                .where(created_day.between(start_date_str, end_date_str))
                .group_by(TestCaseLocal.team_id, created_day)
                .order_by(created_day.asc())
            )

            updated_rows_result = await session.execute(
                select(
                    TestCaseLocal.team_id,
                    updated_day.label("day"),
                    func.count(TestCaseLocal.id).label("cnt"),
                )
                .where(
                    TestCaseLocal.updated_at.is_not(None),
                    TestCaseLocal.updated_at > TestCaseLocal.created_at,
                    updated_day.between(start_date_str, end_date_str),
                )
                .group_by(TestCaseLocal.team_id, updated_day)
                .order_by(updated_day.asc())
            )

            created_rows = created_rows_result.all()
            updated_rows = updated_rows_result.all()

            involved_team_ids = {int(row[0]) for row in created_rows + updated_rows if row[0] is not None}

            team_name_map: Dict[int, str] = {}
            if involved_team_ids:
                teams_result = await session.execute(select(Team.id, Team.name).where(Team.id.in_(involved_team_ids)))
                team_name_map = {int(row[0]): (row[1] or f"未命名團隊 #{row[0]}") for row in teams_result.all()}

            return {
                "created_rows": created_rows,
                "updated_rows": updated_rows,
                "involved_team_ids": involved_team_ids,
                "team_name_map": team_name_map,
            }

        trend_data = await main_boundary.run_read(_load_trends)
        created_rows = trend_data["created_rows"]
        updated_rows = trend_data["updated_rows"]
        involved_team_ids = trend_data["involved_team_ids"]
        team_name_map = trend_data["team_name_map"]

        labels = _build_date_labels(start_date_obj, end_date_obj)

        created_map: Dict[int, Dict[str, int]] = defaultdict(dict)
        updated_map: Dict[int, Dict[str, int]] = defaultdict(dict)

        for team_id, day_value, count in created_rows:
            day_str = _day_to_label(day_value)
            if team_id is None or day_str is None:
                continue
            created_map[int(team_id)][day_str] = int(count)

        for team_id, day_value, count in updated_rows:
            day_str = _day_to_label(day_value)
            if team_id is None or day_str is None:
                continue
            updated_map[int(team_id)][day_str] = int(count)

        per_team_daily: List[Dict[str, Any]] = []

        for team_id in sorted(involved_team_ids):
            if team_id == 0:
                continue
            team_name = team_name_map.get(team_id, f"未命名團隊 #{team_id}")
            total_created = 0
            total_updated = 0
            daily_entries: List[Dict[str, Any]] = []

            for label in labels:
                created_count = created_map.get(team_id, {}).get(label, 0)
                updated_count = updated_map.get(team_id, {}).get(label, 0)
                total_created += created_count
                total_updated += updated_count
                daily_entries.append({"date": label, "created": created_count, "updated": updated_count})

            if total_created == 0 and total_updated == 0:
                continue

            per_team_daily.append(
                {
                    "team_id": team_id,
                    "team_name": team_name,
                    "daily": daily_entries,
                    "total_created": total_created,
                    "total_updated": total_updated,
                }
            )

        per_team_daily.sort(key=lambda item: (item["total_created"], item["total_updated"]), reverse=True)

        overall_daily_created: List[Dict[str, Any]] = []
        overall_daily_updated: List[Dict[str, Any]] = []

        for idx, label in enumerate(labels):
            created_sum = sum(team_entry["daily"][idx]["created"] for team_entry in per_team_daily)
            updated_sum = sum(team_entry["daily"][idx]["updated"] for team_entry in per_team_daily)
            overall_daily_created.append({"date": label, "count": created_sum})
            overall_daily_updated.append({"date": label, "count": updated_sum})

        total_created_sum = sum(team["total_created"] for team in per_team_daily)
        total_updated_sum = sum(team["total_updated"] for team in per_team_daily)

        response_payload = {
            "dates": labels,
            "per_team_daily": per_team_daily,
            "overall": {
                "daily_created": overall_daily_created,
                "daily_updated": overall_daily_updated,
                "total_created": total_created_sum,
                "total_updated": total_updated_sum,
            },
            "date_range": {"start": start_date_str, "end": end_date_str, "days": range_days},
        }

        return JSONResponse(response_payload)

    except Exception as e:
        logger.error(f"獲取測試案例趨勢失敗: {e}")
        raise HTTPException(status_code=500, detail={"error": "無法載入測試案例趨勢"})


@router.get("/test_run_metrics", include_in_schema=False)
async def get_test_run_metrics(
    current_user: User = Depends(require_admin()),
    days: int = Query(30, ge=1, le=MAX_STAT_RANGE_DAYS, description="統計天數"),
    start_date: Optional[date] = Query(None, description="開始日期 (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="結束日期 (YYYY-MM-DD)"),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    """
    測試執行指標分析

    Returns:
        - dates: 日期座標列表
        - per_team_daily: 團隊別每日執行統計
        - per_team_pass_rate: 團隊別每日通過率統計
        - by_status: 按狀態分佈 {status: count}
        - by_team: 按團隊統計總數
        - overall: 全域彙總（每日執行及通過率）
    """
    try:
        start_date_str, end_date_str, _, _, range_days = _resolve_date_range(days, start_date, end_date)
        start_date_obj = date.fromisoformat(start_date_str)
        end_date_obj = date.fromisoformat(end_date_str)

        async def _load_metrics(session: AsyncSession) -> Dict[str, Any]:
            daily_exec_day = func.date(TestRunItem.created_at)
            history_day = func.date(TestRunItemResultHistory.changed_at)
            pass_count_expr = func.sum(
                case(
                    (TestRunItemResultHistory.new_result == TestResultStatus.PASSED, 1),
                    else_=0,
                )
            ).label("pass_count")
            status_count_expr = func.count(TestRunItemResultHistory.id).label("cnt")
            team_count_expr = func.count(TestRunItem.id).label("cnt")

            daily_team_result = await session.execute(
                select(
                    TestRunItem.team_id,
                    daily_exec_day.label("day"),
                    func.count(TestRunItem.id).label("cnt"),
                )
                .where(daily_exec_day.between(start_date_str, end_date_str))
                .group_by(TestRunItem.team_id, daily_exec_day)
                .order_by(daily_exec_day.asc())
            )
            daily_team_rows = daily_team_result.all()

            pass_rate_team_result = await session.execute(
                select(
                    TestRunItemResultHistory.team_id,
                    history_day.label("day"),
                    pass_count_expr,
                    func.count(TestRunItemResultHistory.id).label("total_count"),
                )
                .where(history_day.between(start_date_str, end_date_str))
                .group_by(TestRunItemResultHistory.team_id, history_day)
                .order_by(history_day.asc())
            )
            pass_rate_team_rows = pass_rate_team_result.all()

            status_result = await session.execute(
                select(
                    TestRunItemResultHistory.new_result,
                    status_count_expr,
                )
                .where(history_day.between(start_date_str, end_date_str))
                .group_by(TestRunItemResultHistory.new_result)
            )
            by_status = {
                (_enum_storage_key(row[0]) if row[0] is not None else "unknown"): int(row[1])
                for row in status_result.all()
            }

            involved_team_ids = {int(row[0]) for row in daily_team_rows + pass_rate_team_rows if row[0] is not None}

            team_name_map: Dict[int, str] = {}
            if involved_team_ids:
                teams_result = await session.execute(select(Team.id, Team.name).where(Team.id.in_(involved_team_ids)))
                team_name_map = {int(row[0]): (row[1] or f"未命名團隊 #{row[0]}") for row in teams_result.all()}

            team_result = await session.execute(
                select(
                    TestRunItem.team_id,
                    Team.name,
                    team_count_expr,
                )
                .outerjoin(Team, TestRunItem.team_id == Team.id)
                .where(
                    daily_exec_day.between(start_date_str, end_date_str),
                    TestRunItem.team_id > 0,
                )
                .group_by(TestRunItem.team_id, Team.name)
                .order_by(team_count_expr.desc())
            )
            by_team = [
                {"team_id": row[0], "team_name": row[1] or f"Team {row[0]}", "count": int(row[2])}
                for row in team_result.all()
            ]

            return {
                "daily_team_rows": daily_team_rows,
                "pass_rate_team_rows": pass_rate_team_rows,
                "by_status": by_status,
                "involved_team_ids": involved_team_ids,
                "team_name_map": team_name_map,
                "by_team": by_team,
            }

        metric_data = await main_boundary.run_read(_load_metrics)
        daily_team_rows = metric_data["daily_team_rows"]
        pass_rate_team_rows = metric_data["pass_rate_team_rows"]
        by_status = metric_data["by_status"]
        involved_team_ids = metric_data["involved_team_ids"]
        team_name_map = metric_data["team_name_map"]
        by_team = metric_data["by_team"]

        labels = _build_date_labels(start_date_obj, end_date_obj)

        daily_exec_map: Dict[int, Dict[str, int]] = defaultdict(dict)
        for team_id, day_value, count in daily_team_rows:
            day_str = _day_to_label(day_value)
            if team_id is None or day_str is None:
                continue
            daily_exec_map[int(team_id)][day_str] = int(count)

        pass_rate_map: Dict[int, Dict[str, tuple]] = defaultdict(dict)
        for team_id, day_value, pass_count, total_count in pass_rate_team_rows:
            day_str = _day_to_label(day_value)
            if team_id is None or day_str is None:
                continue
            pass_rate_map[int(team_id)][day_str] = (int(pass_count), int(total_count))

        # 構建團隊別每日執行數據
        per_team_daily: List[Dict[str, Any]] = []
        for team_id in sorted(involved_team_ids):
            if team_id == 0:
                continue
            team_name = team_name_map.get(team_id, f"未命名團隊 #{team_id}")
            daily_entries: List[Dict[str, Any]] = []
            total_executions = 0

            for label in labels:
                exec_count = daily_exec_map.get(team_id, {}).get(label, 0)
                total_executions += exec_count
                daily_entries.append({"date": label, "count": exec_count})

            if total_executions == 0:
                continue

            per_team_daily.append(
                {
                    "team_id": team_id,
                    "team_name": team_name,
                    "daily": daily_entries,
                    "total_executions": total_executions,
                }
            )

        per_team_daily.sort(key=lambda item: item["total_executions"], reverse=True)

        # 構建團隊別每日通過率數據
        per_team_pass_rate: List[Dict[str, Any]] = []
        for team_id in sorted(involved_team_ids):
            if team_id == 0:
                continue
            team_name = team_name_map.get(team_id, f"未命名團隊 #{team_id}")
            daily_entries: List[Dict[str, Any]] = []
            total_pass = 0
            total_count = 0

            for label in labels:
                pass_count, count = pass_rate_map.get(team_id, {}).get(label, (0, 0))
                pass_rate = round((pass_count / count * 100) if count > 0 else 0, 2)
                total_pass += pass_count
                total_count += count
                daily_entries.append(
                    {"date": label, "pass_rate": pass_rate, "pass_count": pass_count, "total_count": count}
                )

            if total_count == 0:
                continue

            per_team_pass_rate.append(
                {
                    "team_id": team_id,
                    "team_name": team_name,
                    "daily": daily_entries,
                    "total_pass": total_pass,
                    "total_count": total_count,
                    "overall_pass_rate": round((total_pass / total_count * 100) if total_count > 0 else 0, 2),
                }
            )

        per_team_pass_rate.sort(key=lambda item: item["overall_pass_rate"], reverse=True)

        # 計算全域彙總
        overall_daily_executions: List[Dict[str, Any]] = []
        overall_pass_rate_trend: List[Dict[str, Any]] = []

        for idx, label in enumerate(labels):
            # 彙總執行數
            exec_sum = sum(team_entry["daily"][idx]["count"] for team_entry in per_team_daily)
            overall_daily_executions.append({"date": label, "count": exec_sum})

            # 彙總通過率
            pass_sum = sum(team_entry["daily"][idx]["pass_count"] for team_entry in per_team_pass_rate)
            total_sum = sum(team_entry["daily"][idx]["total_count"] for team_entry in per_team_pass_rate)
            pass_rate = round((pass_sum / total_sum * 100) if total_sum > 0 else 0, 2)
            overall_pass_rate_trend.append(
                {"date": label, "pass_rate": pass_rate, "pass_count": pass_sum, "total_count": total_sum}
            )

        response_payload = {
            "dates": labels,
            "per_team_daily": per_team_daily,
            "per_team_pass_rate": per_team_pass_rate,
            "by_status": by_status,
            "by_team": by_team,
            "overall": {"daily_executions": overall_daily_executions, "pass_rate_trend": overall_pass_rate_trend},
            "date_range": {"start": start_date_str, "end": end_date_str, "days": range_days},
        }

        return JSONResponse(response_payload)

    except Exception as e:
        logger.error(f"獲取測試執行指標失敗: {e}")
        raise HTTPException(status_code=500, detail={"error": "無法載入測試執行指標"})


@router.get("/user_activity", include_in_schema=False)
async def get_user_activity(
    current_user: User = Depends(require_admin()),
    days: int = Query(30, ge=1, le=MAX_STAT_RANGE_DAYS, description="統計天數"),
    start_date: Optional[date] = Query(None, description="開始日期 (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="結束日期 (YYYY-MM-DD)"),
    audit_boundary: AuditAccessBoundary = Depends(get_audit_access_boundary),
):
    """
    使用者行為分析 - 基於審計日誌

    Returns:
        - top_users: 最活躍使用者（前20）
        - by_operation: 操作類型分佈（全體使用者）
        - hourly_distribution: 每小時活動分佈
    """
    try:
        start_date, end_date, start_dt, end_dt, range_days = _resolve_date_range(days, start_date, end_date)

        async def _load_user_activity(audit_session: AsyncSession) -> Dict[str, Any]:
            logs_result = await audit_session.execute(
                select(
                    AuditLogTable.user_id,
                    AuditLogTable.username,
                    AuditLogTable.role,
                    AuditLogTable.action_type,
                    AuditLogTable.resource_type,
                    AuditLogTable.details,
                    AuditLogTable.timestamp,
                ).where(AuditLogTable.timestamp >= start_dt, AuditLogTable.timestamp <= end_dt)
            )
            user_counter: Dict[int, Dict[str, Any]] = {}
            operation_counter: Dict[str, int] = {}
            hourly_counter: Dict[int, int] = {}

            for row in logs_result.all():
                weight = _get_action_weight(row.resource_type, row.details)
                if weight <= 0:
                    continue

                uid = row.user_id
                hour_val = row.timestamp.hour if row.timestamp else None
                action_key = _enum_value(row.action_type)

                entry = user_counter.setdefault(
                    uid, {"user_id": uid, "username": row.username, "role": row.role, "action_count": 0}
                )
                entry["action_count"] += weight

                operation_counter[action_key] = operation_counter.get(action_key, 0) + weight

                if hour_val is not None:
                    hourly_counter[hour_val] = hourly_counter.get(hour_val, 0) + weight

            top_users = sorted(user_counter.values(), key=lambda x: x["action_count"], reverse=True)[:20]
            return {
                "top_users": top_users,
                "by_operation": operation_counter,
                "hourly_distribution": hourly_counter,
            }

        user_activity = await audit_boundary.run_read(_load_user_activity)

        return JSONResponse({**user_activity, "date_range": {"start": start_date, "end": end_date, "days": range_days}})

    except Exception as e:
        logger.error(f"獲取使用者活動統計失敗: {e}")
        raise HTTPException(status_code=500, detail={"error": "無法載入使用者活動統計"})


@router.get("/audit_analysis", include_in_schema=False)
async def get_audit_analysis(
    current_user: User = Depends(require_admin()),
    days: int = Query(30, ge=1, le=MAX_STAT_RANGE_DAYS, description="統計天數"),
    start_date: Optional[date] = Query(None, description="開始日期 (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="結束日期 (YYYY-MM-DD)"),
    audit_boundary: AuditAccessBoundary = Depends(get_audit_access_boundary),
):
    """
    審計日誌深度分析

    Returns:
        - by_resource_type: 按資源類型分佈
        - by_severity: 按嚴重性分佈
        - critical_actions: 關鍵操作列表（severity=critical，最近50筆）
        - daily_trend: 每日操作趨勢
    """
    try:
        start_date, end_date, start_dt, end_dt, range_days = _resolve_date_range(days, start_date, end_date)

        async def _load_audit_analysis(audit_session: AsyncSession) -> Dict[str, Any]:
            resource_count_expr = func.count(AuditLogTable.id).label("cnt")
            severity_count_expr = func.count(AuditLogTable.id).label("cnt")
            daily_day = func.date(AuditLogTable.timestamp)
            resource_result = await audit_session.execute(
                select(
                    AuditLogTable.resource_type,
                    resource_count_expr,
                )
                .where(
                    AuditLogTable.timestamp >= start_dt,
                    AuditLogTable.timestamp <= end_dt,
                )
                .group_by(AuditLogTable.resource_type)
                .order_by(resource_count_expr.desc())
            )
            by_resource_type = {_enum_storage_key(row[0]): int(row[1]) for row in resource_result.all()}

            severity_result = await audit_session.execute(
                select(
                    AuditLogTable.severity,
                    severity_count_expr,
                )
                .where(
                    AuditLogTable.timestamp >= start_dt,
                    AuditLogTable.timestamp <= end_dt,
                )
                .group_by(AuditLogTable.severity)
            )
            by_severity = {_enum_storage_key(row[0]): int(row[1]) for row in severity_result.all()}

            critical_result = await audit_session.execute(
                select(AuditLogTable)
                .where(
                    AuditLogTable.timestamp >= start_dt,
                    AuditLogTable.timestamp <= end_dt,
                    AuditLogTable.severity == AuditSeverity.CRITICAL,
                )
                .order_by(AuditLogTable.timestamp.desc())
                .limit(50)
            )
            critical_actions = [
                {
                    "id": log.id,
                    "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                    "username": log.username,
                    "action_type": _enum_storage_key(log.action_type),
                    "resource_type": _enum_storage_key(log.resource_type),
                    "resource_id": log.resource_id,
                    "action_brief": log.action_brief,
                    "team_id": log.team_id,
                }
                for log in critical_result.scalars()
            ]

            daily_result = await audit_session.execute(
                select(
                    daily_day.label("day"),
                    func.count(AuditLogTable.id).label("cnt"),
                )
                .where(
                    AuditLogTable.timestamp >= start_dt,
                    AuditLogTable.timestamp <= end_dt,
                )
                .group_by(daily_day)
                .order_by(daily_day.asc())
            )
            daily_trend = [{"date": _day_to_label(row[0]), "count": int(row[1])} for row in daily_result.all()]

            return {
                "by_resource_type": by_resource_type,
                "by_severity": by_severity,
                "critical_actions": critical_actions,
                "daily_trend": daily_trend,
            }

        audit_analysis = await audit_boundary.run_read(_load_audit_analysis)

        return JSONResponse(
            {**audit_analysis, "date_range": {"start": start_date, "end": end_date, "days": range_days}}
        )

    except Exception as e:
        logger.error(f"獲取審計分析統計失敗: {e}")
        raise HTTPException(status_code=500, detail={"error": "無法載入審計分析統計"})


@router.get("/department_stats", include_in_schema=False)
async def get_department_stats(
    current_user: User = Depends(require_admin()),
    days: int = Query(30, ge=1, le=MAX_STAT_RANGE_DAYS, description="統計天數"),
    start_date: Optional[date] = Query(None, description="開始日期 (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="結束日期 (YYYY-MM-DD)"),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
    audit_boundary: AuditAccessBoundary = Depends(get_audit_access_boundary),
):
    """
    部門與人員統計 - 基於 Lark 組織架構

    Returns:
        - by_department: 按部門統計活動（基於審計日誌的 username 關聯）
        - department_list: 部門列表與人員數
        - user_distribution: 使用者角色分佈
    """
    try:
        start_date, end_date, start_dt, end_dt, range_days = _resolve_date_range(days, start_date, end_date)

        async def _load_department_meta(session: AsyncSession) -> Dict[str, Any]:
            dept_rows = await session.execute(
                select(
                    LarkDepartment.department_id,
                    LarkDepartment.path,
                    LarkDepartment.direct_user_count,
                    LarkDepartment.total_user_count,
                ).where(LarkDepartment.status == "active")
            )
            dept_map: Dict[str, Dict[str, Any]] = {}
            for department_id, path, direct_count, total_count in dept_rows.all():
                dept_map[department_id] = {
                    "path": path,
                    "direct_user_count": int(direct_count or 0),
                    "total_user_count": int(total_count or 0),
                }

            role_result = await session.execute(
                select(
                    User.role,
                    func.count(User.id).label("cnt"),
                )
                .where(User.is_active == True)
                .group_by(User.role)
            )
            user_distribution = {
                (_enum_storage_key(row[0]) if row[0] is not None else "unknown"): int(row[1])
                for row in role_result.all()
            }

            lark_user_rows = await session.execute(
                select(
                    LarkUser.primary_department_id,
                    LarkUser.department_ids_json,
                ).where(
                    LarkUser.is_activated == True,
                    LarkUser.is_exited == False,
                )
            )

            total_counter: Counter = Counter()
            direct_counter: Counter = Counter()
            for primary_id, dept_ids_json in lark_user_rows.all():
                if primary_id:
                    direct_counter[primary_id] += 1
                if not dept_ids_json:
                    continue
                try:
                    parsed = json.loads(dept_ids_json)
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(parsed, list):
                    for dept_id in parsed:
                        if isinstance(dept_id, str) and dept_id:
                            total_counter[dept_id] += 1

            return {
                "dept_map": dept_map,
                "user_distribution": user_distribution,
                "total_counter": total_counter,
                "direct_counter": direct_counter,
            }

        department_meta = await main_boundary.run_read(_load_department_meta)
        dept_map = department_meta["dept_map"]
        user_distribution = department_meta["user_distribution"]
        total_counter = department_meta["total_counter"]
        direct_counter = department_meta["direct_counter"]

        department_entries: List[Dict[str, Any]] = []
        all_dept_ids = set(dept_map.keys()) | set(total_counter.keys()) | set(direct_counter.keys())

        for dept_id in all_dept_ids:
            meta = dept_map.get(dept_id, {})
            total = total_counter.get(dept_id, meta.get("total_user_count", 0))
            direct = direct_counter.get(dept_id, meta.get("direct_user_count", 0))
            display_name = _format_department_name(dept_id, meta.get("path"))

            department_entries.append(
                {
                    "dept_id": dept_id,
                    "dept_name": display_name,
                    "display_name": display_name,
                    "total_user_count": int(total or 0),
                    "direct_user_count": int(direct or 0),
                }
            )

        department_entries.sort(key=lambda item: item["total_user_count"], reverse=True)
        department_list = department_entries[:50]

        async def _load_department_activity(audit_session: AsyncSession) -> List[Dict[str, Any]]:
            action_count_expr = func.count(AuditLogTable.id).label("action_count")
            dept_activity_result = await audit_session.execute(
                select(
                    AuditLogTable.username,
                    action_count_expr,
                )
                .where(
                    AuditLogTable.timestamp >= start_dt,
                    AuditLogTable.timestamp <= end_dt,
                )
                .group_by(AuditLogTable.username)
                .order_by(action_count_expr.desc())
                .limit(50)
            )
            return [{"username": row[0], "action_count": int(row[1])} for row in dept_activity_result.all()]

        by_department_users = await audit_boundary.run_read(_load_department_activity)

        return JSONResponse(
            {
                "department_list": department_list,
                "user_distribution": user_distribution,
                "by_department_users": by_department_users,
                "date_range": {"start": start_date, "end": end_date, "days": range_days},
            }
        )

    except Exception as e:
        logger.error(f"獲取部門統計失敗: {e}")
        raise HTTPException(status_code=500, detail={"error": "無法載入部門統計"})



