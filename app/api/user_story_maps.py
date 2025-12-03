"""
User Story Map API 路由
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy import select, delete, or_, and_, text, update
from sqlalchemy.orm.attributes import flag_modified
from typing import List, Optional, Union, Dict, Tuple, Set, Any
from json import JSONDecodeError
from datetime import datetime
import uuid
import logging

from app.models.user_story_map import (
    UserStoryMapCreate,
    UserStoryMapUpdate,
    UserStoryMapResponse,
    UserStoryMapNode,
    UserStoryMapEdge,
    SearchNodeResult,
    RelationCreateRequest,
    RelationDeleteRequest,
    RelationPayload,
    RelationBulkUpdateRequest,
    RelationBulkUpdateResponse,
)
from app.models.user_story_map_db import (
    get_usm_db,
    UserStoryMapDB,
    UserStoryMapNodeDB,
)
from app.auth.dependencies import get_current_user
from app.auth.models import PermissionType
from app.auth.permission_service import permission_service
from app.models.database_models import User, Team
from app.database import get_db, get_sync_db
from app.audit import audit_service, ActionType, ResourceType, AuditSeverity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/user-story-maps", tags=["user-story-maps"])


def _normalize_related_ids(related_ids):
    """將 related_ids 從舊格式（字串）轉換為新格式（物件）以支援向下相容"""
    if not related_ids:
        return []

    normalized = []
    for rel in related_ids:
        if isinstance(rel, str):
            normalized.append(rel)
            continue

        if hasattr(rel, "dict"):
            rel = rel.dict()

        if isinstance(rel, dict):
            relation_id = rel.get("relation_id") or rel.get("relationId")
            node_id = rel.get("node_id") or rel.get("nodeId")
            map_id = rel.get("map_id") if "map_id" in rel else rel.get("mapId")
            team_id = rel.get("team_id") if "team_id" in rel else rel.get("teamId")
            map_name = rel.get("map_name") or rel.get("mapName") or ""
            team_name = rel.get("team_name") or rel.get("teamName") or ""
            display_title = (
                rel.get("display_title")
                or rel.get("displayTitle")
                or rel.get("node_title")
                or rel.get("nodeTitle")
                or node_id
                or ""
            )

            try:
                map_id_val = int(map_id) if map_id is not None and str(map_id).isdigit() else map_id
            except Exception:
                map_id_val = map_id

            try:
                team_id_val = int(team_id) if team_id is not None and str(team_id).isdigit() else team_id
            except Exception:
                team_id_val = team_id

            normalized.append({
                "relation_id": relation_id or f"legacy-{node_id or ''}",
                "node_id": node_id or "",
                "map_id": map_id_val,
                "map_name": map_name,
                "team_id": team_id_val,
                "team_name": team_name,
                "display_title": display_title,
            })
    return normalized


async def _prepare_relation_entries(
    raw_relations: List[Union[str, RelationPayload]],
    source_map: UserStoryMapDB,
    current_user: User,
    usm_db: AsyncSession,
    db: AsyncSession,
) -> List[Dict[str, Any]]:
    """將輸入的關聯資料轉換為標準格式，並補齊目標節點資訊"""

    if not raw_relations:
        return []

    prepared: List[Dict[str, Any]] = []
    seen: Set[Tuple[int, str]] = set()

    map_cache: Dict[int, UserStoryMapDB] = {source_map.id: source_map}
    team_cache: Dict[int, str] = {}
    node_cache: Dict[Tuple[int, str], UserStoryMapNodeDB] = {}

    for raw in raw_relations:
        if isinstance(raw, str):
            rel_dict: Dict[str, Any] = {"node_id": raw}
        elif isinstance(raw, RelationPayload):
            rel_dict = raw.dict(exclude_unset=True)
        elif hasattr(raw, "dict"):
            rel_dict = raw.dict()
        else:
            rel_dict = dict(raw)

        node_id = str(rel_dict.get("node_id") or "").strip()
        if not node_id:
            continue

        try:
            map_id_candidate = rel_dict.get("map_id") if "map_id" in rel_dict else rel_dict.get("mapId")
        except Exception:
            map_id_candidate = None

        map_id = map_id_candidate if map_id_candidate is not None else source_map.id

        # 取得目標地圖資訊
        if map_id not in map_cache:
            map_result = await usm_db.execute(
                select(UserStoryMapDB).where(UserStoryMapDB.id == map_id)
            )
            target_map = map_result.scalar_one_or_none()
            if not target_map:
                raise HTTPException(status_code=404, detail=f"Target map {map_id} not found")
            map_cache[map_id] = target_map
        else:
            target_map = map_cache[map_id]

        # 權限檢查：跨地圖需具備 view 權限
        await _require_usm_permission(current_user, "view", target_map.team_id)

        # 取得團隊名稱
        team_id_candidate = rel_dict.get("team_id") if "team_id" in rel_dict else rel_dict.get("teamId")
        team_id = team_id_candidate if team_id_candidate is not None else target_map.team_id
        team_name = rel_dict.get("team_name") or rel_dict.get("teamName")

        if team_id is not None and not team_name:
            if team_id in team_cache:
                team_name = team_cache[team_id]
            else:
                team_result = await db.execute(select(Team).where(Team.id == team_id))
                team = team_result.scalar_one_or_none()
                team_name = team.name if team else ""
                if team:
                    team_cache[team_id] = team_name
        elif team_id is not None and team_name:
            team_cache.setdefault(team_id, team_name)

        # 取得目標節點資訊
        node_key = (map_id, node_id)
        if node_key not in node_cache:
            node_result = await usm_db.execute(
                select(UserStoryMapNodeDB).where(
                    and_(
                        UserStoryMapNodeDB.map_id == map_id,
                        UserStoryMapNodeDB.node_id == node_id,
                    )
                )
            )
            target_node_db = node_result.scalar_one_or_none()
            if not target_node_db:
                raise HTTPException(status_code=404, detail=f"Target node {node_id} not found in map {map_id}")
            node_cache[node_key] = target_node_db
        else:
            target_node_db = node_cache[node_key]

        display_title = (
            rel_dict.get("display_title")
            or rel_dict.get("displayTitle")
            or getattr(target_node_db, "title", None)
            or node_id
        )

        relation_id = rel_dict.get("relation_id") or rel_dict.get("relationId") or str(uuid.uuid4())

        dedup_key = (map_id, node_id)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        prepared.append({
            "relation_id": relation_id,
            "node_id": node_id,
            "map_id": map_id,
            "map_name": rel_dict.get("map_name") or rel_dict.get("mapName") or target_map.name,
            "team_id": team_id,
            "team_name": team_name or "",
            "display_title": display_title,
        })

    return prepared


async def _get_usm_map(usm_db: AsyncSession, map_id: int) -> Optional[UserStoryMapDB]:
    """取得 USM Map，並在 JSON 欄位損毀時嘗試修復"""
    try:
        result = await usm_db.execute(
            select(UserStoryMapDB).where(UserStoryMapDB.id == map_id)
        )
        return result.scalar_one_or_none()
    except JSONDecodeError:
        await usm_db.execute(
            text(
                "UPDATE user_story_maps SET nodes='[]' WHERE id=:map_id AND (nodes IS NULL OR trim(nodes)='')"
            ),
            {"map_id": map_id},
        )
        await usm_db.commit()
        result = await usm_db.execute(
            select(UserStoryMapDB).where(UserStoryMapDB.id == map_id)
        )
        return result.scalar_one_or_none()


async def _get_usm_node(
    usm_db: AsyncSession, map_id: int, node_id: str
) -> Optional[UserStoryMapNodeDB]:
    """取得 USM Node，遇到 JSONDecodeError 時自動修復"""
    try:
        result = await usm_db.execute(
            select(UserStoryMapNodeDB).where(
                and_(
                    UserStoryMapNodeDB.map_id == map_id,
                    UserStoryMapNodeDB.node_id == node_id,
                )
            )
        )
        return result.scalar_one_or_none()
    except JSONDecodeError:
        await usm_db.execute(
            text(
                """
                UPDATE user_story_map_nodes
                SET related_ids='[]'
                WHERE map_id=:map_id AND node_id=:node_id AND (related_ids IS NULL OR trim(related_ids)='')
                """
            ),
            {"map_id": map_id, "node_id": node_id},
        )
        await usm_db.commit()
        result = await usm_db.execute(
            select(UserStoryMapNodeDB).where(
                and_(
                    UserStoryMapNodeDB.map_id == map_id,
                    UserStoryMapNodeDB.node_id == node_id,
                )
            )
        )
        return result.scalar_one_or_none()


def _save_node_relations(
    source_map: UserStoryMapDB,
    source_node_db: UserStoryMapNodeDB,
    relations: List[Dict[str, Any]],
) -> None:
    """更新來源節點以及主 JSON 的關聯欄位"""

    normalized_relations = _normalize_related_ids(relations)
    source_node_db.related_ids = normalized_relations
    source_node_db.updated_at = datetime.utcnow()
    flag_modified(source_node_db, "related_ids")

    map_nodes = list(source_map.nodes or [])
    updated = False
    for idx, entry in enumerate(map_nodes):
        entry_id = entry.get("id") if isinstance(entry, dict) else None
        if entry_id == source_node_db.node_id:
            entry_copy = dict(entry)
            entry_copy["related_ids"] = normalized_relations
            map_nodes[idx] = entry_copy
            updated = True
            break

    if not updated:
        map_nodes.append({
            "id": source_node_db.node_id,
            "title": source_node_db.title,
            "description": source_node_db.description,
            "node_type": source_node_db.node_type,
            "parent_id": source_node_db.parent_id,
            "children_ids": source_node_db.children_ids or [],
            "related_ids": normalized_relations,
            "comment": source_node_db.comment,
            "jira_tickets": source_node_db.jira_tickets or [],
            "team": source_node_db.team,
            "aggregated_tickets": source_node_db.aggregated_tickets or [],
            "position_x": source_node_db.position_x,
            "position_y": source_node_db.position_y,
            "level": source_node_db.level,
            "as_a": source_node_db.as_a,
            "i_want": source_node_db.i_want,
            "so_that": source_node_db.so_that,
        })

    source_map.nodes = map_nodes
    source_map.updated_at = datetime.utcnow()
    flag_modified(source_map, "nodes")


async def _require_usm_permission(
    current_user: User,
    action: str,
    team_id: Optional[int] = None,
) -> None:
    """對 USM 資源執行 Casbin 權限檢查並套用團隊權限限制"""

    casbin_check = await permission_service.check_permission(
        current_user=current_user,
        feature="user_story_map",
        action=action,
    )

    if not casbin_check.has_permission:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "USM_PERMISSION_DENIED",
                "message": casbin_check.reason or "無權限執行此操作",
            },
        )

    if team_id is None:
        return

    required_team_permission = (
        PermissionType.READ if action == "view" else PermissionType.WRITE
    )

    team_check = await permission_service.check_team_permission(
        current_user.id,
        team_id,
        required_team_permission,
        current_user.role,
    )

    if not team_check.has_permission:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "USM_TEAM_PERMISSION_DENIED",
                "message": team_check.reason or "無權限存取此團隊",
            },
        )


@router.get("/search-nodes", response_model=List[SearchNodeResult])
async def search_global_nodes(
    q: Optional[str] = Query(None, description="搜尋關鍵字"),
    node_type: Optional[str] = Query(None, description="節點類型"),
    map_id: Optional[int] = Query(None, description="限制在特定地圖"),
    team_id: Optional[int] = Query(None, description="限制在特定團隊"),
    team_ids: Optional[str] = Query(None, description="限制在特定團隊們 (逗號分隔)"),
    include_external: bool = Query(False, description="是否搜尋外部地圖"),
    exclude_node_id: Optional[str] = Query(None, description="排除的節點ID"),
    jira_tickets: Optional[str] = Query(None, description="JIRA 單號 (逗號分隔)"),
    jira_logic: str = Query("and", description="JIRA 搜尋邏輯 (and/or)"),
    current_user: User = Depends(get_current_user),
    usm_db: AsyncSession = Depends(get_usm_db),
    db: AsyncSession = Depends(get_db),
):
    """跨地圖搜尋節點"""

    if not map_id:
        raise HTTPException(status_code=400, detail="map_id is required")

    source_map_result = await usm_db.execute(
        select(UserStoryMapDB).where(UserStoryMapDB.id == map_id)
    )
    source_map_db = source_map_result.scalar_one_or_none()

    if not source_map_db:
        raise HTTPException(status_code=404, detail="Source map not found")

    await _require_usm_permission(current_user, "view", source_map_db.team_id)

    query = select(UserStoryMapNodeDB)

    if not include_external:
        query = query.where(UserStoryMapNodeDB.map_id == map_id)

    if q:
        like_pattern = f"%{q}%"
        query = query.where(
            or_(
                UserStoryMapNodeDB.title.ilike(like_pattern),
                UserStoryMapNodeDB.description.ilike(like_pattern),
                UserStoryMapNodeDB.comment.ilike(like_pattern),
                UserStoryMapNodeDB.as_a.ilike(like_pattern),
                UserStoryMapNodeDB.i_want.ilike(like_pattern),
                UserStoryMapNodeDB.so_that.ilike(like_pattern),
            )
        )

    if node_type:
        query = query.where(UserStoryMapNodeDB.node_type == node_type)

    # Support both team_id (single) and team_ids (multiple, comma-separated)
    if team_ids:
        team_id_list = [int(tid.strip()) for tid in team_ids.split(',') if tid.strip().isdigit()]
        if team_id_list:
            query = query.where(UserStoryMapNodeDB.map_id.in_(
                select(UserStoryMapDB.id).where(UserStoryMapDB.team_id.in_(team_id_list))
            ))
    elif team_id:
        query = query.where(UserStoryMapNodeDB.map_id.in_(
            select(UserStoryMapDB.id).where(UserStoryMapDB.team_id == team_id)
        ))

    result = await usm_db.execute(query)
    nodes = result.scalars().all()

    # 排除根節點和指定的節點
    nodes = [node for node in nodes if node.node_type != 'root']
    if exclude_node_id:
        nodes = [node for node in nodes if node.node_id != exclude_node_id]

    # 處理 JIRA 票號過濾 (AND/OR 邏輯)
    if jira_tickets:
        ticket_list = [t.strip() for t in jira_tickets.split(',') if t.strip()]
        if ticket_list:
            if jira_logic == 'or':
                # OR 邏輯：節點包含任何一個 JIRA 票號
                nodes = [n for n in nodes if any(t in (n.jira_tickets or []) for t in ticket_list)]
            else:
                # AND 邏輯：節點包含所有 JIRA 票號
                nodes = [n for n in nodes if all(t in (n.jira_tickets or []) for t in ticket_list)]

    search_results = []
    for node in nodes:
        map_result = await usm_db.execute(
            select(UserStoryMapDB).where(UserStoryMapDB.id == node.map_id)
        )
        node_map = map_result.scalar_one_or_none()

        team_result = await db.execute(
            select(Team).where(Team.id == node_map.team_id)
        )
        team = team_result.scalar_one_or_none()

        if include_external and node.map_id != map_id:
            await _require_usm_permission(current_user, "view", node_map.team_id)

        search_results.append(SearchNodeResult(
            node_id=node.node_id,
            node_title=node.title,
            node_type=node.node_type,
            map_id=node.map_id,
            map_name=node_map.name if node_map else "Unknown",
            team_id=node_map.team_id if node_map else 0,
            team_name=team.name if team else "Unknown",
            breadcrumb=node.comment,
            description=node.description,
        ))

    return search_results


@router.get("/team/{team_id}", response_model=List[UserStoryMapResponse])
async def get_team_maps(
    team_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_usm_db),
):
    """獲取團隊的所有 User Story Maps"""
    await _require_usm_permission(current_user, "view", team_id)

    result = await db.execute(
        select(UserStoryMapDB).where(UserStoryMapDB.team_id == team_id)
    )
    maps = result.scalars().all()
    
    response_maps = []
    for map_db in maps:
        # 優先從 nodes 表取資料
        node_rows = await db.execute(
            select(UserStoryMapNodeDB).where(UserStoryMapNodeDB.map_id == map_db.id)
        )
        node_list = node_rows.scalars().all()

        raw_nodes = []
        if node_list:
            for n in node_list:
                raw_nodes.append({
                    "id": n.node_id,
                    "title": n.title,
                    "description": n.description,
                    "node_type": n.node_type,
                    "parent_id": n.parent_id,
                    "children_ids": n.children_ids or [],
                    "related_ids": n.related_ids or [],
                    "comment": n.comment,
                    "jira_tickets": n.jira_tickets or [],
                    "team": n.team,
                    "team_tags": n.team_tags or [],
                    "aggregated_tickets": n.aggregated_tickets or [],
                    "position_x": n.position_x or 0,
                    "position_y": n.position_y or 0,
                    "level": n.level or 0,
                    "as_a": n.as_a,
                    "i_want": n.i_want,
                    "so_that": n.so_that,
                })
        else:
            raw_nodes = map_db.nodes or []

        processed_nodes = []
        legacy_mapping = {'epic': 'feature_category', 'feature': 'feature_category', 'task': 'user_story'}
        for node in raw_nodes:
            node_copy = dict(node)
            if node_copy.get('node_type') in legacy_mapping:
                node_copy['node_type'] = legacy_mapping[node_copy['node_type']]
            if not node_copy.get('node_type'):
                node_copy['node_type'] = 'feature_category'
            processed_nodes.append(node_copy)

        nodes = [UserStoryMapNode(**node) for node in processed_nodes]

        if map_db.edges:
            edges = [UserStoryMapEdge(**edge) for edge in map_db.edges]
        else:
            generated_edges = []
            seen_edges = set()
            for n in processed_nodes:
                if n.get("parent_id"):
                    eid = f"{n['parent_id']}->{n['id']}"
                    if eid not in seen_edges:
                        generated_edges.append({"id": eid, "source": n['parent_id'], "target": n['id'], "edge_type": "parent"})
                        seen_edges.add(eid)
                for rid in n.get("related_ids") or []:
                    eid = f"relation-{n['id']}-{rid}"
                    if eid not in seen_edges:
                        generated_edges.append({"id": eid, "source": n['id'], "target": rid, "edge_type": "related"})
                        seen_edges.add(eid)
            edges = [UserStoryMapEdge(**edge) for edge in generated_edges]
        
        response_maps.append(
            UserStoryMapResponse(
                id=map_db.id,
                team_id=map_db.team_id,
                name=map_db.name,
                description=map_db.description,
                nodes=nodes,
                edges=edges,
                created_at=map_db.created_at,
                updated_at=map_db.updated_at,
            )
        )
    
    return response_maps


@router.get("/{map_id}", response_model=UserStoryMapResponse)
async def get_map(
    map_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_usm_db),
):
    """獲取特定 User Story Map"""
    result = await db.execute(
        select(UserStoryMapDB).where(UserStoryMapDB.id == map_id)
    )
    map_db = result.scalar_one_or_none()
    
    if not map_db:
        raise HTTPException(status_code=404, detail="User Story Map not found")

    await _require_usm_permission(current_user, "view", map_db.team_id)

    # 優先從 nodes 表取資料
    node_rows = await db.execute(
        select(UserStoryMapNodeDB).where(UserStoryMapNodeDB.map_id == map_id)
    )
    node_list = node_rows.scalars().all()

    raw_nodes = []
    if node_list:
        for n in node_list:
            raw_nodes.append({
                "id": n.node_id,
                "title": n.title,
                "description": n.description,
                "node_type": n.node_type,
                "parent_id": n.parent_id,
                "children_ids": n.children_ids or [],
                "related_ids": _normalize_related_ids(n.related_ids),
                "comment": n.comment,
                "jira_tickets": n.jira_tickets or [],
                "team": n.team,
                "team_tags": n.team_tags or [],
                "aggregated_tickets": n.aggregated_tickets or [],
                "position_x": n.position_x or 0,
                "position_y": n.position_y or 0,
                "level": n.level or 0,
                "as_a": n.as_a,
                "i_want": n.i_want,
                "so_that": n.so_that,
            })
    else:
        raw_nodes = map_db.nodes or []

    # Map legacy node_type values to new enum values
    processed_nodes = []
    legacy_mapping = {
        'epic': 'feature_category',
        'feature': 'feature_category',
        'task': 'user_story'
    }
    for node in raw_nodes:
        node_copy = dict(node)
        if node_copy.get('node_type') in legacy_mapping:
            node_copy['node_type'] = legacy_mapping[node_copy['node_type']]
        if not node_copy.get('node_type'):
            node_copy['node_type'] = 'feature_category'
        node_copy['related_ids'] = _normalize_related_ids(node_copy.get('related_ids'))
        processed_nodes.append(node_copy)

    nodes = [UserStoryMapNode(**node) for node in processed_nodes]

    # Edge 來源：map_db.edges，若空則由 parent/related 動態生成
    if map_db.edges:
        edges = [UserStoryMapEdge(**edge) for edge in map_db.edges]
    else:
        generated_edges = []
        seen_edges = set()
        for n in processed_nodes:
            if n.get("parent_id"):
                eid = f"{n['parent_id']}->{n['id']}"
                if eid not in seen_edges:
                    generated_edges.append({
                        "id": eid,
                        "source": n['parent_id'],
                        "target": n['id'],
                        "edge_type": "parent"
                    })
                    seen_edges.add(eid)
            for rid in n.get("related_ids") or []:
                eid = f"relation-{n['id']}-{rid}"
                if eid not in seen_edges:
                    generated_edges.append({
                        "id": eid,
                        "source": n['id'],
                        "target": rid,
                        "edge_type": "related"
                    })
                    seen_edges.add(eid)
        edges = [UserStoryMapEdge(**edge) for edge in generated_edges]
    
    return UserStoryMapResponse(
        id=map_db.id,
        team_id=map_db.team_id,
        name=map_db.name,
        description=map_db.description,
        nodes=nodes,
        edges=edges,
        created_at=map_db.created_at,
        updated_at=map_db.updated_at,
    )


@router.post("/", response_model=UserStoryMapResponse)
async def create_map(
    map_data: UserStoryMapCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_usm_db),
):
    """建立新的 User Story Map"""
    await _require_usm_permission(current_user, "create", map_data.team_id)
    # Create root node
    import time
    root_node = {
        "id": f"root_{int(time.time() * 1000)}",
        "title": "Root",
        "description": "根節點",
        "node_type": "root",
        "parent_id": None,
        "children_ids": [],
        "related_ids": [],
        "comment": "",
        "jira_tickets": [],
        "team": None,
        "aggregated_tickets": [],
        "position_x": 250.0,
        "position_y": 250.0,
        "level": 0,
        "as_a": None,
        "i_want": None,
        "so_that": None,
    }
    
    new_map = UserStoryMapDB(
        team_id=map_data.team_id,
        name=map_data.name,
        description=map_data.description,
        nodes=[root_node],
        edges=[],
    )
    
    db.add(new_map)
    await db.commit()
    await db.refresh(new_map)
    
    # Create node DB entry for search
    node_db = UserStoryMapNodeDB(
        map_id=new_map.id,
        node_id=root_node["id"],
        title=root_node["title"],
        description=root_node["description"],
        node_type=root_node["node_type"],
        parent_id=root_node["parent_id"],
        children_ids=root_node["children_ids"],
        related_ids=root_node["related_ids"],
        comment=root_node["comment"],
        jira_tickets=root_node["jira_tickets"],
        team=root_node["team"],
        aggregated_tickets=root_node["aggregated_tickets"],
        position_x=float(root_node["position_x"]),
        position_y=float(root_node["position_y"]),
        level=root_node["level"],
        as_a=root_node["as_a"],
        i_want=root_node["i_want"],
        so_that=root_node["so_that"],
    )
    db.add(node_db)
    await db.commit()

    # 記錄審計日誌
    role_value = (
        current_user.role.value
        if hasattr(current_user.role, "value")
        else str(current_user.role)
    )
    try:
        await audit_service.log_action(
            user_id=current_user.id,
            username=current_user.username,
            role=role_value,
            action_type=ActionType.CREATE,
            resource_type=ResourceType.USER_STORY_MAP,
            resource_id=str(new_map.id),
            team_id=map_data.team_id,
            details={
                "map_id": new_map.id,
                "map_name": new_map.name,
                "description": new_map.description,
                "source": "manual_creation",
            },
            action_brief=f"{current_user.username} created User Story Map: {new_map.name}",
            severity=AuditSeverity.INFO,
        )
    except Exception as exc:
        logger.warning("寫入 USM 創建審計記錄失敗: %s", exc, exc_info=True)

    return UserStoryMapResponse(
        id=new_map.id,
        team_id=new_map.team_id,
        name=new_map.name,
        description=new_map.description,
        nodes=[UserStoryMapNode(**root_node)],
        edges=[],
        created_at=new_map.created_at,
        updated_at=new_map.updated_at,
    )


@router.put("/{map_id}", response_model=UserStoryMapResponse)
async def update_map(
    map_id: int,
    map_data: UserStoryMapUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_usm_db),
):
    """更新 User Story Map"""
    result = await db.execute(
        select(UserStoryMapDB).where(UserStoryMapDB.id == map_id)
    )
    map_db = result.scalar_one_or_none()
    
    if not map_db:
        raise HTTPException(status_code=404, detail="User Story Map not found")
    
    await _require_usm_permission(current_user, "update", map_db.team_id)

    if map_data.name is not None:
        map_db.name = map_data.name
    if map_data.description is not None:
        map_db.description = map_data.description
    if map_data.nodes is not None:
        normalized_nodes = []

        # 更新節點索引表
        await db.execute(
            delete(UserStoryMapNodeDB).where(UserStoryMapNodeDB.map_id == map_id)
        )

        for node in map_data.nodes:
            normalized_related = _normalize_related_ids(node.related_ids)

            node_dict = node.dict()
            node_dict["related_ids"] = normalized_related
            normalized_nodes.append(node_dict)

            node_db = UserStoryMapNodeDB(
                map_id=map_id,
                node_id=node.id,
                title=node.title,
                description=node.description,
                node_type=node.node_type.value if hasattr(node.node_type, 'value') else node.node_type,
                parent_id=node.parent_id,
                children_ids=node.children_ids,
                related_ids=normalized_related,
                comment=node.comment,
                jira_tickets=node.jira_tickets,
                team=node.team,
                aggregated_tickets=node.aggregated_tickets,
                position_x=node.position_x,
                position_y=node.position_y,
                level=node.level,
                as_a=getattr(node, 'as_a', None),
                i_want=getattr(node, 'i_want', None),
                so_that=getattr(node, 'so_that', None),
            )
            db.add(node_db)

        map_db.nodes = normalized_nodes
        flag_modified(map_db, "nodes")

    if map_data.edges is not None:
        map_db.edges = [edge.dict() for edge in map_data.edges]
        flag_modified(map_db, "edges")
    
    map_db.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(map_db)

    # 記錄審計日誌
    role_value = (
        current_user.role.value
        if hasattr(current_user.role, "value")
        else str(current_user.role)
    )
    changes = []
    if map_data.name is not None:
        changes.append("name")
    if map_data.description is not None:
        changes.append("description")
    if map_data.nodes is not None:
        changes.append(f"nodes ({len(map_data.nodes)} total)")
    if map_data.edges is not None:
        changes.append(f"edges ({len(map_data.edges)} total)")

    try:
        await audit_service.log_action(
            user_id=current_user.id,
            username=current_user.username,
            role=role_value,
            action_type=ActionType.UPDATE,
            resource_type=ResourceType.USER_STORY_MAP,
            resource_id=str(map_id),
            team_id=map_db.team_id,
            details={
                "map_id": map_id,
                "map_name": map_db.name,
                "changed_fields": changes,
                "source": "map_update",
            },
            action_brief=f"{current_user.username} updated User Story Map: {map_db.name} ({', '.join(changes)})",
            severity=AuditSeverity.INFO,
        )
    except Exception as exc:
        logger.warning("寫入 USM 更新審計記錄失敗: %s", exc, exc_info=True)

    # Ensure all nodes have normalized related_ids
    processed_nodes = []
    for node in (map_db.nodes or []):
        node_copy = dict(node)
        node_copy['related_ids'] = _normalize_related_ids(node_copy.get('related_ids'))
        processed_nodes.append(node_copy)

    nodes = [UserStoryMapNode(**node) for node in processed_nodes]
    edges = [UserStoryMapEdge(**edge) for edge in (map_db.edges or [])]

    return UserStoryMapResponse(
        id=map_db.id,
        team_id=map_db.team_id,
        name=map_db.name,
        description=map_db.description,
        nodes=nodes,
        edges=edges,
        created_at=map_db.created_at,
        updated_at=map_db.updated_at,
    )


@router.delete("/{map_id}")
async def delete_map(
    map_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_usm_db),
):
    """刪除 User Story Map 及其所有節點"""
    result = await db.execute(
        select(UserStoryMapDB).where(UserStoryMapDB.id == map_id)
    )
    map_db = result.scalar_one_or_none()

    if not map_db:
        raise HTTPException(status_code=404, detail="User Story Map not found")

    await _require_usm_permission(current_user, "delete", map_db.team_id)

    # 記錄要刪除的 map 信息
    map_name = map_db.name
    team_id = map_db.team_id
    node_count = len(map_db.nodes) if map_db.nodes else 0

    # 級聯刪除：先刪除所有關聯的節點
    await db.execute(
        delete(UserStoryMapNodeDB).where(UserStoryMapNodeDB.map_id == map_id)
    )

    # 再刪除 map 本身
    await db.delete(map_db)
    await db.commit()

    # 記錄審計日誌
    role_value = (
        current_user.role.value
        if hasattr(current_user.role, "value")
        else str(current_user.role)
    )
    try:
        await audit_service.log_action(
            user_id=current_user.id,
            username=current_user.username,
            role=role_value,
            action_type=ActionType.DELETE,
            resource_type=ResourceType.USER_STORY_MAP,
            resource_id=str(map_id),
            team_id=team_id,
            details={
                "map_id": map_id,
                "map_name": map_name,
                "node_count": node_count,
                "source": "map_deletion",
            },
            action_brief=f"{current_user.username} deleted User Story Map: {map_name} ({node_count} nodes)",
            severity=AuditSeverity.CRITICAL,
        )
    except Exception as exc:
        logger.warning("寫入 USM 刪除審計記錄失敗: %s", exc, exc_info=True)

    return {"message": "User Story Map deleted successfully"}


@router.get("/{map_id}/search")
async def search_nodes(
    map_id: int,
    q: Optional[str] = Query(None, description="搜尋關鍵字"),
    node_type: Optional[str] = Query(None, description="節點類型"),
    team: Optional[str] = Query(None, description="團隊"),
    jira_ticket: Optional[str] = Query(None, description="JIRA Ticket"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_usm_db),
):
    """搜尋 User Story Map 節點"""
    map_result = await db.execute(
        select(UserStoryMapDB).where(UserStoryMapDB.id == map_id)
    )
    map_db = map_result.scalar_one_or_none()

    if not map_db:
        raise HTTPException(status_code=404, detail="User Story Map not found")

    await _require_usm_permission(current_user, "view", map_db.team_id)

    query = select(UserStoryMapNodeDB).where(UserStoryMapNodeDB.map_id == map_id)
    
    if q:
        like_pattern = f"%{q}%"
        query = query.where(
            or_(
                UserStoryMapNodeDB.title.ilike(like_pattern),
                UserStoryMapNodeDB.description.ilike(like_pattern),
                UserStoryMapNodeDB.comment.ilike(like_pattern),
                UserStoryMapNodeDB.as_a.ilike(like_pattern),
                UserStoryMapNodeDB.i_want.ilike(like_pattern),
                UserStoryMapNodeDB.so_that.ilike(like_pattern),
            )
        )

    if node_type:
        query = query.where(UserStoryMapNodeDB.node_type == node_type)

    if team:
        query = query.where(UserStoryMapNodeDB.team == team)
    
    result = await db.execute(query)
    nodes = result.scalars().all()

    if jira_ticket:
        # JSON 欄位搜尋需要特殊處理
        nodes = [n for n in nodes if jira_ticket in (n.jira_tickets or [])]

    return [
        {
            "node_id": node.node_id,
            "title": node.title,
            "description": node.description,
            "node_type": node.node_type,
            "team": node.team,
            "jira_tickets": node.jira_tickets,
        }
        for node in nodes
    ]


@router.post("/{map_id}/calculate-aggregated-tickets")
async def calculate_aggregated_tickets(
    map_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_usm_db),
):
    """計算並更新所有節點的聚合 tickets (從子節點繼承)"""
    result = await db.execute(
        select(UserStoryMapDB).where(UserStoryMapDB.id == map_id)
    )
    map_db = result.scalar_one_or_none()
    
    if not map_db:
        raise HTTPException(status_code=404, detail="User Story Map not found")
    
    await _require_usm_permission(current_user, "update", map_db.team_id)

    nodes = map_db.nodes or []
    node_dict = {node["id"]: node for node in nodes}
    
    def aggregate_tickets(node_id: str, visited: set = None) -> List[str]:
        """遞迴聚合子節點的 tickets"""
        if visited is None:
            visited = set()
        
        if node_id in visited:
            return []
        
        visited.add(node_id)
        node = node_dict.get(node_id)
        
        if not node:
            return []
        
        tickets = set(node.get("jira_tickets", []))
        
        for child_id in node.get("children_ids", []):
            tickets.update(aggregate_tickets(child_id, visited))
        
        return list(tickets)
    
    for node in nodes:
        node["aggregated_tickets"] = aggregate_tickets(node["id"])

    map_db.nodes = nodes
    flag_modified(map_db, "nodes")

    for node in nodes:
        await db.execute(
            update(UserStoryMapNodeDB)
            .where(
                UserStoryMapNodeDB.map_id == map_id,
                UserStoryMapNodeDB.node_id == node["id"],
            )
            .values(
                aggregated_tickets=node.get("aggregated_tickets", []),
                jira_tickets=node.get("jira_tickets", []),
                updated_at=datetime.utcnow(),
            )
        )

    await db.commit()
    await db.refresh(map_db)

    return {"message": "Aggregated tickets calculated successfully"}


@router.get("/{map_id}/path/{node_id}")
async def get_node_path(
    map_id: int,
    node_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_usm_db),
):
    """獲取從根節點到指定節點的路徑"""
    result = await db.execute(
        select(UserStoryMapDB).where(UserStoryMapDB.id == map_id)
    )
    map_db = result.scalar_one_or_none()
    
    if not map_db:
        raise HTTPException(status_code=404, detail="User Story Map not found")

    await _require_usm_permission(current_user, "view", map_db.team_id)
    
    nodes = map_db.nodes or []
    node_dict = {node["id"]: node for node in nodes}
    
    path = []
    current = node_dict.get(node_id)
    
    while current:
        path.insert(0, current["id"])
        parent_id = current.get("parent_id")
        current = node_dict.get(parent_id) if parent_id else None
    
    return {"path": path}


async def _create_reverse_relation(
    target_node_db: UserStoryMapNodeDB,
    target_map: UserStoryMapDB,
    source_node_id: str,
    source_map_id: int,
    source_map_name: str,
    source_team_id: int,
    source_team_name: str,
    source_node_name: str,
    usm_db: AsyncSession,
) -> None:
    """建立反向關聯：被關聯的節點也要記錄源節點的關聯"""
    
    # 建立反向關聯數據
    reverse_relation = {
        "node_id": source_node_id,
        "map_id": source_map_id,
        "map_name": source_map_name,
        "team_id": source_team_id,
        "team_name": source_team_name,
        "display_title": source_node_name,
        "relation_id": None,
    }
    
    # 取得目標節點的現有關聯
    existing_relations = _normalize_related_ids(target_node_db.related_ids)
    dedup: Set[Tuple[int, str]] = set()
    merged: List[Union[str, Dict[str, Any]]] = []
    
    # 保留現有關聯並去重
    for rel in existing_relations:
        if isinstance(rel, str):
            key = (target_map.id, rel)
            if key in dedup:
                continue
            dedup.add(key)
            merged.append(rel)
        else:
            key = ((rel.get("map_id") or target_map.id), rel.get("node_id"))
            if key in dedup:
                continue
            dedup.add(key)
            merged.append(rel)
    
    # 檢查反向關聯是否已存在
    key = (source_map_id, source_node_id)
    if key not in dedup:
        merged.append(reverse_relation)
        _save_node_relations(target_map, target_node_db, merged)
        await usm_db.flush()


@router.post("/{map_id}/nodes/{node_id}/relations")
async def create_relation(
    map_id: int,
    node_id: str,
    request: RelationCreateRequest,
    current_user: User = Depends(get_current_user),
    usm_db: AsyncSession = Depends(get_usm_db),
    db: AsyncSession = Depends(get_db),
):
    """建立節點關聯"""
    source_map = await _get_usm_map(usm_db, map_id)

    if not source_map:
        raise HTTPException(status_code=404, detail="Source map not found")

    await _require_usm_permission(current_user, "update", source_map.team_id)

    source_node_db = await _get_usm_node(usm_db, map_id, node_id)

    if not source_node_db:
        raise HTTPException(status_code=404, detail="Source node not found")

    new_relations = await _prepare_relation_entries(
        [RelationPayload(node_id=request.target_node_id, map_id=request.target_map_id)],
        source_map,
        current_user,
        usm_db,
        db,
    )

    if not new_relations:
        raise HTTPException(status_code=400, detail="No relation provided")

    existing_relations = _normalize_related_ids(source_node_db.related_ids)
    dedup: Set[Tuple[int, str]] = set()
    merged: List[Union[str, Dict[str, Any]]] = []

    for rel in existing_relations:
        if isinstance(rel, str):
            key = (source_map.id, rel)
            if key in dedup:
                continue
            dedup.add(key)
            merged.append(rel)
            continue

        key = ((rel.get("map_id") or source_map.id), rel.get("node_id"))
        if key in dedup:
            continue
        dedup.add(key)
        merged.append(rel)

    created_relation = None
    for rel in new_relations:
        key = (rel.get("map_id") or source_map.id, rel.get("node_id"))
        if key in dedup:
            continue
        dedup.add(key)
        merged.append(rel)
        if created_relation is None:
            created_relation = rel

    if created_relation is None:
        return {"relation_id": None, "message": "Relation already exists"}

    _save_node_relations(source_map, source_node_db, merged)
    
    # 建立反向關聯：目標節點也要記錄源節點的關聯
    target_node_id = created_relation.get("node_id")
    target_map_id = created_relation.get("map_id") or source_map.id
    
    if target_node_id:
        target_map = await _get_usm_map(usm_db, target_map_id)
        if target_map:
            target_node_db = await _get_usm_node(usm_db, target_map_id, target_node_id)
            if target_node_db:
                # 取得源節點名稱 - 直接使用 DB 物件的 title
                source_node_name = source_node_db.title or ""
                
                # 建立反向關聯
                await _create_reverse_relation(
                    target_node_db=target_node_db,
                    target_map=target_map,
                    source_node_id=source_node_db.node_id,
                    source_map_id=source_map.id,
                    source_map_name=source_map.name or "",
                    source_team_id=source_map.team_id,
                    source_team_name="",  # 可以後續改進取得團隊名稱
                    source_node_name=source_node_name,
                    usm_db=usm_db,
                )
    
    await usm_db.commit()
    await usm_db.refresh(source_node_db)
    await usm_db.refresh(source_map)

    # 記錄審計日誌
    role_value = (
        current_user.role.value
        if hasattr(current_user.role, "value")
        else str(current_user.role)
    )
    try:
        await audit_service.log_action(
            user_id=current_user.id,
            username=current_user.username,
            role=role_value,
            action_type=ActionType.CREATE,
            resource_type=ResourceType.USER_STORY_MAP,
            resource_id=f"{map_id}:{node_id}",
            team_id=source_map.team_id,
            details={
                "map_id": map_id,
                "node_id": node_id,
                "target_node_id": created_relation.get("node_id"),
                "target_map_id": created_relation.get("map_id") or map_id,
                "source": "node_relation",
            },
            action_brief=f"{current_user.username} created relation from node {node_id} in map {map_id}",
            severity=AuditSeverity.INFO,
        )
    except Exception as exc:
        logger.warning("寫入 USM 關聯審計記錄失敗: %s", exc, exc_info=True)

    return {
        "relation_id": created_relation.get("relation_id"),
        "message": "Relation created successfully",
    }


@router.delete("/{map_id}/nodes/{node_id}/relations/{relation_id}")
async def delete_relation(
    map_id: int,
    node_id: str,
    relation_id: str,
    current_user: User = Depends(get_current_user),
    usm_db: AsyncSession = Depends(get_usm_db),
):
    """刪除節點關聯（包括反向關聯）"""
    
    source_map = await _get_usm_map(usm_db, map_id)
    
    if not source_map:
        raise HTTPException(status_code=404, detail="Source map not found")
    
    await _require_usm_permission(current_user, "update", source_map.team_id)
    
    source_node_db = await _get_usm_node(usm_db, map_id, node_id)
    
    if not source_node_db:
        raise HTTPException(status_code=404, detail="Source node not found")

    existing_relations = _normalize_related_ids(source_node_db.related_ids)

    # 找到要刪除的關聯詳情
    removed_relation = None
    filtered: List[Union[str, Dict[str, Any]]] = []
    removed = False
    
    for rel in existing_relations:
        if isinstance(rel, str):
            if relation_id == rel:
                removed = True
                removed_relation = {"node_id": rel, "map_id": source_map.id}
                continue
            filtered.append(rel)
            continue

        if rel.get("relation_id") == relation_id:
            removed = True
            removed_relation = rel
            continue
        filtered.append(rel)

    if not removed:
        return {"message": "Relation deleted successfully"}

    _save_node_relations(source_map, source_node_db, filtered)
    
    # 刪除反向關聯：從目標節點移除源節點
    if removed_relation:
        target_node_id = removed_relation.get("node_id")
        target_map_id = removed_relation.get("map_id") or source_map.id
        
        if target_node_id:
            try:
                target_map = await _get_usm_map(usm_db, target_map_id)
                if target_map:
                    target_node_db = await _get_usm_node(usm_db, target_map_id, target_node_id)
                    if target_node_db:
                        # 從目標節點的關聯中移除源節點
                        target_relations = _normalize_related_ids(target_node_db.related_ids)
                        target_filtered: List[Union[str, Dict[str, Any]]] = []
                        
                        for rel in target_relations:
                            should_keep = True
                            
                            if isinstance(rel, str):
                                # 字符串格式的關聯：匹配 node_id 和 map_id 才刪除
                                if rel == source_node_db.node_id and (removed_relation.get("map_id") or source_map.id) == source_map.id:
                                    should_keep = False
                            else:
                                # 字典格式的關聯：完全匹配 node_id 和 map_id 才刪除
                                if (rel.get("node_id") == source_node_db.node_id and 
                                    (rel.get("map_id") or source_map.id) == source_map.id):
                                    should_keep = False
                            
                            if should_keep:
                                target_filtered.append(rel)
                        
                        _save_node_relations(target_map, target_node_db, target_filtered)
            except Exception as e:
                print(f"[DELETE RELATION] Error deleting reverse relation: {e}")
    
    await usm_db.commit()
    await usm_db.refresh(source_node_db)
    await usm_db.refresh(source_map)

    # 記錄審計日誌
    if removed:
        role_value = (
            current_user.role.value
            if hasattr(current_user.role, "value")
            else str(current_user.role)
        )
        try:
            await audit_service.log_action(
                user_id=current_user.id,
                username=current_user.username,
                role=role_value,
                action_type=ActionType.DELETE,
                resource_type=ResourceType.USER_STORY_MAP,
                resource_id=f"{map_id}:{node_id}:{relation_id}",
                team_id=source_map.team_id,
                details={
                    "map_id": map_id,
                    "node_id": node_id,
                    "relation_id": relation_id,
                    "target_node_id": removed_relation.get("node_id") if removed_relation else None,
                    "source": "relation_deletion",
                },
                action_brief=f"{current_user.username} deleted relation from node {node_id} in map {map_id}",
                severity=AuditSeverity.INFO,
            )
        except Exception as exc:
            logger.warning("寫入 USM 關聯刪除審計記錄失敗: %s", exc, exc_info=True)

    return {"message": "Relation deleted successfully"}


@router.put("/{map_id}/nodes/{node_id}/relations", response_model=RelationBulkUpdateResponse)
async def replace_relations(
    map_id: int,
    node_id: str,
    payload: RelationBulkUpdateRequest,
    current_user: User = Depends(get_current_user),
    usm_db: AsyncSession = Depends(get_usm_db),
    db: AsyncSession = Depends(get_db),
):
    """批次更新指定節點的所有關聯"""
    
    print(f"\n[PUT RELATION] Called - map_id={map_id}, node_id={node_id}")
    print(f"[PUT RELATION] Payload relations count: {len(payload.relations) if payload and payload.relations else 0}")

    source_map = await _get_usm_map(usm_db, map_id)

    if not source_map:
        raise HTTPException(status_code=404, detail="Source map not found")

    await _require_usm_permission(current_user, "update", source_map.team_id)

    source_node_db = await _get_usm_node(usm_db, map_id, node_id)

    if not source_node_db:
        raise HTTPException(status_code=404, detail="Source node not found")

    incoming_relations = payload.relations if payload and payload.relations is not None else []
    print(f"[PUT RELATION] Incoming relations: {incoming_relations}")
    
    prepared_relations = await _prepare_relation_entries(
        incoming_relations,
        source_map,
        current_user,
        usm_db,
        db,
    )
    
    print(f"[PUT RELATION] Prepared relations: {prepared_relations}")

    # 獲取舊關聯以便清理反向關聯
    old_relations = _normalize_related_ids(source_node_db.related_ids)
    
    _save_node_relations(source_map, source_node_db, prepared_relations)
    
    print(f"[PUT RELATION] After save, source_node_db.related_ids: {source_node_db.related_ids}")
    
    # 清理舊的反向關聯（從被移除的關聯目標中刪除源節點）
    for old_rel in old_relations:
        should_remove = True
        
        # 檢查是否在新關聯中
        for new_rel in prepared_relations:
            if isinstance(old_rel, str) and isinstance(new_rel, str):
                if old_rel == new_rel:
                    should_remove = False
                    break
            elif isinstance(old_rel, dict) and isinstance(new_rel, dict):
                if old_rel.get("node_id") == new_rel.get("node_id") and old_rel.get("map_id") == new_rel.get("map_id"):
                    should_remove = False
                    break
        
        # 如果需要刪除，從目標節點的關聯中移除源節點
        if should_remove and isinstance(old_rel, dict):
            old_target_node_id = old_rel.get("node_id")
            old_target_map_id = old_rel.get("map_id") or source_map.id
            
            if old_target_node_id:
                try:
                    old_target_map = await _get_usm_map(usm_db, old_target_map_id)
                    if old_target_map:
                        old_target_node_db = await _get_usm_node(usm_db, old_target_map_id, old_target_node_id)
                        if old_target_node_db:
                            # 從舊目標節點的關聯中移除源節點
                            old_target_relations = _normalize_related_ids(old_target_node_db.related_ids)
                            old_target_filtered: List[Union[str, Dict[str, Any]]] = []
                            
                            for rel in old_target_relations:
                                should_keep = True
                                if isinstance(rel, str):
                                    if rel == source_node_db.node_id and old_target_map_id == source_map.id:
                                        should_keep = False
                                else:
                                    if rel.get("node_id") == source_node_db.node_id and (rel.get("map_id") or source_map.id) == source_map.id:
                                        should_keep = False
                                
                                if should_keep:
                                    old_target_filtered.append(rel)
                            
                            _save_node_relations(old_target_map, old_target_node_db, old_target_filtered)
                except Exception as e:
                    print(f"[PUT RELATION] Error cleaning old reverse relation: {e}")
    
    # 創建新的反向關聯
    source_node_name = source_node_db.title or ""
    
    # 為每個新關聯建立反向關聯
    for rel in prepared_relations:
        if not isinstance(rel, dict):
            continue
            
        target_node_id = rel.get("node_id")
        target_map_id = rel.get("map_id") or source_map.id
        
        if target_node_id:
            try:
                target_map = await _get_usm_map(usm_db, target_map_id)
                if target_map:
                    target_node_db = await _get_usm_node(usm_db, target_map_id, target_node_id)
                    if target_node_db:
                        await _create_reverse_relation(
                            target_node_db=target_node_db,
                            target_map=target_map,
                            source_node_id=source_node_db.node_id,
                            source_map_id=source_map.id,
                            source_map_name=source_map.name or "",
                            source_team_id=source_map.team_id,
                            source_team_name="",
                            source_node_name=source_node_name,
                            usm_db=usm_db,
                        )
            except Exception as e:
                print(f"[PUT RELATION] Error creating reverse relation: {e}")
                continue
    
    await usm_db.commit()
    print(f"[PUT RELATION] After commit")

    await usm_db.refresh(source_node_db)
    await usm_db.refresh(source_map)

    print(f"[PUT RELATION] After refresh, source_node_db.related_ids: {source_node_db.related_ids}\n")

    # 記錄審計日誌
    role_value = (
        current_user.role.value
        if hasattr(current_user.role, "value")
        else str(current_user.role)
    )
    try:
        await audit_service.log_action(
            user_id=current_user.id,
            username=current_user.username,
            role=role_value,
            action_type=ActionType.UPDATE,
            resource_type=ResourceType.USER_STORY_MAP,
            resource_id=f"{map_id}:{node_id}",
            team_id=source_map.team_id,
            details={
                "map_id": map_id,
                "node_id": node_id,
                "relation_count": len(prepared_relations),
                "source": "relations_bulk_update",
            },
            action_brief=f"{current_user.username} updated relations for node {node_id} in map {map_id} ({len(prepared_relations)} relations)",
            severity=AuditSeverity.INFO,
        )
    except Exception as exc:
        logger.warning("寫入 USM 批量關聯更新審計記錄失敗: %s", exc, exc_info=True)

    return RelationBulkUpdateResponse(relations=_normalize_related_ids(source_node_db.related_ids))


@router.post("/team/{team_id}/{map_id}/move-node")
async def move_node(
    team_id: int,
    map_id: str,
    request_data: Dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
    usm_db: AsyncSession = Depends(get_usm_db),
):
    """
    搬移節點到新的父節點

    Parameters:
    - node_id: 要搬移的節點 ID
    - new_parent_id: 新的父節點 ID
    - all_nodes_to_move: 所有要搬移的節點 ID 列表（包含源節點及所有子節點）
    """
    try:
        # 驗證權限
        await _require_usm_permission(current_user, "update", team_id)

        # 確保 map_id 為整數
        try:
            map_id_int = int(map_id)
        except Exception:
            map_id_int = map_id

        # 取得 map
        map_obj = await _get_usm_map(usm_db, map_id_int)
        if not map_obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"找不到地圖 {map_id}",
            )

        node_id = request_data.get("node_id")
        new_parent_id = request_data.get("new_parent_id")

        if not node_id or not new_parent_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="缺少必要參數: node_id 或 new_parent_id",
            )

        # 取得所有節點
        nodes = map_obj.nodes or []

        # 找到源節點和目標節點
        source_node = next((n for n in nodes if n.get("id") == node_id), None)
        target_node = next((n for n in nodes if n.get("id") == new_parent_id), None)

        if not source_node:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"找不到節點 {node_id}",
            )

        if not target_node:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"找不到目標節點 {new_parent_id}",
            )

        # 不能搬移到 User Story 節點
        if target_node.get("node_type") == "user_story":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="無法將節點搬移至 User Story 節點",
            )

        # 不能搬移到自己
        if node_id == new_parent_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="無法將節點搬移至自己",
            )

        # 檢查是否是源節點的子節點
        def is_descendant(parent_id, child_id, nodes):
            """檢查 child_id 是否是 parent_id 的後代"""
            node = next((n for n in nodes if n.get("id") == child_id), None)
            if not node:
                return False
            current = node
            while current and current.get("parent_id"):
                if current.get("parent_id") == parent_id:
                    return True
                current = next((n for n in nodes if n.get("id") == current.get("parent_id")), None)
            return False

        if is_descendant(node_id, new_parent_id, nodes):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="無法將節點搬移至其子節點",
            )

        # 執行搬移：更新源節點的 parent_id
        source_node["parent_id"] = new_parent_id

        # 以 parent_id 重新建立 children_ids（全量重建避免殘留/重複）
        node_dict = {n.get("id"): n for n in nodes}
        for n in node_dict.values():
            n["children_ids"] = []
        for nid, n in node_dict.items():
            pid = n.get("parent_id")
            if pid and pid in node_dict:
                parent_children = node_dict[pid].setdefault("children_ids", [])
                parent_children.append(nid)

        # 去重 children_ids
        for n in node_dict.values():
            if n.get("children_ids"):
                n["children_ids"] = list(dict.fromkeys(n["children_ids"]))

        # 更新邊：去掉所有 parent edge，依 parent-child 關係重建一次
        edges = [e for e in (map_obj.edges or []) if e.get("edge_type") != "parent"]
        for child_id, n in node_dict.items():
            pid = n.get("parent_id")
            if pid:
                edges.append({
                    "id": f"{pid}-{child_id}",
                    "source": pid,
                    "target": child_id,
                    "edge_type": "parent",
                })

        # 重新計算各節點的層級，避免搬移多次後 level 不一致
        visited = set()

        def assign_level(node_id: str, level: int):
            if node_id in visited:
                return
            visited.add(node_id)
            node = node_dict.get(node_id)
            if not node:
                return
            node["level"] = level
            for child_id in node.get("children_ids") or []:
                assign_level(child_id, level + 1)

        # 根節點（無 parent_id）作為起點
        root_ids = [nid for nid, n in node_dict.items() if not n.get("parent_id")]
        for rid in root_ids:
            assign_level(rid, 0)

        # 保存更改到主 JSON
        map_obj.nodes = nodes
        map_obj.edges = edges
        flag_modified(map_obj, "nodes")
        flag_modified(map_obj, "edges")
        map_obj.updated_at = datetime.utcnow()
        usm_db.add(map_obj)

        # 重新寫入 node table（先刪再全量插入），確保含子節點的搬移也被正確落盤
        await usm_db.execute(
            delete(UserStoryMapNodeDB).where(UserStoryMapNodeDB.map_id == map_id_int)
        )

        new_node_rows = []
        for n in nodes:
            new_node_rows.append(
                UserStoryMapNodeDB(
                    map_id=map_id_int,
                    node_id=n.get("id"),
                    title=n.get("title"),
                    description=n.get("description"),
                    node_type=n.get("node_type"),
                    parent_id=n.get("parent_id"),
                    children_ids=n.get("children_ids") or [],
                    related_ids=n.get("related_ids") or [],
                    comment=n.get("comment"),
                    jira_tickets=n.get("jira_tickets") or [],
                    team=n.get("team"),
                    aggregated_tickets=n.get("aggregated_tickets") or [],
                    position_x=float(n.get("position_x", 0) or 0),
                    position_y=float(n.get("position_y", 0) or 0),
                    level=n.get("level", 0),
                    as_a=n.get("as_a"),
                    i_want=n.get("i_want"),
                    so_that=n.get("so_that"),
                    updated_at=datetime.utcnow(),
                )
            )

        usm_db.add_all(new_node_rows)

        await usm_db.commit()

        # 記錄審計日誌
        role_value = (
            current_user.role.value
            if hasattr(current_user.role, "value")
            else str(current_user.role)
        )
        try:
            await audit_service.log_action(
                user_id=current_user.id,
                username=current_user.username,
                role=role_value,
                action_type=ActionType.UPDATE,
                resource_type=ResourceType.USER_STORY_MAP,
                resource_id=f"{map_id}:{node_id}",
                team_id=team_id,
                details={
                    "action": "move_node",
                    "source_node_id": node_id,
                    "new_parent_id": new_parent_id,
                    "old_parent_id": old_parent_id,
                    "source": "move_node_api",
                },
                action_brief=f"{current_user.username} moved node {node_id} to parent {new_parent_id}",
                severity=AuditSeverity.INFO,
            )
        except Exception as exc:
            logger.warning("寫入 USM 搬移節點審計記錄失敗: %s", exc, exc_info=True)

        return {
            "success": True,
            "message": "節點搬移成功",
            "node_id": node_id,
            "new_parent_id": new_parent_id,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("搬移節點失敗: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"搬移節點失敗: {str(exc)}",
        )


# ============================================================================
# USM 文字模式 API Endpoints
# ============================================================================

from pydantic import BaseModel


class USMTextImportRequest(BaseModel):
    """USM 文字匯入請求"""
    text: str
    replace_existing: bool = False  # 是否取代現有節點


class USMTextImportResponse(BaseModel):
    """USM 文字匯入回應"""
    success: bool
    nodes_count: int
    message: str
    errors: Optional[List[str]] = None


class USMTextExportResponse(BaseModel):
    """USM 文字匯出回應"""
    text: str
    nodes_count: int


@router.post("/{map_id}/import-text", response_model=USMTextImportResponse)
async def import_usm_text(
    map_id: int,
    request: USMTextImportRequest,
    current_user: User = Depends(get_current_user),
    usm_db: AsyncSession = Depends(get_usm_db),
    main_db: Session = Depends(get_sync_db),
):
    """
    從 USM 文字格式匯入節點
    
    Args:
        map_id: User Story Map ID
        request: 匯入請求（包含文字內容）
        
    Returns:
        匯入結果
    """
    from app.services.usm_text_parser import (
        parse_usm_text,
        convert_usm_nodes_to_db_format,
        ParseError,
    )
    
    try:
        # 檢查 map 是否存在
        result = await usm_db.execute(
            select(UserStoryMapDB).where(UserStoryMapDB.id == map_id)
        )
        usm_map = result.scalar_one_or_none()
        
        if not usm_map:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User Story Map {map_id} 不存在"
            )
        
        # 權限檢查：僅確認 Team 存在，允許匯入
        team = main_db.execute(
            select(Team).where(Team.id == usm_map.team_id)
        ).scalar_one_or_none()
        if not team:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"團隊 {usm_map.team_id} 不存在"
            )
        
        # 解析文字
        try:
            parsed_nodes = parse_usm_text(request.text)
        except ParseError as e:
            return USMTextImportResponse(
                success=False,
                nodes_count=0,
                message=f"解析錯誤",
                errors=[f"第 {e.line_num} 行: {e.message}"]
            )
        
        if not parsed_nodes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="文字內容為空或格式錯誤，未做任何變更"
            )
        
        # 轉換為資料庫格式
        db_nodes_data = convert_usm_nodes_to_db_format(parsed_nodes, map_id)
        if not db_nodes_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="轉換後沒有可用的節點資料，未做任何變更"
            )
        has_root = any(n.get("node_type") == "root" for n in db_nodes_data)
        if not has_root:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="缺少 root 節點，未做任何變更"
            )
        
        # 構建 edges（parent / related）
        edges: List[Dict[str, Any]] = []
        seen_edges = set()
        for node_data in db_nodes_data:
            node_id = node_data.get("node_id")
            parent_id = node_data.get("parent_id")
            if parent_id:
                edge_id = f"{parent_id}->{node_id}"
                if edge_id not in seen_edges:
                    edges.append({
                        "id": edge_id,
                        "source": parent_id,
                        "target": node_id,
                        "edge_type": "parent",
                    })
                    seen_edges.add(edge_id)
            for rid in node_data.get("related_ids", []):
                rel_id = f"relation-{node_id}-{rid}"
                if rel_id not in seen_edges:
                    edges.append({
                        "id": rel_id,
                        "source": node_id,
                        "target": rid,
                        "edge_type": "related",
                    })
                    seen_edges.add(rel_id)
        
        # 如果要取代現有節點，先刪除
        if request.replace_existing:
            await usm_db.execute(
                delete(UserStoryMapNodeDB).where(
                    UserStoryMapNodeDB.map_id == map_id
                )
            )
            await usm_db.commit()
        
        try:
            # 插入新節點到 user_story_map_nodes 表
            for node_data in db_nodes_data:
                db_node = UserStoryMapNodeDB(
                    map_id=node_data['map_id'],
                    node_id=node_data['node_id'],
                    title=node_data['title'],
                    description=node_data.get('description'),
                    node_type=node_data['node_type'],
                    parent_id=node_data.get('parent_id'),
                    children_ids=node_data.get('children_ids', []),
                    related_ids=node_data.get('related_ids', []),
                    comment=node_data.get('comment'),
                    jira_tickets=node_data.get('jira_tickets', []),
                    product=node_data.get('product'),
                    team=node_data.get('team'),
                    team_tags=node_data.get('team_tags', []),
                    aggregated_tickets=node_data.get('aggregated_tickets', []),
                    position_x=node_data.get('position_x', 0),
                    position_y=node_data.get('position_y', 0),
                    level=node_data.get('level', 0),
                    as_a=node_data.get('as_a'),
                    i_want=node_data.get('i_want'),
                    so_that=node_data.get('so_that'),
                )
                usm_db.add(db_node)
            
            # 同步更新 user_story_maps 表的 nodes/edges JSON
            usm_map.nodes = db_nodes_data
            usm_map.edges = edges
            
            # 更新 user_story_maps 表的 updated_at
            usm_map.updated_at = datetime.utcnow()
            
            await usm_db.commit()
        except Exception:
            await usm_db.rollback()
            raise
        
        # 審計記錄
        try:
            await audit_service.log_action(
                usm_db,
                user_id=current_user.id,
                action_type=ActionType.CREATE,
                resource_type=ResourceType.USER_STORY_MAP,
                resource_id=str(map_id),
                team_id=usm_map.team_id,
                details={
                    "action": "import_text",
                    "nodes_count": len(parsed_nodes),
                    "replace_existing": request.replace_existing,
                },
                action_brief=f"{current_user.username} 從文字匯入 {len(parsed_nodes)} 個節點到 map {map_id}",
                severity=AuditSeverity.INFO,
            )
        except Exception as exc:
            logger.warning("寫入 USM 文字匯入審計記錄失敗: %s", exc, exc_info=True)
        
        return USMTextImportResponse(
            success=True,
            nodes_count=len(parsed_nodes),
            message=f"成功匯入 {len(parsed_nodes)} 個節點"
        )
        
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("匯入 USM 文字失敗: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"匯入失敗: {str(exc)}"
        )


@router.get("/{map_id}/export-text", response_model=USMTextExportResponse)
async def export_usm_text(
    map_id: int,
    current_user: User = Depends(get_current_user),
    usm_db: AsyncSession = Depends(get_usm_db),
    main_db: Session = Depends(get_sync_db),
):
    """
    匯出 User Story Map 為文字格式
    
    Args:
        map_id: User Story Map ID
        
    Returns:
        USM 文字格式內容
    """
    from app.services.usm_text_parser import export_to_usm_text
    from sqlalchemy.exc import SQLAlchemyError

    try:
        # 檢查 map 是否存在
        result = await usm_db.execute(
            select(UserStoryMapDB).where(UserStoryMapDB.id == map_id)
        )
        usm_map = result.scalar_one_or_none()
        
        if not usm_map:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User Story Map {map_id} 不存在"
            )
        
        # 權限檢查（簡化：僅確認 team 存在）
        team = main_db.execute(
            select(Team).where(Team.id == usm_map.team_id)
        ).scalar_one_or_none()
        if not team:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"團隊 {usm_map.team_id} 不存在"
            )
        
        nodes_db = []
        try:
            nodes_db = main_db.execute(
                select(UserStoryMapNodeDB)
                .where(UserStoryMapNodeDB.map_id == map_id)
                .order_by(UserStoryMapNodeDB.level, UserStoryMapNodeDB.position_x)
            ).scalars().all()
        except SQLAlchemyError:
            nodes_db = []
        
        nodes_data = []
        if nodes_db:
            for node in nodes_db:
                node_dict = {
                    'node_id': node.node_id,
                    'title': node.title,
                    'description': node.description,
                    'node_type': node.node_type,
                    'parent_id': node.parent_id,
                    'children_ids': node.children_ids or [],
                    'related_ids': node.related_ids or [],
                    'comment': node.comment,
                    'jira_tickets': node.jira_tickets or [],
                    'product': node.product,
                    'team': node.team,
                    'team_tags': node.team_tags or [],
                    'aggregated_tickets': node.aggregated_tickets or [],
                    'position_x': node.position_x,
                    'position_y': node.position_y,
                    'level': node.level,
                    'as_a': node.as_a,
                    'i_want': node.i_want,
                    'so_that': node.so_that,
                }
                nodes_data.append(node_dict)
        else:
            # fallback: usm_map.nodes JSON
            if usm_map.nodes:
                for node in usm_map.nodes:
                    node_dict = dict(node)
                    node_dict['node_id'] = node_dict.get('node_id') or node_dict.get('id')
                    nodes_data.append(node_dict)
        
        if not nodes_data:
            return USMTextExportResponse(
                text="# 此地圖沒有任何節點\n",
                nodes_count=0
            )
        
        # 匯出為文字
        text = export_to_usm_text(nodes_data, indent_size=2)
        
        # 審計記錄
        try:
            await audit_service.log_action(
                main_db,
                user_id=current_user.id,
                action_type=ActionType.READ,
                resource_type=ResourceType.USER_STORY_MAP,
                resource_id=str(map_id),
                team_id=usm_map.team_id,
                details={
                    "action": "export_text",
                    "nodes_count": len(nodes_data),
                },
                action_brief=f"{current_user.username} 匯出 map {map_id} 為文字格式",
                severity=AuditSeverity.INFO,
            )
        except Exception as exc:
            logger.warning("寫入 USM 文字匯出審計記錄失敗: %s", exc, exc_info=True)
        
        return USMTextExportResponse(
            text=text,
            nodes_count=len(nodes_data)
        )
        
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("匯出 USM 文字失敗: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"匯出失敗: {str(exc)}"
        )
