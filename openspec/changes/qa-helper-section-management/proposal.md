## Why

QA AI Helper 的 Screen 3「需求驗證項目分類與填充」目前由 deterministic planner 自動產出 sections，使用者只能在既有 sections 內新增/刪除 verification items，但**無法新增或刪除整個 section**。當 planner 產出的 section 劃分不符合實際驗證需求時（例如某個 Acceptance Criteria 被拆得太細或遺漏了需要獨立驗證的情境），使用者只能放棄整份 plan 重來，嚴重影響效率與使用意願。

## What Changes

- **新增 section 功能**：使用者可在 Screen 3 手動新增空白 section，新 section 須符合 `PlanSection` 既有 data model（含 section_key、section_id、section_title、given/when/then、verification_items），並自動編排 section_id。
- **多選刪除 section 功能**：使用者可勾選多個 sections 後一次批次刪除。刪除後剩餘 sections 的 section_id 自動重新編號，維持連續性。
- **Section 排序功能**：使用者可透過上移/下移按鈕調整 section 順序，重新排列後 section_id 自動依新順序重新編號。
- **UI 變更**：Section rail 增加多選 checkbox、批次刪除按鈕、新增 section 按鈕、上移/下移排序按鈕。介面樣式須遵循 TCRT 既有 UI 設計規範。
- **儲存相容**：新增與刪除 section 的操作透過既有 `PUT /api/teams/{teamId}/qa-ai-helper/sessions/{sessionId}/requirement-plan` API 儲存，不需新增 API endpoint。autosave 機制須涵蓋 section 增刪操作。

## Capabilities

### New Capabilities
- `helper-plan-section-crud`: 定義 Screen 3 section 層級的新增、多選批次刪除與排序行為規範，包含 section_id 自動編排、空白 section 初始結構、批次刪除後重新編號、上移/下移排序、以及 locked 狀態下禁止操作的限制。

### Modified Capabilities
- `helper-deterministic-seed-planning`: 原 spec 僅定義 planner 自動產出 sections 與 verification items 的編輯行為，需擴充 section 層級的使用者手動 CRUD 與排序需求（新增空白 section、多選刪除 section、調整 section 順序），並明確 section_id 重編規則。

## Impact

- **前端**：`app/static/js/qa-ai-helper/main.js`（Screen 3 section rail 渲染、多選 UI、事件處理）、`app/static/css/qa-ai-helper.css`（checkbox 與 batch action 樣式）。
- **後端 Service**：`app/services/qa_ai_helper_service.py`（`save_requirement_plan` 需正確處理新增 section 的 key 分配與刪除後的 display_order 重排）。
- **資料庫**：無 schema 變更。新增 section 使用既有 `qa_ai_helper_plan_sections` 表與欄位，刪除 section 會級聯刪除其 verification_items 與 check_conditions（既有 FK cascade）。
- **i18n**：`app/static/locales/` 需新增「新增區段」、「刪除選取區段」等文案。
- **Migration / Rollback**：無 DB migration 需求，回滾僅需復原前端與 service 程式碼。
- **相容性**：不影響 planner 自動產出流程；手動新增的 sections 與 planner 產出的 sections 在 data model 層面完全一致，下游 seed generation 不需區分來源。
