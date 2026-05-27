## Context

Automation Hub 既有掃描流程位於 `app/services/automation/smart_scan_service.py` 與 `app/services/automation/script_service.py`：

- `_extract_test_metadata` 已使用 Python AST 解析 `FunctionDef` / `AsyncFunctionDef` / `ClassDef` 名稱，回傳 `EntryPoint.test_names` — 但只取函式名，未走訪 decorator
- JS/TS 走 regex `\b(?:test(?:\.(?:describe|only|skip))?|it|describe)\s*\(\s*['"]([^'"]+)['"]`，只擷取字串名稱
- `automation_script_case_links` 表是檔案級 M2M，`UniqueConstraint(automation_script_id, test_case_id)`、`note TEXT`、`created_by VARCHAR(64)`
- `AutomationRun` 表也是檔案/suite 級（`automation_script_id` FK），per-test pass/fail 在外部 Allure server，TCRT 端不存
- UI 端 `app/static/js/automation-hub/suites/main.js` 與 `smart-scan/main.js` 從未渲染 `test_names`

本 change 在這些既存設施上加掛 marker 解析、derived link 同步、view 切換與建議式 AI 連結。

關鍵約束：
- 不引入新表（spike 結論：run report 是檔案級，per-test entity 沒有對應的 status data 可顯示）
- 不破壞既有 link 表的 unique key（`automation_script_id, test_case_id`）
- AI 走既有 OpenRouter integration（與 smart-scan LLM enrichment 共用 `get_settings().openrouter.api_key`），不新增供應商
- Skill `tools/skills/tcrt-automation-pomify/` 同步義務在 spec 已強制

## Goals / Non-Goals

**Goals:**

1. 測試碼可用 marker 自宣告對應 manual test case，且 marker 是 link 表的 derived source of truth（搭配人類手建覆寫機制）
2. 掃描結果暴露 test 函式層級資訊，UI 可在「Script view（檔案中心）」與「Test view（函式中心）」間切換
3. AI 連結建議是「輔助使用者決定」的角色，不自動寫入 link
4. 變更對既有 API、DB、UI 路徑為 additive，無破壞性遷移

**Non-Goals:**

1. ❌ 不引入 per-test entity 表（`automation_script_tests` 等）
2. ❌ 不在這個 change 內 ingest Allure JSON、不顯示 per-test pass/fail
3. ❌ 不支援檔案 sidecar YAML / docstring 標頭 marker（兩種主流文法已涵蓋使用情境）
4. ❌ 不做 marker → manual case 自動建立（marker 指向不存在的 TC 只警告，不創 case）
5. ❌ AI 不會在沒有人類確認下寫入 link，也不會自動套用 PRIMARY link_type

## Decisions

### D1. Marker 文法精確語法

**決定**：Python 走 pytest decorator，JS/TS 走註解，且兩者語意保持對齊。

**Python（PYTEST、PLAYWRIGHT_PY_ASYNC）：**

```python
@pytest.mark.tcrt("TC-001")                          # 單 case，link_type=COVERS（預設）
@pytest.mark.tcrt("TC-001", "TC-005")                # 多 case
@pytest.mark.tcrt("TC-001", link_type="primary")     # 指定 link_type
@pytest.mark.tcrt("TC-001", "TC-005", link_type="references")
def test_login_happy(): ...
```

- `link_type` 接受字串 `"primary"` / `"covers"` / `"references"`（case-insensitive，對應 `AutomationScriptLinkType` enum）
- TC id 必須是 `^[A-Za-z0-9_-]+$` 的非空字串
- 一個 test 函式上可疊加多個 `@pytest.mark.tcrt(...)`，視為多個 marker hit
- 同一 marker 內 TC 共用同一 `link_type`；要不同 `link_type` 請拆成多個 marker

**JS/TS（PLAYWRIGHT_JS、含 .spec.ts/.test.js）：**

```typescript
// tcrt: TC-001
test('login happy', ...);

// tcrt: TC-001, TC-005
test('login multi', ...);

// tcrt: TC-001 primary
// tcrt: TC-005 covers
test('login mixed', ...);
```

- 註解規則：`// tcrt: <TC-list> [link_type]?`，多個 TC 以 `,` 分隔
- 必須**緊鄰** `test(...)` / `it(...)` / `describe(...)` 之上（中間只允許空行與其他 `// tcrt:` 註解）
- 允許在同一 test 上堆疊多行 `// tcrt:`（如示範第三段）
- `link_type` 缺省為 `covers`

**Rejected alternatives:**

- *Docstring 標頭* (`"""TCRT: TC-001"""`)：易與 docstring 混用，解析語意含糊
- *YAML sidecar* (`test_login.tcrt.yml`)：rename 同步成本高，使用者要維護兩個檔
- *純註解（連 Python 也用）*：放棄 pytest 生態優勢（無法用 `pytest -m tcrt` 篩選、無法被 IDE 識別）

### D2. Marker 解析器擴充點

**決定**：擴充 `smart_scan_service._extract_test_metadata`，回傳結構從 `list[str]` 升級為 `list[TestEntry]`，向上層回傳 marker 解析結果。

```python
@dataclass
class TestEntry:
    name: str                       # 函式名 / test() 字串
    kind: str                       # "function" | "class" | "js_test"
    line: int                       # 起始行（給 conflict 訊息用）
    docstring: str | None           # AI 建議要送的 prompt 輸入
    markers: list[MarkerHit]        # 解析出的 marker 集

@dataclass
class MarkerHit:
    tc_ids: list[str]               # ["TC-001", "TC-005"]
    link_type: str                  # "primary" | "covers" | "references"
    source_line: int                # marker 在原檔的行號
    raw: str                        # 原始文字（debug 用）
```

`EntryPoint.test_names: list[str]` 保留以保持 API 向下相容；同時新增 `EntryPoint.test_entries: list[TestEntry]` 與 `EntryPoint.marker_links: list[dict]`。

**Python 解析**（AST）：
- 走訪 `FunctionDef.decorator_list` / `AsyncFunctionDef.decorator_list`
- 比對 `ast.Attribute(value=ast.Attribute(value=ast.Name(id='pytest'), attr='mark'), attr='tcrt')` 或 `ast.Call` 的 func 結構
- 從 `ast.Call.args` 與 `keywords` 萃取 TC 與 `link_type`
- 解析失敗（非字面量、表達式）→ 記入 warnings，不算 marker hit

**JS/TS 解析**（行對位 regex）：
- 先用既有 regex 找到所有 `test()` / `it()` / `describe()` 的起始行
- 對每個 test，往上掃直到非空非註解行；蒐集 `// tcrt: ...` 行
- 解析 marker payload：`/^\/\/\s*tcrt:\s*(.+)$/` 後處理 comma split 與 link_type 後綴

**安全網**：解析錯誤（語法錯、token 不合法）一律 fail-open — 不阻擋掃描、記入 `warnings[]`、回傳該 entry 的 `markers=[]`。

### D3. Derived link sync 策略 + 衝突解決（解 Q1）

**決定**：人類手建 link 永遠勝過 marker；marker 衝突時保留人類版本並把 marker 結果列入 warnings 由使用者決定。

`AutomationScriptService.sync()` 在掃完檔案後的補充階段：

```
for entry_point in entry_points:
    for marker in entry_point.markers:
        for tc_id in marker.tc_ids:
            existing = find_link(script_id, tc_id)
            if existing is None:
                create_link(script_id, tc_id, marker.link_type,
                            created_by="marker-sync",
                            note=JSON{test_name, line, marker_raw})
            elif existing.created_by == "marker-sync":
                # 之前由 marker 同步建立，可重寫 link_type 與 note
                if existing.link_type != marker.link_type:
                    update_link(existing, marker.link_type, new_note)
            else:
                # 人類或 AI confirm 建立過 → 不動
                if existing.link_type != marker.link_type:
                    warnings.append({type: "link_type_conflict",
                                     script_id, tc_id,
                                     human_link_type, marker_link_type})

# 清理：曾由 marker 建、現在 marker 已不存在的 link
for link in find_links(script_id, created_by="marker-sync"):
    if (script_id, link.tc_id) not in marker_pairs:
        delete_link(link)
```

**`created_by` 欄位 sentinel 值**：

- `"marker-sync"` — derived from code marker
- `"ai-suggest:<user_id>"` — AI 建議被使用者確認時寫入
- `<user_id>` 純數字字串 — 人類手動建立（既有行為）

**人類 vs marker 衝突**（link_type 不同）：

- DB 層保留人類版本不動
- Scan response `warnings[]` 帶 `{type: "link_type_conflict"}`
- UI 在 Test view 對該 row 顯示衝突 badge，附「採用 marker」按鈕（一鍵把 `created_by` 從人類改成 `"marker-sync"` 並更新 `link_type`）

**Rejected alternatives:**

- *Marker 永遠贏*：破壞使用者的手動 override；不可接受
- *人類永遠贏且不警告*：使用者改了 marker 後沒有任何 feedback，容易斷層
- *拋 sync error*：sync 是 background job，error 會中斷整批同步，過於激進

### D4. Unknown TC number 處理（解 Q2）

**決定**：warn-only、不寫 link、不自動建立 case。

```
解析 marker → 拿到 tc_ids
  ↓
for tc_id in tc_ids:
    case = find_test_case(team_id, number=tc_id)
    if case is None:
        warnings.append({type: "unknown_tc",
                         script_id, tc_id,
                         line: marker.source_line})
        continue  # 不建 link
    # 否則繼續正常 upsert
```

- `find_test_case` 透過 `test_cases.test_case_number` 反查（既有欄位，team-scoped）
- UI 把 `unknown_tc` warnings 顯示在 Test view 該 test row 上：「⚠ TC-999 不存在於本 team」+「Open in code」連結直接跳到 marker 行
- **不**自動建 case 的理由：建 case 屬於 manual workflow，需要 title / description / steps，從 marker 無法推導；自動建會產出空殼 case 污染資料

**Rejected alternatives:**

- *硬 error 中斷 sync*：一個 typo 就讓整個 team 的 scan 失敗，不合比例
- *自動建立空殼 case*：違反 manual case 既有建立流程（缺欄位、無 audit 軌跡）

### D5. Marker 移除後的 derived link 清理（解 Q3）

**決定**：每次 sync 是 reconcile-style — 當下檔案內找不到 marker pair，且 link 為 `created_by="marker-sync"`，就刪除。

具體在 D3 流程末尾的「清理」步驟（已嵌在 pseudocode 中）。

- 清理只影響 `created_by="marker-sync"` 的 link，**不**碰人類或 AI confirm 建立的 link
- 刪除前寫 audit（`resource_type=AUTOMATION_SCRIPT_LINK`、`action_type=DELETE`、details 含 `reason: "marker_removed"`）
- 若使用者用 `--dry-run` 觸發 sync（未來功能），刪除步驟 skip 但回 preview

**Edge case**：如果使用者把 `@pytest.mark.tcrt("TC-001")` 改成 `@pytest.mark.tcrt("TC-002")` —
- 舊 link (TC-001) 被清理（marker pair 不在了）
- 新 link (TC-002) 被建立
- 兩個動作在同一 sync transaction 內完成，UI 端看起來是「替換」

### D6. AI 建議 endpoint 的輸入安全邊界（解 Q4）

**決定**：送 `test_name + docstring + 同檔 imports`，**絕不**送 function body。

```
POST /api/teams/{team_id}/automation-scripts/{script_id}/ai-link-suggestions
Body: {
  "test_name": "test_login_with_2fa",
  "limit": 5             // top-N 候選，預設 5、max 10
}
```

Service 端組 prompt 時：

```python
prompt_input = {
    "test_name": entry.name,
    "docstring": entry.docstring,        # ast.get_docstring()，可能 None
    "file_imports": _collect_imports(content),   # ast.Import / ImportFrom 的字面 module 名
    "ref_path": script.ref_path,
    "candidate_cases": [
        {"id": c.id, "number": c.test_case_number, "title": c.title,
         "summary": c.summary[:300]}
        for c in candidate_cases   # 來自 team 內 manual cases，預先以 BM25 / token overlap 過濾 top-50
    ]
}
```

**不**送出：
- Function body / 行為碼
- Fixture 內容
- 任何同檔其他 test 的 body
- 同 repo 其他檔案內容
- DB credentials / config

Response：

```json
{
  "suggestions": [
    {"test_case_id": 12, "test_case_number": "TC-001",
     "title": "Login with 2FA succeeds",
     "confidence": 0.91,
     "rationale": "test_name 含 'login_with_2fa'，case title 直接對應"},
    ...
  ],
  "model": "google/gemini-3-flash-preview",
  "prompt_version": "ai-link-suggest.v1"
}
```

Audit log：每次呼叫寫 `READ` audit，details 含 `script_id`、`test_name`、`suggestions_count`、`model` — 但**不**寫 prompt 內容（避免 audit log 變成 PII 沉積區）。

**Rejected alternatives:**

- *送 function body 提高準確度*：洩漏內部測試邏輯到外部 LLM，違反資安原則
- *Embedding-only 不走 LLM*：vector search 對短測試名/case title 召回率差；改 LLM with few-shot 更穩

### D7. AI 信心門檻與 UI 顯示規則（解 Q5）

**決定**：

| 信心分數 | UI 行為 |
|---|---|
| ≥ 0.85 | 顯示在 Test view，badge 標「AI 高信心」，**預設勾選**但仍需使用者按「Accept」才寫 link |
| 0.60 ~ 0.85 | 顯示但不預勾，使用者主動勾才寫入 |
| < 0.60 | 隱藏（避免噪音） |

- Accept 動作：UI 呼叫 `POST .../automation-scripts/{id}/links`（既有 endpoint），`created_by="ai-suggest:<user_id>"`、`link_type=COVERS`（保守預設，不自動套 PRIMARY）
- Dismiss 動作：純前端狀態，不持久化（下次 sync 同樣 confidence 仍會出現）— 未來若噪音多再加 dismiss persistence
- 信心分數由 LLM 回傳，TCRT 不二次校準

**Rejected alternatives:**

- *自動寫入 ≥ 0.95 的 link*：違反 Q5 既定「suggestion-only」原則
- *統一 0.5 門檻*：低信心建議實測噪音極大，會反過來打擊使用者信任度

### D8. View 切換與 API 形狀

**決定**：純前端 toggle，後端只多回 `test_entries`。

```
GET /api/teams/{team_id}/automation-scripts                 ← 既有
GET /api/teams/{team_id}/automation-smart-scans/{id}         ← 既有，response 擴充

擴充後的 entry_point shape:
{
  "ref_path": "tests/test_login.py",
  ...                                       // 既有欄位
  "test_entries": [
    {
      "name": "test_login_happy",
      "kind": "function",
      "line": 12,
      "docstring": "Verifies the happy login path.",
      "markers": [
        {"tc_ids": ["TC-001"], "link_type": "covers", "source_line": 11}
      ],
      "derived_links": [
        {"test_case_id": 5, "test_case_number": "TC-001",
         "link_type": "covers", "source": "marker"}
      ]
    },
    ...
  ],
  "marker_warnings": [
    {"type": "unknown_tc", "tc_id": "TC-999", "line": 23},
    {"type": "link_type_conflict", "tc_id": "TC-001",
     "human_link_type": "primary", "marker_link_type": "covers"}
  ]
}
```

UI Suites tab：

- 加 toolbar toggle `[Script view] ◀▶ [Test view]`，預設 Script view 維持現狀
- Test view 把所有 `entry_points[*].test_entries[*]` 攤平成一個列表，columns：
  - Test name
  - Source file（可點擊跳檔）
  - TC linkage（badge 顯示 source: marker / human / ai-suggested）
  - Warnings（衝突、unknown TC）
  - AI 建議區塊（信心 ≥ 0.60 才顯示，預勾邏輯依 D7）
- View 狀態存 `localStorage`（per-team），下次開啟還原

## Risks / Trade-offs

**[R1] Marker decorator 未在 `conftest.py` 註冊 → pytest 跳 `PytestUnknownMarkWarning`**
→ Mitigation: skill template 提供 `pytest_configure` snippet；spec 文件強調這是 hard requirement；warning 不影響 test pass/fail，只是 noise

**[R2] JS/TS regex 行對位的脆弱性 — 註解與 test() 之間有複雜結構時誤判**
→ Mitigation: 明確規定「marker 必須**緊鄰** test()，中間只能空行或同類 marker」；解析失敗 fail-open + warn；長期可換 TypeScript AST（babel parser），但本期不做

**[R3] Marker 解析失敗讓使用者看不到任何錯誤**
→ Mitigation: 所有解析錯誤強制進 `marker_warnings[]`，UI 在 Test view 該檔案行顯示；CLI 端 `openspec` 風格的 `tcrt validate-markers` 工具不在這個 change 範圍，但留 follow-up

**[R4] AI 建議的隱私邊界誤踩**
→ Mitigation: D6 明確列白名單欄位；service 層在送 OpenRouter 前過濾、加 unit test 覆蓋；prompt template 走版本控制 (`prompt_version`)

**[R5] 大檔案（含 1000+ 個 test）的 sync 效能**
→ Mitigation: 既有 `max_scan_bytes = 256KB` 護欄已在；decorator walk 是 AST 二次走訪，成本可忽略；JS/TS regex 也已是 O(n)

**[R6] 衝突 warning 在 UI 被忽略 → 使用者誤以為 marker 生效實則沒生效**
→ Mitigation: Test view 衝突 badge 用紅色強烈視覺；考慮在 Smart Scan run summary 也顯示 warnings 總數；audit log 記每次衝突偵測

**[R7] `created_by` 欄位 `VARCHAR(64)` 容納 `ai-suggest:<user_id>` 長度**
→ Mitigation: 確認 user_id 最大長度（既有為 32 char user id）+ `"ai-suggest:"` 11 char = 43 char，安全；測試覆蓋 boundary

**[R8] Skill 同步義務在 PR 沒同步**
→ Mitigation: spec 既有 requirement 已強制 archive gate；本 change 的 tasks.md 把 skill 更新列為必做項；考慮加 pre-commit / CI check 偵測「change 的 spec.md 動了 marker 但 skill 沒動」— 留 follow-up
