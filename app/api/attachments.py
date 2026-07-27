"""
附件下載代理 API 路由

提供附件下載代理：優先自本機附件目錄取檔，僅在本機來源全部落空時，才對仍保有
歷史 Lark 設定的 team 走 Lark 回退（見 `lark-runtime-boundary` spec）。原本將
檔案上傳至 Lark Drive 並附加到記錄的端點已由 `purge-dead-lark-runtime-code`
change 移除；附件寫入一律走本機路徑。
"""

import aiohttp
import asyncio
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from typing import Optional
import json
import logging

from app.database import get_db
from app.db_access.main import (
    MainAccessBoundary,
    create_main_access_boundary_for_session,
    get_main_access_boundary,
)
from app.models.database_models import Team as TeamDB
from app.services.lark_client import LarkClient
from app.services.attachment_storage import (
    get_attachments_root_dir,
    resolve_attachment_metadata_path,
    resolve_relative_attachment_path,
)
from app.config import settings

# 配置日志
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/attachments", tags=["attachments"])


async def get_lark_client_for_team(
    team_id: int,
    db: Optional[AsyncSession] = None,
    main_boundary: Optional[MainAccessBoundary] = None,
) -> tuple[LarkClient, TeamDB]:
    """取得團隊的 Lark Client"""
    if main_boundary is None:
        if db is None:
            raise ValueError("Either db or main_boundary must be provided")
        main_boundary = create_main_access_boundary_for_session(db)

    def _get_team(sync_db: Session):
        return sync_db.query(TeamDB).filter(TeamDB.id == team_id).first()

    team = await main_boundary.run_sync_read(_get_team)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"找不到團隊 ID {team_id}")

    # team 層級的 Lark Bitable 設定已移除；新建立的 team 不會有 wiki_token，
    # 這類 team 不可能存在 Lark 附件，直接視為找不到附件（而非回報 Lark 服務異常）。
    if not team.wiki_token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="附件不存在")

    # 建立 Lark Client
    lark_client = LarkClient(app_id=settings.lark.app_id, app_secret=settings.lark.app_secret)

    if not await asyncio.to_thread(lark_client.set_wiki_token, team.wiki_token):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="無法連接到 Lark 服務")

    return lark_client, team


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
    import urllib.parse

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

    # 優先級 4：代理 Lark 下載
    lark_client, team = await get_lark_client_for_team(team_id, db=db)
    session = None
    response = None

    async def _close_upstream():
        if response is not None:
            response.release()
        if session is not None and not session.closed:
            await session.close()

    try:
        # 決定下載 URL
        download_url = file_url
        if not download_url and file_token:
            download_url = f"https://open.larksuite.com/open-apis/drive/v1/medias/{file_token}/download"

        if not download_url:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="必須提供 file_url 或 file_token")

        # 取得 access token
        token = await asyncio.to_thread(lark_client.auth_manager.get_tenant_access_token)
        if not token:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="無法取得 Lark access token")

        # 代理下載請求
        headers = {
            "Authorization": f"Bearer {token}",
        }

        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        try:
            response = await session.get(download_url, headers=headers)
        except Exception:
            await _close_upstream()
            raise

        if response.status_code == 401:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Lark API 認證失敗")
        elif response.status_code == 404:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="附件不存在")
        elif response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Lark API 錯誤: HTTP {response.status_code}"
            )

        # 準備響應 headers
        response_headers = {}

        # 設定 Content-Type
        content_type = response.headers.get("content-type")
        if content_type:
            response_headers["Content-Type"] = content_type

        # 設定檔案名稱（處理中文檔名）
        if filename:
            # 使用 RFC 5987 標準處理非 ASCII 檔案名稱
            try:
                # 嘗試 ASCII 編碼
                filename.encode("ascii")
                response_headers["Content-Disposition"] = f'attachment; filename="{filename}"'
            except UnicodeEncodeError:
                # 包含非 ASCII 字符，使用 RFC 5987 格式
                encoded_filename = urllib.parse.quote(filename, safe="")
                response_headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{encoded_filename}"
        elif "content-disposition" in response.headers:
            response_headers["Content-Disposition"] = response.headers["content-disposition"]

        # 設定 Content-Length (如果有)
        content_length = response.headers.get("content-length")
        if content_length:
            response_headers["Content-Length"] = content_length

        # 創建流式響應
        async def generate_file_stream():
            try:
                async for chunk in response.content.iter_chunked(8192):
                    if chunk:
                        yield chunk
            finally:
                await _close_upstream()

        return StreamingResponse(generate_file_stream(), headers=response_headers)

    except HTTPException:
        await _close_upstream()
        raise
    except asyncio.TimeoutError:
        await _close_upstream()
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Lark 文件下載超時")
    except aiohttp.ClientError as e:
        await _close_upstream()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Lark 文件下載失敗: {str(e)}")
    except Exception as e:
        await _close_upstream()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"附件下載代理錯誤: {str(e)}")
