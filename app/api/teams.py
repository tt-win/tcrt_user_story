"""
團隊管理 API 路由
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, delete
from pydantic import BaseModel

from app.db_access.main import MainAccessBoundary, get_main_access_boundary
from app.auth.dependencies import (
    get_current_user,
    require_admin,
)
from app.auth.models import PermissionType
from app.models.database_models import User
from app.models.team import TeamCreate, TeamUpdate
from app.models.lark_types import Priority
from app.models.database_models import (
    Team as TeamDB,
    TestRunConfig as TestRunConfigDB,
    TestRunItem as TestRunItemDB,
    TestRunItemResultHistory as ResultHistoryDB,
    SyncHistory as SyncHistoryDB,
    TestCaseLocal as TestCaseLocalDB,
)
import logging

from app.services.lark_client import LarkClient
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/teams", tags=["teams"])


class SimpleTableValidationRequest(BaseModel):
    """簡單的表格驗證請求"""

    wiki_token: str
    table_id: str


class ValidationResponse(BaseModel):
    """驗證回應"""

    valid: bool
    message: str


def team_db_to_model(team_db: TeamDB, test_case_count: int = 0) -> dict:
    """將資料庫團隊模型轉換為 API 回應字典。

    `test_case_count` 由呼叫端即時計算傳入；`Team.test_case_count` 欄位無人維護，勿使用。
    """
    from app.models.team import LarkRepoConfig, JiraConfig, TeamSettings

    lark_config = LarkRepoConfig(
        wiki_token=team_db.wiki_token, test_case_table_id=team_db.test_case_table_id
    )

    jira_config = None
    if team_db.jira_project_key:
        jira_config = JiraConfig(
            project_key=team_db.jira_project_key,
            default_assignee=team_db.default_assignee,
            issue_type=team_db.issue_type,
        )

    # 僅保留目前使用中的設定欄位（其他已從 TeamSettings 移除）
    db_default_priority = team_db.default_priority
    if hasattr(db_default_priority, "value"):
        default_priority_str = db_default_priority.value
    else:
        default_priority_str = db_default_priority or "Medium"

    settings = TeamSettings(default_priority=default_priority_str)

    return {
        "id": team_db.id,
        "name": team_db.name,
        "description": team_db.description,
        "lark_config": lark_config.dict(),
        "jira_config": jira_config.dict() if jira_config else None,
        "settings": settings.dict(),
        "status": (
            team_db.status.value
            if hasattr(team_db.status, "value") and team_db.status
            else (team_db.status if team_db.status else "active")
        ),
        "created_at": team_db.created_at,
        "updated_at": team_db.updated_at,
        "test_case_count": test_case_count,
        "last_sync_at": team_db.last_sync_at,
        "is_lark_configured": bool(team_db.wiki_token and team_db.test_case_table_id),
        "is_jira_configured": bool(team_db.jira_project_key),
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
        default_assignee=(
            team.jira_config.default_assignee if team.jira_config else None
        ),
        issue_type=team.jira_config.issue_type if team.jira_config else "Bug",
        # 從 TeamSettings 只保留 default_priority；其餘欄位已移除
        default_priority=(
            Priority(team.settings.default_priority)
            if (team.settings and team.settings.default_priority)
            else Priority.MEDIUM
        ),
        status="active",
    )


@router.get("/")
async def get_teams(
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
    current_user: User = Depends(get_current_user),
):
    """取得當前使用者可存取的團隊列表

    - SUPER_ADMIN: 可以查看所有團隊
    - ADMIN/USER: 只能查看有權限的團隊
    """
    try:
        async def _load_teams(session):
            result = await session.execute(select(TeamDB))
            teams_db = result.scalars().all()
            if not teams_db:
                return []
            count_rows = await session.execute(
                select(TestCaseLocalDB.team_id, func.count(TestCaseLocalDB.id))
                .group_by(TestCaseLocalDB.team_id)
            )
            case_counts = {team_id: int(count or 0) for team_id, count in count_rows.all()}
            return [
                team_db_to_model(team, test_case_count=case_counts.get(team.id, 0))
                for team in teams_db
            ]

        return await main_boundary.run_read(_load_teams)
    except Exception as e:
        print(f"Error loading teams: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="取得團隊列表時發生錯誤",
        )


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_team(
    team: TeamCreate,
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
    current_user: User = Depends(require_admin()),
):
    """新增一個團隊（需要 ADMIN 或以上權限）"""
    try:
        async def _create_team(session):
            team_db = team_model_to_db(team)
            session.add(team_db)
            await session.flush()
            await session.refresh(team_db)
            return team_db_to_model(team_db)

        return await main_boundary.run_write(_create_team)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"建立團隊失敗：{str(e)}",
        )


@router.post("/validate", response_model=dict)
async def validate_lark_repo(
    team: TeamCreate, current_user: User = Depends(require_admin())
):
    """驗證 Lark Repo 的連線（需要 ADMIN+ 權限）"""
    try:
        # 創建 Lark Client 來驗證連線
        lark_client = LarkClient(
            app_id=settings.lark.app_id, app_secret=settings.lark.app_secret
        )

        def _validate_connection():
            lark_client.set_wiki_token(team.lark_config.wiki_token)
            return lark_client.get_table_fields(team.lark_config.test_case_table_id)

        # 設定 wiki token 並取得表格資訊來驗證連線
        await asyncio.to_thread(_validate_connection)

        return {"valid": True, "message": "Lark Repo 連線驗證成功"}
    except Exception as e:
        return {"valid": False, "message": f"Lark Repo 連線驗證失敗: {str(e)}"}


@router.post("/validate-table", response_model=ValidationResponse)
async def validate_table(
    request: SimpleTableValidationRequest, current_user: User = Depends(require_admin())
):
    """簡單的表格驗證 API（需要 ADMIN+ 權限）"""
    try:
        # 創建 Lark Client 來驗證表格
        lark_client = LarkClient(
            app_id=settings.lark.app_id, app_secret=settings.lark.app_secret
        )

        def _validate_connection():
            if not lark_client.set_wiki_token(request.wiki_token):
                return False, None
            return True, lark_client.get_table_fields(request.table_id)

        # 設定 wiki token 並取得表格資訊來驗證連線
        token_valid, fields = await asyncio.to_thread(_validate_connection)
        if not token_valid:
            return ValidationResponse(
                valid=False,
                message="Failed to set Wiki Token, please check if the token is correct",
            )

        if fields:
            return ValidationResponse(
                valid=True,
                message=f"Table validation successful, found {len(fields)} fields",
            )
        else:
            return ValidationResponse(
                valid=False,
                message="Unable to retrieve table field information, please check if the Table ID is correct",
            )

    except Exception as e:
        return ValidationResponse(
            valid=False, message=f"Table validation failed: {str(e)}"
        )


@router.get("/{team_id}")
async def get_team(
    team_id: int,
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
    current_user: User = Depends(get_current_user),
):
    """根據 ID 取得特定團隊（需要對該團隊的讀取權限）"""
    from app.auth.models import UserRole
    from app.auth.permission_service import permission_service

    async def _load_team(session):
        result = await session.execute(select(TeamDB).where(TeamDB.id == team_id))
        team_db = result.scalar_one_or_none()
        if not team_db:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"找不到團隊 ID {team_id}",
            )
        count_result = await session.execute(
            select(func.count(TestCaseLocalDB.id)).where(TestCaseLocalDB.team_id == team_id)
        )
        return team_db_to_model(team_db, test_case_count=count_result.scalar() or 0)

    team_payload = await main_boundary.run_read(_load_team)

    # 權限檢查
    if current_user.role != UserRole.SUPER_ADMIN:
        permission_check = await permission_service.check_team_permission(
            current_user.id, team_id, PermissionType.READ, current_user.role
        )
        if not permission_check.has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="無權限存取此團隊"
            )

    return team_payload


@router.put("/{team_id}")
async def update_team(
    team_id: int,
    team_update: TeamUpdate,
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
    current_user: User = Depends(require_admin()),
):
    """更新指定的團隊（需要 ADMIN 或以上權限）"""
    try:
        rename_info: dict[str, str] = {}

        async def _update_team(session):
            result = await session.execute(select(TeamDB).where(TeamDB.id == team_id))
            team_db = result.scalar_one_or_none()
            if not team_db:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"找不到團隊 ID {team_id}",
                )

            if team_update.name is not None:
                if team_update.name != team_db.name:
                    rename_info["old"] = team_db.name
                    rename_info["new"] = team_update.name
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
                if getattr(team_update.settings, "default_priority", None):
                    try:
                        team_db.default_priority = Priority(
                            team_update.settings.default_priority
                        )
                    except Exception:
                        team_db.default_priority = Priority.MEDIUM

            if team_update.status is not None:
                team_db.status = team_update.status

            await session.flush()
            await session.refresh(team_db)
            count_result = await session.execute(
                select(func.count(TestCaseLocalDB.id)).where(TestCaseLocalDB.team_id == team_id)
            )
            return team_db_to_model(team_db, test_case_count=count_result.scalar() or 0)

        result = await main_boundary.run_write(_update_team)

        # A rename strands this team's Jenkins jobs/view + Allure projects (all
        # embed the team name/slug). Re-sync them to the new name in an isolated,
        # best-effort write — a CI / report-server outage must never fail or roll
        # back the rename itself.
        if rename_info:
            try:
                async def _resync(session):
                    from app.services.automation.script_group_service import (
                        AutomationScriptGroupService,
                    )

                    service = AutomationScriptGroupService(session)
                    await service.resync_team_after_rename(
                        team_id=team_id,
                        old_team_name=rename_info["old"],
                        new_team_name=rename_info["new"],
                    )

                await main_boundary.run_write(_resync)
            except Exception:
                logger.warning(
                    "Automation re-sync after team %s rename failed (non-fatal)",
                    team_id,
                    exc_info=True,
                )

        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新團隊失敗：{str(e)}",
        )


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(
    team_id: int,
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
    current_user: User = Depends(require_admin()),
):
    """刪除指定的團隊（需要 ADMIN 或以上權限）"""
    try:
        async def _delete_team(session):
            result = await session.execute(select(TeamDB).where(TeamDB.id == team_id))
            team_db = result.scalar_one_or_none()
            if not team_db:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"找不到團隊 ID {team_id}",
                )

            await session.execute(
                delete(ResultHistoryDB).where(ResultHistoryDB.team_id == team_id)
            )
            await session.execute(
                delete(TestRunItemDB).where(TestRunItemDB.team_id == team_id)
            )
            await session.execute(
                delete(TestRunConfigDB).where(TestRunConfigDB.team_id == team_id)
            )
            await session.execute(
                delete(SyncHistoryDB).where(SyncHistoryDB.team_id == team_id)
            )
            await session.execute(
                delete(TestCaseLocalDB).where(TestCaseLocalDB.team_id == team_id)
            )
            await session.delete(team_db)
            await session.flush()

        # 刪除 team 前先回收其底下所有 suite 的 Allure 報表儲存空間：team 刪除會
        # 透過 DB cascade 直接移除 AutomationScriptGroup，繞過 delete_group 的逐一
        # 清理，所以要趁 suite 還在時先清。自成一個唯讀交易且吞掉所有例外，確保
        # 不影響團隊刪除本身。
        try:
            from app.services.automation.allure_proxy import delete_projects_for_team

            async def _reclaim_allure(session):
                return await delete_projects_for_team(session=session, team_id=team_id)

            await main_boundary.run_read(_reclaim_allure)
        except Exception:
            pass

        await main_boundary.run_write(_delete_team)

        # 嘗試移除磁碟附件資料夾（非致命）
        try:
            from pathlib import Path
            import shutil

            project_root = Path(__file__).resolve().parents[2]
            from app.config import settings

            root_dir = (
                Path(settings.attachments.root_dir)
                if settings.attachments.root_dir
                else (project_root / "attachments")
            )
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"刪除團隊失敗：{str(e)}",
        )
