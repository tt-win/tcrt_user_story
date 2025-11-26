"""
LLM Context API

提供專為 LLM (Large Language Model) 與 Text Embedding 設計的資料端點。
此模組負責將系統內的結構化資料（Test Case, USM 等）轉換為語意化、
適合向量化的文本格式，並過濾掉不必要的 UI/系統中繼資料。
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional, Dict, Any
from datetime import datetime
import json
from pydantic import BaseModel

from app.database import get_db
from app.auth.dependencies import get_current_user
from app.auth.models import UserRole, PermissionType
from app.auth.permission_service import permission_service
from app.models.database_models import (
    User, Team, TestCaseLocal, 
    TestCaseSet, TestCaseSection
)
from app.models.user_story_map_db import (
    get_usm_db, 
    UserStoryMapDB, 
    UserStoryMapNodeDB
)

router = APIRouter(prefix="/llm-context", tags=["llm-context"])

# ==================== Models ====================

class EmbeddingDocument(BaseModel):
    """通用 Embedding 文件格式"""
    id: str
    resource_type: str  # 'test_case', 'usm_node'
    text: str           # 用於 Embedding 的主要文本
    metadata: Dict[str, Any] # 額外的過濾用欄位 (team_id, priority, etc.)
    updated_at: Optional[datetime]

class ContextResponse(BaseModel):
    """API 回應格式"""
    items: List[EmbeddingDocument]
    total: int
    generated_at: datetime = datetime.utcnow()

# ==================== Helper Functions ====================

def format_test_case_text(tc: TestCaseLocal) -> str:
    """將 Test Case 轉換為語意化文本"""
    parts = []
    
    # 標題
    parts.append(f"標題: {tc.title}")
    
    # 前置條件
    if tc.precondition:
        parts.append(f"前置條件: {tc.precondition}")
    
    # 步驟與預期結果 (嘗試合併閱讀)
    if tc.steps:
        parts.append(f"測試步驟: {tc.steps}")
    
    if tc.expected_result:
        parts.append(f"預期結果: {tc.expected_result}")
        
    return "\n".join(parts)

def build_usm_node_path(
    node: UserStoryMapNodeDB, 
    node_map: Dict[str, UserStoryMapNodeDB]
) -> str:
    """建構 USM 節點的階層路徑字串 (Root > Parent > Node)"""
    path = [node.title]
    current = node
    
    # 向上追溯父節點 (最多追溯 5 層避免無窮迴圈)
    depth = 0
    while current.parent_id and depth < 5:
        parent = node_map.get(current.parent_id)
        if parent:
            path.insert(0, parent.title)
            current = parent
        else:
            break
        depth += 1
        
    return " > ".join(path)

def format_usm_node_text(
    node: UserStoryMapNodeDB, 
    path_str: str,
    map_name: str,
    children_summaries: List[str] = None,
    related_nodes: List[str] = None,
    jira_tickets: List[str] = None
) -> str:
    """將 USM Node 轉換為語意化文本"""
    parts = []
    
    # 上下文路徑
    parts.append(f"地圖: {map_name}")
    parts.append(f"路徑: {path_str}")
    
    # 節點內容
    parts.append(f"名稱: {node.title}")
    
    if node.description:
        parts.append(f"描述: {node.description}")
    
    if node.node_type:
        node_type_map = {
            "feature_category": "Feature",
            "user_story": "Story",
            "root": "Root"
        }
        type_str = node_type_map.get(node.node_type, node.node_type)
        parts.append(f"類型: {type_str}")
        
    # User Story 特有欄位
    if node.node_type == 'user_story':
        if node.as_a:
            parts.append(f"角色 (As a): {node.as_a}")
        if node.i_want:
            parts.append(f"需求 (I want): {node.i_want}")
        if node.so_that:
            parts.append(f"目的 (So that): {node.so_that}")
            
    if node.comment:
        parts.append(f"備註: {node.comment}")
    
    # 增強資訊：子節點摘要
    if children_summaries:
        parts.append("\n[子功能/User Stories]")
        for child in children_summaries:
            parts.append(f"- {child}")
            
    # 增強資訊：關聯節點
    if related_nodes:
        parts.append("\n[關聯節點]")
        for related in related_nodes:
            parts.append(f"- {related}")
            
    # 增強資訊：JIRA Tickets
    if jira_tickets:
        parts.append("\n[JIRA]")
        for ticket in jira_tickets:
            parts.append(f"- {ticket}")
        
    return "\n".join(parts)

# ==================== Endpoints ====================

@router.get("/test-cases", response_model=ContextResponse)
async def get_test_cases_context(
    team_id: int,
    since: Optional[datetime] = Query(None, description="僅回傳此時間後更新的資料"),
    limit: int = Query(1000, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    獲取測試案例的 Embedding 上下文資料
    
    - 權限: 需要該團隊的 READ 權限
    - 內容: 將標題、步驟、預期結果合併為單一語意化文本
    """
    # 權限檢查
    if current_user.role != UserRole.SUPER_ADMIN:
        perm = await permission_service.check_team_permission(
            current_user.id, team_id, PermissionType.READ, current_user.role
        )
        if not perm.has_permission:
            raise HTTPException(status_code=403, detail="無權限存取此團隊資料")

    # 查詢資料
    query = select(TestCaseLocal).where(TestCaseLocal.team_id == team_id)
    
    if since:
        query = query.where(TestCaseLocal.updated_at >= since)
        
    query = query.limit(limit)
    
    result = await db.execute(query)
    test_cases = result.scalars().all()
    
    # 獲取團隊名稱
    team_result = await db.execute(select(Team).where(Team.id == team_id))
    team = team_result.scalar_one_or_none()
    team_name = team.name if team else f"Team {team_id}"
    
    documents = []
    for tc in test_cases:
        # 解析 JIRA/TCG Tickets
        tcg_tickets = []
        try:
            if tc.tcg_json:
                data = json.loads(tc.tcg_json)
                if isinstance(data, list):
                    tcg_tickets = [str(t) for t in data if t]
                elif isinstance(data, str):
                    tcg_tickets = [data]
            elif tc.raw_fields_json:
                # 嘗試從 raw_fields 解析
                raw = json.loads(tc.raw_fields_json)
                # 常見的欄位名稱嘗試
                for key in ['jira_tickets', 'jira', 'tcg_tickets', 'tcg', 'tickets']:
                    if key in raw:
                        val = raw[key]
                        if isinstance(val, list):
                            tcg_tickets = [str(t) for t in val if t]
                        elif isinstance(val, str):
                            tcg_tickets = [val]
                        break
        except Exception:
            pass

        doc = EmbeddingDocument(
            id=str(tc.id),
            resource_type="test_case",
            text=format_test_case_text(tc),
            metadata={
                "team_id": team_id,
                "team_name": team_name,
                "test_case_number": tc.test_case_number,
                "priority": tc.priority.value if hasattr(tc.priority, 'value') else tc.priority,
                "set_id": tc.test_case_set_id,
                "lark_record_id": tc.lark_record_id,
                "tcg_tickets": tcg_tickets,
                # 分開儲存欄位以利混合搜尋與 RAG 結構化
                "title": tc.title,
                "precondition": tc.precondition,
                "steps": tc.steps,
                "expected_result": tc.expected_result
            },
            updated_at=tc.updated_at
        )
        documents.append(doc)
        
    return ContextResponse(items=documents, total=len(documents))


@router.get("/usm", response_model=ContextResponse)
async def get_usm_context(
    team_id: int,
    map_id: Optional[int] = Query(None, description="指定地圖 ID (選填)"),
    since: Optional[datetime] = Query(None, description="僅回傳此時間後更新的資料"),
    usm_db: AsyncSession = Depends(get_usm_db),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    獲取 User Story Map 節點的 Embedding 上下文資料
    
    - 權限: 需要該團隊的 READ 權限
    - 內容: 包含地圖名稱、節點路徑 (Epic > Feature > Story) 與節點詳細描述
    """
    # 權限檢查
    if current_user.role != UserRole.SUPER_ADMIN:
        perm = await permission_service.check_team_permission(
            current_user.id, team_id, PermissionType.READ, current_user.role
        )
        if not perm.has_permission:
            raise HTTPException(status_code=403, detail="無權限存取此團隊資料")

    # 1. 獲取地圖資訊
    map_query = select(UserStoryMapDB).where(UserStoryMapDB.team_id == team_id)
    if map_id:
        map_query = map_query.where(UserStoryMapDB.id == map_id)
        
    map_result = await usm_db.execute(map_query)
    maps = map_result.scalars().all()
    
    if not maps:
        return ContextResponse(items=[], total=0)
        
    map_ids = [m.id for m in maps]
    map_names = {m.id: m.name for m in maps}
    
    # 獲取團隊名稱
    team_result = await db.execute(select(Team).where(Team.id == team_id))
    team = team_result.scalar_one_or_none()
    team_name = team.name if team else f"Team {team_id}"
    
    # 2. 獲取節點資訊
    node_query = select(UserStoryMapNodeDB).where(
        UserStoryMapNodeDB.map_id.in_(map_ids)
    )
    
    if since:
        node_query = node_query.where(UserStoryMapNodeDB.updated_at >= since)
        
    node_result = await usm_db.execute(node_query)
    nodes = node_result.scalars().all()
    
    # 為了建立路徑，需要先將同地圖的節點建立索引
    # MapID -> {NodeID -> Node}
    nodes_by_map: Dict[int, Dict[str, UserStoryMapNodeDB]] = {}
    
    # 為了確保路徑完整，如果是增量更新(since)，我們可能需要額外查詢父節點
    # 但為了效能與簡化，這裡假設若父節點不在本次查詢結果中，則只顯示當前節點標題
    # 若要完整支援增量更新時的路徑還原，需要更複雜的查詢邏輯 (先取出所有節點結構)
    
    # 實作策略：先取出該地圖"所有"節點來建立結構樹，但只回傳符合 since 條件的節點
    # 這樣才能保證路徑 (Breadcrumb) 正確
    
    all_nodes_query = select(
        UserStoryMapNodeDB.map_id, 
        UserStoryMapNodeDB.node_id, 
        UserStoryMapNodeDB.parent_id, 
        UserStoryMapNodeDB.title,
        UserStoryMapNodeDB.node_type
    ).where(
        UserStoryMapNodeDB.map_id.in_(map_ids)
    )
    all_nodes_res = await usm_db.execute(all_nodes_query)
    
    # 輕量化節點結構用於路徑查找與子節點關聯
    class LightNode:
        def __init__(self, title, parent_id, node_type):
            self.title = title
            self.parent_id = parent_id
            self.node_type = node_type
            
    structure_map: Dict[int, Dict[str, LightNode]] = {}
    
    for row in all_nodes_res:
        mid, nid, pid, title, ntype = row
        if mid not in structure_map:
            structure_map[mid] = {}
        structure_map[mid][nid] = LightNode(title, pid, ntype)
        
    documents = []
    for node in nodes:
        # 略過根節點，通常無語意價值
        if node.node_type == 'root':
            continue
            
        # 建構路徑
        current_structure = structure_map.get(node.map_id, {})
        
        path_segments = [node.title]
        curr_pid = node.parent_id
        depth = 0
        
        while curr_pid and depth < 5:
            parent = current_structure.get(curr_pid)
            if parent:
                path_segments.insert(0, parent.title)
                curr_pid = parent.parent_id
            else:
                break
            depth += 1
            
        path_str = " > ".join(path_segments)
        map_name = map_names.get(node.map_id, "Unknown Map")
        
        # 準備增強資訊
        # 1. 子節點摘要
        children_summaries = []
        if node.children_ids:
            for child_id in node.children_ids:
                child = current_structure.get(child_id)
                if child:
                    type_label = "Story" if child.node_type == "user_story" else "Feature"
                    children_summaries.append(f"{child.title} ({type_label})")
        
        # 2. 關聯節點摘要
        related_nodes_list = []
        if node.related_ids:
            for rel in node.related_ids:
                # related_ids 可能是 string (legacy) 或 dict
                rel_node_id = None
                rel_map_id = node.map_id
                
                if isinstance(rel, str):
                    rel_node_id = rel
                elif isinstance(rel, dict):
                    rel_node_id = rel.get("node_id") or rel.get("nodeId")
                    rel_map_id = rel.get("map_id") or rel.get("mapId") or node.map_id
                
                if rel_node_id:
                    # 嘗試在當前地圖結構中查找
                    if rel_map_id == node.map_id:
                        rel_node = current_structure.get(rel_node_id)
                        if rel_node:
                            type_label = "Story" if rel_node.node_type == "user_story" else "Feature"
                            related_nodes_list.append(f"{rel_node.title} ({type_label})")
                        else:
                            related_nodes_list.append(f"ID: {rel_node_id} (Unknown)")
                    else:
                        # 跨地圖關聯 (這裡簡化處理，不跨地圖查詢名稱以免效能問題)
                        # 若需要更完整資訊，可考慮將跨地圖節點名稱緩存到 related_ids 結構中
                        display_title = rel.get("display_title") if isinstance(rel, dict) else rel_node_id
                        related_nodes_list.append(f"{display_title} (External Map {rel_map_id})")

        # 3. JIRA Tickets
        jira_tickets = node.jira_tickets if node.jira_tickets else []

        # 4. 提取 ID 列表供 RAG 用戶端擴展使用
        raw_children_ids = node.children_ids if isinstance(node.children_ids, list) else []
        
        raw_related_ids = []
        if node.related_ids and isinstance(node.related_ids, list):
            for rel in node.related_ids:
                if isinstance(rel, str):
                    raw_related_ids.append(rel)
                elif isinstance(rel, dict):
                    nid = rel.get("node_id") or rel.get("nodeId")
                    if nid:
                        raw_related_ids.append(nid)

        doc = EmbeddingDocument(
            id=f"{node.map_id}:{node.node_id}", # 複合 ID
            resource_type="usm_node",
            text=format_usm_node_text(
                node, path_str, map_name,
                children_summaries=children_summaries,
                related_nodes=related_nodes_list,
                jira_tickets=jira_tickets
            ),
            metadata={
                "team_id": team_id,
                "team_name": team_name,
                "map_id": node.map_id,
                "map_name": map_name,
                "node_type": node.node_type,
                "level": node.level,
                "node_id": node.node_id, # 方便 client 端比對
                "children_ids": raw_children_ids, # 結構化擴展用
                "related_node_ids": raw_related_ids, # 結構化擴展用
                # 分開儲存欄位以利混合搜尋與 RAG 結構化
                "title": node.title,
                "description": node.description,
                "as_a": node.as_a,
                "i_want": node.i_want,
                "so_that": node.so_that,
                "jira_tickets": jira_tickets
            },
            updated_at=node.updated_at
        )
        documents.append(doc)
        
    return ContextResponse(items=documents, total=len(documents))