"""
版本 API
提供伺服器版本時間戳查詢功能
"""

from fastapi import APIRouter
from pydantic import BaseModel
from app.services.version_service import get_version_service

router = APIRouter(prefix="/version", tags=["version"])

class VersionResponse(BaseModel):
    server_timestamp: int
    server_time: str

@router.get("/", response_model=VersionResponse)
async def get_server_version():
    """取得伺服器版本時間戳"""
    version_service = get_version_service()
    timestamp = version_service.get_server_timestamp()

    # 轉換為可讀的時間格式
    from datetime import datetime
    server_time = datetime.fromtimestamp(timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S')

    return VersionResponse(
        server_timestamp=timestamp,
        server_time=server_time
    )

@router.post("/refresh")
async def refresh_server_version():
    """手動刷新伺服器版本時間戳（用於開發測試）"""
    version_service = get_version_service()
    new_timestamp = version_service.refresh_timestamp()

    from datetime import datetime
    server_time = datetime.fromtimestamp(new_timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S')

    return {
        "message": "伺服器版本時間戳已刷新",
        "server_timestamp": new_timestamp,
        "server_time": server_time
    }