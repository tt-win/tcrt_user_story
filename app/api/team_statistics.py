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
from collections import Counter, defaultdict
from sqlalchemy import text, func, and_, select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal
from app.auth.dependencies import require_admin
from app.models.database_models import User, TestCaseLocal, TestRunItem, TestRunConfig, Team, LarkUser, LarkDepartment
from app.models.team import TeamStatus
from app.audit.database import get_audit_session, AuditLogTable
from app.audit.models import ActionType, ResourceType, AuditSeverity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/team_statistics", tags=["team_statistics"])


def _get_date_range(days: int) -> tuple[str, str]:
    """計算日期範圍（ISO 格式字符串）"""
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=days)
    return start_dt.date().isoformat(), end_dt.date().isoformat()


def _extract_assignee_names(payload: Any) -> List[str]:
    """從 assignee_json 負載中提取姓名列表"""
    names: List[str] = []

    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            # 以逗號分隔的字串簡單拆解
            for part in payload.split(','):
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
        parts = [segment for segment in path.split('/') if segment and segment != '0']
        if parts:
            readable_parts = [
                part if not part.startswith('od-') or len(part) <= 8 else f"{part[:3]}…{part[-4:]}"
                for part in parts[-3:]
            ]
            return " / ".join(readable_parts)

    if dept_id.startswith('od-') and len(dept_id) > 8:
        return f"{dept_id[:3]}…{dept_id[-4:]}"

    return dept_id


@router.get("/overview", include_in_schema=False)
async def get_overview(
    current_user: User = Depends(require_admin()),
    days: int = Query(30, ge=1, le=90, description="統計天數")
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
        start_date, end_date = _get_date_range(days)

        async with SessionLocal() as session:
            # 統計團隊數
            team_count_result = await session.execute(
                select(func.count(Team.id)).where(Team.status == TeamStatus.ACTIVE)
            )
            team_count = team_count_result.scalar() or 0

            # 統計活躍使用者數
            user_count_result = await session.execute(
                select(func.count(User.id)).where(User.is_active == True)
            )
            user_count = user_count_result.scalar() or 0

            # 統計測試案例總數
            test_case_count_result = await session.execute(
                select(func.count(TestCaseLocal.id))
            )
            test_case_total = test_case_count_result.scalar() or 0

            # 統計測試執行配置總數（Test Run 總數）
            test_run_result = await session.execute(
                select(func.count(TestRunConfig.id))
            )
            test_run_total = test_run_result.scalar() or 0

            # 統計每個團隊的 Test Case 總數
            team_test_case_result = await session.execute(
                select(
                    TestCaseLocal.team_id,
                    Team.name,
                    func.count(TestCaseLocal.id).label('test_case_count')
                )
                .join(Team, TestCaseLocal.team_id == Team.id)
                .where(Team.status == TeamStatus.ACTIVE)
                .group_by(TestCaseLocal.team_id, Team.name)
                .order_by(desc('test_case_count'))
            )
            team_test_cases = [
                {
                    "team_id": row[0],
                    "team_name": row[1],
                    "test_case_count": row[2]
                }
                for row in team_test_case_result.all()
            ]

            # 統計每個團隊的 Test Run 總數
            team_test_run_result = await session.execute(
                select(
                    TestRunConfig.team_id,
                    Team.name,
                    func.count(TestRunConfig.id).label('test_run_count')
                )
                .join(Team, TestRunConfig.team_id == Team.id)
                .where(Team.status == TeamStatus.ACTIVE)
                .group_by(TestRunConfig.team_id, Team.name)
                .order_by(desc('test_run_count'))
            )
            team_test_runs = [
                {
                    "team_id": row[0],
                    "team_name": row[1],
                    "test_run_count": row[2]
                }
                for row in team_test_run_result.all()
            ]

        # 從審計日誌取得最近活動
        async with get_audit_session() as audit_session:
            recent_logs = await audit_session.execute(
                select(AuditLogTable)
                .order_by(desc(AuditLogTable.timestamp))
                .limit(10)
            )
            recent_activity = [
                {
                    "id": log.id,
                    "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                    "username": log.username,
                    "action_type": log.action_type.value if log.action_type else None,
                    "resource_type": log.resource_type.value if log.resource_type else None,
                    "action_brief": log.action_brief,
                    "severity": log.severity.value if log.severity else "info"
                }
                for log in recent_logs.scalars()
            ]

        return JSONResponse({
            "team_count": team_count,
            "user_count": user_count,
            "test_case_total": test_case_total,
            "test_run_total": test_run_total,
            "team_test_cases": team_test_cases,
            "team_test_runs": team_test_runs,
            "recent_activity": recent_activity,
            "date_range": {
                "start": start_date,
                "end": end_date,
                "days": days
            }
        })

    except Exception as e:
        logger.error(f"獲取總覽統計失敗: {e}")
        raise HTTPException(status_code=500, detail={"error": "無法載入總覽統計"})


@router.get("/team_activity", include_in_schema=False)
async def get_team_activity(
    current_user: User = Depends(require_admin()),
    days: int = Query(30, ge=1, le=90, description="統計天數")
):
    """
    團隊活動分析 - 基於審計日誌

    Returns:
        - by_team: 各團隊操作統計 {team_id: {team_name, total, by_action}}
        - top_active_teams: 最活躍團隊列表（前10）
    """
    try:
        start_date, end_date = _get_date_range(days)
        start_dt = datetime.fromisoformat(start_date + "T00:00:00+00:00")

        # 獲取團隊資訊
        async with SessionLocal() as session:
            teams_result = await session.execute(
                select(Team.id, Team.name).where(Team.status == TeamStatus.ACTIVE)
            )
            teams_dict = {row[0]: row[1] for row in teams_result}

        # 從審計日誌統計團隊活動
        async with get_audit_session() as audit_session:
            # 統計各團隊的操作數量（按操作類型分組）
            activity_result = await audit_session.execute(
                text("""
                    SELECT team_id, action_type, COUNT(*) as count
                    FROM audit_logs
                    WHERE timestamp >= :start_dt
                    GROUP BY team_id, action_type
                    ORDER BY team_id, action_type
                """),
                {"start_dt": start_dt}
            )
            activity_rows = activity_result.all()

        # 整理數據
        by_team = {}
        for team_id, action_type, count in activity_rows:
            if team_id not in by_team:
                by_team[team_id] = {
                    "team_id": team_id,
                    "team_name": teams_dict.get(team_id, f"Team {team_id}"),
                    "total": 0,
                    "by_action": {}
                }
            by_team[team_id]["total"] += count
            by_team[team_id]["by_action"][action_type] = count

        # 排序取得最活躍團隊
        top_active_teams = sorted(
            by_team.values(),
            key=lambda x: x["total"],
            reverse=True
        )[:10]

        return JSONResponse({
            "by_team": by_team,
            "top_active_teams": top_active_teams,
            "date_range": {
                "start": start_date,
                "end": end_date,
                "days": days
            }
        })

    except Exception as e:
        logger.error(f"獲取團隊活動統計失敗: {e}")
        raise HTTPException(status_code=500, detail={"error": "無法載入團隊活動統計"})


@router.get("/test_case_trends", include_in_schema=False)
async def get_test_case_trends(
    current_user: User = Depends(require_admin()),
    days: int = Query(30, ge=1, le=90, description="統計天數")
):
    """
    測試案例趨勢分析

    Returns:
        - dates: 日期座標列表
        - per_team_daily: 團隊別每日新增/更新統計
        - overall: 全域彙總（每日新增/更新及總量）
    """
    try:
        start_date_str, end_date_str = _get_date_range(days)
        start_date_obj = date.fromisoformat(start_date_str)
        end_date_obj = date.fromisoformat(end_date_str)

        async with SessionLocal() as session:
            created_rows_result = await session.execute(
                text(
                    """
                    SELECT team_id, date(created_at) AS day, COUNT(*) AS cnt
                    FROM test_cases
                    WHERE date(created_at) BETWEEN :start_date AND :end_date
                    GROUP BY team_id, day
                    ORDER BY day ASC
                    """
                ),
                {"start_date": start_date_str, "end_date": end_date_str}
            )

            updated_rows_result = await session.execute(
                text(
                    """
                    SELECT team_id, date(updated_at) AS day, COUNT(*) AS cnt
                    FROM test_cases
                    WHERE updated_at IS NOT NULL
                      AND updated_at > created_at
                      AND date(updated_at) BETWEEN :start_date AND :end_date
                    GROUP BY team_id, day
                    ORDER BY day ASC
                    """
                ),
                {"start_date": start_date_str, "end_date": end_date_str}
            )

            created_rows = created_rows_result.all()
            updated_rows = updated_rows_result.all()

            involved_team_ids = {
                int(row[0]) for row in created_rows + updated_rows if row[0] is not None
            }

            team_name_map: Dict[int, str] = {}
            if involved_team_ids:
                teams_result = await session.execute(
                    select(Team.id, Team.name).where(Team.id.in_(involved_team_ids))
                )
                team_name_map = {
                    int(row[0]): (row[1] or f"未命名團隊 #{row[0]}")
                    for row in teams_result.all()
                }

        date_cursor = start_date_obj
        labels: List[str] = []
        while date_cursor <= end_date_obj:
            labels.append(date_cursor.isoformat())
            date_cursor += timedelta(days=1)

        created_map: Dict[int, Dict[str, int]] = defaultdict(dict)
        updated_map: Dict[int, Dict[str, int]] = defaultdict(dict)

        for team_id, day_value, count in created_rows:
            if team_id is None or day_value is None:
                continue
            day_str = day_value if isinstance(day_value, str) else day_value.isoformat()
            created_map[int(team_id)][day_str] = int(count)

        for team_id, day_value, count in updated_rows:
            if team_id is None or day_value is None:
                continue
            day_str = day_value if isinstance(day_value, str) else day_value.isoformat()
            updated_map[int(team_id)][day_str] = int(count)

        per_team_daily: List[Dict[str, Any]] = []

        for team_id in sorted(involved_team_ids):
            team_name = team_name_map.get(team_id, f"未命名團隊 #{team_id}")
            total_created = 0
            total_updated = 0
            daily_entries: List[Dict[str, Any]] = []

            for label in labels:
                created_count = created_map.get(team_id, {}).get(label, 0)
                updated_count = updated_map.get(team_id, {}).get(label, 0)
                total_created += created_count
                total_updated += updated_count
                daily_entries.append({
                    "date": label,
                    "created": created_count,
                    "updated": updated_count
                })

            if total_created == 0 and total_updated == 0:
                continue

            per_team_daily.append({
                "team_id": team_id,
                "team_name": team_name,
                "daily": daily_entries,
                "total_created": total_created,
                "total_updated": total_updated
            })

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
                "total_updated": total_updated_sum
            },
            "date_range": {
                "start": start_date_str,
                "end": end_date_str,
                "days": days
            }
        }

        return JSONResponse(response_payload)

    except Exception as e:
        logger.error(f"獲取測試案例趨勢失敗: {e}")
        raise HTTPException(status_code=500, detail={"error": "無法載入測試案例趨勢"})


@router.get("/test_run_metrics", include_in_schema=False)
async def get_test_run_metrics(
    current_user: User = Depends(require_admin()),
    days: int = Query(30, ge=1, le=90, description="統計天數")
):
    """
    測試執行指標分析

    Returns:
        - daily_executions: 每日執行次數 [{date, count}]
        - by_status: 按狀態分佈 {status: count}
        - pass_rate_trend: 通過率趨勢（每日）
        - by_team: 按團隊統計
    """
    try:
        start_date, end_date = _get_date_range(days)

        async with SessionLocal() as session:
            # 每日執行次數
            daily_result = await session.execute(
                text("""
                    SELECT date(created_at) as day, COUNT(*) as cnt
                    FROM test_run_items
                    WHERE date(created_at) >= :start_date
                    GROUP BY day
                    ORDER BY day ASC
                """),
                {"start_date": start_date}
            )
            daily_executions = [
                {"date": row[0], "count": int(row[1])}
                for row in daily_result.all()
            ]

            # 按狀態分佈（從 test_run_item_result_history）
            status_result = await session.execute(
                text("""
                    SELECT new_result, COUNT(*) as cnt
                    FROM test_run_item_result_history
                    WHERE date(changed_at) >= :start_date
                    GROUP BY new_result
                """),
                {"start_date": start_date}
            )
            by_status = {
                row[0] or "unknown": int(row[1])
                for row in status_result.all()
            }

            # 通過率趨勢（每日）
            pass_rate_result = await session.execute(
                text("""
                    SELECT
                        date(changed_at) as day,
                        SUM(CASE WHEN new_result = 'Pass' THEN 1 ELSE 0 END) as pass_count,
                        COUNT(*) as total_count
                    FROM test_run_item_result_history
                    WHERE date(changed_at) >= :start_date
                    GROUP BY day
                    ORDER BY day ASC
                """),
                {"start_date": start_date}
            )
            pass_rate_trend = [
                {
                    "date": row[0],
                    "pass_rate": round((row[1] / row[2] * 100) if row[2] > 0 else 0, 2),
                    "pass_count": int(row[1]),
                    "total_count": int(row[2])
                }
                for row in pass_rate_result.all()
            ]

            # 按團隊統計
            team_result = await session.execute(
                text("""
                    SELECT tri.team_id, t.name, COUNT(*) as cnt
                    FROM test_run_items tri
                    LEFT JOIN teams t ON tri.team_id = t.id
                    WHERE date(tri.created_at) >= :start_date
                    GROUP BY tri.team_id, t.name
                    ORDER BY cnt DESC
                """),
                {"start_date": start_date}
            )
            by_team = [
                {
                    "team_id": row[0],
                    "team_name": row[1] or f"Team {row[0]}",
                    "count": int(row[2])
                }
                for row in team_result.all()
            ]

        return JSONResponse({
            "daily_executions": daily_executions,
            "by_status": by_status,
            "pass_rate_trend": pass_rate_trend,
            "by_team": by_team,
            "date_range": {
                "start": start_date,
                "end": end_date,
                "days": days
            }
        })

    except Exception as e:
        logger.error(f"獲取測試執行指標失敗: {e}")
        raise HTTPException(status_code=500, detail={"error": "無法載入測試執行指標"})


@router.get("/user_activity", include_in_schema=False)
async def get_user_activity(
    current_user: User = Depends(require_admin()),
    days: int = Query(30, ge=1, le=90, description="統計天數")
):
    """
    使用者行為分析 - 基於審計日誌

    Returns:
        - top_users: 最活躍使用者（前20）
        - by_operation: 操作類型分佈（全體使用者）
        - hourly_distribution: 每小時活動分佈
    """
    try:
        start_date, end_date = _get_date_range(days)
        start_dt = datetime.fromisoformat(start_date + "T00:00:00+00:00")

        async with get_audit_session() as audit_session:
            # 最活躍使用者
            top_users_result = await audit_session.execute(
                text("""
                    SELECT user_id, username, role, COUNT(*) as action_count
                    FROM audit_logs
                    WHERE timestamp >= :start_dt
                    GROUP BY user_id, username, role
                    ORDER BY action_count DESC
                    LIMIT 20
                """),
                {"start_dt": start_dt}
            )
            top_users = [
                {
                    "user_id": row[0],
                    "username": row[1],
                    "role": row[2],
                    "action_count": int(row[3])
                }
                for row in top_users_result.all()
            ]

            # 操作類型分佈
            operation_result = await audit_session.execute(
                text("""
                    SELECT action_type, COUNT(*) as cnt
                    FROM audit_logs
                    WHERE timestamp >= :start_dt
                    GROUP BY action_type
                    ORDER BY cnt DESC
                """),
                {"start_dt": start_dt}
            )
            by_operation = {
                row[0]: int(row[1])
                for row in operation_result.all()
            }

            # 每小時活動分佈（0-23 小時）
            hourly_result = await audit_session.execute(
                text("""
                    SELECT strftime('%H', timestamp) as hour, COUNT(*) as cnt
                    FROM audit_logs
                    WHERE timestamp >= :start_dt
                    GROUP BY hour
                    ORDER BY hour
                """),
                {"start_dt": start_dt}
            )
            hourly_distribution = {
                int(row[0]): int(row[1])
                for row in hourly_result.all()
            }

        return JSONResponse({
            "top_users": top_users,
            "by_operation": by_operation,
            "hourly_distribution": hourly_distribution,
            "date_range": {
                "start": start_date,
                "end": end_date,
                "days": days
            }
        })

    except Exception as e:
        logger.error(f"獲取使用者活動統計失敗: {e}")
        raise HTTPException(status_code=500, detail={"error": "無法載入使用者活動統計"})


@router.get("/audit_analysis", include_in_schema=False)
async def get_audit_analysis(
    current_user: User = Depends(require_admin()),
    days: int = Query(30, ge=1, le=90, description="統計天數")
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
        start_date, end_date = _get_date_range(days)
        start_dt = datetime.fromisoformat(start_date + "T00:00:00+00:00")

        async with get_audit_session() as audit_session:
            # 按資源類型分佈
            resource_result = await audit_session.execute(
                text("""
                    SELECT resource_type, COUNT(*) as cnt
                    FROM audit_logs
                    WHERE timestamp >= :start_dt
                    GROUP BY resource_type
                    ORDER BY cnt DESC
                """),
                {"start_dt": start_dt}
            )
            by_resource_type = {
                row[0]: int(row[1])
                for row in resource_result.all()
            }

            # 按嚴重性分佈
            severity_result = await audit_session.execute(
                text("""
                    SELECT severity, COUNT(*) as cnt
                    FROM audit_logs
                    WHERE timestamp >= :start_dt
                    GROUP BY severity
                """),
                {"start_dt": start_dt}
            )
            by_severity = {
                row[0]: int(row[1])
                for row in severity_result.all()
            }

            # 關鍵操作列表
            critical_result = await audit_session.execute(
                text("""
                    SELECT id, timestamp, username, action_type, resource_type,
                           resource_id, action_brief, team_id
                    FROM audit_logs
                    WHERE timestamp >= :start_dt AND severity = 'critical'
                    ORDER BY timestamp DESC
                    LIMIT 50
                """),
                {"start_dt": start_dt}
            )
            critical_actions = [
                {
                    "id": row[0],
                    "timestamp": row[1].isoformat() if row[1] else None,
                    "username": row[2],
                    "action_type": row[3],
                    "resource_type": row[4],
                    "resource_id": row[5],
                    "action_brief": row[6],
                    "team_id": row[7]
                }
                for row in critical_result.all()
            ]

            # 每日操作趨勢
            daily_result = await audit_session.execute(
                text("""
                    SELECT date(timestamp) as day, COUNT(*) as cnt
                    FROM audit_logs
                    WHERE timestamp >= :start_dt
                    GROUP BY day
                    ORDER BY day ASC
                """),
                {"start_dt": start_dt}
            )
            daily_trend = [
                {"date": row[0], "count": int(row[1])}
                for row in daily_result.all()
            ]

        return JSONResponse({
            "by_resource_type": by_resource_type,
            "by_severity": by_severity,
            "critical_actions": critical_actions,
            "daily_trend": daily_trend,
            "date_range": {
                "start": start_date,
                "end": end_date,
                "days": days
            }
        })

    except Exception as e:
        logger.error(f"獲取審計分析統計失敗: {e}")
        raise HTTPException(status_code=500, detail={"error": "無法載入審計分析統計"})


@router.get("/department_stats", include_in_schema=False)
async def get_department_stats(
    current_user: User = Depends(require_admin()),
    days: int = Query(30, ge=1, le=90, description="統計天數")
):
    """
    部門與人員統計 - 基於 Lark 組織架構

    Returns:
        - by_department: 按部門統計活動（基於審計日誌的 username 關聯）
        - department_list: 部門列表與人員數
        - user_distribution: 使用者角色分佈
    """
    try:
        start_date, end_date = _get_date_range(days)
        start_dt = datetime.fromisoformat(start_date + "T00:00:00+00:00")

        async with SessionLocal() as session:
            dept_rows = await session.execute(
                text("""
                    SELECT department_id, path, direct_user_count, total_user_count
                    FROM lark_departments
                    WHERE status = 'active'
                """)
            )
            dept_map: Dict[str, Dict[str, Any]] = {}
            for department_id, path, direct_count, total_count in dept_rows.all():
                dept_map[department_id] = {
                    "path": path,
                    "direct_user_count": int(direct_count or 0),
                    "total_user_count": int(total_count or 0),
                }

            role_result = await session.execute(
                text("""
                    SELECT role, COUNT(*) as cnt
                    FROM users
                    WHERE is_active = 1
                    GROUP BY role
                """)
            )
            user_distribution = {
                (row[0] or "unknown"): int(row[1])
                for row in role_result.all()
            }

            lark_user_rows = await session.execute(
                text("""
                    SELECT primary_department_id, department_ids_json
                    FROM lark_users
                    WHERE is_activated = 1 AND is_exited = 0
                """)
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

        department_entries: List[Dict[str, Any]] = []
        all_dept_ids = set(dept_map.keys()) | set(total_counter.keys()) | set(direct_counter.keys())

        for dept_id in all_dept_ids:
            meta = dept_map.get(dept_id, {})
            total = total_counter.get(dept_id, meta.get("total_user_count", 0))
            direct = direct_counter.get(dept_id, meta.get("direct_user_count", 0))
            display_name = _format_department_name(dept_id, meta.get("path"))

            department_entries.append({
                "dept_id": dept_id,
                "dept_name": display_name,
                "display_name": display_name,
                "total_user_count": int(total or 0),
                "direct_user_count": int(direct or 0),
            })

        department_entries.sort(key=lambda item: item["total_user_count"], reverse=True)
        department_list = department_entries[:50]

        # 按部門統計活動（透過審計日誌）
        # 這裡簡化處理：直接統計前10個最活躍的部門相關用戶
        async with get_audit_session() as audit_session:
            dept_activity_result = await audit_session.execute(
                text("""
                    SELECT username, COUNT(*) as action_count
                    FROM audit_logs
                    WHERE timestamp >= :start_dt
                    GROUP BY username
                    ORDER BY action_count DESC
                    LIMIT 50
                """),
                {"start_dt": start_dt}
            )
            by_department_users = [
                {"username": row[0], "action_count": int(row[1])}
                for row in dept_activity_result.all()
            ]

        return JSONResponse({
            "department_list": department_list,
            "user_distribution": user_distribution,
            "by_department_users": by_department_users,
            "date_range": {
                "start": start_date,
                "end": end_date,
                "days": days
            }
        })

    except Exception as e:
        logger.error(f"獲取部門統計失敗: {e}")
        raise HTTPException(status_code=500, detail={"error": "無法載入部門統計"})
