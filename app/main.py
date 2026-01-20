from fastapi import FastAPI, Request, Query, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from pathlib import Path
import logging
import os
from typing import Optional
from sqlalchemy.orm import Session

app = FastAPI(
    title="Test Case Repository Web Tool",
    description="A web-based test case management system with Lark integration",
    version="1.0.0"
)

# 啟用 GZip 壓縮（預設對 >= 1KB 的回應進行壓縮）
try:
    from starlette.middleware.gzip import GZipMiddleware
    # 注意：對於已壓縮格式（如 png/jpg/zip）壓縮收益有限；minimum_size 提高可避免浪費 CPU
    app.add_middleware(GZipMiddleware, minimum_size=1024)
except Exception as _e:
    logging.warning(f"GZipMiddleware 啟用失敗（不影響服務）：{_e}")

from app.middlewares import AuditMiddleware
from app.database import get_sync_db
from app.models.database_models import TestCaseLocal

app.add_middleware(AuditMiddleware)

# 配置日誌
logging.basicConfig(level=logging.INFO)

# 初始化版本服務
from app.services.version_service import get_version_service
from app.audit import init_audit_database, cleanup_audit_database, audit_service
version_service = get_version_service()
logging.info(f"應用啟動，伺服器版本時間戳: {version_service.get_server_timestamp()}")

# 設置靜態文件和模板路徑 - 必須在其他路由之前
BASE_DIR = Path.cwd()
STATIC_DIR = BASE_DIR / "app" / "static"
TEMPLATES_DIR = BASE_DIR / "app" / "templates"
REPORT_DIR = BASE_DIR / "generated_report"
TMP_REPORT_DIR = REPORT_DIR / ".tmp"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
# 對外提供報告的靜態目錄
app.mount("/reports", StaticFiles(directory=str(REPORT_DIR), html=True), name="reports")
# 對外提供附件的靜態目錄（本地上傳檔案）
# 優先使用 config.yaml 的 attachments.root_dir；若未設定則回退至專案內的 attachments 目錄
PROJECT_ROOT = Path(__file__).resolve().parents[1]
try:
    from app.config import settings
    cfg_root = settings.attachments.root_dir if getattr(settings, 'attachments', None) else ''
    ATTACHMENTS_DIR = Path(cfg_root) if cfg_root else (PROJECT_ROOT / "attachments")
except Exception:
    ATTACHMENTS_DIR = PROJECT_ROOT / "attachments"
ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/attachments", StaticFiles(directory=str(ATTACHMENTS_DIR), html=False), name="attachments")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# 包含 API 路由
from app.api import api_router
from app.api.system import router as system_router
from app.api.user_story_maps import router as usm_router
from app.api.usm_import import router as usm_import_router
from app.api.llm_context import router as llm_context_router
from app.api.adhoc import router as adhoc_router

app.include_router(api_router, prefix="/api")
app.include_router(system_router)
app.include_router(usm_router, prefix="/api")
app.include_router(usm_import_router)
app.include_router(llm_context_router, prefix="/api")
app.include_router(adhoc_router, prefix="/api")

# 前端頁面路由
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/team-management", response_class=HTMLResponse)
async def team_management(request: Request):
    return templates.TemplateResponse("team_management.html", {"request": request})

@app.get("/adhoc-runs/{run_id}/execution", response_class=HTMLResponse)
async def adhoc_run_execution(request: Request, run_id: int):
    return templates.TemplateResponse("adhoc_test_run_execution.html", {"request": request})

@app.get("/audit-logs", response_class=HTMLResponse)
async def audit_logs(request: Request):
    return templates.TemplateResponse("audit_logs.html", {"request": request})

@app.get("/test-case-sets", response_class=HTMLResponse)
async def test_case_set_list(request: Request):
    """Test Case Set 選擇頁面"""
    return templates.TemplateResponse("test_case_set_list.html", {"request": request})

@app.get("/test-case-management", response_class=HTMLResponse)
async def test_case_management(
    request: Request,
    set_id: Optional[int] = Query(None),
    tc: Optional[str] = Query(None, description="Test case number for direct access"),
    team_id: Optional[int] = Query(None, description="Team ID for resolving test case set"),
    db: Session = Depends(get_sync_db),
):
    """Test Case Management 頁面 - 需要先選擇 Set"""
    resolved_set_id = set_id

    # 允許透過 test case 編號直接解析所屬的 Test Case Set，避免彈窗被重導
    if resolved_set_id is None and tc and team_id:
        normalized_tc = tc.strip()
        if normalized_tc:
            test_case = (
                db.query(TestCaseLocal)
                .filter(TestCaseLocal.team_id == team_id)
                .filter(TestCaseLocal.test_case_number == normalized_tc)
                .first()
            )
            if test_case:
                resolved_set_id = test_case.test_case_set_id

    # 如果仍然無法取得 set_id，維持原本導向邏輯
    if resolved_set_id is None:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/test-case-sets", status_code=303)

    return templates.TemplateResponse(
        "test_case_management.html",
        {"request": request, "set_id": resolved_set_id},
    )

@app.get("/test-run-management", response_class=HTMLResponse)
async def test_run_management(request: Request):
    return templates.TemplateResponse("test_run_management.html", {"request": request})

@app.get("/test-run-execution", response_class=HTMLResponse)
async def test_run_execution(request: Request):
    return templates.TemplateResponse("test_run_execution.html", {"request": request})

@app.get("/test-case-reference", response_class=HTMLResponse)
async def test_case_reference(request: Request):
    return templates.TemplateResponse("test_case_reference.html", {"request": request})

@app.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/setup", response_class=HTMLResponse)
async def setup(request: Request):
    """系統初始化設置頁面"""
    return templates.TemplateResponse("system_setup_standalone.html", {"request": request})


@app.get("/first-login-setup", response_class=HTMLResponse)
async def first_login_setup(request: Request):
    """首次登入設定頁面"""
    return templates.TemplateResponse("first_login_setup.html", {"request": request})


@app.get("/profile", response_class=HTMLResponse)
async def profile(request: Request):
    """個人資料頁面"""
    return templates.TemplateResponse("profile.html", {"request": request})

@app.get("/team-statistics", response_class=HTMLResponse)
async def team_statistics(request: Request):
    """團隊數據統計頁面"""
    return templates.TemplateResponse("team_statistics.html", {"request": request})

@app.get("/user-story-map/{team_id}", response_class=HTMLResponse)
@app.get("/user-story-map/{team_id}/{map_id}", response_class=HTMLResponse)
async def user_story_map(request: Request, team_id: int, map_id: int = None):
    """User Story Map 頁面"""
    context = {"request": request, "team_id": team_id}
    if map_id is not None:
        context["map_id"] = map_id
    return templates.TemplateResponse("user_story_map.html", context)

@app.get("/user-story-map-popup", response_class=HTMLResponse)
async def user_story_map_popup(request: Request):
    """User Story Map 彈出視圖 - 用於外部節點"""
    return templates.TemplateResponse("user_story_map_popup.html", {"request": request})

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.on_event("startup")
async def startup_event():
    """應用程式啟動事件"""
    try:
        try:
            from app.config import settings
            jira_ca_path = settings.jira.ca_cert_path if getattr(settings, 'jira', None) else ''
            if jira_ca_path:
                expanded_path = os.path.expanduser(jira_ca_path)
                if os.path.isfile(expanded_path):
                    logging.info("JIRA TLS 憑證已設定: %s", jira_ca_path)
                else:
                    logging.warning("JIRA TLS 憑證路徑不存在: %s", jira_ca_path)
            else:
                logging.info("JIRA TLS 憑證未設定，使用系統預設 CA")
        except Exception as e:
            logging.warning("讀取 JIRA TLS 憑證設定失敗: %s", e)

        # 確保報告資料夾存在
        os.makedirs(REPORT_DIR, exist_ok=True)
        os.makedirs(TMP_REPORT_DIR, exist_ok=True)
        logging.info("報告目錄已就緒: %s", REPORT_DIR)

        await init_audit_database()
        logging.info("審計資料庫初始化完成")

        # 初始化 User Story Map 資料庫
        from app.models.user_story_map_db import init_usm_db
        await init_usm_db()
        logging.info("User Story Map 資料庫初始化完成")

        # 初始化密碼加密服務
        from app.auth.password_encryption import password_encryption_service
        password_encryption_service.initialize()
        logging.info("密碼加密服務初始化完成")

        # 啟動定時任務調度器
        from app.services.scheduler import task_scheduler
        task_scheduler.start()
        logging.info("定時任務調度器已啟動")
    except Exception as e:
        logging.error(f"啟動服務失敗: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    """應用程式關閉事件"""
    try:
        # 停止定時任務調度器
        from app.services.scheduler import task_scheduler
        task_scheduler.stop()
        logging.info("定時任務調度器已停止")
    except Exception as e:
        logging.error(f"停止定時任務調度器失敗: {e}")

    try:
        await audit_service.force_flush()
        await cleanup_audit_database()
    except Exception as e:
        logging.error(f"關閉審計資料庫失敗: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9999)
