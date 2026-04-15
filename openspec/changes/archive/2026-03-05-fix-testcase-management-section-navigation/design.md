## Context

Test Case Management 頁面右側有一個 section 列表面板，使用者可以點擊 section 來篩選並導航到該 section 的 test cases。目前存在一個 bug：點擊 section 時，系統無法穩定地跳轉到對應的 test case 區塊。

### 問題分析 / Problem Analysis

經過程式碼檢視，發現問題出在 `scrollToAndExpandSection()` 函數（位於 `app/static/js/test-case-section-list.js:673`）：

1. **Timing Issue**: 函數使用固定的 `setTimeout(..., 300)` 等待 DOM 更新，但這個延遲時間可能不足以讓 `renderTestCasesTable()` 完成渲染
2. **Race Condition**: `ensureSectionRendered()` 函數在 setTimeout 內被呼叫，但此時 DOM 可能尚未完全更新
3. **Event Listener Binding**: `bindEvents()` 函數在每次渲染時重新綁定事件監聽器，可能導致重複綁定或遺失

### 目前流程 / Current Flow

```
User clicks section item
  ↓
selectSection(sectionId) [test-case-section-list.js:639]
  ↓
Dispatch "sectionSelected" event
  ↓
Call scrollToAndExpandSection(sectionId)
  ↓
Expand section & ancestors
  ↓
Call renderTestCasesTable()
  ↓
setTimeout(300ms)
  ↓
ensureSectionRendered() - may not find element yet
  ↓
Try to find [data-section-id="${sectionId}"]
  ↓
scrollIntoView() - may fail silently
```

## Goals / Non-Goals

**Goals:**
- 修正 section 導航功能，確保點擊 section 時能穩定跳轉到對應的 test case 區塊
- 改善事件監聽器綁定邏輯，避免記憶體洩漏和重複綁定
- 確保在動態載入和大量 test cases 的情況下，導航功能仍然正常運作

**Non-Goals:**
- 不改變 section 導航的視覺設計或 UI/UX
- 不修改後端 API 或資料庫結構
- 不新增額外的導航功能（例如麵包屑導航）

## Decisions

### Decision 1: 使用 MutationObserver 取代固定延遲

**選擇**: 使用 `MutationObserver` 監聽 DOM 變化，等待目標 section 元素出現後再執行滾動

**原因**:
- 固定延遲（300ms）不可靠，在慢速網路或大量資料時可能不足
- `MutationObserver` 能精確檢測 DOM 變化，避免過早或過晚執行滾動
- 更符合現代 JavaScript 最佳實踐

**替代方案**:
- 增加延遲時間（例如 500ms）→ 不可靠，仍可能有競爭條件
- 使用 `setInterval` 輪詢 → 效能較差，需要額外的清理邏輯

### Decision 2: 改善事件監聽器綁定

**選擇**: 使用事件委派（event delegation）模式，將點擊事件監聽器綁定到父容器而非每個 section item

**原因**:
- 避免在每次渲染時重新綁定大量事件監聽器
- 動態新增的 section items 自動支援點擊事件
- 減少記憶體使用和潛在的記憶體洩漏

**替代方案**:
- 維持現有方式，但在綁定前先移除舊監聽器 → 需要追蹤監聽器，較複雜
- 使用 `once: true` 選項 → 需要每次渲染後重新綁定

### Decision 3: 增強錯誤處理和日誌

**選擇**: 在關鍵路徑增加更詳細的 console.log 和錯誤處理

**原因**:
- 目前的 console.warn 訊息有助於除錯，但需要更多上下文
- 在生產環境中可以透過日誌快速定位問題
- 不影響使用者體驗（僅在開發者工具中顯示）

## Risks / Trade-offs

### Risk 1: MutationObserver 可能在極端情況下逾時
**風險**: 如果 `renderTestCasesTable()` 發生錯誤或資料載入失敗，MutationObserver 可能永遠等待
**緩解措施**: 設定最大等待時間（例如 5 秒），逾時後顯示警告訊息並停止觀察

### Risk 2: 事件委派可能影響其他互動
**風險**: 如果 section item 內有其他可點擊元素（例如編輯按鈕），事件委派需要正確處理事件冒泡
**緩解措施**: 在事件處理器中檢查 `e.target.closest('.section-toggle')` 等特殊元素，避免誤觸導航

### Risk 3: 現有事件監聽器可能未正確清理
**風險**: 修改事件綁定邏輯後，舊的監聽器可能仍然存在
**緩解措施**: 在 `bindEvents()` 開始時先移除所有舊監聽器，或使用 `AbortController` 管理監聽器生命週期

## Migration Plan

1. **階段 1: 實作 MutationObserver**
   - 修改 `scrollToAndExpandSection()` 函數
   - 新增 `waitForSectionElement()` 輔助函數
   - 保留原有 `setTimeout` 作為 fallback

2. **階段 2: 改善事件綁定**
   - 修改 `bindEvents()` 函數，使用事件委派
   - 測試所有 section 互動（點擊、拖曳、右鍵選單）

3. **階段 3: 測試與驗證**
   - 在開發環境測試不同資料量（10, 100, 1000+ test cases）
   - 測試不同網路速度（正常、慢速、離線後恢復）
   - 測試動態載入和懶加載場景

4. **回滾策略**
   - 如果新實作有問題，可以快速回滾到使用 `setTimeout` 的版本
   - 保留舊程式碼作為註解，方便回滾

## Open Questions

- 是否需要在滾動時加入視覺提示（例如高亮 section header 1-2 秒）？→ 建議作為後續改善，不在本次修正範圍
- 是否需要支援鍵盤導航（例如方向鍵切換 section）？→ 不在本次修正範圍
- MutationObserver 的逾時時間應該設定為多少？→ 建議 5 秒，可根據實際測試調整
