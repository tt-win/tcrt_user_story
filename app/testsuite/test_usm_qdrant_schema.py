"""Canonical USM Qdrant schema and guarded-rebuild unit tests."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from qdrant_client.http import models as qmodels

from app.config import QdrantConfig
from app.services.knowledge.qdrant_client import QdrantKnowledgeClient
from app.services.knowledge.usm_payload import (
    build_usm_embedding_text,
    build_usm_payload,
    usm_entity_key,
    usm_point_id,
)
from scripts.rebuild_qdrant_usm_nodes import (
    CANONICAL_INDEXES,
    REQUIRED_PAYLOAD_FIELDS,
    RebuildError,
    TargetState,
    _safe_target,
    build_canonical_payloads,
    mutation_authorized,
    payload_checksum,
    rollback_target,
    switch_target,
    validate_physical_canonical,
)


def _node(map_id: int = 29, node_id: str = "node-1") -> dict:
    return {
        "map_id": map_id,
        "node_id": node_id,
        "title": "Checkout",
        "description": None,
        "node_type": "user_story",
        "map_name": "Shopping Journey",
        "team_id": 12,
        "team_name": "Storefront",
        "parent_id": "feature-1",
        "level": 2,
        "children_ids": '["child-1", "child-1", ""]',
        "related_ids": [
            {"map_id": 30, "node_id": "related-1"},
            {"map_id": 30, "node_id": "related-1"},
            "related-local",
        ],
        "as_a": "buyer",
        "i_want": "to pay",
        "so_that": "my order is placed",
        "jira_tickets": '["TCG-1", "TCG-1"]',
        "updated_at": datetime(2026, 7, 22, 3, 4, 5),
    }


def test_composite_identity_prevents_cross_map_collision() -> None:
    assert usm_entity_key(1, "shared") == "1:shared"
    assert usm_point_id(1, "shared") != usm_point_id(2, "shared")
    assert usm_point_id(1, "shared") == usm_point_id(1, "shared")


def test_build_usm_payload_emits_complete_type_stable_schema() -> None:
    payload = build_usm_payload(_node(), synced_at="2026-07-29T01:02:03Z")

    assert set(payload) == REQUIRED_PAYLOAD_FIELDS
    assert payload["schema_version"] == "usm_node_v2"
    assert payload["resource_type"] == "usm_node"
    assert payload["source"] == "tcrt_usm_mysql"
    assert payload["entity_key"] == "29:node-1"
    assert payload["parent_key"] == "29:feature-1"
    assert payload["children_ids"] == ["child-1"]
    assert payload["children_keys"] == ["29:child-1"]
    assert payload["related_node_ids"] == ["related-1", "related-local"]
    assert payload["related_node_keys"] == [
        "30:related-1",
        "29:related-local",
    ]
    assert payload["jira_tickets"] == ["TCG-1"]
    assert payload["description"] == ""
    assert payload["updated_at"] == "2026-07-22T03:04:05Z"
    assert payload["last_synced_at"] == "2026-07-29T01:02:03Z"


def test_embedding_text_has_deterministic_field_order() -> None:
    text = build_usm_embedding_text(_node())
    assert text.splitlines() == [
        "地圖: Shopping Journey",
        "類型: user_story",
        "標題: Checkout",
        "As a: buyer",
        "I want: to pay",
        "So that: my order is placed",
        "Jira: TCG-1",
    ]


def test_rebuild_payload_checksum_is_source_order_independent() -> None:
    synced_at = "2026-07-29T01:02:03Z"
    first = build_canonical_payloads(
        [_node(1, "same"), _node(2, "same")],
        synced_at=synced_at,
    )
    second = build_canonical_payloads(
        [_node(2, "same"), _node(1, "same")],
        synced_at=synced_at,
    )
    assert payload_checksum(first) == payload_checksum(second)


def test_rebuild_rejects_missing_map_or_team_relationship() -> None:
    row = _node()
    row["team_name"] = ""
    with pytest.raises(RebuildError, match="missing map/team identity"):
        build_canonical_payloads([row], synced_at="2026-07-29T01:02:03Z")


def test_rebuild_requires_explicit_confirmation_and_redacts_target() -> None:
    assert mutation_authorized(dry_run=True, yes=False) is False
    assert mutation_authorized(dry_run=False, yes=True) is True
    with pytest.raises(RebuildError, match="requires --yes"):
        mutation_authorized(dry_run=False, yes=False)
    assert _safe_target("http://user:secret@db.example:6333/path?q=token") == (
        "http://db.example:6333"
    )


@pytest.mark.asyncio
async def test_cutover_materializes_physical_canonical_collection() -> None:
    fake = AsyncMock()
    fake.get_aliases = AsyncMock(
        return_value=SimpleNamespace(
            aliases=[
                SimpleNamespace(
                    alias_name="usm_nodes",
                    collection_name="usm_nodes__v2__run",
                )
            ]
        )
    )
    fake.scroll = AsyncMock(
        return_value=(
            [
                SimpleNamespace(
                    id="ec36c8ee-f012-5d99-a9c4-c658caf5b2af",
                    vector=[0.1, 0.2, 0.3, 0.4],
                    payload={"schema_version": "usm_node_v2"},
                )
            ],
            None,
        )
    )
    fake.count = AsyncMock(return_value=SimpleNamespace(count=1))
    state = TargetState(
        url="http://qdrant.example:6333",
        client=fake,
        logical_collection="usm_nodes",
        backup_collection="usm_nodes__backup__run",
        shadow_collection="usm_nodes__v2__run",
    )

    await switch_target(state, 4)

    assert fake.create_collection.await_args.kwargs["collection_name"] == "usm_nodes"
    assert fake.upsert.await_args.kwargs["collection_name"] == "usm_nodes"
    delete_operations = fake.update_collection_aliases.await_args.kwargs[
        "change_aliases_operations"
    ]
    assert delete_operations[0].delete_alias.alias_name == "usm_nodes"
    assert len(fake.create_payload_index.await_args_list) == len(CANONICAL_INDEXES)
    assert state.switched is True


@pytest.mark.asyncio
async def test_cutover_rollback_repoints_logical_alias_to_backup() -> None:
    fake = AsyncMock()
    fake.get_aliases = AsyncMock(
        side_effect=[
            SimpleNamespace(
                aliases=[
                    SimpleNamespace(
                        alias_name="usm_nodes",
                        collection_name="usm_nodes__v2__run",
                    )
                ]
            ),
            SimpleNamespace(aliases=[]),
        ]
    )
    state = TargetState(
        url="http://qdrant.example:6333",
        client=fake,
        logical_collection="usm_nodes",
        backup_collection="usm_nodes__backup__run",
        shadow_collection="usm_nodes__v2__run",
        switched=True,
    )

    await rollback_target(state)

    delete_operations = fake.update_collection_aliases.await_args_list[0].kwargs[
        "change_aliases_operations"
    ]
    create_operations = fake.update_collection_aliases.await_args_list[1].kwargs[
        "change_aliases_operations"
    ]
    assert delete_operations[0].delete_alias.alias_name == "usm_nodes"
    assert create_operations[0].create_alias.alias_name == "usm_nodes"
    assert (
        create_operations[0].create_alias.collection_name
        == "usm_nodes__backup__run"
    )
    assert state.switched is False


@pytest.mark.asyncio
async def test_failed_materialization_restores_verified_source_alias() -> None:
    fake = AsyncMock()
    fake.get_aliases = AsyncMock(
        side_effect=[
            SimpleNamespace(
                aliases=[
                    SimpleNamespace(
                        alias_name="usm_nodes",
                        collection_name="usm_nodes__v2__run",
                    )
                ]
            ),
            SimpleNamespace(aliases=[]),
            SimpleNamespace(aliases=[]),
        ]
    )
    fake.get_collections = AsyncMock(
        return_value=SimpleNamespace(collections=[])
    )
    fake.create_collection = AsyncMock(side_effect=RuntimeError("create failed"))
    state = TargetState(
        url="http://qdrant.example:6333",
        client=fake,
        logical_collection="usm_nodes",
        backup_collection="usm_nodes__v2__run",
        shadow_collection="usm_nodes__v2__run",
    )

    with pytest.raises(RuntimeError, match="create failed"):
        await switch_target(state, 4)

    create_operations = fake.update_collection_aliases.await_args_list[-1].kwargs[
        "change_aliases_operations"
    ]
    assert create_operations[0].create_alias.alias_name == "usm_nodes"
    assert (
        create_operations[0].create_alias.collection_name
        == "usm_nodes__v2__run"
    )
    assert state.switched is False


@pytest.mark.asyncio
async def test_physical_canonical_validation_rejects_alias() -> None:
    fake = AsyncMock()
    fake.get_collections = AsyncMock(
        return_value=SimpleNamespace(
            collections=[SimpleNamespace(name="usm_nodes")]
        )
    )
    fake.get_aliases = AsyncMock(return_value=SimpleNamespace(aliases=[]))
    state = TargetState(
        url="http://qdrant.example:6333",
        client=fake,
        logical_collection="usm_nodes",
        backup_collection="usm_nodes__backup__run",
        shadow_collection="usm_nodes__v2__run",
    )

    await validate_physical_canonical(state)

    fake.get_aliases.return_value = SimpleNamespace(
        aliases=[
            SimpleNamespace(
                alias_name="usm_nodes",
                collection_name="usm_nodes__v2__run",
            )
        ]
    )
    with pytest.raises(RebuildError, match="still exists as an alias"):
        await validate_physical_canonical(state)


@pytest.mark.asyncio
async def test_qdrant_collection_is_on_disk_and_indexes_missing_fields() -> None:
    wrapper = QdrantKnowledgeClient(QdrantConfig(url="http://localhost:6333"))
    fake = AsyncMock()
    fake.get_collection = AsyncMock(
        return_value=SimpleNamespace(
            payload_schema={"entity_key": SimpleNamespace()}
        )
    )
    wrapper._client = fake

    await wrapper.create_collection("usm", 1024)
    create_kwargs = fake.create_collection.await_args.kwargs
    assert create_kwargs["on_disk_payload"] is True
    assert create_kwargs["vectors_config"].on_disk is True

    await wrapper.ensure_usm_payload_indexes("usm")
    created_fields = {
        call.kwargs["field_name"]
        for call in fake.create_payload_index.await_args_list
    }
    assert created_fields == set(CANONICAL_INDEXES) - {"entity_key"}
    assert all(
        isinstance(call.kwargs["field_schema"], qmodels.PayloadSchemaType)
        for call in fake.create_payload_index.await_args_list
    )
