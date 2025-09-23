import yaml
import os
from typing import Optional, Dict, Any
from pydantic import BaseModel
from dotenv import load_dotenv

# 載入 .env 檔案（如果存在）
load_dotenv()

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

class AppConfig(BaseModel):
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 9999
    database_url: str = "sqlite:///./test_case_repo.db"
    base_url: str = "http://localhost:8000"
    lark_dry_run: bool = False
    
    @classmethod
    def from_env(cls, fallback: 'AppConfig' = None) -> 'AppConfig':
        """從環境變數載入設定，如果環境變數為空則使用 fallback"""
        return cls(
            debug=os.getenv('DEBUG', str(fallback.debug).lower() if fallback else 'false').lower() == 'true',
            host=os.getenv('HOST', fallback.host if fallback else '0.0.0.0'),
            port=int(os.getenv('PORT', str(fallback.port) if fallback else '9999')),
            database_url=os.getenv('DATABASE_URL', fallback.database_url if fallback else 'sqlite:///./test_case_repo.db'),
            base_url=os.getenv('APP_BASE_URL', getattr(fallback, 'base_url', 'http://localhost:8000') if fallback else 'http://localhost:8000'),
            lark_dry_run=os.getenv('LARK_DRY_RUN', str(getattr(fallback, 'lark_dry_run', False)).lower() if fallback else 'false').lower() == 'true'
        )

class AuthConfig(BaseModel):
    """認證系統設定"""
    enable_auth: bool = True
    jwt_secret_key: str = ""
    jwt_expire_days: int = 7
    password_reset_expire_hours: int = 24
    session_cleanup_days: int = 30
    
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
            session_cleanup_days=int(os.getenv('SESSION_CLEANUP_DAYS', str(fallback.session_cleanup_days if fallback else 30)))
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
            "api_token": ""
        },
        "attachments": {
            "root_dir": ""  # 留空代表使用專案內 attachments 目錄
        },
        "auth": {
            "enable_auth": True,
            "jwt_secret_key": "${JWT_SECRET_KEY}",  # 必須由環境變數提供
            "jwt_expire_days": 7,
            "password_reset_expire_hours": 24,
            "session_cleanup_days": 30
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
