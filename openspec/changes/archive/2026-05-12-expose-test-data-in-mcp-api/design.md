## Context

`test_data_json` 是 [`add-test-data-crud`](../../archive/2026-04-23-add-test-data-crud/) 在 `TestCaseLocal` 上新增的 JSON 欄位（[`app/models/database_models.py:438`](../../../app/models/database_models.py:438)），結構由 [`TestDataItem`](../../../app/models/test_case.py:59) 定義：

```python
class TestDataItem(BaseModel):
    id: Optional[str]              # UUID4，未提供則 server 補
    name: str                      # min_length=1, max=500
    category: TestDataCategory     # enum: text|number|credential|email|url|identifier|date|json|other
    value: str                     # 允許空字串，max=100K
```

每筆 test case 上限 100 個 test_data 項。CRUD 走 `/api/test-cases/{id}/test-data`（user JWT），TestRunItem 透過 `viewonly` relationship 即時從 TestCase 讀取（不做 snapshot）。

[`/api/mcp/*`](../../../app/api/mcp.py) 是給 machine principal 的唯讀面，目前只暴露 `attachments / test_results_files / user_story_map / parent_record / raw_fields` 在 detail 端點，**沒有 `test_data`**。

## Goals / Non-Goals

**Goals**
- detail 端點預設帶 `test_data`（與 `attachments` 等其他 extended JSON 欄位一致對待）。
- list / lookup 端點透過新 query param `include_test_data` 選擇性帶出（避免大量 case 場景下回應臃腫）。
- `category` 欄位必須完整回傳，不在 server 端做 redaction（消費端職責）。
- 既有呼叫者不感知新欄位 / 新 query param 也能正常運作。

**Non-Goals**
- 不在 `/api/mcp/*` 提供 mutate API（建立 / 修改 / 刪除）；維持唯讀。
- 不在上游做敏感欄位 redaction（`credential` 類別 value 仍以原文回傳）。
- 不修改 TestRunItem 的 test_data 即時讀取行為。
- 不在 `MCPCrossTeamTestCaseItem` 的外層 metadata 加 `test_data`（仍維持 `test_case` 子物件包覆）。

## Decisions

### 1. detail 端點：與 `include_extended` 綁在一起，預設帶
- **Rationale**：detail 端點本就硬編 `include_extended=True`（[`app/api/mcp.py:625`](../../../app/api/mcp.py:625)），其他 extended 欄位都會帶出來。test_data 在語意上屬於 test case 的核心執行資訊（測試帳號 / URL / payload），與 `attachments` 並列合理。
- **實作**：在 `_build_case_payload` 的 `include_extended` 分支補一行 `"test_data": _parse_json_list(row.test_data_json)`。
- **Pydantic**：`MCPTestCaseDetailItem` 加 `test_data: List[Dict[str, Any]] = Field(default_factory=list)`。
- **Alternatives considered**：
  - 額外在 detail 加 `include_test_data` query param → 拒絕。detail 已是「完整資料」端點，再切細顆粒度只增加複雜度，且使用者預期 detail = 全資料。

### 2. list / lookup 端點：新 query param `include_test_data`，預設 `false`
- **Rationale**：list / lookup 可能一次回傳上百筆 case，每筆 test_data 又可達 100 項 × 100K 字元，總量會爆炸。用獨立 flag 與 `include_content` 解耦，讓消費端決定要不要付這個 size。
- **實作**：route handler 加 `include_test_data: bool = Query(False)`，傳給 `_build_case_payload(..., include_test_data=...)`，內部加一個獨立分支（不依附 `include_extended`，因為 list / lookup 不開 `include_extended`）。
- **Filters echo**：response 的 `filters` 物件加入 `include_test_data` 鍵，便於消費端確認 server 接受了這個 param。
- **Alternatives considered**：
  - 跟 `include_content=true` 綁定（一起帶 test_data）→ 拒絕。`include_content` 已有「帶 precondition/steps/expected_result」的明確語意，混進 test_data 會讓 flag 語意模糊。
  - 永遠帶 → 拒絕。回應大小風險不可控。

### 3. `category` 完整回傳，不在 server 端 redact
- **Rationale**：MCP 接口的權限模型已是 machine token + team scope，能讀的就能讀；category 是分類 metadata，本身不敏感，敏感的是 value。redaction 屬於「下游消費場景決定」（例如 audit log 落地時），上游做就喪失彈性（例如 AI agent 在 secure context 想看到 credential value 用來自動填表）。
- **實作**：`_parse_json_list` 對 `test_data_json` 的解析自然會保留四個欄位；本 change 不做任何 redaction 邏輯。
- **下游契約**：`tcrt_mcp` 在 audit log 寫入時自行根據 `category == "credential"` 做 redaction（見 `tcrt_mcp/openspec/changes/align-mcp-with-latest-tcrt-data-model`）。

### 4. 預設行為向後相容
- 既有 detail 呼叫者：response 多一個 `test_data` 欄位（可能是 `[]`），dict 透傳的客戶端不受影響。
- 既有 list / lookup 呼叫者：不傳 `include_test_data` 等於 `false`，response 完全不變。
- 既有 `tcrt_mcp` 0.x 版本：可繼續運作，直到下游配套 change land 才會利用這個欄位。

## Risks

- **Detail 端點預設多帶資料**：如果某 test case 的 `test_data_json` 異常大（例如有人塞了 90 KB JSON payload 到 value），原本只取核心內容的 detail 呼叫會變慢。但 100K × 100 = 10 MB 是上限，實務應極少觸到；既有 `attachments_json` / `raw_fields_json` 已有相同潛在風險。
- **Pydantic 驗證寬鬆**：`test_data: List[Dict[str, Any]]` 不強型別，意味著 server 不再驗證每筆結構。`_parse_json_list` 的 fallback 已能應付異常 JSON（壞掉 → 回 `[]`），acceptable。
- **下游消費未跟進**：如果只 land 上游、下游 `tcrt_mcp` 還沒升級，AI agent 看到 `test_data` 但 spec doc 沒寫，行為仍正確（dict 透傳）。風險 = 低。
