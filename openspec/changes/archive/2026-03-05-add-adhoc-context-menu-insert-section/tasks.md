## 1. Context Menu Actions（右鍵選單操作）

- [x] 1.1 Refactor Handsontable context menu config to include custom section insertion actions（調整 Handsontable 右鍵選單設定，加入 section insertion 自訂項目）
- [x] 1.2 Add `Insert section above` action that inserts a section row above selected row（新增 `Insert section above`，在選取列上方插入 section）
- [x] 1.3 Add `Insert section below` action that inserts a section row below selected row（新增 `Insert section below`，在選取列下方插入 section）

## 2. Shared Section Logic & Read-only Guard（共用 section 邏輯與唯讀保護）

- [x] 2.1 Extract reusable section-row payload builder shared by toolbar and context menu（抽出可重用的 section row payload，供工具列與右鍵共用）
- [x] 2.2 Reuse existing merge/render/save flow after context-menu insertion（右鍵插入後沿用既有 merge/render/save 流程）
- [x] 2.3 Ensure read-only mode hides or disables context-menu insertion actions（確認唯讀模式不顯示或不可用 section insertion actions）

## 3. Localization & Verification（多語系與驗證）

- [x] 3.1 Add locale keys for context-menu section insertion labels in zh-TW/en-US/zh-CN（新增右鍵 section 插入文案的多語系 key）
- [x] 3.2 Verify editable and read-only scenarios for both above/below insertion actions（驗證可編輯與唯讀情境下的上/下插入行為）
- [x] 3.3 Run targeted regression checks for existing Add Section, row operations, and autosave behavior（執行既有 Add Section、列操作與 autosave 的回歸檢查）
