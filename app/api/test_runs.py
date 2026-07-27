"""
Test Run HTML 報告 API 路由

僅提供 test run 的 HTML 報告產生與查詢；test run 與其執行結果的資料來源是本地
資料庫（見 `test_run_configs` / `test_run_items` 相關 API）。原本直接讀寫 Lark
多維表格的 record CRUD 端點已由 `purge-dead-lark-runtime-code` change 移除。
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
import logging

from app.database import get_db
from app.db_access.main import (
    MainAccessBoundary,
    get_main_access_boundary,
)
from app.models.database_models import Team as TeamDB, TestRunConfig as TestRunConfigDB

router = APIRouter(prefix="/teams/{team_id}/test-runs", tags=["test-runs"])

logger = logging.getLogger(__name__)


@router.post("/{config_id}/generate-html")
async def generate_html_report(
    team_id: int,
    config_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    """生成 Test Run HTML 報告（靜態檔），並回傳可存取的連結"""
    try:
        from ..services.html_report_service import HTMLReportService

        def _verify(sync_db: Session) -> None:
            # 驗證團隊和配置存在（不需要 Lark API 驗證）
            team = sync_db.query(TeamDB).filter(TeamDB.id == team_id).first()
            if not team:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"找不到團隊 ID {team_id}")

            config = (
                sync_db.query(TestRunConfigDB)
                .filter(TestRunConfigDB.id == config_id, TestRunConfigDB.team_id == team_id)
                .first()
            )
            if not config:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"找不到測試執行配置 ID {config_id}",
                )

        await main_boundary.run_sync_read(_verify)

        service = HTMLReportService(db_session=db)
        result = await service.generate_test_run_report(team_id=team_id, config_id=config_id)

        # 將相對路徑轉為完整網址
        base = str(request.base_url).rstrip("/")
        absolute_url = f"{base}{result['report_url']}"
        return {
            "success": True,
            "report_id": result["report_id"],
            "report_url": absolute_url,
            "overwritten": result.get("overwritten", True),
            "generated_at": result.get("generated_at"),
        }

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"HTML 報告生成失敗: {str(e)}",
        )


@router.get("/{config_id}/report", response_model=dict)
async def get_html_report_status(
    team_id: int,
    config_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    """查詢 HTML 報告是否已存在，存在則回傳完整連結"""

    # 驗證團隊與配置存在
    def _verify(sync_db: Session) -> None:
        team = sync_db.query(TeamDB).filter(TeamDB.id == team_id).first()
        if not team:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"找不到團隊 ID {team_id}")
        config = (
            sync_db.query(TestRunConfigDB)
            .filter(TestRunConfigDB.id == config_id, TestRunConfigDB.team_id == team_id)
            .first()
        )
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"找不到測試執行配置 ID {config_id}",
            )

    await main_boundary.run_sync_read(_verify)

    from ..services.html_report_service import HTMLReportService

    service = HTMLReportService(db_session=db)
    report_path = service.report_root / f"team-{team_id}-config-{config_id}.html"
    if report_path.exists():
        base = str(request.base_url).rstrip("/")
        url = f"{base}/reports/team-{team_id}-config-{config_id}.html"
        return {"exists": True, "report_url": url}
    else:
        return {"exists": False}
