## Why

目前 Test Case 編輯 UI 直接暴露「AI 改寫 / AI Rewrite」按鈕，造成部分團隊在尚未完成內部流程治理前就能觸發 AI 流程。We need to hide all AI rewrite entry buttons in UI now, while preserving backend capability for controlled future re-enable.

## What Changes

- 移除（或隱藏）所有終端使用者可見的「AI 改寫 / AI Rewrite」按鈕與可直接開啟 AI modal 的 UI 入口。
- 保留既有 `/ai-assist` 後端 API、prompt 規則、語言判斷與錯誤處理能力，不進行刪除。
- 將前端行為改為「無可見入口時不得觸發 AI assist flow」；既有按鈕文案可保留於 i18n，不作破壞性移除。
- 更新規格以明確區分「UI exposure」與「service capability」。

## Capabilities

### New Capabilities
- `ai-assist-ui-exposure-control`: Define that AI assist visibility in UI can be disabled without removing backend service capability.

### Modified Capabilities
- `test-case-editor-ai-assist`: Change requirements from always-visible toolbar action to hidden UI entry while preserving API behavior and future recoverability.

## Impact

- Affected specs: `test-case-editor-ai-assist` (modified), `ai-assist-ui-exposure-control` (new).
- Affected code: `app/templates/test_case_management.html`, `app/static/js/test-case-management/ai-assist.js`, `app/static/locales/*` (optional cleanup), no breaking API change in `app/api/test_cases.py`.
- No dependency or database schema changes.

## Purpose

在不移除 AI 能力的前提下，先移除 UI 入口，降低誤觸與治理風險；後續可透過小幅 UI 調整快速恢復。Hide UI triggers now, retain service capability for future controlled rollout.

## Requirements

### Requirement: UI-hidden AI rewrite entry
The system SHALL NOT display AI rewrite buttons or direct AI assist entry actions in the test case editing UI.

#### Scenario: User opens test case editor
- **WHEN** 使用者開啟 Test Case 編輯畫面 / user opens the editor
- **THEN** 畫面不顯示 AI 改寫按鈕且無直接入口 / no visible AI rewrite button or direct entry is available

### Requirement: Capability preservation
The system SHALL keep AI assist backend endpoint and business logic available for future controlled UI re-enable.

#### Scenario: API remains available
- **WHEN** 維護者檢查既有 AI assist API 與服務 / maintainer verifies existing AI assist service
- **THEN** 端點與核心邏輯仍可運作且未被刪除 / endpoint and core logic remain intact

## Non-Functional Requirements

- Backward compatibility: No **BREAKING** API change for existing server routes.
- Maintainability: UI hiding change should be localized to template/static assets.
- Safety: No schema migration, no credential/config handling changes.
