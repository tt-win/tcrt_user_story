"""
API 路由初始化
"""

from fastapi import APIRouter
from .teams import router as teams_router
from .test_run_configs import router as test_run_configs_router, search_router as test_run_configs_search_router
from .test_cases import router as test_cases_router
from .test_runs import router as test_runs_router
from .attachments import router as attachments_router
from .tcg import router as tcg_router
from .test_run_items import router as test_run_items_router
from .contacts import router as contacts_router
from .team_sync import router as team_sync_router
from .organization_sync import router as organization_sync_router
from .jira import router as jira_router

# 創建主 API 路由器
api_router = APIRouter()

# 包含所有子路由
api_router.include_router(teams_router)
api_router.include_router(test_run_configs_router)
api_router.include_router(test_run_configs_search_router)  # 新增搜尋路由
api_router.include_router(test_cases_router)
api_router.include_router(test_runs_router)
api_router.include_router(attachments_router)
api_router.include_router(tcg_router)
api_router.include_router(test_run_items_router)
api_router.include_router(contacts_router)
api_router.include_router(team_sync_router)
api_router.include_router(organization_sync_router)
api_router.include_router(jira_router)

# 可以在此添加其他 API 路由
