## Why

目前 Test Case Set 的篩選條件（例如單號、關鍵字）無法被直接分享，協作時接收者需要手動重輸條件，易造成誤差與溝通成本。  
Teams cannot share an exact filtered Test Case Set view, so recipients must re-enter filters manually, which is error-prone.

## Purpose

新增可分享的「篩選結果連結」能力，讓使用者快速重現同一個 Test Case Set 篩選視圖，並維持現有登入與權限保護流程。  
Introduce a shareable filtered-view link while preserving existing authentication and authorization controls.

## Requirements

### Requirement: Generate shareable filtered link
The system SHALL provide a `產生連結 (Generate Link)` action next to `套用篩選 (Apply Filter)` on the Test Case Set case management page.

#### Scenario: User generates link from current filter state
- **Given** 使用者位於某一 Test Case Set 案例管理畫面，且已輸入篩選條件
- **When** 使用者點擊 `產生連結`
- **Then** 系統顯示 modal，內容包含可直接訪問的完整連結
- **And** 該連結可重建同一個 Test Case Set 與相同篩選條件

### Requirement: Auth-gated deep link redirection
The system SHALL require authentication before rendering the filtered view from a shared link.

#### Scenario: Unauthenticated visitor opens shared link
- **Given** 使用者尚未登入
- **When** 使用者直接訪問共享連結
- **Then** 系統先導向登入流程
- **And** 登入成功後重導回原始共享連結並顯示對應篩選結果

## Non-Functional Requirements

- 連結開啟後載入體驗應與既有篩選流程一致，不新增額外等待步驟。  
- Query string encoding SHALL be deterministic and backward-compatible with existing filter parsing logic.  
- 不應暴露敏感資訊；連結僅攜帶必要篩選參數與既有可公開識別資訊。

## What Changes

- 在 Test Case Set 案例管理頁 `套用篩選` 按鍵旁新增 `產生連結` 按鍵。
- 新增 modal 顯示可複製的分享連結（含目前 set 與篩選條件）。
- 調整頁面初始化與登入後重導流程，使共享連結可在授權後重建篩選畫面。
- 非破壞性變更，無 **BREAKING** API。

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `test-case-management-ui`: Add shareable filter-link generation, modal display, and login-aware deep-link restoration for Test Case Set filtering.

## Impact

- Frontend: `app/templates/` 與 `app/static/js/test-run-management/` 相關篩選 UI/初始化流程。  
- Backend/Auth flow: 現有登入重導邏輯需確保保留共享連結 query 狀態。  
- Testing: 需補 UI/API/整合測試，涵蓋已登入與未登入訪問共享連結兩條路徑。
