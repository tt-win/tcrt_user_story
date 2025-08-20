import yaml
import os
from typing import Optional, Dict, Any
from pydantic import BaseModel

class LarkConfig(BaseModel):
    app_id: str = ""
    app_secret: str = ""

class JiraConfig(BaseModel):
    server_url: str = ""
    username: str = ""
    api_token: str = ""

class AppConfig(BaseModel):
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 9999
    database_url: str = "sqlite:///./test_case_repo.db"
    
class Settings(BaseModel):
    app: AppConfig = AppConfig()
    lark: LarkConfig = LarkConfig()
    jira: JiraConfig = JiraConfig()

def load_config(config_path: str = "config.yaml") -> Settings:
    """讀取 YAML 設定檔"""
    if not os.path.exists(config_path):
        # 如果設定檔不存在，回傳預設設定
        return Settings()
    
    with open(config_path, 'r', encoding='utf-8') as file:
        config_data = yaml.safe_load(file) or {}
    
    return Settings(**config_data)

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
settings = load_config()