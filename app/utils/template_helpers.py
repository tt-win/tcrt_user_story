"""
模板助手函數
提供用於 Jinja2 模板的條件渲染邏輯
"""

from typing import Optional
from app.services.user_service import UserService


async def should_show_lark_avatar(user_id: int) -> bool:
    """
    判斷是否應顯示 Lark 頭像
    
    Args:
        user_id: 使用者 ID
        
    Returns:
        bool: 如果應該顯示 Lark 頭像則返回 True，否則返回 False
    """
    try:
        lark_status = await UserService.check_lark_integration_status(user_id)
        return lark_status.get("lark_linked", False) and lark_status.get("has_lark_data", False)
    except Exception as e:
        # 如果檢查失敗，默認為不顯示
        print(f"檢查 Lark 整合狀態失敗: {e}")
        return False


async def should_show_lark_name(user_id: int) -> bool:
    """
    判斷是否應顯示 Lark 名稱
    
    Args:
        user_id: 使用者 ID
        
    Returns:
        bool: 如果應該顯示 Lark 名稱則返回 True，否則返回 False
    """
    try:
        lark_status = await UserService.check_lark_integration_status(user_id)
        return lark_status.get("lark_linked", False) and lark_status.get("has_lark_data", False)
    except Exception as e:
        # 如果檢查失敗，默認為不顯示
        print(f"檢查 Lark 整合狀態失敗: {e}")
        return False


def get_lark_display_data(user_id: int) -> dict:
    """
    獲取 Lark 顯示數據（同步版本，用於模板）
    
    Args:
        user_id: 使用者 ID
        
    Returns:
        dict: 包含 Lark 顯示相關數據的字典
    """
    # 注意：這是一個簡化的同步版本，實際實現中可能需要從快取或其他來源獲取數據
    return {
        "show_lark_elements": False,  # 默認為不顯示
        "lark_name": None,
        "lark_avatar": None
    }


# 全域模板助手函數字典
TEMPLATE_HELPERS = {
    'should_show_lark_avatar': should_show_lark_avatar,
    'should_show_lark_name': should_show_lark_name,
    'get_lark_display_data': get_lark_display_data
}