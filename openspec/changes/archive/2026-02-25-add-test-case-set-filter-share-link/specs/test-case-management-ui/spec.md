## ADDED Requirements

### Requirement: Shareable filtered view link for Test Case Set
系統 SHALL 在 Test Case Set 案例管理頁提供 `產生連結 (Generate Link)` 功能，並以目前頁面的 set 識別與篩選條件（例如 case id、keyword、其他既有 filter 欄位）組成可直接訪問的連結。

#### Scenario: Generate link from current filter state
- **WHEN** 使用者在 Test Case Set 案例管理頁設定篩選條件後點擊 `產生連結`
- **THEN** 系統顯示 modal 並呈現可複製的完整連結
- **AND** 該連結包含目前 set 與當下篩選參數，直接訪問後可重建相同篩選結果

### Requirement: Auth-gated deep link restoration for shared filters
系統 SHALL 在共享連結被訪問時套用既有驗證與授權流程；未登入者 MUST 先登入，且登入後 MUST 回到原共享連結並呈現對應篩選結果。

#### Scenario: Unauthenticated visitor is redirected through login
- **WHEN** 未登入使用者直接開啟共享連結
- **THEN** 系統先導向登入頁
- **AND** 使用者登入成功後，系統回到原共享連結 URL 並顯示對應 Test Case Set 篩選畫面

#### Scenario: Authenticated visitor opens shared link directly
- **WHEN** 已登入且具備該 Test Case Set 存取權限的使用者開啟共享連結
- **THEN** 系統直接載入指定 Test Case Set
- **AND** 系統自動套用連結中的篩選條件並顯示篩選後結果
