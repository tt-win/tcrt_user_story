# team-default-test-case-set Specification

## Purpose
定義每個 team 的 default Test Case Set 行為，包括設定預設集合、保證 Unassigned section，以及統一預設解析。

## Requirements
### Requirement: Admin can set team default Test Case Set
系統 SHALL 允許管理者指定某個 Test Case Set 為 team 的 default set。

#### Scenario: Admin sets a new default
- **WHEN** 管理者將某個 set 設為 default
- **THEN** 該 set 變成新的 default set，且原 default 被取消

### Requirement: Default Set must have an Unassigned section
default Test Case Set SHALL 保證存在可接住未分派案例的 Unassigned section。

#### Scenario: Set as default creates Unassigned section if missing
- **WHEN** 某 set 被設為 default 且缺少 Unassigned section
- **THEN** 系統自動建立所需 section

### Requirement: Unified default resolution
系統 SHALL 在刪除、搬移或建立案例等流程中使用一致的 default set 解析邏輯。

#### Scenario: Fallback uses unified default
- **WHEN** 某流程需要 fallback target set
- **THEN** 系統使用同一套 default resolution 規則
