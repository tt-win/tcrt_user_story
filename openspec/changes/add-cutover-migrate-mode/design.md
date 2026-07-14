# Design — add-cutover-migrate-mode

## Context

既有 runner（`app/db_cutover_workflow.py`）的模式為 `preflight` / `smoke` / `rehearsal`，流程：`build_workflow_target()`（sqlite=run-dir 檔案；mysql/postgres=寫死的 disposable compose 連線，port 33060/5433，帳密 tcrt/tcrt）→ guardrails → `database_init.py --preflight` → `database_init.py --no-backup`（bootstrap）→ `--verify-target all` → 起 app 健康檢查 →（rehearsal）與 baseline summary 比對。資料搬移由 `scripts/db_cross_migrate.py` 獨立負責：reflect 來源 metadata、FK 拓撲排序、chunked copy、MySQL TEXT 容量加寬，輸出每表 copied rows 的 JSON summary，但**沒有搬移後的獨立覆核**（copied rows 是寫入時計數，非事後 re-count）。

## Goals / Non-Goals

**Goals:**

- 單一指令完成「SQLite（或任一來源）→ 指定 MySQL/PostgreSQL server」的 schema 建立、資料搬移、驗證與切換資訊輸出。
- 來源唯讀；目標的破壞性動作需明示旗標。
- 逐表 row count 覆核為成敗判準的一部分。

**Non-Goals:**

- 不做增量/雙寫/線上同步（一次性停機搬移）。
- 不自動改寫 app 的 `.env` / config.yaml（只輸出 env_summary 供人工套用）。
- 不處理 Qdrant 重建索引、附件搬移（既有工具/文件另管）。
- 不改變既有三種模式的行為。

## Decisions

### D1. 目標/來源連線解析

- 新 CLI 參數（`parse_args`）：`--target-env-file <path>`、`--source-env-file <path>`、`--force-reset-target`。
- **目標**優先序：(1) `--target-env-file`：解析檔內 `DATABASE_URL`、`SYNC_DATABASE_URL`、`AUDIT_DATABASE_URL`、`USM_DATABASE_URL` 四鍵（缺任一鍵 → 立即錯誤退出，訊息列出缺鍵）；(2) 未給且 `--manage-services`：沿用 `build_workflow_target(target)` 的 disposable compose 連線（演練）；(3) 兩者皆無 → 錯誤退出。env 檔解析用簡單 `KEY=VALUE` 逐行解析（忽略空行與 `#`，值去除首尾引號），不引入 dotenv 相依。
- **來源**：預設在「不帶 target 環境覆寫」的行程內以 `app.db_migrations.resolve_main_database_url` / `resolve_audit_database_url` / `resolve_usm_database_url` 解析（即目前 app 實際使用的 DB）；`--source-env-file` 提供時改用檔內四鍵。
- 傳給 `db_cross_migrate.py` 的 URL 一律先經 `app.db_url.normalize_sync_database_url()` 轉 sync driver（來源可能是 `sqlite+aiosqlite` / `mysql+asyncmy` 等 async URL）。
- 防呆：任一 target 的（backend, host, port, database）四元組與對應 source 相同 → 錯誤退出（防止自我覆蓋）。比對用 `make_url()` 解析後的正規化值，SQLite 比對 resolve 後的絕對路徑。

### D2. migrate 模式步驟編排（`run_cutover_workflow` 內，`mode == "migrate"` 分支）

```text
1. compose up（僅 --manage-services 且使用 disposable 目標時，沿用既有）
2. guardrails（沿用既有）
3. preflight（database_init --preflight --json，環境=目標 env）
4. 非空目標偵測（D3）→ 非空且無 --force-reset-target → 中止
5. bootstrap 目標 schema（database_init --no-backup --quiet，環境=目標 env）
6. 資料搬移（D4）：main → audit → usm 依序執行 db_cross_migrate 子行程
7. 逐表覆核（D5）：db_cross_migrate 的 row_count_verification 全 matches 才續行
8. verify（database_init --verify-target all --json，環境=目標 env）
9. 健康檢查：以目標 env 起 app（沿用 _run_health_check）
10. summary 寫檔（含 migration 與 env_summary 區段）
```

- 每步失敗即 `_finalize_summary` 短路返回（沿用既有模式的慣例），失敗步驟的 log 都在 `logs/` 下（新增 `logs/migrate-main.log` 等三檔）。
- 步驟 5 用 `--no-backup`：目標是全新/剛清空的庫，備份無意義；與 change `add-boot-upgrade-backup-rollback` 的 fresh-DB 語意一致。

### D3. 非空目標偵測

- 定義「非空」：對目標三庫分別 reflect（沿用 `db_cross_migrate.reflect_selected_metadata` 的 exclude 預設，排除 `alembic_version`、`migration_history`），任一業務表 `SELECT COUNT(*)` > 0 即為非空。目標 database 不存在或無業務表 → 視為空。
- 非空且未帶 `--force-reset-target` → 中止並在 summary 記錄非空表清單（表名＋列數，最多列 20 筆）。
- 帶 `--force-reset-target` → 步驟 6 的 db_cross_migrate 以 `--reset-target` 執行（既有旗標，逐表 DELETE）。**未帶時也一律傳 `--reset-target`**：因步驟 5 bootstrap 可能已 seed（如 `ensure_super_admin_seed`），必須清掉避免與來源資料衝突；此時目標在步驟 4 已確認無業務資料，清空的只是本次 bootstrap 的 seed，不屬破壞既有資料。
- 偵測時點在 bootstrap（步驟 5）**之前**：bootstrap 後所有表都存在，無法區分「原有資料」與「seed」。

### D4. 資料搬移子行程

- 以 `uv run python scripts/db_cross_migrate.py --source-url <sync-src> --target-url <sync-dst> --reset-target --json --quiet` 逐庫執行（main/audit/usm 三次），呼叫方式對齊 `_run_database_init_command` 的 subprocess 慣例（timeout、log 落檔、stdout JSON 抽取用既有 `extract_json_payload`）。
- 不傳 `--create-target-schema`：schema 一律由步驟 5 的 Alembic 建立（canonical），避免 reflect-create 產生的型別漂移。
- `--disable-constraints` 不預設；db_cross_migrate 既有 FK 拓撲排序已處理順序。若來源存在循環 FK 導致排序失敗，錯誤原樣呈現，操作者可用 `--migrate-disable-constraints`（新 CLI 旗標，透傳）重跑。
- 子行程 env：不注入目標 URL（URL 全在 argv 的 `--source-url/--target-url`），log 檔寫入前以 `redact_url()` 遮蔽（db_cross_migrate summary 內的 `source_url`/`target_url` 欄位在寫入 workflow summary 前同樣遮蔽）。

### D5. 逐表 row count 覆核（改 `scripts/db_cross_migrate.py`）

- `run_job()` 完成資料寫入後（非 dry-run），對每張搬移表分別在 source connection 與 target connection 執行 `SELECT COUNT(*)`，寫入 summary：
  `"row_count_verification": [{"table": ..., "source_rows": int, "target_rows": int, "matches": bool}]` 與 `"row_counts_match": bool`（全表 AND）。
- `run_job` 回傳的 `status` 維持 `completed`；`row_counts_match=False` 不改 exit code（工具行為向後相容），**由 workflow 端判定失敗**——migrate 模式在任一庫 `row_counts_match=False` 時視為步驟失敗。
- 理由：覆核放 db_cross_migrate 內（同一組 connection、同一時點）比 workflow 事後另開連線重數更可信，也讓單獨使用工具的人受益。

### D6. Summary 與 env_summary

- summary.json 新增：
  - `"migration": {"jobs": [<每庫 db_cross_migrate summary（URL 遮蔽）>], "row_counts_match": bool, "duration_seconds": float}`
  - `"env_summary": {"DATABASE_URL": <async URL 遮蔽>, "SYNC_DATABASE_URL": ..., "AUDIT_DATABASE_URL": ..., "USM_DATABASE_URL": ...}`——值取自目標 env 檔原文（遮蔽密碼），提示操作者切換 app 設定時要用的四鍵。
- `render_markdown_summary()` 增加 `## Migration` 段（每庫表數、總列數、覆核結果）與 `## Env Summary` 段。
- 密碼遮蔽一律走既有 `redact_url()`；env_summary 明確標註「實際密碼請直接取自 --target-env-file，本檔不含明文」。

### D7. 模式與既有參數的交互

- `--baseline-summary` 在 migrate 模式不適用 → 帶了即錯誤退出（訊息指明僅 rehearsal 用）。
- `--keep-services` / `--health-timeout` 行為不變。
- sqlite 亦可為 migrate 目標（`--target sqlite`＋不帶 target-env-file）：用於測試套件端到端驗證（SQLite→SQLite 到 run-dir 檔案），非實際使用場景但保持一致性。

## Risks / Trade-offs

- [大庫搬移時間長、期間來源仍可寫] → runbook 明載：正式搬移須停止 app 寫入（停容器或維護模式）後執行；工具本身不做鎖定。
- [row count 覆核非內容比對] → 已知取捨；內容級校驗（checksum）留待未來，spec 只承諾 row count。runbook 建議搬移後抽樣人工驗證關鍵頁面。
- [`--target-env-file` 誤指向 production 既有庫] → D3 非空偵測＋`--force-reset-target` 雙重門檻；`--force-reset-target` 的破壞範圍寫進 CLI help 與 runbook。
- [db_cross_migrate 的 enum/型別修補仍存在（schema-engine-portability 未實作前）] → migrate 模式不依賴其修復；`make-schema-engine-portable` 落地後修補自然消失，本 workflow 不需改。

## Migration Plan

1. 純程式碼與文件變更，無 schema 變更、無新相依。
2. 部署即生效；舊模式不受影響。
3. Rollback：revert commits。

## Open Questions

（無——目標解析優先序（D1）、reset 語意與時點（D3）、覆核放工具端（D5）、baseline 互斥（D7）皆已定案。）
