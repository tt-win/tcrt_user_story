# Change: Fix test run execution filter panel toggle

## Why
目前點擊 executionFilterToggle 不會出現 filter panel，因為頁面缺少對應的 panel DOM，導致初始化直接 return、事件未綁定。
同時現有篩選功能無法在 panel 內針對 section 做篩選，使用上缺少必要的控制入口。

## What Changes
- 在 test run execution 頁面補上 filter panel 的 HTML 結構與必要的 element IDs
- 確保 panel 能被 toggle、關閉（點擊外部/ESC/關閉按鈕）並可與既有 JS 事件正確連動
- 在 filter panel 內新增 section 篩選入口，並與既有 section 篩選邏輯連動

## Impact
- Affected specs: test-run-execution-ui
- Affected code: app/templates/test_run_execution.html
