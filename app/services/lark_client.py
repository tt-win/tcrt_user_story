#!/usr/bin/env python3
"""
Lark Base Client

專注於高效的全表掃描功能：
- 快速取得所有記錄
- 批次操作
- 使用者管理
"""

import logging
import requests
import threading
import asyncio
import aiohttp
import time
from typing import Dict, List, Optional, Tuple, Any, Callable
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed


class LarkAuthManager:
    """Lark 認證管理器"""
    
    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        
        # Token 快取
        self._tenant_access_token = None
        self._token_expire_time = None
        self._token_lock = threading.Lock()
        
        # 設定日誌
        self.logger = logging.getLogger(f"{__name__}.LarkAuthManager")
        
        # API 配置
        self.auth_url = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
        self.timeout = 30
    
    def get_tenant_access_token(self, force_refresh: bool = False) -> Optional[str]:
        """取得 Tenant Access Token"""
        with self._token_lock:
            # 檢查是否需要刷新
            if (not force_refresh and 
                self._tenant_access_token and 
                self._token_expire_time and 
                datetime.now() < self._token_expire_time):
                return self._tenant_access_token
            
            # 取得新 Token
            try:
                response = requests.post(
                    self.auth_url,
                    json={
                        "app_id": self.app_id,
                        "app_secret": self.app_secret
                    },
                    timeout=self.timeout
                )
                
                if response.status_code != 200:
                    self.logger.error(f"Token 取得失敗，HTTP {response.status_code}")
                    return None
                
                result = response.json()
                
                if result.get('code') != 0:
                    self.logger.error(f"Token 取得失敗: {result.get('msg')}")
                    return None
                
                # 快取 Token
                self._tenant_access_token = result['tenant_access_token']
                expire_seconds = result.get('expire', 7200)
                self._token_expire_time = datetime.now() + timedelta(seconds=expire_seconds - 300)
                
                return self._tenant_access_token
                
            except Exception as e:
                self.logger.error(f"Token 取得異常: {e}")
                return None
    
    def is_token_valid(self) -> bool:
        """檢查 Token 是否有效"""
        return (self._tenant_access_token is not None and 
                self._token_expire_time is not None and 
                datetime.now() < self._token_expire_time)


class LarkTableManager:
    """Lark 表格管理器"""
    
    def __init__(self, auth_manager: LarkAuthManager):
        self.auth_manager = auth_manager
        
        # 快取
        self._obj_tokens = {}     # wiki_token -> obj_token
        self._cache_lock = threading.Lock()
        
        # 設定日誌
        self.logger = logging.getLogger(f"{__name__}.LarkTableManager")
        
        # API 配置
        self.base_url = "https://open.larksuite.com/open-apis"
        self.timeout = 30
    
    def get_obj_token(self, wiki_token: str) -> Optional[str]:
        """從 Wiki Token 取得 Obj Token"""
        with self._cache_lock:
            if wiki_token in self._obj_tokens:
                return self._obj_tokens[wiki_token]
        
        try:
            token = self.auth_manager.get_tenant_access_token()
            if not token:
                return None
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            url = f"{self.base_url}/wiki/v2/spaces/get_node?token={wiki_token}"
            response = requests.get(url, headers=headers, timeout=self.timeout)
            
            if response.status_code != 200:
                self.logger.error(f"Wiki Token 解析失敗，HTTP {response.status_code}")
                return None
            
            result = response.json()
            if result.get('code') != 0:
                self.logger.error(f"Wiki Token 解析失敗: {result.get('msg')}")
                return None
            
            obj_token = result['data']['node']['obj_token']
            
            # 快取結果
            with self._cache_lock:
                self._obj_tokens[wiki_token] = obj_token
            
            return obj_token
            
        except Exception as e:
            self.logger.error(f"Wiki Token 解析異常: {e}")
            return None
    
    def get_table_fields(self, obj_token: str, table_id: str) -> List[Dict[str, Any]]:
        """
        取得表格的完整欄位結構
        
        Args:
            obj_token: 應用 Token
            table_id: 表格 ID
            
        Returns:
            List[Dict]: 欄位列表，每個欄位包含 field_name, type 等資訊
        """
        try:
            token = self.auth_manager.get_tenant_access_token()
            if not token:
                return []
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            url = f"{self.base_url}/bitable/v1/apps/{obj_token}/tables/{table_id}/fields"
            response = requests.get(url, headers=headers, timeout=self.timeout)
            
            if response.status_code != 200:
                self.logger.error(f"取得表格欄位失敗，HTTP {response.status_code}: {response.text}")
                return []
            
            result = response.json()
            if result.get('code') != 0:
                self.logger.error(f"取得表格欄位失敗: {result.get('msg')}")
                return []
            
            fields = result.get('data', {}).get('items', [])
            self.logger.debug(f"取得表格 {table_id} 的 {len(fields)} 個欄位")
            return fields
            
        except Exception as e:
            self.logger.error(f"取得表格欄位異常: {e}")
            return []
    
    def get_available_field_names(self, obj_token: str, table_id: str) -> List[str]:
        """
        取得表格中所有可用的欄位名稱
        
        Args:
            obj_token: 應用 Token
            table_id: 表格 ID
            
        Returns:
            List[str]: 欄位名稱列表
        """
        fields = self.get_table_fields(obj_token, table_id)
        return [field.get('field_name', '') for field in fields if field.get('field_name')]


class LarkRecordManager:
    """Lark 記錄管理器 - 專注於全表掃描"""
    
    def __init__(self, auth_manager: LarkAuthManager):
        self.auth_manager = auth_manager
        
        # 設定日誌
        self.logger = logging.getLogger(f"{__name__}.LarkRecordManager")
        
        # API 配置
        self.base_url = "https://open.larksuite.com/open-apis"
        self.timeout = 60
        self.max_page_size = 500
        self.max_retries = 3
    
    def _make_request(self, method: str, url: str, **kwargs) -> Optional[Dict]:
        """統一的 HTTP 請求方法（帶重試與退避機制）"""
        last_exception: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                token = self.auth_manager.get_tenant_access_token()
                if not token:
                    self.logger.error("無法取得 Access Token")
                    return None

                headers = kwargs.pop('headers', {})
                headers.update({
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json'
                })

                response = requests.request(
                    method,
                    url,
                    headers=headers,
                    timeout=self.timeout,
                    **kwargs
                )

                if response.status_code != 200:
                    self.logger.error(f"API 請求失敗，HTTP {response.status_code}: {response.text}")
                    if attempt < self.max_retries and response.status_code in {429, 500, 502, 503, 504}:
                        sleep_seconds = min(2 ** attempt, 5)
                        self.logger.info(f"將於 {sleep_seconds}s 後重試 ({attempt}/{self.max_retries})")
                        time.sleep(sleep_seconds)
                        continue
                    return None

                result = response.json()

                if result.get('code') != 0:
                    error_msg = result.get('msg', 'Unknown error')
                    self.logger.error(f"API 請求失敗: {error_msg}")
                    if 'FieldNameNotFound' in error_msg or 'field' in error_msg.lower():
                        self.logger.error(f"API 完整回應: {result}")
                        self.logger.error(f"請求 URL: {url}")
                        self.logger.error(f"請求方法: {method}")
                        if method in ['POST', 'PUT'] and 'json' in kwargs:
                            request_data = kwargs.get('json', {})
                            if 'fields' in request_data:
                                self.logger.error(f"請求的欄位列表: {list(request_data['fields'].keys())}")
                                self.logger.error(f"請求的欄位資料: {request_data['fields']}")
                    if attempt < self.max_retries:
                        sleep_seconds = min(2 ** attempt, 5)
                        self.logger.info(f"將於 {sleep_seconds}s 後重試 ({attempt}/{self.max_retries})")
                        time.sleep(sleep_seconds)
                        continue
                    return None

                return result.get('data', {})

            except (requests.exceptions.SSLError, requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                last_exception = exc
                if attempt < self.max_retries:
                    sleep_seconds = min(2 ** attempt, 5)
                    self.logger.warning(
                        f"API 請求異常 (第 {attempt}/{self.max_retries} 次): {exc}，{sleep_seconds}s 後重試"
                    )
                    time.sleep(sleep_seconds)
                    continue
                self.logger.error(f"API 請求異常: {exc}")
            except Exception as exc:
                last_exception = exc
                self.logger.error(f"API 請求異常: {exc}")
                break

        if last_exception:
            self.logger.error(f"API 請求最終失敗: {last_exception}")
        return None
    
    def get_all_records(self, obj_token: str, table_id: str) -> List[Dict]:
        """
        取得表格所有記錄（高效全表掃描）
        
        Args:
            obj_token: Obj Token
            table_id: 表格 ID
            
        Returns:
            記錄列表
        """
        url = f"{self.base_url}/bitable/v1/apps/{obj_token}/tables/{table_id}/records"
        
        all_records = []
        page_token = None
        
        while True:
            params = {
                'page_size': self.max_page_size,
                'automatic_fields': True  # 包含系統自動欄位（建立時間、更新時間等）
            }
            if page_token:
                params['page_token'] = page_token
            
            
            result = self._make_request('GET', url, params=params)
            if not result:
                break
            
            records = result.get('items', [])
            all_records.extend(records)
            
            # 檢查是否還有更多記錄
            page_token = result.get('page_token')
            if not page_token or not result.get('has_more', False):
                break
        
        self.logger.info(f"全表掃描完成，共取得 {len(all_records)} 筆記錄")
        return all_records
    
    def create_record(self, obj_token: str, table_id: str, fields: Dict) -> Optional[str]:
        """創建單筆記錄"""
        url = f"{self.base_url}/bitable/v1/apps/{obj_token}/tables/{table_id}/records"
        
        data = {'fields': fields}
        result = self._make_request('POST', url, json=data)
        
        if result:
            record = result.get('record', {})
            return record.get('record_id')
        return None
    
    def update_record(self, obj_token: str, table_id: str, record_id: str, fields: Dict) -> bool:
        """更新單筆記錄"""
        url = f"{self.base_url}/bitable/v1/apps/{obj_token}/tables/{table_id}/records/{record_id}"
        
        data = {'fields': fields}
        result = self._make_request('PUT', url, json=data)
        return result is not None
    
    def delete_record(self, obj_token: str, table_id: str, record_id: str) -> bool:
        """刪除單筆記錄"""
        url = f"{self.base_url}/bitable/v1/apps/{obj_token}/tables/{table_id}/records/{record_id}"
        
        result = self._make_request('DELETE', url)
        return result is not None
    
    def batch_delete_records(self, obj_token: str, table_id: str, record_ids: List[str]) -> Tuple[bool, int, List[str]]:
        """批次刪除記錄"""
        if not record_ids:
            return True, 0, []
        
        max_batch_size = 500
        deleted_count = 0
        error_messages = []
        
        # 分批處理
        for i in range(0, len(record_ids), max_batch_size):
            batch_ids = record_ids[i:i + max_batch_size]
            
            url = f"{self.base_url}/bitable/v1/apps/{obj_token}/tables/{table_id}/records/batch_delete"
            data = {'records': batch_ids}
            
            result = self._make_request('POST', url, json=data)
            
            if result:
                # 成功刪除的記錄
                deleted_records = result.get('records', [])
                deleted_count += len(deleted_records)
            else:
                error_messages.append(f"批次 {i//max_batch_size + 1} 刪除失敗")
        
        overall_success = len(error_messages) == 0
        self.logger.info(f"批次刪除完成，成功: {deleted_count}, 失敗: {len(error_messages)}")
        
        return overall_success, deleted_count, error_messages
    
    def batch_create_records(self, obj_token: str, table_id: str, 
                           records_data: List[Dict]) -> Tuple[bool, List[str], List[str]]:
        """批次創建記錄"""
        if not records_data:
            return True, [], []
        
        max_batch_size = 500
        success_ids = []
        error_messages = []
        
        # 分批處理
        for i in range(0, len(records_data), max_batch_size):
            batch_data = records_data[i:i + max_batch_size]
            
            # 準備批次數據
            records = [{'fields': fields} for fields in batch_data]
            data = {'records': records}
            
            url = f"{self.base_url}/bitable/v1/apps/{obj_token}/tables/{table_id}/records/batch_create"
            result = self._make_request('POST', url, json=data)
            
            if result:
                records = result.get('records', [])
                batch_ids = [record.get('record_id') for record in records if record.get('record_id')]
                success_ids.extend(batch_ids)
            else:
                error_messages.append(f"批次 {i//max_batch_size + 1} 創建失敗")
        
        overall_success = len(error_messages) == 0
        self.logger.info(f"批次創建完成，成功: {len(success_ids)}, 失敗: {len(error_messages)}")
        
        return overall_success, success_ids, error_messages
    
    def parallel_update_records(self, obj_token: str, table_id: str, 
                              updates: List[Dict], 
                              max_workers: int = 10,
                              progress_callback: Optional[Callable] = None) -> Tuple[bool, int, List[str]]:
        """並行批次更新記錄
        
        Args:
            obj_token: Object Token
            table_id: 表格 ID
            updates: 更新資料列表 [{'record_id': str, 'fields': dict}, ...]
            max_workers: 最大並行工作者數量
            progress_callback: 進度回調函數 (current, total, success, errors)
        
        Returns:
            (overall_success, success_count, error_messages)
        """
        if not updates:
            return True, 0, []
        
        success_count = 0
        error_messages = []
        completed_count = 0
        
        def update_single_record(update_data: Dict) -> Tuple[bool, str]:
            """更新單筆記錄的內部函數"""
            try:
                record_id = update_data['record_id']
                fields = update_data['fields']
                
                success = self.update_record(obj_token, table_id, record_id, fields)
                if success:
                    return True, ""
                else:
                    return False, f"記錄 {record_id} 更新失敗"
            except Exception as e:
                record_id = update_data.get('record_id', 'unknown')
                return False, f"記錄 {record_id} 更新異常: {str(e)}"
        
        # 使用 ThreadPoolExecutor 進行並行處理
        self.logger.info(f"開始並行更新 {len(updates)} 筆記錄，使用 {max_workers} 個工作者")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任務
            future_to_update = {
                executor.submit(update_single_record, update): update 
                for update in updates
            }
            
            # 處理完成的任務
            for future in as_completed(future_to_update):
                completed_count += 1
                
                try:
                    success, error_msg = future.result()
                    if success:
                        success_count += 1
                    else:
                        error_messages.append(error_msg)
                except Exception as e:
                    update_data = future_to_update[future]
                    record_id = update_data.get('record_id', 'unknown')
                    error_messages.append(f"記錄 {record_id} 處理異常: {str(e)}")
                
                # 調用進度回調
                if progress_callback:
                    try:
                        progress_callback(completed_count, len(updates), success_count, len(error_messages))
                    except Exception as e:
                        self.logger.warning(f"進度回調異常: {e}")
        
        overall_success = len(error_messages) == 0
        self.logger.info(f"並行更新完成，成功: {success_count}/{len(updates)}, 失敗: {len(error_messages)}")
        
        return overall_success, success_count, error_messages


class LarkUserManager:
    """Lark 使用者管理器"""
    
    def __init__(self, auth_manager: LarkAuthManager):
        self.auth_manager = auth_manager
        
        # 設定日誌
        self.logger = logging.getLogger(f"{__name__}.LarkUserManager")
        
        # API 配置
        self.base_url = "https://open.larksuite.com/open-apis"
        self.timeout = 30
        
        # 使用者快取
        self._user_cache = {}  # email -> user_info
        self._all_users_cache = []  # 完整用戶列表快取
        self._users_index = {}  # 用戶搜尋索引
        self._cache_timestamp = None  # 快取時間戳
        self._cache_lock = threading.Lock()
        
        # 快取設定
        self.cache_expiry_hours = 24  # 快取24小時過期
    
    def get_user_by_email(self, email: str) -> Optional[Dict]:
        """根據 Email 取得使用者資訊"""
        with self._cache_lock:
            if email in self._user_cache:
                return self._user_cache[email]
        
        try:
            token = self.auth_manager.get_tenant_access_token()
            if not token:
                return None
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            url = f"{self.base_url}/contact/v3/users/batch_get_id"
            data = {'emails': [email]}
            
            response = requests.post(url, json=data, headers=headers, timeout=self.timeout)
            
            if response.status_code != 200:
                return None
            
            result = response.json()
            if result.get('code') != 0:
                return None
            
            # 提取使用者資訊
            data_section = result.get('data', {})
            user_list = data_section.get('user_list', [])
            
            if user_list:
                user_info = user_list[0]
                user_id = user_info.get('user_id')
                
                if not user_id:
                    return None
                
                # 轉換為統一格式
                result = {
                    'id': user_id,
                    'name': user_info.get('name', email.split('@')[0]),
                    'email': email
                }
                
                # 快取結果
                with self._cache_lock:
                    self._user_cache[email] = result
                return result
            
            return None
                
        except Exception as e:
            self.logger.error(f"使用者查詢異常: {e}")
            return None
    
    def _is_cache_expired(self) -> bool:
        """檢查快取是否過期"""
        if not self._cache_timestamp:
            return True
        
        from datetime import datetime, timedelta
        expiry_time = self._cache_timestamp + timedelta(hours=self.cache_expiry_hours)
        return datetime.now() > expiry_time
    
    def fetch_all_users(self, force_refresh: bool = False) -> List[Dict]:
        """
        拉取所有用戶列表（支援快取）
        
        Args:
            force_refresh: 強制刷新快取
            
        Returns:
            List[Dict]: 用戶列表
        """
        with self._cache_lock:
            # 檢查快取是否有效
            if not force_refresh and self._all_users_cache and not self._is_cache_expired():
                self.logger.info(f"使用快取的用戶列表，共 {len(self._all_users_cache)} 個用戶")
                return self._all_users_cache.copy()
        
        self.logger.info("開始拉取所有用戶列表...")
        
        try:
            token = self.auth_manager.get_tenant_access_token()
            if not token:
                self.logger.error("無法獲取 access token")
                return []
            
            import requests
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            all_users = []
            page_token = None
            page_count = 0
            
            while True:
                page_count += 1
                self.logger.debug(f"拉取第 {page_count} 頁用戶資料...")
                
                url = f"{self.base_url}/contact/v3/users"
                params = {
                    'page_size': 100,  # 每頁最大數量
                    'user_id_type': 'user_id'
                }
                
                if page_token:
                    params['page_token'] = page_token
                
                response = requests.get(url, headers=headers, params=params, timeout=self.timeout)
                
                if response.status_code != 200:
                    self.logger.error(f"拉取用戶列表失敗，HTTP {response.status_code}: {response.text}")
                    break
                
                result = response.json()
                
                if result.get('code') != 0:
                    self.logger.error(f"拉取用戶列表失敗: {result.get('msg')}")
                    # 如果是權限問題，返回空列表但不報錯
                    if "Access denied" in str(result.get('msg', '')):
                        self.logger.warning("Contact API 權限不足，無法拉取用戶列表")
                    break
                
                # 提取用戶資料
                page_users = result.get('data', {}).get('items', [])
                all_users.extend(page_users)
                
                self.logger.debug(f"第 {page_count} 頁獲得 {len(page_users)} 個用戶，累計 {len(all_users)} 個")
                
                # 檢查是否有下一頁
                has_more = result.get('data', {}).get('has_more', False)
                page_token = result.get('data', {}).get('page_token')
                
                if not has_more or not page_token:
                    break
            
            if all_users:
                self.logger.info(f"成功拉取 {len(all_users)} 個用戶")
                
                # 更新快取
                with self._cache_lock:
                    self._all_users_cache = all_users
                    self._users_index = self._create_search_index(all_users)
                    from datetime import datetime
                    self._cache_timestamp = datetime.now()
                
                return all_users
            else:
                self.logger.warning("未拉取到任何用戶資料")
                return []
                
        except Exception as e:
            self.logger.error(f"拉取用戶列表異常: {e}")
            return []
    
    def _create_search_index(self, users: List[Dict]) -> Dict:
        """創建搜尋索引"""
        index = {
            'by_id': {},
            'by_email': {},
            'by_name': {},
            'search_terms': {}
        }
        
        for user in users:
            user_id = user.get('user_id')
            email = user.get('email')
            name = user.get('name', '')
            
            if user_id:
                index['by_id'][user_id] = user
            
            if email:
                index['by_email'][email.lower()] = user
            
            if name:
                index['by_name'][name.lower()] = user
            
            # 建立搜尋詞索引
            search_terms = []
            if name:
                search_terms.extend(name.lower().split())
            if email:
                search_terms.append(email.lower())
                search_terms.append(email.lower().split('@')[0])
            
            for term in search_terms:
                if term not in index['search_terms']:
                    index['search_terms'][term] = []
                index['search_terms'][term].append(user)
        
        return index
    
    def search_users(self, query: str, limit: int = 50) -> List[Dict]:
        """
        搜尋用戶（本地搜尋）
        
        Args:
            query: 搜尋關鍵字
            limit: 結果數量限制
            
        Returns:
            List[Dict]: 搜尋結果
        """
        if not query or not query.strip():
            return []
        
        # 確保有用戶資料
        if not self._all_users_cache:
            users = self.fetch_all_users()
            if not users:
                return []
        
        query = query.lower().strip()
        results = []
        seen_ids = set()  # 避免重複結果
        
        with self._cache_lock:
            # 方法1: 精確匹配（優先級最高）
            if query in self._users_index.get('by_email', {}):
                user = self._users_index['by_email'][query]
                if user.get('user_id') not in seen_ids:
                    results.append(user)
                    seen_ids.add(user.get('user_id'))
            
            if query in self._users_index.get('by_name', {}):
                user = self._users_index['by_name'][query]
                if user.get('user_id') not in seen_ids:
                    results.append(user)
                    seen_ids.add(user.get('user_id'))
            
            # 方法2: 搜尋詞匹配
            for term, term_users in self._users_index.get('search_terms', {}).items():
                if query in term:
                    for user in term_users:
                        if user.get('user_id') not in seen_ids and len(results) < limit:
                            results.append(user)
                            seen_ids.add(user.get('user_id'))
            
            # 方法3: 模糊匹配（如果結果不夠）
            if len(results) < limit:
                for user in self._all_users_cache:
                    if len(results) >= limit:
                        break
                    
                    if user.get('user_id') in seen_ids:
                        continue
                    
                    name = user.get('name', '').lower()
                    email = user.get('email', '').lower()
                    
                    if query in name or query in email:
                        results.append(user)
                        seen_ids.add(user.get('user_id'))
        
        self.logger.debug(f"搜尋 '{query}' 找到 {len(results)} 個結果")
        return results[:limit]
    
    def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        """根據用戶ID獲取用戶資訊"""
        # 先檢查索引快取
        if self._users_index and user_id in self._users_index.get('by_id', {}):
            return self._users_index['by_id'][user_id]
        
        # 直接呼叫單個用戶 API
        try:
            token = self.auth_manager.get_tenant_access_token()
            if not token:
                self.logger.error("無法獲取 access token")
                return None
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            url = f"{self.base_url}/contact/v3/users/{user_id}"
            response = requests.get(url, headers=headers, timeout=self.timeout)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('code') == 0:
                    user_data = result.get('data', {})
                    if user_data:
                        # 更新快取
                        with self._cache_lock:
                            if 'by_id' not in self._users_index:
                                self._users_index['by_id'] = {}
                            self._users_index['by_id'][user_id] = user_data
                        
                        self.logger.debug(f"成功獲取單個用戶: {user_id}")
                        return user_data
                    else:
                        self.logger.warning(f"Lark API 返回空用戶數據: {user_id}")
                else:
                    self.logger.warning(f"Lark API 錯誤: {result.get('msg', 'Unknown error')}")
            else:
                self.logger.error(f"獲取單個用戶失敗，HTTP {response.status_code}: {response.text}")
        except Exception as e:
            self.logger.error(f"獲取單個用戶異常: {e}")
        
        # Fallback 到拉取所有用戶
        self.logger.info(f"單個用戶 API 失敗，回退到拉取所有用戶列表查找 {user_id}")
        users = self.fetch_all_users()
        if users and self._users_index:
            return self._users_index.get('by_id', {}).get(user_id)
        
        return None
    
    def format_user_for_frontend(self, user: Dict) -> Dict:
        """格式化用戶資料供前端使用"""
        avatar_info = user.get('avatar', {})
        avatar = (avatar_info.get('avatar_240') or
                 avatar_info.get('avatar_640') or
                 avatar_info.get('avatar_origin') or
                 avatar_info.get('avatar_72', ''))
        
        return {
            'id': user.get('user_id'),
            'name': user.get('name', ''),
            'email': user.get('email', ''),
            'avatar': avatar,
            'department_name': self._get_department_name(user.get('department_ids', [])),
            'status': user.get('status', {}).get('is_activated', True),
            'display_name': f"{user.get('name', '')} ({user.get('email', '')})" if user.get('email') else user.get('name', '')
        }
    
    def _get_department_name(self, department_ids: List[str]) -> str:
        """獲取部門名稱（簡化實現）"""
        # 這裡可以後續擴展部門資料的拉取邏輯
        if department_ids:
            return f"部門 {len(department_ids)} 個"
        return "未分配部門"
    
    def get_users_for_frontend(self, query: str = None, limit: int = 50) -> List[Dict]:
        """
        獲取格式化的用戶列表供前端使用
        
        Args:
            query: 搜尋關鍵字（可選）
            limit: 結果數量限制
            
        Returns:
            List[Dict]: 格式化的用戶列表
        """
        if query:
            users = self.search_users(query, limit)
        else:
            # 返回前N個用戶
            users = self.fetch_all_users()[:limit] if self._all_users_cache else self.fetch_all_users()[:limit]
        
        return [self.format_user_for_frontend(user) for user in users]
    
    def clear_user_cache(self):
        """清空用戶快取"""
        with self._cache_lock:
            self._user_cache.clear()
            self._all_users_cache.clear()
            self._users_index.clear()
            self._cache_timestamp = None
        
        self.logger.info("用戶快取已清空")


class LarkClient:
    """
    Lark Base Client
    
    專注於高效的全表掃描功能
    """
    
    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        
        # 設定日誌
        self.logger = logging.getLogger(f"{__name__}.LarkClient")
        
        # 初始化管理器
        self.auth_manager = LarkAuthManager(app_id, app_secret)
        self.table_manager = LarkTableManager(self.auth_manager)
        self.record_manager = LarkRecordManager(self.auth_manager)
        self.user_manager = LarkUserManager(self.auth_manager)
        
        # 當前 Wiki Token
        self._current_wiki_token = None
        self._current_obj_token = None
        
        self.logger.info("Lark Client 初始化完成")
    
    def set_wiki_token(self, wiki_token: str) -> bool:
        """設定當前使用的 Wiki Token"""
        self._current_wiki_token = wiki_token
        
        # 立即解析 Obj Token
        obj_token = self.table_manager.get_obj_token(wiki_token)
        if obj_token:
            self._current_obj_token = obj_token
            self.logger.info(f"Wiki Token 設定成功")
            return True
        else:
            self.logger.error(f"Wiki Token 設定失敗")
            return False
    
    def test_connection(self, wiki_token: str = None) -> bool:
        """測試連接"""
        try:
            # 測試認證
            token = self.auth_manager.get_tenant_access_token()
            if not token:
                return False
            
            # 如果提供了 wiki_token，測試 Obj Token 解析
            if wiki_token:
                obj_token = self.table_manager.get_obj_token(wiki_token)
                if not obj_token:
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"連接測試異常: {e}")
            return False
    
    def get_all_records(self, table_id: str, wiki_token: str = None) -> List[Dict]:
        """
        取得表格所有記錄（主要功能）
        
        Args:
            table_id: 表格 ID
            wiki_token: Wiki Token（可選，使用預設值）
            
        Returns:
            記錄列表
        """
        obj_token = self._get_obj_token(wiki_token)
        if not obj_token:
            return []
        
        return self.record_manager.get_all_records(obj_token, table_id)
    
    def create_record(self, table_id: str, fields: Dict, wiki_token: str = None) -> Optional[str]:
        """創建單筆記錄"""
        obj_token = self._get_obj_token(wiki_token)
        if not obj_token:
            return None
        
        return self.record_manager.create_record(obj_token, table_id, fields)
    
    def update_record(self, table_id: str, record_id: str, fields: Dict,
                     wiki_token: str = None) -> bool:
        """更新單筆記錄"""
        obj_token = self._get_obj_token(wiki_token)
        if not obj_token:
            return False
        
        return self.record_manager.update_record(obj_token, table_id, record_id, fields)
    
    def delete_record(self, table_id: str, record_id: str, wiki_token: str = None) -> bool:
        """刪除單筆記錄"""
        obj_token = self._get_obj_token(wiki_token)
        if not obj_token:
            return False
        
        return self.record_manager.delete_record(obj_token, table_id, record_id)
    
    def batch_delete_records(self, table_id: str, record_ids: List[str], 
                           wiki_token: str = None) -> Tuple[bool, int, List[str]]:
        """批次刪除記錄"""
        obj_token = self._get_obj_token(wiki_token)
        if not obj_token:
            return False, 0, ['無法取得 Obj Token']
        
        return self.record_manager.batch_delete_records(obj_token, table_id, record_ids)
    
    def get_table_fields(self, table_id: str, wiki_token: str = None) -> List[Dict[str, Any]]:
        """
        取得表格的完整欄位結構
        
        Args:
            table_id: 表格 ID
            wiki_token: Wiki Token（可選，使用預設值）
            
        Returns:
            List[Dict]: 欄位列表，每個欄位包含 field_name, type 等資訊
        """
        obj_token = self._get_obj_token(wiki_token)
        if not obj_token:
            return []
        
        return self.table_manager.get_table_fields(obj_token, table_id)
    
    def get_available_field_names(self, table_id: str, wiki_token: str = None) -> List[str]:
        """
        取得表格中所有可用的欄位名稱
        
        Args:
            table_id: 表格 ID
            wiki_token: Wiki Token（可選，使用預設值）
            
        Returns:
            List[str]: 欄位名稱列表
        """
        obj_token = self._get_obj_token(wiki_token)
        if not obj_token:
            return []
        
        return self.table_manager.get_available_field_names(obj_token, table_id)
    
    def batch_create_records(self, table_id: str, records: List[Dict],
                           wiki_token: str = None) -> Tuple[bool, List[str], List[str]]:
        """批次創建記錄"""
        obj_token = self._get_obj_token(wiki_token)
        if not obj_token:
            return False, [], ['無法取得 Obj Token']
        
        return self.record_manager.batch_create_records(obj_token, table_id, records)
    
    def parallel_update_records(self, table_id: str, updates: List[Dict],
                              max_workers: int = 10,
                              progress_callback: Optional[Callable] = None,
                              wiki_token: str = None) -> Tuple[bool, int, List[str]]:
        """並行批次更新記錄
        
        Args:
            table_id: 表格 ID
            updates: 更新資料列表 [{'record_id': str, 'fields': dict}, ...]
            max_workers: 最大並行工作者數量（建議 5-15）
            progress_callback: 進度回調函數 (current, total, success, errors)
            wiki_token: Wiki Token（可選，使用預設值）
        
        Returns:
            (overall_success, success_count, error_messages)
        """
        obj_token = self._get_obj_token(wiki_token)
        if not obj_token:
            return False, 0, ['無法取得 Obj Token']
        
        return self.record_manager.parallel_update_records(
            obj_token, table_id, updates, max_workers, progress_callback
        )
    
    def get_user_by_email(self, email: str) -> Optional[Dict]:
        """根據 Email 取得使用者資訊"""
        return self.user_manager.get_user_by_email(email)
    
    def _get_obj_token(self, wiki_token: str = None) -> Optional[str]:
        """取得 Obj Token（內部方法）"""
        if wiki_token:
            return self.table_manager.get_obj_token(wiki_token)
        elif self._current_obj_token:
            return self._current_obj_token
        elif self._current_wiki_token:
            obj_token = self.table_manager.get_obj_token(self._current_wiki_token)
            if obj_token:
                self._current_obj_token = obj_token
            return obj_token
        else:
            self.logger.error("沒有可用的 Wiki Token")
            return None
    
    def get_performance_stats(self) -> Dict:
        """取得效能統計資訊"""
        return {
            'auth_token_valid': self.auth_manager.is_token_valid(),
            'obj_token_cache_size': len(self.table_manager._obj_tokens),
            'user_cache_size': len(self.user_manager._user_cache),
            'client_type': 'LarkClient',
            'features': ['全表掃描', '批次操作', '使用者管理']
        }
    
    def clear_caches(self):
        """清理所有快取"""
        with self.table_manager._cache_lock:
            self.table_manager._obj_tokens.clear()
        
        # 使用 user_manager 的清理方法
        self.user_manager.clear_user_cache()
        
        self.logger.info("所有快取已清理")
    
    def upload_file_to_drive(self, file_content: bytes, file_name: str, wiki_token: str = None) -> Optional[str]:
        """上傳檔案到 Lark Drive 並返回 file_token"""
        obj_token = self._get_obj_token(wiki_token)
        if not obj_token:
            return None
        
        try:
            token = self.auth_manager.get_tenant_access_token()
            if not token:
                self.logger.error("無法取得 Access Token")
                return None
            
            headers = {
                'Authorization': f'Bearer {token}'
            }
            
            # 準備 multipart/form-data
            files = {
                'file': (file_name, file_content, 'application/octet-stream')
            }
            
            data = {
                'file_name': file_name,
                'parent_type': 'bitable_file',  # 正確的 bitable 文件上傳類型
                'parent_node': obj_token,       # 使用 bitable 的 app_token
                'size': str(len(file_content))
            }
            
            url = f"{self.record_manager.base_url}/drive/v1/medias/upload_all"  # 正確的素材上傳端點
            response = requests.post(
                url, 
                headers=headers, 
                files=files, 
                data=data,
                timeout=self.record_manager.timeout
            )
            
            if response.status_code != 200:
                self.logger.error(f"檔案上傳失敗，HTTP {response.status_code}: {response.text}")
                return None
            
            result = response.json()
            
            if result.get('code') != 0:
                error_msg = result.get('msg', 'Unknown error')
                self.logger.error(f"檔案上傳失敗: {error_msg}")
                return None
            
            file_token = result.get('data', {}).get('file_token')
            if file_token:
                self.logger.info(f"檔案上傳成功，file_token: {file_token}")
                return file_token
            else:
                self.logger.error("檔案上傳成功但未取得到 file_token")
                return None
                
        except Exception as e:
            self.logger.error(f"檔案上傳異常: {e}")
            return None
    
    def update_record_attachment(self, table_id: str, record_id: str, field_name: str, 
                               file_tokens: List[str], wiki_token: str = None) -> bool:
        """更新記錄的附件欄位"""
        obj_token = self._get_obj_token(wiki_token)
        if not obj_token:
            return False
        
        try:
            # 準備附件欄位資料
            attachment_data = [{'file_token': token} for token in file_tokens]
            
            # 準備更新資料
            fields = {
                field_name: attachment_data
            }
            
            # 呼叫更新記錄 API
            success = self.record_manager.update_record(obj_token, table_id, record_id, fields)
            
            if success:
                self.logger.info(f"附件欄位更新成功，記錄: {record_id}，附件數: {len(file_tokens)}")
            else:
                self.logger.error(f"附件欄位更新失敗，記錄: {record_id}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"附件欄位更新異常: {e}")
            return False
    
    def upload_and_attach_file(self, table_id: str, record_id: str, field_name: str,
                             file_content: bytes, file_name: str, append: bool = True,
                             wiki_token: str = None) -> bool:
        """
        上傳檔案並附加到記錄的附件欄位
        
        Args:
            table_id: 表格 ID
            record_id: 記錄 ID
            field_name: 附件欄位名稱
            file_content: 檔案內容（二進位）
            file_name: 檔案名稱
            append: 是否追加到現有附件（True）或替換全部附件（False）
            wiki_token: Wiki Token（可選）
            
        Returns:
            bool: 是否成功
        """
        obj_token = self._get_obj_token(wiki_token)
        if not obj_token:
            return False
        
        try:
            # 步驟 1: 上傳檔案到 Lark Drive
            file_token = self.upload_file_to_drive(file_content, file_name, wiki_token)
            if not file_token:
                return False
            
            # 步驟 2: 取得現有附件（如果是追加模式）
            existing_file_tokens = []
            if append:
                # 取得現有記錄
                records = self.get_all_records(table_id, wiki_token)
                target_record = None
                for record in records:
                    if record.get('record_id') == record_id:
                        target_record = record
                        break
                
                if target_record:
                    existing_attachments = target_record.get('fields', {}).get(field_name, [])
                    if isinstance(existing_attachments, list):
                        existing_file_tokens = [att.get('file_token') for att in existing_attachments 
                                              if att.get('file_token')]
            
            # 步驟 3: 準備完整的附件列表
            all_file_tokens = existing_file_tokens + [file_token]
            
            # 步驟 4: 更新記錄的附件欄位
            success = self.update_record_attachment(table_id, record_id, field_name, 
                                                  all_file_tokens, wiki_token)
            
            if success:
                self.logger.info(f"檔案上傳並附加成功，檔案: {file_name}")
            else:
                self.logger.error(f"檔案上傳成功但附加到記錄失敗，檔案: {file_name}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"檔案上傳並附加異常: {e}")
            return False


# 向後相容
LarkBaseClient = LarkClient
