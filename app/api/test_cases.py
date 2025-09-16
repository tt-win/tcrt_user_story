"""
測試案例 API 路由（重構：改用本地資料庫作為單一真實來源）

- 列表/計數：改為從本地 test_cases 讀取
- 單筆查詢：改為從本地 test_cases 讀取
- 新增同步端點：觸發 init/diff/full-update
- 建立/更新/刪除（若後續需要）：先寫本地、標記 pending，再由同步流程推送到 Lark
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Response
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from app.database import get_db
from app.models.test_case import (
    TestCase, TestCaseCreate, TestCaseUpdate, TestCaseResponse,
    TestCaseBatchOperation, TestCaseBatchResponse
)
from app.models.database_models import Team as TeamDB, TestCaseLocal as TestCaseLocalDB, SyncStatus
from app.services.test_case_repo_service import TestCaseRepoService

router = APIRouter(prefix="/teams/{team_id}/testcases", tags=["test-cases"])


class BulkTestCaseItem(BaseModel):
    test_case_number: str
    title: Optional[str] = None
    priority: Optional[str] = "Medium"


class BulkCreateRequest(BaseModel):
    items: List[BulkTestCaseItem]


class BulkCreateResponse(BaseModel):
    success: bool
    created_count: int = 0
    duplicates: List[str] = []
    errors: List[str] = []



@router.get("/", response_model=List[TestCaseResponse])
async def get_test_cases(
    team_id: int,
    response: Response,
    db: Session = Depends(get_db),
    # 搜尋參數
    search: Optional[str] = Query(None, description="標題模糊搜尋"),
    tcg_filter: Optional[str] = Query(None, description="TCG 單號過濾"),
    priority_filter: Optional[str] = Query(None, description="優先級過濾"),
    test_result_filter: Optional[str] = Query(None, description="測試結果過濾"),
    assignee_filter: Optional[str] = Query(None, description="指派人過濾"),
    # 排序參數
    sort_by: Optional[str] = Query("created_at", description="排序欄位"),
    sort_order: Optional[str] = Query("desc", description="排序順序 (asc/desc)"),
    # 分頁參數
    skip: int = Query(0, ge=0, description="跳過筆數"),
    limit: int = Query(1000, ge=1, le=100000, description="回傳筆數"),
    with_meta: bool = Query(False, description="是否回傳分頁中繼資料"),
    load_all: bool = Query(False, description="忽略分頁，一次載入全部資料並回傳")
):
    """取得測試案例列表，支援搜尋、過濾和排序（改為本地 DB）
    - 回應標頭包含:
      - X-Total-Count: 總筆數
      - X-Has-Next: 是否尚有下一頁（true/false）
    - 若 with_meta=true，回傳 { items, page: { skip, limit, total, hasNext } }
    """
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
            sort_by=sort_by or 'created_at',
            sort_order=sort_order or 'desc',
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
                    "hasNext": has_next
                }
            }
        return items
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"取得測試案例失敗: {str(e)}"
        )


@router.get("/count", response_model=dict)
async def get_test_cases_count(
    team_id: int,
    db: Session = Depends(get_db),
    # 搜尋參數（與 get_test_cases 相同）
    search: Optional[str] = Query(None, description="標題模糊搜尋"),
    tcg_filter: Optional[str] = Query(None, description="TCG 單號過濾"),
    priority_filter: Optional[str] = Query(None, description="優先級過濾"),
    test_result_filter: Optional[str] = Query(None, description="測試結果過濾"),
    assignee_filter: Optional[str] = Query(None, description="指派人過濾")
):
    """取得符合條件的測試案例數量（改為本地 DB）"""
    try:
        service = TestCaseRepoService(db)
        total = service.count(
            team_id=team_id,
            search=search,
            tcg_filter=tcg_filter,
            priority_filter=priority_filter,
            test_result_filter=test_result_filter,
            assignee_filter=assignee_filter,
        )
        return {"total": total}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"取得測試案例數量失敗: {str(e)}"
        )


@router.get("/{record_id}", response_model=TestCaseResponse)
async def get_test_case(
    team_id: int,
    record_id: str,
    db: Session = Depends(get_db)
):
    """取得特定測試案例（改為本地 DB）。預設會載入附件清單。
    支援：record_id 為 lark_record_id 或本地數字 id
    """
    try:
        service = TestCaseRepoService(db)
        result = service.get_by_lark_record_id(team_id, record_id, include_attachments=True)
        if not result:
            # 嘗試以本地數字 id 讀取（相容本地新建而無 lark_record_id 的情況）
            item = None
            try:
                local_id = int(record_id)
                item = db.query(TestCaseLocalDB).filter(
                    TestCaseLocalDB.team_id == team_id,
                    TestCaseLocalDB.id == local_id
                ).first()
            except Exception:
                item = None
            if not item:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"找不到測試案例 {record_id}")
            # 轉換本地資料為回應
            # 轉入附件
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
                    attachments.append({
                        "file_token": token,
                        "name": name,
                        "size": size,
                        "type": mime,
                        "url": url,
                        "tmp_url": url,
                    })
            except Exception:
                attachments = []

            return TestCaseResponse(
                record_id=item.lark_record_id or str(item.id),
                test_case_number=item.test_case_number or '',
                title=item.title or '',
                priority=item.priority.value if hasattr(item.priority, 'value') else (item.priority or ''),
                precondition=item.precondition or '',
                steps=item.steps or '',
                expected_result=item.expected_result or '',
                assignee=None,
                test_result=item.test_result.value if hasattr(item.test_result, 'value') else (item.test_result or None),
                attachments=attachments,
                test_results_files=[],
                user_story_map=[],
                tcg=[],
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
            detail=f"取得測試案例失敗: {str(e)}"
        )


@router.post("/", response_model=TestCaseResponse, status_code=status.HTTP_201_CREATED)
async def create_test_case(
    team_id: int,
    case: TestCaseCreate,
    db: Session = Depends(get_db)
):
    """建立新的測試案例（只寫本地 DB）"""
    try:
        # 檢查重複 test_case_number
        exists = db.query(TestCaseLocalDB).filter(
            TestCaseLocalDB.team_id == team_id,
            TestCaseLocalDB.test_case_number == case.test_case_number
        ).first()
        if exists:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="測試案例編號已存在")

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
        db.commit()
        # 回傳本地物件
        return TestCaseResponse(
            record_id=str(item.id),
            test_case_number=item.test_case_number,
            title=item.title,
            priority=item.priority.value if hasattr(item.priority, 'value') else (item.priority or ''),
            precondition=item.precondition,
            steps=item.steps,
            expected_result=item.expected_result,
            assignee_name=None,
            test_result=item.test_result.value if hasattr(item.test_result, 'value') else (item.test_result or None),
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
            detail=f"建立測試案例失敗: {str(e)}"
        )


@router.put("/{record_id}", response_model=TestCaseResponse)
async def update_test_case(
    team_id: int,
    record_id: str,
    case_update: TestCaseUpdate,
    db: Session = Depends(get_db)
):
    """更新測試案例（只寫本地 DB）。
    規則：優先以本地 id（純數字）尋找；否則以 lark_record_id 尋找。
    """
    try:
        item = None
        # 優先：本地數字 id
        try:
            rid_int = int(record_id)
            item = db.query(TestCaseLocalDB).filter(TestCaseLocalDB.id == rid_int).first()
            if item and item.team_id != team_id:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"測試案例 id={rid_int} 屬於 team={item.team_id}")
        except ValueError:
            item = None
        # 次選：lark_record_id
        if item is None:
            item = db.query(TestCaseLocalDB).filter(
                TestCaseLocalDB.team_id == team_id,
                TestCaseLocalDB.lark_record_id == record_id
            ).first()
        if not item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"找不到測試案例 {record_id}")

        if case_update.test_case_number is not None:
            item.test_case_number = case_update.test_case_number
        if case_update.title is not None:
            item.title = case_update.title
        if case_update.priority is not None:
            item.priority = case_update.priority
        if case_update.precondition is not None:
            item.precondition = case_update.precondition
        if case_update.steps is not None:
            item.steps = case_update.steps
        if case_update.expected_result is not None:
            item.expected_result = case_update.expected_result
        if case_update.test_result is not None:
            item.test_result = case_update.test_result
        # 變更後標為待同步
        item.sync_status = SyncStatus.PENDING
        db.commit()

        return TestCaseResponse(
            record_id=str(item.id),
            test_case_number=item.test_case_number or '',
            title=item.title or '',
            priority=item.priority.value if hasattr(item.priority, 'value') else (item.priority or ''),
            precondition=item.precondition or '',
            steps=item.steps or '',
            expected_result=item.expected_result or '',
            assignee_name=None,
            test_result=item.test_result.value if hasattr(item.test_result, 'value') else (item.test_result or None),
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
            detail=f"更新測試案例失敗: {str(e)}"
        )


# 規則：首選 DB 本地 id 版本（更精準更快）
@router.post("/{test_case_id:int}/attachments", response_model=dict)
async def upload_test_case_attachments_by_id(
    team_id: int,
    test_case_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db)
):
    """上傳測試案例附件（本地 id 版）"""
    import re, json
    from pathlib import Path
    from datetime import datetime

# 先以本地 id 查找（不帶 team 條件，避免 team_id 傳錯時無法診斷）
    item = db.query(TestCaseLocalDB).filter(
        TestCaseLocalDB.id == test_case_id
    ).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"找不到測試案例 id={test_case_id}")
    # 確認 team 一致，不一致回報 409 並提示正確 team_id
    if item.team_id != team_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"測試案例 id={test_case_id} 屬於 team={item.team_id}，請改用該 team_id 或確認路徑參數。")

    # 固定專案根
    project_root = Path(__file__).resolve().parents[2]
    base_dir = project_root / "attachments" / "test-cases" / str(team_id) / item.test_case_number
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
            "relative_path": str(stored_path.relative_to(project_root / "attachments")),
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
    team_id: int,
    test_case_id: int,
    db: Session = Depends(get_db)
):
    """列出某測試案例的附件（以本地 id）。"""
    import json
    from pathlib import Path

    item = db.query(TestCaseLocalDB).filter(TestCaseLocalDB.id == test_case_id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"找不到測試案例 id={test_case_id}")
    if item.team_id != team_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"測試案例 id={test_case_id} 屬於 team={item.team_id}")

    files = []
    if item.attachments_json:
        try:
            files = json.loads(item.attachments_json) or []
        except Exception:
            files = []
    return {"success": True, "files": files, "count": len(files), "base_url": "/attachments"}

@router.delete("/{test_case_id:int}/attachments/{target}", response_model=dict)
async def delete_test_case_attachment(
    team_id: int,
    test_case_id: int,
    target: str,
    db: Session = Depends(get_db)
):
    """刪除單一附件（以本地整數 id）。"""
    return await _delete_attachment_common(team_id, target, db, id_value=test_case_id)


@router.delete("/{record_key}/attachments/{target}", response_model=dict)
async def delete_test_case_attachment_by_key(
    team_id: int,
    record_key: str,
    target: str,
    db: Session = Depends(get_db)
):
    """刪除單一附件（接受 lark_record_id 或本地整數 id）。"""
    # 嘗試轉成 int，否則視為 lark_record_id
    id_value = None
    lark_id = None
    try:
        id_value = int(record_key)
    except Exception:
        lark_id = record_key
    return await _delete_attachment_common(team_id, target, db, id_value=id_value, lark_record_id=lark_id)


@router.delete("/by-number/{test_case_number}/attachments/{target}", response_model=dict)
async def delete_test_case_attachment_by_number(
    team_id: int,
    test_case_number: str,
    target: str,
    db: Session = Depends(get_db)
):
    """刪除單一附件（以測試案例編號）。"""
    return await _delete_attachment_common(team_id, target, db, test_case_number=test_case_number)


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
        item = q.filter(TestCaseLocalDB.team_id == team_id, TestCaseLocalDB.lark_record_id == lark_record_id).first()
    elif test_case_number is not None:
        item = q.filter(TestCaseLocalDB.team_id == team_id, TestCaseLocalDB.test_case_number == test_case_number).first()
    else:
        item = None

    if not item:
        key = id_value if id_value is not None else (lark_record_id or test_case_number or "")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"找不到測試案例 {key}")
    if item.team_id != team_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"測試案例 id={item.id} 屬於 team={item.team_id}")

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
        if matches(f.get('stored_name') or '') or matches(f.get('name') or ''):
            idx = i
            break

    if idx is None:
        key = id_value if id_value is not None else (lark_record_id or test_case_number or "")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"找不到附件 {target}（case={key}）")

    # 刪除檔案
    project_root = Path(__file__).resolve().parents[2]
    disk_path = files[idx].get('absolute_path')
    try:
        if disk_path:
            p = Path(disk_path)
            if (project_root / "attachments") in p.parents and p.exists():
                p.unlink()
    except Exception:
        pass

    # 移除 JSON 條目
    deleted_entry = files.pop(idx)
    item.attachments_json = json.dumps(files, ensure_ascii=False)
    db.commit()

    return {"success": True, "deleted": deleted_entry.get('stored_name') or deleted_entry.get('name'), "remaining": len(files)}

# 維持兼容：test_case_number 版（若前端尚未切換可用這個）
# 兼容舊路徑與新明確路徑（避免與整數 id 衝突）
@router.post("/by-number/{test_case_number}/attachments", response_model=dict)
@router.post("/{test_case_number}/attachments", response_model=dict)
async def upload_test_case_attachments(
    team_id: int,
    test_case_number: str,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db)
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
    item = db.query(TestCaseLocalDB).filter(
        TestCaseLocalDB.team_id == team_id,
        TestCaseLocalDB.test_case_number == test_case_number
    ).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"找不到測試案例 {test_case_number}（team={team_id}）")

# 固定以專案根做為 base，避免受啟動目錄影響
    project_root = Path(__file__).resolve().parents[2]
    base_dir = project_root / "attachments" / "test-cases" / str(team_id) / item.test_case_number
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
"relative_path": str(stored_path.relative_to(project_root / "attachments")),
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
    db: Session = Depends(get_db)
):
    """刪除測試案例（本地 DB）。
    支援 record_id 為本地整數 id、lark_record_id，或 test_case_number（備援）。
    同時清理附件檔案與 JSON 紀錄。
    """
    import json
    from pathlib import Path
    try:
        item = None
        # 1) 嘗試以本地整數 id
        try:
            rid_int = int(record_id)
            item = db.query(TestCaseLocalDB).filter(TestCaseLocalDB.id == rid_int).first()
            if item and item.team_id != team_id:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"測試案例 id={rid_int} 屬於 team={item.team_id}")
        except ValueError:
            item = None
        # 2) lark_record_id
        if item is None:
            item = db.query(TestCaseLocalDB).filter(
                TestCaseLocalDB.team_id == team_id,
                TestCaseLocalDB.lark_record_id == record_id
            ).first()
        # 3) 備援：test_case_number
        if item is None:
            item = db.query(TestCaseLocalDB).filter(
                TestCaseLocalDB.team_id == team_id,
                TestCaseLocalDB.test_case_number == record_id
            ).first()
        if not item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"找不到測試案例 {record_id}")

        # 先嘗試刪除附件檔案（非致命）
        try:
            project_root = Path(__file__).resolve().parents[2]
            if item.attachments_json:
                data = json.loads(item.attachments_json)
                if isinstance(data, list):
                    for f in data:
                        ap = f.get('absolute_path')
                        if ap:
                            p = Path(ap)
                            if (project_root / 'attachments') in p.parents and p.exists():
                                p.unlink()
            # 刪除整個目錄（attachments/test-cases/{team_id}/{test_case_number}）
            base_dir = project_root / 'attachments' / 'test-cases' / str(team_id) / (item.test_case_number or '')
            if base_dir.exists() and base_dir.is_dir():
                import shutil
                shutil.rmtree(base_dir, ignore_errors=True)
        except Exception:
            pass

        db.delete(item)
        db.commit()
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"刪除測試案例失敗: {str(e)}"
        )


# 依測試案例編號取得單筆（含附件）
@router.get("/by-number/{test_case_number}", response_model=TestCaseResponse)
async def get_test_case_by_number(
    team_id: int,
    test_case_number: str,
    db: Session = Depends(get_db)
):
    try:
        item = db.query(TestCaseLocalDB).filter(
            TestCaseLocalDB.team_id == team_id,
            TestCaseLocalDB.test_case_number == test_case_number
        ).first()
        if not item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"找不到測試案例 {test_case_number}")
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
                attachments.append({
                    "file_token": token,
                    "name": name,
                    "size": size,
                    "type": mime,
                    "url": url,
                    "tmp_url": url,
                })
        except Exception:
            attachments = []
        return TestCaseResponse(
            record_id=item.lark_record_id or str(item.id),
            test_case_number=item.test_case_number or '',
            title=item.title or '',
            priority=item.priority.value if hasattr(item.priority, 'value') else (item.priority or ''),
            precondition=item.precondition or '',
            steps=item.steps or '',
            expected_result=item.expected_result or '',
            assignee=None,
            test_result=item.test_result.value if hasattr(item.test_result, 'value') else (item.test_result or None),
            attachments=attachments,
            test_results_files=[],
            user_story_map=[],
            tcg=[],
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
    db: Session = Depends(get_db)
):
    """批次建立測試案例（只寫本地 DB）"""
    try:
        if not request.items:
            return BulkCreateResponse(success=False, created_count=0, errors=["空的建立清單"])

        # 取得現有記錄用於重複檢查（本地）
        existing_numbers = set(
            n[0] for n in db.query(TestCaseLocalDB.test_case_number).filter(TestCaseLocalDB.team_id == team_id).all()
        )
        duplicates = [item.test_case_number for item in request.items if item.test_case_number in existing_numbers]
        if duplicates:
            return BulkCreateResponse(success=False, created_count=0, duplicates=duplicates)

        created_count = 0
        for it in request.items:
            title = it.title.strip() if it.title else f"{it.test_case_number} 的測試案例"
            item = TestCaseLocalDB(
                team_id=team_id,
                lark_record_id=None,
                test_case_number=it.test_case_number,
                title=title,
                priority=it.priority or 'Medium',
                precondition=None,
                steps=None,
                expected_result=None,
                test_result=None,
                sync_status=SyncStatus.PENDING,
                local_version=1,
            )
            db.add(item)
            created_count += 1
        db.commit()
        return BulkCreateResponse(success=True, created_count=created_count, duplicates=[], errors=[])
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
    db: Session = Depends(get_db)
):
    """批次複製測試案例（只寫本地 DB）
    - 從來源記錄（以 lark_record_id 尋找）複製 Precondition、Steps、Expected Result、Priority
    - 不複製：TCG、附件、測試結果檔案、User Story Map、Parent Record
    - 新的 Test Case Number 與 Title 由請求提供（Title 缺省時沿用來源）
    """
    try:
        if not request.items:
            return BulkCloneResponse(success=False, created_count=0, errors=["空的建立清單"])

        # 本地重複檢查
        existing_numbers = set(
            n[0] for n in db.query(TestCaseLocalDB.test_case_number).filter(TestCaseLocalDB.team_id == team_id).all()
        )
        req_numbers = [it.test_case_number for it in request.items]
        duplicates = [num for num in req_numbers if num in existing_numbers]
        if duplicates:
            return BulkCloneResponse(success=False, created_count=0, duplicates=duplicates, errors=[])

        # 快速索引來源（本地以 lark_record_id 尋找）
        source_ids = [it.source_record_id for it in request.items]
        src_rows = db.query(TestCaseLocalDB).filter(
            TestCaseLocalDB.team_id == team_id,
            TestCaseLocalDB.lark_record_id.in_(source_ids)
        ).all()
        src_map = {r.lark_record_id: r for r in src_rows if r.lark_record_id}

        created = 0
        errors: List[str] = []

        for it in request.items:
            src = src_map.get(it.source_record_id)
            if not src:
                errors.append(f"來源記錄不存在: {it.source_record_id}")
                continue

            try:
                new_title = (it.title.strip() if (it.title is not None and it.title.strip()) else src.title)
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
            except Exception as e:
                errors.append(f"來源 {it.source_record_id} 複製失敗: {str(e)}")

        if created == 0 and errors:
            db.rollback()
            return BulkCloneResponse(success=False, created_count=0, duplicates=[], errors=errors)

        db.commit()
        return BulkCloneResponse(success=True, created_count=created, duplicates=[], errors=errors)
    except Exception as e:
        db.rollback()
        return BulkCloneResponse(success=False, created_count=0, duplicates=[], errors=[str(e)])


@router.post("/batch", response_model=TestCaseBatchResponse)
async def batch_operation_test_cases(
    team_id: int,
    operation: TestCaseBatchOperation,
    db: Session = Depends(get_db)
):
    """批次操作本地測試案例（不呼叫 Lark）。
    支援：delete、update_priority。update_tcg 暫不支援（需另定規格）。
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
            item = db.query(TestCaseLocalDB).filter(TestCaseLocalDB.id == rid_int).first()
            if item and item.team_id == team_id:
                return item
        except ValueError:
            pass
        # 2) lark_record_id
        item = db.query(TestCaseLocalDB).filter(
            TestCaseLocalDB.team_id == team_id,
            TestCaseLocalDB.lark_record_id == rid
        ).first()
        if item:
            return item
        # 3) test_case_number
        item = db.query(TestCaseLocalDB).filter(
            TestCaseLocalDB.team_id == team_id,
            TestCaseLocalDB.test_case_number == rid
        ).first()
        return item

    processed = 0
    success_count = 0
    errors: list[str] = []

    try:
        if operation.operation == "delete":
            for rid in operation.record_ids:
                processed += 1
                item = resolve_one(rid)
                if not item:
                    errors.append(f"找不到測試案例 {rid}")
                    continue
                # 刪檔（非致命）
                try:
                    if item.attachments_json:
                        data = json.loads(item.attachments_json)
                        if isinstance(data, list):
                            project_root = Path(__file__).resolve().parents[2]
                            for f in data:
                                ap = f.get('absolute_path')
                                if ap:
                                    p = Path(ap)
                                    if (project_root / 'attachments') in p.parents and p.exists():
                                        p.unlink()
                    # 刪除目錄
                    project_root = Path(__file__).resolve().parents[2]
                    base_dir = project_root / 'attachments' / 'test-cases' / str(team_id) / (item.test_case_number or '')
                    if base_dir.exists():
                        import shutil
                        shutil.rmtree(base_dir, ignore_errors=True)
                except Exception:
                    pass
                db.delete(item)
                success_count += 1
            db.commit()

        elif operation.operation == "update_priority":
            pr = (operation.update_data or {}).get('priority') if operation.update_data else None
            if not pr:
                raise HTTPException(status_code=400, detail="批次更新優先級需要提供 priority")
            for rid in operation.record_ids:
                processed += 1
                item = resolve_one(rid)
                if not item:
                    errors.append(f"找不到測試案例 {rid}")
                    continue
                try:
                    item.priority = pr
                    item.sync_status = SyncStatus.PENDING
                    success_count += 1
                except Exception as e:
                    errors.append(f"{rid}: {e}")
            db.commit()

        elif operation.operation == "update_tcg":
            raise HTTPException(status_code=400, detail="update_tcg 尚未支援（請提供規格）")
        else:
            raise HTTPException(status_code=400, detail=f"不支援的批次操作: {operation.operation}")

        return TestCaseBatchResponse(
            success=len(errors) == 0,
            processed_count=processed,
            success_count=success_count,
            error_count=len(errors),
            error_messages=errors
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
            error_messages=errors + [str(e)]
        )
