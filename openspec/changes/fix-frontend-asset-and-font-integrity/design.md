## Context

TCRT 是內網 QA 工具，但前端執行期依賴 6 個外部網域。`ui-design-system` 已有「單一來源」條款，實際上沒有落實，且該條款的範圍不足以涵蓋這次實測到的兩類外洩：字型與使用者頭像。

字型問題特別隱蔽：Google Fonts 的 `css2` 端點對含有無效 family 的**合併請求**仍回 HTTP 200，只是靜默丟棄無法解析的 family。所以沒有任何錯誤訊息、沒有 console warning，只有「中文看起來跟預期不一樣」這個難以歸因的症狀。驗證方式：

```bash
curl -s "https://fonts.googleapis.com/css2?family=Noto+Sans:wght@400;500;600;700&family=Noto+Sans+CJK+TC:wght@400;500;600;700&family=Noto+Sans+Condensed:wght@400;600;700&display=swap" \
  | grep -o "font-family: '[^']*'" | sort -u
# → 只輸出 'Noto Sans'
```

## Goals / Non-Goals

**Goals**

- 宣告的字型 token 都有實際載入的字型檔支撐，CJK 不再靠系統 fallback。
- 呈現資產零外部網域依賴，內網／離線環境下頁面本身完整可用（功能性外部內容依其所屬能力降級）。
- 使用者頭像不再向外部服務洩漏瀏覽行為。
- i18n 載入量降為當前語系。

**Non-Goals**

- 不更換字型設計方向（維持 Noto Sans 家族，不引入新品牌字型）。這是修復，不是重新設計。
- 不改變 i18n 的 key 覆蓋契約與三語齊備要求。
- 不改變頭像的來源系統（Lark／Gravatar 仍是上游），只改變瀏覽器取得路徑。
- 不涵蓋功能性外部內容。`automation-hub-run-orchestration` 已規範 Allure 報表以 `<iframe src="{report_url}">` 內嵌，Jira／Lark 亦以外部連結呈現；這些由各自能力規範，本變更不觸及。
- 不引入 bundler 或 asset pipeline；vendor 目錄是靜態檔複製。

## Decisions

### 1. Condensed 需求改以等寬字型滿足，但需先收斂萬用選擇器

初版誤判 `--font-condensed` 只服務 `.test-case-number`。實際使用面較廣：

```
style.css:12-15   .test-case-number, [class*="case-number"], [class*="test-number"]  ← 兩個萬用屬性選擇器
index.css:558     另一處直接引用 var(--font-condensed)
```

萬用選擇器實際命中至少 `.test-case-number-open`、`.test-case-number-value`（`test-case-management.css:150,155`）與 `.case-number`（`test-case-set-list.css:76`）。等寬字型（`Noto Sans Mono`）在「編號可讀」這個用途上比 condensed 更合適——數字等寬、辨識度高，且與 `establish-navigation-and-data-legibility` 的 tabular figures 方向一致。

但直接把萬用選擇器改綁等寬有風險：`[class*="case-number"]` 會命中任何 class 名含該片段的元素，若其中含中文說明文字，等寬字型缺 CJK 字符會導致二次 fallback、視覺劣化。決定先把萬用選擇器收斂為具名 class 清單，再改綁字型。

### 2. Vendor 而非改用單一 CDN origin

原條款允許「同一 CDN origin」作為選項。對內網部署的 QA 工具而言，任何外部 origin 都是可用性風險。決定收斂到 `app/static/vendor/`，並在 spec 中移除「單一 CDN origin」這個選項。

### 3. 頭像走後端代理 + 快取，不落地為永久檔案

後端提供 `/api/avatar/{user_id}` 之類的端點，向上游取得後以短期快取回應。不把頭像永久寫入 repo 或 volume，避免產生新的個資落地面。上游不可用時回傳本地產生的字母縮寫佔位圖，而非破圖。

### 4. i18n 按需載入，切換語系時才抓目標語系

`i18n.js` 目前一次抓三份。改為只抓當前語系；`switchLanguage()` 時抓目標語系並在成功後才切換。失敗時維持原語系並回報，不留下半套翻譯狀態。

### 5. 字型以 `font-display: swap` + 自託管 woff2，不做 preload 以外的最佳化

自託管後字型與頁面同源，延遲已大幅下降。只加 `<link rel="preload">` 給主字重，其餘交給瀏覽器。

## Risks / Trade-offs

- **Vendor 資產的版本維護成本**：升級 Bootstrap／Font Awesome 從改一行 URL 變成替換檔案。緩解：在 `app/static/vendor/` 放一份記錄來源與版本的 manifest，升級步驟寫進 `docs/`。
- **容器映像變大**：字型（含 CJK）與 Font Awesome 會增加映像體積。CJK woff2 子集化可緩解，但子集化需要建置步驟——與「不引入 build pipeline」的約束衝突。決定先用完整 woff2，體積若不可接受再評估預先產生的靜態子集（產物入 repo，不在部署時建置）。
- **頭像代理增加後端負載與一條對外連線**：緩解為短期快取 + 佔位圖降級；此端點只在使用者已驗證時可用。
- **`Noto Sans TC` 與現有 `Noto Sans` 的字重對應可能不完全一致**，中文與拉丁混排的視覺重量會變。緩解：browser QA 三語系逐頁比對。
- **i18n 按需載入改變 `i18nReady` 時序**：目前有頁面在 `i18nReady` 前以 `body.i18n-loading{opacity:0}` 隱藏整頁。載入量下降應使其更快，但需確認失敗路徑不會讓頁面永久隱藏。

## Migration Plan

1. 先修字型 family 名稱（單行修正，立即讓 CJK 字型生效），同時合併 `style.css` 重複的 `body` 宣告。
2. Vendor Bootstrap／Font Awesome／字型檔，切換 `base.html` 的 link／script 來源，保留一次可回退的 commit 邊界。
3. 加入頭像代理端點與前端改寫，先於 `/organization-management`（頭像最多）驗證。
4. i18n 改按需載入，驗證三語切換與 `i18nReady` 時序。
5. 補外部 origin 的自動化檢查。

無資料庫變更、無 migration。回滾即還原模板與靜態資產。

## Open Questions

- CJK woff2 的實際體積尚未量化。Google Fonts 的 `css2` 端點對非瀏覽器 User-Agent 回傳 TTF 而非 woff2 分片，無法以 CLI 直接量測；需在瀏覽器 DevTools 下載 `Noto Sans TC` 四字重的全部 `unicode-range` 分片後加總。若體積不可接受，靜態子集的產生方式與更新時機需要另行決定（產物入 repo，不在部署時建置）。
- 頭像代理的快取存放位置（記憶體／Redis／臨時目錄）尚未決定，取決於多副本部署下的一致性需求。
- Lark 頭像 URL（`lark_user_service.py` 存入的 `avatar_240`／`avatar_640`／`avatar_origin`）是否會過期或需要簽章？目前前端直連可正常載入，代表至少在當下是公開可取；但若 URL 有效期有限，代理層需要能觸發 `lark_org_sync_service` 重新取得。
- Gravatar fallback 是否一併移除？移除後未設頭像者一律使用本地字母佔位圖，行為更一致但會失去既有的 Gravatar 整合。
