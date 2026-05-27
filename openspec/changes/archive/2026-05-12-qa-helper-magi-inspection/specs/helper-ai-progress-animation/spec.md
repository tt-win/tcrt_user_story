## ADDED Requirements

### Requirement: MAGI animation MUST display real-time status of three extraction models
MAGI 過場動畫 SHALL 同時顯示三個低階角色模型的即時狀態，每個模型面板包含模型標籤（label）、角色名稱（role_name）與當前狀態。

#### Scenario: Three model panels are shown during Phase 1
- **WHEN** MAGI inspection Phase 1 開始執行
- **THEN** 前端顯示三個模型面板，各自標示模型 label 與角色名稱

#### Scenario: Individual model status updates in real time
- **WHEN** 某個低階模型完成或失敗
- **THEN** 該模型面板即時更新為「完成」或「失敗」狀態，其他面板不受影響

### Requirement: MAGI animation MUST indicate current phase
MAGI 動畫 SHALL 清楚標示當前所在階段（Phase 1: Extraction / Phase 2: Consolidation），讓使用者了解整體進度。

#### Scenario: Phase indicator shows extraction during Phase 1
- **WHEN** 系統正在執行 Phase 1 extraction
- **THEN** 動畫顯示當前為 Phase 1 Extraction 階段

#### Scenario: Phase indicator transitions to consolidation
- **WHEN** 所有 Phase 1 呼叫完成，Phase 2 開始
- **THEN** 動畫過渡到 Phase 2 Consolidation 階段顯示

### Requirement: MAGI animation MUST follow Evangelion MAGI visual style
MAGI 動畫的視覺風格 SHALL 參考 Evangelion MAGI 系統，包含三系統並列面板、狀態指示燈與決策過程的動態呈現。

#### Scenario: Animation renders three-panel MAGI layout
- **WHEN** inspection 流程啟動
- **THEN** 前端渲染仿 MAGI 三系統並列佈局（MELCHIOR / BALTHASAR / CASPER 對應三個角色模型）

#### Scenario: Animation uses MAGI-themed color scheme and typography
- **WHEN** MAGI 動畫元件渲染
- **THEN** 使用符合 MAGI 主題的配色方案與字型風格

### Requirement: AI thinking animation MUST display during seed and testcase generation
Seed 產生與 testcase 產生流程中 SHALL 顯示「AI 思考中...」動畫，讓使用者知道系統正在處理。

#### Scenario: Thinking animation appears during seed generation
- **WHEN** 系統開始 seed generation LLM 呼叫
- **THEN** 前端顯示「AI 思考中...」動畫

#### Scenario: Thinking animation appears during testcase generation
- **WHEN** 系統開始 testcase generation LLM 呼叫
- **THEN** 前端顯示「AI 思考中...」動畫

#### Scenario: Thinking animation dismisses on completion or failure
- **WHEN** LLM 呼叫完成或失敗
- **THEN** 思考動畫消失，顯示結果或錯誤訊息

### Requirement: Progress animations MUST not block user interaction
所有進度動畫（MAGI 過場與 AI 思考）SHALL 不阻擋使用者的基本互動能力。

#### Scenario: User can cancel during MAGI animation
- **WHEN** MAGI inspection 動畫進行中
- **THEN** 使用者可透過取消按鈕中止流程

#### Scenario: Page remains responsive during animation
- **WHEN** 任何進度動畫正在播放
- **THEN** 頁面不產生凍結或無回應狀態
