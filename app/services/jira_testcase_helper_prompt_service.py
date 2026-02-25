"""JIRA Ticket -> Test Case Helper prompt service.

此模組負責：
- 讀取 helper model 設定
- 從 `prompts/jira_testcase_helper/*.md` 載入 prompt 模板
- 模板缺漏時退回內建機械契約模板（fail-safe）
- 以一致方式替換模板變數
"""

from __future__ import annotations

import logging
from pathlib import Path
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

logger = logging.getLogger(__name__)
DEFAULT_PROMPT_DIR = (
    Path(__file__).resolve().parents[2] / "prompts" / "jira_testcase_helper"
)
PROMPT_FILE_MAP: Dict[HelperPromptStage, str] = {
    "requirement_ir": "requirement_ir.md",
    "analysis": "analysis.md",
    "coverage": "coverage.md",
    "coverage_backfill": "coverage_backfill.md",
    "testcase": "testcase.md",
    "testcase_supplement": "testcase_supplement.md",
    "audit": "audit.md",
}

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
        "本階段是單一 prompt，必須直接完成可用於 pre-testcase 的 analysis+coverage。\n"
        "每個 analysis item 必須可直接被 testcase 生成使用，禁止空泛描述。\n"
        "禁止使用「參考 REF-xxx」當作唯一內容；必須展開成可驗證條目。\n"
        "若需求含表格欄位（reference columns），必須逐欄位拆解成明確檢核與預期，不得合併省略。\n"
        "coverage 的 seed 必須完整覆蓋 analysis item，且每個 seed.ref 僅對應一個 item.id。\n"
        "coverage 必須明確考慮四個面向：happy path、edge test cases、error handling、permission。\n"
        "seed.ax 僅可為 happy|edge|error|permission。\n"
        "seed.cat 必須遵守映射：happy->happy，edge->boundary，error/permission->negative。\n"
        "若某面向不適用，仍需輸出對應 seed，並設定 st=assume 且在 a 提供原因。\n"
        "seed 必須含 t/chk/exp/pre_hint/step_hint，供低推理模型產生詳細 testcase。\n\n"
        "TCG={ticket_key}\n"
        "REQUIREMENT_IR_JSON={requirement_ir_json}\n\n"
        "輸出限制：只輸出單一 JSON 物件，不可有任何其他文字。\n"
        "輸出 schema:\n"
        '{"analysis":{"sec":[{"g":"","it":[{"id":"010.001","t":"","det":[],"chk":[],"exp":[],"rid":[],"source_refs":[{"chunk_id":"","sentence_ids":[0],"quote":""}]}]}],"it":[{"id":"010.001","t":"","det":[],"chk":[],"exp":[],"rid":[],"source_refs":[{"chunk_id":"","sentence_ids":[0],"quote":""}]}]},"coverage":{"sec":[{"g":"","seed":[{"g":"","t":"","ax":"happy","cat":"happy","st":"ok","a":"","ref":["010.001"],"rid":[],"chk":[],"exp":[],"pre_hint":[],"step_hint":[],"source_refs":[{"chunk_id":"","sentence_ids":[0],"quote":""}]}]}],"seed":[{"g":"","t":"","ax":"happy","cat":"happy","st":"ok","a":"","ref":["010.001"],"rid":[],"chk":[],"exp":[],"pre_hint":[],"step_hint":[],"source_refs":[{"chunk_id":"","sentence_ids":[0],"quote":""}]}],"trace":{"analysis_item_count":0,"covered_item_count":0,"missing_ids":[],"missing_sections":[],"aspect_review":{"happy":"covered","edge":"covered","error":"covered","permission":"assume"}}}}'
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
        "pre 必須至少 2 條，且要包含測試資料與角色/權限或入口條件。\n"
        "s 必須至少 3 步，且每一步都要是可操作、可重現的動作與檢查。\n"
        "exp 必須且只能 1 條，且要有可觀測結果（畫面元素/回傳欄位/狀態碼/訊息）。\n"
        "禁止在 pre/s/exp 使用 REF/同上/略/TBD/N/A 這類占位詞。\n"
        "若資訊不足，使用完整中文敘述「待確認事項」，不可用縮寫占位詞。\n\n"
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
        "補全後 pre 必須至少 2 條，s 至少 3 步，exp 必須且只能 1 條且可觀測。\n"
        "禁止在 pre/s/exp 使用 REF/同上/略/TBD/N/A 這類占位詞。\n"
        "若資訊不足，使用完整中文敘述「待確認事項」，不可用縮寫占位詞。\n\n"
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
        "pre 必須至少 2 條，s 至少 3 步，exp 必須且只能 1 條且可觀測。\n"
        "禁止在 pre/s/exp 使用 REF/同上/略/TBD/N/A 這類占位詞。\n"
        "若資訊不足，使用完整中文敘述「待確認事項」，不可用縮寫占位詞。\n\n"
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

    def __init__(
        self,
        helper_config: Optional[JiraTestCaseHelperConfig] = None,
        prompt_dir: Optional[Path] = None,
    ):
        settings = get_settings()
        self._config = helper_config or settings.ai.jira_testcase_helper
        self._prompt_dir = Path(prompt_dir) if prompt_dir else DEFAULT_PROMPT_DIR

    def get_stage_model(self, stage: HelperModelStage) -> JiraTestCaseHelperStageModelConfig:
        if stage == "coverage":
            # analysis+coverage 已合併；coverage 沿用 analysis model。
            return self._config.models.analysis
        return getattr(self._config.models, stage)

    def get_stage_prompt_template(self, stage: HelperPromptStage) -> str:
        path = self._resolve_prompt_path(stage)
        try:
            template = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.warning(
                "讀取 helper prompt 檔失敗，改用 fallback template: stage=%s path=%s error=%s",
                stage,
                path,
                exc,
            )
            template = ""
        if template:
            return template
        fallback = MACHINE_PROMPT_TEMPLATES.get(stage, "")
        if fallback:
            logger.warning(
                "helper prompt 檔為空或不存在，改用 fallback template: stage=%s path=%s",
                stage,
                path,
            )
            return fallback
        raise ValueError(f"未知 helper prompt stage: {stage}")

    def _resolve_prompt_path(self, stage: HelperPromptStage) -> Path:
        filename = PROMPT_FILE_MAP.get(stage)
        if not filename:
            raise ValueError(f"未知 helper prompt stage: {stage}")
        return self._prompt_dir / filename

    @staticmethod
    def _render_template(
        template: str,
        replacements: Optional[Dict[str, str]] = None,
    ) -> str:
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

    def render_stage_prompt(
        self,
        stage: HelperPromptStage,
        replacements: Optional[Dict[str, str]] = None,
    ) -> str:
        template = self.get_stage_prompt_template(stage)
        return self._render_template(template, replacements)

    def render_machine_stage_prompt(
        self,
        stage: HelperPromptStage,
        replacements: Optional[Dict[str, str]] = None,
    ) -> str:
        template = self.get_stage_prompt_template(stage)
        if stage == "analysis" and not self._analysis_prompt_supports_merged_coverage(
            template
        ):
            # 舊版 config 只輸出 analysis，這裡強制切回合併契約，避免觸發二次 coverage 生成。
            template = MACHINE_PROMPT_TEMPLATES["analysis"]
        if stage in {"testcase", "testcase_supplement", "audit"} and not self._testcase_prompt_supports_quality_contract(
            template
        ):
            # 舊版 config 若未宣告完整 testcase 品質契約，強制切回 machine 契約模板。
            template = MACHINE_PROMPT_TEMPLATES[stage]
        return self._render_template(template, replacements)

    @staticmethod
    def _analysis_prompt_supports_merged_coverage(template: str) -> bool:
        text = str(template or "")
        merged_markers = (
            '"coverage"',
            "一次輸出 analysis 與 coverage",
            "analysis 與 coverage",
            "Analysis+Coverage",
        )
        aspect_markers = (
            "happy path",
            "edge test cases",
            "error handling",
            "permission",
            "happy、edge、error、permission",
            "四個面向",
            "seed.ax",
        )
        return any(marker in text for marker in merged_markers) and any(
            marker in text for marker in aspect_markers
        )

    @staticmethod
    def _testcase_prompt_supports_quality_contract(template: str) -> bool:
        text = str(template or "")
        return all(
            any(marker in text for marker in group)
            for group in (
                ("pre 至少 2 條", "pre 必須至少 2 條"),
                ("s 至少 3 步", "s 必須至少 3 步"),
                ("exp 必須且只能",),
                ("REF/同上/略/TBD/N/A",),
            )
        )

    def get_contract_versions(self) -> Dict[str, str]:
        return {
            "prompt_contract_version": str(
                getattr(self._config, "prompt_contract_version", "helper-prompt.v2")
            ),
            "payload_contract_version": str(
                getattr(self._config, "payload_contract_version", "helper-draft.v2")
            ),
        }


_jira_testcase_helper_prompt_service: Optional[JiraTestCaseHelperPromptService] = None


def get_jira_testcase_helper_prompt_service() -> JiraTestCaseHelperPromptService:
    global _jira_testcase_helper_prompt_service
    if _jira_testcase_helper_prompt_service is None:
        _jira_testcase_helper_prompt_service = JiraTestCaseHelperPromptService()
    return _jira_testcase_helper_prompt_service
