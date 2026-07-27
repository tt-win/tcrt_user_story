# 回滾手冊

本 change 沒有 DB migration，回滾原則上等同 `git revert`。但有一個**必須先讀完再動手**的缺口（見 design「Migration Plan」與 redteam F2）。

## 何時會踩到缺口

同時滿足下列兩個條件才成立：

1. 本 change 已上線，且上線後**曾經建立過新 team**（其 `teams.wiki_token` 與 `teams.test_case_table_id` 為空字串 `''`）。
2. 需要回滾。

若上線後沒有建立過任何新 team，直接 `git revert` 即可，DB 不需要任何動作。

## 症狀

revert 之後 `LarkRepoConfig` validator 回歸（要求 `wiki_token` 長度 ≥ 10、`test_case_table_id` 以 `tbl` 開頭）。`get_teams()` 以 list comprehension 對**所有** team 呼叫 `team_db_to_model()`，因此只要有任何一筆空字串 team，整個 `GET /api/teams` 回 500：

- `/team-management` 顯示不出任何 team
- 首頁 team 卡片全空
- 症狀是**全域**的，不是只有那一筆 team 消失

## 修復步驟

### 1. 先備份

依專案既有的升版備份流程備份 main DB（或至少 `teams` 表）。這是資料寫入操作，不可略過。

### 2. 把空字串補成可通過 validator 的 placeholder

三個引擎（SQLite／MySQL 8／PostgreSQL 16）皆適用同一段標準 SQL：

```sql
UPDATE teams
SET wiki_token = 'LARK_REMOVED_PLACEHOLDER',
    test_case_table_id = 'tblLARKREMOVED'
WHERE wiki_token = '' OR test_case_table_id = '';
```

placeholder 的選值必須滿足舊 validator：`wiki_token` 至少 10 字元、`test_case_table_id` 以 `tbl` 開頭。上面兩個值都是刻意選成一眼可辨識為「非真實 token」的字串，方便日後盤點。

### 3. 驗證

以任一已登入帳號呼叫 `GET /api/teams/`，應回 200 且列出全部 team。

## 替代做法

若不想寫入 DB，也可以在 revert 的同時放寬 `app/models/team.py` 的 `LarkRepoConfig` validator（允許空字串），只 revert 前端與 API 欄位。適用於「只想退掉 UI 變更、不想動任何資料」的情境。

## 為什麼一開始不直接寫 placeholder

寫入看起來像真實設定的假值，會讓既有 team 的歷史 token（cold data）與新 team 的佔位值無法區分，而且 revert 後 `is_lark_configured` 會錯誤地回報 `true`。用一份回滾手冊換取資料語意的乾淨，是划算的取捨（design D1／Migration Plan）。
