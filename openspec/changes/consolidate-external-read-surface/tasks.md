# Implementation Tasks

## 執行者須知（先讀完再動手）

優先**符號名**與「留在 router 的行為」；行號僅導航。不要跳步、不要擴大範圍。  
**禁止把風險留到「實作時注意」——凡下列契約都有對應 checkbox 與驗證指令。**

### 絕對禁止

- ❌ 改 `app/models/mcp.py`、ORM/migration、mutation routers
- ❌ 動 mcp automation（唯一例外 §5.1 `_to_text`→`to_text`）
- ❌ 放寬既有斷言而不經 §7.1
- ❌ `# noqa` / 改 ruff 全域設定
- ❌ `external_read` 開 session、commit/rollback、HTTPException、mutation
- ❌ 宣稱「每 FIX 一具名測」或「修了現網 TeamAppToken 漏 owner」
- ❌ seed 假 HTTP「`team_scope_ids=[]` 的 TeamAppToken」
- ❌ D39 偽測（B orphan 進 A unassigned）
- ❌ 在 `queries.py` 寫 `if not allowed_team_ids` / `if allowed_team_ids:` 判斷 scope  
  （`None` 與 `set()` 在 Python 皆 falsy → **會把空集合誤當不限 = 跨 team 洞**）。**只准** `is None` 與 `len(allowed_team_ids) == 0`
- ❌ D19 只斷言「連打兩次相同」（無 order_by 時 SQLite 常已穩定 → xpass）
- ❌ D25 只用單 set 兩 section 比序（與 app 序相同 → xpass）
- ❌ D32 seed 在 ACTIVE SET 混入 **ACTIVE／非終態** member（resolve 會停在 `active`，打臉 D32；D34 用**雙 COMPLETED** + position 即可）
- ❌ phase gate 拿掉 `test_app_token_auth.py`
- ❌ empty-set 只測 `list_teams_read`、不測 lookup

### 名詞

- D1–D43：**34 FIX / 9 KEEP**
- Tier A/B/C = Decision 11

### 測試計數（改測時同步）

| 集合 | 數量 | 說明 |
| --- | --- | --- |
| MCP 既有 | 26 | |
| MCP 錯誤字串 | +2 | §1.13 |
| **MCP 合計** | **28** | |
| Tier A xfail | 22 | **§1.8** |
| Tier C xfail | 1 | **§1.9** |
| Scope HTTP 必綠 | 3 | **§1.10** |
| `accessible_team_ids` 單元必綠 | 1 | **§1.11**（Phase 1 §1.4 已有方法） |
| Empty-set 契約必綠 | **3** | §3.22 teams 行為 + §3.22b lookup 行為 + §3.23 源碼 |
| **parity 檔 Phase 1** | **4 passed + 23 xfailed** | 3 scope + 1 unit + 22+1 xfail |
| **parity／contract 檔 Phase 4 後** | **≥30 passed** | 4+23 解 xfail + empty-set **3**（可同分檔） |

### Phase gate（**每個** phase 結束必跑；清單不可刪檔）

```bash
uv run ruff check . && uv run pytest \
  app/testsuite/test_mcp_api.py \
  app/testsuite/test_app_token_read_api.py \
  app/testsuite/test_app_token_auth.py \
  app/testsuite/test_mcp_automation.py \
  app/testsuite/test_mcp_audit_resource_id.py \
  app/testsuite/test_app_token_pins_api.py \
  app/testsuite/test_db_access_guardrails.py \
  app/testsuite/test_external_read_parity.py \
  -q
```

**強制含 `test_app_token_auth.py`**：§1.4 改了 `AppTokenPrincipal`；後續 phase 若回歸 `can_access_team`／`accessible_team_ids`，gate 必須抓到。

assistant 多檔連跑可能卡住——gate 不含；§8.2 逐檔。

### Phase 4 診斷

```bash
uv run pytest app/testsuite/test_external_read_parity.py -q -k "lookup"
uv run pytest app/testsuite/test_external_read_parity.py -q -k "search or set_id or test_cases or section"
uv run pytest app/testsuite/test_external_read_parity.py -q -k "run_type or archived or adhoc or unassigned or summary or test_runs or empty"
uv run pytest app/testsuite/test_external_read_parity.py -q
```

---

## 1. Phase 1 — 骨架、授權 model、測試鷹架

- [x] 1.1 建 `app/services/external_read/` 六檔：`__init__.py`、`errors.py`、`payloads.py`、`filters.py`、`counts.py`、`queries.py`
- [x] 1.2 `queries.py` 模組 docstring **必須逐字含**（可多行）：
      - `External read-only queries shared by /api/mcp/* and /api/app/*.`
      - `Read-only only: no session open, no commit/rollback, no HTTPException, no mutation.`
      - `allowed_team_ids: None = unrestricted; empty frozenset/set = empty result; never emit SQL IN ().`
      - `Compare with "is None" and "len(...)==0" only — never "if not allowed_team_ids".`
- [x] 1.3 `errors.py` 六類例外（`ExternalReadError`、`TeamNotFoundError`、`TestCaseSetNotFoundError`、`TestCaseNotFoundError`、`MissingLookupFilterError`、`UnknownRunTypeError`）— 簽章同 design Decision 3 表
- [x] 1.4 **本 phase 就落地** `AppTokenPrincipal.accessible_team_ids()` + 以它實作 `can_access_team`（與 §4.1 相同實作，HTTP 行為不變）。**不得**留到 Phase 4 才加方法。
      ```python
      def accessible_team_ids(self) -> Optional[set[int]]:
          if self.allow_all_teams:
              return None
          ids: set[int] = set(self.team_scope_ids)
          if self.owner_team_id is not None:
              ids.add(self.owner_team_id)
          return ids

      def can_access_team(self, team_id: int) -> bool:
          allowed = self.accessible_team_ids()
          return allowed is None or team_id in allowed
      ```
- [x] 1.5 `uv run pytest app/testsuite/test_app_token_auth.py -q` 全綠；`uv run ruff check app/models/app_token.py app/services/external_read/`

### 1.6–1.12 測試鷹架

- [x] 1.6 建 `app/testsuite/test_external_read_parity.py`：照抄 `test_app_token_read_api` 的 `temp_db`（**含 `@pytest.fixture`**）、imports、`_hash_token`、`_bearer`；db 名 `test_external_read_parity.db`
- [x] 1.7 `_seed_parity_data(session)`：

      **Cases（Team A）**：1 default set；3 cases（**依序 insert，讓 id 遞增 = c1&lt;c2&lt;c3**）：

      | | number | title | tcg_json |
      | --- | --- | --- | --- |
      | c1 | `TC-QNUM-001` | `ZKEY alpha` | 空 |
      | c2 | `TC-PLAIN-002` | `ZKEY beta` | `["QNUM-9"]` |
      | c3 | `TC-PLAIN-003` | `unrelated gamma` | 空 |

      **Sections（D25 必跨 set，否則 xpass）**：
      1. 先建 set `SET-LATE-SORT`，其下 1 section：`name=late-sort`、`level=1`、`sort_order=1`
      2. 再建 set `SET-EARLY-SORT`，其下 1 section：`name=early-sort`、`level=1`、`sort_order=0`  
      → 現行 app 序（`sort_order,id`）：early-sort 在前；MCP 序（`set_id,...`）：先建的 SET-LATE-SORT 在前 → **修前兩 namespace id 序列必不同**

      可另建 default set 專放 cases，或 cases 掛在 SET-LATE-SORT；sections 列表測不帶 set_id。

      **Team B**：set + case `TC-QNUM-B01` / `ZKEY teamb`（scope 護欄）。禁止 B orphan 偽測。

      **Test runs（Team A，加厚）** — **D32 與 D34 同一 set，member status 不可混 ACTIVE**：
      - Set `ACTIVE SET`：DB status=`ACTIVE`（raw）
        - member `IN-SET-CFG-B`：**status=`COMPLETED`**、`position=0`
        - member `IN-SET-CFG`：**status=`COMPLETED`**、`position=1`
        - **禁止**任一 member 為 `ACTIVE`／進行中：`compute_set_status` 僅在「全部 COMPLETED 或 ARCHIVED」時回 `COMPLETED`；混 ACTIVE → resolve 仍為 `ACTIVE`，會打臉 D32（mcp 與 app 都變 `active` → xpass 或 Phase 4 永久紅）
        - **D32**：`resolve_status_for_response` → **`completed`**；raw DB 仍 **`active`**
        - **D34**：修後 `test_runs` 第一筆 id = position=0 的 `IN-SET-CFG-B`
      - Set `ARCHIVED SET`：`ARCHIVED`
      - `UNASSIGNED-CFG` status=`COMPLETED` 無 membership
      - 可選 archived 獨立 config

      **Adhoc**：`Adhoc Active` + sheet + 2 items（1 `PASSED`、1 `test_result=None`）→ counts 2/1；`Adhoc Archived` status ARCHIVED 供鏡射

      **憑證**：真實 `TeamAppToken`（owner=A，scopes read）；`MCPMachineCredential` allow_all + mcp_read。**不要** owner_only HTTP token。

      回傳 dict 必含：`team_a_id`、`team_b_id`、`app_token`、`legacy_token`、`case_ids`（c1,c2,c3）、`section_late_id`、`section_early_id`、`set_active_id`、`config_in_set_id`、`config_in_set_b_id`、`config_unassigned_id`

- [x] 1.8 **Tier A**（`@pytest.mark.xfail(strict=True)`）：

      | test | 修後斷言（xfail 期必須**失敗**） | D |
      | --- | --- | --- |
      | `test_lookup_second_page_not_empty` | `lookup?q=ZKEY&skip=1&limit=1` → `len(items)==1` | D14 |
      | `test_lookup_total_is_match_count` | `limit=1` → `page.total==2` | D15 |
      | `test_lookup_filters_are_anded` | `q=ZKEY&ticket=NOSUCH` → `total==0` | D16 |
      | `test_lookup_q_covers_tcg` | `q=QNUM-9` → `total==1` | D18 |
      | `test_lookup_number_is_substring` | `test_case_number=QNUM` → 命中含 c1 | D17 |
      | `test_lookup_order_is_created_desc_id_desc` | `lookup?q=ZKEY` → items 的 case id **恰為** `[c2, c1]`（seed 先 c1 後 c2；canonical 新在前）。**禁止**只比兩次呼叫相同 | D19 |
      | `test_lookup_unknown_team_returns_404` | `team_id=999999` → 404 | D20 |
      | `test_search_covers_number_and_tcg` | `search=QNUM` → `total==2` | D4 |
      | `test_unknown_set_id_reports_not_found` | `set_id=999999` → `set_not_found` 且 total=3 | D5 |
      | `test_strict_set_returns_404` | `strict_set=true` → 404 | D5 |
      | `test_set_id_zero_applies_unknown_set_semantics` | `set_id=0` → `set_not_found is True` 且 total=省略 set_id 時 total。禁止只 assert filters 有 0 | D6 |
      | `test_test_cases_order_is_created_desc` | list → ids `[c3,c2,c1]` | D7 |
      | `test_sections_order_is_set_level_sort_id` | app sections 不帶 set_id → id 序列 **恰為** MCP 同呼叫的 id 序列；且 **第一個為 late-sort 的 id**（set_id 序）。xfail 期 app 會是 early-sort 在前 | D25 |
      | `test_run_type_excludes_sets` | `run_type=adhoc` → `sets==[]` | D30 |
      | `test_archived_sets_excluded_by_default` | 無 ARCHIVED SET | D31 |
      | `test_archived_sets_included_when_requested` | `include_archived=true` 含之 | D31 |
      | `test_set_status_uses_resolver_not_raw` | ACTIVE SET（**雙 COMPLETED member**）：mcp status **`completed`**、app raw **`active`** 且**不等**；修後雙邊 **`completed`**。若 mcp 已是 `active` → seed 違反 D32（混了 ACTIVE member），停工修 seed | D32 |
      | `test_summary_has_canonical_and_legacy_keys` | app 5+3 | D40 |
      | `test_adhoc_counts_are_computed` | Adhoc Active total=2 executed=1 | D36 |
      | `test_null_team_status_falls_back_to_active` | status NULL → `"active"` | D1 |
      | `test_filters_include_set_not_found_keys` | 未知 set → 有 `set_not_found`+`resolved_set_id` | D9 |
      | `test_app_test_runs_mirrors_mcp_unified_filters` | 三組：(1) 預設 (2) `status=completed` (3) `run_type=adhoc&status=archived&include_archived=true`。修後 sets/unassigned/adhoc 的 **id 集合**與 mcp 相同；(1) ACTIVE SET 的 `test_runs[0].id == config_in_set_b_id`（position=0）；(2) ACTIVE SET **必須出現**（resolve 為 completed；seed 雙 COMPLETED 保證） | D30–D36 |

- [x] 1.9 **Tier C** `test_parity_response_shapes_match_allowlist`：
      - `PAYLOAD_ALLOWED_DIVERGENCE = frozenset({"summary.sets","summary.unassigned","summary.adhoc"})`  
        （**僅**這三個；section_id/team_name 能力差另用專測，不放 happy-path 白名單以免誤解）
      - 參數對齊：`include_content=false`、`include_test_data=false`；不傳 section_id/team_name；test-runs 預設
      - 忽略 `created_at`/`updated_at`
      - `xfail(strict=True)` 至 §4.14

- [x] 1.10 **跨 team HTTP 必綠**：
      | test | 斷言 |
      | --- | --- |
      | `test_lookup_respects_team_scope` | 無 team B |
      | `test_list_respects_team_scope` | team B → 403 |
      | `test_detail_respects_team_scope` | 403/404 無 B 內容 |

- [x] 1.11 **`accessible_team_ids` 單元必綠**（Phase 1 方法已存在）：
      ```python
      def test_accessible_team_ids_includes_owner_when_scope_empty():
          p = AppTokenPrincipal(
              credential_id=1, credential_name="t",
              owner_team_id=5, team_scope_ids=[],
              allow_all_teams=False, scopes=["test_case:read"],
          )
          assert p.accessible_team_ids() == {5}
          assert p.can_access_team(5) is True
          assert p.can_access_team(6) is False
      ```

- [x] 1.12 `pytest test_external_read_parity.py -q` → **4 passed、23 xfailed、0 failed**  
      若 **xpass**：必為 D19/D25/D6 斷言或 seed 又變弱——修測／seed，禁止去 strict。
- [x] 1.13 `test_mcp_api.py` +2 錯誤字串（team 404、run_type bogus 逐字）
- [x] 1.14 `pytest test_mcp_api.py -q` → **28 passed**
- [x] 1.15 Phase gate

---

## 2. Phase 2 — helper 逐字搬

- [x] 2.1 `payloads.py`：`to_text`、`parse_assignee`、`parse_tcg_list`、`parse_json_list`、`parse_json_dict`、`build_case_payload`、`lookup_match_type`、`config_payload`（主體逐字）
- [x] 2.2 `filters.py`：`normalize_priority_filter`、`normalize_result_filter`、`parse_status_filters`、`status_match`、`apply_archive_and_status`；`parse_run_types` 僅改 raise → `UnknownRunTypeError`
- [x] 2.3 `counts.py`：`get_team_case_counts`、`get_section_case_counts`
- [x] 2.4 `queries.ensure_team_exists` → `TeamNotFoundError`
- [x] 2.5 `__init__.py` 匯出 + `__all__`
- [x] 2.6 `mcp.py`：刪定義、import 13 公開符號 + 私有別名過渡；勿 F401 內部-only parse_*
- [x] 2.7 error wrappers 中文訊息**逐字**
- [x] 2.8 清 F401；**保留** automation 用 `json`
- [x] 2.9 MCP 28 + app read/pins 全綠
- [x] 2.10 parity 仍 4+23 xfail
- [x] 2.11 Phase gate

---

## 3. Phase 3 — canonical queries，只委派 mcp

- [x] 3.1 實作 `list_teams_read` / `list_team_test_cases_read` / `get_team_test_case_detail_read` / `lookup_test_cases_read` / `list_team_test_case_sections_read` / `list_team_test_runs_read`  
      **每個**接受 `allowed_team_ids` 的函式必須用同一形狀（lookup／teams）：
      ```python
      if allowed_team_ids is None:
          pass  # unrestricted
      elif len(allowed_team_ids) == 0:
          return <empty response of correct type>
      else:
          stmt = stmt.where(...in_(allowed_team_ids))
      ```
      team-scoped 函式不需 `allowed_team_ids`（router 已 ensure team + access）。
- [x] 3.2 mcp 六 read handler 委派；audit／ensure_team／error map 留 router；空 scope 傳 `set()` **或** router early return（皆須滿足 empty 契約）
- [x] 3.3 test-runs：**自備** joinedload memberships→config 與 adhoc sheets→items；**僅** `resolve_status_for_response`
- [x] 3.4 `pytest test_mcp_api.py -q` → **28 passed**
- [x] 3.5 read handler 內無 `select(`（automation 除外，人工確認）
- [x] 3.6 **禁止**改 `app_read.py`
- [x] 3.22 **必做** empty-set **行為**（皆必綠、非 xfail；同一 async fixture／parity 檔）：
      1. `test_empty_allowed_team_ids_list_teams`：  
         `await list_teams_read(db, allowed_team_ids=set())` → `total==0`、`items==[]`
      2. `test_empty_allowed_team_ids_lookup`：  
         `await lookup_test_cases_read(db, allowed_team_ids=set(), keyword="ZKEY", test_case_number=None, ticket=None, team_id=None, ...)`  
         （其餘參數用函式預設／`include_content=False, skip=0, limit=20`）→ `page.total==0` 且 `items==[]`  
         **不得**只測 teams；lookup 漏 empty 分支 = 未完成
- [x] 3.23 **必做** 源碼契約 `test_allowed_team_ids_uses_is_none_not_truthiness`：
      ```python
      src = Path("app/services/external_read/queries.py").read_text()
      assert "if not allowed_team_ids" not in src
      assert "if allowed_team_ids:" not in src  # 不含 "is None"；簽名 `allowed_team_ids:` 不觸發此字串
      assert "is None" in src and "len(allowed_team_ids)" in src
      # 兩個跨 team 入口都必須出現 empty 分支（字面或等價 len 檢查 ≥2 次）
      assert src.count("len(allowed_team_ids)") >= 2
      ```
- [x] 3.24 Phase gate（含 3.22 兩測 + 3.23；含 `test_app_token_auth`；Tier A 仍 xfail）

---

## 4. Phase 4 — app 委派 + 防禦性 MCP 映射

> `accessible_team_ids` 已在 Phase 1；本 phase 只切 router。

- [x] 4.1 確認 `can_access_team` 仍只委派 `accessible_team_ids`（無分叉邏輯）
- [x] 4.2 **防禦性** `mcp_dependencies` 映射（**禁止** `or []` 吃掉語意時用錯 flag）：
      ```python
      if app_principal.allow_all_teams:
          allow_all_teams = True
          team_scope_ids: list[int] = []
      else:
          allow_all_teams = False
          allowed = app_principal.accessible_team_ids()
          # allowed is set[int] here, never None when allow_all is False
          team_scope_ids = sorted(allowed if allowed is not None else [])
      ```
- [x] 4.3 單元：映射後 `owner_team_id=5, team_scope_ids=[]` 的 app principal → machine `team_scope_ids == [5]`（手搓 AppTokenPrincipal 再呼叫映射函式或抽出 pure helper 測）
- [x] 4.4 app_read 改 import external_read；error map（Decision 3）；移除全部 `app.api.mcp` import（含 local）
- [x] 4.5 `list_app_teams` → `list_teams_read(allowed_team_ids=principal.accessible_team_ids())`；**刪**事後 filter 迴圈
- [x] 4.6 list cases：`strict_set=Query(False)`；ensure_team **先於** require_access；section_id 續傳
- [x] 4.7 detail 委派；去 joinedload set
- [x] 4.8 lookup：`allowed_team_ids=principal.accessible_team_ids()`；刪記憶體 can_access 過濾；`include_content=Query(False)`；無零 scope 403
- [x] 4.9 sections：`include_empty=Query(True)`
- [x] 4.10 test-runs：`include_archived=Query(False)`；summary 三 alias；UnknownRunType map
- [x] 4.11 app_pins：ensure_team + 純文字 404
- [x] 4.12 **中途驗證（解除 xfail 前必跑，二選一皆須寫進 PR／回報）**：
      **A（優先）**：`uv run pytest app/testsuite/test_external_read_parity.py -q -k "mirrors_mcp or set_status or adhoc_counts or archived" --runxfail`  
      **B（無 --runxfail 時）**：暫時刪除該子集測試上的 `@pytest.mark.xfail`，跑同一 `-k`，跑完**立刻**用 git 還原 xfail 標記再繼續  
      失敗 → 文首診斷；**禁止**跳過 4.12 直接 4.13
- [x] 4.13 解除全部 23 個 xfail
- [x] 4.14 `pytest test_external_read_parity.py -q` → **≥30 passed、0 xfailed**（4 護欄 + 23 原 xfail + empty-set **3**；分檔則 parity≥27 且 empty 檔 3 全綠）
- [x] 4.15 MCP 28+6+3；app read/pins 全綠
- [x] 4.16 `rg -n "select\(|func\.count\(|joinedload" app/api/app_read.py` 無輸出
- [x] 4.17 `rg -n "app\.api\.mcp" app/api/app_read.py app/api/app_pins.py` 無輸出
- [x] 4.18 若改既有測 → §7.1
- [x] 4.19 Phase gate

---

## 5. Phase 5 — 清理與文件（可機械驗證）

- [x] 5.1 移除 mcp 過渡別名；automation 僅 `_to_text`→`to_text`；保留 error wrappers
- [x] 5.2 `rg -n "from app\.api\.mcp import|import app\.api\.mcp" app/` — 業務碼無 private 依賴（測試改 import external_read 則 §7.1）
- [x] 5.3 ruff 相關路徑 + 全庫 `uv run ruff check .`
- [x] 5.4 boundary：`rg -n "SessionLocal|commit\(|rollback\(" app/services/external_read/` 無
- [x] 5.5 mutation：`rg -n "session\.add|recalculate_set_status" app/services/external_read/` 無（勿用裸 `update(`）
- [x] 5.6 `rg -n "HTTPException|from app\.api" app/services/external_read/` 無
- [x] 5.7 **文件字串契約**（下列 `rg` 皆須命中，否則任務未完成）：
      ```bash
      rg -n "strict_set" docs/app_token_api_reference.md
      rg -n "set_not_found" docs/app_token_api_reference.md
      rg -n "include_archived" docs/app_token_api_reference.md
      rg -n "set_count" docs/app_token_api_reference.md
      rg -n "deprecated|Deprecated" docs/app_token_api_reference.md
      rg -n "AND|交集|and" docs/app_token_api_reference.md   # lookup 多 filter
      rg -n "strict_set|set_not_found|include_archived" tools/skills/tcrt-app/references/api-reference.md
      rg -n "external_read" openspec/project.md
      ```
- [x] 5.8 **client 遷移段**：`docs/app_token_api_reference.md` 必須有獨立小節（標題含 `Migration` 或 `遷移`），且正文含這五點（可用中英）：
      1. 未知 set_id 不再回空清單 → 讀 `set_not_found` 或 `strict_set=true`
      2. lookup 多 filter 為 AND 非 OR
      3. number 子字串 + `match_type`
      4. 預設不回 archived → `include_archived=true`
      5. summary 用 `*_count`；舊 `sets`/`unassigned`/`adhoc` deprecated
- [x] 5.9 驗證 5.8：
      ```bash
      rg -n "Migration|遷移" docs/app_token_api_reference.md
      rg -n "match_type" docs/app_token_api_reference.md
      ```
- [x] 5.10 行數記入 §8.1

---

## 6. Spec 同步

- [x] 6.1–6.2 delta 與實作一致；**未**改 Stable Error Mapping
- [x] 6.3 `openspec validate consolidate-external-read-surface --strict`
- [x] 6.4 Decision 變更書面記錄

---

## 7. 既有測試修改登記

| 檔案:行 | 原斷言 | 改成 | D | 非放寬理由 |
| --- | --- | --- | --- | --- |
| 無 | — | — | — | 未修改任何既有測試斷言；僅新增 test_external_read_parity.py（新檔）與 test_mcp_api.py +2 新測試 |

---

## 8. 最終驗證

- [x] 8.1 行數表
- [x] 8.2 全套 pytest（assistant 卡住 → 逐檔 + 回報註明）
- [x] 8.3–8.6 ruff / lint / i18n / openspec validate
- [x] 8.7 `git diff` 檔案 ⊆ proposal 清單
- [x] 8.8 **封閉檢查表（全必須「是」）**：

| # | 檢查 | 驗證方式 |
| --- | --- | --- |
| 1 | 34 FIX / 9 KEEP | 對 inventory |
| 2 | Tier A 22 全 pass | pytest |
| 3 | D19 斷言是 `[c2,c1]` 非「兩次相同」 | 讀測碼 |
| 4 | D25 seed 雙 set 且修前序不同 | 讀 seed |
| 5 | D6 用 set_not_found | 讀測碼 |
| 6 | D32：ACTIVE SET **僅** COMPLETED member（≥1，D34 用雙 COMPLETED+position）；resolve=`completed`、raw=`active` | 讀 seed；`rg "IN-SET-CFG" -A2` 無 ACTIVE member |
| 7 | empty-set **3** 測綠（teams + lookup + 源碼） | 3.22+3.22b+3.23 |
| 8 | queries 無 truthiness；`len(allowed_team_ids)` ≥2 | 3.23 |
| 9 | accessible_team_ids 單元綠 | 1.11 |
| 10 | 文件遷移 5 點 + rg | 5.7–5.9 |
| 11 | 無 D39 偽測 | rg 測檔 |
| 12 | parity 白名單僅 summary 三 alias | 讀測碼 |
| 13 | MCP 映射測含 owner→scope | 4.3 |
| 14 | 鏡射 D34 position + status=completed 含 ACTIVE SET | 1.8 最後一列 |
| 15 | phase gate **含** `test_app_token_auth.py` | 讀 tasks 文首；每個 phase 實跑 |
| 16 | §4.12 已執行（A 或 B）後才解 xfail | PR／回報記錄 |
