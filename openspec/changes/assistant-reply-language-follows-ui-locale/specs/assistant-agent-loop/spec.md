## ADDED Requirements

### Requirement: 回覆語言跟隨介面語系

助手產生的自然語言輸出 SHALL 跟隨使用者目前的介面語系（`en-US` / `zh-CN` / `zh-TW`，與前端 i18n 支援清單一致）。前端 MUST 於每次送出訊息與每次確認動作時提供該回合語系（`ui_locale`）；伺服器 MUST 先把該值正規化到支援語系（映射規則 MUST 與前端 `i18n.js` 的語系解析一致，含 `zh-Hant-*` / `zh-Hans-*` 形式），並以正規化後的常數字串組成語言指示，MUST NOT 把 client 原字串插入 prompt。

語言指示 MUST 於同一回合送往 LLM 的 system prompt 末端以 append 注入，且 MUST 排在 capability context 之後；MUST NOT 依賴 system prompt 模板中的任何 token（模板可由管理員編輯），MUST NOT 進入跨使用者共用的 system prompt 快取。指示內容 MUST 宣告為本回合權威、優先於 prompt 中其他語言敘述，MUST 要求即使使用者訊息為其他語言仍以介面語系回覆，並 MUST 要求識別碼（test case 編號、team／set／section／test run 名稱、工具名、API 欄位取值）保持原文不翻譯。

`ui_locale` 未提供或無法映射到支援語系時，系統 MUST 略過語言指示並退回 prompt 內的預設規則（跟隨使用者訊息語言），MUST NOT 因此拒絕該回合，也 MUST NOT 退回寫死的單一語系。confirm continuation 的語言 MUST 取自 confirm 當下的 `ui_locale`（與 MUST 取自 turn 快照的有效 team 不同——語言只影響本次產生的文字）。

#### Scenario: 介面切到英文時以英文回覆

- **WHEN** 使用者把介面語言切到 `en-US` 並送出訊息
- **THEN** 該回合送往 LLM 的 system prompt MUST 含英文撰寫的語言指示，要求一律以英文回覆
- **AND** prompt 中 MUST NOT 出現其他語系的語言指示

#### Scenario: 使用者以其他語言提問仍跟隨介面語系

- **WHEN** 介面語言為 `zh-CN`，使用者以英文輸入訊息
- **THEN** 語言指示 MUST 要求以简体中文回覆，並宣告優先於 prompt 中「跟隨使用者訊息語言」的預設規則

#### Scenario: 切換語系後下一回合即改變，且不污染共用快取

- **WHEN** 同一 process／同一對話先以 `zh-TW` 送出一則訊息，再切到 `en-US` 送出下一則
- **THEN** 兩個回合各自的 system prompt MUST 只含對應語系的語言指示，任一回合的語言指示 MUST NOT 出現在另一回合

#### Scenario: 管理員自訂 prompt 仍取得語言指示

- **WHEN** DB 內的 system prompt 模板已被管理員改寫且不含任何語言相關 token
- **THEN** 語言指示仍 MUST 出現在該回合送往 LLM 的 system prompt 末端

#### Scenario: 未提供或無法映射的語系不影響回合

- **WHEN** 請求未帶 `ui_locale`，或帶了不在支援清單內的語系（例如 `ja-JP`）
- **THEN** 系統 MUST 正常執行該回合並略過語言指示，由 prompt 內的預設規則決定語言，MUST NOT 回傳錯誤

#### Scenario: 確認動作的總結跟隨當下介面語系

- **WHEN** 使用者在確認卡出現後把介面語言切到另一個語系才按下確認
- **THEN** continuation 的語言指示 MUST 採用 confirm 當下的語系
- **AND** 該動作的目標 team MUST 仍取自 pending 所屬 turn 的快照，不受語系參數影響
