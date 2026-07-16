## Context

`database_init.py` 對 main、audit、usm 逐一呼叫 `create_database_if_missing()`。現行實作會先把 URL database 改成 MySQL `mysql` 或 PostgreSQL `postgres`，再查詢並視需要建庫。此流程即使目標 database 已存在，也要求 app 帳號能連管理 database；而正式部署通常只授予三個目標 databases 的 schema 與資料權限。

本次 MySQL 實跑已證明 preflight 可用受限帳號判定三庫為 `empty_ready`，但 bootstrap 隨即因無權連 `mysql` database 而失敗。來源資料與目標資料互不共用，失敗發生在任何 schema 或資料寫入前。

## Goals / Non-Goals

**Goals:**

- 已存在的 MySQL / PostgreSQL 目標 database 可由只具目標權限的 app 帳號完成 bootstrap。
- 目標 database 不存在且帳號具有建庫權限時，維持自動建庫能力。
- 只有明確 missing-database error 才轉入管理 database 建庫路徑；其他認證、網路或 SQL 錯誤原樣失敗。
- 以正式 `--source-env-file` / `--target-env-file` 路徑完成三庫搬移及 app health check。

**Non-Goals:**

- 不改變 Alembic revisions 或任何 table schema。
- 不替正式環境建立 MySQL server、database 或帳號。
- 不擴大 app 帳號權限，也不把 Docker 啟動納入正式 migration runbook。

## Decisions

1. `create_database_if_missing()` 先以同步 driver 直接連目標 database 並執行輕量連線檢查。成功即回傳 `False`，表示不需建立。
   - 理由：最小權限帳號必然可連自身目標 database，且這是 database 已存在的最直接證據。
   - 未採用：繼續查 `INFORMATION_SCHEMA` 但改連目標 database。跨引擎差異較大，且單純成功連線已足夠。
2. 直接連線只有在 `is_missing_database_error()` 明確辨識 missing database 時才 fallback 到既有管理 database 流程。
   - 理由：避免把密碼錯誤、網路中斷、TLS 或權限錯誤誤解為需要建庫。
3. 保留既有管理 database 查詢與 `CREATE DATABASE` 實作，不新增設定旗標或依賴。
   - 理由：維持高權限 bootstrap 的相容性，並保持修正範圍最小。
4. Runbook 將 schema bootstrap、資料搬移、逐表 row count、revision、health check 交給既有 cutover runner；人工只負責來源唯讀、env files、切換部署設定與 rollback。
   - 理由：單一路徑比散落的手動指令更容易由較低能力模型穩定重現。

## Risks / Trade-offs

- [直接連線會增加一次短連線] → bootstrap 每個 target 僅一次，並立即 dispose，影響可忽略。
- [錯誤分類過寬可能進入建庫路徑] → 僅使用既有 `is_missing_database_error()`，並補測一般錯誤不得 fallback。
- [正式搬移期間來源仍寫入導致 row count 或關聯不一致] → runbook 強制先停止 app 寫入並保留來源回復點。
- [切換後 health 成功但特定頁面仍有資料相容問題] → runbook 保留 main/audit/usm sentinel/row count 與人工關鍵頁抽查。

## Migration Plan

1. 部署修正版程式，但先維持 app 指向來源 DB。
2. 停止來源寫入並保存來源 DB 備份或快照。
3. 用來源與目標 env files 執行 `run_db_cutover_workflow.py --mode migrate`。
4. 確認 summary success、三個 jobs row counts、revisions 與 health check。
5. 將部署環境四組 DB URL 切到目標並重啟 app，再檢查 health 與關鍵頁面。
6. 若任何一步失敗，停止新 app、把四組 URL 切回來源並重啟；目標可清空後重跑，來源維持唯讀且不受搬移工具修改。

## Open Questions

無。
