"""
團隊管理 API 路由
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel

from app.database import get_db
from app.models.team import Team, TeamCreate, TeamUpdate, TeamResponse
from app.models.lark_types import Priority
from app.models.database_models import (
    Team as TeamDB,
    TestRunConfig as TestRunConfigDB,
    TestRunItem as TestRunItemDB,
    TestRunItemResultHistory as ResultHistoryDB,
    SyncHistory as SyncHistoryDB,
)
from app.services.lark_client import LarkClient
from app.config import settings

router = APIRouter(prefix="/teams", tags=["teams"])


class SimpleTableValidationRequest(BaseModel):
    """簡單的表格驗證請求"""
    wiki_token: str
    table_id: str


class ValidationResponse(BaseModel):
    """驗證回應"""
    valid: bool
    message: str

def team_db_to_model(team_db: TeamDB) -> dict:
    """將資料庫團隊模型轉換為 API 回應字典"""
    from app.models.team import LarkRepoConfig, JiraConfig, TeamSettings
    
    lark_config = LarkRepoConfig(
        wiki_token=team_db.wiki_token,
        test_case_table_id=team_db.test_case_table_id
    )
    
    jira_config = None
    if team_db.jira_project_key:
        jira_config = JiraConfig(
            project_key=team_db.jira_project_key,
            default_assignee=team_db.default_assignee,
            issue_type=team_db.issue_type
        )
    
    # 僅保留目前使用中的設定欄位（其他已從 TeamSettings 移除）
    db_default_priority = team_db.default_priority
    if hasattr(db_default_priority, 'value'):
        default_priority_str = db_default_priority.value
    else:
        default_priority_str = db_default_priority or "Medium"

    settings = TeamSettings(
        default_priority=default_priority_str
    )
    
    return {
        "id": team_db.id,
        "name": team_db.name,
        "description": team_db.description,
        "lark_config": lark_config.dict(),
        "jira_config": jira_config.dict() if jira_config else None,
        "settings": settings.dict(),
        "status": team_db.status.value if hasattr(team_db.status, 'value') and team_db.status else (team_db.status if team_db.status else "active"),
        "created_at": team_db.created_at,
        "updated_at": team_db.updated_at,
        "test_case_count": team_db.test_case_count or 0,
        "last_sync_at": team_db.last_sync_at,
        "is_lark_configured": bool(team_db.wiki_token and team_db.test_case_table_id),
        "is_jira_configured": bool(team_db.jira_project_key)
    }

def team_model_to_db(team: TeamCreate) -> TeamDB:
    """將 API 團隊模型轉換為資料庫模型"""
    # 將 API 模型轉換為資料庫模型（映射現行欄位）
    return TeamDB(
        name=team.name,
        description=team.description,
        wiki_token=team.lark_config.wiki_token,
        test_case_table_id=team.lark_config.test_case_table_id,
        jira_project_key=team.jira_config.project_key if team.jira_config else None,
        default_assignee=team.jira_config.default_assignee if team.jira_config else None,
        issue_type=team.jira_config.issue_type if team.jira_config else "Bug",
        # 從 TeamSettings 只保留 default_priority；其餘欄位已移除
        default_priority=(
            Priority(team.settings.default_priority)
            if (team.settings and team.settings.default_priority)
            else Priority.MEDIUM
        ),
        status="active"
    )

@router.get("/")
async def get_teams(db: Session = Depends(get_db)):
    """取得所有團隊列表"""
    try:
        teams_db = db.query(TeamDB).all()
        if not teams_db:
            return []
        return [team_db_to_model(team) for team in teams_db]
    except Exception as e:
        print(f"Error loading teams: {e}")
        return []

@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_team(team: TeamCreate, db: Session = Depends(get_db)):
    """新增一個團隊"""
    try:
        # 創建資料庫模型
        team_db = team_model_to_db(team)
        
        # 儲存到資料庫
        db.add(team_db)
        db.commit()
        db.refresh(team_db)
        
        return team_db_to_model(team_db)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"建立團隊失敗：{str(e)}"
        )

@router.post("/validate", response_model=dict)
async def validate_lark_repo(team: TeamCreate):
    """驗證 Lark Repo 的連線"""
    try:
        # 創建 Lark Client 來驗證連線
        lark_client = LarkClient(
            app_id=settings.lark.app_id,
            app_secret=settings.lark.app_secret
        )
        
        # 設定 wiki token
        lark_client.set_wiki_token(team.lark_config.wiki_token)
        
        # 嘗試取得表格資訊來驗證連線
        fields = lark_client.get_table_fields(team.lark_config.test_case_table_id)
        
        return {
            "valid": True,
            "message": "Lark Repo 連線驗證成功"
        }
    except Exception as e:
        return {
            "valid": False,
            "message": f"Lark Repo 連線驗證失敗: {str(e)}"
        }


@router.post("/validate-table", response_model=ValidationResponse)
async def validate_table(request: SimpleTableValidationRequest):
    """簡單的表格驗證 API（不依賴完整團隊資料）"""
    try:
        # 創建 Lark Client 來驗證表格
        lark_client = LarkClient(
            app_id=settings.lark.app_id,
            app_secret=settings.lark.app_secret
        )
        
        # 設定 wiki token
        if not lark_client.set_wiki_token(request.wiki_token):
            return ValidationResponse(
                valid=False,
                message="Failed to set Wiki Token, please check if the token is correct"
            )
        
        # 嘗試取得表格資訊來驗證連線
        fields = lark_client.get_table_fields(request.table_id)
        
        if fields:
            return ValidationResponse(
                valid=True,
                message=f"Table validation successful, found {len(fields)} fields"
            )
        else:
            return ValidationResponse(
                valid=False,
                message="Unable to retrieve table field information, please check if the Table ID is correct"
            )
            
    except Exception as e:
        return ValidationResponse(
            valid=False,
            message=f"Table validation failed: {str(e)}"
        )

@router.get("/{team_id}")
async def get_team(team_id: int, db: Session = Depends(get_db)):
    """根據 ID 取得特定團隊"""
    team_db = db.query(TeamDB).filter(TeamDB.id == team_id).first()
    
    if not team_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到團隊 ID {team_id}"
        )
    
    return team_db_to_model(team_db)

@router.put("/{team_id}")
async def update_team(team_id: int, team_update: TeamUpdate, db: Session = Depends(get_db)):
    """更新指定的團隊"""
    team_db = db.query(TeamDB).filter(TeamDB.id == team_id).first()
    
    if not team_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到團隊 ID {team_id}"
        )
    try:
        # 更新資料庫模型
        if team_update.name is not None:
            team_db.name = team_update.name
        
        if team_update.description is not None:
            team_db.description = team_update.description
        
        if team_update.lark_config is not None:
            team_db.wiki_token = team_update.lark_config.wiki_token
            team_db.test_case_table_id = team_update.lark_config.test_case_table_id
        
        if team_update.jira_config is not None:
            team_db.jira_project_key = team_update.jira_config.project_key
            team_db.default_assignee = team_update.jira_config.default_assignee
            team_db.issue_type = team_update.jira_config.issue_type
        
        if team_update.settings is not None:
            # 僅更新 default_priority（其他設定已移除）
            if getattr(team_update.settings, 'default_priority', None):
                try:
                    team_db.default_priority = Priority(team_update.settings.default_priority)
                except Exception:
                    team_db.default_priority = Priority.MEDIUM
        
        if team_update.status is not None:
            team_db.status = team_update.status
        
        # 提交更新
        db.commit()
        db.refresh(team_db)
        
        return team_db_to_model(team_db)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新團隊失敗：{str(e)}"
        )

@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(team_id: int, db: Session = Depends(get_db)):
    """刪除指定的團隊，並清理相關資料避免參照完整性錯誤"""
    team_db = db.query(TeamDB).filter(TeamDB.id == team_id).first()

    if not team_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到團隊 ID {team_id}"
        )

    try:
        # 先刪除與該團隊相關的歷程與本地項目與配置，避免 FK 參照錯誤
        # 1) 測試結果歷程
        db.query(ResultHistoryDB).filter(ResultHistoryDB.team_id == team_id).delete(synchronize_session=False)
        # 2) 本地測試執行項目
        db.query(TestRunItemDB).filter(TestRunItemDB.team_id == team_id).delete(synchronize_session=False)
        # 3) 測試執行配置
        db.query(TestRunConfigDB).filter(TestRunConfigDB.team_id == team_id).delete(synchronize_session=False)
        # 4) 同步歷史
        db.query(SyncHistoryDB).filter(SyncHistoryDB.team_id == team_id).delete(synchronize_session=False)

        # 最後刪除團隊
        db.delete(team_db)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"刪除團隊失敗：{str(e)}")
