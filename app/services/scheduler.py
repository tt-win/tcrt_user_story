"""定時任務管理器。"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_access.main import MainAccessBoundary, get_main_access_boundary
from app.models.database_models import ScheduledService
from app.services.lark_org_sync_service import get_lark_org_sync_service

LOGGER = logging.getLogger(__name__)
DEFAULT_SCHEDULE_TYPE = "daily"
DEFAULT_SERVICE_TIME = "02:00"
RECOVERY_STATUS = "interrupted"


@dataclass(frozen=True)
class SchedulableServiceDefinition:
    service_key: str
    display_name: str
    description: str
    schedule_type: str
    default_run_at_time: str
    runner: Callable[[], Any]


class TaskScheduler:
    """定時任務調度器。"""

    def __init__(self, main_boundary: MainAccessBoundary | None = None):
        self.logger = LOGGER
        self.main_boundary = main_boundary or get_main_access_boundary()
        self.running = False
        self.scheduler_thread: threading.Thread | None = None
        self._runtime_loop: asyncio.AbstractEventLoop | None = None
        self._runtime_loop_thread_id: int | None = None
        self.tasks: dict[str, dict[str, Any]] = {}
        self.service_registry: dict[str, SchedulableServiceDefinition] = {
            "lark_org_sync": SchedulableServiceDefinition(
                service_key="lark_org_sync",
                display_name="Lark 組織同步",
                description="執行完整的 Lark 部門與使用者同步，並在成功後清理舊資料。",
                schedule_type=DEFAULT_SCHEDULE_TYPE,
                default_run_at_time=DEFAULT_SERVICE_TIME,
                runner=self._run_lark_org_sync,
            )
        }

    async def initialize(self) -> None:
        """在啟動時載入排程設定並回收殘留狀態。"""
        self._bind_runtime_loop()
        await self._refresh_from_database_async(recover_running=True)

    def start(self):
        """啟動調度器。"""
        if self.running:
            return

        self._bind_runtime_loop()

        self.running = True

        self.scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self.scheduler_thread.start()
        self.logger.info("定時任務調度器已啟動")

    def stop(self):
        """停止調度器。"""
        self.running = False
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            if self._runtime_loop_thread_id == threading.get_ident():
                self.logger.info("略過在 runtime event loop 執行緒上等待 scheduler thread 結束")
            else:
                self.scheduler_thread.join(timeout=5)
        self.logger.info("定時任務調度器已停止")

    async def list_services(self) -> list[dict[str, Any]]:
        """回傳所有可排程服務與目前狀態。"""
        self._bind_runtime_loop()
        await self._refresh_from_database_async(recover_running=False)
        return [self._snapshot_task(task) for task in self.tasks.values()]

    async def update_service_schedule(
        self,
        *,
        service_key: str,
        enabled: bool,
        run_at_time: str,
    ) -> dict[str, Any]:
        """更新單一服務排程設定。"""
        self._bind_runtime_loop()
        normalized_time = self._normalize_run_at_time(run_at_time)
        definition = self._get_definition(service_key)

        async def _update(session: AsyncSession) -> dict[str, Any]:
            record = await self._ensure_service_record(session, definition)
            current_time = self._current_local_time()
            record.enabled = bool(enabled)
            record.run_at_time = normalized_time
            record.schedule_type = definition.schedule_type
            record.next_run_at = self._compute_next_run_at(
                normalized_time,
                enabled=bool(enabled),
                reference=current_time,
            )
            record.updated_at = current_time
            await session.flush()
            return self._serialize_record(record)

        payload = await self.main_boundary.run_write(_update)
        await self._refresh_from_database_async(recover_running=False)
        return payload

    def get_task_status(self) -> dict[str, Any]:
        """取得所有任務的狀態。"""
        return {
            "scheduler_running": self.running,
            "tasks": {task_key: self._snapshot_task(task) for task_key, task in self.tasks.items()},
        }

    def trigger_task(self, task_name: str) -> bool:
        """手動觸發任務執行。"""
        task_info = self.tasks.get(task_name)
        if not task_info:
            return False
        self._execute_task(task_name, task_info)
        return True

    def _scheduler_loop(self):
        """調度主循環。"""
        while self.running:
            try:
                self._run_due_tasks()
                time.sleep(60)
            except Exception as exc:  # noqa: BLE001
                self.logger.error("調度器循環異常: %s", exc, exc_info=True)
                time.sleep(60)

    def _run_due_tasks(self, reference_time: datetime | None = None) -> None:
        current_time = reference_time or self._current_local_time()
        for task_name, task_info in list(self.tasks.items()):
            if not task_info.get("enabled"):
                continue
            next_run = task_info.get("next_run")
            if next_run and current_time >= next_run and not task_info.get("is_running"):
                self._execute_task(task_name, task_info)

    def _execute_task(self, task_name: str, task_info: dict[str, Any]):
        """執行單個任務。"""
        self._run_coroutine_blocking(
            self._execute_task_async(task_name, task_info),
            allow_running_loop=False,
        )

    async def _execute_task_async(self, task_name: str, task_info: dict[str, Any]) -> None:
        """在綁定的 event loop 中執行單個任務。"""
        definition = task_info["definition"]
        started_at = self._current_local_time()

        try:
            self.logger.info("開始執行定時任務: %s", task_name)
            await self._mark_task_started(task_name, started_at)

            result = definition.runner()
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, dict):
                result = {
                    "success": bool(result),
                    "message": str(result),
                }

            finished_at = self._current_local_time()
            success = bool(result.get("success", False))
            message = str(result.get("message") or "")
            last_error = None if success else (message or str(result.get("error") or ""))

            await self._mark_task_finished(
                task_name,
                finished_at=finished_at,
                success=success,
                message=message,
                last_error=last_error,
            )

            execution_seconds = (finished_at - started_at).total_seconds()
            self.logger.info(
                "定時任務 %s 執行完成, 耗時: %.2f 秒, 結果: %s",
                task_name,
                execution_seconds,
                message or success,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.error("定時任務 %s 執行失敗: %s", task_name, exc, exc_info=True)
            await self._mark_task_finished(
                task_name,
                finished_at=self._current_local_time(),
                success=False,
                message=str(exc),
                last_error=str(exc),
            )

    async def _refresh_from_database_async(self, *, recover_running: bool) -> None:
        definitions = list(self.service_registry.values())

        async def _load(session: AsyncSession) -> list[dict[str, Any]]:
            payloads: list[dict[str, Any]] = []
            for definition in definitions:
                record = await self._ensure_service_record(session, definition)
                if recover_running and record.is_running:
                    self._recover_stale_record(record)
                payloads.append(self._serialize_record(record))
            await session.flush()
            return payloads

        records = await self.main_boundary.run_write(_load)
        self.tasks = {record["service_key"]: self._build_task_info(record) for record in records}

    async def _mark_task_started(self, service_key: str, started_at: datetime) -> None:
        definition = self._get_definition(service_key)

        async def _update(session: AsyncSession) -> dict[str, Any]:
            record = await self._ensure_service_record(session, definition)
            record.is_running = True
            record.last_run_started_at = started_at
            record.last_run_finished_at = None
            record.last_run_status = "running"
            record.last_run_message = "排程任務執行中"
            record.last_error = None
            record.updated_at = started_at
            await session.flush()
            return self._serialize_record(record)

        payload = await self.main_boundary.run_write(_update)
        self.tasks[service_key] = self._build_task_info(payload)

    async def _mark_task_finished(
        self,
        service_key: str,
        *,
        finished_at: datetime,
        success: bool,
        message: str,
        last_error: str | None,
    ) -> None:
        definition = self._get_definition(service_key)

        async def _update(session: AsyncSession) -> dict[str, Any]:
            record = await self._ensure_service_record(session, definition)
            record.is_running = False
            record.last_run_finished_at = finished_at
            record.last_run_status = "completed" if success else "failed"
            record.last_run_message = message or ("執行成功" if success else "執行失敗")
            record.last_error = last_error
            record.next_run_at = self._compute_next_run_at(
                record.run_at_time or definition.default_run_at_time,
                enabled=bool(record.enabled),
                reference=finished_at,
            )
            record.updated_at = finished_at
            await session.flush()
            return self._serialize_record(record)

        payload = await self.main_boundary.run_write(_update)
        self.tasks[service_key] = self._build_task_info(payload)

    async def _run_lark_org_sync(self) -> dict[str, Any]:
        """Lark 組織架構同步任務。"""
        sync_service = get_lark_org_sync_service()
        result = await sync_service.sync_full_organization()
        if result.get("success", False):
            cleanup_result = await sync_service.cleanup_old_data(days_threshold=30)
            message = result.get("message", "Lark 組織同步完成")
            if cleanup_result.get("error"):
                message = f"{message}；清理舊資料失敗: {cleanup_result['error']}"
                return {
                    "success": False,
                    "message": message,
                    "sync_result": result,
                    "cleanup_result": cleanup_result,
                }
            return {
                "success": True,
                "message": message,
                "sync_result": result,
                "cleanup_result": cleanup_result,
            }
        return {
            "success": False,
            "message": result.get("message", "Lark 組織同步失敗"),
            "sync_result": result,
        }

    async def _ensure_service_record(
        self,
        session: AsyncSession,
        definition: SchedulableServiceDefinition,
    ) -> ScheduledService:
        result = await session.execute(
            select(ScheduledService).where(ScheduledService.service_key == definition.service_key)
        )
        record = result.scalar_one_or_none()
        if record is None:
            record = ScheduledService(
                service_key=definition.service_key,
                display_name=definition.display_name,
                description=definition.description,
                schedule_type=definition.schedule_type,
                run_at_time=definition.default_run_at_time,
                enabled=False,
                is_running=False,
                last_run_status=None,
                last_run_message=None,
                last_error=None,
                next_run_at=None,
            )
            session.add(record)
            await session.flush()
            return record

        record.display_name = definition.display_name
        record.description = definition.description
        record.schedule_type = definition.schedule_type
        if not record.run_at_time:
            record.run_at_time = definition.default_run_at_time
        if record.enabled and record.next_run_at is None:
            record.next_run_at = self._compute_next_run_at(
                record.run_at_time,
                enabled=True,
            )
        return record

    def _recover_stale_record(self, record: ScheduledService) -> None:
        now = self._current_local_time()
        record.is_running = False
        record.last_run_status = RECOVERY_STATUS
        record.last_run_message = "偵測到上次排程執行中斷，已於啟動時回收"
        record.last_error = "scheduler process interrupted before completion"
        record.last_run_finished_at = now
        record.next_run_at = self._compute_next_run_at(
            record.run_at_time or DEFAULT_SERVICE_TIME,
            enabled=bool(record.enabled),
            reference=now,
        )
        record.updated_at = now

    def _serialize_record(self, record: ScheduledService) -> dict[str, Any]:
        return {
            "service_key": record.service_key,
            "display_name": record.display_name,
            "description": record.description,
            "schedule_type": record.schedule_type,
            "run_at_time": record.run_at_time,
            "enabled": bool(record.enabled),
            "is_running": bool(record.is_running),
            "last_run_status": record.last_run_status,
            "last_run_message": record.last_run_message,
            "last_error": record.last_error,
            "last_run_started_at": record.last_run_started_at.isoformat() if record.last_run_started_at else None,
            "last_run_finished_at": record.last_run_finished_at.isoformat() if record.last_run_finished_at else None,
            "next_run_at": record.next_run_at.isoformat() if record.next_run_at else None,
        }

    def _build_task_info(self, payload: dict[str, Any]) -> dict[str, Any]:
        definition = self._get_definition(payload["service_key"])
        next_run_raw = payload.get("next_run_at")
        last_run_finished_raw = payload.get("last_run_finished_at")
        return {
            "definition": definition,
            "service_key": payload["service_key"],
            "display_name": payload.get("display_name") or definition.display_name,
            "description": payload.get("description") or definition.description,
            "schedule_type": payload.get("schedule_type") or definition.schedule_type,
            "run_at_time": payload.get("run_at_time") or definition.default_run_at_time,
            "enabled": bool(payload.get("enabled")),
            "is_running": bool(payload.get("is_running")),
            "last_run_status": payload.get("last_run_status"),
            "last_run_message": payload.get("last_run_message"),
            "last_error": payload.get("last_error"),
            "last_run_started_at": payload.get("last_run_started_at"),
            "last_run_finished_at": payload.get("last_run_finished_at"),
            "next_run": datetime.fromisoformat(next_run_raw) if next_run_raw else None,
            "last_run": datetime.fromisoformat(last_run_finished_raw) if last_run_finished_raw else None,
        }

    def _snapshot_task(self, task: dict[str, Any]) -> dict[str, Any]:
        return {
            "service_key": task["service_key"],
            "display_name": task["display_name"],
            "description": task["description"],
            "schedule_type": task["schedule_type"],
            "run_at_time": task["run_at_time"],
            "enabled": task["enabled"],
            "is_running": task["is_running"],
            "next_run": task["next_run"].isoformat() if task.get("next_run") else None,
            "last_run": task["last_run"].isoformat() if task.get("last_run") else None,
            "last_run_status": task.get("last_run_status"),
            "last_run_message": task.get("last_run_message"),
            "last_error": task.get("last_error"),
            "last_run_started_at": task.get("last_run_started_at"),
            "last_run_finished_at": task.get("last_run_finished_at"),
        }

    def _get_definition(self, service_key: str) -> SchedulableServiceDefinition:
        try:
            return self.service_registry[service_key]
        except KeyError as exc:
            raise ValueError(f"不支援的排程服務: {service_key}") from exc

    def _normalize_run_at_time(self, raw_value: str) -> str:
        value = str(raw_value or "").strip()
        try:
            parsed = datetime.strptime(value, "%H:%M")
        except ValueError as exc:
            raise ValueError("run_at_time 必須為 HH:MM 格式") from exc
        return parsed.strftime("%H:%M")

    def _compute_next_run_at(
        self,
        run_at_time: str,
        *,
        enabled: bool,
        reference: datetime | None = None,
    ) -> datetime | None:
        if not enabled:
            return None

        normalized_time = self._normalize_run_at_time(run_at_time)
        ref = reference or self._current_local_time()
        hour, minute = [int(part) for part in normalized_time.split(":", maxsplit=1)]
        candidate = datetime.combine(ref.date(), dt_time(hour=hour, minute=minute))
        if candidate <= ref:
            candidate = datetime.combine(ref.date() + timedelta(days=1), dt_time(hour=hour, minute=minute))
        return candidate

    def _current_local_time(self) -> datetime:
        return datetime.now()

    def _bind_runtime_loop(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._runtime_loop = loop
        self._runtime_loop_thread_id = threading.get_ident()

    def _run_coroutine_blocking(self, coroutine: Any, *, allow_running_loop: bool = True) -> Any:
        runtime_loop = self._runtime_loop
        runtime_loop_thread_id = self._runtime_loop_thread_id
        if runtime_loop and runtime_loop.is_running() and runtime_loop_thread_id != threading.get_ident():
            future = asyncio.run_coroutine_threadsafe(coroutine, runtime_loop)
            return future.result()

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coroutine)

        if loop is runtime_loop and not allow_running_loop:
            if hasattr(coroutine, "close"):
                coroutine.close()
            raise RuntimeError("無法在執行中的 runtime event loop 上同步等待 coroutine")

        if not allow_running_loop:
            if hasattr(coroutine, "close"):
                coroutine.close()
            raise RuntimeError("無法在執行中的 event loop 上同步等待 coroutine")

        return loop.create_task(coroutine)


task_scheduler = TaskScheduler()
