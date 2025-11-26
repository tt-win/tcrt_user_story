import requests
import json
import uuid
from qdrant_client import QdrantClient
from qdrant_client.http import models
from typing import List, Dict, Optional
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.markdown import Markdown
from rich.live import Live

import sys

# 設定
LLM_API_URL = "https://openrouter.ai/api/v1/chat/completions"
LLM_MODEL = "x-ai/grok-4.1-fast:free"  # OpenRouter 模型
OPENROUTER_API_KEY = "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"

TEXT_EMBEDDING_URL = "http://127.0.0.1:1234/v1/embeddings"
QDRANT_URL = "http://localhost:6333"
COLLECTION_TC = "test_cases"
COLLECTION_USM = "usm_nodes"
TOP_K = 20  # 檢索筆數
SCORE_THRESHOLD = None # 相似度門檻

# 團隊關鍵字對照表 (大寫)
TEAM_KEYWORDS = ["ARD", "CRD", "PCD", "GPD", "TAD", "OPD", "GED", "CCD", "UAD", "UMD", "PMD", "WSD"]

# 資源類型關鍵字
RESOURCE_KEYWORDS = {
    "test_case": ["測試案例", "TEST CASE", "測項", "TC", "TESTCASE"],
    "usm_node": ["需求", "REQUIREMENT", "SPEC", "規格", "USER STORY", "USM", "FEATURE", "功能"]
}

# 初始化 Qdrant
client = QdrantClient(url=QDRANT_URL)
console = Console()

def get_llm_headers():
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:9999",  # Optional
        "X-Title": "TCRT RAG CLI"                 # Optional
    }

def get_embedding(text: str) -> List[float]:
    """取得查詢語句的向量"""
    try:
        payload = {
            "input": text,
            "model": "text-embedding-bge-m3"
        }
        response = requests.post(TEXT_EMBEDDING_URL, json=payload)
        response.raise_for_status()
        data = response.json()
        return data['data'][0]['embedding']
    except Exception as e:
        print(f"Embedding Error: {e}")
        return []

def detect_team_intent(query: str) -> Optional[models.Filter]:
    """從問題中偵測團隊關鍵字，並產生 Qdrant Filter"""
    query_upper = query.upper()
    detected_teams = []
    
    for team in TEAM_KEYWORDS:
        # 簡單的字串比對，實際專案可用 NER
        if team in query_upper:
            detected_teams.append(team)
            
    if not detected_teams:
        return None
        
    print(f"✨ 偵測到團隊意圖: {detected_teams}")
    
    # 構造 Filter: team_name 必須符合其中之一
    return models.Filter(
        must=[
            models.FieldCondition(
                key="team_name",
                match=models.MatchAny(any=detected_teams)
            )
        ]
    )

def detect_resource_intent(query: str) -> List[str]:
    """偵測查詢涉及的資源類型 (test_case, usm_node)"""
    query_upper = query.upper()
    detected_types = []
    
    # 檢查 Test Case 關鍵字
    for kw in RESOURCE_KEYWORDS["test_case"]:
        if kw in query_upper:
            detected_types.append("test_case")
            break
            
    # 檢查 USM 關鍵字
    for kw in RESOURCE_KEYWORDS["usm_node"]:
        if kw in query_upper:
            detected_types.append("usm_node")
            break
            
    # 如果都沒偵測到或都偵測到，則回傳全部
    if not detected_types:
        return ["test_case", "usm_node"]
        
    print(f"✨ 偵測到資源意圖: {detected_types}")
    return detected_types

def search_qdrant(query_vector: List[float], query_filter: Optional[models.Filter] = None, resource_types: List[str] = None) -> List[Dict]:
    """搜尋 Qdrant 資料庫"""
    results = []
    
    if resource_types is None:
        resource_types = ["test_case", "usm_node"]
    
    try:
        # 搜尋 Test Cases (使用 query_points API)
        if "test_case" in resource_types:
            tc_response = client.query_points(
                collection_name=COLLECTION_TC,
                query=query_vector,
                query_filter=query_filter,
                limit=TOP_K,
                with_payload=True,
                score_threshold=SCORE_THRESHOLD
            )
            
            for hit in tc_response.points:
                results.append({
                    "type": "Test Case",
                    "score": hit.score,
                    "text": hit.payload.get("text", ""),
                    "source": f"{hit.payload.get('test_case_number')} (Team: {hit.payload.get('team_name')})",
                    "payload": hit.payload
                })

        # 搜尋 USM Nodes (使用 query_points API)
        if "usm_node" in resource_types:
            usm_response = client.query_points(
                collection_name=COLLECTION_USM,
                query=query_vector,
                query_filter=query_filter,
                limit=TOP_K,
                with_payload=True,
                score_threshold=SCORE_THRESHOLD
            )
            
            for hit in usm_response.points:
                results.append({
                    "type": "USM Node",
                    "score": hit.score,
                    "text": hit.payload.get("text", ""),
                    "source": f"{hit.payload.get('map_name')} > {hit.payload.get('title')}",
                    "payload": hit.payload
                })        
        # 混合排序
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:TOP_K] # 只取最相關的前 K 筆
        
    except Exception as e:
        print(f"Search Error: {e}")
        import traceback
        traceback.print_exc()
        return []

def retrieve_points_by_ids(collection_name: str, point_ids: List[str]) -> List[Dict]:
    """根據 ID 直接獲取 Qdrant Points"""
    if not point_ids:
        return []
    try:
        points = client.retrieve(
            collection_name=collection_name,
            ids=point_ids,
            with_payload=True
        )
        
        results = []
        for p in points:
            source = ""
            if collection_name == COLLECTION_USM:
                source = f"[子節點] {p.payload.get('title', 'Unknown')}"
            else:
                source = f"[關聯測項] {p.payload.get('test_case_number', 'Unknown')}"
                
            results.append({
                "type": "Expanded Context",
                "score": 1.0, # 結構性關聯，視為滿分
                "text": p.payload.get("text", ""),
                "source": source,
                "payload": p.payload
            })
        return results
    except Exception as e:
        print(f"Retrieve Error ({collection_name}): {e}")
        return []

def search_test_cases_by_tickets(tickets: List[str]) -> List[Dict]:
    """根據 Ticket Number 搜尋測試案例 (用於 JIRA <-> Test Case 關聯)"""
    if not tickets:
        return []
        
    try:
        # 構造 Filter: tcg_tickets 包含任一 ticket
        # 注意：Payload 中的 tcg_tickets 是 List[str]
        # Qdrant filter for array contains any:
        # key: "tcg_tickets", match: {any: tickets}
        
        response = client.scroll(
            collection_name=COLLECTION_TC,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="tcg_tickets",
                        match=models.MatchAny(any=tickets)
                    )
                ]
            ),
            limit=10, # 限制擴展數量
            with_payload=True
        )
        
        points = response[0] # scroll returns (points, offset)
        
        results = []
        for p in points:
            results.append({
                "type": "Expanded Context",
                "score": 1.0,
                "text": p.payload.get("text", ""),
                "source": f"[JIRA關聯] {p.payload.get('test_case_number')}",
                "payload": p.payload
            })
        return results
    except Exception as e:
        print(f"Search by Ticket Error: {e}")
        return []

def expand_search_results(initial_results: List[Dict]) -> List[Dict]:
    """智慧擴展：根據搜尋結果進行結構性延伸"""
    expanded_results = list(initial_results) # 複製一份
    existing_sources = set(r['source'] for r in initial_results)
    
    print("\n⚡️ 進行結構性擴展...")
    
    for result in initial_results:
        # 只針對 USM Node 進行擴展
        if result['type'] != "USM Node":
            continue
            
        # 從原始 Payload (如果有的話) 獲取 ID
        # 我們需要修改 search_qdrant 讓它把 payload 也帶出來，或者重新 fetch
        # 為了方便，我們先假設 search_qdrant 回傳的 dict 裡沒有 payload
        # 所以這裡是一個優化點：修改 search_qdrant 回傳 payload
        
        # 暫時解法：如果 result 裡有 payload 欄位
        payload = result.get('payload')
        if not payload:
            continue
            
        # 1. 擴展子節點 (Children)
        children_ids = payload.get('children_ids', [])
        map_id = payload.get('map_id')
        
        if children_ids and map_id:
            # 構造 Qdrant Point IDs for Children
            # ID 規則: uuid5(NAMESPACE_URL, f"usm_{map_id}:{node_id}")
            child_point_ids = []
            for cid in children_ids:
                pid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"usm_{map_id}:{cid}"))
                child_point_ids.append(pid)
            
            children_points = retrieve_points_by_ids(COLLECTION_USM, child_point_ids)
            for cp in children_points:
                if cp['source'] not in existing_sources:
                    expanded_results.append(cp)
                    existing_sources.add(cp['source'])
                    print(f"  + 加入子節點: {cp['source']}")

        # 2. 擴展關聯測試案例 (Via JIRA Tickets)
        jira_tickets = payload.get('jira_tickets', [])
        if jira_tickets:
            tc_points = search_test_cases_by_tickets(jira_tickets)
            for tcp in tc_points:
                if tcp['source'] not in existing_sources:
                    expanded_results.append(tcp)
                    existing_sources.add(tcp['source'])
                    print(f"  + 加入測試案例: {tcp['source']}")
                    
    return expanded_results

def rewrite_query(user_query: str, history: List[Dict]) -> str:
    """根據對話歷史改寫使用者的查詢"""
    if not history:
        return user_query
        
    # 取最近 3 輪對話作為參考
    recent_history = history[-6:]
    
    system_prompt = """你是一個查詢改寫助手。你的任務是根據對話歷史，將使用者的最新問題改寫為一個「完整」、「獨立」且「包含所有必要上下文」的查詢語句，以便用於資料庫檢索。 
    
    規則：
    1. 如果問題依賴上下文（例如使用「它」、「這個功能」），請還原為具體的名詞。
    2. 如果問題是關於特定團隊或專案，請保留這些關鍵字。
    3. 只輸出改寫後的查詢語句，不要輸出其他解釋。
    4. 如果問題已經很完整，則原樣輸出。
    """
    
    messages = [{"role": "system", "content": system_prompt}]
    # 將歷史對話加入 messages，但過濾掉 system role
    for msg in recent_history:
        if msg["role"] != "system":
            messages.append(msg)
            
    messages.append({"role": "user", "content": user_query})
    
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 200,
        "stream": False
    }
    
    try:
        # print("  (正在改寫查詢...)") # Debug
        response = requests.post(LLM_API_URL, json=payload, headers=get_llm_headers())
        response.raise_for_status()
        data = response.json()
        rewritten = data['choices'][0]['message']['content'].strip()
        if rewritten and rewritten != user_query:
            print(f"  ➡️ 改寫查詢: {rewritten}")
            return rewritten
        return user_query
    except Exception as e:
        print(f"Rewrite Error: {e}")
        return user_query

def query_llm(user_query: str, context_items: List[Dict], history: List[Dict]) -> List[Dict]:
    """呼叫 LLM 生成回答，並更新對話歷史"""
    
    # 組裝 Context
    context_str = ""
    for i, item in enumerate(context_items):
        # 決定顯示用的 ID
        payload = item.get("payload", {})
        if item['type'] == 'Test Case':
            ref_id = payload.get("test_case_number", f"TC-{i+1}")
        elif item['type'] == 'USM Node':
            ref_id = payload.get("title", f"USM-{i+1}")
        else:
            ref_id = f"Ref-{i+1}"
            
        context_str += f"--- 資料來源 ID: {ref_id} ({item['type']}) ---\n{item['text']}\n\n"

    system_prompt = """你是一個專業的 QA 測試助手。請根據提供的參考資料回答使用者的問題。

原則：
1. 若參考資料中有答案，請用 Markdown 格式（列表、表格、粗體）清晰呈現，讓閱讀者一目瞭然。
2. 盡量結構化你的回答，例如：「功能摘要」、「詳細步驟」、「預期結果」。
3. 若參考資料中沒有答案，請直接說不知道，不要編造內容。
4. 回答請保持簡潔、專業。
5. **引用來源時，請務必在句尾標註來源 ID，例如：(來源: TCG-123) 或 (來源: Login Feature)。**"""

    # 構建本次請求的 Messages
    # 1. System Prompt (包含 Context)
    # 注意：Context 放在 System Prompt 中通常效果較好，或是放在 User Prompt 的最前面
    # 這裡我們採取：System Prompt 固定，User Prompt 包含 Context + Question
    
    # 為了節省 Token，我們不把所有 History 都帶上 Context，只帶上對話紀錄
    # 但 Context 必須是針對「當前問題」的，所以 Context 應該放在最新的 User Message 中
    
    current_messages = [{"role": "system", "content": system_prompt}]
    
    # 加入歷史對話 (不含 Context，只含問答)
    # 為了避免 Context 污染歷史紀錄，歷史紀錄只存純文字問答
    for msg in history:
        current_messages.append(msg)
        
    # 加入當前問題 (含 Context)
    current_messages.append({
        "role": "user", 
        "content": f"參考資料：\n{context_str}\n\n問題：{user_query}"
    })

    payload = {
        "model": LLM_MODEL,
        "messages": current_messages,
        "temperature": 0.3,
        "max_tokens": -1,
        "stream": True
    }

    full_answer = ""
    
    try:
        print("\n" + "="*50)
        console.print("[bold blue]🤖 AI 回答：[/bold blue]\n")
        
        response = requests.post(LLM_API_URL, json=payload, stream=True, headers=get_llm_headers())
        response.raise_for_status()

        with Live(Markdown(""), refresh_per_second=10, console=console) as live:
            for line in response.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line.startswith('data: '):
                        content = line[6:]
                        if content == '[DONE]':
                            break
                        try:
                            chunk = json.loads(content)
                            if 'choices' in chunk and len(chunk['choices']) > 0:
                                delta = chunk['choices'][0].get('delta', {})
                                if 'content' in delta:
                                    full_answer += delta['content']
                                    live.update(Markdown(full_answer))
                        except json.JSONDecodeError:
                            pass
        print("\n" + "="*50 + "\n")
        
        # 更新歷史紀錄
        # 注意：User History 存的是「原始問題」，不是改寫後的，也不是含 Context 的
        new_history = list(history)
        new_history.append({"role": "user", "content": user_query})
        new_history.append({"role": "assistant", "content": full_answer})
        
        return new_history

    except Exception as e:
        print(f"\033[1;31mLLM Error: {e}\033[0m")
        return history

def main():
    print("=== TCRT 需求問答器 (RAG + Context) ===")
    print("操作說明：")
    print(" - 輸入問題後，按 [Option+Enter] 或 [Esc] [Enter] 送出")
    print(" - 輸入 'exit', 'quit' 離開")
    print(" - 輸入 'clear' 清除對話歷史\n")

    history: List[Dict] = []
    
    # 設定 prompt_toolkit
    bindings = KeyBindings()

    @bindings.add('c-d')
    def _(event):
        event.app.exit()

    session = PromptSession(multiline=True, key_bindings=bindings)

    while True:
        try:
            query = session.prompt("User> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        
        if not query:
            continue
            
        if query.lower() in ['exit', 'quit']:
            break
        if query.lower() == 'clear':
            history = []
            print("對話歷史已清除。")
            continue

        # 1. 改寫查詢 (Query Rewriting)
        search_query = rewrite_query(query, history)

        print(f"\n🔍 搜尋相關資料中... ('{search_query}')")
        vector = get_embedding(search_query)
        if not vector:
            continue

        # 2. 意圖識別與過濾 (使用改寫後的查詢)
        query_filter = detect_team_intent(search_query)
        resource_types = detect_resource_intent(search_query)
        results = search_qdrant(vector, query_filter, resource_types)
        
        if not results:
            print("找不到相關資料。")
            continue

        # 3. 智慧擴展 (Recursive Retrieval)
        results = expand_search_results(results)

        console.print(f"\n[bold green]🔍 找到 {len(results)} 筆相關資料，正在生成回答...[/bold green]")
        
        # Optional: 顯示找到的參考資料標題 (用灰色顯示詳細資訊)
        for i, r in enumerate(results):
            score_color = "yellow" if r['score'] > 0.7 else "white"
            
            # 決定顯示用的 ID
            payload = r.get("payload", {})
            if r['type'] == 'Test Case':
                ref_id = payload.get("test_case_number", f"TC-{i+1}")
            elif r['type'] == 'USM Node':
                ref_id = payload.get("title", f"USM-{i+1}")
            else:
                ref_id = f"Ref-{i+1}"
                
            console.print(f"  [cyan]{i+1}.[/cyan] [{score_color}]{r['score']:.4f}[/{score_color}] [bold]{ref_id}[/bold] - {r['source']}")

        # 4. 生成回答並更新歷史
        history = query_llm(query, results, history)

if __name__ == "__main__":
    main()
