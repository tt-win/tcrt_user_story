"""
TCG API 路由

提供 TCG 搜尋和選擇功能
"""

from fastapi import APIRouter, Query, HTTPException, status, Depends
from typing import List, Optional
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.tcg_converter import tcg_converter

router = APIRouter(prefix="/tcg", tags=["tcg"])


class TCGOption(BaseModel):
    """TCG 選項模型"""
    record_id: str
    tcg_number: str
    title: str
    display_text: str


class TCGSearchResponse(BaseModel):
    """TCG 搜尋回應模型"""
    results: List[TCGOption]
    total: int


@router.get("/search", response_model=TCGSearchResponse)
async def search_tcg(
    keyword: Optional[str] = Query(None, description="搜尋關鍵字"),
    limit: int = Query(20, ge=1, le=100000, description="回傳筆數"),
    offset: int = Query(0, ge=0, description="偏移量"),
    db: AsyncSession = Depends(get_db),
):
    """搜尋 TCG 單號（從本地 SQLite 查詢，極快速度）"""
    try:
        # 直接從本地 SQLite 查詢，速度極快
        results = await tcg_converter.search_tcg_numbers(db, keyword or "", limit + offset)
        
        # 計算總數（搜尋全部結果）
        total_results = await tcg_converter.search_tcg_numbers(db, keyword or "", 999999)
        total_count = len(total_results)
        
        # 應用 offset
        if offset > 0:
            results = results[offset:]
        
        # 應用 limit
        if limit > 0:
            results = results[:limit]
        
        tcg_options = [TCGOption(**result) for result in results]
        
        return TCGSearchResponse(
            results=tcg_options,
            total=total_count
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"搜尋 TCG 失敗: {str(e)}"
        )


@router.get("/popular", response_model=TCGSearchResponse)
async def get_popular_tcg(
    limit: int = Query(20, ge=1, le=100, description="回傳筆數"),
    db: AsyncSession = Depends(get_db),
):
    """取得熱門的 TCG 單號"""
    try:
        results = await tcg_converter.get_popular_tcg_numbers(db, limit)
        
        tcg_options = [
            TCGOption(**result) for result in results
        ]
        
        return TCGSearchResponse(
            results=tcg_options,
            total=len(tcg_options)
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"取得熱門 TCG 失敗: {str(e)}"
        )


# TCG 同步端點已移除 - 不再需要依賴 TCG 轉換
# @router.post("/sync")
# async def sync_tcg_mapping():
#     """手動同步 TCG 資料從 Lark 到本地資料庫"""
#     try:
#         sync_count = tcg_converter.sync_tcg_from_lark()
#         return {
#             "success": True,
#             "message": f"成功同步 {sync_count} 筆 TCG 資料",
#             "sync_count": sync_count
#         }
#     except Exception as e:
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"同步 TCG 資料失敗: {str(e)}"
#         )

# TCG 狀態端點已移除 - 不再需要監控同步狀態
# @router.get("/status")
# async def get_tcg_status():
#     """取得 TCG 資料庫狀態"""
#     try:
#         # 取得資料庫統計
#         all_tcg = tcg_converter.search_tcg_numbers("", 999999)
#         total_count = len(all_tcg)
#
#         # 取得調度器狀態
#         from app.services.scheduler import task_scheduler
#         scheduler_status = task_scheduler.get_task_status()
#
#         return {
#             "database": {
#                 "total_records": total_count,
#                 "sample_records": all_tcg[:5] if all_tcg else []
#             },
#             "scheduler": scheduler_status
#         }
#     except Exception as e:
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"取得 TCG 狀態失敗: {str(e)}"
#         )
