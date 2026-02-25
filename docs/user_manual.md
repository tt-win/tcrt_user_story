# 測試案例管理系統操作手冊 (Test Case Repository Tool User Manual)

本手冊旨在協助使用者了解並操作測試案例管理系統 (Test Case Repository Tool)。本系統提供測試案例的建立、管理、執行以及與 Lark (飛書) 的整合功能。

## 目錄

1. [系統簡介](#系統簡介)
2. [快速入門](#快速入門)
3. [測試案例管理 (Test Case Management)](#測試案例管理-test-case-management)
    - [瀏覽測試案例](#瀏覽測試案例)
    - [建立測試案例](#建立測試案例)
    - [編輯測試案例](#編輯測試案例)
    - [批次操作](#批次操作)
    - [搜尋與篩選](#搜尋與篩選)
4. [測試執行管理 (Test Run Management)](#測試執行管理-test-run-management)
    - [建立測試執行](#建立測試執行)
    - [執行測試](#執行測試)
    - [Test Run Sets](#test-run-sets)
5. [User Story Maps](#user-story-maps)
6. [團隊管理 (Team Management)](#團隊管理-team-management)
7. [統計報表 (Statistics)](#統計報表-statistics)

---

## 系統簡介

測試案例管理系統是一個協助團隊有效管理測試流程的工具。它允許使用者維護測試案例庫、規劃測試執行、追蹤測試結果，並透過與 Lark 的整合，確保資訊的同步與透明。

## 快速入門

### 登入與首頁
登入系統後，您將看到首頁，其中包含主要功能的入口：
- **Test Case Management**: 管理測試案例庫。
- **Test Run Management**: 規劃與執行測試。
- **User Story Maps**: 查看使用者故事地圖。
- **Team Management**: 管理團隊成員與權限。
- **Statistics**: 查看測試統計數據。

---

## 測試案例管理 (Test Case Management)

進入「測試案例管理」頁面，您可以對測試案例進行全方位的操作。

### 瀏覽測試案例
頁面左側為 **Section (目錄)** 結構，右側為測試案例列表。
- 點擊左側目錄可篩選該目錄下的測試案例。
- 列表顯示測試案例的編號 (Test Case Number)、標題 (Title)、優先級 (Priority)、狀態等資訊。

### 建立測試案例
1. 點擊頁面右上角的 **「新增測試案例」** 按鈕。
2. 填寫測試案例資訊：
    - **Title**: 測試案例標題。
    - **Precondition**: 前置條件 (支援 Markdown)。
    - **Steps**: 測試步驟 (支援 Markdown)。
    - **Expected Result**: 預期結果 (支援 Markdown)。
    - **Priority**: 優先級 (High, Medium, Low)。
    - **Test Case Set / Section**: 選擇所屬的集合與目錄。
3. 點擊 **「儲存」**。

### 編輯測試案例
- 在列表中點擊測試案例標題，即可開啟詳細資訊視窗進行編輯。
- 支援 **快速編輯 (Quick Edit)**：滑鼠懸停在列表中的標題或特定欄位上，點擊出現的編輯圖示即可直接修改。
- 目前一般使用者 UI 已隱藏 **AI 改寫 (AI Rewrite)** 入口；後端 AI assist 能力保留，供後續治理完成後再開放。

### 批次操作
系統提供強大的批次操作模式，點擊 **「大量模式」** 按鈕展開選單：

#### 1. 大量新增模式 (Bulk Create)
- 支援類似 Excel 的介面，可一次輸入多筆測試案例。
- 填寫 Title, Priority, Precondition, Steps, Expected Result 等欄位。
- 點擊 **「預覽」** 確認資料無誤後，點擊 **「匯入」**。

#### 2. 大量編輯模式 (Bulk Edit)
- 進入模式後，可勾選多筆測試案例。
- 支援批次修改優先級、狀態、指派人員等。
- 支援 **批次複製** 與 **批次刪除**。

### 搜尋與篩選
頁面上方提供多種篩選工具：
- **關鍵字搜尋**: 搜尋標題或內容。
- **Test Case Number**: 依編號搜尋。
- **TCG**: 依關聯的 TCG 單號搜尋。
- **Priority**: 依優先級篩選。
- **進階篩選**: 點擊篩選圖示可展開更多選項。

---

## 測試執行管理 (Test Run Management)

此功能用於規劃測試週期 (Cycle) 或特定發布 (Release) 的測試執行。

### 建立測試執行 (Test Run)
1. 進入「測試執行管理」頁面。
2. 若無任何 Test Run，可點擊 **「建立第一個測試執行」**。
3. 設定 Test Run 資訊：
    - **名稱**: 例如 "v1.0 Regression Test"。
    - **關聯 Lark Table**: 設定同步的 Lark 表格 (若有)。
4. 選擇要納入此 Test Run 的測試案例。

### 執行測試
1. 點擊 Test Run 卡片進入 **執行頁面**。
2. 頁面顯示待測的測試案例列表。
3. 對每個測試案例進行標記：
    - **Pass**: 通過。
    - **Fail**: 失敗 (可填寫失敗原因與截圖)。
    - **Block**: 受阻。
    - **Retest**: 需重測。
4. 系統會自動計算進度與通過率。

### Test Run Sets
- 可將多個相關的 Test Run 群組為一個 **Test Run Set** (例如：依據不同平台 iOS/Android 分組)。
- 方便統一查看整體進度。

---

## User Story Maps

- 提供視覺化的使用者故事地圖。
- 可將測試案例關聯至特定的 User Story，確保測試覆蓋率。
- 支援從 JIRA 匯入 User Story (若有設定整合)。

---

## 團隊管理 (Team Management)

- **成員列表**: 查看團隊成員。
- **權限設定**: 設定成員的角色 (Admin, Editor, Viewer)。
- **Lark 整合**: 設定團隊對應的 Lark Wiki Token 與 App ID，以啟用同步功能。

---

## 統計報表 (Statistics)

- 提供測試案例的統計數據，如：
    - 測試案例總數與成長趨勢。
    - 各優先級分佈。
    - 自動化 vs 手動測試比例。
    - 測試執行通過率趨勢。

---

## 附錄：Markdown 支援
本系統的文字編輯器支援標準 Markdown 語法：
- **粗體**: `**text**`
- *斜體*: `*text*`
- 列表: `- item`
- 程式碼區塊: ```code```

> [!TIP]
> 使用快捷鍵 `Ctrl+B` (粗體), `Ctrl+I` (斜體) 可加速編輯。
