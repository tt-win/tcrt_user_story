# ui-design-system Specification Delta

本 delta 取代既有的「CDN dependency pinning and single sourcing」。原條款允許依賴來自「同一 CDN origin 或本地 `static/vendor/`」二擇一，且只涵蓋第三方函式庫。實測顯示現況同時違反該條款（jsdelivr + cdnjs + googleapis 三個 origin），且其涵蓋範圍未及於字型與使用者頭像——後者使每次頁面瀏覽都向外部服務洩漏使用者存在，並在內網封鎖時失效。本 delta 以自託管契約取代該條款，並新增字型 token 與實際載入字型檔的一致性需求。

## REMOVED Requirements

### Requirement: CDN dependency pinning and single sourcing

**Reason**: 該條款的兩個選項（單一 CDN origin／本地 vendor）在強度上不等價，實務上被讀成「只要不混用 origin 即可」，因而未阻止對外部服務的執行期依賴。其涵蓋範圍亦僅限第三方函式庫，未涵蓋網頁字型與使用者頭像——2026-07-30 實測單頁接觸 6 個外部網域、24 個請求，其中 17 個是直連 `s16-imfile-sg.feishucdn.com` 的使用者頭像（每張 1.3–2.2 秒）。對內網部署的 QA 工具而言，任何外部 origin 都是可用性與隱私風險。

**Migration**: 由新的「Self-hosted presentation assets with no runtime external origins」承接並強化——版本鎖定的要求完整保留（且新增 manifest 可追溯性），單一來源的要求收斂為「應用程式自身 origin」，涵蓋範圍擴及字型與使用者頭像。既有依賴改以 `app/static/vendor/` 提供，無行為變更；頭像改由後端代理端點提供，上游不可用時降級為本地佔位圖。

## ADDED Requirements

### Requirement: Self-hosted presentation assets with no runtime external origins

系統 SHALL 由應用程式自身 origin 提供所有**呈現資產**——樣式表、腳本、圖示字型、網頁字型與使用者頭像。瀏覽器在渲染任一頁面時 SHALL 不為呈現資產向應用程式以外的 origin 發出請求。自託管資產 SHALL 鎖定於明確版本，並附記錄來源與版本的 manifest。

本需求的範圍限於呈現資產，SHALL 不涵蓋**功能性外部內容**——即由使用者設定的整合服務所提供、以連結或內嵌方式呈現的內容（例如 `automation-hub-run-orchestration` 規範的 Allure 報表 `<iframe src="{report_url}">`、Jira 與 Lark 的外部連結）。此類內容的來源由其所屬能力規範，SHALL 不受本需求限制。

#### Scenario: No external origin is requested for presentation assets

- **WHEN** 已驗證使用者載入任一頁面
- **THEN** 該頁面的樣式表、腳本、字型、圖示與頭像請求 SHALL 指向應用程式自身 origin
- **AND** SHALL 不存在指向 CDN、字型服務或頭像服務的請求

#### Scenario: Functional embeds are out of scope

- **WHEN** 頁面依所屬能力的契約內嵌外部報表或連結至外部整合服務
- **THEN** 該內嵌或連結 SHALL 不因本需求而被禁止
- **AND** 其來源與行為 SHALL 由該能力自身的需求規範

#### Scenario: Dependencies are version-pinned and traceable

- **WHEN** 自託管任一第三方依賴
- **THEN** 其版本 SHALL 為明確鎖定的版本
- **AND** SHALL 於 manifest 記錄來源與版本，SHALL 不使用會自動跟進更新的浮動版本

#### Scenario: User avatars are served through the application

- **WHEN** 任一頁面呈現使用者頭像
- **THEN** 該圖片 SHALL 由應用程式端點提供
- **AND** 上游不可用時 SHALL 降級為本地產生的佔位圖，SHALL 不回退為直連外部服務

#### Scenario: Application remains usable without external network access

- **WHEN** 部署環境無法連線至外部網域
- **THEN** 所有頁面的樣式、圖示、字型與頭像 SHALL 正常呈現
- **AND** 功能性外部內容 SHALL 依其所屬能力的降級規則處理，SHALL 不影響頁面本身的可用性

### Requirement: Declared font tokens are backed by actually loaded font files

每一個宣告的 `--font-*` token SHALL 對應到實際載入且可解析的字型檔。系統 SHALL 不宣告無對應字型檔的 token，亦 SHALL 不引用無效的字型 family 名稱。介面主要語言（zh-TW／zh-CN）的文字 SHALL 由明確載入的 CJK 字型呈現，SHALL 不依賴作業系統 fallback。

#### Scenario: Every font token resolves to a loaded file

- **WHEN** 樣式表宣告 `--font-*` token
- **THEN** 該 token 所指的 family SHALL 有對應的自託管字型檔被載入

#### Scenario: CJK text uses an explicitly loaded font

- **WHEN** 以 zh-TW 或 zh-CN 呈現介面
- **THEN** 中文字符 SHALL 由明確載入的 CJK 字型呈現
- **AND** SHALL 不因無效 family 名稱而 fallback 至系統字型

#### Scenario: Single font-family declaration per element scope

- **WHEN** 樣式表為同一選擇器宣告 `font-family`
- **THEN** SHALL 僅存在單一有效宣告
- **AND** SHALL 不以 `!important` 解決同層級的重複宣告衝突
