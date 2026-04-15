# Change: 統一 DB 非同步存取

## Why
目前系統在 FastAPI async 路由內仍混用同步 DB session，與既定的 async SQLite 架構不一致，容易造成事件迴圈阻塞、鎖競爭、以及維護成本升高。需要統一為 async-only，以提升可維護性與一致性，同時保持功能行為不變。

## What Changes
- 將 Web runtime（API handler、背景任務）全面改用 AsyncSession 存取主 DB / audit DB / USM DB
- 同步 DB 存取僅保留在離線工具（例如 database_init.py、scripts）或必要的 threadpool 隔離場景
- 新增防呆/測試以避免同步 DB 被誤用於 Web runtime
- 確保所有既有 API 回應、資料副作用與流程行為保持一致（無破壞性變更）

## Impact
- Affected specs: 新增能力 `database-async`
- Affected code: `app/database.py`, `app/api/*`, `app/services/*`, `app/audit/*`, `app/models/*`, `app/testsuite/*`
