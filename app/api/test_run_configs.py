"""
測試執行配置 API 路由

管理團隊的多個測試執行配置。重構後 Test Run 不再依賴 Lark 表格，
內容由本系統從團隊的 Test Case 中挑選並儲存於本地資料庫。
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
import json
import logging

logger = logging.getLogger(__name__)

from app.database import get_db, get_sync_db
from app.models.test_run_config import (
    TestRunConfig, TestRunConfigCreate, TestRunConfigUpdate, TestRunConfigResponse,
    TestRunConfigSummary
)
from app.models.database_models import (
    TestRunConfig as TestRunConfigDB,
    TestRunSet as TestRunSetDB,
    TestRunSetMembership as TestRunSetMembershipDB,
    Team as TeamDB,
    TestRunItem as TestRunItemDB,
    TestRunItemResultHistory as ResultHistoryDB,
)
from app.models.lark_types import TestResultStatus
from app.models.test_run_config import TestRunStatus
from app.services.lark_notify_service import get_lark_notify_service
from datetime import datetime
from pydantic import BaseModel, Field

router = APIRouter(prefix="/teams/{team_id}/test-run-configs", tags=["test-run-configs"])

# 搜尋 API 路由器（不依賴 team_id 路徑參數）
search_router = APIRouter(prefix="/test-run-configs/search", tags=["test-run-configs-search"])


def serialize_tp_tickets(tp_tickets: Optional[List[str]]) -> tuple[Optional[str], Optional[str]]:
    """
    序列化 TP 票號為 JSON 字串和搜尋索引
    
    Args:
        tp_tickets: TP 票號列表
        
    Returns:
        tuple: (json_string, search_string)
    """
    if not tp_tickets:
        return None, None
    
    # JSON 序列化
    json_string = json.dumps(tp_tickets)
    
    # 搜尋索引（空格分隔）
    search_string = " ".join(tp_tickets)
    
    return json_string, search_string


def deserialize_tp_tickets(json_string: Optional[str]) -> List[str]:
    """
    反序列化 JSON 字串為 TP 票號列表
    
    Args:
        json_string: JSON 字串
        
    Returns:
        TP 票號列表
    """
    if not json_string:
        return []
    
    try:
        tickets = json.loads(json_string)
        return tickets if isinstance(tickets, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def serialize_notify_chats(ids: Optional[List[str]], names: Optional[List[str]]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    序列化通知群組資料
    
    Args:
        ids: 群組 Chat ID 列表
        names: 群組名稱快照列表
        
    Returns:
        tuple: (ids_json, names_json, search_string)
    """
    ids_json = None
    names_json = None
    search_string = None
    
    if ids:
        ids_json = json.dumps(ids, ensure_ascii=False)
    
    if names:
        names_json = json.dumps(names, ensure_ascii=False)
        # 以空白連接作為搜尋索引
        search_string = ' '.join(names)
    
    return ids_json, names_json, search_string


def deserialize_notify_chats(ids_json: Optional[str], names_json: Optional[str]) -> tuple[List[str], List[str]]:
    """
    反序列化通知群組資料
    
    Args:
        ids_json: 群組 Chat ID JSON 字串
        names_json: 群組名稱快照 JSON 字串
        
    Returns:
        tuple: (ids: List[str], names: List[str])
    """
    ids = []
    names = []
    
    if ids_json:
        try:
            parsed_ids = json.loads(ids_json)
            if isinstance(parsed_ids, list):
                ids = parsed_ids
        except (json.JSONDecodeError, TypeError):
            pass
    
    if names_json:
        try:
            parsed_names = json.loads(names_json)
            if isinstance(parsed_names, list):
                names = parsed_names
        except (json.JSONDecodeError, TypeError):
            pass
    
    return ids, names


def sync_tp_tickets_to_db(config_db: TestRunConfigDB, tp_tickets: Optional[List[str]]) -> None:
    """
    同步 TP 票號到資料庫欄位
    
    Args:
        config_db: 資料庫模型實例
        tp_tickets: TP 票號列表
    """
    json_string, search_string = serialize_tp_tickets(tp_tickets)
    config_db.related_tp_tickets_json = json_string
    config_db.tp_tickets_search = search_string


def sync_notify_chats_to_db(config_db: TestRunConfigDB, chat_ids: Optional[List[str]], chat_names: Optional[List[str]]) -> None:
    """
    同步通知群組到資料庫欄位
    
    Args:
        config_db: 資料庫模型實例
        chat_ids: 群組 Chat ID 列表
        chat_names: 群組名稱快照列表
    """
    ids_json, names_json, search_string = serialize_notify_chats(chat_ids, chat_names)
    config_db.notify_chat_ids_json = ids_json
    config_db.notify_chat_names_snapshot = names_json
    config_db.notify_chats_search = search_string


def convert_db_to_model(config_db: TestRunConfigDB) -> TestRunConfig:
    """將資料庫 TestRunConfig 模型轉換為 API 模型"""
    # 反序列化 TP 票號
    related_tp_tickets = deserialize_tp_tickets(config_db.related_tp_tickets_json)

    # 反序列化通知群組
    notify_chat_ids, notify_chat_names_snapshot = deserialize_notify_chats(
        config_db.notify_chat_ids_json, 
        config_db.notify_chat_names_snapshot
    )

    set_id = None
    set_name = None
    if getattr(config_db, "set_membership", None):
        set_id = config_db.set_membership.set_id
        if config_db.set_membership.test_run_set:
            set_name = config_db.set_membership.test_run_set.name

    return TestRunConfig(
        id=config_db.id,
        team_id=config_db.team_id,
        name=config_db.name,
        description=config_db.description,
        set_id=set_id,
        set_name=set_name,
        test_version=config_db.test_version,
        test_environment=config_db.test_environment,
        build_number=config_db.build_number,
        related_tp_tickets=related_tp_tickets,
        # 通知設定
        notifications_enabled=config_db.notifications_enabled or False,
        notify_chat_ids=notify_chat_ids if notify_chat_ids else None,
        notify_chat_names_snapshot=notify_chat_names_snapshot if notify_chat_names_snapshot else None,
        # 狀態與時間
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


def convert_model_to_db(config: TestRunConfigCreate) -> TestRunConfigDB:
    """將 API TestRunConfig 模型轉換為資料庫模型"""
    # 序列化 TP 票號
    tp_json, tp_search = serialize_tp_tickets(config.related_tp_tickets)
    
    # 序列化通知群組
    ids_json, names_json, chats_search = serialize_notify_chats(
        config.notify_chat_ids, config.notify_chat_names_snapshot
    )
    
    return TestRunConfigDB(
        team_id=config.team_id,
        name=config.name,
        description=config.description,
        test_version=config.test_version,
        test_environment=config.test_environment,
        build_number=config.build_number,
        related_tp_tickets_json=tp_json,
        tp_tickets_search=tp_search,
        # 通知設定
        notifications_enabled=config.notifications_enabled or False,
        notify_chat_ids_json=ids_json,
        notify_chat_names_snapshot=names_json,
        notify_chats_search=chats_search,
        # 狀態
        status=config.status,
        start_date=config.start_date
    )


def build_config_summary(config_db: TestRunConfigDB) -> TestRunConfigSummary:
    """建立 TestRunConfig 摘要模型"""
    config = convert_db_to_model(config_db)
    return TestRunConfigSummary(
        id=config.id,
        name=config.name,
        set_id=config.set_id,
        set_name=config.set_name,
        test_environment=config.test_environment,
        build_number=config.build_number,
        test_version=config.test_version,
        related_tp_tickets=config.related_tp_tickets,
        tp_tickets_count=len(config.related_tp_tickets) if config.related_tp_tickets else 0,
        status=config.status,
        execution_rate=config.get_execution_rate(),
        pass_rate=config.get_pass_rate(),
        total_test_cases=config.total_test_cases,
        executed_cases=config.executed_cases,
        passed_cases=config.passed_cases,
        start_date=config.start_date,
        end_date=config.end_date,
        created_at=config.created_at
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


def ensure_test_run_set(
    db: Session,
    team_id: int,
    set_id: int
) -> TestRunSetDB:
    """確認 Test Run Set 存在且屬於指定團隊"""
    test_run_set = db.query(TestRunSetDB).filter(
        TestRunSetDB.id == set_id,
        TestRunSetDB.team_id == team_id
    ).first()
    if not test_run_set:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到 Test Run Set ID {set_id}"
        )
    return test_run_set


def attach_config_to_set(
    db: Session,
    team_id: int,
    config_db: TestRunConfigDB,
    set_id: int
) -> None:
    """將 Test Run Config 加入指定 Set"""
    ensure_test_run_set(db, team_id, set_id)

    existing = db.query(TestRunSetMembershipDB).filter(
        TestRunSetMembershipDB.config_id == config_db.id
    ).first()

    if existing:
        if existing.set_id == set_id:
            return
        existing.set_id = set_id
        existing.team_id = team_id
    else:
        membership = TestRunSetMembershipDB(
            team_id=team_id,
            set_id=set_id,
            config_id=config_db.id
        )
        db.add(membership)


def detach_config_from_set(
    db: Session,
    config_id: int
) -> None:
    """將 Test Run Config 從任何 Set 中移出"""
    db.query(TestRunSetMembershipDB).filter(
        TestRunSetMembershipDB.config_id == config_id
    ).delete(synchronize_session=False)


async def delete_test_run_config_cascade(
    db: Session,
    team_id: int,
    config_db: TestRunConfigDB
) -> None:
    """刪除 Test Run Config 與相關紀錄與檔案"""
    from ..services.test_result_cleanup_service import TestResultCleanupService

    # 先清除 set membership
    detach_config_from_set(db, config_db.id)

    # 清理檔案與資料
    cleanup_service = TestResultCleanupService()
    cleaned_files_count = await cleanup_service.cleanup_test_run_config_files(
        team_id, config_db.id, db
    )

    if cleaned_files_count > 0:
        logger.info(
            "Test Run Config %s 已清理 %s 個測試結果檔案",
            config_db.id,
            cleaned_files_count
        )

    db.query(ResultHistoryDB).filter(
        ResultHistoryDB.config_id == config_db.id,
        ResultHistoryDB.team_id == team_id
    ).delete(synchronize_session=False)

    db.query(TestRunItemDB).filter(
        TestRunItemDB.config_id == config_db.id,
        TestRunItemDB.team_id == team_id
    ).delete(synchronize_session=False)

    db.delete(config_db)


@router.get("/", response_model=List[TestRunConfigSummary])
async def get_test_run_configs(
    team_id: int,
    status_filter: Optional[str] = Query(None, description="狀態過濾"),
    db: Session = Depends(get_sync_db)
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
        summaries.append(build_config_summary(config_db))
    
    return summaries


@router.post("/", response_model=TestRunConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_test_run_config(
    team_id: int,
    config: TestRunConfigCreate,
    db: Session = Depends(get_sync_db)
):
    """建立新的測試執行配置"""
    verify_team_exists(team_id, db)
    
    # 確保 team_id 一致
    config.team_id = team_id
    
    # 建立資料庫模型
    config_db = convert_model_to_db(config)
    
    # 儲存到資料庫並處理 Set 關聯
    db.add(config_db)
    db.flush()

    if config.set_id is not None:
        attach_config_to_set(db, team_id, config_db, config.set_id)

    db.commit()
    db.refresh(config_db)
    db.expire(config_db, ['set_membership'])
    
    return convert_db_to_model(config_db)


@router.get("/{config_id}", response_model=TestRunConfigResponse)
async def get_test_run_config(
    team_id: int,
    config_id: int,
    db: Session = Depends(get_sync_db)
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
    
    return convert_db_to_model(config_db)


@router.put("/{config_id}", response_model=TestRunConfigResponse)
async def update_test_run_config(
    team_id: int,
    config_id: int,
    config_update: TestRunConfigUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_sync_db)
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
    
    # 記錄更新前的狀態（用於觸發通知）
    old_status = config_db.status
    
    # 更新欄位
    update_data = config_update.dict(exclude_unset=True)
    
    # 特殊處理 TP 票號欄位
    if 'related_tp_tickets' in update_data:
        tp_tickets = update_data.pop('related_tp_tickets')
        sync_tp_tickets_to_db(config_db, tp_tickets)
    
    # 特殊處理通知群組欄位
    if 'notify_chat_ids' in update_data or 'notify_chat_names_snapshot' in update_data:
        chat_ids = update_data.pop('notify_chat_ids', None)
        chat_names = update_data.pop('notify_chat_names_snapshot', None)
        sync_notify_chats_to_db(config_db, chat_ids, chat_names)
    
    # 更新其他欄位
    for key, value in update_data.items():
        setattr(config_db, key, value)
    
    # 提交更新
    db.commit()
    db.refresh(config_db)
    
    # 狀態變更通知觸發
    new_status = config_db.status
    if old_status != new_status and config_db.notifications_enabled:
        # 確認有設定通知群組
        if config_db.notify_chat_ids_json:
            try:
                chat_ids = json.loads(config_db.notify_chat_ids_json)
                if chat_ids:
                    lark_service = get_lark_notify_service()
                    
                    # 觸發開始執行通知
                    if new_status == TestRunStatus.ACTIVE and old_status != TestRunStatus.ACTIVE:
                        logger.info(f"Test Run Config {config_id} 狀態變更為 ACTIVE，觸發開始通知")
                        background_tasks.add_task(
                            lark_service.send_execution_started,
                            config_id, team_id
                        )
                    
                    # 觸發結束執行通知
                    elif new_status == TestRunStatus.COMPLETED and old_status != TestRunStatus.COMPLETED:
                        logger.info(f"Test Run Config {config_id} 狀態變更為 COMPLETED，觸發結束通知")
                        background_tasks.add_task(
                            lark_service.send_execution_ended,
                            config_id, team_id
                        )
                        
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"Test Run Config {config_id} 的 notify_chat_ids_json 解析失敗: {e}")
    
    return convert_db_to_model(config_db)


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_test_run_config(
    team_id: int,
    config_id: int,
    db: Session = Depends(get_sync_db)
):
    """刪除測試執行配置及相關附件"""
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
    
    try:
        await delete_test_run_config_cascade(db, team_id, config_db)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/{config_id}/validate", response_model=dict)
async def validate_test_run_config(
    team_id: int,
    config_id: int,
    db: Session = Depends(get_sync_db)
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
    db: Session = Depends(get_sync_db)
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


class RestartRequest(BaseModel):
    mode: str = Field(..., description="重置模式：all / failed / pending")
    name: Optional[str] = Field(None, description="新建立的 Test Run 名稱（未提供則預設為 Rerun - 原名）")

class StatusChangeRequest(BaseModel):
    status: TestRunStatus = Field(..., description="目標狀態")
    reason: Optional[str] = Field(None, description="狀態變更原因")


@router.put("/{config_id}/status", response_model=TestRunConfigResponse)
async def change_test_run_status(
    team_id: int,
    config_id: int,
    status_request: StatusChangeRequest,
    db: Session = Depends(get_sync_db)
):
    """更改測試執行狀態"""
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
    
    # 驗證狀態轉換是否合法
    old_status = config_db.status
    new_status = status_request.status
    
    # 定義允許的狀態轉換規則
    allowed_transitions = {
        TestRunStatus.DRAFT: [TestRunStatus.ACTIVE, TestRunStatus.ARCHIVED],
        TestRunStatus.ACTIVE: [TestRunStatus.COMPLETED, TestRunStatus.ARCHIVED],  # 進行中不可回到草稿
        TestRunStatus.COMPLETED: [TestRunStatus.ARCHIVED],  # 已完成只能歸檔
        TestRunStatus.ARCHIVED: [TestRunStatus.ACTIVE, TestRunStatus.DRAFT]
    }
    
    if new_status not in allowed_transitions.get(old_status, []):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不允許從 {old_status} 轉換到 {new_status}"
        )
    
    # 執行狀態變更
    config_db.status = new_status
    
    # 如果從 archived 狀態切換到 active，重新設定開始時間
    if old_status == TestRunStatus.ARCHIVED and new_status == TestRunStatus.ACTIVE:
        config_db.start_date = datetime.utcnow()
        config_db.end_date = None
    
    # 如果切換到 completed 狀態，設定結束時間
    if new_status == TestRunStatus.COMPLETED and not config_db.end_date:
        config_db.end_date = datetime.utcnow()
    
    # 如果切換到 active 狀態，清除結束時間
    if new_status == TestRunStatus.ACTIVE:
        config_db.end_date = None
        if not config_db.start_date:
            config_db.start_date = datetime.utcnow()
    
    config_db.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(config_db)
    
    return convert_db_to_model(config_db)


@router.post("/{config_id}/restart", response_model=dict)
async def restart_test_run(
    team_id: int,
    config_id: int,
    payload: RestartRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_sync_db)
):
    """重新執行 Test Run：建立一個新的 Test Run（複製設定），
    並依模式挑選要帶入的新測試案例項目。

    - all: 複製所有項目（結果清空）
    - failed: 僅複製 Failed、Retest 的項目（結果清空）
    - pending: 僅複製未執行（結果為 NULL）的項目
    """
    # 檢查團隊與配置存在
    config_db = db.query(TestRunConfigDB).filter(
        TestRunConfigDB.id == config_id,
        TestRunConfigDB.team_id == team_id
    ).first()
    if not config_db:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"找不到測試執行配置 ID {config_id}")

    mode = (payload.mode or '').lower()
    if mode not in ['all', 'failed', 'pending']:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支援的重新執行模式")

    # 選取要複製的項目
    q = db.query(TestRunItemDB).filter(
        TestRunItemDB.team_id == team_id,
        TestRunItemDB.config_id == config_id,
    )
    if mode == 'failed':
        q = q.filter(TestRunItemDB.test_result.in_([TestResultStatus.FAILED, TestResultStatus.RETEST]))
    elif mode == 'pending':
        # 定義「未完成」為狀態非 Passed/Failed（包含未執行、重測、不適用等）
        from sqlalchemy import or_, not_
        q = q.filter(
            or_(
                TestRunItemDB.test_result.is_(None),
                not_(TestRunItemDB.test_result.in_([TestResultStatus.PASSED, TestResultStatus.FAILED]))
            )
        )

    items = q.all()

    # 準備新名稱
    base_name = f"Rerun - {config_db.name}"
    new_name = (payload.name or '').strip() or base_name

    # 建立新的 Test Run Config（複製主要欄位，包括 TP 票號和通知設定）
    new_config = TestRunConfigDB(
        team_id=team_id,
        name=new_name,
        description=config_db.description,
        test_version=config_db.test_version,
        test_environment=config_db.test_environment,
        build_number=config_db.build_number,
        related_tp_tickets_json=config_db.related_tp_tickets_json,
        tp_tickets_search=config_db.tp_tickets_search,
        # 複製通知設定
        notifications_enabled=config_db.notifications_enabled,
        notify_chat_ids_json=config_db.notify_chat_ids_json,
        notify_chat_names_snapshot=config_db.notify_chat_names_snapshot,
        status=TestRunStatus.ACTIVE,
        start_date=datetime.utcnow(),
        end_date=None,
        total_test_cases=0,
        executed_cases=0,
        passed_cases=0,
        failed_cases=0,
        last_sync_at=None,
    )
    db.add(new_config)
    db.commit()
    db.refresh(new_config)

    created = 0
    now = datetime.utcnow()
    for item in items:
        new_item = TestRunItemDB(
            team_id=team_id,
            config_id=new_config.id,
            test_case_number=item.test_case_number,
            # 保留指派者資料（若有）
            assignee_id=item.assignee_id,
            assignee_name=item.assignee_name,
            assignee_en_name=item.assignee_en_name,
            assignee_email=item.assignee_email,
            assignee_json=item.assignee_json,
            # 重置結果與時間
            test_result=None,
            executed_at=None,
            execution_duration=None,
            # 附件與執行結果不沿用
            attachments_json=None,
            execution_results_json=None,
            # 其餘上下文資料沿用
            user_story_map_json=item.user_story_map_json,
            tcg_json=item.tcg_json,
            parent_record_json=item.parent_record_json,
            raw_fields_json=item.raw_fields_json,
            created_at=now,
            updated_at=now,
        )
        db.add(new_item)
        created += 1

    # 更新新配置的統計
    new_config.total_test_cases = created
    new_config.executed_cases = 0
    new_config.passed_cases = 0
    new_config.failed_cases = 0
    new_config.last_sync_at = now

    db.commit()
    
    # 發送開始執行通知（新配置直接進入 ACTIVE 狀態）
    if new_config.notifications_enabled and new_config.notify_chat_ids_json:
        try:
            from ..services.lark_notify_service import get_lark_notify_service
            lark_service = get_lark_notify_service()
            background_tasks.add_task(
                lark_service.send_execution_started,
                new_config.id,
                team_id
            )
        except Exception as e:
            # 通知失敗不影響主流程
            pass

    return {
        "success": True,
        "mode": mode,
        "new_config_id": new_config.id,
        "created_count": created,
    }


# @router.get("/statistics", response_model=TestRunConfigStatistics)
# async def get_test_run_statistics(
#     team_id: int,
#     db: Session = Depends(get_db)
# ):
#     """取得團隊測試執行統計資訊"""
#     verify_team_exists(team_id, db)
#     
#     configs_db = db.query(TestRunConfigDB).filter(TestRunConfigDB.team_id == team_id).all()
#     configs = [convert_db_to_model(config_db) for config_db in configs_db]
#     
#     return TestRunConfigStatistics.from_configs(configs)


# ========== TP 票號搜尋 API ==========

@search_router.get("/tp", response_model=List[TestRunConfigSummary])
async def search_configs_by_tp_tickets(
    q: str = Query(..., min_length=2, max_length=50, description="搜尋查詢字串（TP 票號）"),
    team_id: int = Query(..., description="團隊 ID"),
    limit: int = Query(20, ge=1, le=100, description="最大返回結果數"),
    db: Session = Depends(get_sync_db)
):
    """
    根據 TP 票號搜尋 Test Run Configs
    
    Args:
        q: 搜尋查詢字串，支援 TP 票號的模糊搜尋
        team_id: 團隊 ID，限制搜尋範圍
        limit: 最大返回結果數（1-100）
        db: 資料庫會話
        
    Returns:
        List[TestRunConfigSummary]: 匹配的 Test Run Config 列表
    """
    # 驗證團隊存在
    verify_team_exists(team_id, db)
    
    # 清理搜尋查詢
    search_query = q.strip().upper()
    
    # 驗證搜尋查詢格式（基本的 TP 票號格式檢查）
    if not _is_valid_tp_search_query(search_query):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="搜尋查詢必須包含 TP 票號相關內容"
        )
    
    try:
        # 使用 tp_tickets_search 欄位進行模糊搜尋
        query = db.query(TestRunConfigDB).filter(
            TestRunConfigDB.team_id == team_id,
            TestRunConfigDB.tp_tickets_search.isnot(None),
            TestRunConfigDB.tp_tickets_search.contains(search_query)
        ).order_by(
            TestRunConfigDB.updated_at.desc()
        ).limit(limit)
        
        configs_db = query.all()
        
        # 轉換為摘要格式
        summaries = []
        for config_db in configs_db:
            config = convert_db_to_model(config_db)
            
            # 過濾匹配的 TP 票號 (highlight matching tickets)
            matching_tickets = _filter_matching_tp_tickets(config.related_tp_tickets, search_query)
            
            summary = TestRunConfigSummary(
                id=config.id,
                name=config.name,
                set_id=config.set_id,
                set_name=config.set_name,
                test_environment=config.test_environment,
                build_number=config.build_number,
                test_version=config.test_version,
                related_tp_tickets=matching_tickets,  # 只返回匹配的票號
                tp_tickets_count=len(matching_tickets),
                status=config.status,
                execution_rate=config.get_execution_rate(),
                pass_rate=config.get_pass_rate(),
                total_test_cases=config.total_test_cases,
                executed_cases=config.executed_cases,
                passed_cases=config.passed_cases,
                start_date=config.start_date,
                end_date=config.end_date,
                created_at=config.created_at
            )
            summaries.append(summary)
        
        return summaries
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"搜尋 TP 票號時發生錯誤: {str(e)}"
        )


def _is_valid_tp_search_query(query: str) -> bool:
    """
    驗證搜尋查詢是否為有效的 TP 票號搜尋
    
    Args:
        query: 搜尋查詢字串
        
    Returns:
        bool: 是否為有效的搜尋查詢
    """
    # 轉為大寫進行檢查，確保大小寫不敏感
    query_upper = query.upper()
    
    # 基本檢查：必須包含 "TP"
    if "TP" not in query_upper:
        return False
    
    # 檢查是否包含數字（TP 票號應該包含數字）
    import re
    if not re.search(r'\d', query):
        return False
    
    return True


def _filter_matching_tp_tickets(tp_tickets: List[str], search_query: str) -> List[str]:
    """
    過濾出匹配搜尋查詢的 TP 票號
    
    Args:
        tp_tickets: 所有 TP 票號列表
        search_query: 搜尋查詢字串
        
    Returns:
        List[str]: 匹配的 TP 票號列表
    """
    if not tp_tickets:
        return []
    
    matching_tickets = []
    for ticket in tp_tickets:
        if search_query in ticket.upper():
            matching_tickets.append(ticket)
    
    # 如果沒有精確匹配，返回所有票號（表示整個配置匹配）
    return matching_tickets if matching_tickets else tp_tickets


@search_router.get("/tp/stats")
async def get_tp_search_statistics(
    team_id: int = Query(..., description="團隊 ID"),
    db: Session = Depends(get_sync_db)
):
    """
    取得 TP 票號搜尋相關統計資訊
    
    Args:
        team_id: 團隊 ID
        db: 資料庫會話
        
    Returns:
        Dict: TP 票號搜尋統計資訊
    """
    # 驗證團隊存在
    verify_team_exists(team_id, db)
    
    try:
        # 查詢該團隊的 TP 票號統計
        total_configs = db.query(TestRunConfigDB).filter(
            TestRunConfigDB.team_id == team_id
        ).count()
        
        configs_with_tp = db.query(TestRunConfigDB).filter(
            TestRunConfigDB.team_id == team_id,
            TestRunConfigDB.tp_tickets_search.isnot(None),
            TestRunConfigDB.tp_tickets_search != ""
        ).count()
        
        # 取得所有 TP 票號進行分析
        configs_db = db.query(TestRunConfigDB).filter(
            TestRunConfigDB.team_id == team_id,
            TestRunConfigDB.tp_tickets_search.isnot(None)
        ).all()
        
        all_tp_tickets = set()
        for config_db in configs_db:
            tp_tickets = deserialize_tp_tickets(config_db.related_tp_tickets_json)
            all_tp_tickets.update(tp_tickets)
        
        return {
            "team_id": team_id,
            "total_configs": total_configs,
            "configs_with_tp_tickets": configs_with_tp,
            "searchable_configs_percentage": round(
                (configs_with_tp / total_configs * 100) if total_configs > 0 else 0, 2
            ),
            "unique_tp_tickets": len(all_tp_tickets),
            "tp_tickets_list": sorted(list(all_tp_tickets)),
            "search_tips": [
                "使用完整的 TP 票號進行精確搜尋 (例如: TP-12345)",
                "使用部分 TP 票號進行模糊搜尋 (例如: TP-123)",
                "搜尋查詢至少需要 2 個字符",
                "搜尋結果按更新時間排序，最多返回 100 筆"
            ]
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"取得搜尋統計時發生錯誤: {str(e)}"
        )
