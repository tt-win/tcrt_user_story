"""
QA AI Helper 團隊數據統計 API

涵蓋 Session 漏斗、採用率、生成產出、LLM 遙測、使用者與團隊參與度分析。
僅限 Admin 及以上角色存取。
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.db_access.main import MainAccessBoundary, get_main_access_boundary
from app.models.database_models import (
    QAAIHelperCommitLink,
    QAAIHelperSeedItem,
    QAAIHelperSeedSet,
    QAAIHelperSession,
    QAAIHelperTelemetryEvent,
    QAAIHelperTestcaseDraft,
    QAAIHelperTestcaseDraftSet,
    Team,
    TestCaseLocal,
    User,
)
from app.models.team import TeamStatus

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/team_statistics/qa-ai-helper",
    tags=["team_statistics_qa_ai_helper"],
)

MAX_STAT_RANGE_DAYS = 90

# ---------------------------------------------------------------------------
# 快取（60 秒 TTL）
# ---------------------------------------------------------------------------
_cache: Dict[str, Tuple[float, Any]] = {}
_CACHE_TTL = 60.0


def _cache_key(endpoint: str, **params: Any) -> str:
    raw = f"{endpoint}:{json.dumps(params, sort_keys=True, default=str)}"
    return hashlib.md5(raw.encode()).hexdigest()


def _get_cached(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry and (time.monotonic() - entry[0]) < _CACHE_TTL:
        return entry[1]
    return None


def _set_cached(key: str, value: Any) -> None:
    _cache[key] = (time.monotonic(), value)


# ---------------------------------------------------------------------------
# 共用工具函式
# ---------------------------------------------------------------------------


def _parse_team_ids(raw_team_ids: Optional[str]) -> List[int]:
    if not raw_team_ids:
        return []
    values: List[int] = []
    seen: set[int] = set()
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


def _resolve_date_range(
    days: int, start_date: Optional[date], end_date: Optional[date]
) -> Tuple[str, str, datetime, datetime, int]:
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


def _build_date_labels(start_date_obj: date, end_date_obj: date) -> List[str]:
    cursor = start_date_obj
    labels: List[str] = []
    while cursor <= end_date_obj:
        labels.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return labels


def _safe_adoption(adopted: int, generated: int) -> float:
    if generated <= 0:
        return 0.0
    return round(adopted / generated, 4)


def _p95(values: List[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return int(ordered[index])


def _date_range_payload(start_str: str, end_str: str, days: int) -> Dict[str, Any]:
    return {"start": start_str, "end": end_str, "days": days}


# ---------------------------------------------------------------------------
# 共用查詢 helpers
# ---------------------------------------------------------------------------
# 以下 session 子查詢模式用於所有端點：先篩出符合 team_ids + 日期範圍的 session_ids。


def _session_filter(start_dt: datetime, end_dt: datetime, team_ids: List[int]):
    """回傳套用了日期與團隊篩選的 session SELECT 條件清單。"""
    conditions = [
        QAAIHelperSession.created_at >= start_dt,
        QAAIHelperSession.created_at <= end_dt,
    ]
    if team_ids:
        conditions.append(QAAIHelperSession.team_id.in_(team_ids))
    return conditions


async def _load_team_names(session: AsyncSession, team_ids: set[int] | None = None) -> Dict[int, str]:
    stmt = select(Team.id, Team.name).where(Team.status == TeamStatus.ACTIVE)
    if team_ids:
        stmt = stmt.where(Team.id.in_(team_ids))
    rows = (await session.execute(stmt)).all()
    return {int(r[0]): (r[1] or f"未命名團隊 #{r[0]}") for r in rows}


async def _load_user_names(session: AsyncSession, user_ids: set[int] | None = None) -> Dict[int, str]:
    stmt = select(User.id, User.username)
    if user_ids:
        stmt = stmt.where(User.id.in_(user_ids))
    rows = (await session.execute(stmt)).all()
    return {int(r[0]): (r[1] or f"user#{r[0]}") for r in rows}


# ===========================================================================
# 端點 1: GET /overview
# ===========================================================================
@router.get("/overview", include_in_schema=False)
async def get_qa_ai_helper_overview(
    current_user: User = Depends(require_admin()),
    days: int = Query(30, ge=1, le=MAX_STAT_RANGE_DAYS, description="統計天數"),
    start_date: Optional[date] = Query(None, description="開始日期 (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="結束日期 (YYYY-MM-DD)"),
    team_ids: Optional[str] = Query(None, description="團隊 ID（逗號分隔）"),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    try:
        sd, ed, start_dt, end_dt, range_days = _resolve_date_range(days, start_date, end_date)
        parsed_team_ids = _parse_team_ids(team_ids)

        ck = _cache_key("overview", sd=sd, ed=ed, tids=parsed_team_ids)
        cached = _get_cached(ck)
        if cached is not None:
            return JSONResponse(cached)

        async def _load(sess: AsyncSession) -> Dict[str, Any]:
            conds = _session_filter(start_dt, end_dt, parsed_team_ids)

            # -- session 統計 --
            base = select(QAAIHelperSession).where(*conds)
            all_sessions = (await sess.execute(base)).scalars().all()

            total = len(all_sessions)
            completed = sum(1 for s in all_sessions if s.status == "completed")
            failed = sum(1 for s in all_sessions if s.status == "failed")

            session_ids = {s.id for s in all_sessions}
            involved_team_ids = {s.team_id for s in all_sessions}

            # -- seed sets 聚合 --
            if session_ids:
                ss_rows = (
                    await sess.execute(
                        select(
                            QAAIHelperSession.team_id,
                            func.sum(QAAIHelperSeedSet.generated_seed_count),
                            func.sum(QAAIHelperSeedSet.included_seed_count),
                        )
                        .join(QAAIHelperSession, QAAIHelperSeedSet.session_id == QAAIHelperSession.id)
                        .where(QAAIHelperSeedSet.session_id.in_(session_ids))
                        .group_by(QAAIHelperSession.team_id)
                    )
                ).all()
            else:
                ss_rows = []

            team_seed: Dict[int, Dict[str, int]] = {}
            total_gen_seed = 0
            total_inc_seed = 0
            for tid, gen, inc in ss_rows:
                g, i = int(gen or 0), int(inc or 0)
                team_seed[tid] = {"generated": g, "included": i}
                total_gen_seed += g
                total_inc_seed += i

            # -- testcase draft sets 聚合 --
            if session_ids:
                td_rows = (
                    await sess.execute(
                        select(
                            QAAIHelperSession.team_id,
                            func.sum(QAAIHelperTestcaseDraftSet.generated_testcase_count),
                            func.sum(QAAIHelperTestcaseDraftSet.selected_for_commit_count),
                        )
                        .join(QAAIHelperSession, QAAIHelperTestcaseDraftSet.session_id == QAAIHelperSession.id)
                        .where(QAAIHelperTestcaseDraftSet.session_id.in_(session_ids))
                        .group_by(QAAIHelperSession.team_id)
                    )
                ).all()
            else:
                td_rows = []

            team_tc: Dict[int, Dict[str, int]] = {}
            total_gen_tc = 0
            total_sel_tc = 0
            for tid, gen, sel in td_rows:
                g, s = int(gen or 0), int(sel or 0)
                team_tc[tid] = {"generated": g, "selected": s}
                total_gen_tc += g
                total_sel_tc += s

            # -- commit links 聚合 --
            if session_ids:
                cl_rows = (
                    await sess.execute(
                        select(
                            QAAIHelperSession.team_id,
                            func.count(QAAIHelperCommitLink.id),
                        )
                        .join(QAAIHelperSession, QAAIHelperCommitLink.session_id == QAAIHelperSession.id)
                        .where(QAAIHelperCommitLink.session_id.in_(session_ids))
                        .group_by(QAAIHelperSession.team_id)
                    )
                ).all()
            else:
                cl_rows = []

            team_committed: Dict[int, int] = {}
            total_committed = 0
            for tid, cnt in cl_rows:
                c = int(cnt or 0)
                team_committed[tid] = c
                total_committed += c

            # -- 團隊名稱 --
            team_names = await _load_team_names(sess, involved_team_ids)

            # -- 團隊排行 session 計數 --
            team_session_counts: Dict[int, Dict[str, int]] = defaultdict(lambda: {"total": 0, "completed": 0})
            for s in all_sessions:
                team_session_counts[s.team_id]["total"] += 1
                if s.status == "completed":
                    team_session_counts[s.team_id]["completed"] += 1

            team_ranking = []
            for tid in sorted(involved_team_ids):
                sc = team_session_counts[tid]
                sd_data = team_seed.get(tid, {"generated": 0, "included": 0})
                td_data = team_tc.get(tid, {"generated": 0, "selected": 0})
                committed_count = team_committed.get(tid, 0)
                team_ranking.append(
                    {
                        "team_id": tid,
                        "team_name": team_names.get(tid, f"Team #{tid}"),
                        "session_count": sc["total"],
                        "completed_session_count": sc["completed"],
                        "completion_rate": _safe_adoption(sc["completed"], sc["total"]),
                        "generated_seed_count": sd_data["generated"],
                        "included_seed_count": sd_data["included"],
                        "seed_adoption_rate": _safe_adoption(sd_data["included"], sd_data["generated"]),
                        "generated_tc_count": td_data["generated"],
                        "selected_tc_count": td_data["selected"],
                        "tc_adoption_rate": _safe_adoption(td_data["selected"], td_data["generated"]),
                        "committed_tc_count": committed_count,
                    }
                )

            # 按 committed_tc_count 降序
            team_ranking.sort(key=lambda x: x["committed_tc_count"], reverse=True)

            return {
                "kpi": {
                    "total_sessions": total,
                    "completed_sessions": completed,
                    "completion_rate": _safe_adoption(completed, total),
                    "failed_sessions": failed,
                    "total_seeds_generated": total_gen_seed,
                    "total_tcs_generated": total_gen_tc,
                    "total_tcs_committed": total_committed,
                    "overall_seed_adoption_rate": _safe_adoption(total_inc_seed, total_gen_seed),
                    "overall_tc_adoption_rate": _safe_adoption(total_sel_tc, total_gen_tc),
                },
                "team_ranking": team_ranking,
                "date_range": _date_range_payload(sd, ed, range_days),
            }

        payload = await main_boundary.run_read(_load)
        _set_cached(ck, payload)
        return JSONResponse(payload)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("QA AI Helper overview 統計失敗: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "無法載入 QA AI Helper 總覽統計"})


# ===========================================================================
# 端點 2: GET /adoption
# ===========================================================================
@router.get("/adoption", include_in_schema=False)
async def get_qa_ai_helper_adoption(
    current_user: User = Depends(require_admin()),
    days: int = Query(30, ge=1, le=MAX_STAT_RANGE_DAYS, description="統計天數"),
    start_date: Optional[date] = Query(None, description="開始日期 (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="結束日期 (YYYY-MM-DD)"),
    team_ids: Optional[str] = Query(None, description="團隊 ID（逗號分隔）"),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    try:
        sd, ed, start_dt, end_dt, range_days = _resolve_date_range(days, start_date, end_date)
        parsed_team_ids = _parse_team_ids(team_ids)

        ck = _cache_key("adoption", sd=sd, ed=ed, tids=parsed_team_ids)
        cached = _get_cached(ck)
        if cached is not None:
            return JSONResponse(cached)

        date_labels = _build_date_labels(date.fromisoformat(sd), date.fromisoformat(ed))

        async def _load(sess: AsyncSession) -> Dict[str, Any]:
            conds = _session_filter(start_dt, end_dt, parsed_team_ids)
            all_sessions = (await sess.execute(select(QAAIHelperSession).where(*conds))).scalars().all()

            session_ids = {s.id for s in all_sessions}
            involved_team_ids = {s.team_id for s in all_sessions}
            session_team_map = {s.id: s.team_id for s in all_sessions}
            session_user_map = {s.id: s.created_by_user_id for s in all_sessions}

            if not session_ids:
                return _empty_adoption(date_labels, sd, ed, range_days)

            # -- seed sets (set 級別) --
            ss_rows = (
                (await sess.execute(select(QAAIHelperSeedSet).where(QAAIHelperSeedSet.session_id.in_(session_ids))))
                .scalars()
                .all()
            )

            # -- testcase draft sets (set 級別) --
            td_rows = (
                (
                    await sess.execute(
                        select(QAAIHelperTestcaseDraftSet).where(QAAIHelperTestcaseDraftSet.session_id.in_(session_ids))
                    )
                )
                .scalars()
                .all()
            )

            # -- seed items (item 級別，用於 edit rate / ai ratio) --
            si_rows = (
                await sess.execute(
                    select(
                        QAAIHelperSeedItem.is_ai_generated,
                        QAAIHelperSeedItem.user_edited,
                    )
                    .join(QAAIHelperSeedSet, QAAIHelperSeedItem.seed_set_id == QAAIHelperSeedSet.id)
                    .where(QAAIHelperSeedSet.session_id.in_(session_ids))
                )
            ).all()

            # -- testcase drafts (item 級別) --
            tcd_rows = (
                await sess.execute(
                    select(
                        QAAIHelperTestcaseDraft.is_ai_generated,
                        QAAIHelperTestcaseDraft.user_edited,
                    )
                    .join(
                        QAAIHelperTestcaseDraftSet,
                        QAAIHelperTestcaseDraft.testcase_draft_set_id == QAAIHelperTestcaseDraftSet.id,
                    )
                    .where(QAAIHelperTestcaseDraftSet.session_id.in_(session_ids))
                )
            ).all()

            # ---- overall ----
            total_gen_seed = sum(s.generated_seed_count or 0 for s in ss_rows)
            total_inc_seed = sum(s.included_seed_count or 0 for s in ss_rows)
            total_gen_tc = sum(t.generated_testcase_count or 0 for t in td_rows)
            total_sel_tc = sum(t.selected_for_commit_count or 0 for t in td_rows)

            all_items = list(si_rows) + list(tcd_rows)
            total_items = len(all_items)
            ai_count = sum(1 for r in all_items if r[0])
            edited_count = sum(1 for r in all_items if r[1])

            overall = {
                "seed_adoption_rate": _safe_adoption(total_inc_seed, total_gen_seed),
                "tc_adoption_rate": _safe_adoption(total_sel_tc, total_gen_tc),
                "user_edit_rate": _safe_adoption(edited_count, total_items),
                "ai_generated_ratio": _safe_adoption(ai_count, total_items),
            }

            # ---- overall trend (按日) ----
            date_seed_gen: Dict[str, int] = defaultdict(int)
            date_seed_inc: Dict[str, int] = defaultdict(int)
            date_tc_gen: Dict[str, int] = defaultdict(int)
            date_tc_sel: Dict[str, int] = defaultdict(int)

            for ss in ss_rows:
                d = ss.created_at.date().isoformat() if ss.created_at else None
                if d:
                    date_seed_gen[d] += ss.generated_seed_count or 0
                    date_seed_inc[d] += ss.included_seed_count or 0

            for td in td_rows:
                d = td.created_at.date().isoformat() if td.created_at else None
                if d:
                    date_tc_gen[d] += td.generated_testcase_count or 0
                    date_tc_sel[d] += td.selected_for_commit_count or 0

            overall_trend = {
                "dates": date_labels,
                "seed_adoption": [
                    _safe_adoption(date_seed_inc.get(d, 0), date_seed_gen.get(d, 0)) for d in date_labels
                ],
                "tc_adoption": [_safe_adoption(date_tc_sel.get(d, 0), date_tc_gen.get(d, 0)) for d in date_labels],
            }

            # ---- by team ----
            team_ss: Dict[int, List] = defaultdict(list)
            for ss in ss_rows:
                tid = session_team_map.get(ss.session_id)
                if tid is not None:
                    team_ss[tid].append(ss)

            team_td: Dict[int, List] = defaultdict(list)
            for td in td_rows:
                tid = session_team_map.get(td.session_id)
                if tid is not None:
                    team_td[tid].append(td)

            team_names = await _load_team_names(sess, involved_team_ids)

            team_ranking_list: List[Dict[str, Any]] = []
            by_team_trend: List[Dict[str, Any]] = []

            for tid in sorted(involved_team_ids):
                t_ss = team_ss.get(tid, [])
                t_td = team_td.get(tid, [])
                g_seed = sum(s.generated_seed_count or 0 for s in t_ss)
                i_seed = sum(s.included_seed_count or 0 for s in t_ss)
                g_tc = sum(t.generated_testcase_count or 0 for t in t_td)
                s_tc = sum(t.selected_for_commit_count or 0 for t in t_td)
                sample = len({s.session_id for s in t_ss} | {t.session_id for t in t_td})

                entry = {
                    "team_id": tid,
                    "team_name": team_names.get(tid, f"Team #{tid}"),
                    "seed_adoption_rate": _safe_adoption(i_seed, g_seed),
                    "tc_adoption_rate": _safe_adoption(s_tc, g_tc),
                    "generated_seed_count": g_seed,
                    "generated_tc_count": g_tc,
                    "sample_count": sample,
                }
                team_ranking_list.append(entry)

                # team trend
                t_date_sg: Dict[str, int] = defaultdict(int)
                t_date_si: Dict[str, int] = defaultdict(int)
                t_date_tg: Dict[str, int] = defaultdict(int)
                t_date_ts: Dict[str, int] = defaultdict(int)
                for ss in t_ss:
                    d = ss.created_at.date().isoformat() if ss.created_at else None
                    if d:
                        t_date_sg[d] += ss.generated_seed_count or 0
                        t_date_si[d] += ss.included_seed_count or 0
                for td in t_td:
                    d = td.created_at.date().isoformat() if td.created_at else None
                    if d:
                        t_date_tg[d] += td.generated_testcase_count or 0
                        t_date_ts[d] += td.selected_for_commit_count or 0

                by_team_trend.append(
                    {
                        "team_id": tid,
                        "team_name": team_names.get(tid, f"Team #{tid}"),
                        "seed_adoption_rate": entry["seed_adoption_rate"],
                        "tc_adoption_rate": entry["tc_adoption_rate"],
                        "trend": {
                            "dates": date_labels,
                            "seed_adoption": [
                                _safe_adoption(t_date_si.get(d, 0), t_date_sg.get(d, 0)) for d in date_labels
                            ],
                            "tc_adoption": [
                                _safe_adoption(t_date_ts.get(d, 0), t_date_tg.get(d, 0)) for d in date_labels
                            ],
                        },
                    }
                )

            # 排名按 tc_adoption_rate 降序
            team_ranking_list.sort(key=lambda x: x["tc_adoption_rate"], reverse=True)
            # trend 只取 Top 10 (按 sample_count 降序選最活躍的)
            by_team_trend.sort(key=lambda x: x.get("tc_adoption_rate", 0), reverse=True)
            by_team_trend_top10 = by_team_trend[:10]

            # ---- user ranking (Top 20) ----
            user_ss: Dict[int, List] = defaultdict(list)
            for ss in ss_rows:
                uid = session_user_map.get(ss.session_id)
                if uid is not None:
                    user_ss[uid].append(ss)

            user_td: Dict[int, List] = defaultdict(list)
            for td in td_rows:
                uid = session_user_map.get(td.session_id)
                if uid is not None:
                    user_td[uid].append(td)

            all_user_ids = set(user_ss.keys()) | set(user_td.keys())
            user_names = await _load_user_names(sess, all_user_ids) if all_user_ids else {}
            # user -> team 映射（取最常用的 team）
            user_team: Dict[int, int] = {}
            for s in all_sessions:
                if s.created_by_user_id is not None:
                    user_team.setdefault(s.created_by_user_id, s.team_id)

            user_ranking: List[Dict[str, Any]] = []
            for uid in all_user_ids:
                u_ss = user_ss.get(uid, [])
                u_td = user_td.get(uid, [])
                g_seed = sum(s.generated_seed_count or 0 for s in u_ss)
                i_seed = sum(s.included_seed_count or 0 for s in u_ss)
                g_tc = sum(t.generated_testcase_count or 0 for t in u_td)
                s_tc = sum(t.selected_for_commit_count or 0 for t in u_td)
                session_count = len({s.session_id for s in u_ss} | {t.session_id for t in u_td})
                tid = user_team.get(uid, 0)
                user_ranking.append(
                    {
                        "user_id": uid,
                        "username": user_names.get(uid, f"user#{uid}"),
                        "team_name": team_names.get(tid, f"Team #{tid}"),
                        "seed_adoption_rate": _safe_adoption(i_seed, g_seed),
                        "tc_adoption_rate": _safe_adoption(s_tc, g_tc),
                        "session_count": session_count,
                    }
                )
            user_ranking.sort(key=lambda x: x["tc_adoption_rate"], reverse=True)
            user_ranking = user_ranking[:20]

            return {
                "overall": overall,
                "overall_trend": overall_trend,
                "by_team_trend": by_team_trend_top10,
                "team_ranking": team_ranking_list,
                "user_ranking": user_ranking,
                "date_range": _date_range_payload(sd, ed, range_days),
            }

        payload = await main_boundary.run_read(_load)
        _set_cached(ck, payload)
        return JSONResponse(payload)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("QA AI Helper adoption 統計失敗: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "無法載入 QA AI Helper 採用率統計"})


def _empty_adoption(date_labels: List[str], sd: str, ed: str, range_days: int) -> Dict[str, Any]:
    return {
        "overall": {
            "seed_adoption_rate": 0.0,
            "tc_adoption_rate": 0.0,
            "user_edit_rate": 0.0,
            "ai_generated_ratio": 0.0,
        },
        "overall_trend": {
            "dates": date_labels,
            "seed_adoption": [0.0] * len(date_labels),
            "tc_adoption": [0.0] * len(date_labels),
        },
        "by_team_trend": [],
        "team_ranking": [],
        "user_ranking": [],
        "date_range": _date_range_payload(sd, ed, range_days),
    }


# ===========================================================================
# 端點 3: GET /generation
# ===========================================================================
@router.get("/generation", include_in_schema=False)
async def get_qa_ai_helper_generation(
    current_user: User = Depends(require_admin()),
    days: int = Query(30, ge=1, le=MAX_STAT_RANGE_DAYS, description="統計天數"),
    start_date: Optional[date] = Query(None, description="開始日期 (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="結束日期 (YYYY-MM-DD)"),
    team_ids: Optional[str] = Query(None, description="團隊 ID（逗號分隔）"),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    try:
        sd, ed, start_dt, end_dt, range_days = _resolve_date_range(days, start_date, end_date)
        parsed_team_ids = _parse_team_ids(team_ids)

        ck = _cache_key("generation", sd=sd, ed=ed, tids=parsed_team_ids)
        cached = _get_cached(ck)
        if cached is not None:
            return JSONResponse(cached)

        date_labels = _build_date_labels(date.fromisoformat(sd), date.fromisoformat(ed))

        async def _load(sess: AsyncSession) -> Dict[str, Any]:
            conds = _session_filter(start_dt, end_dt, parsed_team_ids)
            all_sessions = (await sess.execute(select(QAAIHelperSession).where(*conds))).scalars().all()

            session_ids = {s.id for s in all_sessions}
            involved_team_ids = {s.team_id for s in all_sessions}
            session_team_map = {s.id: s.team_id for s in all_sessions}
            session_user_map = {s.id: s.created_by_user_id for s in all_sessions}

            if not session_ids:
                return _empty_generation(date_labels, sd, ed, range_days)

            # -- seed sets --
            ss_rows = (
                (await sess.execute(select(QAAIHelperSeedSet).where(QAAIHelperSeedSet.session_id.in_(session_ids))))
                .scalars()
                .all()
            )

            # -- testcase draft sets --
            td_rows = (
                (
                    await sess.execute(
                        select(QAAIHelperTestcaseDraftSet).where(QAAIHelperTestcaseDraftSet.session_id.in_(session_ids))
                    )
                )
                .scalars()
                .all()
            )

            # -- commit links --
            cl_rows = (
                (
                    await sess.execute(
                        select(QAAIHelperCommitLink).where(QAAIHelperCommitLink.session_id.in_(session_ids))
                    )
                )
                .scalars()
                .all()
            )

            # -- seed items (coverage tags) --
            seed_set_ids = {s.id for s in ss_rows}
            if seed_set_ids:
                si_rows = (
                    await sess.execute(
                        select(
                            QAAIHelperSeedItem.coverage_tags_json,
                        ).where(QAAIHelperSeedItem.seed_set_id.in_(seed_set_ids))
                    )
                ).all()
            else:
                si_rows = []

            # ---- overall trend ----
            d_seeds: Dict[str, int] = defaultdict(int)
            d_tcs: Dict[str, int] = defaultdict(int)
            d_committed: Dict[str, int] = defaultdict(int)

            for ss in ss_rows:
                d = ss.created_at.date().isoformat() if ss.created_at else None
                if d:
                    d_seeds[d] += ss.generated_seed_count or 0
            for td in td_rows:
                d = td.created_at.date().isoformat() if td.created_at else None
                if d:
                    d_tcs[d] += td.generated_testcase_count or 0
            for cl in cl_rows:
                d = cl.committed_at.date().isoformat() if cl.committed_at else None
                if d:
                    d_committed[d] += 1

            overall_trend = {
                "dates": date_labels,
                "seeds_generated": [d_seeds.get(d, 0) for d in date_labels],
                "tcs_generated": [d_tcs.get(d, 0) for d in date_labels],
                "tcs_committed": [d_committed.get(d, 0) for d in date_labels],
            }

            # ---- overall summary ----
            total_seeds = sum(s.generated_seed_count or 0 for s in ss_rows)
            total_tcs = sum(t.generated_testcase_count or 0 for t in td_rows)
            total_committed = len(cl_rows)
            session_count = len(session_ids)

            # refine round distribution
            round_dist: Dict[int, int] = defaultdict(int)
            for ss in ss_rows:
                round_dist[ss.generation_round or 1] += 1

            # coverage tags
            tag_dist: Dict[str, int] = defaultdict(int)
            for (tags_json,) in si_rows:
                if tags_json:
                    try:
                        tags = json.loads(tags_json) if isinstance(tags_json, str) else tags_json
                        if isinstance(tags, list):
                            for tag in tags:
                                tag_dist[str(tag)] += 1
                    except (json.JSONDecodeError, TypeError):
                        pass

            overall_summary = {
                "total_seeds": total_seeds,
                "total_tcs_generated": total_tcs,
                "total_tcs_committed": total_committed,
                "avg_seeds_per_session": round(total_seeds / session_count, 2) if session_count else 0,
                "avg_tcs_per_session": round(total_tcs / session_count, 2) if session_count else 0,
                "refine_round_distribution": dict(sorted(round_dist.items())),
                "coverage_tag_distribution": dict(sorted(tag_dist.items(), key=lambda x: x[1], reverse=True)),
            }

            # ---- by team ----
            team_names = await _load_team_names(sess, involved_team_ids)

            # 團隊聚合
            team_ss_map: Dict[int, List] = defaultdict(list)
            for ss in ss_rows:
                tid = session_team_map.get(ss.session_id)
                if tid is not None:
                    team_ss_map[tid].append(ss)

            team_td_map: Dict[int, List] = defaultdict(list)
            for td in td_rows:
                tid = session_team_map.get(td.session_id)
                if tid is not None:
                    team_td_map[tid].append(td)

            team_cl_map: Dict[int, int] = defaultdict(int)
            for cl in cl_rows:
                tid = session_team_map.get(cl.session_id)
                if tid is not None:
                    team_cl_map[tid] += 1

            team_session_count: Dict[int, int] = defaultdict(int)
            for s in all_sessions:
                team_session_count[s.team_id] += 1

            team_ranking: List[Dict[str, Any]] = []
            by_team_trend: List[Dict[str, Any]] = []

            for tid in sorted(involved_team_ids):
                t_ss = team_ss_map.get(tid, [])
                t_td = team_td_map.get(tid, [])
                seeds = sum(s.generated_seed_count or 0 for s in t_ss)
                tcs = sum(t.generated_testcase_count or 0 for t in t_td)
                committed = team_cl_map.get(tid, 0)
                sess_cnt = team_session_count.get(tid, 0)

                team_ranking.append(
                    {
                        "team_id": tid,
                        "team_name": team_names.get(tid, f"Team #{tid}"),
                        "seeds_generated": seeds,
                        "tcs_generated": tcs,
                        "tcs_committed": committed,
                        "session_count": sess_cnt,
                        "avg_per_session": round(tcs / sess_cnt, 2) if sess_cnt else 0,
                    }
                )

                # team trend
                td_seeds: Dict[str, int] = defaultdict(int)
                td_tcs: Dict[str, int] = defaultdict(int)
                td_committed_d: Dict[str, int] = defaultdict(int)
                for ss in t_ss:
                    d = ss.created_at.date().isoformat() if ss.created_at else None
                    if d:
                        td_seeds[d] += ss.generated_seed_count or 0
                for td in t_td:
                    d = td.created_at.date().isoformat() if td.created_at else None
                    if d:
                        td_tcs[d] += td.generated_testcase_count or 0
                # commit links for this team
                for cl in cl_rows:
                    if session_team_map.get(cl.session_id) == tid:
                        d = cl.committed_at.date().isoformat() if cl.committed_at else None
                        if d:
                            td_committed_d[d] += 1

                by_team_trend.append(
                    {
                        "team_id": tid,
                        "team_name": team_names.get(tid, f"Team #{tid}"),
                        "trend": {
                            "dates": date_labels,
                            "seeds": [td_seeds.get(d, 0) for d in date_labels],
                            "tcs": [td_tcs.get(d, 0) for d in date_labels],
                            "committed": [td_committed_d.get(d, 0) for d in date_labels],
                        },
                    }
                )

            team_ranking.sort(key=lambda x: x["tcs_committed"], reverse=True)
            by_team_trend.sort(
                key=lambda x: next((r["tcs_committed"] for r in team_ranking if r["team_id"] == x["team_id"]), 0),
                reverse=True,
            )
            by_team_trend = by_team_trend[:10]

            # ---- user ranking (Top 20) ----
            user_sessions: Dict[int, int] = defaultdict(int)
            for s in all_sessions:
                if s.created_by_user_id is not None:
                    user_sessions[s.created_by_user_id] += 1

            user_seeds: Dict[int, int] = defaultdict(int)
            for ss in ss_rows:
                uid = session_user_map.get(ss.session_id)
                if uid is not None:
                    user_seeds[uid] += ss.generated_seed_count or 0

            user_committed: Dict[int, int] = defaultdict(int)
            for cl in cl_rows:
                uid = session_user_map.get(cl.session_id)
                if uid is not None:
                    user_committed[uid] += 1

            all_user_ids = set(user_sessions.keys())
            user_names = await _load_user_names(sess, all_user_ids) if all_user_ids else {}
            user_team: Dict[int, int] = {}
            for s in all_sessions:
                if s.created_by_user_id is not None:
                    user_team.setdefault(s.created_by_user_id, s.team_id)

            user_ranking: List[Dict[str, Any]] = []
            for uid in all_user_ids:
                tid = user_team.get(uid, 0)
                user_ranking.append(
                    {
                        "user_id": uid,
                        "username": user_names.get(uid, f"user#{uid}"),
                        "team_name": team_names.get(tid, f"Team #{tid}"),
                        "session_count": user_sessions.get(uid, 0),
                        "seeds_generated": user_seeds.get(uid, 0),
                        "tcs_committed": user_committed.get(uid, 0),
                    }
                )
            user_ranking.sort(key=lambda x: x["tcs_committed"], reverse=True)
            user_ranking = user_ranking[:20]

            return {
                "overall_trend": overall_trend,
                "overall_summary": overall_summary,
                "by_team_trend": by_team_trend,
                "team_ranking": team_ranking,
                "user_ranking": user_ranking,
                "date_range": _date_range_payload(sd, ed, range_days),
            }

        payload = await main_boundary.run_read(_load)
        _set_cached(ck, payload)
        return JSONResponse(payload)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("QA AI Helper generation 統計失敗: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "無法載入 QA AI Helper 生成統計"})


def _empty_generation(date_labels: List[str], sd: str, ed: str, range_days: int) -> Dict[str, Any]:
    return {
        "overall_trend": {
            "dates": date_labels,
            "seeds_generated": [0] * len(date_labels),
            "tcs_generated": [0] * len(date_labels),
            "tcs_committed": [0] * len(date_labels),
        },
        "overall_summary": {
            "total_seeds": 0,
            "total_tcs_generated": 0,
            "total_tcs_committed": 0,
            "avg_seeds_per_session": 0,
            "avg_tcs_per_session": 0,
            "refine_round_distribution": {},
            "coverage_tag_distribution": {},
        },
        "by_team_trend": [],
        "team_ranking": [],
        "user_ranking": [],
        "date_range": _date_range_payload(sd, ed, range_days),
    }


# ===========================================================================
# 端點 4: GET /funnel
# ===========================================================================
@router.get("/funnel", include_in_schema=False)
async def get_qa_ai_helper_funnel(
    current_user: User = Depends(require_admin()),
    days: int = Query(30, ge=1, le=MAX_STAT_RANGE_DAYS, description="統計天數"),
    start_date: Optional[date] = Query(None, description="開始日期 (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="結束日期 (YYYY-MM-DD)"),
    team_ids: Optional[str] = Query(None, description="團隊 ID（逗號分隔）"),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    try:
        sd, ed, start_dt, end_dt, range_days = _resolve_date_range(days, start_date, end_date)
        parsed_team_ids = _parse_team_ids(team_ids)

        ck = _cache_key("funnel", sd=sd, ed=ed, tids=parsed_team_ids)
        cached = _get_cached(ck)
        if cached is not None:
            return JSONResponse(cached)

        # phase 排序用於漏斗
        PHASE_ORDER = ["intake", "planned", "generated", "validated", "committed", "failed"]

        async def _load(sess: AsyncSession) -> Dict[str, Any]:
            conds = _session_filter(start_dt, end_dt, parsed_team_ids)
            all_sessions = (await sess.execute(select(QAAIHelperSession).where(*conds))).scalars().all()

            involved_team_ids = {s.team_id for s in all_sessions}

            if not all_sessions:
                return {
                    "funnel": {p: 0 for p in PHASE_ORDER},
                    "status_distribution": {},
                    "avg_completion_time_hours": 0,
                    "by_team": [],
                    "date_range": _date_range_payload(sd, ed, range_days),
                }

            # -- 全域漏斗 --
            phase_counts: Dict[str, int] = defaultdict(int)
            status_counts: Dict[str, int] = defaultdict(int)
            completion_durations: List[float] = []

            for s in all_sessions:
                phase_counts[s.current_phase or "intake"] += 1
                status_counts[s.status or "active"] += 1
                if s.status == "completed" and s.updated_at and s.created_at:
                    delta = (s.updated_at - s.created_at).total_seconds() / 3600
                    if delta >= 0:
                        completion_durations.append(delta)

            funnel = {p: phase_counts.get(p, 0) for p in PHASE_ORDER}
            avg_hours = round(sum(completion_durations) / len(completion_durations), 2) if completion_durations else 0

            # -- by team --
            team_names = await _load_team_names(sess, involved_team_ids)
            team_sessions: Dict[int, List] = defaultdict(list)
            for s in all_sessions:
                team_sessions[s.team_id].append(s)

            by_team: List[Dict[str, Any]] = []
            for tid in sorted(involved_team_ids):
                t_sessions = team_sessions.get(tid, [])
                t_total = len(t_sessions)
                t_completed = sum(1 for s in t_sessions if s.status == "completed")
                t_failed = sum(1 for s in t_sessions if s.status == "failed")
                t_durations = []
                for s in t_sessions:
                    if s.status == "completed" and s.updated_at and s.created_at:
                        delta = (s.updated_at - s.created_at).total_seconds() / 3600
                        if delta >= 0:
                            t_durations.append(delta)

                t_phase: Dict[str, int] = defaultdict(int)
                for s in t_sessions:
                    t_phase[s.current_phase or "intake"] += 1

                by_team.append(
                    {
                        "team_id": tid,
                        "team_name": team_names.get(tid, f"Team #{tid}"),
                        "session_count": t_total,
                        "completed": t_completed,
                        "failed": t_failed,
                        "completion_rate": _safe_adoption(t_completed, t_total),
                        "avg_completion_time_hours": round(sum(t_durations) / len(t_durations), 2)
                        if t_durations
                        else 0,
                        "phase_distribution": {p: t_phase.get(p, 0) for p in PHASE_ORDER},
                    }
                )

            by_team.sort(key=lambda x: x["completion_rate"], reverse=True)

            return {
                "funnel": funnel,
                "status_distribution": dict(status_counts),
                "avg_completion_time_hours": avg_hours,
                "by_team": by_team,
                "date_range": _date_range_payload(sd, ed, range_days),
            }

        payload = await main_boundary.run_read(_load)
        _set_cached(ck, payload)
        return JSONResponse(payload)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("QA AI Helper funnel 統計失敗: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "無法載入 QA AI Helper 漏斗統計"})


# ===========================================================================
# 端點 5: GET /telemetry
# ===========================================================================
@router.get("/telemetry", include_in_schema=False)
async def get_qa_ai_helper_telemetry(
    current_user: User = Depends(require_admin()),
    days: int = Query(30, ge=1, le=MAX_STAT_RANGE_DAYS, description="統計天數"),
    start_date: Optional[date] = Query(None, description="開始日期 (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="結束日期 (YYYY-MM-DD)"),
    team_ids: Optional[str] = Query(None, description="團隊 ID（逗號分隔）"),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    try:
        sd, ed, start_dt, end_dt, range_days = _resolve_date_range(days, start_date, end_date)
        parsed_team_ids = _parse_team_ids(team_ids)

        ck = _cache_key("telemetry", sd=sd, ed=ed, tids=parsed_team_ids)
        cached = _get_cached(ck)
        if cached is not None:
            return JSONResponse(cached)

        date_labels = _build_date_labels(date.fromisoformat(sd), date.fromisoformat(ed))

        async def _load(sess: AsyncSession) -> Dict[str, Any]:
            # telemetry_events 有直接 team_id，不需 JOIN sessions
            tel_conds = [
                QAAIHelperTelemetryEvent.created_at >= start_dt,
                QAAIHelperTelemetryEvent.created_at <= end_dt,
            ]
            if parsed_team_ids:
                tel_conds.append(QAAIHelperTelemetryEvent.team_id.in_(parsed_team_ids))

            all_events = (await sess.execute(select(QAAIHelperTelemetryEvent).where(*tel_conds))).scalars().all()

            if not all_events:
                return _empty_telemetry(date_labels, sd, ed, range_days)

            involved_team_ids = {e.team_id for e in all_events}

            # ---- overall ----
            total_calls = len(all_events)
            total_prompt = sum(e.prompt_tokens or 0 for e in all_events)
            total_completion = sum(e.completion_tokens or 0 for e in all_events)
            total_tokens = sum(e.total_tokens or 0 for e in all_events)
            durations = [e.duration_ms or 0 for e in all_events if (e.duration_ms or 0) > 0]
            error_count = sum(1 for e in all_events if e.status != "success")

            overall = {
                "total_calls": total_calls,
                "total_prompt_tokens": total_prompt,
                "total_completion_tokens": total_completion,
                "total_tokens": total_tokens,
                "avg_duration_ms": round(sum(durations) / len(durations)) if durations else 0,
                "p95_duration_ms": _p95(durations),
                "error_count": error_count,
                "error_rate": _safe_adoption(error_count, total_calls),
            }

            # ---- token trend ----
            d_prompt: Dict[str, int] = defaultdict(int)
            d_completion: Dict[str, int] = defaultdict(int)
            d_calls: Dict[str, int] = defaultdict(int)

            for e in all_events:
                d = e.created_at.date().isoformat() if e.created_at else None
                if d:
                    d_prompt[d] += e.prompt_tokens or 0
                    d_completion[d] += e.completion_tokens or 0
                    d_calls[d] += 1

            token_trend = {
                "dates": date_labels,
                "prompt_tokens": [d_prompt.get(d, 0) for d in date_labels],
                "completion_tokens": [d_completion.get(d, 0) for d in date_labels],
                "call_count": [d_calls.get(d, 0) for d in date_labels],
            }

            # ---- by model ----
            by_model: Dict[str, Dict[str, int]] = defaultdict(lambda: {"calls": 0, "tokens": 0})
            for e in all_events:
                model = e.model_name or "unknown"
                by_model[model]["calls"] += 1
                by_model[model]["tokens"] += e.total_tokens or 0

            # ---- by stage ----
            stage_data: Dict[str, Dict[str, Any]] = defaultdict(
                lambda: {
                    "calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "tokens": 0,
                    "durations": [],
                    "errors": 0,
                }
            )
            for e in all_events:
                stage = e.stage or "unknown"
                stage_data[stage]["calls"] += 1
                stage_data[stage]["prompt_tokens"] += e.prompt_tokens or 0
                stage_data[stage]["completion_tokens"] += e.completion_tokens or 0
                stage_data[stage]["tokens"] += e.total_tokens or 0
                if (e.duration_ms or 0) > 0:
                    stage_data[stage]["durations"].append(e.duration_ms)
                if e.status != "success":
                    stage_data[stage]["errors"] += 1

            by_stage: Dict[str, Dict[str, Any]] = {}
            for stage, data in stage_data.items():
                dur = data["durations"]
                by_stage[stage] = {
                    "calls": data["calls"],
                    "prompt_tokens": data["prompt_tokens"],
                    "completion_tokens": data["completion_tokens"],
                    "tokens": data["tokens"],
                    "avg_ms": round(sum(dur) / len(dur)) if dur else 0,
                    "p95_ms": _p95(dur),
                    "error_rate": _safe_adoption(data["errors"], data["calls"]),
                }

            # ---- team ranking ----
            team_names = await _load_team_names(sess, involved_team_ids)
            team_events: Dict[int, List] = defaultdict(list)
            for e in all_events:
                team_events[e.team_id].append(e)

            team_ranking: List[Dict[str, Any]] = []
            by_team_trend: List[Dict[str, Any]] = []

            for tid in sorted(involved_team_ids):
                t_events = team_events.get(tid, [])
                t_prompt = sum(e.prompt_tokens or 0 for e in t_events)
                t_completion = sum(e.completion_tokens or 0 for e in t_events)
                t_tokens = sum(e.total_tokens or 0 for e in t_events)
                t_durations = [e.duration_ms or 0 for e in t_events if (e.duration_ms or 0) > 0]

                team_ranking.append(
                    {
                        "team_id": tid,
                        "team_name": team_names.get(tid, f"Team #{tid}"),
                        "total_calls": len(t_events),
                        "prompt_tokens": t_prompt,
                        "completion_tokens": t_completion,
                        "total_tokens": t_tokens,
                        "avg_duration_ms": round(sum(t_durations) / len(t_durations)) if t_durations else 0,
                    }
                )

                # team trend
                td_tokens: Dict[str, int] = defaultdict(int)
                td_calls: Dict[str, int] = defaultdict(int)
                for e in t_events:
                    d = e.created_at.date().isoformat() if e.created_at else None
                    if d:
                        td_tokens[d] += e.total_tokens or 0
                        td_calls[d] += 1

                by_team_trend.append(
                    {
                        "team_id": tid,
                        "team_name": team_names.get(tid, f"Team #{tid}"),
                        "trend": {
                            "dates": date_labels,
                            "tokens": [td_tokens.get(d, 0) for d in date_labels],
                            "calls": [td_calls.get(d, 0) for d in date_labels],
                        },
                    }
                )

            team_ranking.sort(key=lambda x: x["total_tokens"], reverse=True)
            by_team_trend.sort(
                key=lambda x: next((r["total_tokens"] for r in team_ranking if r["team_id"] == x["team_id"]), 0),
                reverse=True,
            )
            by_team_trend = by_team_trend[:10]

            return {
                "overall": overall,
                "token_trend": token_trend,
                "by_model": dict(by_model),
                "by_stage": by_stage,
                "team_ranking": team_ranking,
                "by_team_trend": by_team_trend,
                "date_range": _date_range_payload(sd, ed, range_days),
            }

        payload = await main_boundary.run_read(_load)
        _set_cached(ck, payload)
        return JSONResponse(payload)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("QA AI Helper telemetry 統計失敗: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "無法載入 QA AI Helper 遙測統計"})


def _empty_telemetry(date_labels: List[str], sd: str, ed: str, range_days: int) -> Dict[str, Any]:
    return {
        "overall": {
            "total_calls": 0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_tokens": 0,
            "avg_duration_ms": 0,
            "p95_duration_ms": 0,
            "error_count": 0,
            "error_rate": 0.0,
        },
        "token_trend": {
            "dates": date_labels,
            "prompt_tokens": [0] * len(date_labels),
            "completion_tokens": [0] * len(date_labels),
            "call_count": [0] * len(date_labels),
        },
        "by_model": {},
        "by_stage": {},
        "team_ranking": [],
        "by_team_trend": [],
        "date_range": _date_range_payload(sd, ed, range_days),
    }


# ===========================================================================
# 端點 6: GET /user-engagement
# ===========================================================================
@router.get("/user-engagement", include_in_schema=False)
async def get_qa_ai_helper_user_engagement(
    current_user: User = Depends(require_admin()),
    days: int = Query(30, ge=1, le=MAX_STAT_RANGE_DAYS, description="統計天數"),
    start_date: Optional[date] = Query(None, description="開始日期 (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="結束日期 (YYYY-MM-DD)"),
    team_ids: Optional[str] = Query(None, description="團隊 ID（逗號分隔）"),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    try:
        sd, ed, start_dt, end_dt, range_days = _resolve_date_range(days, start_date, end_date)
        parsed_team_ids = _parse_team_ids(team_ids)

        ck = _cache_key("user_engagement", sd=sd, ed=ed, tids=parsed_team_ids)
        cached = _get_cached(ck)
        if cached is not None:
            return JSONResponse(cached)

        date_labels = _build_date_labels(date.fromisoformat(sd), date.fromisoformat(ed))

        async def _load(sess: AsyncSession) -> Dict[str, Any]:
            conds = _session_filter(start_dt, end_dt, parsed_team_ids)
            all_sessions = (await sess.execute(select(QAAIHelperSession).where(*conds))).scalars().all()

            session_ids = {s.id for s in all_sessions}
            involved_team_ids = {s.team_id for s in all_sessions}
            session_team_map = {s.id: s.team_id for s in all_sessions}

            if not all_sessions:
                return {
                    "team_ranking": [],
                    "user_ranking": [],
                    "dau_trend": {"dates": date_labels, "overall": [0] * len(date_labels), "by_team": []},
                    "date_range": _date_range_payload(sd, ed, range_days),
                }

            # -- commit links --
            if session_ids:
                cl_rows = (
                    (
                        await sess.execute(
                            select(QAAIHelperCommitLink).where(QAAIHelperCommitLink.session_id.in_(session_ids))
                        )
                    )
                    .scalars()
                    .all()
                )
            else:
                cl_rows = []

            # -- seed sets + testcase draft sets for adoption --
            if session_ids:
                ss_rows = (
                    (await sess.execute(select(QAAIHelperSeedSet).where(QAAIHelperSeedSet.session_id.in_(session_ids))))
                    .scalars()
                    .all()
                )
                td_rows = (
                    (
                        await sess.execute(
                            select(QAAIHelperTestcaseDraftSet).where(
                                QAAIHelperTestcaseDraftSet.session_id.in_(session_ids)
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            else:
                ss_rows = []
                td_rows = []

            team_names = await _load_team_names(sess, involved_team_ids)

            # ---- team ranking ----
            team_users: Dict[int, set] = defaultdict(set)
            team_sessions: Dict[int, int] = defaultdict(int)
            team_committed: Dict[int, int] = defaultdict(int)

            for s in all_sessions:
                team_sessions[s.team_id] += 1
                if s.created_by_user_id is not None:
                    team_users[s.team_id].add(s.created_by_user_id)
            for cl in cl_rows:
                tid = session_team_map.get(cl.session_id)
                if tid is not None:
                    team_committed[tid] += 1

            team_ranking: List[Dict[str, Any]] = []
            for tid in sorted(involved_team_ids):
                team_ranking.append(
                    {
                        "team_id": tid,
                        "team_name": team_names.get(tid, f"Team #{tid}"),
                        "active_user_count": len(team_users.get(tid, set())),
                        "session_count": team_sessions.get(tid, 0),
                        "committed_tc_count": team_committed.get(tid, 0),
                    }
                )
            team_ranking.sort(key=lambda x: x["committed_tc_count"], reverse=True)

            # ---- user ranking (Top 20 with adoption) ----
            user_sessions_cnt: Dict[int, int] = defaultdict(int)
            user_committed_cnt: Dict[int, int] = defaultdict(int)
            user_team_map: Dict[int, int] = {}

            for s in all_sessions:
                uid = s.created_by_user_id
                if uid is not None:
                    user_sessions_cnt[uid] += 1
                    user_team_map.setdefault(uid, s.team_id)
            for cl in cl_rows:
                uid_sess = next((s for s in all_sessions if s.id == cl.session_id), None)
                if uid_sess and uid_sess.created_by_user_id is not None:
                    user_committed_cnt[uid_sess.created_by_user_id] += 1

            # user adoption
            session_user_map = {s.id: s.created_by_user_id for s in all_sessions}
            user_seed_gen: Dict[int, int] = defaultdict(int)
            user_seed_inc: Dict[int, int] = defaultdict(int)
            user_tc_gen: Dict[int, int] = defaultdict(int)
            user_tc_sel: Dict[int, int] = defaultdict(int)

            for ss in ss_rows:
                uid = session_user_map.get(ss.session_id)
                if uid is not None:
                    user_seed_gen[uid] += ss.generated_seed_count or 0
                    user_seed_inc[uid] += ss.included_seed_count or 0
            for td in td_rows:
                uid = session_user_map.get(td.session_id)
                if uid is not None:
                    user_tc_gen[uid] += td.generated_testcase_count or 0
                    user_tc_sel[uid] += td.selected_for_commit_count or 0

            all_user_ids = set(user_sessions_cnt.keys())
            user_names = await _load_user_names(sess, all_user_ids) if all_user_ids else {}

            user_ranking: List[Dict[str, Any]] = []
            for uid in all_user_ids:
                tid = user_team_map.get(uid, 0)
                user_ranking.append(
                    {
                        "user_id": uid,
                        "username": user_names.get(uid, f"user#{uid}"),
                        "team_name": team_names.get(tid, f"Team #{tid}"),
                        "session_count": user_sessions_cnt.get(uid, 0),
                        "committed_tc_count": user_committed_cnt.get(uid, 0),
                        "seed_adoption_rate": _safe_adoption(user_seed_inc.get(uid, 0), user_seed_gen.get(uid, 0)),
                        "tc_adoption_rate": _safe_adoption(user_tc_sel.get(uid, 0), user_tc_gen.get(uid, 0)),
                    }
                )
            user_ranking.sort(key=lambda x: x["committed_tc_count"], reverse=True)
            user_ranking = user_ranking[:20]

            # ---- DAU trend ----
            dau_overall: Dict[str, set] = defaultdict(set)
            dau_team: Dict[int, Dict[str, set]] = defaultdict(lambda: defaultdict(set))

            for s in all_sessions:
                d = s.created_at.date().isoformat() if s.created_at else None
                uid = s.created_by_user_id
                if d and uid is not None:
                    dau_overall[d].add(uid)
                    dau_team[s.team_id][d].add(uid)

            dau_by_team: List[Dict[str, Any]] = []
            # Top 10 teams by session count for trend
            top_team_ids = sorted(involved_team_ids, key=lambda t: team_sessions.get(t, 0), reverse=True)[:10]
            for tid in top_team_ids:
                dau_by_team.append(
                    {
                        "team_id": tid,
                        "team_name": team_names.get(tid, f"Team #{tid}"),
                        "daily": [len(dau_team[tid].get(d, set())) for d in date_labels],
                    }
                )

            dau_trend = {
                "dates": date_labels,
                "overall": [len(dau_overall.get(d, set())) for d in date_labels],
                "by_team": dau_by_team,
            }

            return {
                "team_ranking": team_ranking,
                "user_ranking": user_ranking,
                "dau_trend": dau_trend,
                "date_range": _date_range_payload(sd, ed, range_days),
            }

        payload = await main_boundary.run_read(_load)
        _set_cached(ck, payload)
        return JSONResponse(payload)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("QA AI Helper user-engagement 統計失敗: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "無法載入 QA AI Helper 使用者參與度統計"})


# ---------------------------------------------------------------------------
# 7) AI vs 手動撰寫比例（團隊維度）
# ---------------------------------------------------------------------------


@router.get("/ai-ratio", include_in_schema=False)
async def get_qa_ai_helper_ai_ratio(
    current_user: User = Depends(require_admin()),
    days: int = Query(30, ge=1, le=MAX_STAT_RANGE_DAYS, description="統計天數"),
    start_date: Optional[date] = Query(None, description="開始日期 (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="結束日期 (YYYY-MM-DD)"),
    team_ids: Optional[str] = Query(None, description="團隊 ID（逗號分隔）"),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    """AI vs 手動撰寫 Test Case 比例（團隊維度）。

    * **AI committed**: 透過 QA AI Helper 產生且已 committed 的 test case 數量
      （由 ``qa_ai_helper_commit_links`` 溯源）。
    * **手動 created**: 同期間在 ``test_cases`` 新建的總數減去 AI committed 數。
    * 提供 overall KPI、逐日趨勢、團隊排行、Top 10 團隊趨勢線。
    """
    try:
        sd, ed, start_dt, end_dt, range_days = _resolve_date_range(days, start_date, end_date)
        parsed_team_ids = _parse_team_ids(team_ids)

        ck = _cache_key("ai_ratio", sd=sd, ed=ed, tids=parsed_team_ids)
        cached = _get_cached(ck)
        if cached is not None:
            return JSONResponse(cached)

        date_labels = _build_date_labels(date.fromisoformat(sd), date.fromisoformat(ed))

        async def _load(sess: AsyncSession) -> Dict[str, Any]:
            # -- 1) 查詢同期間所有新建的 test_cases --
            tc_conds = [
                TestCaseLocal.created_at >= start_dt,
                TestCaseLocal.created_at < end_dt,
            ]
            if parsed_team_ids:
                tc_conds.append(TestCaseLocal.team_id.in_(parsed_team_ids))

            all_tcs = (
                await sess.execute(
                    select(
                        TestCaseLocal.id,
                        TestCaseLocal.team_id,
                        TestCaseLocal.created_at,
                    ).where(*tc_conds)
                )
            ).all()

            tc_ids = {r[0] for r in all_tcs}

            # -- 2) 查詢哪些 test_case_id 有 AI commit_link --
            ai_tc_ids: set[int] = set()
            if tc_ids:
                ai_rows = (
                    await sess.execute(
                        select(QAAIHelperCommitLink.test_case_id).where(
                            QAAIHelperCommitLink.test_case_id.in_(tc_ids),
                            QAAIHelperCommitLink.is_ai_generated.is_(True),
                        )
                    )
                ).all()
                ai_tc_ids = {r[0] for r in ai_rows}

            # -- 3) 計算 overall --
            total = len(all_tcs)
            ai_count = sum(1 for r in all_tcs if r[0] in ai_tc_ids)
            manual_count = total - ai_count

            overall = {
                "total_created": total,
                "ai_committed": ai_count,
                "manual_created": manual_count,
                "ai_ratio": round(ai_count / total, 4) if total > 0 else 0.0,
            }

            # -- 4) 逐日趨勢 (overall) --
            day_total: Dict[str, int] = defaultdict(int)
            day_ai: Dict[str, int] = defaultdict(int)
            for r in all_tcs:
                d = r[2].date().isoformat() if r[2] else None
                if d:
                    day_total[d] += 1
                    if r[0] in ai_tc_ids:
                        day_ai[d] += 1

            overall_trend = {
                "dates": date_labels,
                "total_created": [day_total.get(d, 0) for d in date_labels],
                "ai_committed": [day_ai.get(d, 0) for d in date_labels],
                "manual_created": [day_total.get(d, 0) - day_ai.get(d, 0) for d in date_labels],
                "ai_ratio": [
                    round(day_ai.get(d, 0) / day_total[d], 4) if day_total.get(d, 0) > 0 else 0.0 for d in date_labels
                ],
            }

            # -- 5) 按團隊分組 --
            team_total: Dict[int, int] = defaultdict(int)
            team_ai: Dict[int, int] = defaultdict(int)
            # 團隊逐日
            team_day_total: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
            team_day_ai: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
            involved_team_ids: set[int] = set()

            for r in all_tcs:
                tid = r[1]
                d = r[2].date().isoformat() if r[2] else None
                involved_team_ids.add(tid)
                team_total[tid] += 1
                if d:
                    team_day_total[tid][d] += 1
                if r[0] in ai_tc_ids:
                    team_ai[tid] += 1
                    if d:
                        team_day_ai[tid][d] += 1

            team_names = await _load_team_names(sess, involved_team_ids)

            # -- 6) 團隊排行（全部）--
            team_ranking: List[Dict[str, Any]] = []
            for tid in sorted(involved_team_ids):
                t_total = team_total[tid]
                t_ai = team_ai[tid]
                team_ranking.append(
                    {
                        "team_id": tid,
                        "team_name": team_names.get(tid, f"Team #{tid}"),
                        "total_created": t_total,
                        "ai_committed": t_ai,
                        "manual_created": t_total - t_ai,
                        "ai_ratio": round(t_ai / t_total, 4) if t_total > 0 else 0.0,
                    }
                )
            team_ranking.sort(key=lambda x: x["ai_ratio"], reverse=True)

            # -- 7) Top 10 團隊趨勢 --
            by_team_trend: List[Dict[str, Any]] = []
            for entry in team_ranking:
                tid = entry["team_id"]
                by_team_trend.append(
                    {
                        "team_id": tid,
                        "team_name": entry["team_name"],
                        "ai_ratio": entry["ai_ratio"],
                        "trend": {
                            "dates": date_labels,
                            "ai_ratio": [
                                round(team_day_ai[tid].get(d, 0) / team_day_total[tid][d], 4)
                                if team_day_total[tid].get(d, 0) > 0
                                else 0.0
                                for d in date_labels
                            ],
                            "total_created": [team_day_total[tid].get(d, 0) for d in date_labels],
                            "ai_committed": [team_day_ai[tid].get(d, 0) for d in date_labels],
                        },
                    }
                )
            by_team_trend_top10 = by_team_trend[:10]

            return {
                "overall": overall,
                "overall_trend": overall_trend,
                "team_ranking": team_ranking,
                "by_team_trend": by_team_trend_top10,
                "date_range": _date_range_payload(sd, ed, range_days),
            }

        payload = await main_boundary.run_read(_load)
        _set_cached(ck, payload)
        return JSONResponse(payload)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("QA AI Helper ai-ratio 統計失敗: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "無法載入 QA AI Helper AI 生成比例統計"})
