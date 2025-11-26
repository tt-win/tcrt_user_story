
import asyncio
import sys
import os
import requests
import json
from datetime import datetime
from typing import List, Dict, Any
from qdrant_client import QdrantClient
from qdrant_client.http import models

# 將專案根目錄加入 sys.path
sys.path.insert(0, os.getcwd())

from app.database import SessionLocal
from app.models.user_story_map_db import USMAsyncSessionLocal
from app.models.database_models import User, Team
from app.auth.models import UserRole
from app.api.llm_context import get_test_cases_context, get_usm_context
from sqlalchemy import select

# 設定
TEXT_EMBEDDING_URL = "http://127.0.0.1:1234/v1/embeddings"
QDRANT_URL = "http://localhost:6333"
VECTOR_SIZE = 768
COLLECTION_NAME_TC = "test_cases"
COLLECTION_NAME_USM = "usm_nodes"

# 模擬使用者
class MockUser:
    id = 1
    username = "mock_admin"
    role = UserRole.SUPER_ADMIN

async def get_embeddings(texts: List[str]) -> List[List[float]]:
    """呼叫 Text Embedding API"""
    if not texts:
        return []
    
    try:
        # 一次最多處理 32 筆，避免超過 token 限制或 timeout
        batch_size = 32
        all_embeddings = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            print(f"  Embedding batch {i//batch_size + 1}/{(len(texts)+batch_size-1)//batch_size} ({len(batch)} items)...")
            
            payload = {
                "input": batch,
                "model": "text-embedding-nomic-embed-text-v1.5" # 根據實際模型名稱調整，或讓 server 決定
            }
            response = requests.post(TEXT_EMBEDDING_URL, json=payload)
            response.raise_for_status()
            data = response.json()
            
            # OpenAI format: data['data'][i]['embedding']
            embeddings = [item['embedding'] for item in data['data']]
            all_embeddings.extend(embeddings)
            
        return all_embeddings
    except Exception as e:
        print(f"Embedding failed: {e}")
        return []

def init_qdrant(client: QdrantClient):
    """初始化 Qdrant Collections"""
    for collection_name in [COLLECTION_NAME_TC, COLLECTION_NAME_USM]:
        try:
            client.get_collection(collection_name)
            print(f"Collection '{collection_name}' exists.")
        except Exception:
            print(f"Creating collection '{collection_name}'...")
            client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=VECTOR_SIZE,
                    distance=models.Distance.COSINE
                )
            )

async def process_test_cases(db, current_user, qdrant_client, team_id):
    print("\n[Test Cases] Fetching data...")
    tc_resp = await get_test_cases_context(
        team_id=team_id,
        since=None,
        limit=5000, # 一次取多一點
        db=db,
        current_user=current_user
    )
    
    items = tc_resp.items
    if not items:
        print("[Test Cases] No data found.")
        return

    print(f"[Test Cases] Found {len(items)} items. Generating embeddings...")
    texts = [item.text for item in items]
    vectors = await get_embeddings(texts)
    
    if not vectors:
        print("[Test Cases] Failed to generate embeddings.")
        return

    print(f"[Test Cases] Upserting to Qdrant...")
    points = []
    for i, item in enumerate(items):
        # Metadata 處理：Qdrant payload 支援 dict
        payload = item.metadata.copy()
        payload["text"] = item.text
        payload["resource_type"] = item.resource_type
        payload["updated_at"] = item.updated_at.isoformat() if item.updated_at else None
        
        # 使用 record_id 的 hash 作為 point ID (或直接用 int id 如果是純數字)
        # 這裡簡單用 UUID
        import uuid
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"tc_{item.id}"))
        
        points.append(models.PointStruct(
            id=point_id,
            vector=vectors[i],
            payload=payload
        ))

    qdrant_client.upsert(
        collection_name=COLLECTION_NAME_TC,
        points=points
    )
    print(f"[Test Cases] Successfully indexed {len(points)} documents.")

async def process_usm_nodes(usm_db, db, current_user, qdrant_client, team_id):
    print("\n[USM Nodes] Fetching data...")
    usm_resp = await get_usm_context(
        team_id=team_id,
        map_id=None,
        since=None,
        usm_db=usm_db,
        db=db,
        current_user=current_user
    )
    
    items = usm_resp.items
    if not items:
        print("[USM Nodes] No data found.")
        return

    print(f"[USM Nodes] Found {len(items)} items. Generating embeddings...")
    texts = [item.text for item in items]
    vectors = await get_embeddings(texts)
    
    if not vectors:
        print("[USM Nodes] Failed to generate embeddings.")
        return

    print(f"[USM Nodes] Upserting to Qdrant...")
    points = []
    for i, item in enumerate(items):
        payload = item.metadata.copy()
        payload["text"] = item.text
        payload["resource_type"] = item.resource_type
        payload["updated_at"] = item.updated_at.isoformat() if item.updated_at else None
        
        import uuid
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"usm_{item.id}"))
        
        points.append(models.PointStruct(
            id=point_id,
            vector=vectors[i],
            payload=payload
        ))

    qdrant_client.upsert(
        collection_name=COLLECTION_NAME_USM,
        points=points
    )
    print(f"[USM Nodes] Successfully indexed {len(points)} documents.")

async def main():
    print("=== RAG ETL POC Script ===")
    
    # 1. Setup Qdrant
    try:
        qdrant = QdrantClient(url=QDRANT_URL)
        init_qdrant(qdrant)
    except Exception as e:
        print(f"Failed to connect to Qdrant at {QDRANT_URL}: {e}")
        return

    # 2. Setup DB Sessions
    db = SessionLocal()
    usm_db = USMAsyncSessionLocal()
    current_user = MockUser()

    try:
        # 3. Get Team
        result = await db.execute(select(Team).limit(1))
        team = result.scalars().first()
        if not team:
            print("No team found.")
            return
        
        print(f"Target Team: {team.name} (ID: {team.id})")

        # 4. Process Data
        await process_test_cases(db, current_user, qdrant, team.id)
        await process_usm_nodes(usm_db, db, current_user, qdrant, team.id)

    finally:
        await db.close()
        await usm_db.close()
        print("\nDone.")

if __name__ == "__main__":
    asyncio.run(main())
