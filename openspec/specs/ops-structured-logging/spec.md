# Ops Structured Logging Specification

## Purpose
Define the contract for recording operational (ops) events via the event catalog, structured message format, level selection criteria, and migration of existing bare logger calls to catalog-based emit.

## Requirements

### Requirement: Ops 事件經 catalog 與 emit_event
系統 SHALL 經 `app/observability` 的 catalog 與 `emit_event`／`ops_log.emit` 記錄重要 ops 事件。呼叫 MUST 使用已登錄 `event_code` 與 `outcome`。stdlib level MUST **唯一**由 catalog 的 `ops_level_by_outcome[outcome]` 決定；同一 event_code 對同一 outcome MUST 只有一個 level。若 outcome 不在該 event 的 map 中，核心 emit MUST raise 固定驗證例外（fail-closed）。需要不同嚴重度時 MUST 使用不同 outcome 或不同 event_code，MUST NOT 對同一 (event_code, outcome) 雙寫 level。未知 event_code 時核心 emit MUST raise 固定例外；業務路徑 MUST 使用 safe wrapper，行為與 audit-event-envelope 的 safe emit 一致。當 catalog 同時 `write_ops` 與 `write_audit` 為 true 時，emit MUST 先完成驗證，再寫 ops logger，再寫 audit DB；驗證失敗則兩者皆不寫。

#### Scenario: 已登錄 ops 事件寫入 logger
- **WHEN** 以已登錄 ops event_code 與 outcome=failure 成功 emit
- **THEN** logger 產出 record，其 level 等於 catalog 對該 outcome 的設定，message 含人類可讀描述

#### Scenario: 未知 ops event_code 核心 raise
- **WHEN** 測試直接以未登錄 event_code 呼叫核心 emit
- **THEN** 抛出 UnknownEventCodeError（或同等固定型別）

#### Scenario: outcome 不在 level map
- **WHEN** 已登錄 event_code 但 outcome 未出現在其 ops_level_by_outcome
- **THEN** 核心 emit raise 驗證例外，且不寫入 logger 列

#### Scenario: 雙寫順序 validate 後 ops 再 audit
- **WHEN** 某 event_code 同時 write_ops 與 write_audit 且 validate 通過
- **THEN** 先出現 ops log record，再出現 audit 列；若僅 audit DB 隨後失敗，ops record 仍已存在

### Requirement: Structured message 尾碼穩定可解析
經 ops emit 產出的 message SHALL 格式為：`{human_message} | event={event_code} outcome={outcome}`，其後可接空白分隔的 `k=v` 額外欄位。human_message MUST 非空且位於 ` | ` 分隔之前。event_code MUST 匹配 `[a-z0-9._-]+`。MUST NOT 僅輸出無 human 正文的純 JSON 作為唯一 stdout 形式。

#### Scenario: message 含 event 與 outcome 尾碼
- **WHEN** ops emit 成功寫入一筆事件
- **THEN** 格式化 message 含 human 正文、子字串 `event=` 與 `outcome=`，且 ` | ` 出現在正文之後

#### Scenario: 額外欄位在尾碼
- **WHEN** emit 帶 team_id 等允許欄位
- **THEN** 尾碼含對應 `team_id=`（或約定鍵名），human 正文仍在前段

### Requirement: Ops level 選用準則
系統 SHALL 依下列準則編碼於 catalog：DEBUG＝可忽略細節；INFO＝正常生命週期或已處理的可預期外部失敗／降級；WARNING＝非預期但服務可繼續且建議關注；ERROR＝該請求或 job 目標失敗且無完整成功 fallback；CRITICAL＝進程或資料完整性危急。業務刪除的合規敏感度 MUST 以 audit impact 表達，MUST NOT 僅因 DELETE 寫 CRITICAL system log。

#### Scenario: 可預期降級使用 INFO 而非 WARNING
- **WHEN** 設計為可 fallback 的外部步驟失敗且流程繼續降級
- **THEN** 該 ops 事件 level 為 INFO 或 DEBUG，不得為 WARNING

#### Scenario: 無 fallback 的設定損壞使用 ERROR
- **WHEN** 必要 provider 實例化失敗且無法提供功能
- **THEN** 該 ops 事件 level 為 ERROR

### Requirement: Automation result 路徑 level 校正
下列路徑 MUST 改為 catalog 化 ops emit，並移除不當裸 `logger.warning`：Result provider instantiate 失敗；CI artifact 下載失敗後繼續後續策略；Allure proxy 未配置 skip；Allure proxy 上傳失敗（區分是否 fall through）；Result provider report URL 查詢失敗。

#### Scenario: CI artifact 失敗後 fallback 為 INFO
- **WHEN** CI artifact 下載失敗且系統繼續後續 report 策略
- **THEN** 事件 outcome 為 failure、level 為 INFO，且 message 含對應 event_code 尾碼

#### Scenario: Result provider instantiate 例外為 ERROR
- **WHEN** 已配置 Result provider 但 instantiate 拋例外
- **THEN** 事件 level 為 ERROR 且含 event_code

#### Scenario: Allure 未配置 skip 為 DEBUG
- **WHEN** Allure proxy 因未配置而 skip 並 fall through
- **THEN** 若寫 log，level 為 DEBUG 且不得為 WARNING

#### Scenario: Allure 上傳失敗且 fall through 為 partial+INFO
- **WHEN** Allure proxy 上傳失敗且控制流繼續 legacy report URL 策略（strategy 2）
- **THEN** 事件 outcome 為 partial、level 為 INFO（由 catalog 對 partial 映射），event_code 為 `tcrt.ops.automation.allure_proxy.upload`

#### Scenario: Allure 上傳失敗且 terminal 為 failure+ERROR
- **WHEN** Allure proxy 上傳失敗且控制流不繼續任何後續 report 策略而結束
- **THEN** 事件 outcome 為 failure、level 為 ERROR（由 catalog 對 failure 映射），event_code 為 `tcrt.ops.automation.allure_proxy.upload`
