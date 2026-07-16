## MODIFIED Requirements

### Requirement: 資料搬移工具 SHALL 回報逐表 row count 覆核
`db_cross_migrate` 於非 dry-run 搬移完成後 SHALL 對每張搬移表重新計數 source 與 target 列數，並在 JSON summary 提供 `source_rows`、`filtered_rows`、`expected_target_rows`、`target_rows`、per-table repair counts、`matches` 與整體 `row_counts_match`。只有 allowlisted、可稽核的 repair filters 可使 `expected_target_rows` 小於 `source_rows`；非預期落差 SHALL 維持失敗。

#### Scenario: 單獨執行搬移工具
- **WHEN** 操作者直接以 `--json` 執行 db_cross_migrate 完成一個 job
- **THEN** summary 含 row_count_verification 逐表列數、repair / filtered-row 說明與 row_counts_match 欄位

#### Scenario: 孤兒 result history 被明確過濾
- **WHEN** `test_run_item_result_history` 含 FK 指向不存在 `test_run_items` 的 orphan rows
- **THEN** 工具不將 orphan rows 寫入 target
- **AND** summary 記錄 `skipped_orphan_item_refs` 與相同數量的 `filtered_rows`
- **AND** 當 `target_rows = source_rows - filtered_rows` 時該表 `matches=true`，workflow 可繼續 verify 與 health check

#### Scenario: 非預期資料少列
- **WHEN** target row count 小於 expected target 且沒有對應 allowlisted filtered-row repair
- **THEN** 該表 `matches=false` 且整體 `row_counts_match=false`
