#!/usr/bin/env python3
"""Safely rebuild local and remote Qdrant ``usm_nodes`` from remote MySQL.

The source transaction is read-only. Each Qdrant target is backed up and a
shadow collection is fully loaded and validated before a physical collection
named ``usm_nodes`` is materialized. Backups and shadows are intentionally
retained.

The MySQL password is accepted only from a named environment variable or a
hidden interactive prompt; it is never accepted as a command-line argument.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import hashlib
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pymysql
from dotenv import dotenv_values
from pymysql.cursors import DictCursor
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"
DEFAULT_QDRANT_TARGETS = (
    "http://127.0.0.1:6333",
    "http://10.81.1.49:6333",
)
CANONICAL_INDEXES: dict[str, qmodels.PayloadSchemaType] = {
    "entity_key": qmodels.PayloadSchemaType.KEYWORD,
    "node_id": qmodels.PayloadSchemaType.KEYWORD,
    "node_type": qmodels.PayloadSchemaType.KEYWORD,
    "map_id": qmodels.PayloadSchemaType.INTEGER,
    "team_id": qmodels.PayloadSchemaType.INTEGER,
    "updated_at": qmodels.PayloadSchemaType.DATETIME,
    "last_synced_at": qmodels.PayloadSchemaType.DATETIME,
}
REQUIRED_PAYLOAD_FIELDS = frozenset(
    {
        "schema_version",
        "resource_type",
        "source",
        "entity_key",
        "node_id",
        "title",
        "description",
        "node_type",
        "map_id",
        "map_name",
        "team_id",
        "team_name",
        "parent_id",
        "parent_key",
        "level",
        "children_ids",
        "children_keys",
        "related_node_ids",
        "related_node_keys",
        "as_a",
        "i_want",
        "so_that",
        "jira_tickets",
        "text",
        "updated_at",
        "last_synced_at",
    }
)


class RebuildError(RuntimeError):
    """Raised when a safety precondition or rebuild validation fails."""


@dataclass(frozen=True)
class EmbeddingSettings:
    provider: str
    model: str
    dimensions: int
    api_key: str
    base_url: str
    batch_size: int
    concurrency: int
    cache_path: str


@dataclass
class TargetState:
    url: str
    client: AsyncQdrantClient
    logical_collection: str
    backup_collection: str
    shadow_collection: str
    original_is_alias: bool = False
    original_alias_target: str | None = None
    original_count: int = 0
    switched: bool = False


def _safe_target(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RebuildError(f"Invalid Qdrant target URL: {url!r}")
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{host}{port}"


def _env_value(values: Mapping[str, str], name: str, default: str = "") -> str:
    return os.getenv(name, values.get(name, default)).strip()


def load_embedding_settings(env_path: Path) -> EmbeddingSettings:
    if not env_path.is_file():
        raise RebuildError(f"Embedding environment file not found: {env_path}")
    raw = dotenv_values(env_path, interpolate=True)
    values = {
        key: value
        for key, value in raw.items()
        if key is not None and value is not None
    }
    try:
        dimensions = int(_env_value(values, "EMBEDDING_DIMENSIONS", "1024"))
        batch_size = int(_env_value(values, "EMBEDDING_BATCH_SIZE", "100"))
        concurrency = int(_env_value(values, "EMBEDDING_CONCURRENCY", "1"))
    except ValueError as exc:
        raise RebuildError("Embedding dimensions/batch/concurrency must be integers") from exc
    provider = _env_value(values, "EMBEDDING_PROVIDER", "openai")
    model = _env_value(values, "EMBEDDING_MODEL")
    base_url = _env_value(values, "EMBEDDING_BASE_URL")
    api_key = _env_value(values, "EMBEDDING_API_KEY")
    if not model or dimensions <= 0 or batch_size <= 0 or concurrency <= 0:
        raise RebuildError("Embedding model and positive numeric settings are required")
    if provider.lower() != "openrouter" and not base_url and not api_key:
        raise RebuildError(
            "EMBEDDING_BASE_URL or EMBEDDING_API_KEY is required for the provider"
        )
    return EmbeddingSettings(
        provider=provider,
        model=model,
        dimensions=dimensions,
        api_key=api_key,
        base_url=base_url,
        batch_size=batch_size,
        concurrency=concurrency,
        cache_path=_env_value(values, "EMBEDDING_CACHE_PATH", "none"),
    )


def resolve_mysql_password(env_name: str) -> str:
    password = os.getenv(env_name, "")
    if password:
        return password
    if not sys.stdin.isatty():
        raise RebuildError(
            f"Set {env_name} or run interactively so the password can be hidden"
        )
    password = getpass.getpass("Remote MySQL password: ")
    if not password:
        raise RebuildError("MySQL password must not be empty")
    return password


def mutation_authorized(*, dry_run: bool, yes: bool) -> bool:
    """Return whether mutation is authorized, or reject an unsafe mode."""
    if dry_run and yes:
        raise RebuildError("--dry-run and --yes are mutually exclusive")
    if dry_run:
        return False
    if not yes:
        raise RebuildError("Mutation requires --yes (run --dry-run first)")
    return True


def fetch_remote_usm_nodes(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
) -> list[dict[str, Any]]:
    """Fetch one consistent, read-only snapshot from the two remote schemas."""
    connection = pymysql.connect(
        host=host,
        port=port,
        user=username,
        password=password,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        connect_timeout=10,
        read_timeout=60,
        write_timeout=10,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cursor.execute("START TRANSACTION READ ONLY")
            cursor.execute(
                """
                SELECT
                    n.id,
                    n.map_id,
                    n.node_id,
                    n.title,
                    n.description,
                    n.node_type,
                    n.parent_id,
                    n.children_ids,
                    n.related_ids,
                    n.jira_tickets,
                    n.level,
                    n.as_a,
                    n.i_want,
                    n.so_that,
                    n.updated_at,
                    m.name AS map_name,
                    m.team_id,
                    COALESCE(t.name, '') AS team_name
                FROM tcrt_usm.user_story_map_nodes AS n
                INNER JOIN tcrt_usm.user_story_maps AS m ON m.id = n.map_id
                LEFT JOIN tcrt_main.teams AS t ON t.id = m.team_id
                ORDER BY n.map_id ASC, n.id ASC
                """
            )
            rows = [dict(row) for row in cursor.fetchall()]
    finally:
        # Closing a non-autocommit connection ends the read-only snapshot
        # without crossing the project's managed rollback boundary.
        connection.close()
    if not rows:
        raise RebuildError("Remote MySQL returned no USM nodes")
    return rows


def build_canonical_payloads(
    rows: Sequence[dict[str, Any]],
    *,
    synced_at: str,
) -> list[dict[str, Any]]:
    from app.services.knowledge.usm_payload import build_usm_payload

    for row in rows:
        required_source_values = {
            "map_id": row.get("map_id"),
            "node_id": row.get("node_id"),
            "map_name": row.get("map_name"),
            "team_id": row.get("team_id"),
            "team_name": row.get("team_name"),
        }
        missing = [
            name
            for name, value in required_source_values.items()
            if value is None or (isinstance(value, str) and not value.strip())
        ]
        if missing:
            raise RebuildError(
                "Remote MySQL row has missing map/team identity fields: "
                f"{sorted(missing)}"
            )
    payloads = [build_usm_payload(row, synced_at=synced_at) for row in rows]
    entity_keys = [str(payload["entity_key"]) for payload in payloads]
    if len(entity_keys) != len(set(entity_keys)):
        raise RebuildError("Remote MySQL contains duplicate composite entity keys")
    return payloads


def payload_checksum(payloads: Sequence[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for payload in sorted(payloads, key=lambda item: str(item["entity_key"])):
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest.update(encoded)
        digest.update(b"\n")
    return digest.hexdigest()


async def _collection_names(client: AsyncQdrantClient) -> set[str]:
    response = await client.get_collections()
    return {collection.name for collection in response.collections}


async def _aliases(client: AsyncQdrantClient) -> dict[str, str]:
    response = await client.get_aliases()
    return {alias.alias_name: alias.collection_name for alias in response.aliases}


async def inspect_target(state: TargetState) -> None:
    physical = await _collection_names(state.client)
    aliases = await _aliases(state.client)
    logical = state.logical_collection
    if logical in aliases:
        state.original_is_alias = True
        state.original_alias_target = aliases[logical]
    elif logical not in physical:
        raise RebuildError(f"{state.url}: collection {logical!r} does not exist")
    for generated_name in (state.backup_collection, state.shadow_collection):
        if generated_name in physical or generated_name in aliases:
            raise RebuildError(f"{state.url}: generated collection already exists")
    count = await state.client.count(collection_name=logical, exact=True)
    state.original_count = int(count.count)
    info = await state.client.get_collection(collection_name=logical)
    vectors = info.config.params.vectors
    size = getattr(vectors, "size", None)
    if size is None:
        raise RebuildError(f"{state.url}: named or unsupported vector config")


async def copy_collection_points(
    client: AsyncQdrantClient,
    source: str,
    destination: str,
) -> int:
    """Copy every point, payload, and vector into an existing collection."""
    offset: Any | None = None
    copied = 0
    while True:
        records, offset = await client.scroll(
            collection_name=source,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        if records:
            points = [
                qmodels.PointStruct(
                    id=record.id,
                    vector=record.vector,
                    payload=record.payload or {},
                )
                for record in records
            ]
            await client.upsert(
                collection_name=destination,
                points=points,
                wait=True,
            )
            copied += len(points)
        if offset is None:
            return copied


async def clone_collection(state: TargetState) -> None:
    source = state.logical_collection
    destination = state.backup_collection
    info = await state.client.get_collection(collection_name=source)
    vectors = info.config.params.vectors
    on_disk_payload = bool(getattr(info.config.params, "on_disk_payload", True))
    await state.client.create_collection(
        collection_name=destination,
        vectors_config=vectors,
        on_disk_payload=on_disk_payload,
    )
    copied = await copy_collection_points(state.client, source, destination)
    backup_count = await state.client.count(
        collection_name=destination,
        exact=True,
    )
    if copied != state.original_count or int(backup_count.count) != state.original_count:
        raise RebuildError(
            f"{state.url}: backup count mismatch "
            f"({backup_count.count} != {state.original_count})"
        )


async def create_canonical_collection(
    client: AsyncQdrantClient,
    collection: str,
    dimensions: int,
) -> None:
    await client.create_collection(
        collection_name=collection,
        vectors_config=qmodels.VectorParams(
            size=dimensions,
            distance=qmodels.Distance.COSINE,
            on_disk=True,
        ),
        on_disk_payload=True,
    )
    for field_name, field_schema in CANONICAL_INDEXES.items():
        await client.create_payload_index(
            collection_name=collection,
            field_name=field_name,
            field_schema=field_schema,
            wait=True,
        )


async def create_shadow(state: TargetState, dimensions: int) -> None:
    await create_canonical_collection(
        state.client,
        state.shadow_collection,
        dimensions,
    )


async def load_shadows(
    states: Sequence[TargetState],
    payloads: Sequence[dict[str, Any]],
    settings: EmbeddingSettings,
) -> None:
    from app.config import EmbeddingConfig
    from app.services.knowledge.embedding_service import EmbeddingService
    from app.services.knowledge.usm_payload import usm_point_id

    service = EmbeddingService(
        EmbeddingConfig(
            provider=settings.provider,
            model=settings.model,
            dimensions=settings.dimensions,
            api_key=settings.api_key,
            base_url=settings.base_url,
            batch_size=settings.batch_size,
            concurrency=settings.concurrency,
            cache_path=settings.cache_path,
        )
    )
    try:
        window = settings.batch_size * max(1, settings.concurrency)
        for start in range(0, len(payloads), window):
            batch = payloads[start : start + window]
            vectors = await service.embed_batch([str(payload["text"]) for payload in batch])
            if len(vectors) != len(batch):
                raise RebuildError("Embedding provider returned an incomplete batch")
            points = [
                qmodels.PointStruct(
                    id=usm_point_id(payload["map_id"], payload["node_id"]),
                    vector=vector,
                    payload=dict(payload),
                )
                for payload, vector in zip(batch, vectors)
            ]
            await asyncio.gather(
                *(
                    state.client.upsert(
                        collection_name=state.shadow_collection,
                        points=points,
                        wait=True,
                    )
                    for state in states
                )
            )
            print(f"Embedded and loaded {min(start + len(batch), len(payloads))}/{len(payloads)}")
    finally:
        await service.close()


async def read_collection_payloads(
    client: AsyncQdrantClient,
    collection: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    point_ids: list[str] = []
    payloads: list[dict[str, Any]] = []
    offset: Any | None = None
    while True:
        records, offset = await client.scroll(
            collection_name=collection,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for record in records:
            point_ids.append(str(record.id))
            payloads.append(dict(record.payload or {}))
        if offset is None:
            break
    return point_ids, payloads


async def validate_collection(
    state: TargetState,
    collection: str,
    *,
    expected_point_ids: set[str],
    expected_checksum: str,
    expected_count: int,
    dimensions: int,
) -> None:
    info = await state.client.get_collection(collection_name=collection)
    vectors = info.config.params.vectors
    if getattr(vectors, "size", None) != dimensions:
        raise RebuildError(f"{state.url}: vector dimensions mismatch")
    payload_schema = getattr(info, "payload_schema", {}) or {}
    missing_indexes = set(CANONICAL_INDEXES) - set(payload_schema)
    if missing_indexes:
        raise RebuildError(
            f"{state.url}: missing payload indexes {sorted(missing_indexes)}"
        )
    point_ids, payloads = await read_collection_payloads(state.client, collection)
    if len(point_ids) != expected_count or len(set(point_ids)) != expected_count:
        raise RebuildError(f"{state.url}: point count or point-id uniqueness mismatch")
    if set(point_ids) != expected_point_ids:
        raise RebuildError(f"{state.url}: deterministic point IDs mismatch")
    for payload in payloads:
        missing_fields = REQUIRED_PAYLOAD_FIELDS - set(payload)
        if missing_fields:
            raise RebuildError(
                f"{state.url}: payload missing fields {sorted(missing_fields)}"
            )
        if payload.get("schema_version") != "usm_node_v2":
            raise RebuildError(f"{state.url}: unexpected payload schema version")
    if payload_checksum(payloads) != expected_checksum:
        raise RebuildError(f"{state.url}: payload checksum mismatch")


def _create_alias_operation(
    collection_name: str,
    alias_name: str,
) -> qmodels.CreateAliasOperation:
    return qmodels.CreateAliasOperation(
        create_alias=qmodels.CreateAlias(
            collection_name=collection_name,
            alias_name=alias_name,
        )
    )


def _delete_alias_operation(alias_name: str) -> qmodels.DeleteAliasOperation:
    return qmodels.DeleteAliasOperation(
        delete_alias=qmodels.DeleteAlias(alias_name=alias_name)
    )


async def point_logical_alias(state: TargetState, collection: str) -> None:
    aliases = await _aliases(state.client)
    operations: list[qmodels.CreateAliasOperation | qmodels.DeleteAliasOperation] = []
    if state.logical_collection in aliases:
        operations.append(_delete_alias_operation(state.logical_collection))
    operations.append(_create_alias_operation(collection, state.logical_collection))
    await state.client.update_collection_aliases(
        change_aliases_operations=operations
    )


async def remove_logical_name(state: TargetState) -> None:
    aliases = await _aliases(state.client)
    if state.logical_collection in aliases:
        await state.client.update_collection_aliases(
            change_aliases_operations=[
                _delete_alias_operation(state.logical_collection)
            ]
        )
        return
    physical = await _collection_names(state.client)
    if state.logical_collection in physical:
        await state.client.delete_collection(
            collection_name=state.logical_collection
        )


async def switch_target(state: TargetState, dimensions: int) -> None:
    """Materialize the validated shadow as the physical canonical collection."""
    try:
        await remove_logical_name(state)
        await create_canonical_collection(
            state.client,
            state.logical_collection,
            dimensions,
        )
        copied = await copy_collection_points(
            state.client,
            state.shadow_collection,
            state.logical_collection,
        )
        shadow_count = await state.client.count(
            collection_name=state.shadow_collection,
            exact=True,
        )
        if copied != int(shadow_count.count):
            raise RebuildError(
                f"{state.url}: physical cutover count mismatch "
                f"({copied} != {shadow_count.count})"
            )
    except Exception:
        await remove_logical_name(state)
        try:
            await point_logical_alias(state, state.backup_collection)
        finally:
            state.switched = False
        raise
    state.switched = True


async def rollback_target(state: TargetState) -> None:
    await remove_logical_name(state)
    await point_logical_alias(state, state.backup_collection)
    state.switched = False


async def validate_physical_canonical(state: TargetState) -> None:
    physical = await _collection_names(state.client)
    aliases = await _aliases(state.client)
    if state.logical_collection not in physical:
        raise RebuildError(
            f"{state.url}: {state.logical_collection!r} is not a physical collection"
        )
    if state.logical_collection in aliases:
        raise RebuildError(
            f"{state.url}: {state.logical_collection!r} still exists as an alias"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mysql-host", default="10.81.0.13")
    parser.add_argument("--mysql-port", type=int, default=3306)
    parser.add_argument("--mysql-user", default="tcrt_user")
    parser.add_argument(
        "--mysql-password-env",
        default="TCRT_USM_MYSQL_PASSWORD",
        help="Environment variable containing the password (value is never logged)",
    )
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument(
        "--qdrant-target",
        action="append",
        dest="qdrant_targets",
        help="Repeat for each Qdrant base URL; defaults to local and 10.81.1.49",
    )
    parser.add_argument("--collection", default="usm_nodes")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--yes",
        action="store_true",
        help=(
            "Authorize backups, shadow writes, removal of the old logical name, "
            "and physical collection materialization"
        ),
    )
    return parser


async def run(args: argparse.Namespace) -> int:
    from app.services.knowledge.usm_payload import usm_point_id, utc_now_rfc3339

    if args.mysql_port <= 0 or args.mysql_port > 65535:
        raise RebuildError("MySQL port must be between 1 and 65535")
    targets = tuple(args.qdrant_targets or DEFAULT_QDRANT_TARGETS)
    if len(targets) != 2 or len(set(targets)) != 2:
        raise RebuildError("Exactly two distinct Qdrant targets are required")
    safe_targets = [_safe_target(target) for target in targets]
    settings = load_embedding_settings(args.env_file)
    password = resolve_mysql_password(args.mysql_password_env)
    print(
        f"Reading remote MySQL {args.mysql_host}:{args.mysql_port} as {args.mysql_user} "
        "in a read-only transaction"
    )
    rows = fetch_remote_usm_nodes(
        host=args.mysql_host,
        port=args.mysql_port,
        username=args.mysql_user,
        password=password,
    )
    synced_at = utc_now_rfc3339()
    payloads = build_canonical_payloads(rows, synced_at=synced_at)
    expected_checksum = payload_checksum(payloads)
    expected_point_ids = {
        usm_point_id(payload["map_id"], payload["node_id"])
        for payload in payloads
    }
    if len(expected_point_ids) != len(payloads):
        raise RebuildError("Deterministic point IDs are not unique")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    api_key = os.getenv("QDRANT_API_KEY", "")
    states = [
        TargetState(
            url=safe_url,
            client=AsyncQdrantClient(
                url=target,
                api_key=api_key or None,
                timeout=60,
            ),
            logical_collection=args.collection,
            backup_collection=f"{args.collection}__backup__{run_id}",
            shadow_collection=f"{args.collection}__v2__{run_id}",
        )
        for target, safe_url in zip(targets, safe_targets)
    ]
    try:
        await asyncio.gather(*(inspect_target(state) for state in states))
        print(
            f"Source rows={len(payloads)}, schema=usm_node_v2, "
            f"dimensions={settings.dimensions}, checksum={expected_checksum[:12]}…"
        )
        for state in states:
            source_kind = "alias" if state.original_is_alias else "physical collection"
            print(
                f"Target {state.url}: current={state.original_count} ({source_kind}), "
                f"backup={state.backup_collection}, shadow={state.shadow_collection}"
            )
        if not mutation_authorized(dry_run=args.dry_run, yes=args.yes):
            print("Dry run complete; no Qdrant data was mutated.")
            return 0

        for state in states:
            print(f"Backing up {state.url}…")
            await clone_collection(state)
            await create_shadow(state, settings.dimensions)

        await load_shadows(states, payloads, settings)
        for state in states:
            await validate_collection(
                state,
                state.shadow_collection,
                expected_point_ids=expected_point_ids,
                expected_checksum=expected_checksum,
                expected_count=len(payloads),
                dimensions=settings.dimensions,
            )
            print(f"Validated shadow on {state.url}")

        switched: list[TargetState] = []
        try:
            for state in states:
                await switch_target(state, settings.dimensions)
                switched.append(state)
                await validate_collection(
                    state,
                    state.logical_collection,
                    expected_point_ids=expected_point_ids,
                    expected_checksum=expected_checksum,
                    expected_count=len(payloads),
                    dimensions=settings.dimensions,
                )
                await validate_physical_canonical(state)
                print(f"Materialized and validated physical collection on {state.url}")
        except Exception:
            for state in reversed(switched):
                await rollback_target(state)
                print(f"Rolled back {state.url} to {state.backup_collection}")
            raise

        print(
            "Both targets now expose a physical usm_nodes collection with "
            "the validated usm_node_v2 dataset."
        )
        for state in states:
            print(
                f"Retained on {state.url}: backup={state.backup_collection}, "
                f"shadow={state.shadow_collection}"
            )
        return 0
    finally:
        await asyncio.gather(*(state.client.close() for state in states))


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(run(args))
    except (RebuildError, pymysql.MySQLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
