"""
附件管理 API 路由

提供檔案上傳到 Lark Drive 並附加到測試案例或測試執行記錄的功能
"""

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional
import io

from app.database import get_db
from app.models.database_models import Team as TeamDB, TestRunConfig as TestRunConfigDB
from app.services.lark_client import LarkClient
from app.config import settings

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
    db: Session = Depends(get_db)
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
    db: Session = Depends(get_db)
):
    """
    上傳檔案到測試執行記錄的附件欄位
    
    Args:
        team_id: 團隊 ID
        config_id: 測試執行配置 ID
        record_id: 測試執行記錄 ID
        file: 上傳的檔案
        field_name: 附件欄位名稱（預設: "Execution Result"）
        append: 是否追加到現有附件（預設: True）
    """
    lark_client, team = get_lark_client_for_team(team_id, db)
    
    # 取得測試執行配置
    config = db.query(TestRunConfigDB).filter(
        TestRunConfigDB.id == config_id,
        TestRunConfigDB.team_id == team_id
    ).first()
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到測試執行配置 ID {config_id}"
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
        
        # 上傳檔案並附加到記錄
        success = lark_client.upload_and_attach_file(
            table_id=config.table_id,
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
                "append_mode": append,
                "field_name": field_name
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


@router.post("/teams/{team_id}/test-runs/{config_id}/records/{record_id}/upload-screenshot")
async def upload_testrun_screenshot(
    team_id: int,
    config_id: int,
    record_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    上傳測試執行結果截圖
    
    專門用於上傳測試執行的截圖檔案，會自動附加到 "Execution Result" 欄位
    """
    # 檢查檔案類型
    allowed_image_types = ["image/jpeg", "image/jpg", "image/png", "image/gif", "image/bmp"]
    if file.content_type not in allowed_image_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支援的圖片格式，支援格式: {', '.join(allowed_image_types)}"
        )
    
    # 使用通用的測試執行附件上傳功能
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
    db: Session = Depends(get_db)
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
    db: Session = Depends(get_db)
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
    db: Session = Depends(get_db)
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