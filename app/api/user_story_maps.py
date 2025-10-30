"""
User Story Map API 路由
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, or_
from typing import List, Optional
import json
from datetime import datetime

from app.models.user_story_map import (
    UserStoryMap,
    UserStoryMapCreate,
    UserStoryMapUpdate,
    UserStoryMapResponse,
    UserStoryMapNode,
    UserStoryMapEdge,
)
from app.models.user_story_map_db import (
    get_usm_db,
    UserStoryMapDB,
    UserStoryMapNodeDB,
)
from app.auth.dependencies import get_current_user
from app.models.database_models import User

router = APIRouter(prefix="/user-story-maps", tags=["user-story-maps"])


@router.get("/team/{team_id}", response_model=List[UserStoryMapResponse])
async def get_team_maps(
    team_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_usm_db),
):
    """獲取團隊的所有 User Story Maps"""
    result = await db.execute(
        select(UserStoryMapDB).where(UserStoryMapDB.team_id == team_id)
    )
    maps = result.scalars().all()
    
    response_maps = []
    for map_db in maps:
        nodes = [UserStoryMapNode(**node) for node in (map_db.nodes or [])]
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
    
    nodes = [UserStoryMapNode(**node) for node in (map_db.nodes or [])]
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
    new_map = UserStoryMapDB(
        team_id=map_data.team_id,
        name=map_data.name,
        description=map_data.description,
        nodes=[],
        edges=[],
    )
    
    db.add(new_map)
    await db.commit()
    await db.refresh(new_map)
    
    return UserStoryMapResponse(
        id=new_map.id,
        team_id=new_map.team_id,
        name=new_map.name,
        description=new_map.description,
        nodes=[],
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
    
    if map_data.name is not None:
        map_db.name = map_data.name
    if map_data.description is not None:
        map_db.description = map_data.description
    if map_data.nodes is not None:
        map_db.nodes = [node.dict() for node in map_data.nodes]
        
        # 更新節點索引表
        await db.execute(
            delete(UserStoryMapNodeDB).where(UserStoryMapNodeDB.map_id == map_id)
        )
        
        for node in map_data.nodes:
            node_db = UserStoryMapNodeDB(
                map_id=map_id,
                node_id=node.id,
                title=node.title,
                description=node.description,
                node_type=node.node_type,
                parent_id=node.parent_id,
                children_ids=node.children_ids,
                related_ids=node.related_ids,
                comment=node.comment,
                jira_tickets=node.jira_tickets,
                product=node.product,
                team=node.team,
                position_x=node.position_x,
                position_y=node.position_y,
            )
            db.add(node_db)
    
    if map_data.edges is not None:
        map_db.edges = [edge.dict() for edge in map_data.edges]
    
    map_db.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(map_db)
    
    nodes = [UserStoryMapNode(**node) for node in (map_db.nodes or [])]
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
    
    await db.delete(map_db)
    await db.commit()
    
    return {"message": "User Story Map deleted successfully"}


@router.get("/{map_id}/search")
async def search_nodes(
    map_id: int,
    q: Optional[str] = Query(None, description="搜尋關鍵字"),
    node_type: Optional[str] = Query(None, description="節點類型"),
    product: Optional[str] = Query(None, description="產品"),
    team: Optional[str] = Query(None, description="團隊"),
    jira_ticket: Optional[str] = Query(None, description="JIRA Ticket"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_usm_db),
):
    """搜尋 User Story Map 節點"""
    query = select(UserStoryMapNodeDB).where(UserStoryMapNodeDB.map_id == map_id)
    
    if q:
        query = query.where(
            or_(
                UserStoryMapNodeDB.title.contains(q),
                UserStoryMapNodeDB.description.contains(q),
                UserStoryMapNodeDB.comment.contains(q),
            )
        )
    
    if node_type:
        query = query.where(UserStoryMapNodeDB.node_type == node_type)
    
    if product:
        query = query.where(UserStoryMapNodeDB.product == product)
    
    if team:
        query = query.where(UserStoryMapNodeDB.team == team)
    
    if jira_ticket:
        # JSON 欄位搜尋需要特殊處理
        result = await db.execute(query)
        nodes = result.scalars().all()
        nodes = [n for n in nodes if jira_ticket in (n.jira_tickets or [])]
        return [
            {
                "node_id": node.node_id,
                "title": node.title,
                "description": node.description,
                "node_type": node.node_type,
                "product": node.product,
                "team": node.team,
                "jira_tickets": node.jira_tickets,
            }
            for node in nodes
        ]
    
    result = await db.execute(query)
    nodes = result.scalars().all()
    
    return [
        {
            "node_id": node.node_id,
            "title": node.title,
            "description": node.description,
            "node_type": node.node_type,
            "product": node.product,
            "team": node.team,
            "jira_tickets": node.jira_tickets,
        }
        for node in nodes
    ]
