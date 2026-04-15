# Capability: Helper Prompt File Loading

## Purpose

定義 QA AI Agent / Test Case Helper 的 prompt 來源與 model routing 契約，確保 prompt file-backed、stage 分工清楚且 fallback 可預測。

## Requirements

### Requirement: Helper prompts MUST be loaded from Markdown files per AI stage

系統 SHALL 從 `prompts/jira_testcase_helper/*.md` 載入各 AI 階段 prompt，而非把 prompt 內嵌在 `config.yaml`。

#### Scenario: Load prompt template for seed generation
- **WHEN** helper 準備 screen-4 的 seed generation prompt
- **THEN** 讀取對應的 markdown prompt file

#### Scenario: Load prompt template for testcase generation
- **WHEN** helper 準備 screen-5 的 testcase generation prompt
- **THEN** 讀取 `testcase.md` 或配置對應的 prompt file

### Requirement: Model routing MUST separate seed generation and testcase generation

系統 SHALL 將 prompt source 與 model source 分離，並允許 `seed`、`seed_refine`、`testcase` 使用不同模型與溫度設定。

#### Scenario: Parse helper configuration for staged generation
- **WHEN** 設定從 `config.yaml` 載入
- **THEN** helper 可解析不同 stage 的模型設定而不依賴 inline prompt blocks

#### Scenario: Environment variables override staged model routing
- **WHEN** `.env` 或 process environment 提供對應 stage model 覆寫
- **THEN** helper 使用環境變數值取代 YAML 預設

#### Scenario: Unresolved placeholder fails fast
- **WHEN** 設定引用不存在的環境變數 placeholder
- **THEN** settings loading 直接失敗，不把 placeholder 當成真實模型名

#### Scenario: Seed refinement model falls back to seed model
- **WHEN** 未設定專屬 `seed_refine` model
- **THEN** helper 回退使用 `seed` model

#### Scenario: Default stage temperatures favor stability
- **WHEN** 未提供顯式溫度設定
- **THEN** 系統使用偏穩定輸出的低溫預設值

### Requirement: Missing prompt files MUST have deterministic fallback

若 seed、seed_refine 或 testcase 的 prompt file 缺失或為空，系統 SHALL 使用 deterministic fallback template 並記錄 warning。

#### Scenario: Missing seed refinement prompt file
- **WHEN** seed refinement prompt file 缺失
- **THEN** helper 使用內建 fallback template 並寫入 warning log
