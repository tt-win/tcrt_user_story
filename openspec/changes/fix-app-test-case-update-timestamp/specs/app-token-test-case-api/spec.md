# app-token-test-case-api Delta Specification

## Purpose

定義 App Token 單筆 Test Case generic update 對本地 `updated_at` 的一致維護語意，讓既有更新時間消費者能觀察 API／`tcrt-app` skill 的有效內容異動。

## MODIFIED Requirements

### Requirement: Test Case Create and Update Operations
App-token API SHALL 支援建立與更新 test case，並沿用本地 test case 管理的驗證規則、default set 規則、section scope 規則與 local-only persistence。外部 app token mutation SHALL 不觸發 Lark 或其他外部 test case sync。

成功的單筆 generic update 若實際改變至少一個持久化 Test Case 欄位，系統 SHALL 在同一 transaction 刷新該案例的本地 `updated_at`。空 payload、同值重送、驗證失敗或被拒絕的 update SHALL 保留原 `updated_at`。

#### Scenario: 建立 test case
- **WHEN** token 具備 `test_case:write` 並提交有效 test case payload
- **THEN** 系統 SHALL 在指定 team 建立本地 test case
- **AND** 若 payload 未指定 set，系統 SHALL 使用該 team default test case set

#### Scenario: 更新 test case
- **WHEN** token 具備 `test_case:write` 並更新同 team 的 test case
- **THEN** 系統 SHALL 更新本地 DB
- **AND** SHALL NOT 呼叫外部同步 API

#### Scenario: 有效內容更新刷新 updated_at
- **GIVEN** test case 的 `created_at` 與 `updated_at` 為既有時間
- **WHEN** token 具備 `test_case:write` 並以 generic update 實際改變該案例的持久化內容
- **THEN** 內容與較新的 `updated_at` SHALL 在同一 transaction 寫入
- **AND** 既有依 `updated_at` 計算的 Test Case update trend SHALL 能在新更新日期納入該案例

#### Scenario: Effective no-op 保留 updated_at
- **WHEN** token 提交空 payload 或所有可寫欄位均與現有持久化值相同
- **THEN** 系統 SHALL 保留原 `updated_at`
- **AND** SHALL NOT 因 retry 或同值重送製造新的更新日期

#### Scenario: 拒絕跨 team section 或 set
- **WHEN** payload 指向不屬於該 team 的 test case set 或 section
- **THEN** 系統 SHALL 回 400 `APP_TOKEN_VALIDATION_ERROR`
- **AND** mutation SHALL NOT 執行
- **AND** 案例的 `updated_at` SHALL 保持不變
