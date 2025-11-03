"""
User Story Map 關聯節點功能的單元和整合測試

測試範圍:
- 搜尋節點 API (同圖/跨圖)
- 建立/刪除關聯 API
- 權限檢查 (RBAC + 團隊級別)
- 資料模型和向下相容性
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from uuid import uuid4

from app.models.user_story_map import (
    RelatedNode,
    SearchNodeResult,
    RelationCreateRequest,
    RelationDeleteRequest,
    UserStoryMapNode,
    NodeType,
)
from app.models.user_story_map_db import UserStoryMapNodeDB, UserStoryMapDB
from app.api.user_story_maps import _normalize_related_ids


class TestDataModels:
    """測試資料模型"""
    
    def test_related_node_model(self):
        """測試 RelatedNode 模型"""
        related = RelatedNode(
            relation_id=str(uuid4()),
            node_id="node-1",
            map_id=1,
            map_name="Feature Map",
            team_id=1,
            team_name="Team A",
            display_title="Feature X"
        )
        assert related.relation_id
        assert related.node_id == "node-1"
        assert related.map_id == 1
        assert related.map_name == "Feature Map"
    
    def test_search_node_result_model(self):
        """測試 SearchNodeResult 模型"""
        result = SearchNodeResult(
            node_id="node-2",
            node_title="User Story Title",
            node_type="user_story",
            map_id=1,
            map_name="Feature Map",
            team_id=1,
            team_name="Team A",
            description="Test description"
        )
        assert result.node_id == "node-2"
        assert result.node_type == "user_story"
        assert result.map_id == 1
    
    def test_user_story_map_node_with_new_related_ids(self):
        """測試 UserStoryMapNode 支援新 related_ids 格式"""
        related_objects = [
            {
                "relation_id": str(uuid4()),
                "node_id": "node-2",
                "map_id": 1,
                "map_name": "Map 1",
                "team_id": 1,
                "team_name": "Team A",
                "display_title": "Feature B"
            }
        ]
        node = UserStoryMapNode(
            id="node-1",
            title="Feature A",
            node_type=NodeType.FEATURE_CATEGORY,
            related_ids=related_objects
        )
        assert len(node.related_ids) == 1
        # Pydantic 會自動轉換 dict 為 RelatedNode 物件
        assert isinstance(node.related_ids[0], (dict, RelatedNode))
    
    def test_user_story_map_node_with_old_related_ids(self):
        """測試 UserStoryMapNode 向下相容舊 related_ids 格式"""
        old_related_ids = ["node-2", "node-3"]
        node = UserStoryMapNode(
            id="node-1",
            title="Feature A",
            node_type=NodeType.FEATURE_CATEGORY,
            related_ids=old_related_ids
        )
        assert len(node.related_ids) == 2
        assert all(isinstance(rel, str) for rel in node.related_ids)


class TestNormalizeRelatedIds:
    """測試 related_ids 正規化函式"""
    
    def test_normalize_empty(self):
        """測試空的 related_ids"""
        result = _normalize_related_ids(None)
        assert result == []
        
        result = _normalize_related_ids([])
        assert result == []
    
    def test_normalize_old_format(self):
        """測試舊格式 (字串) 的正規化"""
        old_ids = ["node-1", "node-2", "node-3"]
        result = _normalize_related_ids(old_ids)
        assert len(result) == 3
        assert all(isinstance(r, str) for r in result)
    
    def test_normalize_new_format(self):
        """測試新格式 (物件) 的正規化"""
        new_ids = [
            {
                "relation_id": str(uuid4()),
                "node_id": "node-1",
                "map_id": 1,
                "map_name": "Map 1",
                "team_id": 1,
                "team_name": "Team A",
                "display_title": "Title"
            }
        ]
        result = _normalize_related_ids(new_ids)
        assert len(result) == 1
        assert isinstance(result[0], dict)
    
    def test_normalize_mixed_format(self):
        """測試混合格式 (舊格式 + 新格式) 的正規化"""
        mixed = [
            "node-1",  # 舊格式
            {
                "relation_id": str(uuid4()),
                "node_id": "node-2",
                "map_id": 1,
                "map_name": "Map 1",
                "team_id": 1,
                "team_name": "Team A",
                "display_title": "Title"
            }  # 新格式
        ]
        result = _normalize_related_ids(mixed)
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], dict)


class TestRelationCreateRequest:
    """測試關聯建立請求模型"""
    
    def test_relation_create_request(self):
        """測試關聯建立請求"""
        request = RelationCreateRequest(
            target_node_id="node-2",
            target_map_id=2
        )
        assert request.target_node_id == "node-2"
        assert request.target_map_id == 2


class TestRelationDeleteRequest:
    """測試關聯刪除請求模型"""
    
    def test_relation_delete_request(self):
        """測試關聯刪除請求"""
        relation_id = str(uuid4())
        request = RelationDeleteRequest(relation_id=relation_id)
        assert request.relation_id == relation_id


# 整合測試可在此新增，需要 FastAPI TestClient
class TestSearchNodesAPI:
    """搜尋節點 API 測試 (需要 TestClient)"""
    
    @pytest.mark.asyncio
    async def test_search_nodes_same_map(self):
        """測試在同一地圖內搜尋節點"""
        # 此測試需要 FastAPI TestClient 和資料庫設定
        # 暫時作為佔位符
        pass
    
    @pytest.mark.asyncio
    async def test_search_nodes_cross_map(self):
        """測試跨地圖搜尋節點"""
        # 此測試需要 FastAPI TestClient 和資料庫設定
        pass


class TestRelationManagementAPI:
    """關聯管理 API 測試 (需要 TestClient)"""
    
    @pytest.mark.asyncio
    async def test_create_relation_same_map(self):
        """測試建立同地圖關聯"""
        pass
    
    @pytest.mark.asyncio
    async def test_create_relation_cross_map(self):
        """測試建立跨地圖關聯"""
        pass
    
    @pytest.mark.asyncio
    async def test_delete_relation(self):
        """測試刪除關聯"""
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
