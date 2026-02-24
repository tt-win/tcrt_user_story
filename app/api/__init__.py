"""
API 路由初始化
"""

from fastapi import APIRouter
from .auth import router as auth_router
from .users import router as users_router
from .teams import router as teams_router
from .test_run_configs import router as test_run_configs_router, search_router as test_run_configs_search_router
from .test_cases import router as test_cases_router
from .test_runs import router as test_runs_router
from .test_run_sets import router as test_run_sets_router
from .attachments import router as attachments_router
from .tcg import router as tcg_router
from .test_run_items import router as test_run_items_router
from .contacts import router as contacts_router
from .team_sync import router as team_sync_router
from .organization_sync import router as organization_sync_router
from .jira import router as jira_router
from .lark_groups import router as lark_groups_router
from .lark_users import router as lark_users_router
from .admin import router as admin_router
from .version import router as version_router
from .permissions import router as permissions_router
from .audit import router as audit_router
from .team_statistics import router as team_statistics_router
from .test_case_sets import router as test_case_sets_router
from .test_case_sections import router as test_case_sections_router
from .test_case_helper import router as test_case_helper_router

# 創建主 API 路由器
api_router = APIRouter()

# 包含所有子路由
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(teams_router)
api_router.include_router(test_run_configs_router)
api_router.include_router(test_run_configs_search_router)  # 新增搜尋路由
api_router.include_router(test_cases_router)
api_router.include_router(test_runs_router)
api_router.include_router(test_run_sets_router)
api_router.include_router(attachments_router)
api_router.include_router(tcg_router)
api_router.include_router(test_run_items_router)
api_router.include_router(contacts_router)
api_router.include_router(team_sync_router)
api_router.include_router(organization_sync_router)
api_router.include_router(jira_router)
api_router.include_router(lark_groups_router)
api_router.include_router(lark_users_router)
api_router.include_router(admin_router)
api_router.include_router(version_router)
api_router.include_router(permissions_router)
api_router.include_router(audit_router)
api_router.include_router(team_statistics_router)
api_router.include_router(test_case_sets_router)  # Test Case Set 路由
api_router.include_router(test_case_sections_router)  # Test Case Section 路由
api_router.include_router(test_case_helper_router)  # Test Case Helper 路由

# 可以在此添加其他 API 路由
