# Delta Spec — automation-hub-script-management

> 對 `openspec/specs/automation-hub-script-management/spec.md` 的 delta，記錄「拿掉 Script preview 的 Run Now 按鈕、Suite detail 的 Run Suite 與 Run this script only 按鈕」對既有 requirement 的影響。

## REMOVED Requirements

### Requirement: Script preview MUST surface recent runs and quick-run button

**Reason for removal**：「Run Now」按鈕對應的 trigger 端點已於 `move-automation-execution-to-test-run-set` 移除；preview 內的 trigger CTA 整段無對應 endpoint，僅保留 Recent Runs 區段（見下方 ADDED）。

**原本內容**（節錄自既有 spec）：

Script preview SHALL 顯示「Recent Runs」與「Run Now」按鈕（modal 觸發 workflow / branch / runner / inputs 選擇）。

#### Scenario: Quick run from suite context
- **WHEN** 使用者於 suite detail 或展開的 script preview 中點 Run Now、確認 modal
- **THEN** API 觸發 run，UI 立即跳轉到 run detail 頁

### Requirement: Suite detail MUST provide Run Suite button

**Reason for removal**：Automation Hub 不再對外暴露 suite 觸發。Suite detail 頁的「Run Suite」按鈕整段移除；觸發入口統一由 Test Run Set 接管。

**原本內容**（節錄自既有 spec）：

Suite detail 頁 SHALL 有「Run Suite」CTA，點擊觸發 `POST .../automation-script-groups/{group_id}/runs`。

### Requirement: Suite detail MUST provide Run this script only button

**Reason for removal**：連同 `remove-single-script-run` 一併移除的「Run this script only」按鈕（從未實作於此 spec，但作為 UI 設計意圖在 archive 前也明確剔除）。

---

## MODIFIED Requirements

### Requirement: Script preview UI MUST be embedded in Suites tab context

Script preview 嵌入 SHALL 改為 read-only：場景 1（Suites tab 檔案樹展開）刪除「Run Now」按鈕，頂端 SHALL 顯示引導訊息「To run this script, add its suite to a Test Run Set.」；場景 2（Suite detail 內的 script 列表）刪除「Run Now」與「Run this script only」按鈕，SHALL 顯示「To run this suite, use a Test Run Set.」；場景 3（Case detail Automation 面板）SHALL 移除 preview 內隱含的 trigger 段，保留 read-only 預覽與最近 runs。

#### Scenario: Script preview without any trigger CTA
- **WHEN** 使用者於任何場景展開 script preview
- **THEN** preview 區 SHALL NOT 包含「Run Now」「執行」「Run」等 trigger CTA
- **AND** 頂端 SHALL 顯示「To run this script, add its suite to a Test Run Set.」
- **AND** 若 user 想觸發：引導到 Test Run Set（訊息內含「Test Run Set」連結 / 按鈕，導向 Test Run Management 頁）

#### Scenario: Suite detail without Run Suite button
- **WHEN** 使用者進入 suite detail 頁
- **THEN** 頁面 SHALL NOT 包含「Run Suite」按鈕
- **AND** SHALL 顯示引導訊息：「To run this suite, add it to a Test Run Set's Automation Suites.」+「Go to Test Run Set」CTA

---

## ADDED Requirements

### Requirement: Script preview MUST surface recent runs (read-only) with no trigger CTA

Script preview SHALL 顯示「Recent Runs」（最近 5 筆，showing status / started_at），**read-only** 顯示，**不再提供任何 trigger CTA**（Run Now / 執行 / Run 按鈕）。Preview 區頂端 SHALL 顯示引導訊息：「To run this script, add its suite to a Test Run Set.」

#### Scenario: Read-only run history in script preview
- **WHEN** 使用者展開 script preview
- **THEN** 顯示該 script 關聯的歷史 runs（**僅** history，無 trigger CTA）
- **WHEN** 該 script 從未執行（無 `automation_runs.automation_script_id` 對應）
- **THEN** preview SHALL 顯示「No runs yet. Add this suite to a Test Run Set to run it.」訊息

### Requirement: Suite detail MUST redirect to Test Run Set for execution

Suite detail 頁 SHALL 在無觸發 CTA 的同時，提供顯眼的「Run in Test Run Set」引導：列出（或連結到）當前已包含此 suite 的 Test Run Set 列表，讓 user 一鍵跳轉到 Test Run Set detail 觸發。

#### Scenario: Suite detail surfaces linked Test Run Set
- **WHEN** 使用者進入 suite detail 頁
- **THEN** 頁面 SHALL 顯示「Linked Test Run Sets」section，列出所有 `automation_suite_ids` 含此 suite 的 Test Run Set（顯示 set name + 連結）
- **WHEN** 該 suite 未被任何 Test Run Set 引用
- **THEN** 顯示「This suite is not yet linked to any Test Run Set.」+「Create a Test Run Set」CTA（若有權限）
