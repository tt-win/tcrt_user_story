# Red Team Review — optimize-assistant-context-and-tools

**結束條件（使用者要求）：** 多輪對抗，直到紅隊**沒有審查上的阻擋級／規格疑慮**才結束。  
**日期：** 2026-07-22  
**範圍：** proposal / design / specs（context-budget、history-compaction、efficient-tools）／tasks  
**狀態：** 規劃期；**尚未實作**

---

## 輪次總覽

| 輪次 | 性質 | 結果 |
|------|------|------|
| **R1** | 初審（曾只內嵌 design，後補 RT-01…22） | 發現主風險並定案方向；**程序不足**（未獨立成檔、未再打） |
| **R2** | 對「已寫成的 specs」重打 | **新開 9 條規格缺口**（見 §R2）→ 藍隊已修 specs／design／tasks |
| **R3** | 對「R2 修補後 specs」再打 | **無新增阻擋級疑慮**；僅產品接受殘餘（§殘餘） |

**退出裁決（R3）：** 紅隊對**現行規格文字**無「必須再改規格才能實作」的意見。  
殘餘僅為產品／營運接受項（使用者確認後的大範圍操作、模型品質崖、費用上限靠既有 admission），已簽名於 §殘餘。

---

## R1 — 初審結論（摘要，完整條目見歷史）

涵蓋：1M 誤用、char budget、soft vs hard truncate、compact DB／pair／injection、filter count 信任、cap、team、confirmation 不降級、iterations／continuation、與既有安全契約回歸。  
**R1 的程序問題：** 只跑一輪且結論曾未獨立成檔——**不符合**使用者「跑到沒有疑慮」的結束條件。

---

## R2 — 重打：新規格缺口（已全部藍隊修補）

以下為 R2 紅隊對 **R1 定案後的 specs** 仍能打穿或含糊之處；每條含 **修補後狀態**。

### RT-R2-01 模型顯式傳巨大 `limit`（非省略）
- **攻擊：** `list_test_cases(limit=100000)` 繞過「省略才注入 default」。
- **R1 漏洞：** 只規範 omit → default。
- **藍隊修補：** full list clamp ≤100；refs clamp ≤500／200；registry `max_limit`。
- **R3 複驗：** 通過（efficient-tools full list／refs clamp 情境）。

### RT-R2-02 Soft truncate 裸陣列形狀與 0 列可放入
- **攻擊／模糊：** 裸 `[]` 加 meta 形狀不定；單列 > budget 時若 hard preview 可能半截或失控。
- **藍隊修補：** 一律 envelope；0 列 → 空 items + truncated meta；禁止未 redact hard preview。
- **R3 複驗：** 通過。

### RT-R2-03 `next_skip` 無 request skip
- **攻擊／缺陷：** truncation 只見 payload 不見 args → next_skip 錯 → 分頁錯亂或重複 mutation 規劃。
- **藍隊修補：** executor MUST 傳 skip；`next_skip=(skip|0)+returned_count`。
- **R3 複驗：** 通過。

### RT-R2-04 keep_recent 永不 compact → recent 自身爆 hard budget
- **攻擊／可用性：** 4 組巨大 tool-result 使 provider request 必然超限或 400。
- **藍隊修補：** recent 優先完整，但超 hard 時組內壓縮 → 整組 trim；不得送超 hard 請求。
- **R3 複驗：** 通過。

### RT-R2-05 Compact 規格 MAY／MUST 矛盾
- **模糊：**「MAY／在 enabled 時 MUST」不可測。
- **藍隊修補：** enabled=true 時達閾值 MUST 嘗試；false 時 MUST NOT。
- **R3 複驗：** 通過。

### RT-R2-06 Filter batch TOCTOU（建立後集合變）
- **攻擊：** pending 後他人改 assignee → confirm 打到不同集合。
- **R1 不足：** 只說 server count，未強制 membership digest + re-resolve。
- **藍隊修補：** fingerprint 含排序 matched ids；confirm 重 resolve → STALE；payload 存 server ids。
- **R3 複驗：** 通過（對齊既有 confirmation stale 契約）。

### RT-R2-07 匹配 0 筆仍建 pending
- **攻擊／噪音：** 空確認卡誤導。
- **藍隊修補：** 0 筆 MUST 拒絕 pending。
- **R3 複驗：** 通過。

### RT-R2-08 Filter 語意模糊（未指派／未執行）
- **攻擊：** `assignee_name=""` 與 null 行為未定義；與 `assignee_unassigned` 混用。
- **藍隊修補：** 封閉 `assignee_unassigned` bool；test_result 明確枚舉；互斥拒絕；search 走 ORM／參數化。
- **R3 複驗：** 通過。

### RT-R2-09 分頁不穩定排序
- **攻擊：** soft truncate + skip 在不穩定 order 下漏改／重改。
- **藍隊修補：** refs／分頁 list 穩定排序（id tie-break）。
- **R3 複驗：** 通過。

### RT-R2-10（附帶）無分頁 list（configs／sets）仍可爆
- **風險：** soft truncation 已覆蓋任意 list；tool description 提示截斷。
- **藍隊：** 寫入 efficient-tools full list 需求末段。
- **R3：** 接受為 soft-truncation 通用路徑；不另開無界 API。非阻擋。

---

## R3 — 再打（修補後）檢查表

| 檢查 | 結果 |
|------|------|
| 能否不確認就 mutation？ | 否（high_impact + pending） |
| 能否用模型 count／id 當執行集合？ | 否（server resolve + payload） |
| 能否 omit 或 max limit 灌爆 context？ | 否（default + clamp + soft trunc） |
| Compact 能否改 DB／拆 pair／當 confirmation？ | 否 |
| Recent 爆 budget 是否無規格？ | 否（已規定組內壓縮／trim） |
| Stale membership？ | 有 STALE 路徑 |
| 0 筆／>500？ | 拒絕 pending／422 |
| Filter 互斥／SQL 拼接？ | 互斥拒；ORM 參數化 |
| 與既有 credential／team／projection 契約衝突？ | 未發現削弱 |
| 規格可測性（WHEN／THEN）？ | R2 修補後可測 |
| 是否還有「規格沒寫清楚會讓實作自由發揮出事」？ | **紅隊未再提出阻擋級條目** |

**R3 紅隊聲明：** 在現行三份 specs + design D1–D7（含 R2 修補）下，**沒有進一步的審查疑慮（阻擋級）**。若實作偏離規格，屬實作缺陷而非規格未審完。

---

## 殘餘（非阻擋；產品接受）

以下**不是**「規格沒寫好」，而是刻意接受：

1. 使用者在確認卡上批准最多 500 筆 filter batch（僅 10 sample ids）——誤操作風險由使用者與 UI 摘要承擔。  
2. 長 context 模型品質崖與費用——靠 working budget、admission、hourly limit，不保證 1M 品質。  
3. 不實作精確 token 計數；context 400 靠既有單次 drop group。  
4. 模型仍可能忽略 skill 去 call full list——clamp + soft trunc 限制損害，不保證模型永遠選 refs。  
5. Extreme recent 組內 trim 可能丟掉當輪部分 id——極端歷史才觸發；可再 list。

---

## 必測清單（實作門檻，R1+R2 合併）

1. Soft trunc：envelope、完整前列、meta、next_skip 含 skip。  
2. Soft trunc：0 列可放入；credential 先 redact。  
3. Soft trunc：meta 不進業務寫入。  
4. Full list omit default ≤50；顯式 limit clamp ≤100。  
5. Refs clamp ≤500／200；穩定排序。  
6. Compact 不改 DB；不拆 pair；注入不跳過 confirmation。  
7. Recent 自身爆 budget 仍 ≤ hard 且 protocol-valid。  
8. Filter batch：server count；0 拒；>500 拒；stale；未確認不執行；team mismatch。  
9. Filter 互斥 assignee_unassigned + assignee_name。  
10. max_iterations 24；continuation 重置；config clamp。

---

## 結論（符合使用者結束條件）

| 問題 | 答 |
|------|-----|
| 是否只跑一輪？ | **曾錯誤地只做 R1**；已補 **R2 重打 + 藍隊修補 + R3 複驗** |
| 紅隊是否還有審查疑慮？ | **阻擋級：無（R3）** |
| 可否實作？ | **規格層：是**；等你下令「實作」 |
| 實作中若發現新洞？ | 先開 RT-R4 回寫規格，再改碼（同一結束條件） |

**簽署（規劃紅隊 R3）：** 對 `optimize-assistant-context-and-tools` 現行規格 **無剩餘審查疑慮（阻擋級）**。
