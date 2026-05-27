## Context

QA AI Helper Screen 3「需求驗證項目分類與填充」目前的 section 管理架構：

- **Section 來源**：由 `QAAIHelperPlanner.build_plan()` 從 Acceptance Criteria deterministically 產出，每個 AC scenario 對應一個 section。
- **使用者操作範圍**：目前僅能在 section 內層操作（增刪 verification items、修改 category/summary/coverage_tag），section 本身不可新增或刪除。
- **資料模型**：`RequirementPlan → PlanSection[] → VerificationItem[] → CheckCondition[]`，三層巢狀結構已有完整的 DB schema（含 FK cascade delete）與 Pydantic models。
- **儲存機制**：統一透過 `PUT .../requirement-plan` 端點，整份 sections 陣列 replace 式儲存，autosave 每 5 秒觸發。
- **前端**：Section rail 為左側導覽列，每個 section 顯示標題與 item 計數，點擊選中後右側顯示編輯區。

**關鍵限制**：planner 自動劃分的 section 不一定完全符合使用者的驗證邏輯分群需求，目前缺乏手動增刪 section 的能力。

## Goals / Non-Goals

**Goals:**

- 使用者可在 Screen 3 手動新增空白 section，填入 section_title 與 Gherkin 條件後使用
- 使用者可多選 sections 後批次刪除，刪除後 section_id 自動重新編號
- 使用者可透過上移/下移按鈕調整 section 順序，排序後 section_id 自動重新編號
- 新增的 section 完全遵循既有 PlanSection data model，對下游 seed generation 透明
- UI 操作遵循 TCRT 既有設計語言（checkbox、batch action bar、icon buttons、排序按鈕）
- locked 狀態下禁止新增/刪除/排序操作

**Non-Goals:**

- 不支援 section 複製（duplicate）
- 不改動 planner 自動產出邏輯
- 不新增 API endpoint — 沿用既有 save requirement plan API
- 不改動資料庫 schema

## Decisions

### D1: 新增 section 使用前端本地建構，不經過 planner

**選擇**：使用者點擊「新增區段」按鈕時，前端直接建構一個空白 section object（使用 `createEmptySection()` 工廠函式），加入 `workspace.requirement_plan.sections` 陣列尾端，觸發 `recomputeRequirementSectionIds()` 重新編號，然後自動選中新 section 以便編輯。

**替代方案**：呼叫後端 planner 產出新 section → 被否決，因為 planner 需要 AC context 驅動，手動新增的 section 不一定對應任何 AC scenario，且增加不必要的 roundtrip。

**理由**：空白 section 的結構簡單（section_key + section_title + 空 given/when/then + 空 verification_items），前端完全可以本地建構。後續儲存時透過既有 API 統一持久化到後端。

### D2: section_key 產生策略 — 前端 UUID

**選擇**：新增 section 的 `section_key` 使用前端 `crypto.randomUUID()` 產生，格式為 `manual_{uuid}`，以便與 planner 產出的 key（格式為 `ac.scenario_XXX`）區隔。

**替代方案**：使用遞增數字（如 `manual_001`）→ 被否決，因為在多次新增刪除後可能衝突。

**理由**：UUID 保證唯一性，`manual_` prefix 讓開發者可快速識別來源。後端儲存時 `section_key` 只要在同一份 plan 內唯一即可（已有 unique constraint）。

### D3: 多選刪除使用 checkbox + batch action bar 模式

**選擇**：在 section rail 中每個 section 項目前加入 checkbox，勾選後 rail 頂部出現 batch action bar 顯示「已選 N 個區段」和「刪除」按鈕。

**替代方案 A**：逐個 section 旁邊放刪除按鈕 → 不符合「多選刪除」需求。
**替代方案 B**：使用 modal 對話框列出所有 section 讓使用者勾選 → 操作路徑較長，不如 inline checkbox 直覺。

**理由**：Checkbox + batch action bar 是 TCRT 已有的模式（session manager 的批次刪除即使用此模式），使用者無需學習新互動方式。

### D4: 刪除前 confirm dialog

**選擇**：批次刪除執行前顯示確認對話框，列出即將刪除的 section 標題清單。

**理由**：section 刪除是破壞性操作，且會連帶移除所有 verification items 與 check conditions，需要明確確認。

### D5: Section 排序使用上移/下移按鈕

**選擇**：在 section rail 中每個 section 項目右側提供上移（▲）與下移（▼）icon buttons，點擊後交換相鄰 section 在陣列中的位置，然後呼叫 `recomputeRequirementSectionIds()` 重新編號。

**替代方案 A**：Drag-and-drop 拖拉排序 → 被否決。TCRT 前端為原生 JS 無框架，實作可靠的 DnD 需要額外函式庫（如 SortableJS）或大量自訂 drag event 處理，複雜度不符合此功能的重要性。
**替代方案 B**：直接輸入 display_order 數字 → 被否決，操作不直覺且容易衝突。

**理由**：上移/下移按鈕實作簡單（swap 陣列元素）、行為明確、不需引入外部依賴。第一個 section 的上移按鈕 disabled，最後一個 section 的下移按鈕 disabled，避免無效操作。移動後維持該 section 為選中狀態，使用者可連續點擊移動多個位置。

### D6: 不新增 API endpoint

**選擇**：沿用既有 `PUT .../requirement-plan` 端點。前端刪除 sections 後，儲存時只送剩餘的 sections 陣列；後端 `save_requirement_plan` 已有 replace 邏輯——先刪除所有舊 sections 再插入新的。

**理由**：現有 API 的 replace 語義天然支援增刪，無需額外 endpoint。

## Risks / Trade-offs

- **[手動 section 與 planner 不一致]** → 手動新增的 section 不含 planner 產出的 `scenario_key`、`detected_traits` 等 metadata。Mitigation: seed generation 僅依賴 `section_id`、`section_title`、`verification_items`，不強依賴 planner-only 欄位；前端新增時將 `scenario_key` 設為 `manual.{uuid}` 以免下游查詢出錯。
- **[誤刪恢復]** → 批次刪除後無 undo 機制。Mitigation: 使用 confirm dialog 作為防線；autosave 前使用者可重新載入恢復。一旦 autosave 已觸發，需要從 audit log 或重新 plan 恢復。
- **[section_id 重編與 seed traceability]** → 若已有 seed 指向舊 section_id，重編後 traceability 斷裂。Mitigation: section 增刪僅允許在 plan 為 `draft` 狀態時操作；locked 後禁止操作，此時 seed 尚未產出，無 traceability 風險。
