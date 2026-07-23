"""Knowledge Write Service.

負責將 TestCase / USM 資料寫入 Qdrant：embed + upsert。
支援 initial bulk load（backfill）、incremental write、event-driven write。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from qdrant_client.http import models as qmodels

from app.config import KnowledgeGraphConfig
from app.services.knowledge.embedding_service import EmbeddingService
from app.services.knowledge.qdrant_client import QdrantKnowledgeClient

LOGGER = logging.getLogger(__name__)


@dataclass
class BackfillProgress:
    entity_type: str
    processed_count: int
    total_count: int
    last_processed_id: str | None
    status: str  # in_progress / completed / failed
    started_at: str
    updated_at: str


class KnowledgeWriteService:
    """TestCase / USM → embed → Qdrant upsert."""

    def __init__(
        self,
        qdrant_client: QdrantKnowledgeClient,
        embedding_service: EmbeddingService,
        config: KnowledgeGraphConfig,
    ) -> None:
        self._qdrant = qdrant_client
        self._embedding = embedding_service
        self._config = config
        # in-memory watermarks (per entity type)
        self._watermarks: dict[str, str | None] = {
            "test_cases": None,
            "usm_nodes": None,
        }
        self._is_backfill_in_progress: bool = False
        self._scheduler_task: asyncio.Task[None] | None = None
        self._stopped = False

    # ----- Watermark management -----

    def get_watermark(self, entity_type: str) -> str | None:
        return self._watermarks.get(entity_type)

    def set_watermark(self, entity_type: str, ts: str) -> None:
        self._watermarks[entity_type] = ts

    # ----- Backfill progress management -----

    def _progress_path(self) -> Path:
        return Path(self._config.backfill_progress_path)

    def _load_progress(self, entity_type: str) -> BackfillProgress | None:
        path = self._progress_path()
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            LOGGER.warning("Failed to load backfill progress: %s", exc)
            return None
        entry = data.get(entity_type)
        if not entry:
            return None
        return BackfillProgress(
            entity_type=entity_type,
            processed_count=entry.get("processed_count", 0),
            total_count=entry.get("total_count", 0),
            last_processed_id=entry.get("last_processed_id"),
            status=entry.get("status", "in_progress"),
            started_at=entry.get("started_at", ""),
            updated_at=entry.get("updated_at", ""),
        )

    def _save_progress(self, progress: BackfillProgress) -> None:
        path = self._progress_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}
        data[progress.entity_type] = {
            "processed_count": progress.processed_count,
            "total_count": progress.total_count,
            "last_processed_id": progress.last_processed_id,
            "status": progress.status,
            "started_at": progress.started_at,
            "updated_at": progress.updated_at,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _clear_progress(self, entity_type: str) -> None:
        path = self._progress_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data.pop(entity_type, None)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except (json.JSONDecodeError, OSError):
            pass

    # ----- Point ID helpers -----

    @staticmethod
    def _test_case_point_id(test_case_number: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"tcrt-test-case:{test_case_number}"))

    @staticmethod
    def _usm_point_id(node_id: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"tcrt-usm-node:{node_id}"))

    # ----- Embedding text builders -----

    @staticmethod
    def _test_case_embedding_text(tc: dict[str, Any]) -> str:
        parts = [
            tc.get("title", ""),
            tc.get("precondition", ""),
            tc.get("steps", ""),
            tc.get("expected_result", ""),
        ]
        return "\n".join(p for p in parts if p)

    @staticmethod
    def _usm_embedding_text(node: dict[str, Any]) -> str:
        bdd_parts = []
        if node.get("as_a"):
            bdd_parts.append(f"As a {node['as_a']}")
        if node.get("i_want"):
            bdd_parts.append(f"I want {node['i_want']}")
        if node.get("so_that"):
            bdd_parts.append(f"so that {node['so_that']}")
        bdd = ", ".join(bdd_parts)
        parts = [
            node.get("title", ""),
            node.get("description", ""),
            bdd,
        ]
        return "\n".join(p for p in parts if p)

    # ----- Single entity write -----

    async def write_test_case(self, tc: dict[str, Any]) -> None:
        """Write a single test case to Qdrant."""
        if not await self._ensure_collections():
            return
        text = self._test_case_embedding_text(tc)
        test_case_number = tc.get("test_case_number", "")
        if not text.strip() and test_case_number:
            try:
                from app.db_access.main import MainAccessBoundary
                from app.services.knowledge.data_sources import fetch_test_case_by_number
                boundary = MainAccessBoundary()
                fetched = await fetch_test_case_by_number(boundary, test_case_number)
                if fetched:
                    tc = fetched
                    text = self._test_case_embedding_text(tc)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Failed to fetch test case %s from DB for KG write: %s", test_case_number, exc)

        if not text.strip():
            LOGGER.warning("Test case %s has no embeddable text, skipping", tc.get("test_case_number"))
            return
        embedding = await self._embedding.embed_one(text)
        if not test_case_number:
            test_case_number = tc.get("test_case_number", "")
        if not test_case_number:
            LOGGER.warning("Test case missing test_case_number, skipping")
            return
        payload = self._build_test_case_payload(tc)
        point = qmodels.PointStruct(
            id=self._test_case_point_id(test_case_number),
            vector=embedding,
            payload=payload,
        )
        collection = self._config.qdrant.collection_test_cases
        await self._qdrant.upsert_points(collection, [point])

    async def write_usm_node(self, node: dict[str, Any]) -> None:
        if not await self._ensure_collections():
            return
        text = self._usm_embedding_text(node)
        node_id = node.get("node_id", "")
        if not text.strip() and node_id:
            try:
                from app.db_access.usm import UsmAccessBoundary
                from app.services.knowledge.data_sources import fetch_usm_node_by_id
                boundary = UsmAccessBoundary()
                fetched = await fetch_usm_node_by_id(boundary, node_id)
                if fetched:
                    node = fetched
                    text = self._usm_embedding_text(node)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Failed to fetch USM node %s from DB for KG write: %s", node_id, exc)

        if not text.strip():
            LOGGER.warning("USM node %s has no embeddable text, skipping", node.get("node_id"))
            return
        embedding = await self._embedding.embed_one(text)
        if not node_id:
            node_id = node.get("node_id", "")
        if not node_id:
            LOGGER.warning("USM node missing node_id, skipping")
            return
        payload = self._build_usm_payload(node)
        point = qmodels.PointStruct(
            id=self._usm_point_id(node_id),
            vector=embedding,
            payload=payload,
        )
        collection = self._config.qdrant.collection_usm_nodes
        await self._qdrant.upsert_points(collection, [point])

    async def write_entity(
        self,
        entity_type: str,
        entity_id: str,
        payload: Any = None,
        operation: str = "upsert",
    ) -> None:
        """Generic write/delete entry point used by KnowledgeSyncTaskQueue.

        ``operation`` is one of:
        - ``"upsert"`` (default): embed + upsert to Qdrant
        - ``"delete"``: remove the point from Qdrant
        """
        if operation == "delete":
            if entity_type == "test_cases":
                await self.delete_test_case(entity_id)
            elif entity_type == "usm_nodes":
                await self.delete_usm_node(entity_id)
            else:
                LOGGER.warning("Unknown entity_type for delete: %s", entity_type)
            return
        if entity_type == "test_cases":
            data = payload or {"test_case_number": entity_id}
            await self.write_test_case(data)
        elif entity_type == "usm_nodes":
            data = payload or {"node_id": entity_id}
            await self.write_usm_node(data)
        else:
            LOGGER.warning("Unknown entity_type for write: %s", entity_type)

    # ----- Delete operations -----

    async def delete_test_case(self, test_case_number: str) -> None:
        """Delete a test case point from Qdrant by test_case_number.

        Uses a Qdrant payload filter to match the canonical test_case_number;
        no embedding roundtrip is required.  Idempotent: a no-op if the
        point does not exist.
        """
        if not test_case_number:
            LOGGER.warning("delete_test_case called with empty test_case_number, skipping")
            return
        collection = self._config.qdrant.collection_test_cases
        await self._qdrant.delete_by_filter(
            collection=collection,
            query_filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="test_case_number",
                        match=qmodels.MatchValue(value=test_case_number),
                    )
                ]
            ),
        )
        LOGGER.info("Deleted test case point: %s", test_case_number)

    async def delete_usm_node(self, node_id: str) -> None:
        """Delete a USM node point from Qdrant by node_id."""
        if not node_id:
            LOGGER.warning("delete_usm_node called with empty node_id, skipping")
            return
        collection = self._config.qdrant.collection_usm_nodes
        await self._qdrant.delete_by_filter(
            collection=collection,
            query_filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="node_id",
                        match=qmodels.MatchValue(value=node_id),
                    )
                ]
            ),
        )
        LOGGER.info("Deleted USM node point: %s", node_id)

    # ----- Payload builders -----

    @staticmethod
    def _build_test_case_payload(tc: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "test_case_number": tc.get("test_case_number", ""),
            "title": tc.get("title", ""),
        }
        for key in [
            "test_case_id",
            "priority",
            "precondition",
            "steps",
            "expected_result",
            "team_id",
            "team_name",
            "section_id",
            "section_name",
            "test_case_set_id",
        ]:
            if key in tc:
                payload[key] = tc[key]
        if tc.get("jira_tickets"):
            payload["jira_tickets"] = tc["jira_tickets"]
        if tc.get("tags"):
            payload["tags"] = tc["tags"]
        payload["last_synced_at"] = datetime.now(timezone.utc).isoformat()
        return payload

    @staticmethod
    def _build_usm_payload(node: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "node_id": node.get("node_id", ""),
            "title": node.get("title", ""),
        }
        for key in [
            "description",
            "node_type",
            "map_id",
            "map_name",
            "team_id",
            "team_name",
            "as_a",
            "i_want",
            "so_that",
        ]:
            if key in node:
                payload[key] = node[key]
        if node.get("jira_tickets"):
            payload["jira_tickets"] = node["jira_tickets"]
        payload["last_synced_at"] = datetime.now(timezone.utc).isoformat()
        return payload

    # ----- Collection setup -----

    async def _ensure_collections(self) -> bool:
        """Ensure required Qdrant collections exist with correct dimensions.

        Validates that the configured embedding dimensions match the
        existing Qdrant collection dimensions at runtime.  On dimension
        mismatch this function returns ``False`` and emits an error log,
        but DOES NOT mutate the shared config singleton — that is the
        caller's responsibility (and only the caller's).
        """
        dimensions = self._config.embedding.dimensions
        for collection in [
            self._config.qdrant.collection_test_cases,
            self._config.qdrant.collection_usm_nodes,
        ]:
            existing_dims = await self._qdrant.get_collection_dimensions(collection)
            if existing_dims is not None and existing_dims != dimensions:
                LOGGER.error(
                    "Dimension mismatch on %s: configured=%d, existing=%d. "
                    "Caller should stop the backfill / write.",
                    collection,
                    dimensions,
                    existing_dims,
                )
                return False
            await self._qdrant.ensure_collection(
                collection=collection,
                vector_size=dimensions,
                distance=qmodels.Distance.COSINE,
            )
        return True

    # ----- Backfill -----

    async def backfill_test_cases(
        self,
        fetch_all: AsyncIterator[dict[str, Any]],
    ) -> BackfillProgress:
        """Backfill all test cases. `fetch_all` is an async iterator yielding test case dicts."""
        return await self._run_backfill(
            entity_type="test_cases",
            collection=self._config.qdrant.collection_test_cases,
            fetch_all=fetch_all,
            text_builder=self._test_case_embedding_text,
            point_id_builder=self._test_case_point_id,
            payload_builder=self._build_test_case_payload,
        )

    async def backfill_usm_nodes(
        self,
        fetch_all: AsyncIterator[dict[str, Any]],
    ) -> BackfillProgress:
        return await self._run_backfill(
            entity_type="usm_nodes",
            collection=self._config.qdrant.collection_usm_nodes,
            fetch_all=fetch_all,
            text_builder=self._usm_embedding_text,
            point_id_builder=self._usm_point_id,
            payload_builder=self._build_usm_payload,
        )

    async def _run_backfill(
        self,
        *,
        entity_type: str,
        collection: str,
        fetch_all: AsyncIterator[dict[str, Any]],
        text_builder,
        point_id_builder,
        payload_builder,
    ) -> BackfillProgress:
        """Generic backfill loop with batch processing + progress tracking + crash recovery."""
        if self._is_backfill_in_progress:
            raise RuntimeError("Another backfill is already in progress")

        self._is_backfill_in_progress = True
        try:
            if not await self._ensure_collections():
                # Dimension mismatch — record failed progress and bail.
                now_iso = datetime.now(timezone.utc).isoformat()
                failed = BackfillProgress(
                    entity_type=entity_type,
                    processed_count=0,
                    total_count=0,
                    last_processed_id=None,
                    status="failed",
                    started_at=now_iso,
                    updated_at=now_iso,
                )
                self._save_progress(failed)
                return failed

            existing = self._load_progress(entity_type)
            if existing and existing.status in ("in_progress", "failed"):
                # `failed` here means the prior run crashed mid-batch: the
                # `last_processed_id` on disk is the id of the last
                # successfully-embedded batch boundary, and re-running from
                # there is safe (UUID-based point IDs are idempotent).
                LOGGER.info(
                    "Resuming %s backfill: %d/%d processed (previous status=%s)",
                    entity_type,
                    existing.processed_count,
                    existing.total_count,
                    existing.status,
                )
                processed_count = existing.processed_count
                last_processed_id = existing.last_processed_id
                started_at = existing.started_at
            else:
                processed_count = 0
                last_processed_id = None
                started_at = datetime.now(timezone.utc).isoformat()

            now_iso = datetime.now(timezone.utc).isoformat()
            progress = BackfillProgress(
                entity_type=entity_type,
                processed_count=processed_count,
                total_count=0,  # updated incrementally
                last_processed_id=last_processed_id,
                status="in_progress",
                started_at=started_at,
                updated_at=now_iso,
            )
            self._save_progress(progress)

            # Effective batch size for one upsert iteration:
            #   backfill_batch_size × embedding.concurrency
            # The embedding service splits the input into chunks of
            # ``batch_size`` and runs ``concurrency`` of them in parallel.
            # Multiplying here ensures one ``_process_batch`` call yields
            # enough chunks for the full concurrency window; otherwise
            # parallelism is wasted (e.g. 100 items with concurrency=8
            # produces 1 chunk).
            batch_size = self._config.backfill_batch_size * max(1, self._config.embedding.concurrency)
            batch: list[dict[str, Any]] = []
            failed_entities: list[str] = []
            resumed = last_processed_id is not None
            try:
                async for entity in fetch_all:
                    entity_id = str(entity.get("test_case_number") or entity.get("node_id") or "")
                    if resumed:
                        if entity_id == last_processed_id:
                            resumed = False
                        continue

                    batch.append(entity)
                    if len(batch) >= batch_size:
                        count, total = await self._process_batch(
                            batch, collection, text_builder, point_id_builder, payload_builder
                        )
                        progress.processed_count += count
                        progress.total_count = total
                        progress.last_processed_id = batch[-1].get(
                            "test_case_number"
                        ) or batch[-1].get("node_id")
                        progress.updated_at = datetime.now(timezone.utc).isoformat()
                        self._save_progress(progress)
                        batch = []

                if batch:
                    count, total = await self._process_batch(
                        batch, collection, text_builder, point_id_builder, payload_builder
                    )
                    progress.processed_count += count
                    progress.total_count = total
                    progress.last_processed_id = batch[-1].get(
                        "test_case_number"
                    ) or batch[-1].get("node_id")
                    progress.updated_at = datetime.now(timezone.utc).isoformat()
                    self._save_progress(progress)

                progress.status = "completed"
                progress.updated_at = datetime.now(timezone.utc).isoformat()
                self._save_progress(progress)
                # set watermark so incremental sync picks up from now
                self.set_watermark(entity_type, datetime.now(timezone.utc).isoformat())
                LOGGER.info(
                    "Backfill %s completed: %d processed",
                    entity_type,
                    progress.processed_count,
                )
            except Exception as exc:
                progress.status = "failed"
                progress.updated_at = datetime.now(timezone.utc).isoformat()
                self._save_progress(progress)
                LOGGER.error("Backfill %s failed: %s", entity_type, exc)
                raise
            except (KeyboardInterrupt, asyncio.CancelledError):
                # User-initiated cancellation (Ctrl-C or task cancel).  Mark as
                # in_progress so a subsequent run resumes from the last
                # successfully-saved batch boundary; the most recent batch's
                # last_processed_id is already on disk.
                progress.status = "in_progress"
                progress.updated_at = datetime.now(timezone.utc).isoformat()
                self._save_progress(progress)
                LOGGER.warning(
                    "Backfill %s interrupted; progress saved for resume. "
                    "last_processed_id=%s",
                    entity_type,
                    progress.last_processed_id,
                )
                raise
            finally:
                if failed_entities:
                    LOGGER.warning("Backfill %s had %d failed entities", entity_type, len(failed_entities))
            return progress
        finally:
            self._is_backfill_in_progress = False

    async def _process_batch(
        self,
        batch: list[dict[str, Any]],
        collection: str,
        text_builder,
        point_id_builder,
        payload_builder,
    ) -> tuple[int, int]:
        """Process one batch: embed + upsert. Returns (success_count, total_count)."""
        texts = [text_builder(e) for e in batch]
        # filter out empty texts
        non_empty: list[tuple[int, str]] = [
            (i, t) for i, t in enumerate(texts) if t.strip()
        ]
        if not non_empty:
            return 0, len(batch)
        embeddings = await self._embedding.embed_batch([t for _, t in non_empty])
        points: list[qmodels.PointStruct] = []
        for (orig_idx, _), embedding in zip(non_empty, embeddings):
            entity = batch[orig_idx]
            entity_id = entity.get("test_case_number") or entity.get("node_id")
            if not entity_id:
                continue
            payload = payload_builder(entity)
            points.append(
                qmodels.PointStruct(
                    id=point_id_builder(str(entity_id)),
                    vector=embedding,
                    payload=payload,
                )
            )
        if points:
            await self._qdrant.upsert_points(collection, points)
        return len(points), len(batch)

    # ----- Scheduler -----

    async def start_scheduler(self) -> None:
        """Start independent asyncio timer for incremental writes."""
        if self._scheduler_task is not None:
            return
        self._stopped = False
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())

    async def stop_scheduler(self) -> None:
        self._stopped = True
        if self._scheduler_task is not None:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except (asyncio.CancelledError, Exception):
                pass
            self._scheduler_task = None

    async def _scheduler_loop(self) -> None:
        interval = self._config.sync_interval_minutes * 60
        # First tick: auto-detect whether backfill is needed
        first_tick = True
        while not self._stopped:
            try:
                if not self._is_backfill_in_progress:
                    if first_tick:
                        await self._auto_detect_and_backfill()
                        first_tick = False
                    # Placeholder for incremental sync (would query TCRT DB)
                    LOGGER.debug("Incremental write tick (placeholder)")
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Scheduler tick failed: %s", exc)
                await asyncio.sleep(min(interval, 60))

    async def _auto_detect_and_backfill(self) -> None:
        """If watermark missing AND Qdrant collection empty, trigger backfill.

        Note: This requires an async iterator of real data, which is
        provided by callers (CLI or API). Here we only log the detection.
        Actual backfill must be initiated via CLI/REST API.
        """
        for entity_type, collection_name in [
            ("test_cases", self._config.qdrant.collection_test_cases),
            ("usm_nodes", self._config.qdrant.collection_usm_nodes),
        ]:
            watermark = self.get_watermark(entity_type)
            if watermark is not None:
                continue
            is_empty = await self._qdrant.collection_is_empty(collection_name)
            if is_empty:
                LOGGER.info(
                    "Auto-detect: %s watermark missing and Qdrant %s is empty. "
                    "Backfill required (run via CLI: python -m app.services.knowledge backfill --entity %s).",
                    entity_type,
                    collection_name,
                    entity_type,
                )

    async def close(self) -> None:
        await self.stop_scheduler()
        await self._qdrant.close()
        await self._embedding.close()
