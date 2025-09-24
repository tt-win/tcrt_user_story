"""
應用程式日誌記錄配置和工具函數
"""

import logging
from typing import Any, Dict
from datetime import datetime


def setup_app_logging():
    """設定應用程式的日誌記錄配置"""
    # 設定根日誌記錄器
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),  # 輸出到控制台
            # 可以添加檔案處理器
            # logging.FileHandler('app.log')
        ]
    )


def log_lark_display_decision(user_id: int, lark_linked: bool, has_data: bool, decision: str):
    """
    記錄 Lark 顯示決策
    
    Args:
        user_id: 使用者 ID
        lark_linked: 是否連結 Lark 帳號
        has_data: 是否有 Lark 數據
        decision: 顯示決策（顯示/隱藏）
    """
    logger = logging.getLogger(__name__)
    logger.info(f"Lark 顯示決策 - 使用者 {user_id}: "
                f"連結={lark_linked}, 有數據={has_data}, 決策='{decision}'")


def log_template_render(template_name: str, context: Dict[str, Any]):
    """
    記錄模板渲染事件
    
    Args:
        template_name: 模板名稱
        context: 模板上下文
    """
    logger = logging.getLogger(__name__)
    logger.debug(f"渲染模板 '{template_name}'，上下文包含: {list(context.keys())}")


def log_api_call(endpoint: str, method: str, user_id: int = None, success: bool = True):
    """
    記錄 API 呼叫事件
    
    Args:
        endpoint: 端點路徑
        method: HTTP 方法
        user_id: 使用者 ID（可選）
        success: 是否成功
    """
    logger = logging.getLogger(__name__)
    status = "成功" if success else "失敗"
    user_info = f" 使用者ID: {user_id}" if user_id else ""
    logger.info(f"API 呼叫 {method} {endpoint}{user_info} - {status}")


# 初始化日誌記錄
setup_app_logging()