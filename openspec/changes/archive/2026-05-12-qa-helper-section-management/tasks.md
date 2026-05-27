## 1. 前端 — Section 新增功能

- [x] 1.1 在 `main.js` 新增 `createEmptySection()` 工廠函式，產出符合 PlanSection data model 的空白 section object（section_key 為 `manual_{uuid}`，含一個空白 verification item 與 check condition）
- [x] 1.2 在 section rail 底部新增「新增區段」按鈕（icon + 文字），plan locked 時 disabled
- [x] 1.3 實作按鈕 click handler：呼叫 `createEmptySection()` → push 至 sections 陣列 → 呼叫 `recomputeRequirementSectionIds()` → 設定 `state.selectedPlanSectionKey` 為新 section → 標記 dirty → 重新渲染
- [x] 1.4 新增後自動 focus 到 section title input 欄位

## 2. 前端 — Section 多選刪除功能

- [x] 2.1 在 section rail 每個 section 項目前加入 checkbox（plan locked 時隱藏），維護 `state.selectedSectionKeysForDelete` Set 追蹤勾選狀態
- [x] 2.2 實作 checkbox change handler：更新 `state.selectedSectionKeysForDelete`，重新渲染 batch action bar
- [x] 2.3 在 section rail 頂部實作 batch action bar（已選 N 個區段 + 刪除按鈕），僅在有勾選時顯示
- [x] 2.4 實作刪除 click handler：彈出 confirm dialog 列出待刪 section 標題 → 確認後 filter sections 陣列移除 → 呼叫 `recomputeRequirementSectionIds()` → 清空 `state.selectedSectionKeysForDelete` → 若當前選中的 section 被刪則自動選中第一個 → 標記 dirty → 重新渲染
- [x] 2.5 處理邊界情境：刪除後無 section 時清空編輯區顯示空狀態提示

## 3. 前端 — Section 排序功能

- [x] 3.1 在 section rail 每個 section 項目右側新增上移（▲）與下移（▼）icon buttons（plan locked 時隱藏）
- [x] 3.2 實作上移 click handler：swap 當前 section 與上方相鄰 section 在 sections 陣列中的位置 → 呼叫 `recomputeRequirementSectionIds()` → 維持該 section 為選中狀態 → 標記 dirty → 重新渲染
- [x] 3.3 實作下移 click handler：swap 當前 section 與下方相鄰 section，其餘同上
- [x] 3.4 第一個 section 的上移按鈕 disabled，最後一個 section 的下移按鈕 disabled
- [x] 3.5 確認排序操作觸發 autosave timer

## 4. 前端 — CSS 樣式

- [x] 4.1 在 `qa-ai-helper.css` 新增 section checkbox 樣式（對齊 section rail item，不影響現有 click 選中行為）
- [x] 4.2 新增 batch action bar 樣式（固定於 rail 頂部，包含計數文字與刪除按鈕，配色遵循 TCRT 警告色系）
- [x] 4.3 新增「新增區段」按鈕樣式（底部固定，虛線邊框 + 加號 icon，hover 效果）
- [x] 4.4 新增上移/下移按鈕樣式（小型 icon button，hover 高亮，disabled 灰色淡化）
- [x] 4.5 使用 TCRT UI 設計規範確認整體一致性（配色、圓角、間距、字體大小）

## 5. i18n 文案

- [x] 5.1 在 `app/static/locales/` 各語系檔新增文案 key：新增區段、刪除選取區段、已選取 N 個區段、確認刪除區段、無區段提示、上移、下移等
- [x] 5.2 前端渲染程式碼中使用 i18n key 取代硬編碼文字

## 6. 後端驗證

- [x] 6.1 確認 `save_requirement_plan` service 方法正確處理新增 section（section_key 為 `manual_*` 格式、id 為 null 的新 section insert）
- [x] 6.2 確認刪除 section 後，因 FK cascade delete，相關 verification_items 與 check_conditions 自動清除
- [x] 6.3 確認 locked plan 狀態下後端拒絕含增刪 section 的 save request（若前端旁路時的防線）
- [x] 6.4 確認 section display_order 正確反映前端排序結果（save 時依陣列順序寫入 display_order）

## 7. 測試

- [x] 7.1 撰寫前端手動測試案例：新增 section → 填入資料 → autosave → 重新載入確認持久化
- [x] 7.2 撰寫前端手動測試案例：多選 3 個 section → 刪除 → 確認 section_id 重編正確
- [x] 7.3 撰寫前端手動測試案例：locked 狀態下確認新增/刪除/排序按鈕不可用
- [x] 7.4 撰寫前端手動測試案例：手動新增 section 填入 verification items → lock → 進入 seed generation → 確認 seed 正常產出
- [x] 7.5 撰寫前端手動測試案例：將第三個 section 上移兩次至第一位 → autosave → 重新載入確認順序持久化
- [x] 7.6 撰寫前端手動測試案例：確認第一個 section 上移 disabled、最後一個 section 下移 disabled
- [x] 7.7 執行既有 pytest 測試確認無 regression：`pytest app/testsuite -q`
