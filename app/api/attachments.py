"""
附件管理 API 路由

提供檔案上傳到 Lark Drive 並附加到測試案例或測試執行記錄的功能
"""

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional
import io
import requests
import urllib.parse
import logging

from app.database import get_db, get_sync_db
from app.models.database_models import Team as TeamDB, TestRunConfig as TestRunConfigDB
from app.services.lark_client import LarkClient
from app.config import settings

# 配置日志
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/attachments", tags=["attachments"])


def get_lark_client_for_team(team_id: int, db: Session) -> tuple[LarkClient, TeamDB]:
    """取得團隊的 Lark Client"""
    team = db.query(TeamDB).filter(TeamDB.id == team_id).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到團隊 ID {team_id}"
        )
    
    # 建立 Lark Client
    lark_client = LarkClient(
        app_id=settings.lark.app_id,
        app_secret=settings.lark.app_secret
    )
    
    if not lark_client.set_wiki_token(team.wiki_token):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="無法連接到 Lark 服務"
        )
    
    return lark_client, team


@router.post("/teams/{team_id}/testcases/{record_id}/upload")
async def upload_testcase_attachment(
    team_id: int,
    record_id: str,
    file: UploadFile = File(...),
    field_name: str = Form("Attachment"),
    append: bool = Form(True),
    db: Session = Depends(get_sync_db)
):
    """
    上傳檔案到測試案例的附件欄位
    
    Args:
        team_id: 團隊 ID
        record_id: 測試案例記錄 ID
        file: 上傳的檔案
        field_name: 附件欄位名稱（預設: "Attachment"）
        append: 是否追加到現有附件（預設: True）
    """
    lark_client, team = get_lark_client_for_team(team_id, db)
    
    try:
        # 讀取檔案內容
        file_content = await file.read()
        
        if not file_content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="檔案內容不能為空"
            )
        
        # 檢查檔案大小（限制 10MB）
        max_size = 10 * 1024 * 1024  # 10MB
        if len(file_content) > max_size:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"檔案大小超過限制 ({max_size // (1024*1024)}MB)"
            )
        
        # 上傳檔案並附加到記錄
        success = lark_client.upload_and_attach_file(
            table_id=team.test_case_table_id,
            record_id=record_id,
            field_name=field_name,
            file_content=file_content,
            file_name=file.filename or "unknown_file",
            append=append
        )
        
        if success:
            return {
                "success": True,
                "message": f"檔案 '{file.filename}' 上傳成功",
                "file_name": file.filename,
                "file_size": len(file_content),
                "append_mode": append
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="檔案上傳失敗"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"檔案上傳過程發生錯誤: {str(e)}"
        )


@router.post("/teams/{team_id}/test-runs/{config_id}/records/{record_id}/upload")
async def upload_testrun_attachment(
    team_id: int,
    config_id: int,
    record_id: str,
    file: UploadFile = File(...),
    field_name: str = Form("Execution Result"),
    append: bool = Form(True),
    db: Session = Depends(get_sync_db)
):
    """
    上傳檔案到測試執行記錄（使用本地檔案系統）

    本函式已重構為使用本地檔案系統，與 test_run_items.py 的架構保持一致。
    檔案會存儲在 attachments/test-runs/{team_id}/{config_id}/{item_id}/ 目錄下。

    Args:
        team_id: 團隊 ID
        config_id: 測試執行配置 ID
        record_id: 測試執行記錄 ID（實際為 item_id）
        file: 上傳的檔案
        field_name: 附件欄位名稱（預設: "Execution Result"）
        append: 是否追加到現有附件（預設: True）
    """
    from app.models.database_models import TestRunItem as TestRunItemDB
    import os
    import re
    import json
    from pathlib import Path
    from datetime import datetime

    # 驗證團隊和配置存在
    team = db.query(TeamDB).filter(TeamDB.id == team_id).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到團隊 ID {team_id}"
        )

    config = db.query(TestRunConfigDB).filter(
        TestRunConfigDB.id == config_id,
        TestRunConfigDB.team_id == team_id
    ).first()
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到測試執行配置 ID {config_id}"
        )

    # record_id 實際對應 TestRunItem 的 ID
    try:
        item_id = int(record_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="無效的記錄 ID 格式"
        )

    # 驗證 Test Run Item 存在
    test_run_item = db.query(TestRunItemDB).filter(
        TestRunItemDB.id == item_id,
        TestRunItemDB.config_id == config_id,
        TestRunItemDB.team_id == team_id
    ).first()

    if not test_run_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到測試執行項目 ID {item_id}"
        )

    try:
        # 讀取檔案內容
        file_content = await file.read()

        if not file_content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="檔案內容不能為空"
            )

        # 檢查檔案大小（限制 10MB）
        max_size = 10 * 1024 * 1024  # 10MB
        if len(file_content) > max_size:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"檔案大小超過限制 ({max_size // (1024*1024)}MB)"
            )

        # 使用與 test_run_items.py 相同的檔案存儲邏輯
        project_root = Path(__file__).resolve().parents[2]
        base_dir = Path(settings.attachments.root_dir) if settings.attachments.root_dir else (project_root / "attachments")
        target_dir = base_dir / "test-runs" / str(team_id) / str(config_id) / str(item_id)
        target_dir.mkdir(parents=True, exist_ok=True)

        # 解析現有的執行結果檔案
        existing = []
        if test_run_item.execution_results_json:
            try:
                data = json.loads(test_run_item.execution_results_json)
                if isinstance(data, list):
                    existing = data
            except Exception:
                existing = []

        # 生成唯一檔名
        ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f")
        safe_re = re.compile(r"[^A-Za-z0-9_.\-]+")
        orig_name = file.filename or "unnamed"
        name_part = safe_re.sub("_", orig_name)
        stored_name = f"{ts}-{name_part}"
        stored_path = target_dir / stored_name

        # 寫入檔案
        with open(stored_path, "wb") as out:
            out.write(file_content)

        # 準備檔案元資料
        item_meta = {
            "name": orig_name,
            "stored_name": stored_name,
            "size": len(file_content),
            "type": file.content_type or "application/octet-stream",
            "relative_path": str(stored_path.relative_to(base_dir)),
            "absolute_path": str(stored_path),
            "uploaded_at": datetime.utcnow().isoformat(),
        }

        # 根據 append 參數決定是否追加
        if append:
            existing.append(item_meta)
        else:
            existing = [item_meta]

        # 更新資料庫記錄
        test_run_item.execution_results_json = json.dumps(existing, ensure_ascii=False)
        test_run_item.result_files_uploaded = 1 if len(existing) > 0 else 0
        test_run_item.result_files_count = len(existing)

        # 更新上傳歷史
        history = []
        if test_run_item.upload_history_json:
            try:
                history = json.loads(test_run_item.upload_history_json) or []
            except Exception:
                history = []

        history.append({
            "uploaded": 1,
            "at": datetime.utcnow().isoformat(),
            "files": [item_meta],
        })
        test_run_item.upload_history_json = json.dumps(history, ensure_ascii=False)
        test_run_item.updated_at = datetime.utcnow()

        db.commit()

        return {
            "success": True,
            "message": f"檔案 '{file.filename}' 上傳成功",
            "file_name": file.filename,
            "file_size": len(file_content),
            "append_mode": append,
            "field_name": field_name,
            "file_token": stored_name,
            "total_files": len(existing),
            "base_url": "/attachments"
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"檔案上傳過程發生錯誤: {str(e)}"
        )


@router.post("/teams/{team_id}/test-runs/{config_id}/records/{record_id}/upload-screenshot")
async def upload_testrun_screenshot(
    team_id: int,
    config_id: int,
    record_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_sync_db)
):
    """
    上傳測試執行結果截圖（使用本地檔案系統）

    專門用於上傳測試執行的截圖檔案，會自動附加到執行結果中
    """
    # 檢查檔案類型
    allowed_image_types = ["image/jpeg", "image/jpg", "image/png", "image/gif", "image/bmp"]
    if file.content_type not in allowed_image_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支援的圖片格式，支援格式: {', '.join(allowed_image_types)}"
        )

    # 使用修正後的測試執行附件上傳功能
    return await upload_testrun_attachment(
        team_id=team_id,
        config_id=config_id,
        record_id=record_id,
        file=file,
        field_name="Execution Result",
        append=True,
        db=db
    )


@router.post("/teams/{team_id}/upload-file-token")
async def upload_file_get_token(
    team_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_sync_db)
):
    """
    只上傳檔案到 Lark Drive，返回 file_token
    
    這個 API 可用於先上傳檔案，稍後再附加到記錄
    """
    lark_client, team = get_lark_client_for_team(team_id, db)
    
    try:
        # 讀取檔案內容
        file_content = await file.read()
        
        if not file_content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="檔案內容不能為空"
            )
        
        # 檢查檔案大小（限制 10MB）
        max_size = 10 * 1024 * 1024  # 10MB
        if len(file_content) > max_size:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"檔案大小超過限制 ({max_size // (1024*1024)}MB)"
            )
        
        # 只上傳檔案到 Lark Drive
        file_token = lark_client.upload_file_to_drive(
            file_content=file_content,
            file_name=file.filename or "unknown_file"
        )
        
        if file_token:
            return {
                "success": True,
                "file_token": file_token,
                "file_name": file.filename,
                "file_size": len(file_content),
                "message": "檔案上傳到 Lark Drive 成功，可使用 file_token 附加到記錄"
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="檔案上傳到 Lark Drive 失敗"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"檔案上傳過程發生錯誤: {str(e)}"
        )


@router.post("/teams/{team_id}/testcases/{record_id}/attach-token")
async def attach_file_token_to_testcase(
    team_id: int,
    record_id: str,
    file_token: str = Form(...),
    field_name: str = Form("Attachment"),
    append: bool = Form(True),
    db: Session = Depends(get_sync_db)
):
    """
    將已上傳的檔案（file_token）附加到測試案例記錄
    """
    lark_client, team = get_lark_client_for_team(team_id, db)
    
    try:
        # 取得現有附件（如果是追加模式）
        existing_file_tokens = []
        if append:
            records = lark_client.get_all_records(team.test_case_table_id)
            target_record = None
            for record in records:
                if record.get('record_id') == record_id:
                    target_record = record
                    break
            
            if target_record:
                existing_attachments = target_record.get('fields', {}).get(field_name, [])
                if isinstance(existing_attachments, list):
                    existing_file_tokens = [att.get('file_token') for att in existing_attachments 
                                          if att.get('file_token')]
        
        # 準備完整的附件列表
        all_file_tokens = existing_file_tokens + [file_token]
        
        # 更新記錄的附件欄位
        success = lark_client.update_record_attachment(
            table_id=team.test_case_table_id,
            record_id=record_id,
            field_name=field_name,
            file_tokens=all_file_tokens
        )
        
        if success:
            return {
                "success": True,
                "message": f"file_token 附加成功",
                "file_token": file_token,
                "field_name": field_name,
                "total_attachments": len(all_file_tokens)
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="file_token 附加失敗"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"附加 file_token 過程發生錯誤: {str(e)}"
        )


@router.delete("/teams/{team_id}/testcases/{record_id}/attachments/{file_token}")
async def remove_testcase_attachment(
    team_id: int,
    record_id: str,
    file_token: str,
    field_name: str = "Attachment",
    db: Session = Depends(get_sync_db)
):
    """
    從測試案例記錄中移除指定的附件
    
    Args:
        team_id: 團隊 ID
        record_id: 測試案例記錄 ID
        file_token: 要移除的附件 file_token
        field_name: 附件欄位名稱（預設: "Attachment"）
    """
    lark_client, team = get_lark_client_for_team(team_id, db)
    
    try:
        # 取得現有記錄
        records = lark_client.get_all_records(team.test_case_table_id)
        target_record = None
        for record in records:
            if record.get('record_id') == record_id:
                target_record = record
                break
        
        if not target_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"找不到記錄 ID {record_id}"
            )
        
        # 取得現有附件
        existing_attachments = target_record.get('fields', {}).get(field_name, [])
        if not isinstance(existing_attachments, list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="附件欄位格式錯誤"
            )
        
        # 過濾掉要刪除的 file_token
        remaining_file_tokens = []
        removed_attachment_name = None
        
        for attachment in existing_attachments:
            if attachment.get('file_token') != file_token:
                remaining_file_tokens.append(attachment.get('file_token'))
            else:
                removed_attachment_name = attachment.get('name', file_token)
        
        if len(remaining_file_tokens) == len(existing_attachments):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"找不到要刪除的附件 file_token: {file_token}"
            )
        
        # 更新記錄的附件欄位
        success = lark_client.update_record_attachment(
            table_id=team.test_case_table_id,
            record_id=record_id,
            field_name=field_name,
            file_tokens=remaining_file_tokens
        )
        
        if success:
            return {
                "success": True,
                "message": f"已成功移除附件: {removed_attachment_name or file_token}",
                "removed_file_token": file_token,
                "removed_file_name": removed_attachment_name,
                "remaining_attachments": len(remaining_file_tokens)
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="附件移除失敗"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"移除附件過程發生錯誤: {str(e)}"
        )


@router.get("/teams/{team_id}/attachments/download")
async def download_attachment_proxy(
    team_id: int,
    file_url: str = None,
    file_token: str = None,
    filename: str = None,
    config_id: int = None,
    item_id: int = None,
    file_index: int = None,
    db: Session = Depends(get_sync_db)
):
    """
    附件下載代理 API

    優先級：
    1. 若提供 config_id + item_id + file_index，從資料庫直接查詢文件路徑（無遞迴搜尋）- 最快
    2. 若 file_url 以 /attachments 開頭，直接從本地檔案系統讀取並回傳
    3. 若只有 file_token，嘗試在本地 attachments 目錄中以檔名搜尋（較慢，向後相容）
    4. 其餘情況才代理 Lark 下載
    """
    import os
    import mimetypes
    from pathlib import Path
    import urllib.parse

    # 優先級 1：通過資料庫直接查詢文件路徑（無遞迴搜尋）- 最優化
    if config_id is not None and item_id is not None and file_index is not None:
        try:
            from app.models.database_models import TestRunItem as TestRunItemDB

            item = db.query(TestRunItemDB).filter(
                TestRunItemDB.team_id == team_id,
                TestRunItemDB.config_id == config_id,
                TestRunItemDB.id == item_id
            ).first()

            if item:
                try:
                    execution_results = json.loads(item.execution_results_json or '[]')
                    if 0 <= file_index < len(execution_results):
                        file_meta = execution_results[file_index]
                        # 優先使用 absolute_path，否則嘗試重建路徑
                        file_path = file_meta.get('absolute_path')

                        if file_path and Path(file_path).exists() and Path(file_path).is_file():
                            # 驗證路徑安全性
                            project_root = Path(__file__).resolve().parents[2]
                            cfg_root = getattr(settings, 'attachments', None)
                            attachments_root = Path(cfg_root.root_dir) if (cfg_root and cfg_root.root_dir) else (project_root / 'attachments')

                            try:
                                Path(file_path).resolve().relative_to(attachments_root.resolve())
                                # 路徑合法，提供文件
                                media_type = mimetypes.guess_type(str(file_path))[0] or file_meta.get('type', 'application/octet-stream')
                                def iterfile():
                                    with open(file_path, 'rb') as f:
                                        yield from f
                                return StreamingResponse(iterfile(), media_type=media_type)
                            except ValueError:
                                # 路徑穿越檢查失敗
                                logger.warning(f"路徑穿越嘗試: {file_path}")
                                raise HTTPException(status_code=403, detail="禁止存取")
                except (json.JSONDecodeError, IndexError, KeyError) as e:
                    logger.warning(f"無法解析執行結果: {e}")
        except Exception as e:
            logger.warning(f"資料庫查詢失敗: {e}")
            # 降級到其他方法

    # 優先級 2：本地附件：/attachments 相對路徑
    try:
        if file_url and file_url.strip().startswith('/attachments'):
            project_root = Path(__file__).resolve().parents[2]
            cfg_root = getattr(settings, 'attachments', None)
            attachments_root = Path(cfg_root.root_dir) if (cfg_root and cfg_root.root_dir) else (project_root / 'attachments')
            # 防止目錄穿越
            rel = file_url[len('/attachments/'):].lstrip('/') if file_url else ''
            rel = urllib.parse.unquote(rel)
            disk_path = attachments_root / rel
            if not disk_path.exists() or not disk_path.is_file():
                raise HTTPException(status_code=404, detail="附件不存在")

            # 驗證路徑安全性（修複的邏輯）
            try:
                disk_path.resolve().relative_to(attachments_root.resolve())
            except ValueError:
                # 路徑穿越檢查失敗
                raise HTTPException(status_code=403, detail="禁止存取")

            media_type = mimetypes.guess_type(str(disk_path))[0] or 'application/octet-stream'
            def iterfile():
                with open(disk_path, 'rb') as f:
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
            project_root = Path(__file__).resolve().parents[2]
            cfg_root = getattr(settings, 'attachments', None)
            attachments_root = Path(cfg_root.root_dir) if (cfg_root and cfg_root.root_dir) else (project_root / 'attachments')
            # 在整個 attachments 目錄中搜尋相符檔名（stored_name）
            target = None
            if attachments_root.exists():
                for p in attachments_root.rglob('*'):
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

                media_type = mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
                def iterfile():
                    with open(target, 'rb') as f:
                        yield from f
                return StreamingResponse(iterfile(), media_type=media_type)
    except HTTPException:
        raise
    except Exception:
        pass

    # 優先級 4：代理 Lark 下載
    lark_client, team = get_lark_client_for_team(team_id, db)
    
    try:
        # 決定下載 URL
        download_url = file_url
        if not download_url and file_token:
            download_url = f"https://open.larksuite.com/open-apis/drive/v1/medias/{file_token}/download"
        
        if not download_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="必須提供 file_url 或 file_token"
            )
        
        # 取得 access token
        token = lark_client.auth_manager.get_tenant_access_token()
        if not token:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="無法取得 Lark access token"
            )
        
        # 代理下載請求
        headers = {
            'Authorization': f'Bearer {token}',
        }
        
        response = requests.get(
            download_url, 
            headers=headers, 
            stream=True,
            timeout=30
        )
        
        if response.status_code == 401:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Lark API 認證失敗"
            )
        elif response.status_code == 404:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="附件不存在"
            )
        elif response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Lark API 錯誤: HTTP {response.status_code}"
            )
        
        # 準備響應 headers
        response_headers = {}
        
        # 設定 Content-Type
        content_type = response.headers.get('content-type')
        if content_type:
            response_headers['Content-Type'] = content_type
        
        # 設定檔案名稱（處理中文檔名）
        if filename:
            # 使用 RFC 5987 標準處理非 ASCII 檔案名稱
            try:
                # 嘗試 ASCII 編碼
                filename.encode('ascii')
                response_headers['Content-Disposition'] = f'attachment; filename="{filename}"'
            except UnicodeEncodeError:
                # 包含非 ASCII 字符，使用 RFC 5987 格式
                encoded_filename = urllib.parse.quote(filename, safe='')
                response_headers['Content-Disposition'] = f'attachment; filename*=UTF-8\'\'{encoded_filename}'
        elif 'content-disposition' in response.headers:
            response_headers['Content-Disposition'] = response.headers['content-disposition']
        
        # 設定 Content-Length (如果有)
        content_length = response.headers.get('content-length')
        if content_length:
            response_headers['Content-Length'] = content_length
        
        # 創建流式響應
        def generate_file_stream():
            try:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
            finally:
                response.close()
        
        return StreamingResponse(
            generate_file_stream(),
            headers=response_headers
        )
        
    except HTTPException:
        raise
    except requests.exceptions.Timeout:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Lark 文件下載超時"
        )
    except requests.exceptions.RequestException as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Lark 文件下載失敗: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"附件下載代理錯誤: {str(e)}"
        )
