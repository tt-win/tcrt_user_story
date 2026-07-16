import yaml
import os
import logging
import re
from pathlib import Path
from typing import Optional, Any, ClassVar, List
from urllib.parse import urlparse
from pydantic import BaseModel
from dotenv import load_dotenv

# 載入 .env 檔案（如果存在）
load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGGER = logging.getLogger(__name__)

DEFAULT_PUBLIC_BASE_URL_TEMPLATE = "http://localhost:{port}"
LOCALHOST_HOSTNAMES = {"localhost", "127.0.0.1", "::1"}
ENV_PLACEHOLDER_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _first_non_empty_env(*names: str) -> Optional[str]:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def _env_truthy(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _is_container_runtime() -> bool:
    app_env = (_first_non_empty_env("APP_ENV") or "").lower()
    return _env_truthy("RUNNING_IN_DOCKER") or app_env in {"docker", "container"}


def _url_targets_localhost(url: str) -> bool:
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    hostname = (parsed.hostname or "").lower()
    return hostname in LOCALHOST_HOSTNAMES


def _expand_env_placeholders(value: Any, *, path: str = "config") -> Any:
    if isinstance(value, dict):
        return {
            key: _expand_env_placeholders(
                nested_value,
                path=f"{path}.{key}",
            )
            for key, nested_value in value.items()
        }
    if isinstance(value, list):
        return [_expand_env_placeholders(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    if not isinstance(value, str):
        return value

    def _replace(match: re.Match[str]) -> str:
        env_name = match.group(1)
        env_value = os.getenv(env_name)
        if env_value is None:
            raise ValueError(f"{path} 參考的環境變數 {env_name} 未設定")
        return env_value

    return ENV_PLACEHOLDER_RE.sub(_replace, value)


class LarkConfig(BaseModel):
    app_id: str = ""
    app_secret: str = ""

    @classmethod
    def from_env(cls, fallback: "LarkConfig" = None) -> "LarkConfig":
        """從環境變數載入設定，如果環境變數為空則使用 fallback"""
        env_app_id = os.getenv("LARK_APP_ID")
        env_app_secret = os.getenv("LARK_APP_SECRET")

        return cls(
            app_id=env_app_id if env_app_id else (fallback.app_id if fallback else ""),
            app_secret=env_app_secret if env_app_secret else (fallback.app_secret if fallback else ""),
        )


class JiraConfig(BaseModel):
    server_url: str = ""
    username: str = ""
    api_token: str = ""
    ca_cert_path: str = ""

    @classmethod
    def from_env(cls, fallback: "JiraConfig" = None) -> "JiraConfig":
        return cls(
            server_url=os.getenv("JIRA_SERVER_URL", fallback.server_url if fallback else ""),
            username=os.getenv("JIRA_USERNAME", fallback.username if fallback else ""),
            api_token=os.getenv("JIRA_API_TOKEN", fallback.api_token if fallback else ""),
            ca_cert_path=os.getenv("JIRA_CA_CERT_PATH", fallback.ca_cert_path if fallback else ""),
        )


class OpenRouterConfig(BaseModel):
    api_key: str = ""

    @classmethod
    def from_env(cls, fallback: "OpenRouterConfig" = None) -> "OpenRouterConfig":
        return cls(
            api_key=os.getenv("OPENROUTER_API_KEY", fallback.api_key if fallback else ""),
        )


class AllureConfig(BaseModel):
    """Org-level Allure Docker Service settings.

    Consumed by the TCRT-side Allure proxy (``allure_proxy._resolve_project_id``)
    when a run reaches a terminal state: ``base_url`` / ``api_token`` select the
    Allure server and ``project_id_template`` (expanded per run) selects which
    Allure project the results are sent to and the report generated from.

    Leave ``base_url`` empty to disable the Allure integration (the proxy then
    no-ops and ``report_url`` stays unset).

    ``project_id_template`` placeholders:
      - ``{team_id}``    — numeric team id
      - ``{team_slug}``  — slugified team name
      - ``{suite_id}``   — ``script-<id>`` for a single-script run, else the
        numeric script-group id (unique + stable across renames)
      - ``{suite_slug}`` — slugified script path / group name
    The default keeps each script and each suite in its own project so their
    reports don't bleed into one another. Use a static string (no placeholders)
    for a single org-wide project.
    """

    base_url: str = ""
    api_token: str = ""
    project_id_template: str = "tcrt-team-{team_slug}-{suite_slug}-{suite_id}"

    @classmethod
    def from_env(cls, fallback: "AllureConfig" = None) -> "AllureConfig":
        fb = fallback or cls()
        return cls(
            base_url=os.getenv("ALLURE_BASE_URL", fb.base_url),
            api_token=os.getenv("ALLURE_API_TOKEN", fb.api_token),
            project_id_template=os.getenv(
                "ALLURE_PROJECT_ID_TEMPLATE", fb.project_id_template
            ),
        )


class AutomationProviderConfig(BaseModel):
    encryption_key: str = ""
    allure: AllureConfig = AllureConfig()

    @classmethod
    def from_env(cls, fallback: "AutomationProviderConfig" = None) -> "AutomationProviderConfig":
        fb = fallback or cls()
        return cls(
            encryption_key=os.getenv(
                "AUTOMATION_PROVIDER_ENCRYPTION_KEY",
                fb.encryption_key,
            ),
            allure=AllureConfig.from_env(fb.allure),
        )


class QAAIHelperStageModelConfig(BaseModel):
    model: str = "google/gemini-3-flash-preview"
    temperature: float = 0.1

    @classmethod
    def from_env(cls, stage_name: str, fallback: "QAAIHelperStageModelConfig" = None) -> "QAAIHelperStageModelConfig":
        stage_key = stage_name.upper()
        return cls(
            model=os.getenv(
                f"QA_AI_HELPER_MODEL_{stage_key}",
                fallback.model if fallback else "google/gemini-3-flash-preview",
            ),
            temperature=float(
                os.getenv(
                    f"QA_AI_HELPER_MODEL_{stage_key}_TEMPERATURE",
                    str(fallback.temperature if fallback else 0.1),
                )
            ),
        )


class QAAIHelperModelsConfig(BaseModel):
    seed: QAAIHelperStageModelConfig = QAAIHelperStageModelConfig(
        model="google/gemini-3-flash-preview",
        temperature=0.1,
    )
    seed_refine: Optional[QAAIHelperStageModelConfig] = QAAIHelperStageModelConfig(
        model="google/gemini-3-flash-preview",
        temperature=0.0,
    )
    testcase: QAAIHelperStageModelConfig = QAAIHelperStageModelConfig(
        model="google/gemini-3-flash-preview",
        temperature=0.0,
    )
    repair: Optional[QAAIHelperStageModelConfig] = None
    inspection_extraction_a: QAAIHelperStageModelConfig = QAAIHelperStageModelConfig(
        model="openai/gpt-5.4-mini",
        temperature=0.1,
    )
    inspection_extraction_b: QAAIHelperStageModelConfig = QAAIHelperStageModelConfig(
        model="google/gemini-3-flash-preview",
        temperature=0.1,
    )
    inspection_extraction_c: QAAIHelperStageModelConfig = QAAIHelperStageModelConfig(
        model="x-ai/grok-4.20",
        temperature=0.1,
    )
    inspection_consolidation: QAAIHelperStageModelConfig = QAAIHelperStageModelConfig(
        model="openai/gpt-5.3-chat",
        temperature=0.1,
    )

    @classmethod
    def from_env(cls, fallback: "QAAIHelperModelsConfig" = None) -> "QAAIHelperModelsConfig":
        fallback_models = fallback or cls()
        return cls(
            seed=QAAIHelperStageModelConfig.from_env("SEED", fallback_models.seed),
            seed_refine=QAAIHelperStageModelConfig.from_env(
                "SEED_REFINE",
                fallback_models.seed_refine or fallback_models.seed,
            ),
            testcase=QAAIHelperStageModelConfig.from_env("TESTCASE", fallback_models.testcase),
            repair=fallback_models.repair,
            inspection_extraction_a=QAAIHelperStageModelConfig.from_env(
                "INSPECTION_EXTRACTION_A",
                fallback_models.inspection_extraction_a,
            ),
            inspection_extraction_b=QAAIHelperStageModelConfig.from_env(
                "INSPECTION_EXTRACTION_B",
                fallback_models.inspection_extraction_b,
            ),
            inspection_extraction_c=QAAIHelperStageModelConfig.from_env(
                "INSPECTION_EXTRACTION_C",
                fallback_models.inspection_extraction_c,
            ),
            inspection_consolidation=QAAIHelperStageModelConfig.from_env(
                "INSPECTION_CONSOLIDATION",
                fallback_models.inspection_consolidation,
            ),
        )


class InspectionRoleConfig(BaseModel):
    label: str
    role_name: str
    role_focus: str


class InspectionConfig(BaseModel):
    max_scenarios_warning: int = 5
    roles: List[InspectionRoleConfig] = [
        InspectionRoleConfig(
            label="A",
            role_name="Happy Path + Permission",
            role_focus=(
                "你專注於 Happy Path（正常流程驗證）與基本 Permission（權限控制）。"
                "確保主要正常使用情境都有對應的驗證項目，"
                "以及各角色的存取權限控制正確。"
            ),
        ),
        InspectionRoleConfig(
            label="B",
            role_name="Edge Cases + Performance",
            role_focus=(
                "你專注於 Edge Cases（邊界與異常輸入）與 Performance/Concurrency（效能與併發）。"
                "找出邊界值、空值、超長輸入、特殊字元等情境，"
                "以及併發操作、大量資料等效能相關的驗證項目。"
            ),
        ),
        InspectionRoleConfig(
            label="C",
            role_name="Error Handling + Abuse",
            role_focus=(
                "你專注於 Error Handling（錯誤處理）、進階 Permission 與 Abuse（濫用防護）。"
                "確保各種錯誤情境的處理正確，"
                "以及系統能防範惡意操作與權限繞過。"
            ),
        ),
    ]


class QAAIHelperConfig(BaseModel):
    enable: bool = True
    prompt_contract_version: str = "qa-ai-helper.prompt.v2"
    payload_contract_version: str = "qa-ai-helper.payload.v1"
    min_steps: int = 3
    min_preconditions: int = 1
    max_repair_rounds: int = 1
    generation_budget_row_limit: int = 120
    generation_budget_prompt_tokens: int = 12000
    generation_budget_output_tokens: int = 12000
    max_concurrent_llm_calls: int = 5
    models: QAAIHelperModelsConfig = QAAIHelperModelsConfig()
    inspection: InspectionConfig = InspectionConfig()

    @classmethod
    def from_env(cls, fallback: "QAAIHelperConfig" = None) -> "QAAIHelperConfig":
        current = fallback or cls()
        return cls(
            enable=current.enable,
            prompt_contract_version=current.prompt_contract_version,
            payload_contract_version=current.payload_contract_version,
            min_steps=current.min_steps,
            min_preconditions=current.min_preconditions,
            max_repair_rounds=current.max_repair_rounds,
            generation_budget_row_limit=current.generation_budget_row_limit,
            generation_budget_prompt_tokens=current.generation_budget_prompt_tokens,
            generation_budget_output_tokens=current.generation_budget_output_tokens,
            max_concurrent_llm_calls=int(
                os.getenv("QA_AI_HELPER_MAX_CONCURRENT_LLM_CALLS", str(current.max_concurrent_llm_calls))
            ),
            models=QAAIHelperModelsConfig.from_env(current.models),
            inspection=current.inspection,
        )


class AIConfig(BaseModel):
    qa_ai_helper: QAAIHelperConfig = QAAIHelperConfig()

    @classmethod
    def from_env(cls, fallback: "AIConfig" = None) -> "AIConfig":
        current = fallback or cls()
        return cls(
            qa_ai_helper=QAAIHelperConfig.from_env(current.qa_ai_helper),
        )


class AppConfig(BaseModel):
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 9999
    database_url: str = "sqlite:///./test_case_repo.db"
    public_base_url: Optional[str] = None
    base_url: Optional[str] = None  # legacy 欄位，保留向後相容
    lark_dry_run: bool = False

    def get_base_url(self) -> str:
        """
        根據環境變數或配置動態構建 base_url
        優先級：
        1. PUBLIC_BASE_URL 環境變數
        2. APP_BASE_URL 環境變數（legacy）
        3. 配置檔案中的 public_base_url
        4. 配置檔案中的 base_url（legacy）
        5. 自動構建：http://localhost:{port}
        """
        env_base_url = _first_non_empty_env("PUBLIC_BASE_URL", "APP_BASE_URL")
        if env_base_url:
            return env_base_url

        configured_base_url = self.public_base_url or self.base_url
        if configured_base_url:
            return configured_base_url

        if _is_container_runtime():
            LOGGER.warning("偵測到 container runtime，但未設定 PUBLIC_BASE_URL；暫時回退為 localhost。")

        return DEFAULT_PUBLIC_BASE_URL_TEMPLATE.format(port=self.port)

    @classmethod
    def from_env(cls, fallback: "AppConfig" = None) -> "AppConfig":
        """從環境變數載入設定，如果環境變數為空則使用 fallback"""
        resolved_public_base_url = _first_non_empty_env("PUBLIC_BASE_URL", "APP_BASE_URL")
        return cls(
            debug=os.getenv("DEBUG", str(fallback.debug).lower() if fallback else "false").lower() == "true",
            host=os.getenv("HOST", fallback.host if fallback else "0.0.0.0"),
            port=int(os.getenv("PORT", str(fallback.port) if fallback else "9999")),
            database_url=os.getenv(
                "DATABASE_URL", fallback.database_url if fallback else "sqlite:///./test_case_repo.db"
            ),
            public_base_url=resolved_public_base_url
            or getattr(fallback, "public_base_url", None)
            or getattr(fallback, "base_url", None),
            base_url=getattr(fallback, "base_url", None) if fallback else None,
            lark_dry_run=os.getenv(
                "LARK_DRY_RUN", str(getattr(fallback, "lark_dry_run", False)).lower() if fallback else "false"
            ).lower()
            == "true",
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
    # /api/app/* 與 /api/mcp/* 認證「失敗」的 per-IP rate limit（token-bucket）
    app_token_auth_fail_limit: int = 30
    app_token_auth_fail_window_seconds: int = 60

    @classmethod
    def from_env(cls, fallback: "AuthConfig" = None) -> "AuthConfig":
        """從環境變數載入認證設定"""
        # JWT_SECRET_KEY 必須來自環境變數
        jwt_secret = os.getenv("JWT_SECRET_KEY")
        if not jwt_secret:
            # 如果沒有環境變數，使用 fallback，但在生產環境會有警告
            jwt_secret = fallback.jwt_secret_key if fallback else ""

        return cls(
            enable_auth=os.getenv("ENABLE_AUTH", str(fallback.enable_auth if fallback else True)).lower() == "true",
            jwt_secret_key=jwt_secret,
            jwt_expire_days=int(os.getenv("JWT_EXPIRE_DAYS", str(fallback.jwt_expire_days if fallback else 7))),
            password_reset_expire_hours=int(
                os.getenv("PASSWORD_RESET_EXPIRE_HOURS", str(fallback.password_reset_expire_hours if fallback else 24))
            ),
            session_cleanup_days=int(
                os.getenv("SESSION_CLEANUP_DAYS", str(fallback.session_cleanup_days if fallback else 30))
            ),
            use_team_permissions=False,
            app_token_auth_fail_limit=int(
                os.getenv(
                    "APP_TOKEN_AUTH_FAIL_LIMIT",
                    str(fallback.app_token_auth_fail_limit if fallback else 30),
                )
            ),
            app_token_auth_fail_window_seconds=int(
                os.getenv(
                    "APP_TOKEN_AUTH_FAIL_WINDOW_SECONDS",
                    str(fallback.app_token_auth_fail_window_seconds if fallback else 60),
                )
            ),
        )


class AuditConfig(BaseModel):
    """審計系統設定"""

    enabled: bool = True
    database_url: str = "sqlite:///./audit.db"
    batch_size: int = 100
    cleanup_days: int = 365
    max_detail_size: int = 10240
    # 寫入失敗時保留於記憶體的重排緩衝上限，避免審計 DB 故障時無限增長
    max_buffer_size: int = 10000
    excluded_fields: list = ["password", "token", "secret", "key"]
    debug_sql: bool = False

    @classmethod
    def from_env(cls, fallback: "AuditConfig" = None) -> "AuditConfig":
        """從環境變數載入審計設定"""
        return cls(
            enabled=os.getenv("ENABLE_AUDIT", str(fallback.enabled if fallback else True)).lower() == "true",
            database_url=os.getenv("AUDIT_DATABASE_URL", fallback.database_url if fallback else "sqlite:///./audit.db"),
            batch_size=int(os.getenv("AUDIT_BATCH_SIZE", str(fallback.batch_size if fallback else 100))),
            cleanup_days=int(os.getenv("AUDIT_CLEANUP_DAYS", str(fallback.cleanup_days if fallback else 365))),
            max_detail_size=int(
                os.getenv("AUDIT_MAX_DETAIL_SIZE", str(fallback.max_detail_size if fallback else 10240))
            ),
            max_buffer_size=int(
                os.getenv("AUDIT_MAX_BUFFER_SIZE", str(fallback.max_buffer_size if fallback else 10000))
            ),
            excluded_fields=fallback.excluded_fields if fallback else ["password", "token", "secret", "key"],
            debug_sql=os.getenv("AUDIT_DEBUG_SQL", str(fallback.debug_sql if fallback else False)).lower() == "true",
        )


class UsmConfig(BaseModel):
    """User Story Map 資料庫設定"""

    database_url: str = "sqlite:///./userstorymap.db"
    debug_sql: bool = False

    @classmethod
    def from_env(cls, fallback: "UsmConfig" = None) -> "UsmConfig":
        return cls(
            database_url=os.getenv(
                "USM_DATABASE_URL", fallback.database_url if fallback else "sqlite:///./userstorymap.db"
            ),
            debug_sql=os.getenv("USM_DEBUG_SQL", str(fallback.debug_sql if fallback else False)).lower() == "true",
        )


class AttachmentsConfig(BaseModel):
    # 若留空，則預設使用專案根目錄下的 attachments 子目錄
    root_dir: str = ""

    @classmethod
    def from_env(cls, fallback: "AttachmentsConfig" = None) -> "AttachmentsConfig":
        env_root = os.getenv("ATTACHMENTS_ROOT_DIR")
        return cls(root_dir=env_root if env_root else (fallback.root_dir if fallback else ""))

    def resolve_root_dir(self, project_root: Optional[Path] = None) -> Path:
        base_root = project_root or PROJECT_ROOT
        return Path(self.root_dir) if self.root_dir else (base_root / "attachments")


class ReportsConfig(BaseModel):
    # 若留空，則預設使用專案根目錄下的 generated_report 子目錄
    root_dir: str = ""

    @classmethod
    def from_env(cls, fallback: "ReportsConfig" = None) -> "ReportsConfig":
        env_root = os.getenv("REPORTS_ROOT_DIR")
        return cls(root_dir=env_root if env_root else (fallback.root_dir if fallback else ""))

    def resolve_root_dir(self, project_root: Optional[Path] = None) -> Path:
        base_root = project_root or PROJECT_ROOT
        return Path(self.root_dir) if self.root_dir else (base_root / "generated_report")


class LogViewerConfig(BaseModel):
    """Super Admin 系統 log viewer 設定（全部為 per-worker 容量）"""

    buffer_size: int = 2000
    max_streams: int = 3
    max_message_chars: int = 4096
    subscriber_queue_size: int = 1000
    keepalive_seconds: int = 15
    stream_max_lifetime_seconds: int = 900

    # (env var, 欄位名, 預設, 下限, 上限)
    FIELD_BOUNDS: ClassVar[tuple] = (
        ("LOG_VIEWER_BUFFER_SIZE", "buffer_size", 2000, 1, 20000),
        ("LOG_VIEWER_MAX_STREAMS", "max_streams", 3, 1, 10),
        ("LOG_VIEWER_MAX_MESSAGE_CHARS", "max_message_chars", 4096, 1, 65536),
        ("LOG_VIEWER_SUBSCRIBER_QUEUE_SIZE", "subscriber_queue_size", 1000, 1, 10000),
        ("LOG_VIEWER_KEEPALIVE_SECONDS", "keepalive_seconds", 15, 5, 60),
        ("LOG_VIEWER_STREAM_MAX_LIFETIME_SECONDS", "stream_max_lifetime_seconds", 900, 60, 3600),
    )
    # per-worker aggregate budget（字元數）：單欄位各自合法不代表組合合法
    AGGREGATE_BUDGET_CHARS: ClassVar[int] = 2**25

    @classmethod
    def from_env(cls, fallback: "LogViewerConfig" = None) -> "LogViewerConfig":
        values = {}
        for env_name, field, default, low, high in cls.FIELD_BOUNDS:
            base = getattr(fallback, field) if fallback else default
            raw = os.getenv(env_name)
            value = base
            if raw is not None:
                try:
                    value = int(raw)
                except ValueError:
                    value = default
            if not (low <= value <= high):
                LOGGER.warning(
                    "LogViewerConfig: %s=%r 超出合法範圍 [%d, %d]，改用預設值 %d",
                    env_name, value, low, high, default,
                )
                value = default
            values[field] = value

        # 跨欄位 aggregate budget：buffer 與訂閱端（係數 2 計 generator 持有
        # local batch 期間 pending 再度填滿的峰值）各不得超過預算，
        # 超過即整組容量欄位回落預設值（規則單一、可預期）。
        buffer_chars = values["buffer_size"] * values["max_message_chars"]
        subscriber_chars = (
            2 * values["max_streams"] * values["subscriber_queue_size"] * values["max_message_chars"]
        )
        if buffer_chars > cls.AGGREGATE_BUDGET_CHARS or subscriber_chars > cls.AGGREGATE_BUDGET_CHARS:
            LOGGER.warning(
                "LogViewerConfig: 容量組合超出 per-worker 預算（buffer=%d、subscriber=%d、budget=%d 字元），"
                "容量欄位整組回落預設值",
                buffer_chars, subscriber_chars, cls.AGGREGATE_BUDGET_CHARS,
            )
            for _env, field, default, _low, _high in cls.FIELD_BOUNDS:
                if field not in ("keepalive_seconds", "stream_max_lifetime_seconds"):
                    values[field] = default
        return cls(**values)


class Settings(BaseModel):
    app: AppConfig = AppConfig()
    lark: LarkConfig = LarkConfig()
    jira: JiraConfig = JiraConfig()
    openrouter: OpenRouterConfig = OpenRouterConfig()
    automation_provider: AutomationProviderConfig = AutomationProviderConfig()
    ai: AIConfig = AIConfig()
    attachments: AttachmentsConfig = AttachmentsConfig()
    reports: ReportsConfig = ReportsConfig()
    auth: AuthConfig = AuthConfig()
    audit: AuditConfig = AuditConfig()
    usm: UsmConfig = UsmConfig()
    log_viewer: LogViewerConfig = LogViewerConfig()

    @classmethod
    def from_env_and_file(cls, config_path: str = "config.yaml") -> "Settings":
        """從環境變數和 YAML 檔案載入設定（環境變數優先）"""
        # 先載入檔案設定
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as file:
                config_data = yaml.safe_load(file) or {}
            config_data = _expand_env_placeholders(config_data)
            base_settings = cls(**config_data)
        else:
            base_settings = cls()

        # 環境變數覆蓋檔案設定（僅當環境變數存在時）
        loaded = cls(
            app=AppConfig.from_env(base_settings.app),
            lark=LarkConfig.from_env(base_settings.lark),
            jira=JiraConfig.from_env(base_settings.jira),
            openrouter=OpenRouterConfig.from_env(base_settings.openrouter),
            automation_provider=AutomationProviderConfig.from_env(base_settings.automation_provider),
            ai=AIConfig.from_env(base_settings.ai),
            attachments=AttachmentsConfig.from_env(base_settings.attachments),
            reports=ReportsConfig.from_env(base_settings.reports),
            auth=AuthConfig.from_env(base_settings.auth),
            audit=AuditConfig.from_env(base_settings.audit),
            usm=UsmConfig.from_env(base_settings.usm),
            log_viewer=LogViewerConfig.from_env(base_settings.log_viewer),
        )
        _warn_container_runtime_configuration(loaded)
        _fail_fast_if_sqlite_without_volume_ack(loaded)
        return loaded


def _fail_fast_if_sqlite_without_volume_ack(settings: Settings) -> None:
    """容器內用 SQLite 且沒有掛 volume，容器重建/重新部署會靜默遺失所有資料——這件事
    應用程式本身無法從檔案系統可靠偵測（bind mount 與容器可寫層在 stat() 層級看起來
    可能無法區分），所以改用明確的 op-in 環境變數，逼運維者在部署當下就正視這個風險，
    而不是等到容器重建、資料消失了才發現。"""
    if not _is_container_runtime():
        return
    if _env_truthy("SQLITE_CONTAINER_STORAGE_ACK"):
        return

    sqlite_targets = [
        (name, url)
        for name, url in (
            ("DATABASE_URL", settings.app.database_url),
            ("AUDIT_DATABASE_URL", settings.audit.database_url),
            ("USM_DATABASE_URL", settings.usm.database_url),
        )
        if (url or "").strip().lower().startswith("sqlite")
    ]
    if not sqlite_targets:
        return

    offending = ", ".join(f"{name}={url}" for name, url in sqlite_targets)
    raise RuntimeError(
        f"偵測到 container runtime 使用 SQLite（{offending}），但未設定 "
        "SQLITE_CONTAINER_STORAGE_ACK=1。容器沒有為這個路徑掛 volume 時，SQLite 檔案存在"
        "容器的可寫層，容器重建或重新部署會靜默遺失所有資料。請擇一處理：\n"
        "1. 確認已經幫這個 SQLite 檔案的目錄掛好 named volume 或 host bind mount，"
        "再設定 SQLITE_CONTAINER_STORAGE_ACK=1 明確承認並繼續（本檢查無法從應用層可靠"
        "驗證 volume 是否真的掛好，這個環境變數只是要求你在部署當下想清楚這件事）；\n"
        "2. 正式環境建議改用 MySQL/PostgreSQL（見 docs/database-cutover-readiness.md 的"
        "一鍵搬移流程 `--mode migrate`）。"
    )


def _warn_container_runtime_configuration(settings: Settings) -> None:
    if not _is_container_runtime():
        return

    runtime_urls = {
        "DATABASE_URL": settings.app.database_url,
        "AUDIT_DATABASE_URL": settings.audit.database_url,
        "USM_DATABASE_URL": settings.usm.database_url,
    }

    for key, value in runtime_urls.items():
        if value and _url_targets_localhost(value):
            LOGGER.warning(
                "偵測到 container runtime，但 %s 仍指向 localhost/127.0.0.1；容器互連請改用 service name。",
                key,
            )

    explicit_public_base_url = (
        _first_non_empty_env("PUBLIC_BASE_URL", "APP_BASE_URL") or settings.app.public_base_url or settings.app.base_url
    )
    if not explicit_public_base_url:
        LOGGER.warning("偵測到 container runtime，但未設定 PUBLIC_BASE_URL；對外連結與通知網址可能仍會落到 localhost。")


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
            "database_url": "sqlite:///./test_case_repo.db",
            "public_base_url": "",
        },
        "lark": {"app_id": "", "app_secret": ""},
        "jira": {"server_url": "", "username": "", "api_token": "", "ca_cert_path": ""},
        "openrouter": {"api_key": ""},
        "automation_provider": {"encryption_key": ""},
        "ai": {
            "qa_ai_helper": {
                "enable": True,
                "prompt_contract_version": "qa-ai-helper.prompt.v2",
                "payload_contract_version": "qa-ai-helper.payload.v1",
                "min_steps": 3,
                "min_preconditions": 1,
                "max_repair_rounds": 1,
                "generation_budget_row_limit": 120,
                "generation_budget_prompt_tokens": 12000,
                "generation_budget_output_tokens": 12000,
                "max_concurrent_llm_calls": 5,
                "models": {
                    "seed": {
                        "model": "google/gemini-3-flash-preview",
                        "temperature": 0.1,
                    },
                    "seed_refine": {
                        "model": "google/gemini-3-flash-preview",
                        "temperature": 0.0,
                    },
                    "testcase": {
                        "model": "google/gemini-3-flash-preview",
                        "temperature": 0.0,
                    },
                },
            },
        },
        "attachments": {
            "root_dir": ""  # 留空代表使用專案內 attachments 目錄
        },
        "reports": {
            "root_dir": ""  # 留空代表使用專案內 generated_report 目錄
        },
        "auth": {
            "enable_auth": True,
            "jwt_secret_key": "${JWT_SECRET_KEY}",  # 必須由環境變數提供
            "jwt_expire_days": 7,
            "password_reset_expire_hours": 24,
            "session_cleanup_days": 30,
            "use_team_permissions": False,
        },
        "audit": {
            "enabled": True,
            "database_url": "sqlite:///./audit.db",
            "batch_size": 100,
            "cleanup_days": 365,
            "max_detail_size": 10240,
            "excluded_fields": ["password", "token", "secret", "key"],
            "debug_sql": False,
        },
        "usm": {"database_url": "sqlite:///./userstorymap.db", "debug_sql": False},
    }

    with open(config_path, "w", encoding="utf-8") as file:
        yaml.dump(default_config, file, default_flow_style=False, allow_unicode=True)


# 全域設定實例
# APP_CONFIG_PATH 可指定 config.yaml 路徑（容器中以掛載方式提供）；未設定時回退預設 config.yaml。
# 與 app/db_migrations.py 的 APP_CONFIG_PATH 解析保持一致。
settings = Settings.from_env_and_file(os.getenv("APP_CONFIG_PATH") or "config.yaml")


# 方便的 getter 函式
def get_settings() -> Settings:
    """取得設定實例"""
    return settings
