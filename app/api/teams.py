"""
團隊管理 API 路由
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from typing import List
from pydantic import BaseModel

from app.database import get_db
from app.auth.dependencies import get_current_user, require_admin, require_super_admin, require_team_permission
from app.auth.models import PermissionType
from app.models.database_models import User
from app.models.team import Team, TeamCreate, TeamUpdate, TeamResponse
from app.models.lark_types import Priority
from app.models.database_models import (
    Team as TeamDB,
    TestRunConfig as TestRunConfigDB,
    TestRunItem as TestRunItemDB,
    TestRunItemResultHistory as ResultHistoryDB,
    SyncHistory as SyncHistoryDB,
    TestCaseLocal as TestCaseLocalDB,
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
async def get_teams(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """取得當前使用者可存取的團隊列表
    
    - SUPER_ADMIN: 可以查看所有團隊
    - ADMIN/USER: 只能查看有權限的團隊
    """
    try:
        from app.auth.models import UserRole
        from app.auth.permission_service import permission_service
        
        if current_user.role == UserRole.SUPER_ADMIN:
            # 超管可以查看所有團隊
            result = await db.execute(select(TeamDB))
            teams_db = result.scalars().all()
        else:
            # 一般使用者只能查看有權限的團隊
            accessible_team_ids = await permission_service.get_user_accessible_teams(current_user.id)
            if not accessible_team_ids:
                return []
            
            result = await db.execute(select(TeamDB).where(TeamDB.id.in_(accessible_team_ids)))
            teams_db = result.scalars().all()
        
        if not teams_db:
            return []
        return [team_db_to_model(team) for team in teams_db]
    except Exception as e:
        print(f"Error loading teams: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="取得團隊列表時發生錯誤"
        )

@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_team(
    team: TeamCreate, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_super_admin())
):
    """新增一個團隊（僅 SUPER_ADMIN 可以建立團隊）"""
    try:
        # 創建資料庫模型
        team_db = team_model_to_db(team)
        
        # 儲存到資料庫
        db.add(team_db)
        await db.commit()
        await db.refresh(team_db)
        
        return team_db_to_model(team_db)
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"建立團隊失敗：{str(e)}"
        )

@router.post("/validate", response_model=dict)
async def validate_lark_repo(
    team: TeamCreate,
    current_user: User = Depends(require_admin())
):
    """驗證 Lark Repo 的連線（需要 ADMIN+ 權限）"""
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
async def validate_table(
    request: SimpleTableValidationRequest,
    current_user: User = Depends(require_admin())
):
    """簡單的表格驗證 API（需要 ADMIN+ 權限）"""
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
async def get_team(
    team_id: int, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """根據 ID 取得特定團隊（需要對該團隊的讀取權限）"""
    from app.auth.models import UserRole
    from app.auth.permission_service import permission_service
    
    # 檢查團隊是否存在
    result = await db.execute(select(TeamDB).where(TeamDB.id == team_id))
    team_db = result.scalar_one_or_none()
    if not team_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到團隊 ID {team_id}"
        )
    
    # 權限檢查
    if current_user.role != UserRole.SUPER_ADMIN:
        permission_check = await permission_service.check_team_permission(
            current_user.id, team_id, PermissionType.READ, current_user.role
        )
        if not permission_check.has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="無權限存取此團隊"
            )
    
    return team_db_to_model(team_db)

@router.put("/{team_id}")
async def update_team(
    team_id: int, 
    team_update: TeamUpdate, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """更新指定的團隊（需要對該團隊的寫入權限）"""
    from app.auth.models import UserRole
    from app.auth.permission_service import permission_service
    
    result = await db.execute(select(TeamDB).where(TeamDB.id == team_id))
    team_db = result.scalar_one_or_none()
    if not team_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到團隊 ID {team_id}"
        )
    
    # 權限檢查
    if current_user.role != UserRole.SUPER_ADMIN:
        permission_check = await permission_service.check_team_permission(
            current_user.id, team_id, PermissionType.WRITE, current_user.role
        )
        if not permission_check.has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="無權限修改此團隊"
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
        await db.commit()
        await db.refresh(team_db)
        
        return team_db_to_model(team_db)
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新團隊失敗：{str(e)}"
        )

@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(
    team_id: int, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_super_admin())
):
    """刪除指定的團隊（僅 SUPER_ADMIN 可以刪除團隊）"""
    result = await db.execute(select(TeamDB).where(TeamDB.id == team_id))
    team_db = result.scalar_one_or_none()

    if not team_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到團隊 ID {team_id}"
        )

    try:
        # 先刪除與該團隊相關的歷程與本地項目與配置與測試案例，避免 FK 參照錯誤
        # 1) 測試結果歷程
        await db.execute(delete(ResultHistoryDB).where(ResultHistoryDB.team_id == team_id))
        # 2) 本地測試執行項目
        await db.execute(delete(TestRunItemDB).where(TestRunItemDB.team_id == team_id))
        # 3) 測試執行配置
        await db.execute(delete(TestRunConfigDB).where(TestRunConfigDB.team_id == team_id))
        # 4) 同步歷史
        await db.execute(delete(SyncHistoryDB).where(SyncHistoryDB.team_id == team_id))
        # 5) 本地測試案例
        await db.execute(delete(TestCaseLocalDB).where(TestCaseLocalDB.team_id == team_id))

        # 最後刪除團隊
        await db.delete(team_db)
        await db.commit()

        # 嘗試移除磁碟附件資料夾（非致命）
        try:
            from pathlib import Path
            import shutil
            project_root = Path(__file__).resolve().parents[2]
            from app.config import settings
            root_dir = Path(settings.attachments.root_dir) if settings.attachments.root_dir else (project_root / "attachments")
            # test-cases/{team_id}
            tc_dir = root_dir / "test-cases" / str(team_id)
            if tc_dir.exists():
                shutil.rmtree(tc_dir, ignore_errors=True)
            # test-runs/{team_id}
            tr_dir = root_dir / "test-runs" / str(team_id)
            if tr_dir.exists():
                shutil.rmtree(tr_dir, ignore_errors=True)
        except Exception:
            pass
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"刪除團隊失敗：{str(e)}")
