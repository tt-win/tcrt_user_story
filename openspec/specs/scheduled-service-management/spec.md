# scheduled-service-management Specification

## Purpose
定義 Super Admin 可在團隊管理 / 組織管理流程中查看與管理可排程服務的能力。

## Requirements
### Requirement: Super Admin can manage scheduled services in organization modal
系統 SHALL 僅允許 Super Admin 在組織管理 UI 管理 scheduled services。

#### Scenario: Super Admin sees service management tab
- **WHEN** Super Admin 開啟組織管理介面
- **THEN** 可見 scheduled service management 分頁

#### Scenario: Non-Super-Admin cannot access service management tab
- **WHEN** 非 Super Admin 使用者開啟相同介面
- **THEN** 看不到或無法存取該分頁

### Requirement: System exposes available schedulable services from backend registry
後端 SHALL 由 schedulable service registry 提供可管理的服務清單。

#### Scenario: Load schedulable services
- **WHEN** UI 查詢 scheduled services API
- **THEN** 回應包含已註冊的可排程服務資訊

### Requirement: Super Admin can configure daily scheduled execution time
Super Admin SHALL 可設定每日執行時間或停用排程服務。

#### Scenario: Save enabled daily schedule
- **WHEN** 管理者儲存合法的每日時間
- **THEN** 系統更新排程設定與下一次執行時間

#### Scenario: Disable scheduled service
- **WHEN** 管理者停用某服務
- **THEN** 系統停止該服務的排程

### Requirement: Service management shows current runtime state and last execution result
系統 SHALL 顯示 scheduler 目前狀態與各服務最後執行結果。

#### Scenario: Show current running state
- **WHEN** 使用者檢視服務管理分頁
- **THEN** UI 顯示 scheduler 是否運行中

#### Scenario: Show last execution result
- **WHEN** 某服務曾執行過
- **THEN** UI 顯示最後執行時間與結果

### Requirement: Scheduler restores persisted schedules on startup
系統啟動時 SHALL 還原已保存的 schedule 狀態，並修復 stale running state。

#### Scenario: Startup loads existing schedules
- **WHEN** 系統啟動
- **THEN** scheduler 載入既有 schedule 設定

#### Scenario: Startup recovers stale running state
- **WHEN** 上次執行留下不一致的 running state
- **THEN** 初始化流程修正該狀態
