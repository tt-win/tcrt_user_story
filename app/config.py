import yaml
import os
import logging
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse
from pydantic import BaseModel
from dotenv import load_dotenv

# 載入 .env 檔案（如果存在）
load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGGER = logging.getLogger(__name__)

DEFAULT_QDRANT_URL = "http://localhost:6333"
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
        return [
            _expand_env_placeholders(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
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


class JiraTestCaseHelperStageModelConfig(BaseModel):
    model: str = "google/gemini-3-flash-preview"
    temperature: float = 0.1


class JiraTestCaseHelperModelsConfig(BaseModel):
    analysis: JiraTestCaseHelperStageModelConfig = JiraTestCaseHelperStageModelConfig(
        model="google/gemini-3-flash-preview",
    )
    testcase: JiraTestCaseHelperStageModelConfig = JiraTestCaseHelperStageModelConfig(
        model="google/gemini-3-flash-preview",
    )
    audit: JiraTestCaseHelperStageModelConfig = JiraTestCaseHelperStageModelConfig(
        model="google/gemini-3-flash-preview",
    )


class JiraTestCaseHelperConfig(BaseModel):
    enable: bool = True
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
        )


class QAAIHelperConfig(BaseModel):
    enable: bool = True
    prompt_contract_version: str = "qa-ai-helper.prompt.v1"
    payload_contract_version: str = "qa-ai-helper.payload.v1"
    min_steps: int = 3
    min_preconditions: int = 1
    max_repair_rounds: int = 1
    generation_budget_row_limit: int = 120
    generation_budget_prompt_tokens: int = 12000
    generation_budget_output_tokens: int = 12000
    models: QAAIHelperModelsConfig = QAAIHelperModelsConfig()

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
            models=QAAIHelperModelsConfig.from_env(current.models),
        )


class AIAssistConfig(BaseModel):
    model: str = "openai/gpt-oss-120b:free"


class AIConfig(BaseModel):
    ai_assist: AIAssistConfig = AIAssistConfig()
    jira_testcase_helper: JiraTestCaseHelperConfig = JiraTestCaseHelperConfig()
    qa_ai_helper: QAAIHelperConfig = QAAIHelperConfig()

    @classmethod
    def from_env(cls, fallback: "AIConfig" = None) -> "AIConfig":
        current = fallback or cls()
        return cls(
            ai_assist=current.ai_assist,
            jira_testcase_helper=current.jira_testcase_helper,
            qa_ai_helper=QAAIHelperConfig.from_env(current.qa_ai_helper),
        )


class QdrantWeightsConfig(BaseModel):
    test_cases: float = 0.7
    usm_nodes: float = 0.3


class QdrantLimitConfig(BaseModel):
    jira_referances: int = 20
    test_cases: int = 14
    usm_nodes: int = 6


class QdrantConfig(BaseModel):
    url: str = DEFAULT_QDRANT_URL
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
    def from_env(cls, fallback: "QdrantConfig" = None) -> "QdrantConfig":
        fallback_jira_collection = fallback.collection_jira_referances if fallback else "jira_references"
        jira_collection = os.getenv(
            "QDRANT_COLLECTION_JIRA_REFERENCES",
            os.getenv("QDRANT_COLLECTION_JIRA_REFERANCES", fallback_jira_collection),
        )
        if str(jira_collection or "").strip() == "jira_referances":
            jira_collection = "jira_references"

        return cls(
            url=os.getenv("QDRANT_URL", fallback.url if fallback else DEFAULT_QDRANT_URL),
            api_key=os.getenv("QDRANT_API_KEY", fallback.api_key if fallback else ""),
            timeout=int(os.getenv("QDRANT_TIMEOUT", str(fallback.timeout if fallback else 30))),
            prefer_grpc=os.getenv("QDRANT_PREFER_GRPC", str(fallback.prefer_grpc if fallback else False)).lower()
            == "true",
            pool_size=int(os.getenv("QDRANT_POOL_SIZE", str(fallback.pool_size if fallback else 32))),
            max_concurrent_requests=int(
                os.getenv("QDRANT_MAX_CONCURRENT_REQUESTS", str(fallback.max_concurrent_requests if fallback else 32))
            ),
            max_retries=int(os.getenv("QDRANT_MAX_RETRIES", str(fallback.max_retries if fallback else 3))),
            retry_backoff_seconds=float(
                os.getenv("QDRANT_RETRY_BACKOFF_SECONDS", str(fallback.retry_backoff_seconds if fallback else 0.5))
            ),
            retry_backoff_max_seconds=float(
                os.getenv(
                    "QDRANT_RETRY_BACKOFF_MAX_SECONDS", str(fallback.retry_backoff_max_seconds if fallback else 5.0)
                )
            ),
            check_compatibility=os.getenv(
                "QDRANT_CHECK_COMPATIBILITY", str(fallback.check_compatibility if fallback else True)
            ).lower()
            == "true",
            collection_jira_referances=jira_collection,
            collection_test_cases=os.getenv(
                "QDRANT_COLLECTION_TEST_CASES", fallback.collection_test_cases if fallback else "test_cases"
            ),
            collection_usm_nodes=os.getenv(
                "QDRANT_COLLECTION_USM_NODES", fallback.collection_usm_nodes if fallback else "usm_nodes"
            ),
            weights=fallback.weights if fallback else QdrantWeightsConfig(),
            limit=fallback.limit if fallback else QdrantLimitConfig(),
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
        )


class AuditConfig(BaseModel):
    """審計系統設定"""

    enabled: bool = True
    database_url: str = "sqlite:///./audit.db"
    batch_size: int = 100
    cleanup_days: int = 365
    max_detail_size: int = 10240
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


class Settings(BaseModel):
    app: AppConfig = AppConfig()
    lark: LarkConfig = LarkConfig()
    jira: JiraConfig = JiraConfig()
    openrouter: OpenRouterConfig = OpenRouterConfig()
    ai: AIConfig = AIConfig()
    qdrant: QdrantConfig = QdrantConfig()
    attachments: AttachmentsConfig = AttachmentsConfig()
    reports: ReportsConfig = ReportsConfig()
    auth: AuthConfig = AuthConfig()
    audit: AuditConfig = AuditConfig()
    usm: UsmConfig = UsmConfig()

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
            ai=AIConfig.from_env(base_settings.ai),
            qdrant=QdrantConfig.from_env(base_settings.qdrant),
            attachments=AttachmentsConfig.from_env(base_settings.attachments),
            reports=ReportsConfig.from_env(base_settings.reports),
            auth=AuthConfig.from_env(base_settings.auth),
            audit=AuditConfig.from_env(base_settings.audit),
            usm=UsmConfig.from_env(base_settings.usm),
        )
        _warn_container_runtime_configuration(loaded)
        return loaded


def _warn_container_runtime_configuration(settings: Settings) -> None:
    if not _is_container_runtime():
        return

    runtime_urls = {
        "DATABASE_URL": settings.app.database_url,
        "AUDIT_DATABASE_URL": settings.audit.database_url,
        "USM_DATABASE_URL": settings.usm.database_url,
        "QDRANT_URL": settings.qdrant.url,
        "TEXT_EMBEDDING_URL": _first_non_empty_env("TEXT_EMBEDDING_URL") or "",
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
        "ai": {
            "ai_assist": {
                "model": "openai/gpt-oss-120b:free",
            },
            "jira_testcase_helper": {
                "enable": False,
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
                        "temperature": 0.1,
                    },
                    "testcase": {
                        "model": "google/gemini-3-flash-preview",
                        "temperature": 0.1,
                    },
                    "audit": {
                        "model": "google/gemini-3-flash-preview",
                        "temperature": 0.1,
                    },
                },
            },
            "qa_ai_helper": {
                "enable": True,
                "prompt_contract_version": "qa-ai-helper.prompt.v1",
                "payload_contract_version": "qa-ai-helper.payload.v1",
                "min_steps": 3,
                "min_preconditions": 1,
                "max_repair_rounds": 1,
                "generation_budget_row_limit": 120,
                "generation_budget_prompt_tokens": 12000,
                "generation_budget_output_tokens": 12000,
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
        "qdrant": {
            "url": DEFAULT_QDRANT_URL,
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
            "weights": {"test_cases": 0.7, "usm_nodes": 0.3},
            "limit": {"jira_referances": 20, "test_cases": 14, "usm_nodes": 6},
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
settings = Settings.from_env_and_file()


# 方便的 getter 函式
def get_settings() -> Settings:
    """取得設定實例"""
    return settings
