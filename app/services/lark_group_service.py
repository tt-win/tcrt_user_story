"""
Lark 群組查詢服務

提供群組列表查詢功能，並包含簡單快取機制
"""

import requests
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from app.config import get_settings
import time

logger = logging.getLogger(__name__)

# 簡單的記憶體快取
_cache = {}
_cache_ttl = 60  # 60 秒 TTL

class LarkGroupService:
    def __init__(self):
        self.settings = get_settings()
    
    def _get_tenant_access_token(self) -> Optional[str]:
        """
        取得 tenant_access_token
        
        Returns:
            access token 或 None (如果失敗)
        """
        url = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal/"
        payload = {
            "app_id": self.settings.lark.app_id,
            "app_secret": self.settings.lark.app_secret
        }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            
            result = response.json()
            if result.get("code") == 0:
                return result.get("tenant_access_token")
            else:
                logger.error(f"取得 tenant_access_token 失敗: {result}")
                return None
                
        except Exception as e:
            logger.error(f"取得 tenant_access_token 時發生錯誤: {e}")
            return None
    
    def _fetch_chat_list(self, token: str) -> List[Dict]:
        """
        取得群組列表
        
        Args:
            token: tenant_access_token
            
        Returns:
            群組列表
        """
        url = "https://open.larksuite.com/open-apis/im/v1/chats"
        headers = {"Authorization": f"Bearer {token}"}
        
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            result = response.json()
            if result.get("code") == 0:
                return result.get("data", {}).get("items", [])
            else:
                logger.error(f"取得群組列表失敗: {result}")
                return []
                
        except Exception as e:
            logger.error(f"取得群組列表時發生錯誤: {e}")
            return []
    
    def list_groups(self, query: Optional[str] = None) -> List[Dict[str, str]]:
        """
        列出 Lark 群組，支援關鍵字搜尋和快取
        
        Args:
            query: 搜尋關鍵字（name 包含），大小寫不敏感
            
        Returns:
            群組列表 [{"chat_id": "oc_xxx", "name": "群組名稱"}]
        """
        cache_key = f"lark_groups_{query or 'all'}"
        now = datetime.now()
        
        # 檢查快取
        if cache_key in _cache:
            cache_entry = _cache[cache_key]
            if now < cache_entry['expires']:
                logger.debug(f"使用快取的群組列表: {cache_key}")
                return cache_entry['data']
        
        # 取得 access token
        token = self._get_tenant_access_token()
        if not token:
            logger.error("無法取得 access token，返回空列表")
            return []
        
        # 取得群組列表
        raw_groups = self._fetch_chat_list(token)
        if not raw_groups:
            logger.warning("未取得任何群組")
            return []
        
        # 轉換格式
        groups = []
        for chat in raw_groups:
            chat_id = chat.get('chat_id', '')
            name = chat.get('name', '')
            
            if chat_id and name:
                groups.append({
                    'chat_id': chat_id,
                    'name': name
                })
        
        # 過濾搜尋結果
        if query:
            query_lower = query.lower()
            filtered_groups = [
                group for group in groups 
                if query_lower in group['name'].lower()
            ]
        else:
            filtered_groups = groups
        
        # 更新快取
        _cache[cache_key] = {
            'data': filtered_groups,
            'expires': now + timedelta(seconds=_cache_ttl)
        }
        
        # 清理過期快取
        self._cleanup_cache()
        
        logger.info(f"取得 {len(filtered_groups)} 個群組（查詢: {query or 'all'}）")
        return filtered_groups
    
    def _cleanup_cache(self):
        """清理過期的快取項目"""
        now = datetime.now()
        expired_keys = [
            key for key, entry in _cache.items()
            if now >= entry['expires']
        ]
        
        for key in expired_keys:
            del _cache[key]
        
        if expired_keys:
            logger.debug(f"清理了 {len(expired_keys)} 個過期快取項目")


# 全域服務實例
_lark_group_service = None

def get_lark_group_service() -> LarkGroupService:
    """取得 Lark 群組服務實例"""
    global _lark_group_service
    if _lark_group_service is None:
        _lark_group_service = LarkGroupService()
    return _lark_group_service
