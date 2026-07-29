"""Response models for the role-aware homepage dashboard."""

from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


class DashboardCurrentUser(BaseModel):
    id: int
    display_name: str


class DashboardQuickAction(BaseModel):
    key: str
    href: str
    icon: str


class DashboardResponse(BaseModel):
    dashboard_type: Literal["personal", "system_administration"]
    current_user: DashboardCurrentUser
    sections: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    quick_actions: List[DashboardQuickAction] = Field(default_factory=list)
