from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from pathlib import Path
import logging

app = FastAPI(
    title="Test Case Repository Web Tool",
    description="A web-based test case management system with Lark integration",
    version="1.0.0"
)

# 配置日誌
logging.basicConfig(level=logging.INFO)

# 設置靜態文件和模板路徑 - 必須在其他路由之前
BASE_DIR = Path.cwd()
STATIC_DIR = BASE_DIR / "app" / "static"
TEMPLATES_DIR = BASE_DIR / "app" / "templates"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
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
