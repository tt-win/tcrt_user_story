"""
API 路由初始化
"""

from fastapi import APIRouter
from .teams import router as teams_router
from .test_run_configs import router as test_run_configs_router
from .test_cases import router as test_cases_router
from .test_runs import router as test_runs_router
from .attachments import router as attachments_router
from .tcg import router as tcg_router

# 創建主 API 路由器
api_router = APIRouter()

# 包含所有子路由
api_router.include_router(teams_router)
api_router.include_router(test_run_configs_router)
api_router.include_router(test_cases_router)
api_router.include_router(test_runs_router)
api_router.include_router(attachments_router)
api_router.include_router(tcg_router)

# 可以在此添加其他 API 路由