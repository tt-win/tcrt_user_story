## 1. Backend: storage + migration

- [x] 1.1 在 `app/models/database_models.py` 新增 `SystemSetting` model（`system_settings`：`key` PK String、`value` Text、`updated_at`、`updated_by` nullable）
- [x] 1.2 新增 Alembic migration（main target）建立 `system_settings` 表，`down_revision` 指向目前 head，`downgrade` 為 `drop_table`
- [x] 1.3 啟動 app 確認 drift 檢查通過（model 與 migration 同步）

## 2. Backend: settings accessor + API

- [x] 2.1 新增小型 accessor（get/set bool by key），key `automation_hub_entry_enabled`，缺漏回退 `True`
- [x] 2.2 新增 `GET /api/system/automation-hub/settings`（`get_current_user`，回傳 `{ "enabled": bool }`）
- [x] 2.3 新增 `PUT /api/system/automation-hub/settings`（`require_super_admin()`，body `{ "enabled": bool }`，寫入並記稽核）
- [x] 2.4 確認新 router 已掛載到 app（與既有 system 路由一致的 prefix）

## 3. Frontend: toggle UI（組織自動化基礎設施分頁）

- [x] 3.1 在 `app/templates/team_management.html` 的 `tab-pane-org-automation-infra` 新增 `form-switch` 開關 UI 與說明文字
- [x] 3.2 在 `app/static/js/team-management/org-automation-infra.js` 載入時讀取開關狀態並反映到 UI
- [x] 3.3 切換開關時呼叫 `PUT`，成功顯示提示、失敗回滾 UI 狀態

## 4. Frontend: hide entry points when OFF

- [x] 4.1 新增共用讀取＋快取 helper（取得 `enabled`，失敗回退顯示）
- [x] 4.2 `app/static/js/index.js`：渲染 team card 前取得狀態，OFF 時不輸出首頁 Automation Hub 按鈕
- [x] 4.3 `app/static/js/team-management/main.js`：渲染 team card 前取得狀態，OFF 時不輸出「進入團隊」選單的 Automation Hub 項目

## 5. i18n

- [x] 5.1 在 `en-US.json` / `zh-CN.json` / `zh-TW.json` 新增開關標題、說明、儲存成功/失敗等字串

## 6. Tests + verification

- [x] 6.1 後端測試：GET 預設回 `enabled: true`；PUT 以 Super Admin 切換後 GET 回 `false`；非 Super Admin PUT 得 403；未登入 GET 被拒
- [x] 6.2 執行 `pytest app/testsuite -q` 相關測試通過
- [ ] 6.3 瀏覽器手動驗證（待執行）：OFF 時兩個入口隱藏、ON 時恢復；`/automation-hub` 直接網址仍可進入（能力保留）。後端行為已由 6.1 整合測試涵蓋；「直接網址仍可進入」由設計保證（未加任何 guard）。
