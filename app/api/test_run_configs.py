"""
測試執行配置 API 路由

管理團隊的多個測試執行配置。重構後 Test Run 不再依賴 Lark 表格，
內容由本系統從團隊的 Test Case 中挑選並儲存於本地資料庫。
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database import get_db
from app.models.test_run_config import (
    TestRunConfig, TestRunConfigCreate, TestRunConfigUpdate, TestRunConfigResponse,
    TestRunConfigSummary, TestRunConfigStatistics
)
from app.models.database_models import (
    TestRunConfig as TestRunConfigDB,
    Team as TeamDB,
    TestRunItem as TestRunItemDB,
    TestRunItemResultHistory as ResultHistoryDB,
)
from datetime import datetime

router = APIRouter(prefix="/teams/{team_id}/test-run-configs", tags=["test-run-configs"])


def test_run_config_db_to_model(config_db: TestRunConfigDB) -> TestRunConfig:
    """將資料庫 TestRunConfig 模型轉換為 API 模型"""
    return TestRunConfig(
        id=config_db.id,
        team_id=config_db.team_id,
        name=config_db.name,
        description=config_db.description,
        table_id=getattr(config_db, 'table_id', None),
        test_version=config_db.test_version,
        test_environment=config_db.test_environment,
        build_number=config_db.build_number,
        status=config_db.status,
        start_date=config_db.start_date,
        end_date=config_db.end_date,
        total_test_cases=config_db.total_test_cases,
        executed_cases=config_db.executed_cases,
        passed_cases=config_db.passed_cases,
        failed_cases=config_db.failed_cases,
        created_at=config_db.created_at,
        updated_at=config_db.updated_at,
        last_sync_at=config_db.last_sync_at
    )


def test_run_config_model_to_db(config: TestRunConfigCreate) -> TestRunConfigDB:
    """將 API TestRunConfig 模型轉換為資料庫模型"""
    return TestRunConfigDB(
        team_id=config.team_id,
        name=config.name,
        description=config.description,
        table_id=config.table_id if hasattr(config, 'table_id') else None,
        test_version=config.test_version,
        test_environment=config.test_environment,
        build_number=config.build_number,
        status=config.status,
        start_date=config.start_date
    )


def verify_team_exists(team_id: int, db: Session) -> TeamDB:
    """驗證團隊存在"""
    team = db.query(TeamDB).filter(TeamDB.id == team_id).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到團隊 ID {team_id}"
        )
    return team


@router.get("/", response_model=List[TestRunConfigSummary])
async def get_test_run_configs(
    team_id: int,
    status_filter: Optional[str] = Query(None, description="狀態過濾"),
    db: Session = Depends(get_db)
):
    """取得團隊的所有測試執行配置"""
    verify_team_exists(team_id, db)
    
    query = db.query(TestRunConfigDB).filter(TestRunConfigDB.team_id == team_id)
    
    if status_filter:
        query = query.filter(TestRunConfigDB.status == status_filter)
    
    configs_db = query.order_by(TestRunConfigDB.created_at.desc()).all()
    
    # 轉換為摘要格式（execution_rate/pass_rate 由模型方法計算）
    summaries = []
    for config_db in configs_db:
        config = test_run_config_db_to_model(config_db)
        summary = TestRunConfigSummary(
            id=config.id,
            name=config.name,
            table_id=config.table_id,
            test_environment=config.test_environment,
            build_number=config.build_number,
            test_version=config.test_version,
            status=config.status,
            execution_rate=config.get_execution_rate(),
            pass_rate=config.get_pass_rate(),
            total_test_cases=config.total_test_cases,
            executed_cases=config.executed_cases,
            start_date=config.start_date,
            end_date=config.end_date,
            created_at=config.created_at
        )
        summaries.append(summary)
    
    return summaries


@router.post("/", response_model=TestRunConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_test_run_config(
    team_id: int,
    config: TestRunConfigCreate,
    db: Session = Depends(get_db)
):
    """建立新的測試執行配置"""
    verify_team_exists(team_id, db)
    
    # 確保 team_id 一致
    config.team_id = team_id
    
    # 建立資料庫模型
    config_db = test_run_config_model_to_db(config)
    
    # 儲存到資料庫
    db.add(config_db)
    db.commit()
    db.refresh(config_db)
    
    return test_run_config_db_to_model(config_db)


@router.get("/{config_id}", response_model=TestRunConfigResponse)
async def get_test_run_config(
    team_id: int,
    config_id: int,
    db: Session = Depends(get_db)
):
    """取得特定的測試執行配置"""
    verify_team_exists(team_id, db)
    
    config_db = db.query(TestRunConfigDB).filter(
        TestRunConfigDB.id == config_id,
        TestRunConfigDB.team_id == team_id
    ).first()
    
    if not config_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到測試執行配置 ID {config_id}"
        )
    
    return test_run_config_db_to_model(config_db)


@router.put("/{config_id}", response_model=TestRunConfigResponse)
async def update_test_run_config(
    team_id: int,
    config_id: int,
    config_update: TestRunConfigUpdate,
    db: Session = Depends(get_db)
):
    """更新測試執行配置"""
    verify_team_exists(team_id, db)
    
    config_db = db.query(TestRunConfigDB).filter(
        TestRunConfigDB.id == config_id,
        TestRunConfigDB.team_id == team_id
    ).first()
    
    if not config_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到測試執行配置 ID {config_id}"
        )
    
    # 更新欄位
    update_data = config_update.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(config_db, key, value)
    
    # 提交更新
    db.commit()
    db.refresh(config_db)
    
    return test_run_config_db_to_model(config_db)


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_test_run_config(
    team_id: int,
    config_id: int,
    db: Session = Depends(get_db)
):
    """刪除測試執行配置"""
    verify_team_exists(team_id, db)
    
    config_db = db.query(TestRunConfigDB).filter(
        TestRunConfigDB.id == config_id,
        TestRunConfigDB.team_id == team_id
    ).first()
    
    if not config_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到測試執行配置 ID {config_id}"
        )
    # 先刪除歷程與本地 items，避免潛在的參照錯誤
    try:
        # 保險刪除：相關歷程
        db.query(ResultHistoryDB).filter(
            ResultHistoryDB.config_id == config_id,
            ResultHistoryDB.team_id == team_id
        ).delete(synchronize_session=False)
        db.query(TestRunItemDB).filter(
            TestRunItemDB.config_id == config_id,
            TestRunItemDB.team_id == team_id
        ).delete(synchronize_session=False)
        db.delete(config_db)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/{config_id}/validate", response_model=dict)
async def validate_test_run_config(
    team_id: int,
    config_id: int,
    db: Session = Depends(get_db)
):
    """重構後：僅確認配置存在與基本欄位有效。"""
    verify_team_exists(team_id, db)
    config_db = db.query(TestRunConfigDB).filter(
        TestRunConfigDB.id == config_id,
        TestRunConfigDB.team_id == team_id
    ).first()
    if not config_db:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"找不到測試執行配置 ID {config_id}")
    return {"valid": True, "message": "配置有效（本地模式）"}


@router.get("/{config_id}/sync", response_model=dict)
async def sync_test_run_config(
    team_id: int,
    config_id: int,
    db: Session = Depends(get_db)
):
    """重構後：從本地 TestRunItem 統計並回寫到 TestRunConfig。"""
    verify_team_exists(team_id, db)
    config_db = db.query(TestRunConfigDB).filter(
        TestRunConfigDB.id == config_id,
        TestRunConfigDB.team_id == team_id
    ).first()
    if not config_db:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"找不到測試執行配置 ID {config_id}")

    # 以本地 items 統計
    items_q = db.query(TestRunItemDB).filter(TestRunItemDB.config_id == config_id)
    total_cases = items_q.count()
    executed_cases = items_q.filter(TestRunItemDB.test_result.isnot(None)).count()
    passed_cases = items_q.filter(TestRunItemDB.test_result == 'Passed').count()
    failed_cases = items_q.filter(TestRunItemDB.test_result == 'Failed').count()

    config_db.total_test_cases = total_cases
    config_db.executed_cases = executed_cases
    config_db.passed_cases = passed_cases
    config_db.failed_cases = failed_cases
    config_db.last_sync_at = datetime.utcnow()
    db.commit()

    return {
        "success": True,
        "message": "同步完成（本地資料）",
        "statistics": {
            "total_test_cases": total_cases,
            "executed_cases": executed_cases,
            "passed_cases": passed_cases,
            "failed_cases": failed_cases,
            "execution_rate": (executed_cases / total_cases * 100) if total_cases > 0 else 0,
            "pass_rate": (passed_cases / executed_cases * 100) if executed_cases > 0 else 0
        }
    }


@router.get("/statistics", response_model=TestRunConfigStatistics)
async def get_test_run_statistics(
    team_id: int,
    db: Session = Depends(get_db)
):
    """取得團隊測試執行統計資訊"""
    verify_team_exists(team_id, db)
    
    configs_db = db.query(TestRunConfigDB).filter(TestRunConfigDB.team_id == team_id).all()
    configs = [test_run_config_db_to_model(config_db) for config_db in configs_db]
    
    return TestRunConfigStatistics.from_configs(configs)
