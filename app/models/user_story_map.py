"""
User Story Map 資料模型
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Union
from datetime import datetime
from enum import Enum


class NodeType(str, Enum):
    """節點類型"""
    ROOT = "root"
    FEATURE_CATEGORY = "feature_category"
    USER_STORY = "user_story"


class RelatedNode(BaseModel):
    """相關節點物件"""
    relation_id: str
    node_id: str
    map_id: int
    map_name: str
    team_id: int
    team_name: str
    display_title: str


class UserStoryMapNode(BaseModel):
    """User Story Map 節點"""
    id: str
    title: str
    description: Optional[str] = None
    node_type: NodeType
    parent_id: Optional[str] = None
    children_ids: List[str] = Field(default_factory=list)
    related_ids: Union[List[str], List[Union[str, RelatedNode]]] = Field(default_factory=list)
    comment: Optional[str] = None
    jira_tickets: List[str] = Field(default_factory=list)
    team: Optional[str] = None
    aggregated_tickets: List[str] = Field(default_factory=list)
    position_x: float = 0
    position_y: float = 0
    level: int = 0
    # BDD fields for User Story nodes
    as_a: Optional[str] = None
    i_want: Optional[str] = None
    so_that: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UserStoryMapEdge(BaseModel):
    """User Story Map 連接線"""
    id: str
    source: str
    target: str
    edge_type: str = "default"  # parent, child, related


class UserStoryMap(BaseModel):
    """User Story Map"""
    id: Optional[int] = None
    team_id: int
    name: str
    description: Optional[str] = None
    nodes: List[UserStoryMapNode] = Field(default_factory=list)
    edges: List[UserStoryMapEdge] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UserStoryMapCreate(BaseModel):
    """建立 User Story Map 請求"""
    team_id: int
    name: str
    description: Optional[str] = None


class UserStoryMapUpdate(BaseModel):
    """更新 User Story Map 請求"""
    name: Optional[str] = None
    description: Optional[str] = None
    nodes: Optional[List[UserStoryMapNode]] = None
    edges: Optional[List[UserStoryMapEdge]] = None


class UserStoryMapResponse(BaseModel):
    """User Story Map 回應"""
    id: int
    team_id: int
    name: str
    description: Optional[str]
    nodes: List[UserStoryMapNode]
    edges: List[UserStoryMapEdge]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SearchNodeResult(BaseModel):
    """搜尋節點結果"""
    node_id: str
    node_title: str
    node_type: Optional[str] = None
    map_id: int
    map_name: str
    team_id: int
    team_name: str
    breadcrumb: Optional[str] = None
    description: Optional[str] = None


class RelationCreateRequest(BaseModel):
    """建立關聯請求"""
    target_node_id: str
    target_map_id: int


class RelationDeleteRequest(BaseModel):
    """刪除關聯請求"""
    relation_id: str


class RelationPayload(BaseModel):
    """批次更新關聯時的單一項目資料"""
    relation_id: Optional[str] = Field(None, description="關聯 ID，未提供時由後端產生")
    node_id: str = Field(..., description="目標節點 ID")
    map_id: Optional[int] = Field(None, description="目標地圖 ID，預設為來源地圖")
    map_name: Optional[str] = Field(None, description="目標地圖名稱（顯示用）")
    team_id: Optional[int] = Field(None, description="目標團隊 ID，用於權限檢查")
    team_name: Optional[str] = Field(None, description="目標團隊名稱")
    display_title: Optional[str] = Field(None, description="顯示名稱，預設為目標節點標題")


class RelationBulkUpdateRequest(BaseModel):
    """批次更新關聯請求"""
    relations: List[Union[str, RelationPayload]] = Field(default_factory=list, description="要設定的關聯列表")


class RelationBulkUpdateResponse(BaseModel):
    """批次更新關聯回應"""
    relations: List[Union[str, RelationPayload]] = Field(default_factory=list, description="更新後的關聯列表")
