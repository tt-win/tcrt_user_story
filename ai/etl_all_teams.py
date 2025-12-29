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
from urllib.parse import urlparse, parse_qs
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
from app.services.lark_client import LarkClient
from app.services.jira_client import JiraClient
from sqlalchemy import select

# 設定
TEXT_EMBEDDING_URL = "http://127.0.0.1:1234/v1/embeddings"
QDRANT_URL = "http://localhost:6333"
VECTOR_SIZE = 1024
COLLECTION_NAME_TC = "test_cases"
COLLECTION_NAME_USM = "usm_nodes"
COLLECTION_NAME_JIRA_REF = "jira_references"
BATCH_SIZE = 50  # 每次處理並寫入 Qdrant 的筆數，避免 Timeout
JIRA_BATCH_SIZE = 50
LARK_REFERENCE_TABLE_URL = "https://igxy0zaeo1r.sg.larksuite.com/wiki/S93iwK3FhiyHNkkvKcilnRkngpg?fromScene=spaceOverview&table=tblCfk9WQ4psypJi"
LARK_REFERENCE_TICKET_FIELD = "TCG Tickets"


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

async def get_embeddings(texts: List[str]) -> List[List[float]]:
    """呼叫 Text Embedding API"""
    if not texts:
        return []
    
    try:
        payload = {
            "input": texts,
            "model": "text-embedding-bge-m3"
        }
        response = requests.post(TEXT_EMBEDDING_URL, json=payload)
        response.raise_for_status()
        data = response.json()
        
        embeddings = [item['embedding'] for item in data['data']]
        return embeddings
    except Exception as e:
        print(f"    [Error] Embedding failed: {e}")
        return []

def parse_lark_table_url(url: str) -> Optional[Dict[str, str]]:
    parsed = urlparse(url)
    wiki_token = None
    table_id = None

    match = re.search(r"/wiki/(?P<wiki_token>[^/]+)/table/(?P<table_id>[^/]+)", parsed.path)
    if match:
        wiki_token = match.group("wiki_token")
        table_id = match.group("table_id")
    else:
        match = re.search(r"/wiki/(?P<wiki_token>[^/]+)", parsed.path)
        if match:
            wiki_token = match.group("wiki_token")
        query = parse_qs(parsed.query or "")
        table_id = query.get("table", [None])[0]

    if not wiki_token or not table_id:
        return None
    return {"wiki_token": wiki_token, "table_id": table_id}

def dedupe_preserve_order(values: List[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if not value:
            continue
        normalized = value.strip().upper()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result

def flatten_lark_field(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        candidates = []
        for key in ("text", "link", "name", "display_name"):
            v = value.get(key)
            if isinstance(v, str) and v.strip():
                candidates.append(v)
        text_arr = value.get("text_arr")
        if isinstance(text_arr, list):
            for item in text_arr:
                if isinstance(item, str) and item.strip():
                    candidates.append(item)
        return candidates
    if isinstance(value, list):
        candidates = []
        for item in value:
            candidates.extend(flatten_lark_field(item))
        return candidates
    try:
        return [str(value)]
    except Exception:
        return []

def extract_tcg_tickets(field_value: Any) -> List[str]:
    candidates = flatten_lark_field(field_value)
    tickets = []
    for candidate in candidates:
        if not candidate:
            continue
        matches = re.findall(r"TCG-\d+", candidate.upper())
        if matches:
            tickets.extend(matches)
    if not tickets:
        for candidate in candidates:
            if not candidate:
                continue
            for part in re.split(r"[,\n]", candidate):
                normalized = part.strip().upper()
                if normalized.startswith("TCG-"):
                    tickets.append(normalized)
    return dedupe_preserve_order(tickets)

def parse_component_name(name: str) -> Dict[str, str]:
    if not name:
        return {"raw": "", "team": "", "product": ""}
    raw = name.strip()
    if not raw:
        return {"raw": "", "team": "", "product": ""}
    parts = raw.split()
    team_token = parts[0].strip().replace(".", "")
    team = team_token.upper() if team_token else ""
    product = " ".join(parts[1:]).strip()
    return {"raw": raw, "team": team, "product": product}

def normalize_jira_description(raw_value: Any) -> str:
    if raw_value is None:
        return ""
    if isinstance(raw_value, str):
        return raw_value.strip()
    if isinstance(raw_value, (dict, list)):
        text = extract_adf_text(raw_value)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
    return str(raw_value).strip()

def extract_adf_text(node: Any) -> str:
    if node is None:
        return ""
    if isinstance(node, list):
        return "".join(extract_adf_text(child) for child in node)
    if isinstance(node, dict):
        node_type = node.get("type")
        if node_type == "text":
            return node.get("text", "")
        content = node.get("content", [])
        text = "".join(extract_adf_text(child) for child in content)
        if node_type in ("paragraph", "heading", "listItem"):
            return text + "\n"
        return text
    return str(node)

def parse_jira_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

def fetch_lark_tcg_tickets(lark_client: LarkClient, table_id: str) -> List[str]:
    records = lark_client.get_all_records(table_id)
    tickets = []
    for record in records:
        fields = record.get("fields", {}) or {}
        raw_value = (
            fields.get(LARK_REFERENCE_TICKET_FIELD)
            or fields.get("TCG Number")
            or fields.get("TCG")
            or fields.get("TCG Ticket")
        )
        tickets.extend(extract_tcg_tickets(raw_value))
    return dedupe_preserve_order(tickets)

def build_jira_reference_item(ticket_key: str, fields: Dict[str, Any]) -> EmbeddingItem:
    title = (fields.get("summary") or "").strip()
    description = normalize_jira_description(fields.get("description"))
    components_raw = fields.get("components") or []
    component_names = [c.get("name") for c in components_raw if isinstance(c, dict) and c.get("name")]
    parsed_components = [parse_component_name(name) for name in component_names]
    component_primary = parsed_components[0] if parsed_components else {"raw": "", "team": "", "product": ""}
    updated_at = parse_jira_datetime(fields.get("updated"))

    text_parts = [
        f"標題: {title or '-'}",
        f"JIRA: {ticket_key}",
        f"Component: {component_primary.get('raw') or '-'}",
        f"Component Team: {component_primary.get('team') or '-'}",
        f"Component Product: {component_primary.get('product') or '-'}",
        f"描述: {description or '-'}"
    ]
    if len(component_names) > 1:
        text_parts.append(f"Components: {', '.join(component_names)}")

    metadata = {
        "title": title,
        "jira_ticket": ticket_key,
        "component": component_primary.get("raw"),
        "component_team": component_primary.get("team"),
        "component_product": component_primary.get("product"),
        "components": component_names,
        "components_parsed": parsed_components,
        "source": "lark_tcg_reference"
    }

    return EmbeddingItem(
        id=ticket_key,
        resource_type="jira_reference",
        text="\n".join(text_parts),
        metadata=metadata,
        updated_at=updated_at
    )

def fetch_jira_reference_items(jira_client: JiraClient, ticket_keys: List[str]) -> List[EmbeddingItem]:
    if not ticket_keys:
        return []
    normalized_keys = dedupe_preserve_order(ticket_keys)
    items = []

    for i in range(0, len(normalized_keys), JIRA_BATCH_SIZE):
        batch = normalized_keys[i : i + JIRA_BATCH_SIZE]
        jql = f"issuekey in ({','.join(batch)})"
        issues = jira_client.search_issues(
            jql,
            fields=["summary", "description", "components", "updated"],
            max_results=len(batch)
        )
        issue_map = {
            (issue.get("key") or "").upper(): issue
            for issue in issues if isinstance(issue, dict)
        }

        missing = [key for key in batch if key not in issue_map]
        if missing:
            print(f"  [JIRA References] Missing {len(missing)} tickets in JIRA: {', '.join(missing)}")

        for key in batch:
            issue = issue_map.get(key)
            if not issue:
                continue
            fields = issue.get("fields", {}) or {}
            items.append(build_jira_reference_item(key, fields))

    return items

async def process_jira_reference(qdrant_client: QdrantClient):
    print("\nProcessing JIRA References from Lark table...")
    parsed = parse_lark_table_url(LARK_REFERENCE_TABLE_URL)
    if not parsed:
        print("  [JIRA References] Invalid Lark table URL, skip.")
        return
    if not settings.lark.app_id or not settings.lark.app_secret:
        print("  [JIRA References] Lark config missing (app_id/app_secret), skip.")
        return

    lark_client = LarkClient(settings.lark.app_id, settings.lark.app_secret)
    if not lark_client.set_wiki_token(parsed["wiki_token"]):
        print("  [JIRA References] Failed to set Lark wiki token, skip.")
        return

    tickets = await asyncio.to_thread(fetch_lark_tcg_tickets, lark_client, parsed["table_id"])
    if not tickets:
        print("  [JIRA References] No tickets found in Lark table.")
        return

    jira_client = JiraClient()
    reference_items = await asyncio.to_thread(fetch_jira_reference_items, jira_client, tickets)
    await process_items_in_batches(qdrant_client, COLLECTION_NAME_JIRA_REF, reference_items, "JIRA References")

def init_qdrant(client: QdrantClient):
    """初始化 Qdrant Collections"""
    for collection_name in [COLLECTION_NAME_TC, COLLECTION_NAME_USM, COLLECTION_NAME_JIRA_REF]:
        try:
            client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=VECTOR_SIZE,
                    distance=models.Distance.COSINE
                )
            )
            print(f"Created collection '{collection_name}'.")
        except Exception as e:
            msg = str(e).lower()
            if "already exists" in msg or "409" in msg:
                print(f"Collection '{collection_name}' exists.")
                continue
            print(f"Failed to ensure collection '{collection_name}': {e}")
            raise

async def process_items_in_batches(qdrant_client, collection_name, items, description_prefix):
    """通用的分批處理與寫入函式"""
    if not items:
        print(f"  [{description_prefix}] No data found.")
        return

    total_items = len(items)
    print(f"  [{description_prefix}] Found {total_items} items. Processing in batches of {BATCH_SIZE}...")
    
    success_count = 0
    
    for i in range(0, total_items, BATCH_SIZE):
        batch_items = items[i : i + BATCH_SIZE]
        batch_texts = [item.text for item in batch_items]
        
        print(f"    Processing batch {i//BATCH_SIZE + 1}/{(total_items + BATCH_SIZE - 1)//BATCH_SIZE} ({len(batch_items)} items)...", end="", flush=True)
        
        # 1. Get Embeddings
        vectors = await get_embeddings(batch_texts)
        
        if not vectors:
            print(" Failed to get embeddings. Skipping batch.")
            continue
            
        if len(vectors) != len(batch_items):
            print(f" Mismatch vectors count ({len(vectors)}) vs items ({len(batch_items)}). Skipping batch.")
            continue

        # 2. Prepare Qdrant Points
        points = []
        for j, item in enumerate(batch_items):
            payload = item.metadata.copy()
            payload["text"] = item.text
            payload["resource_type"] = item.resource_type
            payload["updated_at"] = item.updated_at.isoformat() if item.updated_at else None
            
            # Deterministic UUID based on resource type and ID
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{collection_name}_{item.id}"))
            
            points.append(models.PointStruct(
                id=point_id,
                vector=vectors[j],
                payload=payload
            ))

        # 3. Upsert to Qdrant
        try:
            qdrant_client.upsert(
                collection_name=collection_name,
                points=points,
                wait=False # Async upsert to speed up
            )
            success_count += len(points)
            print(" Done.")
        except Exception as e:
            print(f" Failed to upsert to Qdrant: {e}")

    print(f"  [{description_prefix}] Completed. Indexed {success_count}/{total_items} items.")

async def process_team(team, db, usm_db, current_user, qdrant_client):
    print(f"\nProcessing Team: {team.name} (ID: {team.id})")
    
    # 1. Process Test Cases
    try:
        tc_resp = await get_test_cases_context(
            team_id=team.id,
            since=None,
            limit=10000, # 增加 limit 以確保抓取完整資料，後續會分批處理
            db=db,
            current_user=current_user
        )
        await process_items_in_batches(qdrant_client, COLLECTION_NAME_TC, tc_resp.items, "Test Cases")
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
            current_user=current_user
        )
        await process_items_in_batches(qdrant_client, COLLECTION_NAME_USM, usm_resp.items, "USM Nodes")
    except Exception as e:
        print(f"  [USM Nodes] Error fetching data: {e}")

async def main():
    print("=== Full RAG ETL Script (Batched Upsert) ===")
    
    # 1. Setup Qdrant
    try:
        qdrant = QdrantClient(url=QDRANT_URL, timeout=60) # 增加 client timeout
        init_qdrant(qdrant)
    except Exception as e:
        print(f"Failed to connect to Qdrant at {QDRANT_URL}: {e}")
        return

    # 2. Process JIRA reference data
    try:
        await process_jira_reference(qdrant)
    except Exception as e:
        print(f"  [JIRA References] Error fetching data: {e}")

    # 3. Setup DB Sessions
    db = SessionLocal()
    usm_db = USMAsyncSessionLocal()
    current_user = MockUser()

    try:
        # 4. Get All Teams
        result = await db.execute(select(Team))
        teams = result.scalars().all()
        
        if not teams:
            print("No teams found.")
            return
        
        print(f"Found {len(teams)} teams. Starting processing...")

        # 5. Process Each Team
        for team in teams:
            await process_team(team, db, usm_db, current_user, qdrant)

    finally:
        await db.close()
        await usm_db.close()
        print("\nAll tasks completed.")

if __name__ == "__main__":
    asyncio.run(main())
