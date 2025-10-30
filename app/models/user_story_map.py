"""
User Story Map 資料模型
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class NodeType(str, Enum):
    """節點類型"""
    EPIC = "epic"
    FEATURE = "feature"
    USER_STORY = "user_story"
    TASK = "task"


class UserStoryMapNode(BaseModel):
    """User Story Map 節點"""
    id: str
    title: str
    description: Optional[str] = None
    node_type: NodeType = NodeType.USER_STORY
    parent_id: Optional[str] = None
    children_ids: List[str] = Field(default_factory=list)
    related_ids: List[str] = Field(default_factory=list)
    comment: Optional[str] = None
    jira_tickets: List[str] = Field(default_factory=list)
    product: Optional[str] = None
    team: Optional[str] = None
    position_x: float = 0
    position_y: float = 0
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
