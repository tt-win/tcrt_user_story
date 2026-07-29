## ADDED Requirements

### Requirement: Test Run Item SHALL support a nullable local TCRT assignee identity

`test_run_items` SHALL 擁有 nullable `assignee_user_id`，以 foreign key 指向 `users.id` 並使用 `ON DELETE SET NULL`。既有 `assignee_id`、`assignee_name`、`assignee_en_name`、`assignee_email`、`assignee_json` MUST 保留。既有 JWT/Test Run Item response MUST additive 地回傳 `assignee_user_id`，不得移除既有 assignee 欄位；app-token 與 Assistant 的既有最小 projection MUST NOT 因此新增或洩露 local user id。

main Alembic migration MUST 新增 `(assignee_user_id, updated_at)` 與 Result History `(changed_by_id, changed_at)` 索引，並可在 SQLite、MySQL 8、PostgreSQL 16 upgrade/downgrade。audit DB MUST 不新增 schema。backfill 只能以 active、具既有 Team write capability 且 candidate count 恰為一的 exact trimmed `lark_user_id` 或 `trim + lower` normalized email 執行；若 Item 同時有 id/email 而候選不同、任一值歧義、不匹配或 read-only／inactive，MUST 不回填。MUST NOT 以 name、username 或 full name 推論。

#### Scenario: TCRT-only 帳號可成為穩定 assignee

- **WHEN** active TCRT user 沒有 `lark_user_id` 但被明確指定為 Item 的 `assignee_user_id`
- **THEN** Item 儲存該 local id 與本地 display snapshot，且 Dashboard 能以該 id 找到此 Item

#### Scenario: App token 不會取得 local assignee identity

- **WHEN** app-token client 讀取既有的 Test Run Item 最小 projection
- **THEN** response 維持既有最小欄位，不包含 `assignee_user_id` 或完整 local User 資料

#### Scenario: legacy 同名資料不會被回填

- **WHEN** legacy Item 只含 `assignee_name`，且多個或零個 local user 可能對應此名稱
- **THEN** migration 不回填 `assignee_user_id`，並保留 legacy snapshot 原樣

#### Scenario: 精確 Lark 或 email 可回填

- **WHEN** legacy Item 的 Lark id 或 normalized email 唯一對應一個 local User
- **THEN** migration 回填該 User id，且不刪除既有 Lark snapshot 欄位

#### Scenario: 刪除 local User 不刪除 Test Run Item

- **WHEN** 應用程式永久刪除已被指派的 local User
- **THEN** 同一 transaction 先清除所有精確比對該 User local FK、Lark id 或 normalized email 的 Item 之 `assignee_user_id`、`assignee_id`、`assignee_email`、`assignee_json`，保留非機器可比對 display snapshot，再刪除 User；Test Run Item 不會被刪除

#### Scenario: 重用外部 identity 的新帳號不承接已刪除者的指派

- **WHEN** 已刪除 User 的舊 Lark id 或 email 被新建 User 重用
- **THEN** 原 Item 沒有可供 legacy fallback 比對的 machine identity，不會出現在新 User 的 Dashboard

#### Scenario: downgrade 保留 legacy 指派資料

- **WHEN** 應用程式已先回退且執行此 change 的 migration downgrade
- **THEN** 系統只移除新 FK／索引／欄位，不修改既有 Lark／name snapshot 欄位

### Requirement: TCRT assignee lookup MUST be minimally scoped and authorized

系統 SHALL 提供供 Test Run 指派 UI 使用的 team-scoped local assignee lookup。它 MUST 要求既有 Test Run write permission，且只回傳有限筆數的 local id、顯示名稱與 `lark_linked` boolean。lookup 只可列出 active 且在查詢時依既有授權模型可執行該 Team Test Run 的 User；MUST NOT 回傳 email、role、token、password、完整 profile 或管理員使用者清單資料。

#### Scenario: 可寫入者取得最小 assignee 選項

- **WHEN** 有 Test Run write permission 的使用者查詢目標 Team 的 assignee lookup
- **THEN** 回應只包含符合資格的 active User 最小欄位與伺服器上限，且不含 email 或 role

#### Scenario: 無寫入權限的使用者被拒絕

- **WHEN** 沒有 Test Run write permission 的使用者呼叫 assignee lookup
- **THEN** 系統回傳 403，且不回傳任何 User option

#### Scenario: inactive 或 read-only User 不可被新指派

- **WHEN** local User 已停用或依現有角色模型僅有 read capability
- **THEN** 該 User 不出現在 lookup，且明確指定其 id 的 assignment write 被拒絕

### Requirement: All Test Run Item writes MUST use one unambiguous assignee normalizer

所有 Test Run Item create、single update、batch update、filtered batch、app-token、Assistant、Test Run restart/re-run clone 與 Test Run Set 產生的 Item SHALL 經同一 assignee normalizer。update MUST 以 field presence 判斷 assignment intent：沒有任一 assignee field 時 MUST 保留既有 identity；恰有一種 representation 且值為 `null`／空白字串時才是 clear。每一次 assignment update 只能指定 `assignee_user_id`、structured Lark `assignee`、legacy `assignee_name` 的其中一種；唯一例外為 local id 與 Lark object 同時存在且兩者精確解析為同一 User。其他混合、矛盾或無法解析的一致性宣告 MUST 回 422。bulk endpoint MUST 在改動任一 Item 前完成所有 assignee payload preflight；任一 payload 無效時 MUST 回 422 且不得改動任一 Item identity。

明確 local id MUST 驗證 target active 與既有 Test Run write/execute authorization，並以 non-empty `full_name` fallback `username` 保存 local display snapshot；若沒有同一人的經驗證 structured Lark object，MUST 清除原有 Lark snapshot。structured Lark assignee 只能按 unique exact trimmed `lark_user_id` 或 `trim + lower` normalized email 解析 local User；同一物件同時帶 id/email 時兩者候選不同 MUST 回 422，任一 key 無法安全解析或候選為 read-only／inactive 時只可保存純 Lark snapshot、不得建立 local FK。legacy name-only update MUST 永遠清除 `assignee_user_id` 並不得做名稱解析；clear assignee MUST 同時清除 local 與所有外部 snapshot。restart/re-run clone MUST 重新驗證來源 local assignee；若來源 User 已停用或不再有 write capability，新的 Item 不得保留 local 或可 machine-match 的外部 identity。

#### Scenario: 明確 local assignee 清除不相符 Lark snapshot

- **WHEN** Item 原本有 Lark User A，而寫入者將 `assignee_user_id` 明確改為沒有同時匹配 Lark object 的 local User B
- **THEN** 系統將 local id 與 B 的 display snapshot 寫入，並清除 A 的 Lark snapshot 欄位

#### Scenario: local 與 Lark payload 矛盾時失敗

- **WHEN** request 同時傳入 local User A id 與可解析為 local User B 的 structured Lark object
- **THEN** 系統回傳 422，且 Item 的所有 assignee 欄位不變

#### Scenario: structured Lark payload 唯一解析 local User

- **WHEN** request 只傳入帶唯一 Lark id 或 normalized email 的 structured assignee
- **THEN** 系統保存既有 Lark snapshot，並同步設定對應的 `assignee_user_id`

#### Scenario: Test Run selector 保留單一明確的 machine identity

- **WHEN** 使用者在單筆或批次 Test Run selector 選取 local TCRT user 或帶 Lark id/email 的 contact
- **THEN** 前端分別送出 `assignee_user_id` 或 structured `assignee`，且 Lark contact 有 id 時只送 id、沒有 id 時才送 normalized email，不把同一 contact 的 id/email snapshot 當成兩個獨立一致性宣告；不得將已選取的候選降級成只有 `assignee_name`，只有未選取候選的明確自訂文字維持 legacy name-only 行為

#### Scenario: 批次確認與單筆清除不因 assignee representation 發生執行期錯誤

- **WHEN** 使用者以 local TCRT、Lark id、email fallback 或自訂文字確認批次指派，或在單筆 selector 清除既有 assignee
- **THEN** 前端 MUST 完成確認流程而不發生未定義變數或 `null` 型別錯誤；批次 request 只送出所選 representation，單筆清除則送出明確的 `assignee_name: null`

#### Scenario: legacy name-only payload 不會錯認 TCRT user

- **WHEN** batch、filtered batch、Assistant 或 app-token 寫入只傳入 `assignee_name`
- **THEN** 系統保留 name-only 相容行為、清除任何舊 `assignee_user_id` 與 Lark snapshot，且不以名稱建立新 local identity

#### Scenario: 清空 assignee 清除所有 identity

- **WHEN** request 明確清空 assignee
- **THEN** 系統清除 `assignee_user_id` 與所有 Lark／name snapshot 欄位

#### Scenario: 省略 assignee 欄位不會意外清空既有指派

- **WHEN** single update payload 未出現 `assignee_user_id`、`assignee` 或 `assignee_name`
- **THEN** normalizer 不改動 Item 的任何 assignee identity 欄位

#### Scenario: Lark id 與 email 指向不同帳號時失敗

- **WHEN** structured Lark assignee 同時帶有可解析為 User A 的 id 與可解析為 User B 的 normalized email
- **THEN** 系統回傳 422，且 Item 的所有 assignee 欄位不變

#### Scenario: restart 不複製失效的 local assignee

- **WHEN** restart/re-run 的來源 Item 指向已停用或 read-only local User
- **THEN** 新 Item 只可保留安全 display snapshot，且 `assignee_user_id` 與可 machine-match 的 Lark identity 均為 null

### Requirement: Dashboard identity matching and execution activity SHALL remain precise

「指派給我」與 resume 查詢 MUST 優先比對 `assignee_user_id == current_user.id`。只有 local FK 為 null 時，才可用唯一精確 Lark id 或 normalized email 做 fallback；MUST NOT 以 name 作 fallback，且不可讓 legacy fallback 覆蓋另一個已設定的 local User。

純 assignee 變更 MUST NOT 為了 Dashboard 額外寫入或偽造 Result History execution activity。既有 execution／comment history 維持原本寫入語意；Dashboard 只把現有 actor-id history 視為個人活動來源，且僅 result／execution-time transition 可作成果或 resume 來源。

#### Scenario: local FK 優先於衝突 legacy snapshot

- **WHEN** Item 的 `assignee_user_id` 指向 User A，但遺留 Lark snapshot 恰好可解析為 User B
- **THEN** Item 只會視為 User A 的 assigned 項目，不會出現在 User B 的 Dashboard

#### Scenario: 純重新指派不被列為執行活動

- **WHEN** 寫入只變更 assignee 而不改變 result、execution time 或 comment
- **THEN** 系統不新增虛假的 Result History execution event，且 Dashboard 不將該變更列為該操作者的 execution activity
