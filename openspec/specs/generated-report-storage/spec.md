# generated-report-storage Specification

## Purpose
定義 HTML generated reports 的根目錄設定、預設路徑與建立行為。

## Requirements
### Requirement: Configurable generated report root
系統 SHALL 支援透過 `reports.root_dir` 與 `REPORTS_ROOT_DIR` 控制 generated report 根目錄。

#### Scenario: Configured root directory from config file
- **WHEN** `config.yaml` 提供 `reports.root_dir`
- **THEN** 系統使用該目錄作為 report root

#### Scenario: Environment variable override
- **WHEN** 環境變數 `REPORTS_ROOT_DIR` 有值
- **THEN** 系統以環境變數覆蓋 YAML 設定

### Requirement: Default and consistent report storage behavior
系統 SHALL 在未設定時回退到專案內預設報告目錄，並在使用前建立缺少的資料夾。

#### Scenario: Default root directory
- **WHEN** 未設定報告根目錄
- **THEN** 系統使用專案內預設 `generated_report` 目錄

#### Scenario: Create missing directories before use
- **WHEN** 報告服務或 `/reports` mount 使用目錄前發現目錄不存在
- **THEN** 系統先建立必要資料夾再寫入或掛載
