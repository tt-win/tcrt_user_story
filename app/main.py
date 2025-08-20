from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import os
from pathlib import Path

app = FastAPI(
    title="Test Case Repository Web Tool",
    description="A web-based test case management system with Lark integration",
    version="1.0.0"
)

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

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9999)