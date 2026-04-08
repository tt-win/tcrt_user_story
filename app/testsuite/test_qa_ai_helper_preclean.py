import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.qa_ai_helper_preclean_service import (
    parse_ticket_to_requirement_payload,
    validate_preclean_output,
)
from scripts.qa_ai_helper_preclean import build_output


def test_build_output_preserves_bracketed_section_headings():
    description = """
h1. Menu（功能路徑）
 * 流水反水

----
h1. User Story Narrative（使用者故事敘述）
 * *As a* 系統管理員
 * *I want* 調整 AG 與 WM 遊戲數據的抓取排程與查詢區間限制
 * *So that* 減少 F5 與 F7 FARM 共用 VNDK 線路時，因資料延遲或補抓造成的相互影響，確保數據寫入的穩定性。

----
h1. Criteria
 * *【需求背景】* 目前 AG 與 WM 的 VNDK 線路由 F5、F7 兩個 FARM 共用，需透過錯開排程與限制區間來優化效能。
 * *【AG 抓取規則】* 每次 API 查詢僅能獲取 10 分鐘以內的數據（報表統計類 API 除外）。
 * *【WM 抓取規則】*
 ** 若為遊戲紀錄報表數據，查詢需間隔 30 秒。
 ** 若未搜尋到數據，下次查詢需間隔 10 秒。
 * *【排程優化】* 調整 F5 與 F7 的 Job 啟動時間，使其輪流執行，避免同時競爭線路資源。

----
h1. Technical Specifications（技術規格）
 * 需實作基於 FARM 維度的排程錯位邏輯（例如參考 [TCG-98112|https://jira.tc-gaming.co/jira/browse/TCG-98112] 的錯開分鐘數設計）。
 * 針對 AG API 請求參數，需限制 `startTime` 與 `endTime` 的差距不得超過 10 分鐘。
 * 針對 WM 報表 API，需實作請求頻率限制（Rate Limiting）機制，記錄上次請求時間以符合 30s/10s 的間隔要求。

----
h1. Acceptance Criteria（驗收標準）
h3. Scenario 1: 資料抓取排程 F5 與 F7 輪流拉取
 * *Given* 玩家在 F5 與 F7 環境進行 AG、WM 遊戲產生注單
 * *When* 系統執行自動抓取 Job 時
 * *Then* F5 與 F7 的抓取時間點應有效錯開（不重疊發起請求）
 * *And* 數據應能正確寫入資料庫，無因線路競爭導致的遺漏

h3. Scenario 2: AG 數據抓取區間限制
 * *Given* 系統正在執行 AG 投注記錄抓取任務
 * *When* 調用非報表統計類 API 時
 * *Then* 請求的時間區間（Time Range）必須小於或等於 10 分鐘
 * *And* 系統應能穩定獲取該區間內的注單數據

h3. Scenario 3: WM 報表查詢頻率控制
 * *Given* 系統正在執行 WM 數據抓取
 * *When* 上一次查詢有回傳數據時
 * *Then* 下一次發起查詢的間隔必須大於 30 秒
 * *When* 若上一次查詢未搜尋到數據（Empty Result）時
 * *Then* 下一次發起查詢的間隔必須大於 10 秒

h3. Scenario 4: 異常處理 - 數據完整性
 * *Given* 共用線路負載較高
 * *When* 按照調整後的排程執行抓取
 * *Then* ELK Log 不應出現因頻繁請求導致的廠商端 429 (Too Many Requests) 或連線逾時錯誤
""".strip()

    output = build_output(description, comments=[])

    assert output["Menu"]["path"]["name"] == "流水反水"
    assert output["User Story Narrative"]["As a"] == "系統管理員"
    assert output["User Story Narrative"]["I want"].startswith("調整 AG 與 WM")
    assert output["User Story Narrative"]["So that"].startswith("減少 F5 與 F7 FARM")
    assert set(output["Criteria"].keys()) == {"需求背景", "AG 抓取規則", "WM 抓取規則", "排程優化"}
    assert len(output["Technical Specifications"]["技術規格"]["items"]) == 3
    assert (
        "TCG-98112|https://jira.tc-gaming.co/jira/browse/TCG-98112"
        in output["Technical Specifications"]["技術規格"]["items"][0]["name"]
    )
    assert len(output["Acceptance Criteria"]) == 4
    assert output["Acceptance Criteria"][0]["Scenario"]["name"] == "資料抓取排程 F5 與 F7 輪流拉取"
    assert output["Acceptance Criteria"][0]["Scenario"]["Given"] == ["玩家在 F5 與 F7 環境進行 AG、WM 遊戲產生注單"]


def test_validate_preclean_output_accepts_valid_ticket_and_warns_missing_technical_specs():
    parsed = {
        "User Story Narrative": {
            "As a": "系統管理員",
            "I want": "建立新版 helper",
            "So that": "需求能被正確拆解",
        },
        "Criteria": {
            "需求項目": {
                "items": [
                    {
                        "name": "畫面一需輸入 Ticket Number",
                    }
                ]
            }
        },
        "Acceptance Criteria": [
            {
                "Scenario": {
                    "name": "Scenario 1: 載入需求單",
                    "Given": ["使用者已開啟 QA AI Agent"],
                    "When": ["輸入 Ticket Number 並送出"],
                    "Then": ["系統建立新的 session"],
                }
            }
        ],
    }

    result = validate_preclean_output(parsed)

    assert result["is_valid"] is True
    assert result["stats"]["criteria_item_count"] == 1
    assert result["stats"]["acceptance_scenario_count"] == 1
    assert result["warnings"][0]["code"] == "missing_technical_specifications"


def test_validate_preclean_output_rejects_missing_story_fields_and_unnamed_scenario():
    parsed = {
        "User Story Narrative": {
            "As a": "",
            "I want": "建立新版 helper",
            "So that": "",
        },
        "Criteria": {"需求項目": {"items": [{"name": "至少有一筆 criteria"}]}},
        "Acceptance Criteria": [
            {
                "Scenario": {
                    "name": "Unnamed Scenario",
                    "Given": [],
                    "When": ["送出 Ticket Number"],
                    "Then": [],
                }
            }
        ],
    }

    result = validate_preclean_output(parsed)
    missing_field_codes = {item["code"] for item in result["missing_fields"]}
    scenario_error_codes = {item["code"] for item in result["scenario_errors"]}

    assert result["is_valid"] is False
    assert {"missing_user_story_as_a", "missing_user_story_so_that"} <= missing_field_codes
    assert {
        "unnamed_acceptance_scenario",
        "scenario_missing_given",
        "scenario_missing_then",
    } <= scenario_error_codes


def test_validate_preclean_output_rejects_missing_required_sections_and_invalid_acceptance_shape():
    parsed = {
        "Criteria": {},
        "Acceptance Criteria": {
            "Scenario": {
                "name": "Scenario 1: Invalid",
            }
        },
    }

    result = validate_preclean_output(parsed)
    missing_section_codes = {item["code"] for item in result["missing_sections"]}
    parser_error_codes = {item["code"] for item in result["parser_errors"]}
    missing_field_codes = {item["code"] for item in result["missing_fields"]}

    assert result["is_valid"] is False
    assert "missing_user_story_narrative" in missing_section_codes
    assert "acceptance_criteria_not_list" in parser_error_codes
    assert "criteria_has_no_items" in missing_field_codes


def test_parse_ticket_to_requirement_payload_surfaces_gate_errors():
    description = """
h1. User Story Narrative
 * *I want* 只填需求，不填角色與目的

----
h1. Criteria
 * *【需求項目】* 需要能建立 session

----
h1. Acceptance Criteria
 * *Given* 使用者已進入畫面一
 * *When* 送出 Ticket Number
 * *Then* 系統建立 session
""".strip()

    payload = parse_ticket_to_requirement_payload(description, comments=[])
    scenario_error_codes = {item["code"] for item in payload["validation_result"]["scenario_errors"]}
    missing_field_codes = {item["code"] for item in payload["validation_result"]["missing_fields"]}

    assert payload["validation_result"]["is_valid"] is False
    assert "missing_user_story_as_a" in missing_field_codes
    assert "missing_user_story_so_that" in missing_field_codes
    assert "unnamed_acceptance_scenario" in scenario_error_codes


def test_parse_ticket_to_requirement_payload_preserves_markdown_like_ticket_content():
    description = """
h1. User Story Narrative（使用者故事敘述）
 * *As a* QA
 * *I want* 檢視 ticket markdown
 * *So that* 我能確認畫面二唯讀內容

----
h1. Criteria
 * *【需求項目】* 顯示 markdown 內容

----
h1. Acceptance Criteria（驗收標準）
h3. Scenario 1: 顯示唯讀 markdown
 * *Given* 使用者已載入 Ticket
 * *When* 系統顯示畫面二
 * *Then* 應保留原始 h1 與 h3 區塊
""".strip()

    payload = parse_ticket_to_requirement_payload(description, comments=[])
    structured = payload["structured_requirement"]

    assert payload["validation_result"]["is_valid"] is True
    assert structured["User Story Narrative"]["As a"] == "QA"
    assert structured["Acceptance Criteria"][0]["Scenario"]["name"] == "顯示唯讀 markdown"
