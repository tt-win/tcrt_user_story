## Why

### Purpose
目前 team 的 default Test Case Set 是分散在多個建立與 fallback 流程中的隱含規則，admin 無法把既有 set 指定成新的預設集合。這讓團隊無法把後續「未指定 set 的預設落點」對齊實際作業方式，也讓 default policy 持續散落在多個端點中。

This change introduces a single, admin-controlled default-set policy without migrating existing Test Cases, so future default-targeted behavior becomes consistent and easier to maintain.

## What Changes

### Requirements
- 新增 admin-only 能力，允許將同一 team 內的既有 Test Case Set 設為目前 default。
- 切換後，所有「依賴 default set」的後續行為都 MUST 指向新的 default，包括未指定 set 的 Test Case 建立流程、刪除 set 時的 fallback 目標、adhoc/default resolution，以及 API/UI 的 default 標記。
- 舊的 default set 在切換後 SHALL 立即降為一般 set，並沿用既有一般 set 規則。
- 系統 MUST 確保同一 team 任一時間只有一個 default set，且目標 set 具備可用的 `Unassigned` section。
- 系統 SHALL NOT 因切換 default 而自動搬移舊 default 內既有的 Test Cases。

### Non-Functional Requirements
- default-set resolution MUST 收斂為共享後端邏輯，避免在多個 API 中各自查詢 `is_default`。
- 既有 Test Run impact preview / cleanup 行為應維持一致，只更新其使用的 default fallback target。

## Capabilities

### New Capabilities
- `team-default-test-case-set`: Admin-controlled team default Test Case Set selection and shared default-resolution behavior.

### Modified Capabilities
- `test-case-management-ui`: 在 Test Case Set 管理 UI 顯示目前 default 狀態並提供 admin 可用的切換入口與回饋。

## Impact

- Affected code: `app/api/test_case_sets.py`, `app/services/test_case_set_service.py`, `app/api/test_cases.py`, `app/api/adhoc.py`, `app/static/js/test-case-set-list/main.js`, related locales and tests.
- Affected systems: team permission boundary, Test Case fallback flows, set deletion fallback target, default-set UI state.
