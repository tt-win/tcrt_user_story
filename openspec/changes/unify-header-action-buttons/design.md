## Context

14 個頁面 header 的 `page_specific_actions` 已盤點。`automation_hub` 已符合規範，作為基準。`common.home` 與 `navigation.backToHome` 三語系值相同，header 內可安全替換。

## Decisions

### Decision 1：尺寸統一為 btn-sm

採 `btn-sm`（使用者選定）。header 為固定高度的密集工具列，btn-sm 在按鈕較多的頁面（test_run_execution 8 顆）較不擁擠，且較新頁面已採此尺寸。圖示間距統一 `me-1`（密集按鈕的主流慣例）。

### Decision 2：語意化調色盤（完整套用）

| 意圖 | 顏色 | 範例 |
|------|------|------|
| 主要建立／CTA | `primary` | New Suite、Create Test Case、Create Team、Add Provider/Webhook、Team Settings(首頁) |
| 建設性提交 | `success` | Save、Start Execution、Convert to Test Case |
| 停止／終結 | `warning` | Complete/Stop Execution |
| 次要功能啟動 | `info` | AI Helper、Charts & Reports、Calc Tickets、Restart/Re-run、Import Tools、Data&Records、Org & System |
| 工具與導覽 | `secondary` | Refresh/Rescan、Jump-to、Back-to-parent、Home、Git Sources、Webhooks |

**收斂的 outlier**：`team_management` 的 Import/Data/OrgSync 由 `primary`→`info`（保留 Create Team 為唯一 primary）；`test_case_management` 的 Bulk Mode `primary`→`info`；`test_run_execution`/`adhoc` 的 Charts & Reports `primary`→`info`。

### Decision 3：篩選控制項例外

`test_run_management` 狀態篩選（草稿=warning、進行中=primary、已完成=success…）為狀態編碼，**保留顏色**；`team_statistics` 日期區間／團隊篩選為分段選擇器，**保留顏色與 active**。兩者僅補上 `btn-sm`。理由：重新著色屬於篩選 UX 決策且有破壞 active-state JS 的風險，超出「header 按鈕統一」範圍。

### Decision 4：導覽群組靠右、順序固定

返回上層（`fa-arrow-left`）→ 首頁（`fa-home`），群組於最右、user menu 前。修正：`team_statistics`（首頁/返回顛倒→交換）；`automation_provider_settings`/`automation_webhook_config`（返回鍵由置左移入右側群組，並將橫向「Team Management」連結改為「Home」，因其父層為 Automation Hub，Team Management 仍可從首頁／無團隊狀態進入）；`audit_logs`（chevron→arrow-left，補上 Home）。

### Decision 5：首頁文案鍵統一

header 內 `common.home` → `navigation.backToHome`（值相同，無文案變動）。涉及 `test_case_set_list`、`qa_ai_helper`、`profile`。

## Risks / Trade-offs

- **[Risk] 篩選/分段控制的 btn-sm 化** 可能影響既有版面間距 → 以瀏覽器抽查 `test_run_management`、`team_statistics` 確認。
- **[Risk] 移除設定頁的橫向 Team Management 連結** → 確認無團隊狀態與首頁仍可進入 Team Management（保留 content 區的 Team Management 按鈕）。
