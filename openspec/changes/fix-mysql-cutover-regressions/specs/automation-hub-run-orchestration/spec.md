## MODIFIED Requirements

### Requirement: System MUST sync run status periodically for non-terminal runs

背景 scheduler 任務 SHALL 每 60 秒掃描 `status ∈ {QUEUED, RUNNING}` 且 `last_synced_at < now - 60s` 的 runs，呼叫 `CIProvider.get_run_status` 取最新 status，更新 DB。候選 runs SHALL 以尚未同步（`last_synced_at IS NULL`）優先，其次依 `last_synced_at ASC` 與 `id ASC` 排序；該 query SHALL 在 SQLite、MySQL 8 與 PostgreSQL 16 上可執行。

到達終態（SUCCEEDED / FAILED / CANCELLED / UNKNOWN）後 sync SHALL 停止；同時 TCRT SHALL 呼叫 `ResultProvider.get_run_report_url` 填 `report_url`。

#### Scenario: RUNNING to SUCCEEDED transition
- **WHEN** run 在 CI 完成
- **THEN** 下次 sync SHALL 更新 status=SUCCEEDED、finished_at、duration_ms、report_url，並觸發 outbound webhook event `run.completed`

#### Scenario: 未同步 runs 跨引擎優先排序
- **WHEN** background sync 在 SQLite、MySQL 8 或 PostgreSQL 16 查詢同時含 NULL 與非 NULL `last_synced_at` 的候選 runs
- **THEN** query 不使用目標引擎不支援的 `NULLS FIRST` 語法
- **AND** NULL `last_synced_at` 的 runs 先於非 NULL runs，順序以 `last_synced_at` 與 `id` 穩定決定
