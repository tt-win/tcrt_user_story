## Context

QA AI Helper 目前的六畫面狀態機為：TICKET_CONFIRMATION → VERIFICATION_PLANNING → SEED_REVIEW → TESTCASE_REVIEW → SET_SELECTION → COMMIT_RESULT。VERIFICATION_PLANNING 畫面的驗證項目（PlanSection / VerificationItem / CheckCondition）完全依賴使用者手動填寫或確定性規劃引擎（`qa_ai_helper_planner.py`）產出。

PoC（`scripts/ac_inspection_poc.py`）已驗證「多低階模型角色分工並行 extraction + 高階模型統合」的架構，在 2 個 AC Scenarios 的案例中，Phase 1 約 3-4 秒並行完成，Phase 2 約 187 秒完成。整體流程可能超過 60 秒，現有系統全部為同步 REST，無 SSE 基礎設施。

現有技術棧：FastAPI + aiohttp + aiosqlite，前端為 Jinja2 模板 + 原生 JS/CSS，LLM 呼叫透過 OpenRouter API，prompt 為 `.md` 模板 + `{placeholder}` 字串替換。

## Goals / Non-Goals

**Goals:**
- 將 PoC 的多模型 inspection 流程嵌入現有 QA AI Helper session 狀態機
- 新增 SSE endpoint 即時推送 inspection 進度（三個模型各自完成狀態 + 階段轉換）
- 擴展現有 `QAAIHelperModelsConfig` 以支援 inspection 階段的模型配置
- 在 TICKET_CONFIRMATION 確認後提供 AI inspection 觸發選項
- 前端加入 MAGI 過場動畫與 AI 思考動畫
- Consolidation 輸出為結構化 JSON，可直接填充進 PlanSection / VerificationItem / CheckCondition

**Non-Goals:**
- 不改變現有 seed / testcase 產生的 LLM 流程
- 不引入新的前端 framework（維持原生 JS/CSS）
- 不增加新的 DB table（inspection 結果寫入現有 requirement plan 資料結構）
- 不修改現有 prompt 模板（seed.md / testcase.md 等）
- 不實作 inspection 結果的版本控制或歷史比較

## Decisions

### D1: 嵌入現有狀態機而非獨立模組

**選擇**：擴展 `_SESSION_SCREEN_TRANSITIONS`，在 `ticket_confirmation → verification_planning` 之間新增 `magi_inspection` 過渡狀態。

**替代方案**：建立獨立的 `magi_inspection_service.py` + 獨立 router。

**理由**：
- 與現有 session 管理一致，共用 `_set_session_screen`、workspace 載入、錯誤處理
- inspection 結果直接寫入同一 session 的 requirement plan，無需跨模組協調
- 使用者體驗為連續流程，不需額外的 session 管理

**變更**：
```python
_SESSION_SCREEN_TRANSITIONS = {
    ...
    "ticket_confirmation": {
        "magi_inspection",       # 新增
        "verification_planning",
        "failed",
    },
    "magi_inspection": {         # 新增
        "verification_planning",
        "failed",
    },
    ...
}
```

### D2: SSE 即時串流 inspection 進度

**選擇**：新增 SSE endpoint 串流 inspection 進度事件。

**替代方案**：
- Polling（前端定期 GET 查詢）：MAGI 動畫需要即時更新每個模型狀態，polling 間隔過長會讓動畫失真，過短會增加不必要的 API 呼叫。
- 同步等待：超過 60 秒的 HTTP response 極易 timeout，且無法提供中間進度。

**理由**：
- MAGI 動畫的核心價值在於即時呈現每個模型完成狀態，SSE 是最自然的推送機制
- FastAPI 原生支援 `StreamingResponse`，不需額外依賴
- 事件粒度：每個 extraction 呼叫完成 / 失敗、Phase 切換、consolidation 完成 / 失敗

**API endpoint**：
```
POST /teams/{team_id}/qa-ai-helper/sessions/{session_id}/magi-inspection
→ 回傳 StreamingResponse (text/event-stream)
```

**SSE 事件格式**：
```
event: extraction_complete
data: {"model_label": "A", "scenario_index": 0, "scenario_name": "...", "status": "success"}

event: extraction_error
data: {"model_label": "B", "scenario_index": 1, "scenario_name": "...", "error": "timeout"}

event: phase_change
data: {"phase": "consolidation"}

event: consolidation_complete
data: {"status": "success", "sections_count": 2, "items_count": 12}

event: consolidation_error
data: {"error": "..."}

event: done
data: {"success": true}
```

### D3: 擴展現有 config 結構

**選擇**：在 `QAAIHelperModelsConfig` 新增 inspection 相關欄位。

**替代方案**：在 `config.yaml` 建立獨立 `magi_inspection:` section。

**理由**：
- 沿用現有 `QAAIHelperStageModelConfig` 結構（model + temperature）
- 沿用現有 `from_env` 環境變數覆蓋機制（`QA_AI_HELPER_MODEL_INSPECTION_EXTRACTION_A` 等）
- inspection 是 QA AI Helper 流程的一部分，設定集中管理較合理

**新增欄位**：
```python
class QAAIHelperModelsConfig(BaseModel):
    # ... 現有欄位 ...
    inspection_extraction_a: QAAIHelperStageModelConfig = QAAIHelperStageModelConfig(
        model="openai/gpt-5.4-mini", temperature=0.1,
    )
    inspection_extraction_b: QAAIHelperStageModelConfig = QAAIHelperStageModelConfig(
        model="google/gemini-3-flash-preview", temperature=0.1,
    )
    inspection_extraction_c: QAAIHelperStageModelConfig = QAAIHelperStageModelConfig(
        model="x-ai/grok-4.20", temperature=0.1,
    )
    inspection_consolidation: QAAIHelperStageModelConfig = QAAIHelperStageModelConfig(
        model="openai/gpt-5.3-chat", temperature=0.1,
    )
```

### D4: 混合輸出格式（extraction 壓縮文字 + consolidation JSON）

**選擇**：Extraction 使用 pipe-delimited 壓縮文字，Consolidation 使用 `response_format: {"type": "json_object"}` 產出結構化 JSON。

**替代方案**：
- 全程 JSON：低階模型可能在結構化輸出限制下表現受限，且壓縮格式更省 token。
- 全程 Markdown：需要額外 parser，且 consolidation 結果需要精確填充到資料結構。

**理由**：
- PoC 已驗證低階模型以 pipe-delimited 格式輸出的品質良好
- Consolidation 需要精準映射到 PlanSection / VerificationItem / CheckCondition，JSON 格式可避免 parse 失敗
- 中間層壓縮格式降低 Phase 2 consolidation prompt 的 token 消耗

**Extraction 輸出格式**（每行一筆）：
```
title|coverage_tag|condition_text
```

**Consolidation JSON 輸出 schema**：
```json
{
  "sections": [
    {
      "scenario_name": "string",
      "given": ["string"],
      "when": ["string"],
      "then": ["string"],
      "items": [
        {
          "category": "API|UI|功能驗證|其他",
          "summary": "string",
          "detail": "string",
          "conditions": [
            {
              "condition_text": "string",
              "coverage_tag": "Happy Path|Error Handling|Edge Test Case|Permission"
            }
          ]
        }
      ]
    }
  ]
}
```

### D5: Extraction 角色設定配置化

**選擇**：角色設定（label、role_name、role_focus）直接放入 `config.yaml`，定義為 `InspectionRoleConfig` pydantic model，初版提供合理預設值。

**理由**：
- 角色焦點描述是 prompt 注入內容，允許使用者自訂角色方向而不改程式碼
- 與模型 ID 分離——模型可換但角色職責不變，反之亦然
- PoC 的 `ExtractionModelConfig` 同時包含了 model_id 與 role_focus，正式版拆開更清晰

**結構**：
```python
class InspectionRoleConfig(BaseModel):
    label: str          # "A" / "B" / "C"
    role_name: str      # 短名稱（用於 log 與前端顯示）
    role_focus: str     # 注入 prompt 的角色描述
```

**config.yaml 對應**：
```yaml
ai:
  qa_ai_helper:
    inspection:
      max_scenarios_warning: 5   # 超過此值時提醒使用者
      roles:
        - label: "A"
          role_name: "Happy Path + Permission"
          role_focus: "你專注於 Happy Path（正常流程驗證）與基本 Permission（權限控制）..."
        - label: "B"
          role_name: "Edge Cases + Performance"
          role_focus: "你專注於 Edge Cases（邊界與異常輸入）與 Performance/Concurrency..."
        - label: "C"
          role_name: "Error Handling + Abuse"
          role_focus: "你專注於 Error Handling（錯誤處理）、進階 Permission 與 Abuse..."
```

### D6: Prompt 模板沿用現有機制

**選擇**：新增兩個 prompt stage（`inspection_extraction`、`inspection_consolidation`），擴展 `QAAIHelperPromptStage` 與 `PROMPT_FILE_MAP`。

**理由**：
- 沿用現有的 `render_stage_prompt()` + `{placeholder}` 替換機制
- 與 PoC 的 prompt 模板一致（`{role_focus}`、`{scenario_gherkin}`、`{extraction_results}`）

**新增**：
```python
QAAIHelperPromptStage = Literal[
    "seed", "seed_refine", "testcase", "repair",
    "inspection_extraction", "inspection_consolidation",  # 新增
]

PROMPT_FILE_MAP = {
    ...
    "inspection_extraction": "inspection_extraction.md",
    "inspection_consolidation": "inspection_consolidation.md",
}
```

### D7: LLM 呼叫層擴展

**選擇**：擴展現有 `QAAIHelperLLMStage` 並新增 inspection 專用呼叫方法。

**理由**：
- 現有 `call_stage` 為同步呼叫單一模型的封裝，inspection 需要「指定模型 + 指定 role」的呼叫
- 新增 `call_inspection_extraction(role_label, prompt)` 方法，根據 role_label 選擇對應模型設定
- 新增 `call_inspection_consolidation(prompt)` 方法，使用 `response_format: {"type": "json_object"}`
- 並行呼叫由 service 層以 `asyncio.gather` 編排，沿用現有 `max_concurrent_llm_calls` semaphore

### D8: 結果填充流程

**選擇**：Consolidation JSON 解析後，呼叫現有的 `_replace_requirement_plan_sections_sync` 填充進 requirement plan。

**理由**：
- 現有函式已支援從 `List[Dict[str, Any]]` 建立完整的 PlanSection / VerificationItem / CheckCondition 三層結構
- 只需將 consolidation JSON 轉換為該函式期望的格式即可
- 使用者後續修改沿用現有的 autosave / lock / unlock 機制

**轉換流程**：
```
Consolidation JSON → _transform_inspection_to_sections_payload() → _replace_requirement_plan_sections_sync()
```

## Risks / Trade-offs

**[Phase 2 延遲]** → Consolidation 模型的回應時間可能長達數分鐘（PoC 中 187 秒）。
- **Mitigation**：不設預設 timeout，SSE 持續推送進度事件，前端顯示 MAGI Phase 2 動畫讓使用者知道系統仍在工作。若後續實測發現耗時不可接受，再考慮更換更快的 consolidation model 或分段統合。

**[低階模型服務不穩定]** → 三個不同供應商的低階模型可能各自出現可用性問題。
- **Mitigation**：Phase 1 partial failure 容許（只要至少一個模型成功），Phase 2 consolidation 標註缺少的角色面向。SSE 事件即時通知個別模型失敗。

**[Consolidation JSON 格式不合規]** → 高階模型可能偶爾產出不符合預期 schema 的 JSON。
- **Mitigation**：對 consolidation output 做嚴格 schema 驗證，驗證失敗時嘗試一次 repair call（沿用現有 repair stage pattern）。若仍失敗則 fallback 到手動填寫。

**[SSE 連線管理]** → 長時間 SSE 連線可能被 proxy / load balancer 切斷。
- **Mitigation**：前端實作自動重連機制；每個 SSE 事件包含完整的累積狀態，重連後可從最新事件恢復。

**[Token 消耗]** → 3N 次 extraction + 1 次 consolidation 的 token 成本。
- **Mitigation**：extraction 使用低價模型；中間層壓縮格式降低 consolidation 輸入 token；超過 5 個 AC Scenarios 時提醒使用者可能耗時較長（`max_scenarios_warning: 5`，config 可調）。

**[前端複雜度]** → MAGI 動畫新增大量前端程式碼到已有 3397 行的 main.js。
- **Mitigation**：MAGI 動畫邏輯與 AI 思考動畫各自封裝為獨立模組（`magi-animation.js`、`ai-thinking-animation.js`），透過事件機制與主流程解耦。

## Resolved Questions

1. **Consolidation timeout 閾值** → **不設預設 timeout**。PoC 的 187 秒在 SSE 持續推送進度的情況下可接受。若後續實際使用中發現耗時過長，再採用其他方式優化（如更換更快的 consolidation model 或分段統合）。
2. **Extraction 角色焦點配置化** → **直接支援從 config.yaml 自訂**。`role_focus` 文字放入 config.yaml，允許使用者調整角色焦點方向而不改程式碼。初版提供合理預設值。
3. **MAGI 動畫視覺設計** → **簡化版先上**。初版實作簡化的三面板佈局 + 狀態指示燈，不追求高度還原 MAGI 視覺。後續迭代再強化動畫效果與視覺細節。
4. **max_scenarios_for_inspection** → **5 個 scenarios**。超過 5 個 AC Scenarios 時提醒使用者 inspection 可能耗時較長（15 次 extraction 呼叫 + consolidation 輸入量顯著增加）。此閾值在 config 中可調整。
