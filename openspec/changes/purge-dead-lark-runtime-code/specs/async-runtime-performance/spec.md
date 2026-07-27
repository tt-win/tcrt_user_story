## REMOVED Requirements

### Requirement: 附件下載代理以 async 串流轉發且保留既有行為契約

**Reason**: 附件下載代理的 Lark 代理路徑已整段移除——代理現在只從本機附件目錄取檔，三種本機來源皆落空時回 404，不再對外發出任何 HTTP 請求。本 requirement 規範的對象（async HTTP client 串流轉發、上游 401/404/其他→502、逾時 504、連線錯誤 502、Content-Disposition 傳遞、上游連線釋放）在系統中已不存在。

移除前置條件已於 2026-07-27 以唯讀掃描確認：生產 DB 中 `test_run_items` 沒有任何一筆 `execution_results_json` / `upload_history_json` 帶有 Lark `file_token` 或 `open.larksuite.com` URL（唯二命中是檔名以「Lark」開頭的本機錄影檔）。仍帶 Lark 附件的 2 筆 test case 由前端直接連往 Lark URL，不經過本代理。

**Migration**: 本機串流路徑（`StreamingResponse` + 逐塊讀檔）不涉及事件迴圈阻塞問題；`core-runtime-performance` 的「請求處理不得在事件迴圈上執行阻塞式網路或 IO」仍涵蓋一般性要求，組織層 Lark 出站呼叫的離載要求則由本 spec 其餘 requirement 繼續規範。
