## Context
系統目前已具備 async DB 設計，但實作上仍大量使用同步 session，特別是在 async API 內直接操作同步 DB。這造成事件迴圈阻塞風險，並導致資料存取模式不一致。此次變更要在不影響既有功能的前提下，統一為 async-only 的存取模式。

## Goals / Non-Goals
- Goals:
  - Web runtime 全面使用 AsyncSession（主 DB / audit DB / USM DB）
  - 保持所有 API 行為與資料副作用一致（零功能破壞）
  - 明確隔離同步 DB 使用場景（僅限離線工具或 threadpool）
- Non-Goals:
  - 不更換資料庫類型（維持 SQLite）
  - 不引入破壞性 schema 變更
  - 不重寫 UI 或非 DB 相關模組

## Decisions
- Decision: Web runtime 禁止直接使用同步 session
  - Rationale: 避免阻塞事件迴圈，符合 async 架構預期
- Decision: 同步 DB 使用僅允許在離線工具或以 threadpool 包裝
  - Rationale: 保留必要工具相容性，同時不影響主服務效能
- Decision: 以逐步改寫與回歸測試確保行為不變
  - Rationale: 最大化保守性，降低功能回歸風險

## Risks / Trade-offs
- 風險：改寫範圍大，容易引入細微行為差異
  - 緩解：逐功能回歸測試與對照輸出
- 風險：SQLite 並發行為在 async 模式下可能暴露隱性鎖問題
  - 緩解：保留 WAL/timeout 設定並新增負載測試觀察

## Migration Plan
1. 盤點同步使用點並標記 runtime/offline
2. 建立 async-only DB 存取基準與工具
3. 逐模組替換 API + service + audit/usm
4. 完成回歸測試後移除/封鎖 runtime 同步使用

## Open Questions
- 是否需要新增靜態檢查/CI 規則，防止新增同步 DB 用法？
- audit/usm DB 的 async session 目前是否已有一致介面，或需補齊？
