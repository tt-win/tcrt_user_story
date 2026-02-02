import asyncio
import sys
import os
import requests
import json
import uuid
import re
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Any, Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models

# 將專案根目錄加入 sys.path
sys.path.insert(0, os.getcwd())

from app.database import SessionLocal
from app.models.user_story_map_db import USMAsyncSessionLocal
from app.models.database_models import User, Team
from app.auth.models import UserRole
from app.api.llm_context import get_test_cases_context, get_usm_context
from app.config import settings
from sqlalchemy import select

# 設定
OPENROUTER_EMBEDDING_URL = "https://openrouter.ai/api/v1/embeddings"
OPENROUTER_API_KEY = settings.openrouter.api_key
QDRANT_URL = "http://localhost:6333"
VECTOR_SIZE = 1024
COLLECTION_NAME_TC = "test_cases"
COLLECTION_NAME_USM = "usm_nodes"
BATCH_SIZE = 50  # 每次處理並寫入 Qdrant 的筆數，避免 Timeout


@dataclass
class EmbeddingItem:
    id: str
    resource_type: str
    text: str
    metadata: Dict[str, Any]
    updated_at: Optional[datetime]


# 模擬使用者
class MockUser:
    id = 1
    username = "mock_admin"
    role = UserRole.SUPER_ADMIN


def get_openrouter_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": settings.app.get_base_url(),
        "X-Title": "TCRT ETL",
    }


async def get_embeddings(texts: List[str]) -> List[List[float]]:
    """呼叫 Text Embedding API"""
    if not texts:
        return []
    if not OPENROUTER_API_KEY:
        print("    [Error] OPENROUTER_API_KEY is not set.")
        return []

    try:
        payload = {"input": texts, "model": "baai/bge-m3"}
        response = requests.post(
            OPENROUTER_EMBEDDING_URL, json=payload, headers=get_openrouter_headers()
        )
        response.raise_for_status()
        data = response.json()

        embeddings = [item["embedding"] for item in data["data"]]
        return embeddings
    except Exception as e:
        print(f"    [Error] Embedding failed: {e}")
        return []


def init_qdrant(client: QdrantClient):
    """初始化 Qdrant Collections"""
    for collection_name in [
        COLLECTION_NAME_TC,
        COLLECTION_NAME_USM,
    ]:
        try:
            client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=VECTOR_SIZE, distance=models.Distance.COSINE
                ),
            )
            print(f"Created collection '{collection_name}'.")
        except Exception as e:
            msg = str(e).lower()
            if "already exists" in msg or "409" in msg:
                print(f"Collection '{collection_name}' exists.")
                continue
            print(f"Failed to ensure collection '{collection_name}': {e}")
            raise


async def process_items_in_batches(
    qdrant_client, collection_name, items, description_prefix
):
    """通用的分批處理與寫入函式"""
    if not items:
        print(f"  [{description_prefix}] No data found.")
        return

    total_items = len(items)
    print(
        f"  [{description_prefix}] Found {total_items} items. Processing in batches of {BATCH_SIZE}..."
    )

    success_count = 0

    for i in range(0, total_items, BATCH_SIZE):
        batch_items = items[i : i + BATCH_SIZE]
        batch_texts = [item.text for item in batch_items]

        print(
            f"    Processing batch {i // BATCH_SIZE + 1}/{(total_items + BATCH_SIZE - 1) // BATCH_SIZE} ({len(batch_items)} items)...",
            end="",
            flush=True,
        )

        # 1. Get Embeddings
        vectors = await get_embeddings(batch_texts)

        if not vectors:
            print(" Failed to get embeddings. Skipping batch.")
            continue

        if len(vectors) != len(batch_items):
            print(
                f" Mismatch vectors count ({len(vectors)}) vs items ({len(batch_items)}). Skipping batch."
            )
            continue

        # 2. Prepare Qdrant Points
        points = []
        for j, item in enumerate(batch_items):
            payload = item.metadata.copy()
            payload["text"] = item.text
            payload["resource_type"] = item.resource_type
            payload["updated_at"] = (
                item.updated_at.isoformat() if item.updated_at else None
            )

            # Deterministic UUID based on resource type and ID
            point_id = str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"{collection_name}_{item.id}")
            )

            points.append(
                models.PointStruct(id=point_id, vector=vectors[j], payload=payload)
            )

        # 3. Upsert to Qdrant
        try:
            qdrant_client.upsert(
                collection_name=collection_name,
                points=points,
                wait=False,  # Async upsert to speed up
            )
            success_count += len(points)
            print(" Done.")
        except Exception as e:
            print(f" Failed to upsert to Qdrant: {e}")

    print(
        f"  [{description_prefix}] Completed. Indexed {success_count}/{total_items} items."
    )


async def process_team(team, db, usm_db, current_user, qdrant_client):
    print(f"\nProcessing Team: {team.name} (ID: {team.id})")

    # 1. Process Test Cases
    try:
        tc_resp = await get_test_cases_context(
            team_id=team.id,
            since=None,
            limit=10000,  # 增加 limit 以確保抓取完整資料，後續會分批處理
            db=db,
            current_user=current_user,
        )
        await process_items_in_batches(
            qdrant_client, COLLECTION_NAME_TC, tc_resp.items, "Test Cases"
        )
    except Exception as e:
        print(f"  [Test Cases] Error fetching data: {e}")

    # 2. Process USM Nodes
    try:
        usm_resp = await get_usm_context(
            team_id=team.id,
            map_id=None,
            since=None,
            usm_db=usm_db,
            db=db,
            current_user=current_user,
        )
        await process_items_in_batches(
            qdrant_client, COLLECTION_NAME_USM, usm_resp.items, "USM Nodes"
        )
    except Exception as e:
        print(f"  [USM Nodes] Error fetching data: {e}")


async def main():
    print("=== Full RAG ETL Script (Batched Upsert) ===")

    # 1. Setup Qdrant
    try:
        qdrant = QdrantClient(url=QDRANT_URL, timeout=60)  # 增加 client timeout
        init_qdrant(qdrant)
    except Exception as e:
        print(f"Failed to connect to Qdrant at {QDRANT_URL}: {e}")
        return

    # 2. Setup DB Sessions
    db = SessionLocal()
    usm_db = USMAsyncSessionLocal()
    current_user = MockUser()

    try:
        # 3. Get All Teams
        result = await db.execute(select(Team))
        teams = result.scalars().all()

        if not teams:
            print("No teams found.")
            return

        print(f"Found {len(teams)} teams. Starting processing...")

        # 4. Process Each Team
        for team in teams:
            await process_team(team, db, usm_db, current_user, qdrant)

    finally:
        await db.close()
        await usm_db.close()
        print("\nAll tasks completed.")


if __name__ == "__main__":
    asyncio.run(main())
