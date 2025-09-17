from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from pathlib import Path
import logging
import os

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

# 配置日誌
logging.basicConfig(level=logging.INFO)

# 初始化版本服務
from app.services.version_service import get_version_service
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
app.include_router(api_router, prefix="/api")

# 前端頁面路由
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/team-management", response_class=HTMLResponse)
async def team_management(request: Request):
    return templates.TemplateResponse("team_management.html", {"request": request})

@app.get("/test-case-management", response_class=HTMLResponse)
async def test_case_management(request: Request):
    return templates.TemplateResponse("test_case_management.html", {"request": request})

@app.get("/test-run-management", response_class=HTMLResponse)
async def test_run_management(request: Request):
    return templates.TemplateResponse("test_run_management.html", {"request": request})

@app.get("/test-run-execution", response_class=HTMLResponse)
async def test_run_execution(request: Request):
    return templates.TemplateResponse("test_run_execution.html", {"request": request})

@app.get("/test-case-reference", response_class=HTMLResponse)
async def test_case_reference(request: Request):
    return templates.TemplateResponse("test_case_reference.html", {"request": request})

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.on_event("startup")
async def startup_event():
    """應用程式啟動事件"""
    try:
        # 確保資料表存在（包含新增的歷程表）
        from app.models.database_models import create_database_tables
        create_database_tables()
        logging.info("資料表檢查/建立完成")

        # 確保報告資料夾存在
        os.makedirs(REPORT_DIR, exist_ok=True)
        os.makedirs(TMP_REPORT_DIR, exist_ok=True)
        logging.info("報告目錄已就緒: %s", REPORT_DIR)

        # 啟動定時任務調度器
        from app.services.scheduler import task_scheduler
        task_scheduler.start()
        logging.info("定時任務調度器已啟動")
    except Exception as e:
        logging.error(f"啟動定時任務調度器失敗: {e}")

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9999)
