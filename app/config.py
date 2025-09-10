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
    
class Settings(BaseModel):
    app: AppConfig = AppConfig()
    lark: LarkConfig = LarkConfig()
    jira: JiraConfig = JiraConfig()
    
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
            jira=base_settings.jira  # JIRA 保持檔案設定
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
