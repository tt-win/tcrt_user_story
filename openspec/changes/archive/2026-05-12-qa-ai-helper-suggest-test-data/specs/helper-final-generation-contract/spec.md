# helper-final-generation-contract Specification

## Purpose
定義 QA AI Agent 從 seed generation、seed review 到 testcase generation 與 commit 的最終契約。

## ADDED Requirements

### Requirement: Seed generation MUST output test_data_suggestions per seed under strict criteria
Seed 生成 SHALL 在每個 seed 的 `seed_body_json` 內輸出 `test_data_suggestions: [{id, category, name}]`。僅當 seed 所屬需求或驗證條件明確指出需要輸入 / 參考的資料欄位時才產生建議；spec 不明確或不涉及輸入資料的 seed SHALL 輸出空陣列而非硬湊。

`category` SHALL 為以下之一：`text | number | credential | email | url | identifier | date | json | other`。

#### Scenario: Seed with clear input field yields a suggestion
- **WHEN** seed 對應到「登入帳號長度 ≤ 20」的需求
- **THEN** 該 seed 的 `test_data_suggestions` 至少包含 `{category: "credential", name: "登入帳號"}` 一筆

#### Scenario: Seed without input spec yields empty array
- **WHEN** seed 僅驗證純 UI 顯示邏輯（例：按鈕顏色）
- **THEN** 該 seed 的 `test_data_suggestions` 為 `[]`

#### Scenario: Seed body persists the suggestions alongside text body
- **WHEN** 系統將 seed 寫入 `qa_ai_helper_seed_items.seed_body_json`
- **THEN** JSON 包含原有的 `text` 與新的 `test_data_suggestions` 兩個 key

### Requirement: Seed review MUST allow adding, editing and deleting test_data suggestions
Seed review 介面 SHALL 允許使用者對任一未 lock 的 seed 增加、修改（category / name）、刪除 test_data 建議。

#### Scenario: User adds a new suggestion
- **WHEN** 使用者在 seed review 點擊「新增建議」並填入 category 與 name
- **THEN** 該筆建議持久化至該 seed 的 `test_data_suggestions`，並於後續 Pass 2 使用

#### Scenario: User deletes an AI-generated suggestion
- **WHEN** 使用者點擊某筆 AI 建議旁的刪除 icon
- **THEN** 該筆被從 `test_data_suggestions` 移除，後續 Pass 2 不再輸出對應 test_data

#### Scenario: Locked seed set blocks suggestion edits
- **WHEN** seed set 已 lock
- **THEN** UI 的 test_data suggestion 編輯控制項為 readonly，後端拒絕變更

### Requirement: Testcase generation MUST output test_data shaped by seed suggestions with strict value rules
Testcase 生成 SHALL 將 seed 最終的 `test_data_suggestions`（含使用者編輯結果）作為骨架，輸出 `test_data: [{id, category, name, value}]`。

Value 產生規則：
- 需求或 seed 明確指出邊界值、magic number、spec 帳號 / URL / 錯誤碼 / enum → 填入對應 value
- 其它情況 → value 為空字串
- `category == "credential"` → value SHALL 一律為空字串（不論需求提供與否）

#### Scenario: Boundary value is filled from explicit spec
- **WHEN** seed 建議 `{category: "number", name: "密碼長度"}` 且需求寫「長度 ≤ 8」
- **THEN** 對應 testcase 的 test_data 其中一筆 value 為「8」或「9」等邊界代表值

#### Scenario: Credential value stays empty even when spec hints a value
- **WHEN** seed 建議 `{category: "credential", name: "登入帳號"}` 且需求文字提到範例帳號
- **THEN** 對應 testcase 的 test_data 該筆 value 為空字串

#### Scenario: Unclear field yields empty value
- **WHEN** seed 建議某欄位但需求未指定具體值
- **THEN** 對應 testcase 的 test_data 該筆 value 為空字串

### Requirement: Testcase draft body MUST persist test_data and commit writes it to test case
Testcase draft `body_json` SHALL 包含 `test_data` 欄位；commit 階段 SHALL 將該陣列寫入目標 test case 的 `test_data_json`。

#### Scenario: Draft includes test_data in body_json
- **WHEN** Pass 2 產出一筆 testcase draft
- **THEN** `qa_ai_helper_testcase_drafts.body_json` 的 JSON 包含 `test_data` key（可為空陣列）

#### Scenario: Commit propagates test_data to test case
- **WHEN** 使用者 commit 被選取的 drafts
- **THEN** 目標 test case 的 `test_data_json` 以 draft 的 `test_data` 覆蓋寫入

### Requirement: Legacy seeds and drafts without the new fields MUST be handled with empty defaults
系統 SHALL 在解析舊 seed / draft 時，若缺少 `test_data_suggestions` 或 `test_data`，以空陣列作為預設值，不拋出錯誤。

#### Scenario: Old seed without suggestions renders as empty list
- **WHEN** 使用者開啟一個在本 change 前產生的 seed
- **THEN** seed review UI 的 test_data suggestions 區塊為空清單，且可由使用者新增
