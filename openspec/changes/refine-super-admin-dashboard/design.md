## Context

System Administration Dashboard 與 Personal Dashboard 共用 `index.html`、`index.js`、`index.css` 與固定 hero shell，但目前 system renderer 仍使用巢狀 metric cards、一般大型 quick-action tiles，以及各自佔滿 grid row 的 Provider／Attention cards。這些元件雖安全地消費既有 allowlisted response，卻在相同 viewport 內顯示較少資訊，且與 Personal Dashboard 已採用的高密度單列、內部捲動與 icon-only rail 不一致。

本 change 以重組前端 presentation 為主，並修正實機驗證發現的既有 projection 語意落差：scheduler 儲存 `completed`，但 Dashboard allowlist 只接受 `success`，使成功任務顯示為 `unknown`；同一筆 naive local timestamp 也被 Dashboard formatter 當成 UTC，造成額外時區位移。`GET /api/dashboard` 的 Super Admin dispatch、response shape、獨立失敗狀態與安全資料邊界維持不變。

## Goals / Non-Goals

**Goals:**

- 讓 Super Admin 在固定 viewport 內快速掃描 KPI、排程服務、Provider configured 與需要注意數量。
- 讓服務欄位跨列對齊、長清單只在 section 內捲動。
- 讓管理入口與 Personal Dashboard 採相同的 icon-only、等寬 action rail 與 accessible tooltip。
- 保留三語、responsive、AI Assistant overlay 與每個來源的 partial/unavailable 狀態。
- 讓 Scheduled Services 與管理頁對相同執行紀錄顯示一致的結果、時間與已知服務名稱。

**Non-Goals:**

- 不加入 Resume、Assigned、Outcomes、Recent Activity 或 Preferred Team。
- 不新增 provider probe、監控趨勢、原始 log／error、排程控制或新的管理權限。
- 不改變 API response shape、資料庫、migration、scheduler、provider 或 Audit contract；只修正既有 safe projection 與 presentation mapping。

## Decisions

### 1. System layout 採「compact overview + filling detail」雙欄結構

桌面維持既有主／側欄，但 main column 改為 `auto + minmax(0, 1fr)`：緊湊 Overview KPI strip 固定高度，Scheduled Services 填滿剩餘空間。Side column 同樣採 `auto + minmax(0, 1fr)`：Quick Actions rail 固定高度，System Health 填滿剩餘空間。所有 card 維持 column flex、固定 header 與 body 內捲動。

替代方案是保留五張等比例卡片並只縮小 padding；這仍會讓資料量少的 Provider／Attention 卡佔據過多高度，也無法讓服務表取得主要空間，因此不採用。

### 2. Overview 使用單層 KPI strip

沿用 `compactCard()`，將 active Teams、active Users、active Test Runs 直接 render 為三個等寬 metric cell。每格以 icon、數值與 label 呈現並使用分隔線，不再建立 nested `.card`。Unavailable state 仍使用現有 generic `sectionState()`。

### 3. Scheduled Services 使用 canonical compact table

前端只消費現有 `service_key`、`last_run_at`、`running`、`enabled`、`outcome`，建立 `table table-sm table-hover align-middle mb-0`、sticky header 與 table-responsive wrapper。桌面固定顯示服務、最近執行、狀態、結果四欄；窄螢幕只在 wrapper 內水平捲動，不把一筆服務改成多層 card。動態值一律以 `textContent` 建立，狀態與結果只經既有 allowlisted badge mapping。已知 `service_key` 由前端三語 allowlist 映射友善名稱，未知 key 才顯示安全 identifier；不讀取資料庫中的任意 `display_name`。

### 4. Provider 與 Attention 合併呈現但不合併狀態

新增 System Health presentation card，內含 Attention、CI Provider、Result Provider 三個高密度 row。Provider 與 Attention 仍各自呼叫 `sectionState()`；任一 section unavailable 時只在對應 group 顯示 generic state，另一 group 繼續 render。此合併只發生在 DOM presentation，不改動 response 或把 configured 宣稱為 connection health。

### 5. 管理入口重用 compact Quick Actions

System Dashboard 呼叫既有 `renderQuickActions(..., compact=true)`，因此按鈕只顯示 Font Awesome icon、以 `flex: 1 1 0` 等寬填滿 rail，localized label 留在 `aria-label` 與 `title`。點擊仍只導航 server allowlisted route，不設定 Team context。

### 6. Responsive 保留固定 hero 與內部捲動

桌面沿用 document scroll disabled 與固定 hero。`<= 991.98px` 時 dashboard region 成為內部 vertical scroll container，system cards 取得明確高度；service table wrapper 處理 horizontal overflow。`<= 575.98px` 時 KPI strip 維持三欄但縮小字級與 gap，避免增加整頁層級。

### 7. 排程結果與時間沿用 scheduler 的既有語意

Dashboard safe projection 將 scheduler persistence code `completed` 映射為 `success`、`interrupted` 映射為 `error`，其餘既有安全 code 維持不變；如此既不暴露 raw message／error，也能讓 interrupted 納入既有 Attention 的 `failed`／`error` 計數。排程器目前以 `datetime.now()` 寫入 naive local wall-clock timestamp，Dashboard 的排程服務 renderer 因此採用與管理頁相同的 local-wall-clock parse path，不套用共用 formatter 對 naive UTC 的假設。這是針對 Scheduled Services 的相容修正，不改寫全站時間契約或既有資料。

## Risks / Trade-offs

- [英文 label 可能擠壓 KPI] → metric label ellipsis 並保留 `title`，數值維持可見。
- [服務名稱或時間過長] → table 使用固定 layout、ellipsis／nowrap 與 wrapper horizontal scroll。
- [合併 Health 後來源失敗被誤解為整體失敗] → Provider／Attention 各自保留 section state 與獨立 group label。
- [icon-only action 可發現性降低] → 強制 localized `aria-label`、`title`、keyboard focus 與既有固定 allowlist。
- [排程時間缺少 timezone offset] → 僅對 Scheduled Services 沿用管理頁已建立的 naive local wall-clock 語意並加回歸測試；後續若 scheduler 全面改存 UTC，需另立 migration change。

## Migration Plan

此 change 無資料或 API migration。部署替換 Dashboard service projection、首頁 CSS／JS／locale；回滾可直接回退這些檔案，既有資料不需轉換。

## Open Questions

無。Super Admin 維持 system-only scope，僅同步 Personal Dashboard 已接受的版面密度與 interaction conventions。
