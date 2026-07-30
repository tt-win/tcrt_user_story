# data-view-states Specification Delta

本 delta 建立新能力 `data-view-states`，規範所有呈現伺服器資料的視圖在載入、無資料、失敗與有資料四種情況下的行為契約，並涵蓋選取相依動作的啟用規則與非阻塞式確認。

## ADDED Requirements

### Requirement: Every data section renders an explicit state

任何呈現伺服器資料的區段 SHALL 在任何時刻呈現 loading、content、empty 或 error 其中之一的可見內容。SHALL 不存在既無資料、亦無載入中、亦無說明的空白區域。未被明確處理的情況 SHALL 落入 error 狀態，SHALL 不得落入 empty。

由多個獨立資料來源組成的視圖，SHALL 以區段為單位各自滿足本需求；單一區段降級 SHALL 不使其他已成功的區段停止呈現。已取得部分資料的區段 SHALL 呈現 content 並附明確的降級說明，SHALL 不呈現為完整 content，亦 SHALL 不整段改呈現為 error。

#### Scenario: No unexplained blank region

- **WHEN** 任一資料區段完成初始渲染
- **THEN** 該區段 SHALL 呈現 loading、content、empty 或 error 其中之一的可見內容
- **AND** SHALL 不呈現無任何說明的空白區域

#### Scenario: Unhandled condition falls back to error

- **WHEN** 資料區段遇到未被明確處理的情況
- **THEN** 該區段 SHALL 進入 error 狀態
- **AND** SHALL 不呈現為 empty 狀態

#### Scenario: Request failure does not read as no data

- **WHEN** 資料請求失敗
- **THEN** 該區段 SHALL 呈現 error 狀態
- **AND** SHALL 不呈現「沒有資料」的訊息

#### Scenario: Partial data renders content with a degradation notice

- **WHEN** 區段只取得部分資料（例如上游來源之一不可用）
- **THEN** 該區段 SHALL 呈現已取得的內容
- **AND** SHALL 附上說明資料不完整的可見提示
- **AND** 同一視圖中其他已成功的區段 SHALL 繼續正常呈現

#### Scenario: Silent early return is not an acceptable state

- **WHEN** 載入流程因前置條件不足而提前結束（例如缺少 team 脈絡）
- **THEN** 該區段 SHALL 呈現說明該前置條件的 empty 或 error 狀態
- **AND** SHALL 不僅寫入 console 後維持初始空白

### Requirement: Empty state explains the cause and offers a next step

Empty 狀態 SHALL 說明為何沒有資料，並在使用者具備對應權限時提供可執行的下一步入口。無權限的情況 SHALL 以具名的 error 情況呈現，SHALL 不與 empty 混用。

#### Scenario: Empty state is actionable

- **WHEN** 資料視圖進入 empty 狀態且使用者具備建立權限
- **THEN** 該狀態 SHALL 說明為何是空的
- **AND** SHALL 提供建立或匯入的入口

#### Scenario: Insufficient permission is distinct from empty

- **WHEN** 使用者無權限檢視該資料
- **THEN** 該視圖 SHALL 呈現具名的權限不足訊息
- **AND** SHALL 不呈現為 empty 狀態

### Requirement: Error state is recoverable inline

Error 狀態 SHALL 於視圖內呈現可讀訊息與重試入口。系統 SHALL 不以僅寫入 console 的方式處理使用者可見的載入失敗。

#### Scenario: Inline error with retry

- **WHEN** 資料視圖進入 error 狀態
- **THEN** 該視圖 SHALL 於原位呈現可讀的失敗說明
- **AND** SHALL 提供重試入口

#### Scenario: Failures are not silent

- **WHEN** 使用者可見的資料載入失敗
- **THEN** 系統 SHALL 於介面呈現該失敗
- **AND** SHALL 不僅將訊息寫入 console

### Requirement: Loading state preserves layout shape

版面形狀已知的資料視圖（表格列、卡片列表）SHALL 以骨架（skeleton）呈現載入中狀態，維持與最終內容一致的版面形狀。形狀未知的等待或單一動作的等待 MAY 使用 spinner。

#### Scenario: Known-shape views use skeletons

- **WHEN** 表格或卡片列表進入 loading 狀態
- **THEN** 該視圖 SHALL 呈現與最終內容形狀一致的骨架
- **AND** 版面 SHALL 不因載入完成而塌陷或跳動

### Requirement: Selection-dependent actions are disabled without a selection

需要選取目標才可執行的動作 SHALL 在無選取時為 disabled，並套用統一的 disabled 呈現。此規則 SHALL 適用於單選詳情面板與多選批次工具列。

#### Scenario: Detail panel actions require a selection

- **WHEN** 主從式版面的詳情區未選取任何項目
- **THEN** 該區內需要目標的動作（例如刪除、重設密碼）SHALL 為 disabled

#### Scenario: Batch actions require at least one selected item

- **WHEN** 批次工具列的已選取數量為零
- **THEN** 批次動作 SHALL 為 disabled

### Requirement: Confirmation and notification are non-blocking

確認與通知 SHALL 使用系統內的非阻塞式元件呈現，並套用一致的樣式與在地化。系統 SHALL 不使用 `window.alert()` 或 `window.confirm()`。

#### Scenario: No native dialogs remain

- **WHEN** 任一前端流程需要確認或通知使用者
- **THEN** 該流程 SHALL 使用系統內的非阻塞式元件
- **AND** 前端程式碼 SHALL 不存在 `window.alert()` 或 `window.confirm()` 的呼叫路徑

#### Scenario: Destructive confirmation states the impact

- **WHEN** 使用者觸發破壞性動作
- **THEN** 確認元件 SHALL 說明受影響的目標與數量
- **AND** SHALL 在使用者明確確認後才執行
