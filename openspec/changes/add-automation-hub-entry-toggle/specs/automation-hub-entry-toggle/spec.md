## ADDED Requirements

### Requirement: Org-level toggle controls Automation Hub entry visibility

系統 SHALL 依一個組織層級設定值（Automation Hub 入口開關）控制 Automation Hub 入口在 team card 上的顯示與隱藏。受控的入口包含：團隊管理「進入團隊」下拉選單中的「Automation Hub」項目，以及首頁 team card 上的「Automation Hub」按鈕。

#### Scenario: Entry points visible when enabled
- **WHEN** 開關設定為 `true`（開啟）
- **THEN** 首頁 team card 顯示「Automation Hub」按鈕
- **AND** 團隊管理「進入團隊」選單顯示「Automation Hub」項目

#### Scenario: Entry points hidden when disabled
- **WHEN** 開關設定為 `false`（關閉）
- **THEN** 首頁 team card 不顯示「Automation Hub」按鈕
- **AND** 團隊管理「進入團隊」選單不顯示「Automation Hub」項目

#### Scenario: Default enabled preserves existing visibility
- **WHEN** 尚未設定過開關（設定值不存在）
- **THEN** 系統視為 `true`（開啟），維持既有顯示行為

### Requirement: Super Admin manages the toggle from org automation infra tab

系統 SHALL 於「團隊管理 → 同步組織架構 → 組織自動化基礎設施」分頁提供開關 UI，且僅 Super Admin 可變更其狀態。變更 SHALL 即時持久化（runtime-mutable），並於下次讀取時生效。

#### Scenario: Super Admin sees current state
- **WHEN** Super Admin 開啟「組織自動化基礎設施」分頁
- **THEN** 開關 UI 反映目前持久化的開關狀態

#### Scenario: Super Admin toggles the switch
- **WHEN** Super Admin 將開關切到「關閉」並儲存
- **THEN** 系統持久化 `false`
- **AND** 後續讀取回傳 `false`

#### Scenario: Non-super-admin cannot change the toggle
- **WHEN** 非 Super Admin 嘗試呼叫寫入端點
- **THEN** 系統以 403 拒絕，且開關狀態不變

### Requirement: Toggle state readable by any authenticated user

系統 SHALL 提供讀取端點讓任何已登入使用者取得開關狀態，使首頁與團隊管理頁面可在所有角色下決定入口可見性。未登入的請求 SHALL 被拒絕。

#### Scenario: Authenticated user reads state
- **WHEN** 已登入使用者（任一角色）請求開關狀態
- **THEN** 系統回傳目前開關狀態（缺漏時為預設開啟）

#### Scenario: Unauthenticated request rejected
- **WHEN** 未登入的請求呼叫讀取端點
- **THEN** 系統以未授權錯誤拒絕

### Requirement: Capability retained under hidden mode

當開關為關閉（入口隱藏）時，系統 SHALL 仍保留 Automation Hub 後端能力：`/automation-hub` 頁面與 automation 相關 API 不因開關關閉而被阻擋，可由直接網址存取。

#### Scenario: Hidden mode does not block backend
- **WHEN** 開關為 `false` 且使用者以直接網址造訪 `/automation-hub` 或呼叫 automation API
- **THEN** 頁面與 API 仍正常運作（僅 team card 入口被隱藏）
