## Why

2026-07-30 實測（本機 9911，`/organization-management`，Super Admin）顯示前端資產交付有三個獨立缺陷：

**1. 字型鏈實際上是壞的。** `base.html` 向 Google Fonts 請求三個 family，但其中兩個名稱無效，會被靜默丟棄：

```
family=Noto+Sans           → 有效
family=Noto+Sans+CJK+TC    → 無效（Google Fonts 上的正確名稱是 Noto Sans TC）
family=Noto+Sans+Condensed → 無效
```

合併請求回 HTTP 200，但回應內只含 `font-family: 'Noto Sans'`。Resource Timing 佐證：整頁只下載一支 woff2（`o-0bIpQ…`，Noto Sans 拉丁），**零個 CJK 字型檔**。後果是介面主語言（zh-TW／zh-CN）全部 fallback 到系統字型，跨 OS 呈現不一致；且 `--font-condensed` 沒有對應字型，`style.css:12-15` 為 `.test-case-number`／`[class*="case-number"]`／`[class*="test-number"]` 設的 Condensed 樣式目前無任何效果（`index.css:558` 另有一處引用）。`style.css` 另有兩條互相衝突的 `body { font-family }`（`:7-9` 以 `!important` 勝出、`:193-201` 被壓制）。

**2. 單頁接觸 6 個外部網域、24 個請求。**

| 網域 | 請求數 | 觀察 |
|---|---|---|
| `s16-imfile-sg.feishucdn.com` | 17 | 使用者頭像，每張 1.3–2.2 秒 |
| `cdn.jsdelivr.net` | 3 | Bootstrap CSS/JS、pako |
| `cdnjs.cloudflare.com` | 2 | Font Awesome |
| `fonts.googleapis.com` / `fonts.gstatic.com` | 2 | 字型 |
| `www.gravatar.com` | 1 | 頭像 fallback |

既有 `ui-design-system` 的「CDN dependency pinning and single sourcing」已要求依賴來自單一來源、不得混用多個 CDN origin——**現況正在違反該條款**（jsdelivr + cdnjs + googleapis 三個 origin）。而該條款只涵蓋第三方函式庫，未涵蓋字型與使用者頭像；頭像直連 Feishu 新加坡 CDN 使每次頁面瀏覽都把使用者的存在洩漏給外部服務，且內網封鎖該網域時全數失效。本變更以 `REMOVED`＋`ADDED` 取代該條款，收斂為「自託管」契約。範圍限於呈現資產——功能性外部內容（Allure 報表 iframe、Jira／Lark 外部連結）由其所屬能力規範，明確排除在外。

**3. i18n 三語系每次換頁全量下載。** 實測 `en-US.json` 49.8KB + `zh-TW.json` 53.5KB + `zh-CN.json` 53.7KB ≈ **157KB，實際只使用其中一份**。

## What Changes

- **字型**：修正 family 名稱為 `Noto Sans TC`（已確認提供 400／500／600／700 四字重）；Condensed 需求改以等寬字型滿足，但需先把 `[class*=]` 萬用選擇器收斂為具名 class 清單；合併 `style.css` 中兩條衝突的 `body` 字型宣告。建立契約：宣告的每個 `--font-*` token SHALL 有實際載入的字型檔支撐。
- **自託管**：Bootstrap、Font Awesome 與字型檔 vendor 至 `app/static/vendor/`，由應用程式自身 origin 提供，移除 jsdelivr／cdnjs／Google Fonts 的執行期依賴。此契約的範圍限於**呈現資產**，明確排除功能性外部內容——`automation-hub-run-orchestration` 已規範 Allure 報表以 `<iframe src="{report_url}">` 內嵌（`app/templates/test_run_management.html:866` 的 `#reportEmbedFrame`），該路徑不受影響。
- **頭像**：使用者頭像改由後端代理／快取後以本站 origin 提供，瀏覽器 SHALL 不直接向外部頭像服務發出請求。
- **i18n 載入**：執行期只取得當前語系檔；切換語系時才取得目標語系。
- 不改變 i18n 的 key 覆蓋契約（三語系仍須齊備）、不改變任何 UI 呈現或資料面、不引入 bundler。

## Capabilities

### New Capabilities

無。

### Modified Capabilities

- `ui-design-system`：以 `REMOVED` 移除「CDN dependency pinning and single sourcing」，並 `ADDED`「Self-hosted presentation assets with no runtime external origins」（涵蓋第三方函式庫、字型與使用者頭像，明確排除功能性外部內容）與「Declared font tokens are backed by actually loaded font files」。採 REMOVED＋ADDED 而非改名的 MODIFIED，是因為 archive 階段按 requirement 名稱比對 main spec，改名會找不到對應項。
- `i18n-coverage`：新增執行期只載入當前語系的需求；既有的三語 key 齊備與 CI 檢查不變。

## Impact

- 模板：`app/templates/base.html`（字型與 CDN link／script）
- 樣式：`app/static/css/style.css`（`--font-*` token、重複的 `body` 宣告）
- 靜態資產：新增 `app/static/vendor/`（Bootstrap、Font Awesome、字型檔）
- 前端：`app/static/js/i18n.js`（改為按需載入語系）
- 後端：新增頭像代理／快取端點；`app/services/` 對應服務與 `app/api/`
- 測試：`app/testsuite/test_component_spec.py` 補外部 origin 檢查；`node scripts/check-i18n-coverage.mjs` 維持通過
- 部署：容器映像需納入 vendor 資產；離線／內網環境不再依賴外部網域
