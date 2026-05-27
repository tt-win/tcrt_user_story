# test-case-editor-ai-assist Specification

## Purpose
定義 QA AI Helper screen 5 testcase draft 編輯器的互動與契約。

## ADDED Requirements

### Requirement: Screen 5 draft editor MUST support per-category test_data editing
Screen 5 的 draft 編輯器 SHALL 顯示並允許編輯 `test_data: [{id, category, name, value}]`，每筆提供 category 下拉、name 輸入、以及依 category 調整的 value 輸入元件（復用 `app/static/js/common/test-data-utils.js` 的 per-category 規則）。

#### Scenario: Draft shows AI-generated test_data
- **WHEN** 使用者開啟一筆 Pass 2 產出的 draft
- **THEN** 編輯器顯示 AI 產出的 test_data，每筆對應 category 顯示對應的 value 輸入元件（例：credential 呈現帳密雙欄）

#### Scenario: User edits, adds or deletes test_data rows before commit
- **WHEN** 使用者在 draft 編輯器中新增、修改或刪除 test_data 列
- **THEN** 異動於 commit 時隨 draft 一併寫入對應 test case 的 `test_data_json`

#### Scenario: Empty draft test_data is allowed
- **WHEN** 某筆 draft 的 test_data 為空陣列
- **THEN** 編輯器允許儲存 / commit，對應 test case 的 `test_data_json` 寫入空陣列（或不寫入，視既有序列化邏輯）
