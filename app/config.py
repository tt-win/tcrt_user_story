import yaml
import os
from typing import Optional, Dict, Any, List
from pydantic import BaseModel
from dotenv import load_dotenv

# 載入 .env 檔案（如果存在）
load_dotenv()

JIRA_HELPER_REQUIREMENT_IR_PROMPT_TEMPLATE = """你是需求結構化引擎。請使用 {review_language}，把 Jira ticket 轉成 machine-readable requirement IR。

TCG: {ticket_key}
Summary: {ticket_summary}
Description:
{ticket_description}
Components: {ticket_components}

你必須只輸出「單一 JSON 物件」，不可有 Markdown/code fence/說明文字。
不可杜撰需求，只能抽取、重組、標準化。若資訊不足可留空字串或空陣列，不可腦補。
必須完整保留 ticket 的需求訊息（包含 AC、規則、例外、表格欄位語義、多語內容）。
若原文有表格/欄位定義，必須逐欄展開到 reference_columns，不可用範圍字串取代。
若輸出長度接近上限，優先精簡句子長度，不可刪除條目；不可輸出截斷 JSON。

Schema:
{
  "ticket":{"key":"TCG-123","summary":"...","components":["Auth"]},
  "scenarios":[
    {"rid":"REQ-001","g":"功能群組","t":"需求標題","ac":["可驗證條件"],"rules":["業務規則"],"data_points":["欄位/條件"],"expected":["預期"],"trace":{"source":"description","snippet":"..."}}
  ],
  "reference_columns":[
    {"rid":"REF-001","column":"欄位名稱","new_column":false,"sortable":true,"fixed_lr":"left","format_rules":["規則"],"cross_page_param":"param","edit_note":"註記","expected":["此欄位可觀察結果"],"trace":{"source":"reference_table","row":"1"}}
  ],
  "notes":["補充說明"]
}"""

JIRA_HELPER_ANALYSIS_PROMPT_TEMPLATE = """你是 Analysis+Coverage 合併轉換器。請使用 {review_language}，根據 requirement IR 一次輸出 analysis 與 coverage。

TCG: {ticket_key}
Requirement IR JSON:
{requirement_ir_json}

只輸出單一 JSON 物件，不可有 Markdown/code fence/說明文字。
規則：
- 本階段是單一 prompt，必須直接完成可用於 pre-testcase 的 analysis+coverage。
- analysis:
  - 先按功能分 section（g），每個 section 內提供 it。
  - 每個 item 都是「可執行的驗證條目」，不可只寫 REF 代號或模糊描述。
  - item.id 必須為可追蹤格式（例如 010.001），供 coverage 的 ref 使用。
  - 若同一驗證條目同時驗 4 個欄位（如名字/生日/電話/地址排序），可放同一 item，但 item.chk 必須明列 4 個欄位與驗證動作；item.exp 必須明列對應預期。
  - item.t 需具體可操作；item.det 只放邊界/限制補充。
  - 每個 item 必須帶 rid；rid 中 REF 禁止區間寫法（例如 REF-001~REF-018）。
  - 若 requirement_ir.reference_columns 有 N 個欄位，analysis 需至少覆蓋 N 個欄位語義（可一對一或在同條 item 逐欄列明）。
- coverage:
  - 每個 seed 對應 1 個未來 test case（1 seed = 1 expected result）。
  - 每個 seed.ref 必須且只能有 1 個 analysis item.id。
  - coverage 必須明確考慮四個面向：happy path、edge test cases、error handling、permission。
  - seed.ax 僅允許：happy、edge、error、permission。
  - seed.cat 必須遵守映射：happy->happy，edge->boundary，error/permission->negative。
  - 若某面向不適用，仍需輸出對應 seed，並設定 st=assume 且在 a 提供原因。
  - 每個 seed 必須提供 t、chk、exp、pre_hint、step_hint，且可直接給低推理模型生成 testcase。
  - 輸出 sec（分組）與 seed（展平）兩種視圖。
  - 完整性契約：
    1) Analysis 每個 item.id 至少出現在一個 seed.ref
    2) Analysis 每個 section.g 必須出現在 coverage.sec[].g
    3) trace 需回報 analysis_item_count、covered_item_count、missing_ids、missing_sections
- 若內容長，優先精簡措辭，不可省略條目，不可輸出截斷 JSON。

Schema:
{
  "analysis":{
    "sec":[
      {"g":"功能名稱","it":[{"id":"010.001","t":"驗證排序欄位顯示與排序行為","det":["限制條件"],"chk":["姓名欄位可排序","生日欄位可排序","電話欄位可排序","地址欄位可排序"],"exp":["姓名依升冪排列","生日依升冪排列","電話依升冪排列","地址依升冪排列"],"rid":["REQ-001","REF-001"]}]}
    ],
    "it":[{"id":"010.001","t":"...","det":["..."],"chk":["..."],"exp":["..."],"rid":["REQ-001"]}]
  },
  "coverage":{
    "sec":[{"g":"功能名稱","seed":[{"g":"功能名稱","t":"驗證欄位排序","ax":"happy","cat":"happy","st":"ok","a":"","ref":["010.001"],"rid":["REQ-001","REF-001"],"chk":["姓名可排序","生日可排序"],"exp":["姓名升冪","生日升冪"],"pre_hint":["已有多筆資料"],"step_hint":["點擊欄位標題觸發排序"]}]}],
    "seed":[{"g":"功能名稱","t":"...","ax":"happy","cat":"happy","st":"ok","a":"","ref":["010.001"],"rid":["REQ-001"],"chk":["..."],"exp":["..."],"pre_hint":["..."],"step_hint":["..."]}],
    "trace":{"analysis_item_count":0,"covered_item_count":0,"missing_ids":[],"missing_sections":[],"aspect_review":{"happy":"covered","edge":"covered","error":"covered","permission":"assume"}}
  }
}"""

JIRA_HELPER_COVERAGE_PROMPT_TEMPLATE = """你是 QA 測試設計師。請使用 {review_language}，根據 Requirement IR + Analysis 產生 pre-testcase seeds。

Requirement IR JSON:
{requirement_ir_json}
Analysis JSON:
{expanded_requirements_json}

只輸出單一 JSON 物件，不可有 Markdown/code fence/說明文字。
輸出必須可直接被 JSON.parse 成功。
規則：
- 每個 seed 對應 1 個未來 test case（1 seed = 1 expected result）。
- seed.ref 必須且只能有 1 個 analysis item.id。
- coverage 類別僅允許：happy、negative、boundary。
- 每個 seed 必須提供足夠線索給低推理模型：t、chk、exp、pre_hint、step_hint。
- seed.t 不可只寫「參考 REF-xxx」；必須描述可執行檢核。
- 若 seed 涵蓋多欄位，chk/exp 必須逐欄列明。
- rid 若含 REF，僅允許單一 REF token，禁止 REF 區間。
- 僅當條目明確是邊界語義（上限/下限/極值/分頁跨頁/固定欄位/捲動/極窄寬度）時，cat 才是 boundary。
- 一般功能流程（含一般排序/一般欄位檢核）預設為 happy。
- 輸出 sec（分組）與 seed（展平）兩種視圖。
- 完整性契約：
  1) Analysis 每個 item.id 至少出現在一個 seed.ref
  2) Analysis 每個 section.g 必須出現在 coverage.sec[].g
  3) trace 需回報 analysis_item_count、covered_item_count、missing_ids、missing_sections
- 若內容太長，優先縮短文字，不可刪條目，不可輸出截斷 JSON。

Schema:
{
  "sec":[{"g":"功能名稱","seed":[{"g":"功能名稱","t":"驗證欄位排序","cat":"happy","st":"ok","ref":["010.001"],"rid":["REQ-001","REF-001"],"chk":["姓名可排序","生日可排序"],"exp":["姓名升冪","生日升冪"],"pre_hint":["已有多筆資料"],"step_hint":["點擊欄位標題觸發排序"]}]}],
  "seed":[{"g":"功能名稱","t":"...","cat":"happy","st":"ok","ref":["010.001"],"rid":["REQ-001"],"chk":["..."],"exp":["..."],"pre_hint":["..."],"step_hint":["..."]}],
  "trace":{"analysis_item_count":0,"covered_item_count":0,"missing_ids":[],"missing_sections":[]}
}"""

JIRA_HELPER_COVERAGE_BACKFILL_PROMPT_TEMPLATE = """你是 QA 覆蓋補全器。請使用 {review_language}，只補 missing_ids/missing_sections，不可改寫既有 coverage。

Requirement IR JSON:
{requirement_ir_json}
Analysis JSON:
{expanded_requirements_json}
Current Coverage JSON:
{current_coverage_json}
Missing analysis ids:
{missing_ids_json}
Missing sections:
{missing_sections_json}

只輸出單一 JSON 物件，不可有 Markdown/code fence/說明文字。
規則：
- 只新增 seed，不可覆寫既有 seed。
- 每個新增 seed.ref 必須且只能有 1 個 item.id。
- 每個新增 seed 仍需提供 t/chk/exp/pre_hint/step_hint 線索。
- rid 若含 REF，僅允許單一 REF token，禁止區間。
- 依條目語義決定 cat：錯誤/無效/拒絕 => negative；僅明確邊界語義（上限下限/極值/分頁跨頁/固定欄位/捲動/極窄寬度）=> boundary。
- 若僅為一般排序或一般欄位檢核，cat 應為 happy。
- 若字數過長，縮短句子，不可輸出截斷 JSON。

Schema:
{"seed":[{"g":"功能名稱","t":"...","cat":"happy","st":"ok","ref":["010.001"],"rid":["REQ-001"],"chk":["..."],"exp":["..."],"pre_hint":["..."],"step_hint":["..."]}],"trace":{"resolved_ids":["010.001"],"resolved_sections":["功能名稱"]}}"""

JIRA_HELPER_TESTCASE_PROMPT_TEMPLATE = """你是 QA 工程師。請使用 {output_language}，根據單一 section 的 pre-testcase 條目產生詳細 test cases。

TCG: {ticket_key}
Section: {section_no} {section_name}
Stage 1 Entries JSON (single section):
{coverage_questions_json}
Retrieved clues (jira_references + test_cases):
{similar_cases}
Retry hint:
{retry_hint}

只輸出單一 JSON 物件，不可有 Markdown/code fence/說明文字。
規則：
- 只處理輸入 section 的 en 條目。
- 每個 en 條目必須且只能產生一筆 testcase（1:1）。
- testcase.id 必須是 {ticket_key}.{en.cid}。
- t 必須具體，且能反映 chk/exp 線索，不可空泛。
- pre 至少 2 條，且需包含測試資料與角色/權限或入口條件。
- s 至少 3 步，且每一步都必須可操作、可重現。
- exp 必須且只能有 1 筆字串，且需包含可觀測結果（畫面元素/回傳欄位/狀態碼/訊息）。
- st=assume 時，t 需以 [ASSUME] 開頭，並在 pre 或 exp 明示假設。
- st=ask 時，t 需以 [TBD] 開頭，並在 pre 或 exp 明示「待確認事項」（不可使用 TBD/N/A/同上/略）。
- pre/s/exp 禁止出現 REF/同上/略/TBD/N/A 這類占位詞。
- 不可遺漏條目；不可輸出截斷 JSON。

Schema:
{"tc":[{"id":"{ticket_key}.010.010","t":"...","pre":["詳細前置條件"],"s":["詳細步驟1","詳細步驟2"],"exp":["單一且完整的預期結果"]}]}"""

JIRA_HELPER_TESTCASE_SUPPLEMENT_PROMPT_TEMPLATE = """你是 QA 補全器。請使用 {output_language}，只補上缺漏或不合格的 testcases。

TCG: {ticket_key}
Section: {section_no} {section_name}
Missing/Invalid Stage 1 Entries JSON:
{coverage_questions_json}
Current testcase JSON:
{testcase_json}
Retrieved clues (jira_references + test_cases):
{similar_cases}
Retry hint:
{retry_hint}

只輸出單一 JSON 物件，不可有 Markdown/code fence/說明文字。
規則：
- 只輸出需要補全的 testcase；不要重複輸出已正確條目。
- id 必須使用 {ticket_key}.{en.cid}。
- pre 至少 2 條、s 至少 3 步；exp 必須且只能 1 筆且可觀測。
- pre/s/exp 禁止出現 REF/同上/略/TBD/N/A 這類占位詞。
- 不可輸出截斷 JSON。

Schema:
{"tc":[{"id":"{ticket_key}.010.020","t":"...","pre":["..."],"s":["..."],"exp":["..."]}]}"""

JIRA_HELPER_AUDIT_PROMPT_TEMPLATE = """你是 QA 審查員。請使用 {output_language}，審查並補強單一 section 的 testcases。

TCG: {ticket_key}
Section: {section_no} {section_name}
Stage 1 Entries JSON (single section):
{coverage_questions_json}
Testcases JSON:
{testcase_json}
Retrieved clues (jira_references + test_cases):
{similar_cases}
Retry hint:
{retry_hint}

只輸出單一 JSON 物件，不可有 Markdown/code fence/說明文字。
規則：
- 保持每筆 id 不變；若缺項可補全內容，但不可變更目標條目集合。
- 必須逐條對照 en 的 chk/exp 線索補強 pre/s/exp 細節。
- pre 至少 2 條、s 至少 3 步；exp 必須且只能有 1 筆（單一核心預期且可觀測）。
- [ASSUME]/[TBD] 規則必須正確，且 pre/s/exp 禁止使用 REF/同上/略/TBD/N/A。
- 不可遺漏條目；不可輸出截斷 JSON。

Schema:
{"tc":[{"id":"{ticket_key}.010.010","t":"...","pre":["..."],"s":["..."],"exp":["..."]}]}"""

class LarkConfig(BaseModel):
    app_id: str = ""
    app_secret: str = ""
    
    @classmethod
    def from_env(cls, fallback: 'LarkConfig' = None) -> 'LarkConfig':
        """從環境變數載入設定，如果環境變數為空則使用 fallback"""
        env_app_id = os.getenv('LARK_APP_ID')
        env_app_secret = os.getenv('LARK_APP_SECRET')
        
        return cls(
            app_id=env_app_id if env_app_id else (fallback.app_id if fallback else ''),
            app_secret=env_app_secret if env_app_secret else (fallback.app_secret if fallback else '')
        )

class JiraConfig(BaseModel):
    server_url: str = ""
    username: str = ""
    api_token: str = ""
    ca_cert_path: str = ""

class OpenRouterConfig(BaseModel):
    api_key: str = ""
    model: str = "openai/gpt-oss-120b:free"

    @classmethod
    def from_env(cls, fallback: 'OpenRouterConfig' = None) -> 'OpenRouterConfig':
        return cls(
            api_key=fallback.api_key if fallback else '',
            model=fallback.model if fallback else "openai/gpt-oss-120b:free"
        )


class JiraTestCaseHelperStageModelConfig(BaseModel):
    model: str = "google/gemini-3-flash-preview"
    api_url: str = "https://openrouter.ai/api/v1/chat/completions"
    temperature: float = 0.1
    timeout: int = 120
    system_prompt: str = "You are a QA engineer writing detailed test cases."


class JiraTestCaseHelperModelsConfig(BaseModel):
    analysis: JiraTestCaseHelperStageModelConfig = JiraTestCaseHelperStageModelConfig(
        model="google/gemini-3-flash-preview",
        system_prompt="You are a senior QA analyst.",
    )
    coverage: JiraTestCaseHelperStageModelConfig = JiraTestCaseHelperStageModelConfig(
        model="openai/gpt-5.2",
        system_prompt="You are a test design expert. Think step by step.",
    )
    testcase: JiraTestCaseHelperStageModelConfig = JiraTestCaseHelperStageModelConfig(
        model="google/gemini-3-flash-preview",
        system_prompt="You are a QA engineer writing detailed test cases.",
    )
    audit: JiraTestCaseHelperStageModelConfig = JiraTestCaseHelperStageModelConfig(
        model="google/gemini-3-flash-preview",
        system_prompt="You are a QA reviewer auditing generated test cases.",
    )


class JiraTestCaseHelperPromptsConfig(BaseModel):
    requirement_ir: str = JIRA_HELPER_REQUIREMENT_IR_PROMPT_TEMPLATE
    analysis: str = JIRA_HELPER_ANALYSIS_PROMPT_TEMPLATE
    coverage: str = JIRA_HELPER_COVERAGE_PROMPT_TEMPLATE
    coverage_backfill: str = JIRA_HELPER_COVERAGE_BACKFILL_PROMPT_TEMPLATE
    testcase: str = JIRA_HELPER_TESTCASE_PROMPT_TEMPLATE
    testcase_supplement: str = JIRA_HELPER_TESTCASE_SUPPLEMENT_PROMPT_TEMPLATE
    audit: str = JIRA_HELPER_AUDIT_PROMPT_TEMPLATE


class JiraTestCaseHelperConfig(BaseModel):
    prompt_contract_version: str = "helper-prompt.v2"
    payload_contract_version: str = "helper-draft.v2"
    similar_cases_count: int = 5
    similar_cases_max_length: int = 500
    enable_ir_first: bool = True
    coverage_backfill_max_rounds: int = 1
    coverage_backfill_chunk_size: int = 12
    coverage_force_complete: bool = True
    testcase_force_complete: bool = True
    min_steps: int = 3
    api_min_steps: int = 2
    min_preconditions: int = 1
    max_vi_per_section: int = 12
    max_repair_rounds: int = 3
    forbidden_patterns: List[str] = [
        "參考",
        "REF\\d+",
        "同上",
        "略",
        "TBD",
        "N/A",
        "待補",
        "TODO",
    ]
    models: JiraTestCaseHelperModelsConfig = JiraTestCaseHelperModelsConfig()
    prompts: JiraTestCaseHelperPromptsConfig = JiraTestCaseHelperPromptsConfig()


class AIConfig(BaseModel):
    jira_testcase_helper: JiraTestCaseHelperConfig = JiraTestCaseHelperConfig()

class QdrantWeightsConfig(BaseModel):
    test_cases: float = 0.7
    usm_nodes: float = 0.3


class QdrantLimitConfig(BaseModel):
    jira_referances: int = 20
    test_cases: int = 14
    usm_nodes: int = 6


class QdrantConfig(BaseModel):
    url: str = "http://localhost:6333"
    api_key: str = ""
    timeout: int = 30
    prefer_grpc: bool = False
    pool_size: int = 32
    max_concurrent_requests: int = 32
    max_retries: int = 3
    retry_backoff_seconds: float = 0.5
    retry_backoff_max_seconds: float = 5.0
    check_compatibility: bool = True
    collection_jira_referances: str = "jira_references"
    collection_test_cases: str = "test_cases"
    collection_usm_nodes: str = "usm_nodes"
    weights: QdrantWeightsConfig = QdrantWeightsConfig()
    limit: QdrantLimitConfig = QdrantLimitConfig()

    @classmethod
    def from_env(cls, fallback: 'QdrantConfig' = None) -> 'QdrantConfig':
        fallback_jira_collection = (
            fallback.collection_jira_referances if fallback else 'jira_references'
        )
        jira_collection = os.getenv(
            'QDRANT_COLLECTION_JIRA_REFERENCES',
            os.getenv('QDRANT_COLLECTION_JIRA_REFERANCES', fallback_jira_collection),
        )
        if str(jira_collection or '').strip() == 'jira_referances':
            jira_collection = 'jira_references'

        return cls(
            url=os.getenv('QDRANT_URL', fallback.url if fallback else 'http://localhost:6333'),
            api_key=os.getenv('QDRANT_API_KEY', fallback.api_key if fallback else ''),
            timeout=int(os.getenv('QDRANT_TIMEOUT', str(fallback.timeout if fallback else 30))),
            prefer_grpc=os.getenv('QDRANT_PREFER_GRPC', str(fallback.prefer_grpc if fallback else False)).lower() == 'true',
            pool_size=int(os.getenv('QDRANT_POOL_SIZE', str(fallback.pool_size if fallback else 32))),
            max_concurrent_requests=int(
                os.getenv(
                    'QDRANT_MAX_CONCURRENT_REQUESTS',
                    str(fallback.max_concurrent_requests if fallback else 32)
                )
            ),
            max_retries=int(os.getenv('QDRANT_MAX_RETRIES', str(fallback.max_retries if fallback else 3))),
            retry_backoff_seconds=float(
                os.getenv(
                    'QDRANT_RETRY_BACKOFF_SECONDS',
                    str(fallback.retry_backoff_seconds if fallback else 0.5)
                )
            ),
            retry_backoff_max_seconds=float(
                os.getenv(
                    'QDRANT_RETRY_BACKOFF_MAX_SECONDS',
                    str(fallback.retry_backoff_max_seconds if fallback else 5.0)
                )
            ),
            check_compatibility=os.getenv(
                'QDRANT_CHECK_COMPATIBILITY',
                str(fallback.check_compatibility if fallback else True)
            ).lower() == 'true',
            collection_jira_referances=jira_collection,
            collection_test_cases=os.getenv(
                'QDRANT_COLLECTION_TEST_CASES',
                fallback.collection_test_cases if fallback else 'test_cases'
            ),
            collection_usm_nodes=os.getenv(
                'QDRANT_COLLECTION_USM_NODES',
                fallback.collection_usm_nodes if fallback else 'usm_nodes'
            ),
            weights=fallback.weights if fallback else QdrantWeightsConfig(),
            limit=fallback.limit if fallback else QdrantLimitConfig(),
        )

class AppConfig(BaseModel):
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 9999
    database_url: str = "sqlite:///./test_case_repo.db"
    base_url: Optional[str] = None  # 優先使用環境變數設定，否則自動構建
    lark_dry_run: bool = False

    def get_base_url(self) -> str:
        """
        根據環境變數或配置動態構建 base_url
        優先級：
        1. APP_BASE_URL 環境變數
        2. 配置檔案中的 base_url
        3. 自動構建：http://localhost:{port}
        """
        # 1. 檢查環境變數（最高優先級）
        env_base_url = os.getenv('APP_BASE_URL')
        if env_base_url:
            return env_base_url

        # 2. 檢查配置檔案中是否明確設定了 base_url
        if self.base_url:
            return self.base_url

        # 3. 自動構建（預設為 localhost + port）
        # 在生產環境下應通過 APP_BASE_URL 環境變數明確設定
        return f"http://localhost:{self.port}"

    @classmethod
    def from_env(cls, fallback: 'AppConfig' = None) -> 'AppConfig':
        """從環境變數載入設定，如果環境變數為空則使用 fallback"""
        return cls(
            debug=os.getenv('DEBUG', str(fallback.debug).lower() if fallback else 'false').lower() == 'true',
            host=os.getenv('HOST', fallback.host if fallback else '0.0.0.0'),
            port=int(os.getenv('PORT', str(fallback.port) if fallback else '9999')),
            database_url=os.getenv('DATABASE_URL', fallback.database_url if fallback else 'sqlite:///./test_case_repo.db'),
            base_url=getattr(fallback, 'base_url', None) if fallback else None,  # 不在這裡硬設定，使用 get_base_url() 方法
            lark_dry_run=os.getenv('LARK_DRY_RUN', str(getattr(fallback, 'lark_dry_run', False)).lower() if fallback else 'false').lower() == 'true'
        )

class AuthConfig(BaseModel):
    """認證系統設定"""
    enable_auth: bool = True
    jwt_secret_key: str = ""
    jwt_expire_days: int = 7
    password_reset_expire_hours: int = 24
    session_cleanup_days: int = 30
    # 以角色為唯一權限來源，預設停用團隊權限機制
    use_team_permissions: bool = False
    
    @classmethod
    def from_env(cls, fallback: 'AuthConfig' = None) -> 'AuthConfig':
        """從環境變數載入認證設定"""
        # JWT_SECRET_KEY 必須來自環境變數
        jwt_secret = os.getenv('JWT_SECRET_KEY')
        if not jwt_secret:
            # 如果沒有環境變數，使用 fallback，但在生產環境會有警告
            jwt_secret = fallback.jwt_secret_key if fallback else ''
            
        return cls(
            enable_auth=os.getenv('ENABLE_AUTH', str(fallback.enable_auth if fallback else True)).lower() == 'true',
            jwt_secret_key=jwt_secret,
            jwt_expire_days=int(os.getenv('JWT_EXPIRE_DAYS', str(fallback.jwt_expire_days if fallback else 7))),
            password_reset_expire_hours=int(os.getenv('PASSWORD_RESET_EXPIRE_HOURS', str(fallback.password_reset_expire_hours if fallback else 24))),
            session_cleanup_days=int(os.getenv('SESSION_CLEANUP_DAYS', str(fallback.session_cleanup_days if fallback else 30))),
            use_team_permissions=False
        )

class AuditConfig(BaseModel):
    """審計系統設定"""
    enabled: bool = True
    database_url: str = "sqlite:///./audit.db"
    batch_size: int = 100
    cleanup_days: int = 365
    max_detail_size: int = 10240
    excluded_fields: list = ['password', 'token', 'secret', 'key']
    debug_sql: bool = False
    
    @classmethod
    def from_env(cls, fallback: 'AuditConfig' = None) -> 'AuditConfig':
        """從環境變數載入審計設定"""
        return cls(
            enabled=os.getenv('ENABLE_AUDIT', str(fallback.enabled if fallback else True)).lower() == 'true',
            database_url=os.getenv('AUDIT_DATABASE_URL', fallback.database_url if fallback else 'sqlite:///./audit.db'),
            batch_size=int(os.getenv('AUDIT_BATCH_SIZE', str(fallback.batch_size if fallback else 100))),
            cleanup_days=int(os.getenv('AUDIT_CLEANUP_DAYS', str(fallback.cleanup_days if fallback else 365))),
            max_detail_size=int(os.getenv('AUDIT_MAX_DETAIL_SIZE', str(fallback.max_detail_size if fallback else 10240))),
            excluded_fields=fallback.excluded_fields if fallback else ['password', 'token', 'secret', 'key'],
            debug_sql=os.getenv('AUDIT_DEBUG_SQL', str(fallback.debug_sql if fallback else False)).lower() == 'true'
        )

class AttachmentsConfig(BaseModel):
    # 若留空，則預設使用專案根目錄下的 attachments 子目錄
    root_dir: str = ""

    @classmethod
    def from_env(cls, fallback: 'AttachmentsConfig' = None) -> 'AttachmentsConfig':
        env_root = os.getenv('ATTACHMENTS_ROOT_DIR')
        return cls(
            root_dir=env_root if env_root else (fallback.root_dir if fallback else '')
        )
    
class Settings(BaseModel):
    app: AppConfig = AppConfig()
    lark: LarkConfig = LarkConfig()
    jira: JiraConfig = JiraConfig()
    openrouter: OpenRouterConfig = OpenRouterConfig()
    ai: AIConfig = AIConfig()
    qdrant: QdrantConfig = QdrantConfig()
    attachments: AttachmentsConfig = AttachmentsConfig()
    auth: AuthConfig = AuthConfig()
    audit: AuditConfig = AuditConfig()
    
    @classmethod
    def from_env_and_file(cls, config_path: str = "config.yaml") -> 'Settings':
        """從環境變數和 YAML 檔案載入設定（環境變數優先）"""
        # 先載入檔案設定
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as file:
                config_data = yaml.safe_load(file) or {}
            base_settings = cls(**config_data)
        else:
            base_settings = cls()
        
        # 環境變數覆蓋檔案設定（僅當環境變數存在時）
        return cls(
            app=AppConfig.from_env(base_settings.app),
            lark=LarkConfig.from_env(base_settings.lark),
            jira=base_settings.jira,  # JIRA 保持檔案設定
            openrouter=OpenRouterConfig.from_env(base_settings.openrouter),
            ai=base_settings.ai,
            qdrant=QdrantConfig.from_env(base_settings.qdrant),
            attachments=AttachmentsConfig.from_env(base_settings.attachments),
            auth=AuthConfig.from_env(base_settings.auth),
            audit=AuditConfig.from_env(base_settings.audit)
        )

def load_config(config_path: str = "config.yaml") -> Settings:
    """讀取 YAML 設定檔（兼容旧版）"""
    return Settings.from_env_and_file(config_path)

def create_default_config(config_path: str = "config.yaml") -> None:
    """建立預設設定檔"""
    default_config = {
        "app": {
            "debug": False,
            "host": "0.0.0.0",
            "port": 9999,
            "database_url": "sqlite:///./test_case_repo.db"
        },
        "lark": {
            "app_id": "",
            "app_secret": ""
        },
        "jira": {
            "server_url": "",
            "username": "",
            "api_token": "",
            "ca_cert_path": ""
        },
        "openrouter": {
            "api_key": ""
        },
        "ai": {
                "jira_testcase_helper": {
                    "similar_cases_count": 5,
                    "similar_cases_max_length": 500,
                    "enable_ir_first": True,
                    "coverage_backfill_max_rounds": 1,
                    "coverage_backfill_chunk_size": 12,
                    "coverage_force_complete": True,
                    "testcase_force_complete": True,
                    "min_steps": 3,
                    "api_min_steps": 2,
                    "min_preconditions": 1,
                    "max_vi_per_section": 12,
                    "max_repair_rounds": 3,
                    "forbidden_patterns": [
                        "參考",
                        "REF\\d+",
                        "同上",
                        "略",
                        "TBD",
                        "N/A",
                        "待補",
                        "TODO",
                    ],
                    "models": {
                    "analysis": {
                        "model": "google/gemini-3-flash-preview",
                        "api_url": "https://openrouter.ai/api/v1/chat/completions",
                        "temperature": 0.1,
                        "timeout": 120,
                        "system_prompt": "You are a senior QA analyst."
                    },
                    "coverage": {
                        "model": "openai/gpt-5.2",
                        "api_url": "https://openrouter.ai/api/v1/chat/completions",
                        "temperature": 0.1,
                        "timeout": 120,
                        "system_prompt": "You are a test design expert. Think step by step."
                    },
                    "testcase": {
                        "model": "google/gemini-3-flash-preview",
                        "api_url": "https://openrouter.ai/api/v1/chat/completions",
                        "temperature": 0.1,
                        "timeout": 120,
                        "system_prompt": "You are a QA engineer writing detailed test cases."
                    },
                    "audit": {
                        "model": "google/gemini-3-flash-preview",
                        "api_url": "https://openrouter.ai/api/v1/chat/completions",
                        "temperature": 0.1,
                        "timeout": 120,
                        "system_prompt": "You are a QA reviewer auditing generated test cases."
                    }
                },
                "prompts": {
                    "requirement_ir": JIRA_HELPER_REQUIREMENT_IR_PROMPT_TEMPLATE,
                    "analysis": JIRA_HELPER_ANALYSIS_PROMPT_TEMPLATE,
                    "coverage": JIRA_HELPER_COVERAGE_PROMPT_TEMPLATE,
                    "coverage_backfill": JIRA_HELPER_COVERAGE_BACKFILL_PROMPT_TEMPLATE,
                    "testcase": JIRA_HELPER_TESTCASE_PROMPT_TEMPLATE,
                    "testcase_supplement": JIRA_HELPER_TESTCASE_SUPPLEMENT_PROMPT_TEMPLATE,
                    "audit": JIRA_HELPER_AUDIT_PROMPT_TEMPLATE
                }
            }
        },
        "qdrant": {
            "url": "http://localhost:6333",
            "api_key": "",
            "timeout": 30,
            "prefer_grpc": False,
            "pool_size": 32,
            "max_concurrent_requests": 32,
            "max_retries": 3,
            "retry_backoff_seconds": 0.5,
            "retry_backoff_max_seconds": 5.0,
            "check_compatibility": True,
            "collection_jira_referances": "jira_references",
            "collection_test_cases": "test_cases",
            "collection_usm_nodes": "usm_nodes",
            "weights": {
                "test_cases": 0.7,
                "usm_nodes": 0.3
            },
            "limit": {
                "jira_referances": 20,
                "test_cases": 14,
                "usm_nodes": 6
            }
        },
        "attachments": {
            "root_dir": ""  # 留空代表使用專案內 attachments 目錄
        },
        "auth": {
            "enable_auth": True,
            "jwt_secret_key": "${JWT_SECRET_KEY}",  # 必須由環境變數提供
            "jwt_expire_days": 7,
            "password_reset_expire_hours": 24,
            "session_cleanup_days": 30,
            "use_team_permissions": False
        },
        "audit": {
            "enabled": True,
            "database_url": "sqlite:///./audit.db",
            "batch_size": 100,
            "cleanup_days": 365,
            "max_detail_size": 10240,
            "excluded_fields": ["password", "token", "secret", "key"],
            "debug_sql": False
        }
    }
    
    with open(config_path, 'w', encoding='utf-8') as file:
        yaml.dump(default_config, file, default_flow_style=False, allow_unicode=True)

# 全域設定實例
settings = Settings.from_env_and_file()

# 方便的 getter 函式
def get_settings() -> Settings:
    """取得設定實例"""
    return settings
