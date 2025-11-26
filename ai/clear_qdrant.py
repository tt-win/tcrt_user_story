import sys
from qdrant_client import QdrantClient

# 設定
QDRANT_URL = "http://localhost:6333"
COLLECTIONS = ["test_cases", "usm_nodes"]

def clear_collections():
    print("=== Clearing Qdrant Collections ===")
    try:
        client = QdrantClient(url=QDRANT_URL)
        
        for name in COLLECTIONS:
            try:
                client.get_collection(name)
                print(f"Deleting collection '{name}'...")
                client.delete_collection(name)
                print(f"Collection '{name}' deleted.")
            except Exception as e:
                # 如果集合不存在，get_collection 會拋錯，這是正常的
                print(f"Collection '{name}' not found or already deleted. ({e})")
                
        print("\nAll target collections cleared.")
        
    except Exception as e:
        print(f"Failed to connect to Qdrant: {e}")

if __name__ == "__main__":
    clear_collections()