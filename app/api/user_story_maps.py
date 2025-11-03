"""
User Story Map API 路由
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, or_, and_
from sqlalchemy.orm.attributes import flag_modified
from typing import List, Optional
from datetime import datetime
import uuid

from app.models.user_story_map import (
    UserStoryMapCreate,
    UserStoryMapUpdate,
    UserStoryMapResponse,
    UserStoryMapNode,
    UserStoryMapEdge,
    SearchNodeResult,
    RelationCreateRequest,
    RelationDeleteRequest,
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
from app.database import get_db

router = APIRouter(prefix="/user-story-maps", tags=["user-story-maps"])


def _normalize_related_ids(related_ids):
    """將 related_ids 從舊格式（字串）轉換為新格式（物件）以支援向下相容"""
    if not related_ids:
        return []
    
    normalized = []
    for rel_id in related_ids:
        if isinstance(rel_id, str):
            normalized.append(rel_id)
        elif isinstance(rel_id, dict):
            normalized.append(rel_id)
    return normalized


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
    include_external: bool = Query(False, description="是否搜尋外部地圖"),
    exclude_node_id: Optional[str] = Query(None, description="排除的節點ID"),
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

    if team_id:
        query = query.where(UserStoryMapNodeDB.map_id.in_(
            select(UserStoryMapDB.id).where(UserStoryMapDB.team_id == team_id)
        ))

    result = await usm_db.execute(query)
    nodes = result.scalars().all()

    # 排除指定的節點
    if exclude_node_id:
        nodes = [node for node in nodes if node.node_id != exclude_node_id]

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
        # Map legacy node_type values to new enum values
        processed_nodes = []
        for node in (map_db.nodes or []):
            node_copy = dict(node)
            # Map legacy node_type values
            legacy_mapping = {
                'epic': 'feature_category',
                'feature': 'feature_category',
                'task': 'user_story'
            }
            if node_copy.get('node_type') in legacy_mapping:
                node_copy['node_type'] = legacy_mapping[node_copy['node_type']]
            # Ensure node_type exists and is valid
            if not node_copy.get('node_type'):
                node_copy['node_type'] = 'feature_category'
            processed_nodes.append(node_copy)

        nodes = [UserStoryMapNode(**node) for node in processed_nodes]
        edges = [UserStoryMapEdge(**edge) for edge in (map_db.edges or [])]
        
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

    # Map legacy node_type values to new enum values
    processed_nodes = []
    for node in (map_db.nodes or []):
        node_copy = dict(node)
        # Map legacy node_type values
        legacy_mapping = {
            'epic': 'feature_category',
            'feature': 'feature_category',
            'task': 'user_story'
        }
        if node_copy.get('node_type') in legacy_mapping:
            node_copy['node_type'] = legacy_mapping[node_copy['node_type']]
        # Ensure node_type exists and is valid
        if not node_copy.get('node_type'):
            node_copy['node_type'] = 'feature_category'
        # Ensure related_ids format
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
    
    if map_data.edges is not None:
        map_db.edges = [edge.dict() for edge in map_data.edges]
    
    map_db.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(map_db)
    
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
    """刪除 User Story Map"""
    result = await db.execute(
        select(UserStoryMapDB).where(UserStoryMapDB.id == map_id)
    )
    map_db = result.scalar_one_or_none()
    
    if not map_db:
        raise HTTPException(status_code=404, detail="User Story Map not found")
    
    await _require_usm_permission(current_user, "delete", map_db.team_id)

    await db.delete(map_db)
    await db.commit()
    
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
    await db.commit()
    
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
    
    print(f"\n[API] POST relation called - map_id={map_id}, node_id={node_id}, target_node={request.target_node_id}, target_map={request.target_map_id}")
    
    source_map_result = await usm_db.execute(
        select(UserStoryMapDB).where(UserStoryMapDB.id == map_id)
    )
    source_map = source_map_result.scalar_one_or_none()
    
    if not source_map:
        raise HTTPException(status_code=404, detail="Source map not found")
    
    await _require_usm_permission(current_user, "update", source_map.team_id)
    
    target_map_result = await usm_db.execute(
        select(UserStoryMapDB).where(UserStoryMapDB.id == request.target_map_id)
    )
    target_map = target_map_result.scalar_one_or_none()
    
    if not target_map:
        raise HTTPException(status_code=404, detail="Target map not found")
    
    await _require_usm_permission(current_user, "view", target_map.team_id)
    
    target_node_result = await usm_db.execute(
        select(UserStoryMapNodeDB).where(
            and_(
                UserStoryMapNodeDB.map_id == request.target_map_id,
                UserStoryMapNodeDB.node_id == request.target_node_id
            )
        )
    )
    target_node = target_node_result.scalar_one_or_none()
    
    if not target_node:
        raise HTTPException(status_code=404, detail="Target node not found")
    
    team_result = await db.execute(
        select(Team).where(Team.id == target_map.team_id)
    )
    target_team = team_result.scalar_one_or_none()
    
    source_node_db_result = await usm_db.execute(
        select(UserStoryMapNodeDB).where(
            and_(
                UserStoryMapNodeDB.map_id == map_id,
                UserStoryMapNodeDB.node_id == node_id
            )
        )
    )
    source_node_db = source_node_db_result.scalar_one_or_none()
    
    if not source_node_db:
        raise HTTPException(status_code=404, detail="Source node not found")
    print(f"[API] Source node found: {source_node_db.node_id}, current related_ids: {source_node_db.related_ids}")
    
    relation_id = str(uuid.uuid4())
    
    related_node = {
        "relation_id": relation_id,
        "node_id": request.target_node_id,
        "map_id": request.target_map_id,
        "map_name": target_map.name,
        "team_id": target_map.team_id,
        "team_name": target_team.name if target_team else "Unknown",
        "display_title": target_node.title or "",
    }
    
    print(f"[API] Creating relation: {related_node}")
    
    if source_node_db.related_ids is None:
        source_node_db.related_ids = []
    
    # Create new list to trigger SQLAlchemy change detection
    updated_related_ids = [*source_node_db.related_ids, related_node]
    source_node_db.related_ids = updated_related_ids
    source_node_db.updated_at = datetime.utcnow()
    
    print(f"[API] After reassign, related_ids: {source_node_db.related_ids}")
    
    # Flag as modified for SQLAlchemy
    flag_modified(source_node_db, "related_ids")
    
    print(f"[API] Flag modified called")

    # 同步更新主 Map JSON
    map_nodes = source_map.nodes or []
    updated = False
    for idx, entry in enumerate(map_nodes):
        entry_id = entry.get("id") if isinstance(entry, dict) else None
        if entry_id == node_id:
            entry_copy = dict(entry)
            entry_copy["related_ids"] = _normalize_related_ids(source_node_db.related_ids)
            map_nodes[idx] = entry_copy
            updated = True
            break
    if not updated:
        map_nodes.append({
            "id": node_id,
            "title": source_node_db.title,
            "description": source_node_db.description,
            "node_type": source_node_db.node_type,
            "parent_id": source_node_db.parent_id,
            "children_ids": source_node_db.children_ids or [],
            "related_ids": _normalize_related_ids(source_node_db.related_ids),
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
    
    
    print(f"[API] Before commit, source_node_db.related_ids: {source_node_db.related_ids}")
    print(f"[API] Committing to database...")
    
    await usm_db.commit()
    
    print(f"[API] After commit")
    
    await usm_db.refresh(source_map)
    await usm_db.refresh(source_node_db)
    
    print(f"[API] After refresh, source_node_db.related_ids: {source_node_db.related_ids}")
    print(f"[API] Returning relation_id: {relation_id}\n")
    
    return {"relation_id": relation_id, "message": "Relation created successfully"}


@router.delete("/{map_id}/nodes/{node_id}/relations/{relation_id}")
async def delete_relation(
    map_id: int,
    node_id: str,
    relation_id: str,
    current_user: User = Depends(get_current_user),
    usm_db: AsyncSession = Depends(get_usm_db),
):
    """刪除節點關聯"""
    
    source_map_result = await usm_db.execute(
        select(UserStoryMapDB).where(UserStoryMapDB.id == map_id)
    )
    source_map = source_map_result.scalar_one_or_none()
    
    if not source_map:
        raise HTTPException(status_code=404, detail="Source map not found")
    
    await _require_usm_permission(current_user, "update", source_map.team_id)
    
    source_node_db_result = await usm_db.execute(
        select(UserStoryMapNodeDB).where(
            and_(
                UserStoryMapNodeDB.map_id == map_id,
                UserStoryMapNodeDB.node_id == node_id
            )
        )
    )
    source_node_db = source_node_db_result.scalar_one_or_none()
    
    if not source_node_db:
        raise HTTPException(status_code=404, detail="Source node not found")
    
    if source_node_db.related_ids:
        source_node_db.related_ids = [
            rel for rel in source_node_db.related_ids 
            if isinstance(rel, str) or rel.get("relation_id") != relation_id
        ]
        source_node_db.updated_at = datetime.utcnow()

        # 同步更新主 Map JSON
        map_nodes = source_map.nodes or []
        for idx, entry in enumerate(map_nodes):
            entry_id = entry.get("id") if isinstance(entry, dict) else None
            if entry_id == node_id:
                entry_copy = dict(entry)
                entry_copy["related_ids"] = _normalize_related_ids(source_node_db.related_ids)
                map_nodes[idx] = entry_copy
                break
        source_map.nodes = map_nodes
        source_map.updated_at = datetime.utcnow()
        flag_modified(source_map, "nodes")
        
        await usm_db.commit()
    
    return {"message": "Relation deleted successfully"}
