# test-case-editor-ai-assist Specification

## Purpose
調整既有 AI assist 能力的 UI 暴露策略：一般使用者介面不顯示 AI 改寫入口，但保留服務能力供未來恢復。Keep AI assist capability intact while removing visible end-user entry points.

## MODIFIED Requirements

### Requirement: Field-scoped AI assist actions
The system SHALL NOT display an AI assist action in the Precondition, Steps, and Expected Result toolbars in the standard test case editor UI. The AI assist capability MUST remain available in backend services without contract removal.

#### Scenario: Toolbar AI actions are not visible
- **WHEN** 使用者開啟 Test Case 編輯器 / user opens the test case editor
- **THEN** Precondition、Steps、Expected Result 區域皆不顯示 AI assist action button

#### Scenario: Backend capability remains intact
- **WHEN** 維護者使用既有 API contract 呼叫 AI assist endpoint / maintainer calls AI assist endpoint with existing contract
- **THEN** 服務仍回傳結構化改寫結果或既有錯誤格式，且不需 API schema migration

## ADDED Requirements

### Requirement: UI-hidden trigger policy
The system SHALL enforce a UI-hidden policy for AI assist in normal editor flow, and SHALL prevent direct user-trigger paths from visible controls.

#### Scenario: No direct UI trigger in normal flow
- **WHEN** 使用者在一般編輯流程檢視頁首、欄位工具列與常用操作區 / user checks editor header, field toolbars, and common action areas
- **THEN** 不存在可直接開啟 AI assist modal 的可見控制元件

### Requirement: Re-enable readiness without service rewrite
The system SHALL allow future re-enable of AI assist UI by frontend-level changes, and SHALL NOT require rewriting backend AI assist logic for that re-enable.

#### Scenario: Future UI re-enable path
- **WHEN** 團隊決定重新開放 AI 改寫 UI / team decides to re-enable AI rewrite UI
- **THEN** 可透過前端入口調整恢復能力，並沿用既有 API 與 prompt pipeline
