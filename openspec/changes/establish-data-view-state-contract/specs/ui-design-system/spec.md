# ui-design-system Specification Delta

本 delta 修改既有的「Button State Consistency」。原條款規範了 disabled 的**呈現**（統一樣式與互動阻擋），但未規範**何時**應該進入 disabled。實測顯示 `/organization-management` 在「請選擇使用者」狀態下，`#pm-delete`（刪除）與 `#pm-reset`（重設密碼）皆為 `disabled: false`，兩個需要目標的破壞性動作在無目標時仍可觸發。本 delta 補上進入條件。

## MODIFIED Requirements

### Requirement: Button State Consistency

The system SHALL provide consistent hover, active, disabled, outline, and loading states for all buttons based on the shared button visual system. 系統 SHALL 同時規範按鈕進入 disabled 的條件：需要選取目標才可執行的動作，SHALL 在無選取時為 disabled。

#### Scenario: Hover and active states

- **WHEN** a user hovers over or activates a button
- **THEN** the visual feedback SHALL follow the unified hover/active rules

#### Scenario: Disabled state

- **WHEN** a button is disabled
- **THEN** the button SHALL display the unified disabled styling and block interaction cues

#### Scenario: Outline and loading states

- **WHEN** a button uses outline or loading presentation
- **THEN** the button SHALL follow the unified outline and loading rules

#### Scenario: Actions requiring a target are disabled without one

- **WHEN** 按鈕所觸發的動作需要一個已選取的目標，而目前沒有選取
- **THEN** 該按鈕 SHALL 為 disabled
- **AND** SHALL 套用統一的 disabled 呈現，而非維持啟用外觀
