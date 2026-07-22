# UI Design: add-global-ai-assistant

task 7（前端 widget）的**視覺與狀態規格**，讓實作精確復刻。行為需求見 `specs/assistant-widget-ui/spec.md`；本文件補視覺細節與各狀態的結構。

## 視覺基準

- **完整可運行範例**：本目錄 `ui-mock.html`（standalone HTML，開瀏覽器即可互動，含 8 個可重播情境與 UI 狀態總覽）。實作時以它為像素級基準。
- 已發佈互動 artifact：https://claude.ai/code/artifact/537bb45e-1c9a-4c09-af3c-04bd96f10ed7
- 樣式沿用 TCRT design token，於瀏覽器實測、console 無錯誤。

## 從 mock 到 production 的轉換（重要）

`ui-mock.html` 是 standalone 檔（自帶 token 複製、inline script、簡短 class）。落地到 TCRT 時：

| mock | production |
|---|---|
| inline `<style>` 自帶 token | `app/static/css/assistant-widget.css`，**直接用 TCRT 既有 `var(--tr-*)`/`var(--color-*)`，勿複製 token 定義**（`.stylelintrc.json` 警告 raw hex） |
| 簡短 class（`.assistant-panel`、`.confirm-card`…） | 全部加前綴 `tcrt-assistant-` 避免與頁面衝突（`.tcrt-assistant-panel`、`.tcrt-assistant-confirm-card`…） |
| inline `<script>` 情境引擎 | `app/static/js/assistant-widget.js`（IIFE，仿 `team-nav.js`），SSE parser/確認卡狀態機/取消流程抽純函式模組（task 8.8 測試） |
| 寫死中文文案 | `data-i18n` 屬性 + `window.i18n.t()`，三語系（見 i18n keys 節） |
| `<header>`/`<main>` 仿 TCRT 頁 | 不需要——production 注入 `#tcrt-assistant-root`（FAB + panel）到 `document.body` |
| demo bar、UI 狀態總覽區 | 僅 mock 用，不落地 |

## 設計 token（沿用 TCRT，勿用 raw hex）

- 主色：`--tr-primary`(#4a90e2)、`--tr-primary-dark`、`--tr-primary-light`；`--color-primary-rgb`（陰影用）
- 語意：`--tr-success/-dark/-light`、`--tr-warning/-dark/-light`、`--tr-danger/-dark/-light`
- 中性：`--tr-bg-body/-card/-sidebar`、`--tr-border/-light/-medium`、`--tr-text-primary/-secondary/-muted`
- 陰影：`--tr-shadow-sm/-md/-lg`；版面：`--header-height`(64px)、`--footer-height`(52px)

## 佈局與 z-index

| 元素 | 規格 |
|---|---|
| FAB | `position:fixed; right:20px; bottom:calc(var(--footer-height) + 16px); 52×52 圓; z-index:1045` |
| panel | `position:fixed; right:20px; bottom:calc(var(--footer-height) + 16px + 52 + 12px); width:390px; height:min(640px, calc(100vh - --header-height - --footer-height - 96px)); z-index:1045` |
| mobile (`max-width:575.98px`) | panel `inset:0; width:auto; height:auto; border-radius:0; z-index:1046`；FAB 開啟時可隱藏 |
| 開關動畫 | `.is-open` 切 `opacity`/`transform`，`transition:.15s`，包在 `@media (prefers-reduced-motion:no-preference)` |

z-index 依據：footer 1030、分頁列 1040、**widget 1045**、Bootstrap modal 1050/1055（modal 須蓋過 widget）。

## 元件規格

### FAB
- 圓形，`background:linear-gradient(135deg, var(--tr-primary), var(--tr-primary-dark))`，白色聊天氣泡 icon，`box-shadow:0 4px 14px rgba(var(--color-primary-rgb),.45)`
- hover `translateY(-2px)`；unread 紅點：子元素 `.unread`，容器 `.has-unread` 時顯示（`--tr-danger` + 白邊）

### 面板 header
- `linear-gradient(135deg, primary, primary-dark)` 底、白字；標題「TCRT 助手」+ team badge（半透明白底 pill）
- 三個 icon button（透明白字，hover 半透明白底）：**對話紀錄**（開歷史下拉）、**新對話**、**關閉**
- **對話歷史下拉** `.history-menu`（`.show` 顯示）：絕對定位於 header 下、`--tr-bg-card` 底、標題「近期對話（<team>）」、近 N 筆 `.hm-item`（`.t` 標題截斷 + `.m` 相對時間）、底部 `.hm-new`「＋ 新對話」

### Scope note `.assistant-scope`
- `--tr-primary-light` 底、資訊 icon（primary-dark）+ 文案
- **必含資料外送警告**：末段 `.warn`（`--tr-warning-dark` 粗體）
- 文案：「僅協助 TCRT 的 test case 與 test run 操作，動作以你的帳號權限執行。**對話內容會送往外部 LLM，請勿貼入密碼等機密。**」

### 訊息氣泡
- 容器 `.assistant-messages`（`aria-live="polite"`，flex column gap 12px，`--tr-bg-body` 底）
- `.msg.user .bubble`：右對齊、`--tr-primary` 底白字、右下角小圓角
- `.msg.assistant .bubble`：左對齊、`--tr-bg-card` 底、`--tr-border-light` 邊、`shadow-sm`、左下角小圓角
- 支援 markdown：`p`/`ul`/`table`（細邊、`tabular-nums`）/`code`（sidebar 底細邊）
- typing 指示 `.typing`（3 點 blink 動畫，reduced-motion 停）

### 工具執行步驟 `.tool-activity`
- 原生 `<details open>`（可摺疊、鍵盤友善），`summary` 「執行動作」（▸ 旋轉）
- 每步 `.tool-step`：`.st` 內 `.spinner`（旋轉）→ 完成換 `✓`（`.ok` success-dark）/`✕`（`.fail` danger-dark）+ `.desc`（含 `code`）
- 全部完成後 `details` 收合

### 兩級確認卡 `.confirm-card`（核心）
所有 write 都產生確認卡，依 risk_level 兩級：

**輕量卡 `.confirm-card.light`**（idempotent_write / reversible_write）
- `--tr-bg-card` 底、`border-left:3px solid var(--tr-primary)`、單行 `.cc-desc`（可含 `.tag` 動作標籤 pill）
- `.acts`：`btn btn-sm btn-primary`「確認」+ `btn-text`「取消」（低打擾）

**警告卡 `.confirm-card.warning`**（high_impact / irreversible）
- `--tr-warning-light` 底、`border-left:4px solid var(--tr-warning-dark)`
- `.cc-title`（警告 icon + 「需要你的確認」，warning-dark 粗體）+ 影響清單 `ul`
- `.acts`：`btn btn-sm btn-danger`（如「確認刪除」）+ `btn btn-sm btn-outline`「取消」

**決定後**：`.acts` 換成 `.resolved` 徽章 pill——`.done`「已確認」（success）、`.no`「已取消」/「已過期」（sidebar 灰）、`.yes`（danger，刪除已確認可用）。卡片轉為不可再操作。
**pending 期間**鎖 composer（見下）。續聊載入歷史時未過期 pending 卡重現為可操作；`unknown` 呈現結果不明卡。

### 結果不明卡 `.result-unknown`
- `--tr-bg-sidebar` 底、`border-left:4px solid var(--tr-warning-dark)`
- `.ru-title`（問號 icon + 「結果不明」warning-dark）+ `.ru-body`：「操作已送出但未收到執行確認。系統不會自動重試——請用查詢工具核對實際狀態後再決定。」

### 停止 / 取消（兩段明確狀態）
- streaming 時 send 按鈕變 `.send-btn.stop`（`--tr-danger` 底、方塊 icon）
- **停止中**：按停止 → `composer.stopping` 顯示 hint「停止中…等待當前操作收尾」（`--tr-danger-dark`），輸入仍鎖；send 暫禁用
- **已取消**：當前工具收尾後 → 插入 `.sys-note` 灰 pill「已取消 — 已開始的單一操作照常完成，不再啟動下一步」，輸入解鎖
- 兩者 MUST 為可區分的視覺狀態（對應 spec「停止與取消狀態區分」）

### 錯誤氣泡 `.error-bubble`
- `--tr-danger-light` 底、danger 邊、錯誤訊息 + 「重試」按鈕（以 `client_message_id` 重播，不重跑已成功工具）

### Composer `.assistant-composer`
- 附件 `.attach-chip`（`.show` 顯示，primary-light pill + 移除 ✕）
- `.row`：`.attach-btn`（迴紋針）+ `textarea`（自動增高 max 96px）+ `.send-btn`（streaming 變 stop）
- `.composer-hint`：左「Enter 送出 · Shift+Enter 換行」、右 `.lock`（`.locked`/`.stopping` 時顯示「等待你確認上方操作」/「停止中…」）
- 鎖定：`textarea:disabled` + `send-btn:disabled` + `.locked`

## 互動流程對照（8 情境 → UI 狀態流轉）

對應 `ui-mock.html` demo 情境，實作 SSE 事件流應能重現：

| 情境 | UI 流轉 |
|---|---|
| ① read 連鎖 | user 泡 → assistant 泡（typing→文字）→ tool-activity（查詢 ✓）→ 結果表格 |
| ② 建 case（輕量） | assistant 泡 → **輕量確認卡** → 確認 → 已確認徽章 + tool-activity → 完成文字 |
| ③ 多步驟逐步確認 | 每個 write **各一張輕量卡**，確認後才出下一張（建 run→加 case→標記），非一次連鎖 |
| ④ 刪除（警告） | assistant 泡 → **警告確認卡**（影響清單）→ 確認刪除 → tool-activity → 稽核說明；取消→歸檔引導 |
| ⑤ 停止→已取消 | streaming（send=stop）→ 停止 → **停止中** hint → 收尾 → **已取消** sys-note + 說明 |
| ⑥ 結果不明 | 輕量卡 → 確認 → tool-activity 中斷 → **result-unknown 卡** |
| ⑦ credential 拒 | user 泡（含密碼）→ assistant 拒絕 + 引導改用 UI（不建立 pending） |
| ⑧ off-topic | user 泡 → assistant 固定語氣拒絕 + 引導回 TCRT |

## SSE 事件 → UI 對照

| event | 前端行為 |
|---|---|
| `message_start` | 建 assistant 泡、typing 指示 |
| `text_delta` | append buffer，rAF 節流 `DOMPurify.sanitize(marked.parse(buffer))` |
| `tool_started` | tool-activity 加 spinner 步驟列 |
| `tool_finished` | spinner→✓/✕ + 結果摘要 |
| `confirmation_required` | 依 risk_level 渲染輕量/警告確認卡，鎖 composer |
| `error` | error-bubble + 重試 |
| `done` / `cancelled` | 結束泡、解鎖 composer、（cancelled 顯示已取消） |

markdown：lazy-load `marked@4.3.0` + `DOMPurify`（pinned CDN），失敗 fallback `escapeHtml`；連結加 `target=_blank rel=noopener`。

## i18n keys（`assistant` namespace，三語系全補）

`en-US.json` / `zh-CN.json` / `zh-TW.json` 皆須新增：

```
assistant.fabLabel            開啟 TCRT 助手
assistant.title               TCRT 助手
assistant.scopeNotice         僅協助 TCRT 的 test case 與 test run 操作，動作以你的帳號權限執行。
assistant.scopeDataEgress     對話內容會送往外部 LLM，請勿貼入密碼等機密。
assistant.inputPlaceholder    詢問或操作 test case / test run…
assistant.send / stop         送出 / 停止
assistant.enterHint           Enter 送出 · Shift+Enter 換行
assistant.historyTitle        近期對話（{team}）
assistant.newConversation     新對話
assistant.close               關閉
assistant.confirm / cancel    確認 / 取消
assistant.confirmDelete       確認刪除
assistant.confirmTitle        需要你的確認
assistant.confirmPendingHint  等待你確認上方操作
assistant.resolvedConfirmed   已確認
assistant.resolvedCancelled   已取消
assistant.resolvedExpired     已過期
assistant.unknownTitle        結果不明
assistant.unknownBody         操作已送出但未收到執行確認。系統不會自動重試——請用查詢工具核對實際狀態後再決定。
assistant.stopping            停止中…等待當前操作收尾
assistant.cancelledNote       已取消 — 已開始的單一操作照常完成，不再啟動下一步
assistant.credentialRejected  基於安全，我無法透過對話寫入密碼／token 類的 test data，請改用 test case 編輯器。
assistant.offtopicRejected    抱歉，我只能協助 TCRT 內的 test case 與 test run 操作。
assistant.errorGeneric / retry / activity / executing({tool}) / teamSwitched / emptyState …
```

每個 `t()` 呼叫帶英文 fallback（codebase 慣例）。動態注入 DOM 用 `data-i18n`（`base.html` 的 body MutationObserver 自動翻譯）+ 防禦性 `window.i18n.retranslate(root)`。

## 無障礙

- FAB `data-i18n-aria-label`；panel `role="dialog" aria-modal="false" aria-label`
- composer：Enter 送出 / Shift+Enter 換行（`e.isComposing` guard 防 CJK IME 誤送）；Esc 關閉（先關歷史下拉再關面板）
- 開啟聚焦 textarea、關閉還焦 FAB；訊息區 `aria-live="polite"`；tool-activity 用原生 `<details>`
- FOUC：widget 在 `body.i18n-loading` opacity 守衛下注入；reduced-motion 尊重

## 響應式與主題

- mobile（<576px）panel 全螢幕；TCRT 為 light-only 產品，widget 單一 light 主題（mock 用 `color-scheme:light`）。
