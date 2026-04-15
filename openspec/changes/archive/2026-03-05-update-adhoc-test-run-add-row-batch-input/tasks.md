## 1. UI Entry & Localization（介面入口與多語系）

- [x] 1.1 Add row-count input UI for `Add Row` action in ad-hoc execution toolbar（在 ad-hoc execution toolbar 為 `Add Row` 新增列數輸入互動）
- [x] 1.2 Add i18n keys for row-count prompt, validation message, confirm/cancel labels in zh-TW/en-US/zh-CN（補齊列數輸入與驗證文案的多語系 key）

## 2. Batch Insert Logic（批次新增邏輯）

- [x] 2.1 Refactor `onAddRow` flow to accept validated batch count instead of fixed single-row insert（重構 `onAddRow` 讓其接收驗證後的批次數量）
- [x] 2.2 Implement bounded positive-integer validation and no-op on cancel/invalid input（實作正整數與上限驗證，取消或非法輸入不變更資料）
- [x] 2.3 Keep read-only guard and trigger `handleChange` only after successful insertion（保留唯讀阻擋，僅在成功新增後觸發 `handleChange`）

## 3. Verification（驗證）

- [x] 3.1 Verify scenarios: valid batch add, cancel, invalid count, and archived read-only behavior（驗證合法新增、取消、非法輸入、唯讀阻擋情境）
- [x] 3.2 Run targeted regression checks for ad-hoc execution editing and autosave stability（執行 ad-hoc execution 編輯與自動儲存穩定性回歸檢查）
