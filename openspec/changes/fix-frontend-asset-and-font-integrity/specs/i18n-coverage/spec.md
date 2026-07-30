# i18n-coverage Specification Delta

本 delta 新增執行期語系載入量的需求。既有的三語 key 齊備、CI 檢查與詞彙一致性需求不變。實測顯示每次頁面載入都會下載全部三份語系檔（`en-US.json` 49.8KB + `zh-TW.json` 53.5KB + `zh-CN.json` 53.7KB ≈ 157KB），而實際只使用其中一份。

## ADDED Requirements

### Requirement: Only the active locale is fetched at runtime

系統 SHALL 在初始載入時只取得當前語系的翻譯檔。其他語系的翻譯檔 SHALL 僅在使用者切換語系時才取得。此需求 SHALL 不影響三語系 key 齊備的既有契約。

#### Scenario: Initial load fetches one locale

- **WHEN** 使用者載入任一頁面
- **THEN** 系統 SHALL 只請求當前語系的翻譯檔
- **AND** SHALL 不請求其他語系的翻譯檔

#### Scenario: Switching locale fetches the target on demand

- **WHEN** 使用者切換語系
- **THEN** 系統 SHALL 取得目標語系的翻譯檔
- **AND** SHALL 在取得成功後才套用新語系

#### Scenario: Failed locale fetch preserves the current language

- **WHEN** 目標語系的翻譯檔取得失敗
- **THEN** 系統 SHALL 維持當前語系並回報失敗
- **AND** SHALL 不留下部分套用的翻譯狀態
- **AND** SHALL 不使頁面因載入保護而持續隱藏
