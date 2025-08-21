"""
TCG 快取管理器 - 伺服器端快取機制

提供高效的 TCG 資料快取，減少對 Lark API 的頻繁請求
"""

import time
import logging
from typing import List, Dict, Optional, Any
from threading import Lock
from app.services.lark_client import LarkClient


class TCGCacheManager:
    """TCG 快取管理器"""
    
    def __init__(self, cache_ttl: int = 3600):  # 預設快取 1 小時
        self.cache_ttl = cache_ttl  # 快取過期時間（秒）
        self.cache_lock = Lock()    # 執行緒鎖
        self.logger = logging.getLogger(__name__)
        
        # 快取資料
        self._cache_data: List[Dict] = []
        self._cache_timestamp: float = 0
        self._is_loading: bool = False
        
        # Lark 配置
        self.lark_client = None
        self.tcg_wiki_token = "Q4XxwaS2Cif80DkAku9lMKuAgof"
        self.tcg_table_id = "tblcK6eF3yQCuwwl"
    
    def _init_lark_client(self) -> bool:
        """初始化 Lark 客戶端"""
        if self.lark_client:
            return True
            
        try:
            self.lark_client = LarkClient(
                app_id="cli_a8d1077685be102f",
                app_secret="***REMOVED***"
            )
            
            if not self.lark_client.set_wiki_token(self.tcg_wiki_token):
                self.logger.error("無法設定 Wiki Token")
                return False
                
            return True
        except Exception as e:
            self.logger.error(f"初始化 Lark 客戶端失敗: {e}")
            return False
    
    def _is_cache_valid(self) -> bool:
        """檢查快取是否有效"""
        if not self._cache_data:
            return False
            
        if self._cache_timestamp == 0:
            return False
            
        # 檢查是否過期
        current_time = time.time()
        return (current_time - self._cache_timestamp) < self.cache_ttl
    
    def _load_tcg_data_from_lark(self) -> List[Dict]:
        """從 Lark 載入 TCG 資料"""
        if not self._init_lark_client():
            raise Exception("無法初始化 Lark 客戶端")
        
        self.logger.info("開始從 Lark 載入 TCG 資料...")
        start_time = time.time()
        
        # 從 Lark 表格取得資料（只取得必要欄位）
        records = self.lark_client.get_all_records(
            self.tcg_table_id, 
            field_names=['TCG Tickets']
        )
        
        tcg_options = []
        for record in records:
            fields = record.get('fields', {})
            record_id = record.get('record_id', '')
            
            # 只處理 TCG Tickets 欄位
            tcg_tickets = fields.get('TCG Tickets', '')
            
            # 解析 TCG Tickets 超連結格式
            tcg_number = self._extract_tcg_number(tcg_tickets)
            
            if tcg_number:
                tcg_options.append({
                    'record_id': record_id,
                    'tcg_number': tcg_number,
                    'title': tcg_number,
                    'display_text': tcg_number
                })
        
        load_time = time.time() - start_time
        self.logger.info(f"TCG 資料載入完成: {len(tcg_options)} 筆，耗時 {load_time:.2f} 秒")
        
        return tcg_options
    
    def _extract_tcg_number(self, tcg_tickets: Any) -> Optional[str]:
        """解析 TCG Tickets 欄位，提取 TCG 編號"""
        if not tcg_tickets:
            return None
            
        if isinstance(tcg_tickets, str):
            return tcg_tickets
        elif isinstance(tcg_tickets, dict):
            return tcg_tickets.get('text', '') or tcg_tickets.get('link', '')
        elif isinstance(tcg_tickets, list) and len(tcg_tickets) > 0:
            first_ticket = tcg_tickets[0]
            if isinstance(first_ticket, dict):
                return first_ticket.get('text', '') or first_ticket.get('link', '')
            else:
                return str(first_ticket)
        
        return None
    
    def get_tcg_options(self, keyword: str = "", limit: int = 1000, offset: int = 0) -> Dict[str, Any]:
        """
        取得 TCG 選項資料
        
        Args:
            keyword: 搜尋關鍵字
            limit: 回傳筆數
            offset: 偏移量
            
        Returns:
            包含 results 和 total 的字典
        """
        with self.cache_lock:
            # 檢查快取是否有效
            if not self._is_cache_valid() and not self._is_loading:
                self._is_loading = True
                try:
                    # 重新載入快取
                    self._cache_data = self._load_tcg_data_from_lark()
                    self._cache_timestamp = time.time()
                except Exception as e:
                    self.logger.error(f"載入 TCG 資料失敗: {e}")
                    self._cache_data = []
                    self._cache_timestamp = 0
                finally:
                    self._is_loading = False
            
            # 從快取中搜尋資料
            filtered_data = []
            if keyword:
                keyword_lower = keyword.lower()
                filtered_data = [
                    item for item in self._cache_data
                    if keyword_lower in item['tcg_number'].lower()
                ]
            else:
                filtered_data = self._cache_data.copy()
            
            # 應用 offset 和 limit
            total = len(filtered_data)
            if offset > 0:
                filtered_data = filtered_data[offset:]
            if limit > 0:
                filtered_data = filtered_data[:limit]
            
            return {
                'results': filtered_data,
                'total': total,
                'cached': self._is_cache_valid(),
                'cache_timestamp': self._cache_timestamp
            }
    
    def refresh_cache(self) -> bool:
        """強制重新整理快取"""
        with self.cache_lock:
            if self._is_loading:
                return False  # 正在載入中，不重複載入
                
            self._is_loading = True
            try:
                self._cache_data = self._load_tcg_data_from_lark()
                self._cache_timestamp = time.time()
                return True
            except Exception as e:
                self.logger.error(f"重新整理快取失敗: {e}")
                return False
            finally:
                self._is_loading = False
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """取得快取統計資訊"""
        with self.cache_lock:
            return {
                'total_records': len(self._cache_data),
                'cache_timestamp': self._cache_timestamp,
                'is_valid': self._is_cache_valid(),
                'is_loading': self._is_loading,
                'cache_ttl': self.cache_ttl
            }


# 全域快取管理器實例
tcg_cache_manager = TCGCacheManager()