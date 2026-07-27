"""
附件下載代理 API 路由

自本機附件目錄取檔：依序嘗試 DB 記錄的路徑、`/attachments` 相對路徑、以檔名
遞迴搜尋，全部落空即回 404。此路徑不涉及任何外部服務（見 `lark-runtime-boundary`
spec）。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
import json
import logging

from app.database import get_db
from app.db_access.main import (
    MainAccessBoundary,
    get_main_access_boundary,
)
from app.services.attachment_storage import (
    get_attachments_root_dir,
    resolve_attachment_metadata_path,
    resolve_relative_attachment_path,
)

# 配置日志
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/attachments", tags=["attachments"])


@router.get("/teams/{team_id}/attachments/download")
async def download_attachment_proxy(
    team_id: int,
    file_url: str = None,
    file_token: str = None,
    filename: str = None,
    config_id: int = None,
    item_id: int = None,
    file_index: int = None,
    db: AsyncSession = Depends(get_db),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    """
    附件下載代理 API

    優先級：
    1. 若提供 config_id + item_id + file_index，從資料庫直接查詢文件路徑（無遞迴搜尋）- 最快
    2. 若 file_url 以 /attachments 開頭，直接從本地檔案系統讀取並回傳
    3. 若只有 file_token，嘗試在本地 attachments 目錄中以檔名搜尋（較慢，向後相容）
    4. 其餘情況才代理 Lark 下載
    """
    import mimetypes

    # 優先級 1：通過資料庫直接查詢文件路徑（無遞迴搜尋）- 最優化
    if config_id is not None and item_id is not None and file_index is not None:
        try:
            from app.models.database_models import TestRunItem as TestRunItemDB

            def _fetch_item(sync_db: Session):
                item = (
                    sync_db.query(TestRunItemDB)
                    .filter(
                        TestRunItemDB.team_id == team_id,
                        TestRunItemDB.config_id == config_id,
                        TestRunItemDB.id == item_id,
                    )
                    .first()
                )
                return item.execution_results_json if item else None

            execution_results_json = await main_boundary.run_sync_read(_fetch_item)

            if execution_results_json is not None:
                try:
                    execution_results = json.loads(execution_results_json or "[]")
                    if 0 <= file_index < len(execution_results):
                        file_meta = execution_results[file_index]
                        try:
                            file_path = resolve_attachment_metadata_path(file_meta, allow_legacy_absolute=True)
                        except Exception:
                            file_path = None

                        if file_path and file_path.exists() and file_path.is_file():
                            media_type = mimetypes.guess_type(str(file_path))[0] or file_meta.get(
                                "type", "application/octet-stream"
                            )

                            def iterfile():
                                with open(file_path, "rb") as f:
                                    yield from f

                            return StreamingResponse(iterfile(), media_type=media_type)
                except (json.JSONDecodeError, IndexError, KeyError) as e:
                    logger.warning(f"無法解析執行結果: {e}")
        except Exception as e:
            logger.warning(f"資料庫查詢失敗: {e}")
            # 降級到其他方法

    # 優先級 2：本地附件：/attachments 相對路徑
    try:
        if file_url and file_url.strip().startswith("/attachments"):
            attachments_root = get_attachments_root_dir()
            # 防止目錄穿越
            rel = file_url[len("/attachments/") :].lstrip("/") if file_url else ""
            disk_path = resolve_relative_attachment_path(rel)
            if not disk_path.exists() or not disk_path.is_file():
                raise HTTPException(status_code=404, detail="附件不存在")

            media_type = mimetypes.guess_type(str(disk_path))[0] or "application/octet-stream"

            def iterfile():
                with open(disk_path, "rb") as f:
                    yield from f

            return StreamingResponse(iterfile(), media_type=media_type)
    except HTTPException:
        raise
    except Exception:
        # 本地嘗試失敗則進入下一步
        pass

    # 優先級 3：只有 token：嘗試在本地 attachments 目錄以檔名搜尋（較慢，向後相容）
    # 注意：此方法使用遞迴搜尋，如果有大量附件會很慢
    # 建議前端在呼叫此 API 時提供 config_id + item_id + file_index 以使用優先級 1 的快速路徑
    try:
        if file_token and (not file_url):
            logger.warning(f"使用較慢的遞迴搜尋查找檔案: {file_token}，建議前端提供 config_id/item_id/file_index")
            attachments_root = get_attachments_root_dir()
            # 在整個 attachments 目錄中搜尋相符檔名（stored_name）
            target = None
            if attachments_root.exists():
                for p in attachments_root.rglob("*"):
                    if p.is_file() and p.name == file_token:
                        target = p
                        break
            if target and target.exists():
                # 驗證路徑安全性
                try:
                    target.resolve().relative_to(attachments_root.resolve())
                except ValueError:
                    logger.warning(f"路徑穿越嘗試: {target}")
                    raise HTTPException(status_code=403, detail="禁止存取")

                media_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"

                def iterfile():
                    with open(target, "rb") as f:
                        yield from f

                return StreamingResponse(iterfile(), media_type=media_type)
    except HTTPException:
        raise
    except Exception:
        pass

    # 本機來源全部落空：附件不存在。
    # 舊有的 Lark 代理下載回退已由 `purge-dead-lark-runtime-code` change 移除
    # （掃描確認生產資料中已無任何以 Lark 為來源的 test run 附件）。
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="附件不存在")
