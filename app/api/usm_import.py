"""
USM 匯入 API 端點 - 完整實現
"""
import time
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from pydantic import BaseModel

from app.auth.dependencies import get_current_user
from app.models.database_models import User
from app.models.user_story_map_db import get_usm_db, UserStoryMapDB, UserStoryMapNodeDB
from app.services.lark_usm_import_service import LarkUSMImportService
from app.services.lark_client import LarkClient
from app.config import settings

router = APIRouter(prefix="/api/usm-import", tags=["usm-import"])


class USMImportRequest(BaseModel):
    """USM 匯入請求"""
    lark_url: str
    root_name: str
    team_id: int


class USMImportResponse(BaseModel):
    """USM 匯入響應"""
    success: bool
    message: str
    map_id: Optional[int] = None
    total_nodes: Optional[int] = None


async def _save_imported_usm(
    usm_db: AsyncSession,
    usm_data: dict,
    current_user: User
) -> int:
    """
    將轉換後的 USM 數據保存到數據庫
    
    Args:
        usm_db: 數據庫會話
        usm_data: 轉換後的 USM 數據
        current_user: 當前用戶
        
    Returns:
        創建的 map_id
    """
    try:
        # 1. 生成節點位置
        nodes = usm_data["nodes"]
        _assign_node_positions(nodes)
        edges = _generate_edges_from_nodes(nodes)
        
        # 2. 創建 USM Map
        new_map = UserStoryMapDB(
            team_id=usm_data["team_id"],
            name=usm_data["map_name"],
            description=f"從 Lark 匯入 - 包含 {len(nodes)} 個節點",
            nodes=nodes,
            edges=edges,
        )
        
        usm_db.add(new_map)
        await usm_db.flush()  # 獲取 map_id
        map_id = new_map.id
        
        # 3. 為每個節點創建 NodeDB 記錄（用於搜索）
        for node in nodes:
            node_db = UserStoryMapNodeDB(
                map_id=map_id,
                node_id=node["id"],
                title=node.get("title", ""),
                description=node.get("description", ""),
                node_type=node.get("node_type", "feature_category"),
                parent_id=node.get("parent_id"),
                children_ids=node.get("children_ids", []),
                related_ids=node.get("related_ids", []),
                comment="",
                jira_tickets=node.get("jira_tickets", []),
                team=None,
                aggregated_tickets=[],
                position_x=float(node.get("position_x", 0)),
                position_y=float(node.get("position_y", 0)),
                level=node.get("level", 0),
                as_a=node.get("as_a", ""),
                i_want=node.get("i_want", ""),
                so_that=node.get("so_that", ""),
            )
            usm_db.add(node_db)
        
        # 4. 提交所有更改
        await usm_db.commit()
        await usm_db.refresh(new_map)
        
        return map_id
        
    except Exception as e:
        await usm_db.rollback()
        raise Exception(f"保存 USM 到數據庫失敗: {str(e)}")


def _assign_node_positions(nodes: list, base_x: float = 250.0, base_y: float = 250.0):
    """
    為節點分配位置（按層級）
    
    Args:
        nodes: 節點列表
        base_x: 基礎 X 坐標
        base_y: 基礎 Y 坐標
    """
    # 建立節點查找表
    node_map = {node["id"]: node for node in nodes}
    
    # 計算每個節點的層級
    level_map = {}
    
    def get_level(node_id: str) -> int:
        if node_id in level_map:
            return level_map[node_id]
        
        node = node_map.get(node_id)
        if not node or node["parent_id"] is None:
            level = 0
        else:
            parent_level = get_level(node["parent_id"])
            level = parent_level + 1
        
        level_map[node_id] = level
        return level
    
    # 按層級分組節點
    nodes_by_level = {}
    for node in nodes:
        level = get_level(node["id"])
        if level not in nodes_by_level:
            nodes_by_level[level] = []
        nodes_by_level[level].append(node)
    
    # 分配位置
    for level, level_nodes in nodes_by_level.items():
        y = base_y + (level * 100)  # 垂直間距
        num_nodes = len(level_nodes)
        x_spacing = 150 if num_nodes > 1 else 0
        start_x = base_x - (num_nodes - 1) * x_spacing / 2
        
        for idx, node in enumerate(level_nodes):
            node["position_x"] = float(start_x + idx * x_spacing)
            node["position_y"] = float(y)
            node["level"] = level


def _generate_edges_from_nodes(nodes: list) -> list:
    """
    根據節點的父子關係產生邊資料

    只要節點有 parent_id，就建立對應的 parent edge。
    若 children_ids 存在但 parent_id 遺漏，也會嘗試使用 children_ids 建立邊。
    """
    edges = []
    edge_ids = set()
    node_map = {node.get("id"): node for node in nodes}

    # 先依照 parent_id 建立邊
    for node in nodes:
        parent_id = node.get("parent_id")
        child_id = node.get("id")
        if parent_id and child_id:
            edge_id = f"edge_{parent_id}_{child_id}"
            if edge_id not in edge_ids:
                edge_ids.add(edge_id)
                edges.append({
                    "id": edge_id,
                    "source": parent_id,
                    "target": child_id,
                    "edge_type": "parent",
                })

    # 再依 children_ids 補強，避免 parent_id 遺漏導致無邊
    for node in nodes:
        parent_id = node.get("id")
        for child_id in node.get("children_ids") or []:
            if child_id not in node_map:
                continue
            edge_id = f"edge_{parent_id}_{child_id}"
            if edge_id in edge_ids:
                continue
            edge_ids.add(edge_id)
            edges.append({
                "id": edge_id,
                "source": parent_id,
                "target": child_id,
                "edge_type": "parent",
            })

    return edges


@router.post("/import-from-lark", response_model=USMImportResponse)
async def import_usm_from_lark(
    request: USMImportRequest,
    current_user: User = Depends(get_current_user),
    usm_db: AsyncSession = Depends(get_usm_db),
):
    """
    從 Lark 多維表格匯入 USM
    
    完整流程：
    1. 驗證 URL 和輸入
    2. 獲取 Lark 表格數據
    3. 轉換為 USM 格式
    4. 保存到數據庫
    """
    
    try:
        # 1. 驗證輸入
        if not request.lark_url or not request.root_name or not request.team_id:
            raise HTTPException(status_code=400, detail="缺少必要參數")
        
        # 2. 初始化 Lark 客戶端
        if not settings.lark.app_id or not settings.lark.app_secret:
            raise HTTPException(status_code=500, detail="Lark 認證信息未配置")
        
        lark_client = LarkClient(settings.lark.app_id, settings.lark.app_secret)
        lark_service = LarkUSMImportService(lark_client)
        
        # 3. 獲取 Lark 數據
        lark_records = await lark_service.fetch_lark_table(request.lark_url)
        
        if not lark_records:
            raise HTTPException(status_code=400, detail="無法獲取 Lark 表格數據")
        
        # 4. 轉換為 USM 格式
        usm_data = lark_service.convert_to_usm_nodes(
            lark_records,
            request.root_name,
            request.team_id
        )
        
        # 5. 驗證數據
        is_valid, error_msg = lark_service.validate_import_data(usm_data)
        if not is_valid:
            raise HTTPException(status_code=400, detail=error_msg)
        
        # 6. 保存到數據庫
        map_id = await _save_imported_usm(usm_db, usm_data, current_user)
        
        return USMImportResponse(
            success=True,
            message=f"USM 匯入成功，共 {len(usm_data['nodes'])} 個節點",
            map_id=map_id,
            total_nodes=len(usm_data["nodes"])
        )
        
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.error(f"USM 匯入失敗: {str(e)}", exc_info=True)
        return USMImportResponse(
            success=False,
            message=f"匯入失敗: {str(e)}"
        )


@router.get("/lark-preview")
async def preview_lark_table(
    lark_url: str,
    current_user: User = Depends(get_current_user),
):
    """
    預覽 Lark 表格結構
    不保存任何數據，只用於驗證和預覽
    """
    
    try:
        # 初始化 Lark 客戶端
        if not settings.lark.app_id or not settings.lark.app_secret:
            raise Exception("Lark 認證信息未配置")
        
        lark_client = LarkClient(settings.lark.app_id, settings.lark.app_secret)
        lark_service = LarkUSMImportService(lark_client)
        
        # 獲取 Lark 數據
        lark_records = await lark_service.fetch_lark_table(lark_url)
        
        if not lark_records:
            raise Exception("無法獲取 Lark 表格數據")
        
        # 扁平化嵌套記錄計算總數（避免重複計算）
        total_count = 0
        seen_story_nos = set()
        def count_records(records_list):
            nonlocal total_count
            for record in records_list:
                story_no = record.get('story_no', '')
                # 避免重複計算同一筆記錄
                if story_no and story_no in seen_story_nos:
                    continue
                if story_no:
                    seen_story_nos.add(story_no)
                
                total_count += 1
                children = record.get("children", [])
                if children:
                    count_records(children)
        
        count_records(lark_records)
        
        # 返回預覽數據（限制數量）
        preview_records = lark_records[:3]  # 只預覽前 3 條頂層記錄
        
        return {
            "success": True,
            "total_records": total_count,
            "preview_records": preview_records,
            "structure": {
                "Features": "title",
                "Criteria": "description",
                "As a": "as_a",
                "I want": "i_want",
                "TCG": "jira_tickets",
                "Parent Tickets": "parent_id"
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
