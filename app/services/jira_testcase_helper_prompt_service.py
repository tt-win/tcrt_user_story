"""JIRA Ticket -> Test Case Helper prompt service.

此模組負責：
- 從 `config.yaml`（app.config settings）讀取四階段 prompt 與 model 設定
- 以一致方式替換模板變數
- 提供後續 helper workflow 直接可用的存取介面
"""

from __future__ import annotations

from typing import Dict, Literal, Optional

from app.config import (
    JiraTestCaseHelperConfig,
    JiraTestCaseHelperStageModelConfig,
    get_settings,
)

HelperModelStage = Literal["analysis", "coverage", "testcase", "audit"]
HelperPromptStage = Literal[
    "requirement_ir",
    "analysis",
    "coverage",
    "coverage_backfill",
    "testcase",
    "testcase_supplement",
    "audit",
]

MACHINE_PROMPT_TEMPLATES: Dict[HelperPromptStage, str] = {
    "requirement_ir": (
        "你是 Requirement IR 產生器。使用 {review_language}。\n"
        "你只能抽取、分類、關聯需求，不可做 Markdown/表格/字體等格式化。\n"
        "不可新增來源不存在的需求；若不確定，放到 ambiguities/open_questions。\n"
        "每個需求性欄位都必須有 source_refs。\n"
        "coverage_map 必須覆蓋每一個句子（covered 或 ignored）。\n\n"
        "TCG={ticket_key}\n"
        "SUMMARY={ticket_summary}\n"
        "COMPONENTS={ticket_components}\n"
        "SOURCE_PACKETS_JSON={source_packets_json}\n\n"
        "輸出限制：只輸出單一 JSON 物件，不可輸出任何說明文字/Markdown/code fence。\n"
        "輸出 schema（必填鍵）：\n"
        '{"ir_version":"1.0","ticket_meta":{"ticket_id":"","summary":"","components":[],"labels":[],"platforms":[]},"chunks_index":[{"chunk_id":"","title":"","sentence_count":1}],"actors":[{"actor_id":"ACTOR-001","name":"","type":"user","permissions":[],"source_refs":[{"chunk_id":"","sentence_ids":[0],"quote":""}]}],"entities":[{"entity_id":"ENT-001","name":"","fields":[{"field_id":"FIELD-001","name":"","data_type":"string","constraints":[],"source_refs":[{"chunk_id":"","sentence_ids":[0],"quote":""}]}],"source_refs":[{"chunk_id":"","sentence_ids":[0],"quote":""}]}],"flows":[{"flow_id":"FLOW-001","name":"","actor_ids":["ACTOR-001"],"preconditions":[],"steps":[{"step_id":"STEP-001","action":"","expected_outcome":"","variants":[],"source_refs":[{"chunk_id":"","sentence_ids":[0],"quote":""}]}],"postconditions":[],"source_refs":[{"chunk_id":"","sentence_ids":[0],"quote":""}]}],"rules":[{"rule_id":"RULE-001","type":"other","statement":"","scope":"cross","related_entity_ids":[],"related_flow_ids":[],"acceptance_criteria_hint":"","source_refs":[{"chunk_id":"","sentence_ids":[0],"quote":""}]}],"non_functional":[],"out_of_scope":[],"open_questions":[],"ambiguities":[],"coverage_map":[{"chunk_id":"","sentence_id":0,"status":"covered","covered_by":["FLOW-001"]}],"ticket":{"key":"","summary":"","components":[]},"scenarios":[{"rid":"REQ-001","g":"","t":"","ac":[],"rules":[],"data_points":[],"expected":[],"source_refs":[{"chunk_id":"","sentence_ids":[0],"quote":""}]}],"reference_columns":[],"notes":[],"trace_index":[]}'
    ),
    "analysis": (
        "你是 Analysis+Coverage 合併轉換器。使用 {review_language}。\n"
        "一次輸出 analysis 與 coverage，禁止任何格式化輸出。\n"
        "每個 analysis item 必須可直接被 testcase 生成使用，禁止空泛描述。\n"
        "禁止使用「參考 REF-xxx」當作唯一內容；必須展開成可驗證條目。\n"
        "若需求含表格欄位（reference columns），必須逐欄位拆解成明確檢核與預期，不得合併省略。\n"
        "coverage 的 seed 必須完整覆蓋 analysis item，且每個 seed.ref 僅對應一個 item.id。\n"
        "seed 必須含 t/chk/exp/pre_hint/step_hint，供低推理模型產生詳細 testcase。\n\n"
        "TCG={ticket_key}\n"
        "REQUIREMENT_IR_JSON={requirement_ir_json}\n\n"
        "輸出限制：只輸出單一 JSON 物件，不可有任何其他文字。\n"
        "輸出 schema:\n"
        '{"analysis":{"sec":[{"g":"","it":[{"id":"010.001","t":"","det":[],"chk":[],"exp":[],"rid":[],"source_refs":[{"chunk_id":"","sentence_ids":[0],"quote":""}]}]}],"it":[{"id":"010.001","t":"","det":[],"chk":[],"exp":[],"rid":[],"source_refs":[{"chunk_id":"","sentence_ids":[0],"quote":""}]}]},"coverage":{"sec":[{"g":"","seed":[{"g":"","t":"","cat":"happy","st":"ok","ref":["010.001"],"rid":[],"chk":[],"exp":[],"pre_hint":[],"step_hint":[],"source_refs":[{"chunk_id":"","sentence_ids":[0],"quote":""}]}]}],"seed":[{"g":"","t":"","cat":"happy","st":"ok","ref":["010.001"],"rid":[],"chk":[],"exp":[],"pre_hint":[],"step_hint":[],"source_refs":[{"chunk_id":"","sentence_ids":[0],"quote":""}]}]}}'
    ),
    "coverage": (
        "你是 Coverage 轉換器。使用 {review_language}。\n"
        "只產生 machine-readable seed，不做格式化。\n"
        "cat 僅可為 happy|negative|boundary。\n"
        "每個 seed.ref 必須且只能一個 analysis id（不可多個）。\n"
        "若條目有錯誤/拒絕/無效/權限/逾時語義，cat=negative。\n"
        "僅當條目明確是邊界語義（上限/下限/極值/分頁跨頁/捲動/極窄寬度）時，cat=boundary。\n"
        "一般功能流程（含一般排序/一般欄位檢核）預設為 happy。\n"
        "每個 seed 必須提供 t/chk/exp/pre_hint/step_hint，且可直接生成詳細 testcase。\n\n"
        "REQUIREMENT_IR_JSON={requirement_ir_json}\n"
        "ANALYSIS_JSON={expanded_requirements_json}\n\n"
        "輸出限制：只輸出單一 JSON 物件，不可有任何其他文字。\n"
        "輸出 schema:\n"
        '{"sec":[{"g":"","seed":[{"g":"","t":"","cat":"happy","st":"ok","ref":["010.001"],"rid":[],"chk":[],"exp":[],"pre_hint":[],"step_hint":[],"source_refs":[{"chunk_id":"","sentence_ids":[0],"quote":""}]}]}],"seed":[{"g":"","t":"","cat":"happy","st":"ok","ref":["010.001"],"rid":[],"chk":[],"exp":[],"pre_hint":[],"step_hint":[],"source_refs":[{"chunk_id":"","sentence_ids":[0],"quote":""}]}],"trace":{"analysis_item_count":0,"covered_item_count":0,"missing_ids":[],"missing_sections":[]}}'
    ),
    "coverage_backfill": (
        "你是覆蓋補全器（Coverage 缺漏補全器）。使用 {review_language}。\n"
        "只補 missing ids/sections 對應 seed；不要重寫既有 seed。\n"
        "cat 僅可為 happy|negative|boundary。\n"
        "依條目語義決定 cat：錯誤/無效/拒絕 => negative；僅明確邊界語義（上限下限/極值/分頁跨頁/固定欄位/捲動/極窄寬度）=> boundary。\n"
        "若僅為一般排序或一般欄位檢核，cat 應為 happy。\n"
        "僅輸出 JSON 物件。\n\n"
        "REQUIREMENT_IR_JSON={requirement_ir_json}\n"
        "ANALYSIS_JSON={expanded_requirements_json}\n"
        "CURRENT_COVERAGE_JSON={current_coverage_json}\n"
        "MISSING_IDS_JSON={missing_ids_json}\n"
        "MISSING_SECTIONS_JSON={missing_sections_json}\n\n"
        "輸出限制：只輸出單一 JSON 物件，不可有任何其他文字。\n"
        "輸出 schema:\n"
        '{"seed":[{"g":"","t":"","cat":"happy","st":"ok","ref":["010.001"],"rid":[],"chk":[],"exp":[],"pre_hint":[],"step_hint":[],"source_refs":[{"chunk_id":"","sentence_ids":[0],"quote":""}]}],"trace":{"resolved_ids":[],"resolved_sections":[]}}'
    ),
    "testcase": (
        "你是 Testcase 轉換器。使用 {output_language}。\n"
        "不要做任何格式排版，僅產生可執行 testcase JSON。\n"
        "每個 en 條目對應 1 個 testcase，禁止遺漏。\n"
        "必須依 en.cat 產生情境：happy=正向，negative=負向/錯誤處理，boundary=邊界條件。\n"
        "pre 與 s 必須具體且可執行，expected 必須可觀測。\n"
        "禁止出現 REF/同上/略/TBD/N/A。\n\n"
        "TCG={ticket_key}\n"
        "SECTION={section_no} {section_name}\n"
        "STAGE1_JSON={coverage_questions_json}\n"
        "RETRIEVED_CONTEXT={similar_cases}\n"
        "RETRY_HINT={retry_hint}\n\n"
        "輸出限制：只輸出單一 JSON 物件，不可有任何其他文字。\n"
        "輸出 schema:\n"
        '{"tc":[{"id":"","t":"","pre":[""],"s":["","",""],"exp":[""],"priority":"Medium"}]}'
    ),
    "testcase_supplement": (
        "你是 Testcase 補全器。使用 {output_language}。\n"
        "只補缺漏或不合格 testcase。\n"
        "必須遵守 en.cat 對應的情境類型（happy/negative/boundary）。\n"
        "補全後 pre/s/exp 必須完整可執行、可觀測。\n"
        "禁止出現 REF/同上/略/TBD/N/A。\n\n"
        "TCG={ticket_key}\n"
        "SECTION={section_no} {section_name}\n"
        "MISSING_STAGE1_JSON={coverage_questions_json}\n"
        "CURRENT_TESTCASE_JSON={testcase_json}\n"
        "RETRIEVED_CONTEXT={similar_cases}\n"
        "RETRY_HINT={retry_hint}\n\n"
        "輸出限制：只輸出單一 JSON 物件，不可有任何其他文字。\n"
        "輸出 schema:\n"
        '{"tc":[{"id":"","t":"","pre":[""],"s":["","",""],"exp":[""],"priority":"Medium"}]}'
    ),
    "audit": (
        "你是 Testcase 稽核器。使用 {output_language}。\n"
        "只補強語意完整性與覆蓋性，不做格式排版。\n"
        "保留 testcase id，不可變更目標集合。\n"
        "必須檢查每個 testcase 是否符合 en.cat 的情境類型（happy/negative/boundary）。\n"
        "若有缺陷，直接在同筆 testcase 補全，不可輸出省略語句。\n"
        "禁止出現 REF/同上/略/TBD/N/A。\n\n"
        "TCG={ticket_key}\n"
        "SECTION={section_no} {section_name}\n"
        "STAGE1_JSON={coverage_questions_json}\n"
        "TESTCASE_JSON={testcase_json}\n"
        "RETRIEVED_CONTEXT={similar_cases}\n"
        "RETRY_HINT={retry_hint}\n\n"
        "輸出限制：只輸出單一 JSON 物件，不可有任何其他文字。\n"
        "輸出 schema:\n"
        '{"tc":[{"id":"","t":"","pre":[""],"s":["","",""],"exp":[""],"priority":"Medium"}]}'
    ),
}


class JiraTestCaseHelperPromptService:
    """提供 helper 各階段 prompt/model 設定與模板渲染。"""

    def __init__(self, helper_config: Optional[JiraTestCaseHelperConfig] = None):
        settings = get_settings()
        self._config = helper_config or settings.ai.jira_testcase_helper

    def get_stage_model(self, stage: HelperModelStage) -> JiraTestCaseHelperStageModelConfig:
        return getattr(self._config.models, stage)

    def get_stage_prompt_template(self, stage: HelperPromptStage) -> str:
        return getattr(self._config.prompts, stage)

    def render_stage_prompt(
        self,
        stage: HelperPromptStage,
        replacements: Optional[Dict[str, str]] = None,
    ) -> str:
        template = self.get_stage_prompt_template(stage)

        defaults = {
            "review_language": "繁體中文",
            "output_language": "繁體中文",
            "ticket_key": "",
            "ticket_summary": "",
            "ticket_description": "",
            "ticket_components": "",
            "similar_cases": "",
            "requirement_ir_json": "{}",
            "expanded_requirements_json": "{}",
            "current_coverage_json": "{}",
            "missing_ids_json": "[]",
            "missing_sections_json": "[]",
            "coverage_questions_json": "{}",
            "testcase_json": "{}",
            "section_name": "",
            "section_no": "",
            "retry_hint": "",
            "source_packets_json": "{}",
        }
        if replacements:
            for key, value in replacements.items():
                defaults[key] = "" if value is None else str(value)

        rendered = template
        for key, value in defaults.items():
            rendered = rendered.replace("{" + key + "}", value)

        return rendered

    def render_machine_stage_prompt(
        self,
        stage: HelperPromptStage,
        replacements: Optional[Dict[str, str]] = None,
    ) -> str:
        template = MACHINE_PROMPT_TEMPLATES.get(stage) or self.get_stage_prompt_template(stage)
        defaults = {
            "review_language": "繁體中文",
            "output_language": "繁體中文",
            "ticket_key": "",
            "ticket_summary": "",
            "ticket_description": "",
            "ticket_components": "",
            "similar_cases": "",
            "requirement_ir_json": "{}",
            "expanded_requirements_json": "{}",
            "current_coverage_json": "{}",
            "missing_ids_json": "[]",
            "missing_sections_json": "[]",
            "coverage_questions_json": "{}",
            "testcase_json": "{}",
            "section_name": "",
            "section_no": "",
            "retry_hint": "",
            "source_packets_json": "{}",
        }
        if replacements:
            for key, value in replacements.items():
                defaults[key] = "" if value is None else str(value)

        rendered = template
        for key, value in defaults.items():
            rendered = rendered.replace("{" + key + "}", value)
        return rendered


_jira_testcase_helper_prompt_service: Optional[JiraTestCaseHelperPromptService] = None


def get_jira_testcase_helper_prompt_service() -> JiraTestCaseHelperPromptService:
    global _jira_testcase_helper_prompt_service
    if _jira_testcase_helper_prompt_service is None:
        _jira_testcase_helper_prompt_service = JiraTestCaseHelperPromptService()
    return _jira_testcase_helper_prompt_service
