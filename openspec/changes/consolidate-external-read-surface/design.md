# Design

## Context

`/api/mcp/*`（相容期）與 `/api/app/*`（canonical）對外提供同一組 6 個 read 操作。規模約：mcp handlers 646 行、app_read 430 行、mcp 內 read helper ~280 行。automation 區段不在範圍。

**行號**：tasks 內行號為 2026-07-28 快照，**以函式名與「留在 router 的行為」為準**。

**行數不是收益**：總行數持平或略增；收益是單一外部 read 實作 + 34 FIX。

## Goals / Non-Goals

**Goals**
- 6 個外部 read 一份查詢／組裝（`app/services/external_read/`）
- D1–D43：**34 FIX / 9 KEEP**
- 測試分層（Decision 11）；**不**宣稱每 FIX 具名測
- app-token **model** 授權單一真相：`accessible_team_ids()`
- `allowed_team_ids` 契約：`None` 不限、**空 set 空結果且禁止 `IN ()`**
- helper 離開 api 層

**Non-Goals**
- 不改 error payload 結構（Decision 3）
- 不改 `app/models/mcp.py` 欄位、mutation 路徑、assistant `tool_executor` 查詢
- 不移除 `/api/mcp/*` automation（僅 §5.1 `_to_text` 機械改名例外）
- 無 migration / schema
- 不把 D36 改 count 子查詢
- **不宣稱**「修了現網 TeamAppToken 漏 owner」——見 Decision 5

## Divergence Inventory

**FIX = 對齊 canonical；KEEP = 白名單。** 非預設 MCP 勝（Decision 1）。

### `GET /teams`

| # | 分歧 | mcp | app | 決定 |
| --- | --- | --- | --- | --- |
| D1 | NULL `status` | `"active"` fallback | `"None"` 字串 | **FIX → MCP** |
| D2 | scope 套用 | SQL `in_` | 記憶體 `can_access_team` | **FIX → SQL 下推**（+ empty-set 契約） |
| D3 | 零 scope audit / 提早回傳 | 有 | 無 | **KEEP**（router） |

### `GET /teams/{id}/test-cases`

| # | 分歧 | mcp | app | 決定 |
| --- | --- | --- | --- | --- |
| D4 | search 欄位（B3） | title+number+tcg | 僅 title | **FIX → MCP** |
| D5 | 未知 set_id | 整 team + `set_not_found`；`strict_set` | 當過濾 → 0 筆 | **FIX → MCP**；app 加 `strict_set` 預設 **false**（Decision 2） |
| D6 | `set_id==0` | `is not None` 生效 | `if set_id:` 忽略 | **FIX → MCP**（測**過濾語意**，非僅 echo） |
| D7 | case 排序 | created_at DESC, id DESC | id ASC | **FIX → MCP** |
| D8 | sets 排序 | 同上 | id ASC | **FIX → MCP** |
| D9 | filters echo | 12 key | 10 key（有 section_id） | **FIX → MCP keys + section_id** |
| D10 | section_id 過濾能力 | 無參數 | 有 | **KEEP**（能力；共用後 key 可雙邊皆有 null） |
| D11 | limit 上限 | 1000 | 500 | **KEEP** |

### `GET /teams/{id}/test-cases/{case_id}`

| # | 分歧 | mcp | app | 決定 |
| --- | --- | --- | --- | --- |
| D12 | joinedload set | 無 | 有 | **FIX → 移除** |
| D13 | 404 shape | 中文純文字 | detail.code | **KEEP** |

### `GET /test-cases/lookup`

| # | 分歧 | mcp | app | 決定 |
| --- | --- | --- | --- | --- |
| D14 | 分頁（B1） | SQL only | 雙重切片 | **FIX → MCP** |
| D15 | total（B2） | DB count | len(items) | **FIX → MCP** |
| D16 | filter 組合 | AND（scope 在 AND） | OR | **FIX → AND**（安全關鍵） |
| D17 | number 比對 | ilike 子字串 | 精確 == | **FIX → MCP**（集合擴大；match_type） |
| D18 | q 含 tcg | 是 | 否 | **FIX → MCP** |
| D19 | 排序 | created_at DESC, id DESC | 無 | **FIX → MCP** |
| D20 | 未知 team_id | 404 | 200 空 | **FIX → MCP** |
| D21 | 零 scope | 403 | 200 空 | **KEEP** |
| D22 | team_name 過濾能力 | 有 | 無 | **KEEP**（能力；共用後 key 可雙邊 null） |
| D23 | include_content | 參數預設 true | lookup 無參數恆 false | **FIX → app 加參數預設 false** |
| D24 | limit 上限 | 200 | 100 | **KEEP** |

### `GET /teams/{id}/test-case-sections`

| # | 分歧 | mcp | app | 決定 |
| --- | --- | --- | --- | --- |
| D25 | 排序（B4b） | set, level, sort_order, id | sort_order, id | **FIX → MCP** |
| D26 | include_empty | 有預設 true | 無 | **FIX → app 加參數預設 true** |
| D27 | 未知 set | set_not_found + 空 | 當過濾 | **FIX → MCP** |
| D28 | roots_only 優先 | roots 先 | parent 先 | **FIX → MCP** |
| D29 | filters keys | 5 | 3 | **FIX → MCP** |

### `GET /teams/{id}/test-runs`

| # | 分歧 | mcp | app | 決定 |
| --- | --- | --- | --- | --- |
| D30 | run_type 含 set（B4） | 是 | 否 | **FIX → MCP** |
| D31 | include_archived（B5） | 預設 false | 無參數全回 | **FIX → app 加參數預設 false** |
| D32 | set status（B5b） | resolve_status_for_response | raw DB | **FIX → MCP**（eager-load） |
| D33 | 成員 config status/archived 過濾 | 有 | 無 | **FIX → MCP** |
| D34 | 成員 config 排序 | position, id | 無 | **FIX → MCP** |
| D35 | set status 不符但 member 命中 | 保留 set | 丟棄 | **FIX → MCP** |
| D36 | adhoc 計數 | items 實算 | 恆 0 | **FIX → MCP** |
| D37 | adhoc 排序 | updated_at DESC, id DESC | id DESC | **FIX → MCP** |
| D38 | unassigned 排序 | created_at DESC, id DESC | 無 | **FIX → MCP** |
| D39 | unassigned 查詢形狀 | outerjoin + **config.team_id** | 全域 membership ids NOT IN + **仍有 config.team_id** | **FIX → MCP 查詢形狀**（單一 code path）。**不是**「B 的 config 漏進 A」——app **已有** team_id 過濾；偽安全測已刪 |
| D40 | summary（B6） | 5 key | 3 alias 形 | **FIX → 5 + app 3 deprecated alias** |
| D41 | filters include_archived | 有 | 無 | **FIX → MCP** |

### 跨端點

| # | 分歧 | 決定 |
| --- | --- | --- |
| D42 | allow-path audit 不對稱 | **KEEP** |
| D43 | error shape 混合 | **KEEP** |

**合計：FIX 34、KEEP 9、D1–D43。**

### 測試覆蓋分層

| 層 | 內容 |
| --- | --- |
| **Tier A** | 具名 xfail→pass：分頁/AND/search/set/排序/test-runs 高風險、D32 可構造 raw≠resolved、**鏡射 MCP unified test-runs**（補 D33–D35 種子厚度） |
| **Tier B** | MCP 28 測守 Phase 2/3 |
| **Tier C** | 參數對齊 payload parity + summary alias 白名單 |
| **必綠護欄** | 跨 team scope HTTP；`accessible_team_ids` **單元**（含空 scope+owner）；**禁止**虛構 HTTP `team_scope_ids=[]` 的 TeamAppToken |
| **不具名** | 多數 KEEP、內部 joinedload 移除、filters key 合流後的歷史 KEEP |

## Decisions

### Decision 1：canonical 逐項選

不預設 MCP 勝。D17 選 ilike 因 `lookup_match_type` 設計意圖。lookup 對等由本 change 新建。

### Decision 2：D5 + `strict_set` 預設 false（結案）

等價 MCP；風險用文件遷移 + Tier A；**不再**留 app 預設 true 未決。

### Decision 3：error shape 不變

domain 例外 → 各 router 現行 shape。`TestCaseSetNotFoundError` 在 app 為新行為 → `RESOURCE_NOT_FOUND` dict。存在性 oracle 歸 error-envelope change。

### Decision 4：summary alias + 可驗證退場

app 5+3；MCP 僅 5。退場：wrapper 原始碼 grep（位址由 follow-up design/ops 定）+ docs 無 alias。

### Decision 5：授權真相與「不誇大」的 MCP 映射

**事實（紅隊 2 已核對原始碼）：**
- `_resolve_app_token_principal` 對 TeamAppToken **固定**  
  `team_scope_ids = [owner_team_id]`（有 owner 時），HTTP 下**不會**出現 `owner 有值且 team_scope_ids=[]`。
- 單元測手搓 principal 才有「空 scope + owner」。
- Legacy machine：`owner_team_id=None`，scope 來自 `team_scope_json`。

**選擇：**
1. **Phase 1 就落地** `accessible_team_ids()` + `can_access_team` 委派（HTTP 行為不變）——單元測從第一天鎖 `{5}`，**不**拖到 Phase 4。
2. 護欄拆開：  
   - **單元**：`owner_team_id=5, team_scope_ids=[], allow_all=False` → `accessible_team_ids() == {5}`（必綠）。  
   - **HTTP**：真實 app token lookup 見 A 不見 B；**禁止** seed 假空 scope token。
3. `queries.allowed_team_ids` 必填 keyword-only；scope **AND only**。
4. **Empty-set 契約（強制 + 雙測）**：  
   - `None` → 不限 team  
   - `set()` → **立即空結果**，**禁止** `IN ()`  
   - 源碼**禁止** `if not allowed_team_ids` / `if allowed_team_ids:`（falsy 陷阱）；只准 `is None` 與 `len(...)==0`  
   - tasks §3.22 行為測 + §3.23 源碼測，皆**必綠**
5. MCP 映射：**防禦性**；用 `allow_all` 分支 + `sorted(allowed)`，**禁止**依賴 `allowed or []` 混淆 None／空 set 語意（allow_all 時 flag 為真、scope 列表空）。

### Decision 6：eager-load 自備

`list_team_test_runs_read` 自帶 memberships→config 與 adhoc sheets→items。只用 `resolve_status_for_response`，禁 `recalculate_set_status`。

### Decision 7–9：package / MCP* model / 不遷 tool_executor

同前稿（external_read 獨立；不改名 MCP*；assistant 邊界保留）。

### Decision 10：廢 compat_*；MCP 先、app 後

Gate：Phase 2/3 = **28** MCP 測。Phase 4 診斷用 `-k` 分組。

### Decision 11：測試分層與 parity（第三輪收斂）

凡曾標「實作時注意」的項，全部變成 **seed／斷言／源碼測／文件 rg**。

1. **禁止 xpass 的排序測**：  
   - **D19**：lookup `q=ZKEY` 的 case id **必須恰為 `[c2, c1]`**（created/id DESC），**禁止**「連打兩次相同」。  
   - **D25**：seed **兩 set**（先 `SET-LATE-SORT`+section sort_order=1，後 `SET-EARLY-SORT`+sort_order=0）；斷言序為 MCP 的 set_id 序（late-sort 在前）。單 set 兩 section **禁止**（與 app 同序 → xpass）。
2. **D6**：`set_not_found is True` + total=整 team；禁止只 assert filters 有 `0`。
3. **D32 + D34 同 set、member 全 COMPLETED**：DB raw=`ACTIVE`；兩 member 皆 `COMPLETED`（position 0/1）。**禁止**混 ACTIVE member——`compute_set_status` 僅在全員 COMPLETED/ARCHIVED 時回 COMPLETED；混 ACTIVE → resolve 仍 ACTIVE，D32 崩潰。xfail 期 mcp=`completed`、app raw=`active`。
4. **test-runs 鏡射**：三組參數；預設驗證 D34 position 序；`status=completed` **必須**含 ACTIVE SET（resolve completed 後）。
5. **Tier C 白名單**：僅 summary 三 alias。
6. **Empty-set**：teams **與** lookup 行為測 + 源碼測（`len` ≥2）；必綠。
7. **Phase gate 含** `test_app_token_auth.py`（鎖 §1.4 授權 model）。
8. **文件**：§5.7–5.9 `rg` 鎖遷移五點。

### Decision 12：D36 維持 items 載入

與 MCP 同 path；count 優化另案。

### Decision 13：D39 定性更正

**錯誤舊敘事**：「app 無 team 過濾 → B 漏進 A」。  
**事實**：app unassigned 已有 `TestRunConfig.team_id == team_id`。  
**仍 FIX**：查詢改 MCP outerjoin 形狀，單一實作、排序與 membership 語意一致。  
**測試**：靠加厚 seed + 鏡射 unified + parity，**不**做偽跨 team 安全測。

## Risks / Trade-offs

| 風險 | 如何**關閉**（非「注意」） |
| --- | --- |
| D5 資料放大 | Tier A strict_set/set_not_found；docs 遷移五點 + `rg`（§5.7–5.9） |
| D16 scope OR | AND + scope HTTP 3 測 |
| D19/D25 xpass | 固定 id 序列／雙 set seed（Decision 11） |
| D6/D32/D39 假測 | 語意斷言；D39 偽測禁止 |
| empty / truthiness | §3.22+§3.23 必綠 |
| owner 誇大 | Phase 1 單元鎖 model；映射 4.3 單元 |
| D32 seed 與 D34 衝突 | **雙 COMPLETED member**（禁混 ACTIVE）；§8.8 #6 |
| D32/D36 MissingGreenlet | 函式自備 joinedload；鏡射+D32 測 |
| Phase 4 大 diff | §4.12 A/B 強制後才解 xfail |
| auth model 回歸 | gate **含** `test_app_token_auth.py` |
| lookup 漏 empty-set | §3.22 兩行為測 + `len`≥2 |
| D17 集合擴大 | Tier A + docs `match_type` rg |
| 全套 assistant hang | §8.2 逐檔程序 |

## Migration Plan

1. Phase 1 — 骨架、**accessible_team_ids**、Tier A xfail（防 xpass seed）、護欄、MCP +2  
2. Phase 2 — helper 逐字搬  
3. Phase 3 — queries + **僅 mcp** + empty-set **雙測**  
4. Phase 4 — app 委派 + 防禦映射；§4.12 後再解 xfail  
5. Phase 5 — 清理 + **文件 rg 契約**  

**Rollback**：phase commit revert。無 schema 遷移。
