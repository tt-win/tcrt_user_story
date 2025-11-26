
import sys
import os
from qdrant_client import QdrantClient

# 設定
QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME_TC = "test_cases"
COLLECTION_NAME_USM = "usm_nodes"

def inspect_collection(client, collection_name, limit=3):
    print(f"\n=== Inspecting Collection: {collection_name} ===")
    try:
        # 獲取集合資訊
        info = client.get_collection(collection_name)
        print(f"Status: {info.status}")
        # print(f"Vectors Count: {info.vectors_count}") # Removed in newer client
        print(f"Points Count: {info.points_count}")
        
        # 隨機抽樣 (使用 scroll)
        print(f"\n--- Sample Points (Limit: {limit}) ---")
        result = client.scroll(
            collection_name=collection_name,
            limit=limit,
            with_payload=True,
            with_vectors=False  # 不顯示向量數據以免刷屏
        )
        
        points = result[0] # scroll 返回 tuple (points, next_page_offset) 
        
        if not points:
            print("No points found.")
            return

        for p in points:
            print(f"\nID: {p.id}")
            print("Payload:")
            for k, v in p.payload.items():
                # 針對長文本做截斷顯示
                val_str = str(v)
                if len(val_str) > 100:
                    val_str = val_str[:100] + "..."
                print(f"  - {k}: {val_str}")
                
    except Exception as e:
        print(f"Error inspecting collection '{collection_name}': {e}")

def main():
    try:
        client = QdrantClient(url=QDRANT_URL)
        inspect_collection(client, COLLECTION_NAME_TC)
        inspect_collection(client, COLLECTION_NAME_USM)
    except Exception as e:
        print(f"Failed to connect to Qdrant: {e}")

if __name__ == "__main__":
    main()
