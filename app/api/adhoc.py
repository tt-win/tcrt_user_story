from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, joinedload
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging
import traceback

from app.database import get_db, run_sync
from app.auth.dependencies import get_current_user
from app.models.database_models import User, AdHocRun, AdHocRunSheet, AdHocRunItem, TestCaseLocal, TestCaseSet, TestCaseSection
from sqlalchemy import or_
from app.audit import audit_service, ActionType, ResourceType, AuditSeverity
from app.models.adhoc import (
    AdHocRunCreate, AdHocRunUpdate, AdHocRunResponse,
    AdHocRunSheetCreate, AdHocRunSheetUpdate, AdHocRunSheetResponse,
    AdHocRunItemCreate, AdHocRunItemUpdate, AdHocRunItemResponse
)

logger = logging.getLogger(__name__)
from app.models.lark_types import Priority
from app.models.test_run_config import TestRunStatus

router = APIRouter(prefix="/adhoc-runs", tags=["adhoc-runs"])

@router.post("/{run_id}/convert-to-testcases", status_code=status.HTTP_200_OK)
async def convert_adhoc_to_testcases(
    run_id: int,
    payload: Dict[str, Any] = Body(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Convert Ad-hoc run items to formal Test Cases.
    - Ignores SECTION rows.
    - Ignores rows without Test Case Number or Title.
    - Updates existing Test Cases (by Number) or Creates new ones.
    - Optional payload:
        {
            "sheet_id": <limit to a specific sheet>,
            "item_ids": [<only convert these item IDs>],
            "target_set_id": <explicit Test Case Set>,
            "target_section_id": <explicit Section in that set>
        }
    """
    payload_data = payload or {}

    def _convert(sync_db: Session) -> Dict[str, Any]:
        count_created = 0
        count_updated = 0
        try:
            run = sync_db.query(AdHocRun).filter(AdHocRun.id == run_id).first()
            if not run:
                raise HTTPException(status_code=404, detail="Ad-hoc run not found")

            requested_set_id = payload_data.get("target_set_id")
            requested_section_id = payload_data.get("target_section_id")
            limit_sheet_id = payload_data.get("sheet_id")
            limit_item_ids = (
                payload_data.get("item_ids")
                if isinstance(payload_data.get("item_ids"), list)
                else None
            )

            # Resolve Target Test Case Set
            if requested_set_id:
                target_set = sync_db.query(TestCaseSet).filter(
                    TestCaseSet.id == requested_set_id,
                    TestCaseSet.team_id == run.team_id
                ).first()
                if not target_set:
                    raise HTTPException(status_code=400, detail="Invalid target Test Case Set")
            else:
                target_set = sync_db.query(TestCaseSet).filter(
                    TestCaseSet.team_id == run.team_id,
                    TestCaseSet.is_default == True
                ).first()

                # 2. Try name match
                if not target_set:
                    target_set = sync_db.query(TestCaseSet).filter(
                        TestCaseSet.team_id == run.team_id,
                        or_(TestCaseSet.name == "Default Set", TestCaseSet.name == "Default")
                    ).first()

                # 3. Fallback to any set
                if not target_set:
                    target_set = sync_db.query(TestCaseSet).filter(
                        TestCaseSet.team_id == run.team_id
                    ).first()

                # 4. Create if none
                if not target_set:
                    target_set = TestCaseSet(
                        team_id=run.team_id,
                        name="Default Set",
                        is_default=True
                    )
                    sync_db.add(target_set)
                    sync_db.flush()

            # Resolve target section
            if requested_section_id:
                target_section = sync_db.query(TestCaseSection).filter(
                    TestCaseSection.id == requested_section_id,
                    TestCaseSection.test_case_set_id == target_set.id
                ).first()
                target_section_id = target_section.id if target_section else None
            else:
                unassigned_section = sync_db.query(TestCaseSection).filter(
                    TestCaseSection.test_case_set_id == target_set.id,
                    TestCaseSection.name == "Unassigned"
                ).first()
                target_section_id = unassigned_section.id if unassigned_section else None

            # Collect all items
            all_items = []
            for sheet in run.sheets:
                if limit_sheet_id and sheet.id != limit_sheet_id:
                    continue
                all_items.extend(sheet.items)

            if limit_item_ids:
                limit_set = set(limit_item_ids)
                all_items = [i for i in all_items if i.id in limit_set]

            for item in all_items:
                tc_num = (item.test_case_number or "").strip()
                title = (item.title or "").strip()

                if not tc_num or not title:
                    continue
                if tc_num.upper() == "SECTION":
                    continue

                # Check if exists
                existing_tc = sync_db.query(TestCaseLocal).filter(
                    TestCaseLocal.team_id == run.team_id,
                    TestCaseLocal.test_case_number == tc_num
                ).first()

                tcg_data = None
                if item.jira_tickets:
                    normalized_tickets = item.jira_tickets.replace("|", ",")
                    tickets = [t.strip() for t in normalized_tickets.split(",") if t.strip()]
                    if tickets:
                        import json
                        tcg_data = json.dumps(tickets)

                if existing_tc:
                    # Update and also move to chosen Set / Section
                    existing_tc.title = title
                    existing_tc.precondition = item.precondition
                    existing_tc.steps = item.steps
                    existing_tc.expected_result = item.expected_result
                    existing_tc.priority = item.priority
                    existing_tc.tcg_json = tcg_data
                    existing_tc.updated_at = datetime.utcnow()
                    existing_tc.test_case_set_id = target_set.id
                    existing_tc.test_case_section_id = target_section_id
                    count_updated += 1
                else:
                    # Create
                    new_tc = TestCaseLocal(
                        team_id=run.team_id,
                        test_case_number=tc_num,
                        title=title,
                        precondition=item.precondition,
                        steps=item.steps,
                        expected_result=item.expected_result,
                        priority=item.priority,
                        tcg_json=tcg_data,
                        test_case_set_id=target_set.id,
                        test_case_section_id=target_section_id
                    )
                    sync_db.add(new_tc)
                    count_created += 1

            sync_db.commit()
            return {
                "run_id": run.id,
                "run_name": run.name,
                "team_id": run.team_id,
                "created": count_created,
                "updated": count_updated,
            }
        except HTTPException:
            sync_db.rollback()
            raise
        except Exception:
            sync_db.rollback()
            raise

    try:
        result = await run_sync(db, _convert)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Convert Ad-hoc to Test Cases failed: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Conversion failed: {str(e)}")

    # Audit Log
    await audit_service.log_action(
        user_id=current_user.id,
        username=current_user.username,
        role=str(current_user.role.value if hasattr(current_user.role, "value") else current_user.role),
        action_type=ActionType.CREATE, # or UPDATE, mixed here
        resource_type=ResourceType.TEST_CASE,
        resource_id=str(result["run_id"]), # Related run ID as resource ID or maybe "batch"
        team_id=result["team_id"],
        severity=AuditSeverity.INFO,
        action_brief=f"Converted Ad-hoc Run '{result['run_name']}' to Test Cases",
        details={"created": result["created"], "updated": result["updated"]}
    )

    return {
        "success": True,
        "created": result["created"],
        "updated": result["updated"],
        "message": f"Successfully converted: {result['created']} created, {result['updated']} updated."
    }

@router.post("/", response_model=AdHocRunResponse, status_code=status.HTTP_201_CREATED)
async def create_adhoc_run(
    payload: AdHocRunCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    def _create(sync_db: Session) -> AdHocRun:
        try:
            new_run = AdHocRun(
                team_id=payload.team_id,
                name=payload.name,
                description=payload.description,
                status=TestRunStatus.ACTIVE, # Default to Active now
                jira_ticket=payload.jira_ticket,
                # Enhanced Basic Settings
                test_version=payload.test_version,
                test_environment=payload.test_environment,
                build_number=payload.build_number,
                related_tp_tickets_json=payload.related_tp_tickets_json,
                notifications_enabled=payload.notifications_enabled,
                notify_chat_ids_json=payload.notify_chat_ids_json,
                notify_chat_names_snapshot=payload.notify_chat_names_snapshot
            )
            sync_db.add(new_run)
            sync_db.flush()

            # Create default sheet
            default_sheet = AdHocRunSheet(
                adhoc_run_id=new_run.id,
                name="Sheet1",
                sort_order=0
            )
            sync_db.add(default_sheet)
            sync_db.flush() # Get sheet ID

            # Create initial 5 empty rows
            for i in range(5):
                new_item = AdHocRunItem(
                    sheet_id=default_sheet.id,
                    row_index=i,
                    test_case_number=None,
                    title=None,
                    priority=Priority.MEDIUM,
                    precondition=None,
                    steps=None,
                    expected_result=None
                )
                sync_db.add(new_item)

            sync_db.commit()

            # Query back with relationships to ensure Pydantic model validation works
            result = sync_db.query(AdHocRun).options(
                joinedload(AdHocRun.sheets).joinedload(AdHocRunSheet.items)
            ).filter(AdHocRun.id == new_run.id).first()
            return result
        except Exception:
            sync_db.rollback()
            raise

    try:
        result = await run_sync(db, _create)
    except Exception as e:
        logger.error(f"Create Ad-hoc Run failed: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

    # Audit Log
    await audit_service.log_action(
        user_id=current_user.id,
        username=current_user.username,
        role=str(current_user.role.value if hasattr(current_user.role, "value") else current_user.role),
        action_type=ActionType.CREATE,
        resource_type=ResourceType.TEST_RUN,
        resource_id=str(result.id),
        team_id=result.team_id,
        details={"initial_sheets": 1, "initial_items": 5},
        action_brief=f"Created Ad-hoc Run: {result.name}",
        severity=AuditSeverity.INFO,
    )

    return result

@router.get("/{run_id}")
async def get_adhoc_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    def _get(sync_db: Session) -> Dict[str, Any]:
        run = sync_db.query(AdHocRun).filter(AdHocRun.id == run_id).first()

        if not run:
            raise HTTPException(status_code=404, detail="Ad-hoc run not found")

        # Manual serialization to debug
        result = {
            "id": run.id,
            "team_id": run.team_id,
            "name": run.name,
            "description": run.description,
            "status": run.status,
            "jira_ticket": run.jira_ticket,
            "test_version": run.test_version,
            "test_environment": run.test_environment,
            "build_number": run.build_number,
            "related_tp_tickets_json": run.related_tp_tickets_json,
            "notifications_enabled": run.notifications_enabled,
            "notify_chat_ids_json": run.notify_chat_ids_json,
            "notify_chat_names_snapshot": run.notify_chat_names_snapshot,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
            "sheets": []
        }

        # Fetch sheets manually to debug relationship
        for sheet in run.sheets:
            sheet_data = {
                "id": sheet.id,
                "adhoc_run_id": sheet.adhoc_run_id,
                "name": sheet.name,
                "sort_order": sheet.sort_order,
                "created_at": sheet.created_at,
                "updated_at": sheet.updated_at,
                "items": []
            }
            # Fetch items
            for item in sheet.items:
                clean_result = item.test_result if item.test_result else None
                sheet_data["items"].append({
                    "id": item.id,
                    "sheet_id": item.sheet_id,
                    "row_index": item.row_index,
                    "test_case_number": item.test_case_number,
                    "title": item.title,
                    "priority": item.priority,
                    "precondition": item.precondition,
                    "steps": item.steps,
                    "expected_result": item.expected_result,
                    "jira_tickets": item.jira_tickets,
                    "test_result": clean_result,
                    "assignee_name": item.assignee_name,
                    "comments": item.comments,
                    "bug_list": item.bug_list,
                    "attachments_json": item.attachments_json,
                    "execution_results_json": item.execution_results_json,
                    "meta_json": item.meta_json,
                    "executed_at": item.executed_at,
                    "created_at": item.created_at,
                    "updated_at": item.updated_at
                })
            result["sheets"].append(sheet_data)

        return result

    try:
        return await run_sync(db, _get)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get Ad-hoc Run failed: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Internal Error: {str(e)}")

@router.put("/{run_id}", response_model=AdHocRunResponse)
async def update_adhoc_run(
    run_id: int,
    payload: AdHocRunUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    update_data = payload.model_dump(exclude_unset=True)

    def _update(sync_db: Session) -> AdHocRun:
        run = sync_db.query(AdHocRun).filter(AdHocRun.id == run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail="Ad-hoc run not found")

        for key, value in update_data.items():
            if hasattr(run, key):
                setattr(run, key, value)

        run.updated_at = datetime.utcnow()

        sync_db.commit()
        sync_db.refresh(run)
        return run

    run = await run_sync(db, _update)

    # Audit Log
    await audit_service.log_action(
        user_id=current_user.id,
        username=current_user.username,
        role=str(current_user.role.value if hasattr(current_user.role, "value") else current_user.role),
        action_type=ActionType.UPDATE,
        resource_type=ResourceType.TEST_RUN,
        resource_id=str(run.id),
        team_id=run.team_id,
        severity=AuditSeverity.INFO,
        action_brief=f"Updated Ad-hoc Run: {run.name}",
        details={"payload_keys": list(update_data.keys())}
    )

    return run

@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_adhoc_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    def _delete(sync_db: Session) -> Dict[str, str]:
        run = sync_db.query(AdHocRun).filter(AdHocRun.id == run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail="Ad-hoc run not found")

        run_name = run.name
        team_id = run.team_id
        run_id_str = str(run.id)

        sync_db.delete(run)
        sync_db.commit()
        return {
            "run_name": run_name,
            "team_id": team_id,
            "run_id": run_id_str,
        }

    result = await run_sync(db, _delete)

    # Audit Log
    await audit_service.log_action(
        user_id=current_user.id,
        username=current_user.username,
        role=str(current_user.role.value if hasattr(current_user.role, "value") else current_user.role),
        action_type=ActionType.DELETE,
        resource_type=ResourceType.TEST_RUN,
        resource_id=result["run_id"],
        team_id=result["team_id"],
        severity=AuditSeverity.CRITICAL,
        action_brief=f"Deleted Ad-hoc Run: {result['run_name']}"
    )

@router.post("/{run_id}/rerun", response_model=AdHocRunResponse, status_code=status.HTTP_201_CREATED)
async def rerun_adhoc_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Clone an existing Ad-hoc run and its sheets/items, but reset execution results.
    Used for re-running a completed Ad-hoc run.
    """
    def _rerun(sync_db: Session) -> tuple[AdHocRun, Dict[str, Any]]:
        try:
            original_run = sync_db.query(AdHocRun).filter(AdHocRun.id == run_id).first()
            if not original_run:
                raise HTTPException(status_code=404, detail="Original Ad-hoc run not found")

            # 1. Clone Run
            new_run = AdHocRun(
                team_id=original_run.team_id,
                name=f"Rerun - {original_run.name}"[:120], # Ensure length limit
                description=original_run.description,
                status=TestRunStatus.ACTIVE, # Default to Active
                jira_ticket=original_run.jira_ticket,
                test_version=original_run.test_version,
                test_environment=original_run.test_environment,
                build_number=original_run.build_number,
                related_tp_tickets_json=original_run.related_tp_tickets_json,
                notifications_enabled=original_run.notifications_enabled,
                notify_chat_ids_json=original_run.notify_chat_ids_json,
                notify_chat_names_snapshot=original_run.notify_chat_names_snapshot,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            sync_db.add(new_run)
            sync_db.flush() # Get new_run.id

            # 2. Clone Sheets and Items
            for original_sheet in original_run.sheets:
                new_sheet = AdHocRunSheet(
                    adhoc_run_id=new_run.id,
                    name=original_sheet.name,
                    sort_order=original_sheet.sort_order,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                sync_db.add(new_sheet)
                sync_db.flush() # Get new_sheet.id

                for item in original_sheet.items:
                    new_item = AdHocRunItem(
                        sheet_id=new_sheet.id,
                        row_index=item.row_index,
                        test_case_number=item.test_case_number,
                        title=item.title,
                        priority=item.priority,
                        precondition=item.precondition,
                        steps=item.steps,
                        expected_result=item.expected_result,
                        # Reset execution-related fields
                        comments=None,
                        bug_list=None,
                        test_result=None,
                        assignee_name=item.assignee_name, # Keep assignee? Usually yes for rerun
                        executed_at=None,
                        attachments_json=item.attachments_json, # Keep reference attachments
                        execution_results_json=None, # Clear proof of execution
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    sync_db.add(new_item)

            sync_db.commit()

            result = sync_db.query(AdHocRun).options(
                joinedload(AdHocRun.sheets).joinedload(AdHocRunSheet.items)
            ).filter(AdHocRun.id == new_run.id).first()
            return result, {
                "run_id": new_run.id,
                "run_name": new_run.name,
                "team_id": new_run.team_id,
            }
        except HTTPException:
            sync_db.rollback()
            raise
        except Exception:
            sync_db.rollback()
            raise

    try:
        result, audit_ctx = await run_sync(db, _rerun)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Rerun Ad-hoc failed: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Rerun failed: {str(e)}")

    # Audit Log
    await audit_service.log_action(
        user_id=current_user.id,
        username=current_user.username,
        role=str(current_user.role.value if hasattr(current_user.role, "value") else current_user.role),
        action_type=ActionType.CREATE,
        resource_type=ResourceType.TEST_RUN,
        resource_id=str(audit_ctx["run_id"]),
        team_id=audit_ctx["team_id"],
        severity=AuditSeverity.INFO,
        action_brief=f"Rerun Ad-hoc Run: {audit_ctx['run_name']}",
        details={"source_run_id": run_id}
    )

    # Return full structure
    return result

# --- Sheet Endpoints ---

def _load_sheet_with_items(sync_db: Session, run_id: int, sheet_id: int) -> Optional[AdHocRunSheet]:
    """Load sheet with eager-loaded items for response serialization."""
    return (
        sync_db.query(AdHocRunSheet)
        .options(joinedload(AdHocRunSheet.items))
        .filter(
            AdHocRunSheet.id == sheet_id,
            AdHocRunSheet.adhoc_run_id == run_id,
        )
        .first()
    )

@router.post("/{run_id}/sheets", response_model=AdHocRunSheetResponse)
async def create_sheet(
    run_id: int,
    payload: AdHocRunSheetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    def _create(sync_db: Session) -> AdHocRunSheet:
        sheet = AdHocRunSheet(
            adhoc_run_id=run_id,
            name=payload.name,
            sort_order=payload.sort_order
        )
        sync_db.add(sheet)
        sync_db.commit()
        loaded_sheet = _load_sheet_with_items(sync_db, run_id, sheet.id)
        if not loaded_sheet:
            raise HTTPException(status_code=500, detail="Failed to load created sheet")
        return loaded_sheet

    return await run_sync(db, _create)

@router.put("/{run_id}/sheets/{sheet_id}", response_model=AdHocRunSheetResponse)
async def update_sheet(
    run_id: int,
    sheet_id: int,
    payload: AdHocRunSheetUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    def _update(sync_db: Session) -> AdHocRunSheet:
        sheet = sync_db.query(AdHocRunSheet).filter(
            AdHocRunSheet.id == sheet_id,
            AdHocRunSheet.adhoc_run_id == run_id
        ).first()
        if not sheet:
            raise HTTPException(status_code=404, detail="Sheet not found")

        sheet.name = payload.name
        sheet.sort_order = payload.sort_order
        sheet.updated_at = datetime.utcnow()

        sync_db.commit()
        loaded_sheet = _load_sheet_with_items(sync_db, run_id, sheet_id)
        if not loaded_sheet:
            raise HTTPException(status_code=404, detail="Sheet not found")
        return loaded_sheet

    return await run_sync(db, _update)

@router.delete("/{run_id}/sheets/{sheet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sheet(
    run_id: int,
    sheet_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    def _delete(sync_db: Session) -> None:
        sheet = sync_db.query(AdHocRunSheet).filter(
            AdHocRunSheet.id == sheet_id,
            AdHocRunSheet.adhoc_run_id == run_id
        ).first()
        if not sheet:
            raise HTTPException(status_code=404, detail="Sheet not found")

        sync_db.delete(sheet)
        sync_db.commit()

    await run_sync(db, _delete)

# --- Item Endpoints (Batch is preferred for spreadsheet) ---

@router.post("/{run_id}/sheets/{sheet_id}/items/batch", status_code=status.HTTP_200_OK)
async def batch_update_items(
    run_id: int,
    sheet_id: int,
    payload: List[Dict[str, Any]], # List of changes (id, or new item data)
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Batch create/update/delete items for a sheet.
    If 'id' is present (and positive), update.
    If 'id' is missing or negative, create.
    If '_delete' is true, delete.
    """
    def _batch(sync_db: Session) -> tuple[List[AdHocRunItem], Optional[int]]:
        response_data = []

        for item_data in payload:
            item_id = item_data.get("id")
            is_delete = item_data.get("_delete", False)

            if item_id and int(item_id) > 0:
                # Update or Delete existing
                item = sync_db.query(AdHocRunItem).filter(
                    AdHocRunItem.id == item_id,
                    AdHocRunItem.sheet_id == sheet_id
                ).first()
                if item:
                    if is_delete:
                        sync_db.delete(item)
                    else:
                        # Update fields
                        for field in [
                            "test_case_number", "title", "priority", "precondition", "steps",
                            "expected_result", "jira_tickets", "comments", "bug_list", "test_result",
                            "assignee_name", "row_index", "meta_json"
                        ]:
                            if field in item_data:
                                setattr(item, field, item_data[field])
                        item.updated_at = datetime.utcnow()
                        response_data.append(item)
            elif not is_delete:
                # Create new
                new_item = AdHocRunItem(
                    sheet_id=sheet_id,
                    row_index=item_data.get("row_index", 0),
                    test_case_number=item_data.get("test_case_number"),
                    title=item_data.get("title"),
                    priority=item_data.get("priority", "Medium"),
                    precondition=item_data.get("precondition"),
                    steps=item_data.get("steps"),
                    expected_result=item_data.get("expected_result"),
                    jira_tickets=item_data.get("jira_tickets"),
                    comments=item_data.get("comments"),
                    bug_list=item_data.get("bug_list"),
                    test_result=item_data.get("test_result"),
                    assignee_name=item_data.get("assignee_name"),
                    meta_json=item_data.get("meta_json")
                )
                sync_db.add(new_item)
                sync_db.flush() # to get ID
                response_data.append(new_item)

        sync_db.commit()

        run = sync_db.query(AdHocRun).filter(AdHocRun.id == run_id).first()
        team_id = run.team_id if run else None
        return response_data, team_id

    response_data, team_id = await run_sync(db, _batch)

    # Audit Log (Fetch run for team_id if needed, or optimize)
    try:
        if team_id is not None:
            await audit_service.log_action(
                user_id=current_user.id,
                username=current_user.username,
                role=str(current_user.role.value if hasattr(current_user.role, "value") else current_user.role),
                action_type=ActionType.UPDATE,
                resource_type=ResourceType.TEST_RUN,
                resource_id=str(run_id),
                team_id=team_id,
                severity=AuditSeverity.INFO,
                action_brief="Batch updated Ad-hoc items",
                details={"items": len(payload), "sheet_id": sheet_id}
            )
    except Exception:
        pass # Don't fail batch update if audit fails

    return {
        "success": True,
        "items": [
            {
                "id": item.id,
                "row_index": item.row_index
            }
            for item in response_data
        ]
    }

@router.get("/team/{team_id}", response_model=List[AdHocRunResponse])
async def list_team_adhoc_runs(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    def _list(sync_db: Session) -> List[AdHocRun]:
        runs = (
            sync_db.query(AdHocRun)
            .options(joinedload(AdHocRun.sheets).joinedload(AdHocRunSheet.items))
            .filter(AdHocRun.team_id == team_id)
            .order_by(AdHocRun.updated_at.desc())
            .all()
        )
        for r in runs:
            total = 0
            executed = 0
            for s in r.sheets:
                total += len(s.items or [])
                # 若未有執行狀態區分，暫以有 test_result 視為已執行
                executed += len([i for i in (s.items or []) if i.test_result])
            r.total_test_cases = total
            r.executed_cases = executed
        return runs

    return await run_sync(db, _list)
