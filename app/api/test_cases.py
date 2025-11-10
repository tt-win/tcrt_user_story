"""
測試案例 API 路由（重構：改用本地資料庫作為單一真實來源）

- 列表/計數：改為從本地 test_cases 讀取
- 單筆查詢：改為從本地 test_cases 讀取
- 新增同步端點：觸發 init/diff/full-update
- 建立/更新/刪除（若後續需要）：先寫本地、標記 pending，再由同步流程推送到 Lark
"""

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    Query,
    UploadFile,
    File,
    Response,
    Form,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from datetime import datetime
import uuid
import json
import logging

from app.database import get_db, get_sync_db
from app.auth.dependencies import get_current_user
from app.auth.models import PermissionType
from app.models.database_models import User
from app.models.test_case import (
    TestCase,
    TestCaseCreate,
    TestCaseUpdate,
    TestCaseResponse,
    TestCaseBatchOperation,
    TestCaseBatchResponse,
)
from app.models.database_models import (
    Team as TeamDB,
    TestCaseLocal as TestCaseLocalDB,
    TestCaseSection as TestCaseSectionDB,
    SyncStatus,
)
from app.services.test_case_repo_service import TestCaseRepoService
from app.services.test_case_sync_service import TestCaseSyncService
from app.services.lark_client import LarkClient
from app.config import settings
from app.audit import audit_service, ActionType, ResourceType, AuditSeverity

router = APIRouter(prefix="/teams/{team_id}/testcases", tags=["test-cases"])

logger = logging.getLogger(__name__)


async def log_test_case_action(
    action_type: ActionType,
    current_user: User,
    team_id: int,
    resource_id: str,
    action_brief: str,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    try:
        role_value = (
            current_user.role.value
            if hasattr(current_user.role, "value")
            else str(current_user.role)
        )
        await audit_service.log_action(
            user_id=current_user.id,
            username=current_user.username,
            role=role_value,
            action_type=action_type,
            resource_type=ResourceType.TEST_CASE,
            resource_id=resource_id,
            team_id=team_id,
            details=details,
            action_brief=action_brief,
            severity=AuditSeverity.CRITICAL if action_type == ActionType.DELETE else AuditSeverity.INFO,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("寫入測試案例審計記錄失敗: %s", exc, exc_info=True)


class BulkTestCaseItem(BaseModel):
    test_case_number: str
    title: Optional[str] = None
    priority: Optional[str] = "Medium"
    precondition: Optional[str] = None
    steps: Optional[str] = None
    expected_result: Optional[str] = None
    tcg_numbers: Optional[List[str]] = None


class BulkCreateRequest(BaseModel):
    items: List[BulkTestCaseItem]


class BulkCreateResponse(BaseModel):
    success: bool
    created_count: int = 0
    duplicates: List[str] = []
    errors: List[str] = []


TCG_TABLE_ID_DEFAULT = "tblcK6eF3yQCuwwl"


def normalize_tcg_number(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    upper = str(value).strip().upper().replace(" ", "")
    if not upper:
        return None

    if upper.startswith("TCG"):
        upper = upper[3:]
        if upper.startswith("-"):
            upper = upper[1:]

    if upper.isdigit():
        return f"TCG-{upper}"
    return None


def build_tcg_items(numbers: List[str]) -> List[str]:
    """
    直接返回 TCG 單號列表（簡化版本）
    
    Args:
        numbers: TCG 單號列表
    
    Returns:
        正規化後的 TCG 單號列表
    """
    items: List[str] = []
    seen: set[str] = set()

    for raw in numbers:
        normalized = normalize_tcg_number(raw)
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        items.append(normalized)

    return items


# ============ USM Integration: Get Test Cases by JIRA Tickets ============
@router.get("/by-tickets")
async def get_test_cases_by_jira_tickets(
    team_id: int,
    tickets: str = Query(...),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    """
    按 JIRA tickets 获取相关的测试案例
    
    Parameters:
        team_id: 团队 ID
        tickets: 逗号分隔的 JIRA tickets (如: TEST-123,TEST-456)
    
    Returns:
        List of test cases that contain any of the specified JIRA tickets
    """
    try:
        # Verify team exists
        team = db.query(TeamDB).filter(TeamDB.id == team_id).first()
        if not team:
            raise HTTPException(status_code=404, detail="团队不存在")
        
        # Parse tickets
        ticket_list = [t.strip().upper() for t in tickets.split(',') if t.strip()]
        if not ticket_list:
            return []
        
        # Query all test cases for the team
        test_cases = db.query(TestCaseLocalDB).filter(
            TestCaseLocalDB.team_id == team_id
        ).all()
        
        logger.info(f"Searching for tickets {ticket_list} in {len(test_cases)} test cases for team {team_id}")
        
        # Filter test cases that have matching JIRA tickets
        matching_cases = []
        
        for tc in test_cases:
            jira_tickets = []
            
            # tcg_json is an array of objects with 'text' field containing the TCG number
            if tc.tcg_json:
                try:
                    tcg_data = json.loads(tc.tcg_json)
                    
                    # 新格式：直接是字符串列表 ["TCG-12345", "ICR-45683"]
                    if isinstance(tcg_data, list):
                        for item in tcg_data:
                            if isinstance(item, str) and item:
                                jira_tickets.append(item)
                    # 舊格式相容性：如果還有舊格式的資料
                    elif isinstance(tcg_data, dict):
                        # 嘗試各種鍵名
                        for key in ['jira_tickets', 'jira', 'tcg_tickets', 'tcg', 'text', 'tickets', 'text_arr']:
                            if key in tcg_data:
                                val = tcg_data.get(key)
                                if isinstance(val, list):
                                    jira_tickets.extend([t for t in val if t])
                                elif isinstance(val, str) and val:
                                    jira_tickets.append(val)
                                break
                except (json.JSONDecodeError, TypeError, AttributeError) as e:
                    logger.error(f"Error parsing tcg_json for {tc.test_case_number}: {e}")
            
            # Also try raw_fields_json if tcg_json didn't have results
            if not jira_tickets and tc.raw_fields_json:
                try:
                    raw_fields = json.loads(tc.raw_fields_json)
                    
                    if isinstance(raw_fields, dict):
                        # Try common field names
                        for key in ['jira_tickets', 'jira', 'tcg_tickets', 'tcg', 'jira_ticket', 'tcg_ticket', 'tickets']:
                            if key in raw_fields:
                                val = raw_fields.get(key)
                                if isinstance(val, list):
                                    jira_tickets = val
                                elif isinstance(val, str):
                                    jira_tickets = [val]
                                break
                except (json.JSONDecodeError, TypeError, AttributeError) as e:
                    logger.error(f"Error parsing raw_fields_json for {tc.test_case_number}: {e}")
            
            # Convert to uppercase for comparison
            jira_tickets_upper = [str(t).upper() for t in jira_tickets if t]
            
            # Check if any of the search tickets match
            if any(ticket in jira_tickets_upper for ticket in ticket_list):
                logger.info(f"Match found for {tc.test_case_number}: {jira_tickets}")
                matching_cases.append({
                    "record_id": tc.lark_record_id or tc.id,
                    "test_case_number": tc.test_case_number,
                    "title": tc.title,
                    "priority": tc.priority.value if tc.priority else "MEDIUM",
                    "description": tc.precondition or "",
                    "jira_tickets": jira_tickets,
                })
        
        logger.info(f"Found {len(matching_cases)} matching test cases")
        return matching_cases
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching test cases by JIRA tickets: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取测试案例失败: {str(e)}")


@router.get("/", response_model=List[TestCaseResponse])
async def get_test_cases(
    team_id: int,
    response: Response,
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
    # 搜尋參數
    search: Optional[str] = Query(None, description="標題模糊搜尋"),
    tcg_filter: Optional[str] = Query(None, description="TCG 單號過濾"),
    priority_filter: Optional[str] = Query(None, description="優先級過濾"),
    test_result_filter: Optional[str] = Query(None, description="測試結果過濾"),
    assignee_filter: Optional[str] = Query(None, description="指派人過濾"),
    set_id: Optional[int] = Query(None, description="Test Case Set ID 過濾"),
    # 排序參數
    sort_by: Optional[str] = Query("created_at", description="排序欄位"),
    sort_order: Optional[str] = Query("desc", description="排序順序 (asc/desc)"),
    # 分頁參數
    skip: int = Query(0, ge=0, description="跳過筆數"),
    limit: int = Query(10000, ge=1, le=100000, description="回傳筆數"),
    with_meta: bool = Query(False, description="是否回傳分頁中繼資料"),
    load_all: bool = Query(False, description="忽略分頁，一次載入全部資料並回傳"),
):
    """取得測試案例列表（需要對該團隊的讀取權限）
    - 回應標頭包含:
      - X-Total-Count: 總筆數
      - X-Has-Next: 是否尚有下一頁（true/false）
    - 若 with_meta=true，回傳 { items, page: { skip, limit, total, hasNext } }
    """
    # 權限檢查
    from app.auth.models import UserRole
    from app.auth.permission_service import permission_service

    if current_user.role != UserRole.SUPER_ADMIN:
        permission_check = await permission_service.check_team_permission(
            current_user.id, team_id, PermissionType.READ, current_user.role
        )
        if not permission_check.has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="無權限存取此團隊的測試案例",
            )

    try:
        service = TestCaseRepoService(db)
        # 先取 total 以便計算 hasNext
        total = service.count(
            team_id=team_id,
            search=search,
            tcg_filter=tcg_filter,
            priority_filter=priority_filter,
            test_result_filter=test_result_filter,
            assignee_filter=assignee_filter,
            test_case_set_id=set_id,
        )
        # 一次載入全部（交由前端快取）
        if load_all:
            skip = 0
            limit = total if total > 0 else 1
            has_next = False
        else:
            has_next = total > (skip + limit)
        items = service.list(
            team_id=team_id,
            search=search,
            tcg_filter=tcg_filter,
            priority_filter=priority_filter,
            test_result_filter=test_result_filter,
            assignee_filter=assignee_filter,
            test_case_set_id=set_id,
            sort_by=sort_by or "created_at",
            sort_order=sort_order or "desc",
            skip=skip,
            limit=limit,
        )
        # 設置標頭
        response.headers["X-Total-Count"] = str(total)
        response.headers["X-Has-Next"] = "true" if has_next else "false"
        if with_meta:
            return {
                "items": items,
                "page": {
                    "skip": skip,
                    "limit": limit,
                    "total": total,
                    "hasNext": has_next,
                },
            }
        return items
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"取得測試案例失敗: {str(e)}",
        )


@router.get("/count", response_model=dict)
async def get_test_cases_count(
    team_id: int,
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
    # 搜尋參數（與 get_test_cases 相同）
    search: Optional[str] = Query(None, description="標題模糊搜尋"),
    tcg_filter: Optional[str] = Query(None, description="TCG 單號過濾"),
    priority_filter: Optional[str] = Query(None, description="優先級過濾"),
    test_result_filter: Optional[str] = Query(None, description="測試結果過濾"),
    assignee_filter: Optional[str] = Query(None, description="指派人過濾"),
    set_id: Optional[int] = Query(None, description="Test Case Set ID 過濾"),
):
    """取得符合條件的測試案例數量（需要對該團隊的讀取權限）"""
    # 權限檢查
    from app.auth.models import UserRole
    from app.auth.permission_service import permission_service

    if current_user.role != UserRole.SUPER_ADMIN:
        permission_check = await permission_service.check_team_permission(
            current_user.id, team_id, PermissionType.READ, current_user.role
        )
        if not permission_check.has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="無權限存取此團隊的測試案例數量",
            )

    try:
        service = TestCaseRepoService(db)
        total = service.count(
            team_id=team_id,
            search=search,
            tcg_filter=tcg_filter,
            priority_filter=priority_filter,
            test_result_filter=test_result_filter,
            assignee_filter=assignee_filter,
            test_case_set_id=set_id,
        )
        return {"total": total}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"取得測試案例數量失敗: {str(e)}",
        )


@router.get("/diff", response_model=dict)
async def diff_test_cases(
    team_id: int,
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    # 權限檢查
    from app.auth.models import UserRole
    from app.auth.permission_service import permission_service

    if current_user.role != UserRole.SUPER_ADMIN:
        permission_check = await permission_service.check_team_permission(
            current_user.id, team_id, PermissionType.READ, current_user.role
        )
        if not permission_check.has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="無權限檢視此團隊的測試案例差異",
            )

    team = db.query(TeamDB).filter(TeamDB.id == team_id).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"找不到團隊 ID {team_id}"
        )
    if not (team.wiki_token and team.test_case_table_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="此團隊尚未設定 Lark 連線資訊",
        )

    try:
        lark = LarkClient(
            app_id=settings.lark.app_id, app_secret=settings.lark.app_secret
        )
        svc = TestCaseSyncService(
            team_id=team_id,
            db=db,
            lark_client=lark,
            wiki_token=team.wiki_token,
            table_id=team.test_case_table_id,
        )
        result = svc.compute_diff()
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"計算差異失敗: {str(e)}",
        )


@router.post("/diff/apply", response_model=dict)
async def apply_diff_test_cases(
    team_id: int,
    payload: Dict[str, Any],
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    from app.auth.models import UserRole
    from app.auth.permission_service import permission_service

    if current_user.role != UserRole.SUPER_ADMIN:
        permission_check = await permission_service.check_team_permission(
            current_user.id, team_id, PermissionType.WRITE, current_user.role
        )
        if not permission_check.has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="無權限套用此團隊的測試案例差異",
            )

    decisions = payload.get("decisions") or []
    if not isinstance(decisions, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="decisions 必須是陣列"
        )

    team = db.query(TeamDB).filter(TeamDB.id == team_id).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"找不到團隊 ID {team_id}"
        )
    if not (team.wiki_token and team.test_case_table_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="此團隊尚未設定 Lark 連線資訊",
        )

    try:
        lark = LarkClient(
            app_id=settings.lark.app_id, app_secret=settings.lark.app_secret
        )
        svc = TestCaseSyncService(
            team_id=team_id,
            db=db,
            lark_client=lark,
            wiki_token=team.wiki_token,
            table_id=team.test_case_table_id,
        )
        result = svc.apply_diff(decisions)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"套用差異失敗: {str(e)}",
        )


@router.get("/{record_id}", response_model=TestCaseResponse)
async def get_test_case(
    team_id: int,
    record_id: str,
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    """取得特定測試案例（需要對該團隊的讀取權限）。預設會載入附件清單。
    支援：record_id 為 lark_record_id 或本地數字 id
    """
    # 權限檢查
    from app.auth.models import UserRole
    from app.auth.permission_service import permission_service

    if current_user.role != UserRole.SUPER_ADMIN:
        permission_check = await permission_service.check_team_permission(
            current_user.id, team_id, PermissionType.READ, current_user.role
        )
        if not permission_check.has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="無權限存取此團隊的測試案例",
            )

    try:
        service = TestCaseRepoService(db)
        result = service.get_by_lark_record_id(
            team_id, record_id, include_attachments=True
        )
        if not result:
            # 嘗試以本地數字 id 讀取（相容本地新建而無 lark_record_id 的情況）
            item = None
            try:
                local_id = int(record_id)
                item = (
                    db.query(TestCaseLocalDB)
                    .filter(
                        TestCaseLocalDB.team_id == team_id,
                        TestCaseLocalDB.id == local_id,
                    )
                    .first()
                )
            except Exception:
                item = None
            if not item:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"找不到測試案例 {record_id}",
                )
            # 轉換本地資料為回應
            # 轉入附件
            import json

            attachments = []
            try:
                data = (
                    json.loads(item.attachments_json) if item.attachments_json else []
                )
                base_url = "/attachments"
                for it in data if isinstance(data, list) else []:
                    token = it.get("stored_name") or it.get("name") or ""
                    name = it.get("name") or it.get("stored_name") or "file"
                    size = int(it.get("size") or 0)
                    mime = it.get("type") or "application/octet-stream"
                    rel = it.get("relative_path") or ""
                    url = f"{base_url}/{rel}" if rel else ""
                    attachments.append(
                        {
                            "file_token": token,
                            "name": name,
                            "size": size,
                            "type": mime,
                            "url": url,
                            "tmp_url": url,
                        }
                    )
            except Exception:
                attachments = []

            # 解析 TCG - 新格式：直接是字符串列表
            tcg_items = []
            try:
                if item.tcg_json:
                    data = json.loads(item.tcg_json)
                    # 新格式：["TCG-12345", "ICR-45683"]
                    if isinstance(data, list):
                        tcg_items = [str(t) for t in data if t]
            except Exception:
                tcg_items = []

            return TestCaseResponse(
                record_id=item.lark_record_id or str(item.id),
                test_case_number=item.test_case_number or "",
                title=item.title or "",
                priority=(
                    item.priority.value
                    if hasattr(item.priority, "value")
                    else (item.priority or "")
                ),
                precondition=item.precondition or "",
                steps=item.steps or "",
                expected_result=item.expected_result or "",
                assignee=None,
                test_result=(
                    item.test_result.value
                    if hasattr(item.test_result, "value")
                    else (item.test_result or None)
                ),
                attachments=attachments,
                test_results_files=[],
                user_story_map=[],
                tcg=tcg_items,
                parent_record=[],
                team_id=item.team_id,
                executed_at=None,
                created_at=item.created_at,
                updated_at=item.updated_at,
                last_sync_at=item.last_sync_at,
                raw_fields={},
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"取得測試案例失敗: {str(e)}",
        )


@router.post("/", response_model=TestCaseResponse, status_code=status.HTTP_201_CREATED)
async def create_test_case(
    team_id: int,
    case: TestCaseCreate,
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    """建立新的測試案例（需要對該團隊的寫入權限）
    - 若 case.temp_upload_id 存在，將 attachments/staging/{temp_upload_id} 下檔案搬移到最終路徑
      attachments/test-cases/{team_id}/{test_case_number}/ 並寫入 attachments_json。
    """
    # 權限檢查
    from app.auth.models import UserRole
    from app.auth.permission_service import permission_service

    if current_user.role != UserRole.SUPER_ADMIN:
        permission_check = await permission_service.check_team_permission(
            current_user.id, team_id, PermissionType.WRITE, current_user.role
        )
        if not permission_check.has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="無權限在此團隊建立測試案例",
            )

    try:
        import json
        from pathlib import Path
        from shutil import move

        # 檢查重複 test_case_number
        exists = (
            db.query(TestCaseLocalDB)
            .filter(
                TestCaseLocalDB.team_id == team_id,
                TestCaseLocalDB.test_case_number == case.test_case_number,
            )
            .first()
        )
        if exists:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="測試案例編號已存在"
            )

        item = TestCaseLocalDB(
            team_id=team_id,
            lark_record_id=None,
            test_case_number=case.test_case_number,
            title=case.title,
            priority=case.priority,
            precondition=case.precondition,
            steps=case.steps,
            expected_result=case.expected_result,
            test_result=case.test_result,
            assignee_json=None,
            attachments_json=None,
            user_story_map_json=None,
            tcg_json=None,
            parent_record_json=None,
            raw_fields_json=None,
            sync_status=SyncStatus.PENDING,
            local_version=1,
        )
        db.add(item)
        db.flush()  # 取得自增 id

        # 如有暫存附件，搬移並記錄
        if getattr(case, "temp_upload_id", None):
            project_root = Path(__file__).resolve().parents[2]
            from app.config import settings

            root_dir = (
                Path(settings.attachments.root_dir)
                if settings.attachments.root_dir
                else (project_root / "attachments")
            )
            staging_dir = root_dir / "staging" / case.temp_upload_id
            if staging_dir.exists() and staging_dir.is_dir():
                final_dir = (
                    root_dir / "test-cases" / str(team_id) / item.test_case_number
                )
                final_dir.mkdir(parents=True, exist_ok=True)

                metas = []
                for p in sorted(staging_dir.iterdir()):
                    if not p.is_file():
                        continue
                    dest = final_dir / p.name
                    move(str(p), str(dest))
                    metas.append(
                        {
                            "name": p.name,
                            "stored_name": p.name,
                            "size": dest.stat().st_size,
                            "type": "application/octet-stream",
                            "relative_path": str(dest.relative_to(root_dir)),
                            "absolute_path": str(dest),
                            "uploaded_at": datetime.utcnow().isoformat(),
                        }
                    )
                item.attachments_json = json.dumps(metas, ensure_ascii=False)
                # 清掉空 staging 目錄（非致命）
                try:
                    staging_dir.rmdir()
                except Exception:
                    pass

        db.commit()
        action_brief = f"{current_user.username} created Test Case: {item.test_case_number}"
        if item.title:
            action_brief += f" ({item.title})"
        await log_test_case_action(
            action_type=ActionType.CREATE,
            current_user=current_user,
            team_id=team_id,
            resource_id=item.test_case_number or str(item.id),
            action_brief=action_brief,
            details={
                "record_id": item.id,
                "test_case_number": item.test_case_number,
                "title": item.title,
            },
        )

        # 回傳本地物件
        return TestCaseResponse(
            record_id=str(item.id),
            test_case_number=item.test_case_number,
            title=item.title,
            priority=(
                item.priority.value
                if hasattr(item.priority, "value")
                else (item.priority or "")
            ),
            precondition=item.precondition,
            steps=item.steps,
            expected_result=item.expected_result,
            assignee_name=None,
            test_result=(
                item.test_result.value
                if hasattr(item.test_result, "value")
                else (item.test_result or None)
            ),
            attachment_count=0,
            execution_result_count=0,
            total_attachment_count=0,
            executed_at=None,
            created_at=item.created_at,
            updated_at=item.updated_at,
            last_sync_at=item.last_sync_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"建立測試案例失敗: {str(e)}",
        )


@router.put("/{record_id}", response_model=TestCaseResponse)
async def update_test_case(
    team_id: int,
    record_id: str,
    case_update: TestCaseUpdate,
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    """更新測試案例（需要對該團隊的寫入權限）。
    規則：優先以本地 id（純數字）尋找；否則以 lark_record_id 尋找。
    """
    # 權限檢查
    from app.auth.models import UserRole
    from app.auth.permission_service import permission_service

    if current_user.role != UserRole.SUPER_ADMIN:
        permission_check = await permission_service.check_team_permission(
            current_user.id, team_id, PermissionType.WRITE, current_user.role
        )
        if not permission_check.has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="無權限修改此團隊的測試案例",
            )

    try:
        import json
        from pathlib import Path
        from shutil import move

        item = None
        # 優先：本地數字 id
        try:
            rid_int = int(record_id)
            item = (
                db.query(TestCaseLocalDB).filter(TestCaseLocalDB.id == rid_int).first()
            )
            if item and item.team_id != team_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"測試案例 id={rid_int} 屬於 team={item.team_id}",
                )
        except ValueError:
            item = None
        # 次選：lark_record_id
        if item is None:
            item = (
                db.query(TestCaseLocalDB)
                .filter(
                    TestCaseLocalDB.team_id == team_id,
                    TestCaseLocalDB.lark_record_id == record_id,
                )
                .first()
            )
        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"找不到測試案例 {record_id}",
            )

        recorded_number = item.test_case_number
        recorded_title = item.title
        recorded_id = getattr(item, "id", None)

        changed = False
        changed_fields: List[str] = []

        if case_update.test_case_number is not None:
            item.test_case_number = case_update.test_case_number
            changed = True
            changed_fields.append("test_case_number")
        if case_update.title is not None:
            item.title = case_update.title
            changed = True
            changed_fields.append("title")
        if case_update.priority is not None:
            item.priority = case_update.priority
            changed = True
            changed_fields.append("priority")
        if case_update.precondition is not None:
            item.precondition = case_update.precondition
            changed = True
            changed_fields.append("precondition")
        if case_update.steps is not None:
            item.steps = case_update.steps
            changed = True
            changed_fields.append("steps")
        if case_update.expected_result is not None:
            item.expected_result = case_update.expected_result
            changed = True
            changed_fields.append("expected_result")
        if case_update.test_result is not None:
            item.test_result = case_update.test_result
            changed = True
            changed_fields.append("test_result")

        # 處理 TCG 欄位更新：支援字串（逗號/空白/換行分隔的單號）或字符串列表
        if hasattr(case_update, "tcg") and case_update.tcg is not None:
            try:
                tcg_numbers: list[str] = []
                
                if isinstance(case_update.tcg, str):
                    s = case_update.tcg.strip()
                    if s:
                        # 解析多個單號（使用逗號、空白或換行分隔）
                        parts = [
                            p.strip()
                            for p in s.replace("\n", ",").replace(" ", ",").split(",")
                        ]
                        tcg_numbers = [p for p in parts if p]
                elif isinstance(case_update.tcg, list):
                    # 直接使用列表中的字符串
                    tcg_numbers = [str(t) for t in case_update.tcg if t]
                
                # 正規化 TCG 單號
                normalized_numbers = [normalize_tcg_number(n) for n in tcg_numbers]
                normalized_numbers = [n for n in normalized_numbers if n]
                
                # 存儲為 JSON 列表
                item.tcg_json = json.dumps(normalized_numbers, ensure_ascii=False)
                changed = True
                if "tcg" not in changed_fields:
                    changed_fields.append("tcg")
            except Exception as e:
                # 若 TCG 處理失敗，丟出 400 錯誤
                raise HTTPException(status_code=400, detail=f"更新 TCG 欄位失敗: {e}")

        # 如有暫存附件，搬移並與既存附件合併
        if getattr(case_update, "temp_upload_id", None):
            project_root = Path(__file__).resolve().parents[2]
            from app.config import settings

            root_dir = (
                Path(settings.attachments.root_dir)
                if settings.attachments.root_dir
                else (project_root / "attachments")
            )
            staging_dir = root_dir / "staging" / case_update.temp_upload_id
            if staging_dir.exists() and staging_dir.is_dir():
                final_dir = (
                    root_dir
                    / "test-cases"
                    / str(team_id)
                    / (item.test_case_number or str(item.id))
                )
                final_dir.mkdir(parents=True, exist_ok=True)

                existing = []
                try:
                    if item.attachments_json:
                        data = json.loads(item.attachments_json)
                        if isinstance(data, list):
                            existing = data
                except Exception:
                    existing = []

                for p in sorted(staging_dir.iterdir()):
                    if not p.is_file():
                        continue
                    dest = final_dir / p.name
                    move(str(p), str(dest))
                    existing.append(
                        {
                            "name": p.name,
                            "stored_name": p.name,
                            "size": dest.stat().st_size,
                            "type": "application/octet-stream",
                            "relative_path": str(dest.relative_to(root_dir)),
                            "absolute_path": str(dest),
                            "uploaded_at": datetime.utcnow().isoformat(),
                        }
                    )
                item.attachments_json = json.dumps(existing, ensure_ascii=False)
                if "attachments" not in changed_fields:
                    changed_fields.append("attachments")
                try:
                    staging_dir.rmdir()
                except Exception:
                    pass
                changed = True

        if changed:
            item.updated_at = datetime.utcnow()
            item.sync_status = SyncStatus.PENDING
        db.commit()

        if changed:
            action_brief = f"{current_user.username} updated Test Case: {item.test_case_number or record_id}"
            if item.title:
                action_brief += f" ({item.title})"
            await log_test_case_action(
                action_type=ActionType.UPDATE,
                current_user=current_user,
                team_id=team_id,
                resource_id=item.test_case_number or str(item.id),
                action_brief=action_brief,
                details={
                    "record_id": item.id,
                    "test_case_number": item.test_case_number,
                    "changed_fields": changed_fields,
                },
            )

        # 解析 TCG JSON 以便返回
        tcg_list = []
        if item.tcg_json:
            try:
                tcg_data = json.loads(item.tcg_json)
                if isinstance(tcg_data, list):
                    from app.models.lark_types import LarkRecord
                    for tcg_item in tcg_data:
                        if isinstance(tcg_item, dict):
                            tcg_list.append(LarkRecord(
                                record_ids=tcg_item.get("record_ids", []),
                                table_id=tcg_item.get("table_id", ""),
                                text=tcg_item.get("text", ""),
                                text_arr=tcg_item.get("text_arr", []),
                                type=tcg_item.get("type", "text")
                            ))
            except Exception as e:
                # 如果解析失敗，返回空陣列
                tcg_list = []
        
        return TestCaseResponse(
            record_id=str(item.id),
            test_case_number=item.test_case_number or "",
            title=item.title or "",
            priority=(
                item.priority.value
                if hasattr(item.priority, "value")
                else (item.priority or "")
            ),
            precondition=item.precondition or "",
            steps=item.steps or "",
            expected_result=item.expected_result or "",
            assignee_name=None,
            test_result=(
                item.test_result.value
                if hasattr(item.test_result, "value")
                else (item.test_result or None)
            ),
            tcg=tcg_list,  # 添加 TCG 欄位
            attachment_count=0,
            execution_result_count=0,
            total_attachment_count=0,
            executed_at=None,
            created_at=item.created_at,
            updated_at=item.updated_at,
            last_sync_at=item.last_sync_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新測試案例失敗: {str(e)}",
        )


# 規則：首選 DB 本地 id 版本（更精準更快）
@router.post("/staging/upload", response_model=dict)
async def upload_test_case_attachments_staging(
    team_id: int,
    files: List[UploadFile] = File(...),
    temp_upload_id: Optional[str] = Form(None),
    db: Session = Depends(get_sync_db),
):
    """暫存上傳附件（未決定或尚未建立 Test Case 時使用）
    - 回傳 temp_upload_id，前端於建立/更新 Test Case 時帶回即可完成搬移與綁定。
    目錄：attachments/staging/{temp_upload_id}/
    """
    import re, json
    from pathlib import Path
    from datetime import datetime

    # 生成或沿用 staging id
    sid = temp_upload_id or uuid.uuid4().hex

    project_root = Path(__file__).resolve().parents[2]
    from app.config import settings

    root_dir = (
        Path(settings.attachments.root_dir)
        if settings.attachments.root_dir
        else (project_root / "attachments")
    )
    staging_dir = root_dir / "staging" / sid
    staging_dir.mkdir(parents=True, exist_ok=True)

    safe_re = re.compile(r"[^A-Za-z0-9_.\-]+")
    ts_prefix = datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f")

    uploaded = []
    for f in files:
        orig = f.filename or "unnamed"
        safe = safe_re.sub("_", orig)
        stored = f"{ts_prefix}-{safe}"
        path = staging_dir / stored
        content = await f.read()
        with open(path, "wb") as out:
            out.write(content)
        uploaded.append(
            {
                "name": orig,
                "stored_name": stored,
                "size": len(content),
                "type": f.content_type or "application/octet-stream",
                "relative_path": str(path.relative_to(root_dir)),
                "absolute_path": str(path),
                "uploaded_at": datetime.utcnow().isoformat(),
            }
        )

    return {
        "success": True,
        "temp_upload_id": sid,
        "count": len(uploaded),
        "files": uploaded,
        "base_url": "/attachments",
    }


@router.post("/sync", response_model=dict)
async def sync_test_cases(
    team_id: int,
    mode: str = Query(
        ...,
        description="同步模式: init (Lark->系統), diff (雙向比對), full-update (系統->Lark)",
        pattern="^(init|diff|full-update)$",
    ),
    prune: bool = Query(
        False, description="full-update 時是否清除 Lark 上本地不存在的案例"
    ),
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    """觸發測試案例同步（需要對該團隊的寫入權限）

    - init: 從 Lark 匯入到本地（清空本地 team 資料後重建）
    - diff: 比對差異，Lark->本地 更新/新增，本地缺失者標記 PENDING
    - full-update: 以本地覆蓋 Lark（create/update；可選 prune 刪除 Lark 多餘項）
    """
    # 權限檢查
    from app.auth.models import UserRole
    from app.auth.permission_service import permission_service

    if current_user.role != UserRole.SUPER_ADMIN:
        permission_check = await permission_service.check_team_permission(
            current_user.id, team_id, PermissionType.WRITE, current_user.role
        )
        if not permission_check.has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="無權限執行此團隊的測試案例同步",
            )

    # 讀取團隊配置
    team = db.query(TeamDB).filter(TeamDB.id == team_id).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"找不到團隊 ID {team_id}"
        )
    if not (team.wiki_token and team.test_case_table_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="此團隊尚未設定 Lark 連線資訊",
        )

    try:
        lark = LarkClient(
            app_id=settings.lark.app_id, app_secret=settings.lark.app_secret
        )
        svc = TestCaseSyncService(
            team_id=team_id,
            db=db,
            lark_client=lark,
            wiki_token=team.wiki_token,
            table_id=team.test_case_table_id,
        )
        if mode == "init":
            result = svc.init_sync()
        elif mode == "diff":
            result = svc.diff_sync()
        elif mode == "full-update":
            result = svc.full_update(prune=prune)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="不支援的同步模式"
            )
        return {"success": True, **result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"測試案例同步失敗: {str(e)}",
        )


@router.post("/{test_case_id:int}/attachments", response_model=dict)
async def upload_test_case_attachments_by_id(
    team_id: int,
    test_case_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_sync_db),
):
    """上傳測試案例附件（本地 id 版）"""
    import re, json
    from pathlib import Path
    from datetime import datetime

    # 先以本地 id 查找（不帶 team 條件，避免 team_id 傳錯時無法診斷）
    item = db.query(TestCaseLocalDB).filter(TestCaseLocalDB.id == test_case_id).first()
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到測試案例 id={test_case_id}",
        )
    # 確認 team 一致，不一致回報 409 並提示正確 team_id
    if item.team_id != team_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"測試案例 id={test_case_id} 屬於 team={item.team_id}，請改用該 team_id 或確認路徑參數。",
        )

    # 固定專案根
    project_root = Path(__file__).resolve().parents[2]
    from app.config import settings

    root_dir = (
        Path(settings.attachments.root_dir)
        if settings.attachments.root_dir
        else (project_root / "attachments")
    )
    base_dir = root_dir / "test-cases" / str(team_id) / item.test_case_number
    base_dir.mkdir(parents=True, exist_ok=True)

    # 既存附件
    existing = []
    if item.attachments_json:
        try:
            data = json.loads(item.attachments_json)
            if isinstance(data, list):
                existing = data
        except Exception:
            existing = []

    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f")
    safe_re = re.compile(r"[^A-Za-z0-9_.\-]+")
    uploaded = []

    for f in files:
        orig_name = f.filename or "unnamed"
        name_part = safe_re.sub("_", orig_name)
        stored_name = f"{ts}-{name_part}"
        stored_path = base_dir / stored_name
        content = await f.read()
        with open(stored_path, "wb") as out:
            out.write(content)
        meta = {
            "name": orig_name,
            "stored_name": stored_name,
            "size": len(content),
            "type": f.content_type or "application/octet-stream",
            "relative_path": str(stored_path.relative_to(root_dir)),
            "absolute_path": str(stored_path),
            "uploaded_at": datetime.utcnow().isoformat(),
        }
        existing.append(meta)
        uploaded.append(meta)

    item.attachments_json = json.dumps(existing, ensure_ascii=False)
    db.commit()

    return {
        "success": True,
        "uploaded": len(uploaded),
        "files": uploaded,
        "base_url": "/attachments",
    }


@router.get("/{test_case_id:int}/attachments", response_model=dict)
async def list_test_case_attachments(
    team_id: int, test_case_id: int, db: Session = Depends(get_sync_db)
):
    """列出某測試案例的附件（以本地 id）。"""
    import json
    from pathlib import Path

    item = db.query(TestCaseLocalDB).filter(TestCaseLocalDB.id == test_case_id).first()
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到測試案例 id={test_case_id}",
        )
    if item.team_id != team_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"測試案例 id={test_case_id} 屬於 team={item.team_id}",
        )

    files = []
    if item.attachments_json:
        try:
            files = json.loads(item.attachments_json) or []
        except Exception:
            files = []
    return {
        "success": True,
        "files": files,
        "count": len(files),
        "base_url": "/attachments",
    }


@router.delete("/{test_case_id:int}/attachments/{target}", response_model=dict)
async def delete_test_case_attachment(
    team_id: int, test_case_id: int, target: str, db: Session = Depends(get_sync_db)
):
    """刪除單一附件（以本地整數 id）。"""
    return await _delete_attachment_common(team_id, target, db, id_value=test_case_id)


@router.delete("/{record_key}/attachments/{target}", response_model=dict)
async def delete_test_case_attachment_by_key(
    team_id: int, record_key: str, target: str, db: Session = Depends(get_sync_db)
):
    """刪除單一附件（接受 lark_record_id 或本地整數 id）。"""
    # 嘗試轉成 int，否則視為 lark_record_id
    id_value = None
    lark_id = None
    try:
        id_value = int(record_key)
    except Exception:
        lark_id = record_key
    return await _delete_attachment_common(
        team_id, target, db, id_value=id_value, lark_record_id=lark_id
    )


@router.delete(
    "/by-number/{test_case_number}/attachments/{target}", response_model=dict
)
async def delete_test_case_attachment_by_number(
    team_id: int, test_case_number: str, target: str, db: Session = Depends(get_sync_db)
):
    """刪除單一附件（以測試案例編號）。"""
    return await _delete_attachment_common(
        team_id, target, db, test_case_number=test_case_number
    )


async def _delete_attachment_common(
    team_id: int,
    target: str,
    db: Session,
    id_value: int | None = None,
    lark_record_id: str | None = None,
    test_case_number: str | None = None,
):
    import json
    import urllib.parse
    import unicodedata
    from pathlib import Path

    # 取得項目
    q = db.query(TestCaseLocalDB)
    if id_value is not None:
        item = q.filter(TestCaseLocalDB.id == id_value).first()
    elif lark_record_id is not None:
        item = q.filter(
            TestCaseLocalDB.team_id == team_id,
            TestCaseLocalDB.lark_record_id == lark_record_id,
        ).first()
    elif test_case_number is not None:
        item = q.filter(
            TestCaseLocalDB.team_id == team_id,
            TestCaseLocalDB.test_case_number == test_case_number,
        ).first()
    else:
        item = None

    if not item:
        key = (
            id_value
            if id_value is not None
            else (lark_record_id or test_case_number or "")
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"找不到測試案例 {key}"
        )
    if item.team_id != team_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"測試案例 id={item.id} 屬於 team={item.team_id}",
        )

    # 解析現有附件
    files = []
    try:
        if item.attachments_json:
            files = json.loads(item.attachments_json) or []
    except Exception:
        files = []

    # 準備多種比較字串：原始、URL 解碼後、兩者的 NFC/NFD 版本
    candidates = set()

    def add_variants(s: str):
        if not s:
            return
        try:
            candidates.add(s)
            u = urllib.parse.unquote(s)
            candidates.add(u)
            # Unicode 正規化
            for form in ("NFC", "NFD"):
                candidates.add(unicodedata.normalize(form, s))
                candidates.add(unicodedata.normalize(form, u))
        except Exception:
            candidates.add(s)

    add_variants(target)

    def matches(entry_name: str) -> bool:
        if not entry_name:
            return False
        entry_variants = set()
        for form in ("NFC", "NFD"):
            entry_variants.add(unicodedata.normalize(form, entry_name))
        # 直接比對或尾端比對（處理含時間戳前綴的 stored_name）
        for cand in candidates:
            if cand in entry_variants:
                return True
            for v in entry_variants:
                if v.endswith(cand):
                    return True
        return False

    # 尋找目標：先比對 stored_name，再比對 name
    idx = None
    for i, f in enumerate(files):
        if matches(f.get("stored_name") or "") or matches(f.get("name") or ""):
            idx = i
            break

    if idx is None:
        key = (
            id_value
            if id_value is not None
            else (lark_record_id or test_case_number or "")
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到附件 {target}（case={key}）",
        )

    # 刪除檔案
    project_root = Path(__file__).resolve().parents[2]
    from app.config import settings

    root_dir = (
        Path(settings.attachments.root_dir)
        if settings.attachments.root_dir
        else (project_root / "attachments")
    )
    disk_path = files[idx].get("absolute_path")
    try:
        if disk_path:
            p = Path(disk_path)
            if root_dir in p.parents and p.exists():
                p.unlink()
    except Exception:
        pass

    # 移除 JSON 條目
    deleted_entry = files.pop(idx)
    item.attachments_json = json.dumps(files, ensure_ascii=False)
    db.commit()

    return {
        "success": True,
        "deleted": deleted_entry.get("stored_name") or deleted_entry.get("name"),
        "remaining": len(files),
    }


# 維持兼容：test_case_number 版（若前端尚未切換可用這個）
# 兼容舊路徑與新明確路徑（避免與整數 id 衝突）
@router.post("/by-number/{test_case_number}/attachments", response_model=dict)
@router.post("/{test_case_number}/attachments", response_model=dict)
async def upload_test_case_attachments(
    team_id: int,
    test_case_number: str,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_sync_db),
):
    """上傳測試案例附件（只寫本地檔案與 DB）
    規則：一律以 test_case_number 作為唯一識別鍵。
    - 儲存路徑：attachments/test-cases/{team_id}/{test_case_number}/
    - 更新 TestCaseLocal.attachments_json
    """
    import re
    import json
    from pathlib import Path
    from datetime import datetime

    # 嚴格以 test_case_number 定位
    item = (
        db.query(TestCaseLocalDB)
        .filter(
            TestCaseLocalDB.team_id == team_id,
            TestCaseLocalDB.test_case_number == test_case_number,
        )
        .first()
    )
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到測試案例 {test_case_number}（team={team_id}）",
        )

    # 固定以專案根做為 base，避免受啟動目錄影響
    project_root = Path(__file__).resolve().parents[2]
    from app.config import settings

    root_dir = (
        Path(settings.attachments.root_dir)
        if settings.attachments.root_dir
        else (project_root / "attachments")
    )
    base_dir = root_dir / "test-cases" / str(team_id) / item.test_case_number
    base_dir.mkdir(parents=True, exist_ok=True)

    # 既存附件
    existing = []
    if item.attachments_json:
        try:
            data = json.loads(item.attachments_json)
            if isinstance(data, list):
                existing = data
        except Exception:
            existing = []

    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f")
    safe_re = re.compile(r"[^A-Za-z0-9_.\-]+")
    uploaded = []

    for f in files:
        orig_name = f.filename or "unnamed"
        name_part = safe_re.sub("_", orig_name)
        stored_name = f"{ts}-{name_part}"
        stored_path = base_dir / stored_name
        content = await f.read()
        with open(stored_path, "wb") as out:
            out.write(content)
        meta = {
            "name": orig_name,
            "stored_name": stored_name,
            "size": len(content),
            "type": f.content_type or "application/octet-stream",
            "relative_path": str(stored_path.relative_to(root_dir)),
            "absolute_path": str(stored_path),
            "uploaded_at": datetime.utcnow().isoformat(),
        }
        existing.append(meta)
        uploaded.append(meta)

    item.attachments_json = json.dumps(existing, ensure_ascii=False)
    db.commit()

    return {
        "success": True,
        "uploaded": len(uploaded),
        "files": uploaded,
        "base_url": "/attachments",
    }


@router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_test_case(
    team_id: int,
    record_id: str,
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    """刪除測試案例（本地 DB）。
    支援 record_id 為本地整數 id、lark_record_id，或 test_case_number（備援）。
    同時清理附件檔案與 JSON 紀錄。
    """
    import json
    from pathlib import Path
    from app.auth.models import UserRole
    from app.auth.permission_service import permission_service

    if current_user.role != UserRole.SUPER_ADMIN:
        permission_check = await permission_service.check_team_permission(
            current_user.id, team_id, PermissionType.WRITE, current_user.role
        )
        if not permission_check.has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="無權限刪除此團隊的測試案例",
            )

    try:
        item = None
        # 1) 嘗試以本地整數 id
        try:
            rid_int = int(record_id)
            item = (
                db.query(TestCaseLocalDB).filter(TestCaseLocalDB.id == rid_int).first()
            )
            if item and item.team_id != team_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"測試案例 id={rid_int} 屬於 team={item.team_id}",
                )
        except ValueError:
            item = None
        # 2) lark_record_id
        if item is None:
            item = (
                db.query(TestCaseLocalDB)
                .filter(
                    TestCaseLocalDB.team_id == team_id,
                    TestCaseLocalDB.lark_record_id == record_id,
                )
                .first()
            )
        # 3) 備援：test_case_number
        if item is None:
            item = (
                db.query(TestCaseLocalDB)
                .filter(
                    TestCaseLocalDB.team_id == team_id,
                    TestCaseLocalDB.test_case_number == record_id,
                )
                .first()
            )
        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"找不到測試案例 {record_id}",
            )

        # 在刪除之前保存必要的資訊用於 audit log
        recorded_id = item.id
        recorded_number = item.test_case_number
        recorded_title = item.title

        # 先嘗試刪除附件檔案（非致命）
        try:
            project_root = Path(__file__).resolve().parents[2]
            from app.config import settings

            root_dir = (
                Path(settings.attachments.root_dir)
                if settings.attachments.root_dir
                else (project_root / "attachments")
            )
            if item.attachments_json:
                data = json.loads(item.attachments_json)
                if isinstance(data, list):
                    for f in data:
                        ap = f.get("absolute_path")
                        if ap:
                            p = Path(ap)
                            if root_dir in p.parents and p.exists():
                                p.unlink()
            # 刪除整個目錄（attachments/test-cases/{team_id}/{test_case_number}）
            base_dir = (
                root_dir / "test-cases" / str(team_id) / (item.test_case_number or "")
            )
            if base_dir.exists() and base_dir.is_dir():
                import shutil

                shutil.rmtree(base_dir, ignore_errors=True)
        except Exception:
            pass

        db.delete(item)
        db.commit()

        # 記錄刪除操作到 audit log
        action_brief = f"{current_user.username} deleted Test Case: {recorded_number or record_id}"
        if recorded_title:
            action_brief += f" ({recorded_title})"
        await log_test_case_action(
            action_type=ActionType.DELETE,
            current_user=current_user,
            team_id=team_id,
            resource_id=recorded_number or (str(recorded_id) if recorded_id is not None else record_id),
            action_brief=action_brief,
            details={
                "record_id": recorded_id,
                "test_case_number": recorded_number,
                "title": recorded_title,
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"刪除測試案例失敗: {str(e)}",
        )


# 依測試案例編號取得單筆（含附件）
@router.get("/by-number/{test_case_number}", response_model=TestCaseResponse)
async def get_test_case_by_number(
    team_id: int, test_case_number: str, db: Session = Depends(get_sync_db)
):
    try:
        item = (
            db.query(TestCaseLocalDB)
            .filter(
                TestCaseLocalDB.team_id == team_id,
                TestCaseLocalDB.test_case_number == test_case_number,
            )
            .first()
        )
        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"找不到測試案例 {test_case_number}",
            )
        # 構造附件
        import json

        attachments = []
        try:
            data = json.loads(item.attachments_json) if item.attachments_json else []
            base_url = "/attachments"
            for it in data if isinstance(data, list) else []:
                token = it.get("stored_name") or it.get("name") or ""
                name = it.get("name") or it.get("stored_name") or "file"
                size = int(it.get("size") or 0)
                mime = it.get("type") or "application/octet-stream"
                rel = it.get("relative_path") or ""
                url = f"{base_url}/{rel}" if rel else ""
                attachments.append(
                    {
                        "file_token": token,
                        "name": name,
                        "size": size,
                        "type": mime,
                        "url": url,
                        "tmp_url": url,
                    }
                )
        except Exception:
            attachments = []
        # 解析 TCG
        tcg_items = []
        try:
            if item.tcg_json:
                data = json.loads(item.tcg_json)
                if isinstance(data, list):
                    from app.models.lark_types import LarkRecord

                    for it in data:
                        try:
                            rec = LarkRecord(
                                record_ids=it.get("record_ids") or [],
                                table_id=it.get("table_id") or "",
                                text=it.get("text") or "",
                                text_arr=it.get("text_arr") or [],
                                type=it.get("type") or "text",
                            )
                            tcg_items.append(rec)
                        except Exception:
                            continue
        except Exception:
            tcg_items = []

        return TestCaseResponse(
            record_id=item.lark_record_id or str(item.id),
            test_case_number=item.test_case_number or "",
            title=item.title or "",
            priority=(
                item.priority.value
                if hasattr(item.priority, "value")
                else (item.priority or "")
            ),
            precondition=item.precondition or "",
            steps=item.steps or "",
            expected_result=item.expected_result or "",
            assignee=None,
            test_result=(
                item.test_result.value
                if hasattr(item.test_result, "value")
                else (item.test_result or None)
            ),
            attachments=attachments,
            test_results_files=[],
            user_story_map=[],
            tcg=tcg_items,
            parent_record=[],
            team_id=item.team_id,
            executed_at=None,
            created_at=item.created_at,
            updated_at=item.updated_at,
            last_sync_at=item.last_sync_at,
            raw_fields={},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 以下批次建立/複製等仍為對 Lark 的操作，若後續要完全改本地，請再確認規格。
@router.post("/bulk_create", response_model=BulkCreateResponse)
async def bulk_create_test_cases(
    team_id: int,
    request: BulkCreateRequest,
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    """批次建立測試案例（只寫本地 DB）"""
    try:
        if not request.items:
            return BulkCreateResponse(
                success=False, created_count=0, errors=["空的建立清單"]
            )

        # 取得現有記錄用於重複檢查（本地）
        existing_numbers = set(
            n[0]
            for n in db.query(TestCaseLocalDB.test_case_number)
            .filter(TestCaseLocalDB.team_id == team_id)
            .all()
        )
        duplicates = [
            item.test_case_number
            for item in request.items
            if item.test_case_number in existing_numbers
        ]
        if duplicates:
            return BulkCreateResponse(
                success=False, created_count=0, duplicates=duplicates
            )

        created_count = 0
        created_items = []  # 記錄建立的項目，用於 audit log
        priority_map = {"high": "High", "medium": "Medium", "low": "Low"}
        for it in request.items:
            title = (
                it.title.strip() if it.title else f"{it.test_case_number} 的測試案例"
            )
            priority_key = (it.priority or "Medium").strip().lower()
            priority_value = priority_map.get(priority_key, "Medium")
            item = TestCaseLocalDB(
                team_id=team_id,
                lark_record_id=None,
                test_case_number=it.test_case_number,
                title=title,
                priority=priority_value,
                precondition=it.precondition.strip() if it.precondition else None,
                steps=it.steps.strip() if it.steps else None,
                expected_result=(
                    it.expected_result.strip() if it.expected_result else None
                ),
                test_result=None,
                sync_status=SyncStatus.PENDING,
                local_version=1,
            )

            # 正規化並直接存儲 TCG 單號列表
            tcg_numbers = it.tcg_numbers or []
            normalized_tcg = [normalize_tcg_number(n) for n in tcg_numbers]
            normalized_tcg = [n for n in normalized_tcg if n]
            if normalized_tcg:
                item.tcg_json = json.dumps(normalized_tcg, ensure_ascii=False)

            db.add(item)
            created_count += 1
            created_items.append({
                "test_case_number": it.test_case_number,
                "title": title,
                "priority": priority_value,
            })
        db.commit()

        # 記錄批次建立 audit log
        if created_count > 0:
            test_case_numbers = [item["test_case_number"] for item in created_items]
            action_brief = f"{current_user.username} bulk created {created_count} Test Cases"
            if test_case_numbers[:3]:
                action_brief += f": {', '.join(test_case_numbers[:3])}"
                if len(test_case_numbers) > 3:
                    action_brief += f" and {len(test_case_numbers) - 3} more"

            await log_test_case_action(
                action_type=ActionType.CREATE,
                current_user=current_user,
                team_id=team_id,
                resource_id=f"bulk_{created_count}_items",
                action_brief=action_brief,
                details={
                    "operation": "bulk_create",
                    "created_count": created_count,
                    "created_items": created_items,
                },
            )

        return BulkCreateResponse(
            success=True, created_count=created_count, duplicates=[], errors=[]
        )
    except Exception as e:
        db.rollback()
        return BulkCreateResponse(success=False, created_count=0, errors=[str(e)])


# ===== 批次複製（Bulk Clone）API 定義 =====
class BulkCloneItem(BaseModel):
    source_record_id: str
    test_case_number: str
    title: Optional[str] = None


class BulkCloneRequest(BaseModel):
    items: List[BulkCloneItem]


class BulkCloneResponse(BaseModel):
    success: bool
    created_count: int = 0
    duplicates: List[str] = []
    errors: List[str] = []


@router.post("/bulk_clone", response_model=BulkCloneResponse)
async def bulk_clone_test_cases(
    team_id: int,
    request: BulkCloneRequest,
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    """批次複製測試案例（只寫本地 DB）
    - 從來源記錄（以 lark_record_id 尋找）複製 Precondition、Steps、Expected Result、Priority
    - 不複製：TCG、附件、測試結果檔案、User Story Map、Parent Record
    - 新的 Test Case Number 與 Title 由請求提供（Title 缺省時沿用來源）
    """
    try:
        if not request.items:
            return BulkCloneResponse(
                success=False, created_count=0, errors=["空的建立清單"]
            )

        # 本地重複檢查
        existing_numbers = set(
            n[0]
            for n in db.query(TestCaseLocalDB.test_case_number)
            .filter(TestCaseLocalDB.team_id == team_id)
            .all()
        )
        req_numbers = [it.test_case_number for it in request.items]
        duplicates = [num for num in req_numbers if num in existing_numbers]
        if duplicates:
            return BulkCloneResponse(
                success=False, created_count=0, duplicates=duplicates, errors=[]
            )

        # 快速索引來源（本地以 lark_record_id 尋找）
        source_ids = [it.source_record_id for it in request.items]
        src_rows = (
            db.query(TestCaseLocalDB)
            .filter(
                TestCaseLocalDB.team_id == team_id,
                TestCaseLocalDB.lark_record_id.in_(source_ids),
            )
            .all()
        )
        src_map = {r.lark_record_id: r for r in src_rows if r.lark_record_id}

        created = 0
        errors: List[str] = []
        created_items = []  # 記錄複製的項目，用於 audit log

        for it in request.items:
            src = src_map.get(it.source_record_id)
            if not src:
                errors.append(f"來源記錄不存在: {it.source_record_id}")
                continue

            try:
                new_title = (
                    it.title.strip()
                    if (it.title is not None and it.title.strip())
                    else src.title
                )
                item = TestCaseLocalDB(
                    team_id=team_id,
                    lark_record_id=None,
                    test_case_number=it.test_case_number,
                    title=new_title,
                    priority=src.priority,
                    precondition=src.precondition,
                    steps=src.steps,
                    expected_result=src.expected_result,
                    test_result=None,
                    sync_status=SyncStatus.PENDING,
                    local_version=1,
                )
                db.add(item)
                created += 1
                created_items.append({
                    "test_case_number": it.test_case_number,
                    "title": new_title,
                    "source_record_id": it.source_record_id,
                    "source_test_case_number": src.test_case_number,
                })
            except Exception as e:
                errors.append(f"來源 {it.source_record_id} 複製失敗: {str(e)}")

        if created == 0 and errors:
            db.rollback()
            return BulkCloneResponse(
                success=False, created_count=0, duplicates=[], errors=errors
            )

        db.commit()

        # 記錄批次複製 audit log
        if created > 0:
            test_case_numbers = [item["test_case_number"] for item in created_items]
            action_brief = f"{current_user.username} bulk cloned {created} Test Cases"
            if test_case_numbers[:3]:
                action_brief += f": {', '.join(test_case_numbers[:3])}"
                if len(test_case_numbers) > 3:
                    action_brief += f" and {len(test_case_numbers) - 3} more"

            await log_test_case_action(
                action_type=ActionType.CREATE,
                current_user=current_user,
                team_id=team_id,
                resource_id=f"bulk_clone_{created}_items",
                action_brief=action_brief,
                details={
                    "operation": "bulk_clone",
                    "created_count": created,
                    "cloned_items": created_items,
                },
            )

        return BulkCloneResponse(
            success=True, created_count=created, duplicates=[], errors=errors
        )
    except Exception as e:
        db.rollback()
        return BulkCloneResponse(
            success=False, created_count=0, duplicates=[], errors=[str(e)]
        )


@router.post("/batch", response_model=TestCaseBatchResponse)
async def batch_operation_test_cases(
    team_id: int,
    operation: TestCaseBatchOperation,
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    """批次操作本地測試案例（不呼叫 Lark）。
    支援：delete、update_priority、update_tcg、update_section、update_test_set。
    record_ids 可為本地整數 id、lark_record_id 或 test_case_number。
    """
    import json
    from pathlib import Path

    if not operation.record_ids:
        raise HTTPException(status_code=400, detail="記錄 ID 列表不能為空")

    def resolve_one(rid: str) -> Optional[TestCaseLocalDB]:
        # 1) 本地整數 id
        try:
            rid_int = int(rid)
            item = (
                db.query(TestCaseLocalDB).filter(TestCaseLocalDB.id == rid_int).first()
            )
            if item and item.team_id == team_id:
                return item
        except ValueError:
            pass
        # 2) lark_record_id
        item = (
            db.query(TestCaseLocalDB)
            .filter(
                TestCaseLocalDB.team_id == team_id,
                TestCaseLocalDB.lark_record_id == rid,
            )
            .first()
        )
        if item:
            return item
        # 3) test_case_number
        item = (
            db.query(TestCaseLocalDB)
            .filter(
                TestCaseLocalDB.team_id == team_id,
                TestCaseLocalDB.test_case_number == rid,
            )
            .first()
        )
        return item

    processed = 0
    success_count = 0
    errors: list[str] = []
    success_items = []  # 記錄成功操作的項目，用於 audit log

    try:
        if operation.operation == "delete":
            for rid in operation.record_ids:
                processed += 1
                item = resolve_one(rid)
                if not item:
                    errors.append(f"找不到測試案例 {rid}")
                    continue
                # 記錄刪除的項目資訊（在刪除前）
                item_info = {
                    "id": item.id,
                    "test_case_number": item.test_case_number,
                    "title": item.title,
                }
                # 刪檔（非致命）
                try:
                    if item.attachments_json:
                        data = json.loads(item.attachments_json)
                        if isinstance(data, list):
                            project_root = Path(__file__).resolve().parents[2]
                            for f in data:
                                ap = f.get("absolute_path")
                                if ap:
                                    p = Path(ap)
                                    if (
                                        project_root / "attachments"
                                    ) in p.parents and p.exists():
                                        p.unlink()
                    # 刪除目錄
                    project_root = Path(__file__).resolve().parents[2]
                    base_dir = (
                        project_root
                        / "attachments"
                        / "test-cases"
                        / str(team_id)
                        / (item.test_case_number or "")
                    )
                    if base_dir.exists():
                        import shutil

                        shutil.rmtree(base_dir, ignore_errors=True)
                except Exception:
                    pass
                db.delete(item)
                success_count += 1
                success_items.append(item_info)
            db.commit()

            # 記錄批次刪除 audit log
            if success_count > 0:
                test_case_numbers = [item["test_case_number"] for item in success_items if item.get("test_case_number")]
                action_brief = f"{current_user.username} batch deleted {success_count} Test Cases"
                if test_case_numbers[:3]:  # 顯示前3個
                    action_brief += f": {', '.join(test_case_numbers[:3])}"
                    if len(test_case_numbers) > 3:
                        action_brief += f" and {len(test_case_numbers) - 3} more"

                await log_test_case_action(
                    action_type=ActionType.DELETE,
                    current_user=current_user,
                    team_id=team_id,
                    resource_id=f"batch_{success_count}_items",
                    action_brief=action_brief,
                    details={
                        "operation": "batch_delete",
                        "success_count": success_count,
                        "total_count": len(operation.record_ids),
                        "deleted_items": success_items,
                    },
                )

        elif operation.operation == "update_priority":
            pr = (
                (operation.update_data or {}).get("priority")
                if operation.update_data
                else None
            )
            if not pr:
                raise HTTPException(
                    status_code=400, detail="批次更新優先級需要提供 priority"
                )
            for rid in operation.record_ids:
                processed += 1
                item = resolve_one(rid)
                if not item:
                    errors.append(f"找不到測試案例 {rid}")
                    continue
                try:
                    old_priority = item.priority
                    item.priority = pr
                    item.updated_at = datetime.utcnow()
                    item.sync_status = SyncStatus.PENDING
                    success_count += 1
                    success_items.append({
                        "id": item.id,
                        "test_case_number": item.test_case_number,
                        "title": item.title,
                        "old_priority": old_priority,
                        "new_priority": pr,
                    })
                except Exception as e:
                    errors.append(f"{rid}: {e}")
            db.commit()

            # 記錄批次更新優先級 audit log
            if success_count > 0:
                test_case_numbers = [item["test_case_number"] for item in success_items if item.get("test_case_number")]
                action_brief = f"{current_user.username} batch updated priority to {pr} for {success_count} Test Cases"
                if test_case_numbers[:3]:
                    action_brief += f": {', '.join(test_case_numbers[:3])}"
                    if len(test_case_numbers) > 3:
                        action_brief += f" and {len(test_case_numbers) - 3} more"

                await log_test_case_action(
                    action_type=ActionType.UPDATE,
                    current_user=current_user,
                    team_id=team_id,
                    resource_id=f"batch_{success_count}_items",
                    action_brief=action_brief,
                    details={
                        "operation": "batch_update_priority",
                        "new_priority": pr,
                        "success_count": success_count,
                        "total_count": len(operation.record_ids),
                        "updated_items": success_items,
                    },
                )

        elif operation.operation == "update_tcg":
            # 批次更新 TCG：簡化版本直接存儲單號列表
            payload = operation.update_data or {}
            tcg_value = payload.get("tcg")  # 支援字串（單號或以逗號分隔）、或字串陣列

            # 解析 TCG 單號
            def normalize_tcgs():
                nums: list[str] = []
                if isinstance(tcg_value, str):
                    s = tcg_value.strip()
                    if not s:
                        return []  # 清空
                    # 允許用逗號/空白/換行分隔
                    parts = [
                        p.strip()
                        for p in s.replace("\n", ",").replace(" ", ",").split(",")
                    ]
                    nums = [p for p in parts if p]
                elif isinstance(tcg_value, list):
                    nums = [str(x).strip() for x in tcg_value if str(x).strip()]
                else:
                    return []  # 清空或未提供
                
                # 正規化單號
                normalized = [normalize_tcg_number(n) for n in nums]
                return [n for n in normalized if n]

            # 直接使用正規化的 TCG 單號列表
            tcg_numbers_list = normalize_tcgs()
            
            for rid in operation.record_ids:
                processed += 1
                item = resolve_one(rid)
                if not item:
                    errors.append(f"找不到測試案例 {rid}")
                    continue
                # 寫入 tcg_json
                try:
                    new_tcg_json = json.dumps(tcg_numbers_list, ensure_ascii=False)
                    item.tcg_json = new_tcg_json
                    item.updated_at = datetime.utcnow()
                    item.sync_status = SyncStatus.PENDING
                    success_count += 1
                    # 記錄更新的項目
                    success_items.append({
                        "id": item.id,
                        "test_case_number": item.test_case_number,
                        "title": item.title,
                        "tcg_numbers": tcg_numbers_list,
                    })
                except Exception as e:
                    errors.append(f"{rid}: {e}")
            db.commit()

            # 記錄批次更新 TCG audit log
            if success_count > 0:
                test_case_numbers = [item["test_case_number"] for item in success_items if item.get("test_case_number")]
                tcg_display = ", ".join([pair[1] for pair in rid_pairs if pair[1]][:3])
                action_brief = f"{current_user.username} batch updated TCG for {success_count} Test Cases"
                if tcg_display:
                    action_brief += f" to TCG: {tcg_display}"
                if len(rid_pairs) > 3:
                    action_brief += f" and {len(rid_pairs) - 3} more"

                await log_test_case_action(
                    action_type=ActionType.UPDATE,
                    current_user=current_user,
                    team_id=team_id,
                    resource_id=f"batch_{success_count}_items",
                    action_brief=action_brief,
                    details={
                        "operation": "batch_update_tcg",
                        "tcg_pairs": rid_pairs,
                        "success_count": success_count,
                        "total_count": len(operation.record_ids),
                        "updated_items": success_items,
                    },
                )
        elif operation.operation == "update_section":
            payload = operation.update_data or {}
            section_id_value = payload.get("section_id")
            if section_id_value is None:
                raise HTTPException(status_code=400, detail="批次更新區段需要提供 section_id")
            try:
                target_section_id = int(section_id_value)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="無效的 section_id")

            target_section = (
                db.query(TestCaseSectionDB)
                .filter(TestCaseSectionDB.id == target_section_id)
                .first()
            )
            if not target_section:
                raise HTTPException(status_code=404, detail="指定的區段不存在")

            for rid in operation.record_ids:
                processed += 1
                item = resolve_one(rid)
                if not item:
                    errors.append(f"找不到測試案例 {rid}")
                    continue
                if item.test_case_set_id != target_section.test_case_set_id:
                    errors.append(f"{rid}: 區段不屬於相同的 Test Case Set")
                    continue
                try:
                    old_section_id = item.test_case_section_id
                    item.test_case_section_id = target_section.id
                    item.updated_at = datetime.utcnow()
                    item.sync_status = SyncStatus.PENDING
                    success_count += 1
                    success_items.append({
                        "id": item.id,
                        "test_case_number": item.test_case_number,
                        "title": item.title,
                        "old_section_id": old_section_id,
                        "new_section_id": target_section.id,
                    })
                except Exception as e:
                    errors.append(f"{rid}: {e}")
            db.commit()

            if success_count > 0:
                test_case_numbers = [item["test_case_number"] for item in success_items if item.get("test_case_number")]
                action_brief = f"{current_user.username} batch reassigned {success_count} Test Cases to section {target_section.name}"
                if test_case_numbers[:3]:
                    action_brief += f": {', '.join(test_case_numbers[:3])}"
                    if len(test_case_numbers) > 3:
                        action_brief += f" and {len(test_case_numbers) - 3} more"

                await log_test_case_action(
                    action_type=ActionType.UPDATE,
                    current_user=current_user,
                    team_id=team_id,
                    resource_id=f"batch_{success_count}_items",
                    action_brief=action_brief,
                    details={
                        "operation": "batch_update_section",
                        "target_section_id": target_section.id,
                        "target_section_name": target_section.name,
                        "success_count": success_count,
                        "total_count": len(operation.record_ids),
                        "updated_items": success_items,
                    },
                )
        elif operation.operation == "update_test_set":
            # 批次更新 Test Set：將 test cases 移動到新的 Test Set，並將其放在 Unassigned 區段
            payload = operation.update_data or {}
            test_set_id_value = payload.get("test_set_id")
            if test_set_id_value is None:
                raise HTTPException(status_code=400, detail="批次更新 Test Set 需要提供 test_set_id")
            try:
                target_test_set_id = int(test_set_id_value)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="無效的 test_set_id")

            # 驗證目標 Test Set 存在
            from app.models.database_models import TestCaseSet as TestCaseSetDB
            target_test_set = (
                db.query(TestCaseSetDB)
                .filter(TestCaseSetDB.id == target_test_set_id, TestCaseSetDB.team_id == team_id)
                .first()
            )
            if not target_test_set:
                raise HTTPException(status_code=404, detail="指定的 Test Set 不存在")

            # 找到目標 Test Set 的 Unassigned 區段
            unassigned_section = (
                db.query(TestCaseSectionDB)
                .filter(
                    TestCaseSectionDB.test_case_set_id == target_test_set_id,
                    TestCaseSectionDB.name == "Unassigned",
                )
                .first()
            )
            if not unassigned_section:
                raise HTTPException(status_code=404, detail="目標 Test Set 沒有 Unassigned 區段")

            for rid in operation.record_ids:
                processed += 1
                item = resolve_one(rid)
                if not item:
                    errors.append(f"找不到測試案例 {rid}")
                    continue
                try:
                    old_set_id = item.test_case_set_id
                    old_section_id = item.test_case_section_id

                    # 更新為目標 Test Set 和 Unassigned 區段
                    item.test_case_set_id = target_test_set_id
                    item.test_case_section_id = unassigned_section.id
                    item.updated_at = datetime.utcnow()
                    item.sync_status = SyncStatus.PENDING
                    success_count += 1
                    success_items.append({
                        "id": item.id,
                        "test_case_number": item.test_case_number,
                        "title": item.title,
                        "old_set_id": old_set_id,
                        "new_set_id": target_test_set_id,
                        "old_section_id": old_section_id,
                        "new_section_id": unassigned_section.id,
                    })
                except Exception as e:
                    errors.append(f"{rid}: {e}")
            db.commit()

            if success_count > 0:
                test_case_numbers = [item["test_case_number"] for item in success_items if item.get("test_case_number")]
                action_brief = f"{current_user.username} batch moved {success_count} Test Cases to set {target_test_set.name} (Unassigned)"
                if test_case_numbers[:3]:
                    action_brief += f": {', '.join(test_case_numbers[:3])}"
                    if len(test_case_numbers) > 3:
                        action_brief += f" and {len(test_case_numbers) - 3} more"

                await log_test_case_action(
                    action_type=ActionType.UPDATE,
                    current_user=current_user,
                    team_id=team_id,
                    resource_id=f"batch_{success_count}_items",
                    action_brief=action_brief,
                    details={
                        "operation": "batch_update_test_set",
                        "target_test_set_id": target_test_set_id,
                        "target_test_set_name": target_test_set.name,
                        "target_section_id": unassigned_section.id,
                        "target_section_name": unassigned_section.name,
                        "success_count": success_count,
                        "total_count": len(operation.record_ids),
                        "updated_items": success_items,
                    },
                )
        else:
            raise HTTPException(
                status_code=400, detail=f"不支援的批次操作: {operation.operation}"
            )

        return TestCaseBatchResponse(
            success=len(errors) == 0,
            processed_count=processed,
            success_count=success_count,
            error_count=len(errors),
            error_messages=errors,
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        return TestCaseBatchResponse(
            success=False,
            processed_count=processed,
            success_count=success_count,
            error_count=len(errors) + 1,
            error_messages=errors + [str(e)],
        )


        raise HTTPException(status_code=500, detail="获取测试案例失败")
