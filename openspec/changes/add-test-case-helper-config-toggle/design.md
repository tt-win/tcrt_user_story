# Design: AI Agent Test Case Helper Config Toggle

## Context

目前 Test Case Set 管理畫面（`test_case_set_list.html`）頂部有「AI Agent - Test Case Helper」按鈕（`openAiHelperFromSetListBtn`），始終顯示。config 中 `ai.jira_testcase_helper` 已有多項 LLM 相關設定，但無入口可見性開關。部署者需要能在未配置或不想啟用此功能時隱藏該按鈕。

## Goals / Non-Goals

**Goals:**
- 透過 config 單一布林欄位控制 Test Case Helper 入口按鈕顯示
- 預設保持現有行為（按鈕可見）
- 無需 DB 遷移、無需前端 build 流程變更

**Non-Goals:**
- 不修改後端 API 行為（`enable=false` 時仍可被內部/測試呼叫）
- 不控制 Test Case Management 頁面內其他 AI 相關 UI（該頁面目前無 Test Case Helper 按鈕）
- 不新增權限或 RBAC 層級控制

## Decisions

### 1. Config 欄位位置與預設值

- **決策**：在 `ai.jira_testcase_helper` 下新增 `enable: bool = True`
- **理由**：與既有 helper 設定同處，語意清楚；預設 true 維持向後相容
- **替代**：頂層 `ai.test_case_helper_enabled` — 拒絕，因與 helper 設定分離會增加維護成本

### 2. 前端渲染方式

- **決策**：後端傳入 `ai_helper_enabled` 至 template context，Jinja2 條件渲染按鈕區塊
- **理由**：與既有 `helper_mode` 傳遞模式一致；無需額外 API 或 JS 邏輯
- **替代**：前端 JS 透過 API 取得 config — 拒絕，會暴露 config 結構且增加請求

### 3. 按鈕區塊處理

- **決策**：以 `{% if ai_helper_enabled %}` 包裹整個 `openAiHelperFromSetListBtn` 按鈕
- **理由**：隱藏時不佔版面；若未來該區有其他按鈕，可改為包裹單一按鈕
- **替代**：CSS `display:none` — 拒絕，按鈕仍存在 DOM，較不乾淨

## Risks / Trade-offs

| 風險 | 緩解 |
|------|------|
| 舊 config 無 `enable` 欄位 | Pydantic 預設 `True`，舊 config 自動相容 |
| 部署後需重啟才生效 | 與既有 config 載入方式一致，文件說明即可 |
