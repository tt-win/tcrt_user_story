import logging
import requests
import json
from typing import Dict, List, Any, Optional
from requests.auth import HTTPBasicAuth
from ..config import settings


class JiraAuthManager:
    """JIRA 認證管理器"""
    
    def __init__(self, server_url: str = None, username: str = None, api_token: str = None):
        self.server_url = (server_url or settings.jira.server_url).rstrip('/')
        self.username = username or settings.jira.username
        self.api_token = api_token or settings.jira.api_token
        
        # 設定日誌
        self.logger = logging.getLogger(f"{__name__}.JiraAuthManager")
        
        # 設定認證
        self.auth = HTTPBasicAuth(self.username, self.api_token)
        self.headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        self.timeout = 30
    
    def test_connection(self) -> bool:
        """測試 JIRA 連接"""
        try:
            response = requests.get(
                f"{self.server_url}/rest/api/2/myself",
                auth=self.auth,
                headers=self.headers,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                user_info = response.json()
                self.logger.info(f"JIRA 連接成功，使用者: {user_info.get('displayName', self.username)}")
                return True
            else:
                self.logger.error(f"JIRA 連接失敗，HTTP {response.status_code}")
                return False
                
        except Exception as e:
            self.logger.error(f"JIRA 連接測試異常: {e}")
            return False


class JiraIssueManager:
    """JIRA Issue 管理器"""
    
    def __init__(self, auth_manager: JiraAuthManager):
        self.auth_manager = auth_manager
        
        # 設定日誌
        self.logger = logging.getLogger(f"{__name__}.JiraIssueManager")
        
        # API 配置
        self.timeout = 30
        self.max_results = 1000
    
    def _make_request(self, method: str, endpoint: str, data: Dict[str, Any] = None, 
                     params: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        """統一的 HTTP 請求方法"""
        url = f"{self.auth_manager.server_url}{endpoint}"
        
        try:
            response = requests.request(
                method=method,
                url=url,
                auth=self.auth_manager.auth,
                headers=self.auth_manager.headers,
                json=data,
                params=params,
                timeout=self.timeout
            )
            
            self.logger.debug(f"API 請求: {method} {endpoint} -> {response.status_code}")
            
            if response.status_code in [200, 201]:
                return response.json() if response.text else {}
            elif response.status_code == 204:
                return {}
            else:
                error_msg = f"API 請求失敗: {response.status_code} - {response.text}"
                self.logger.error(error_msg)
                return None
                
        except requests.exceptions.Timeout:
            self.logger.error(f"API 請求逾時: {method} {endpoint}")
            return None
        except requests.exceptions.RequestException as e:
            self.logger.error(f"API 請求錯誤: {e}")
            return None
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON 解析錯誤: {e}")
            return None
    
    def search_issues(self, jql: str, fields: List[str] = None, max_results: int = None) -> List[Dict[str, Any]]:
        """
        使用 JQL 搜尋 Issues
        
        Args:
            jql: JQL 查詢語句
            fields: 要返回的欄位列表
            max_results: 最大結果數量
            
        Returns:
            List[Dict]: Issue 列表
        """
        if fields is None:
            fields = ['summary', 'status', 'assignee', 'created', 'updated', 'description']
        
        if max_results is None:
            max_results = self.max_results
        
        all_issues = []
        start_at = 0
        batch_size = min(100, max_results)
        
        while len(all_issues) < max_results:
            params = {
                'jql': jql,
                'fields': ','.join(fields),
                'startAt': start_at,
                'maxResults': batch_size
            }
            
            response = self._make_request('GET', '/rest/api/2/search', params=params)
            
            if not response or 'issues' not in response:
                break
            
            issues = response['issues']
            all_issues.extend(issues)
            
            # 檢查是否還有更多結果
            total = response.get('total', 0)
            if len(all_issues) >= total or len(issues) < batch_size:
                break
            
            start_at += batch_size
        
        self.logger.info(f"JQL 搜尋完成，共取得 {len(all_issues)} 筆 Issues")
        return all_issues[:max_results]
    
    def get_issue(self, issue_key: str, fields: List[str] = None) -> Optional[Dict[str, Any]]:
        """
        取得單個 Issue
        
        Args:
            issue_key: Issue Key (例如: PROJ-123)
            fields: 要返回的欄位列表
            
        Returns:
            Dict: Issue 詳細資訊或 None
        """
        params = {}
        if fields:
            params['fields'] = ','.join(fields)
        
        response = self._make_request('GET', f'/rest/api/2/issue/{issue_key}', params=params)
        
        if response:
            self.logger.debug(f"成功取得 Issue: {issue_key}")
            return response
        else:
            self.logger.warning(f"無法取得 Issue: {issue_key}")
            return None
    
    def create_issue(self, project_key: str, summary: str, issue_type: str = "Bug", 
                    description: str = "", **kwargs) -> Optional[str]:
        """
        創建新的 Issue
        
        Args:
            project_key: 專案 Key
            summary: Issue 標題
            issue_type: Issue 類型 (Bug, Task, Story 等)
            description: Issue 描述
            **kwargs: 其他欄位
            
        Returns:
            str: 新建 Issue 的 Key 或 None
        """
        issue_data = {
            "fields": {
                "project": {"key": project_key},
                "summary": summary,
                "issuetype": {"name": issue_type},
                "description": description
            }
        }
        
        # 添加其他欄位
        for field, value in kwargs.items():
            issue_data["fields"][field] = value
        
        response = self._make_request('POST', '/rest/api/2/issue', data=issue_data)
        
        if response and 'key' in response:
            issue_key = response['key']
            self.logger.info(f"成功創建 Issue: {issue_key}")
            return issue_key
        else:
            self.logger.error("Issue 創建失敗")
            return None
    
    def update_issue(self, issue_key: str, **kwargs) -> bool:
        """
        更新 Issue
        
        Args:
            issue_key: Issue Key
            **kwargs: 要更新的欄位
            
        Returns:
            bool: 更新成功返回 True
        """
        update_data = {"fields": kwargs}
        
        response = self._make_request('PUT', f'/rest/api/2/issue/{issue_key}', data=update_data)
        
        if response is not None:
            self.logger.info(f"成功更新 Issue: {issue_key}")
            return True
        else:
            self.logger.error(f"Issue 更新失敗: {issue_key}")
            return False
    
    def add_comment(self, issue_key: str, comment: str) -> bool:
        """
        添加評論到 Issue
        
        Args:
            issue_key: Issue Key
            comment: 評論內容
            
        Returns:
            bool: 添加成功返回 True
        """
        comment_data = {"body": comment}
        
        response = self._make_request('POST', f'/rest/api/2/issue/{issue_key}/comment', data=comment_data)
        
        if response:
            self.logger.info(f"成功添加評論到 Issue: {issue_key}")
            return True
        else:
            self.logger.error(f"添加評論失敗: {issue_key}")
            return False
    
    def get_projects(self) -> List[Dict[str, Any]]:
        """
        取得所有專案列表
        
        Returns:
            List[Dict]: 專案列表
        """
        response = self._make_request('GET', '/rest/api/2/project')
        
        if response:
            self.logger.info(f"成功取得 {len(response)} 個專案")
            return response
        else:
            self.logger.error("取得專案列表失敗")
            return []


class JiraClient:
    """JIRA Base Client - 專注於高效的 Issue 管理功能"""
    
    def __init__(self, server_url: str = None, username: str = None, api_token: str = None):
        self.server_url = server_url or settings.jira.server_url
        self.username = username or settings.jira.username
        self.api_token = api_token or settings.jira.api_token
        
        # 設定日誌
        self.logger = logging.getLogger(f"{__name__}.JiraClient")
        
        # 初始化管理器
        self.auth_manager = JiraAuthManager(self.server_url, self.username, self.api_token)
        self.issue_manager = JiraIssueManager(self.auth_manager)
        
        self.logger.info("JIRA Client 初始化完成")
    
    def test_connection(self) -> bool:
        """測試連接"""
        return self.auth_manager.test_connection()
    
    def search_issues(self, jql: str, fields: List[str] = None, max_results: int = None) -> List[Dict[str, Any]]:
        """使用 JQL 搜尋 Issues"""
        return self.issue_manager.search_issues(jql, fields, max_results)
    
    def get_issue(self, issue_key: str, fields: List[str] = None) -> Optional[Dict[str, Any]]:
        """取得單個 Issue"""
        return self.issue_manager.get_issue(issue_key, fields)
    
    def create_issue(self, project_key: str, summary: str, issue_type: str = "Bug", 
                    description: str = "", **kwargs) -> Optional[str]:
        """創建新的 Issue"""
        return self.issue_manager.create_issue(project_key, summary, issue_type, description, **kwargs)
    
    def update_issue(self, issue_key: str, **kwargs) -> bool:
        """更新 Issue"""
        return self.issue_manager.update_issue(issue_key, **kwargs)
    
    def add_comment(self, issue_key: str, comment: str) -> bool:
        """添加評論到 Issue"""
        return self.issue_manager.add_comment(issue_key, comment)
    
    def get_projects(self) -> List[Dict[str, Any]]:
        """取得所有專案列表"""
        return self.issue_manager.get_projects()
    
    def create_bug_from_test_result(self, project_key: str, test_case_title: str, 
                                   failure_description: str, steps_to_reproduce: str = "",
                                   expected_result: str = "", actual_result: str = "",
                                   assignee: str = None) -> Optional[str]:
        """
        從測試結果創建 Bug Issue
        
        Args:
            project_key: 專案 Key
            test_case_title: 測試案例標題
            failure_description: 失敗描述
            steps_to_reproduce: 重現步驟
            expected_result: 預期結果
            actual_result: 實際結果
            assignee: 指派人員
            
        Returns:
            str: 新建 Bug 的 Key 或 None
        """
        summary = f"[Test Failure] {test_case_title}"
        
        description_parts = [
            f"*Test Case:* {test_case_title}",
            f"*Failure Description:* {failure_description}"
        ]
        
        if steps_to_reproduce:
            description_parts.append(f"*Steps to Reproduce:*\n{steps_to_reproduce}")
        
        if expected_result:
            description_parts.append(f"*Expected Result:*\n{expected_result}")
        
        if actual_result:
            description_parts.append(f"*Actual Result:*\n{actual_result}")
        
        description = "\n\n".join(description_parts)
        
        # 準備額外欄位
        extra_fields = {}
        if assignee:
            extra_fields["assignee"] = {"name": assignee}
        
        return self.create_issue(
            project_key=project_key,
            summary=summary,
            issue_type="Bug",
            description=description,
            **extra_fields
        )
    
    def validate_tp_ticket(self, tp_number: str) -> Dict[str, Any]:
        """
        驗證 TP 票號有效性
        
        Args:
            tp_number: TP 票號 (例如: TP-12345)
            
        Returns:
            Dict: 驗證結果包含格式檢查和 JIRA 存在性檢查
        """
        import re
        
        # TP 票號格式驗證
        tp_pattern = re.compile(r'^TP-\d+$')
        format_valid = bool(tp_pattern.match(tp_number))
        
        if not format_valid:
            return {
                'ticket_number': tp_number,
                'valid': False,
                'format_valid': False,
                'exists_in_jira': False,
                'error': f'TP 票號格式無效: {tp_number} (預期格式: TP-XXXXX)'
            }
        
        # JIRA 存在性檢查
        try:
            ticket_data = self.get_issue(tp_number, fields=['summary', 'status', 'key'])
            
            if ticket_data:
                fields = ticket_data.get('fields', {})
                return {
                    'ticket_number': tp_number,
                    'valid': True,
                    'format_valid': True,
                    'exists_in_jira': True,
                    'summary': fields.get('summary', ''),
                    'status': fields.get('status', {}).get('name', ''),
                    'url': f"{self.server_url}/browse/{tp_number}"
                }
            else:
                return {
                    'ticket_number': tp_number,
                    'valid': False,
                    'format_valid': True,
                    'exists_in_jira': False,
                    'error': f'TP 票號在 JIRA 中不存在: {tp_number}'
                }
                
        except Exception as e:
            self.logger.error(f"驗證 TP 票號時發生錯誤: {tp_number}, 錯誤: {e}")
            return {
                'ticket_number': tp_number,
                'valid': False,
                'format_valid': True,
                'exists_in_jira': False,
                'error': f'檢查 TP 票號時發生錯誤: {str(e)}'
            }
    
    def get_tp_ticket_details(self, tp_number: str) -> Optional[Dict[str, Any]]:
        """
        取得 TP 票號詳細資訊
        
        Args:
            tp_number: TP 票號 (例如: TP-12345)
            
        Returns:
            Dict: 完整的 TP 票號 JIRA 資訊或 None
        """
        import re
        from datetime import datetime
        
        # TP 票號格式驗證
        tp_pattern = re.compile(r'^TP-\d+$')
        if not tp_pattern.match(tp_number):
            self.logger.error(f"TP 票號格式無效: {tp_number}")
            return None
        
        try:
            # 查詢完整的票號資訊
            ticket_data = self.get_issue(
                tp_number,
                fields=['summary', 'status', 'assignee', 'priority', 'created', 
                       'updated', 'description', 'issuetype', 'project']
            )
            
            if not ticket_data:
                self.logger.warning(f"TP 票號不存在: {tp_number}")
                return None
            
            fields = ticket_data.get('fields', {})
            
            def safe_get_field(data: Dict, *field_path: str, default: Any = None):
                """安全地從巢狀字典中獲取欄位值"""
                current = data
                for field in field_path:
                    if isinstance(current, dict) and field in current:
                        current = current[field]
                    else:
                        return default
                return current
            
            # 負責人資訊
            assignee_data = fields.get('assignee')
            assignee_info = None
            if assignee_data:
                assignee_info = {
                    'display_name': safe_get_field(assignee_data, 'displayName', default='未知'),
                    'email': safe_get_field(assignee_data, 'emailAddress', default=''),
                    'account_id': safe_get_field(assignee_data, 'accountId', default='')
                }
            
            # 優先級資訊
            priority_data = fields.get('priority')
            priority_info = None
            if priority_data:
                priority_info = {
                    'name': safe_get_field(priority_data, 'name', default='未設定'),
                    'id': safe_get_field(priority_data, 'id', default=''),
                    'icon_url': safe_get_field(priority_data, 'iconUrl', default='')
                }
            
            # 狀態資訊
            status_data = fields.get('status', {})
            status_info = {
                'name': safe_get_field(status_data, 'name', default='未知'),
                'id': safe_get_field(status_data, 'id', default=''),
                'category': safe_get_field(status_data, 'statusCategory', 'name', default='')
            }
            
            # 專案資訊
            project_data = fields.get('project', {})
            project_info = {
                'key': safe_get_field(project_data, 'key', default=''),
                'name': safe_get_field(project_data, 'name', default='')
            }
            
            # 議題類型
            issue_type_data = fields.get('issuetype', {})
            issue_type_info = {
                'name': safe_get_field(issue_type_data, 'name', default=''),
                'icon_url': safe_get_field(issue_type_data, 'iconUrl', default='')
            }
            
            # 安全取得描述並限制長度
            description = safe_get_field(fields, 'description', default='')
            description = description[:1000] if description else ''
            
            # 組裝回應資料
            response_data = {
                'ticket_number': tp_number,
                'summary': safe_get_field(fields, 'summary', default=''),
                'description': description,
                'status': status_info,
                'assignee': assignee_info,
                'priority': priority_info,
                'project': project_info,
                'issue_type': issue_type_info,
                'created': safe_get_field(fields, 'created', default=''),
                'updated': safe_get_field(fields, 'updated', default=''),
                'url': f"{self.server_url}/browse/{tp_number}",
                'retrieved_at': datetime.now().isoformat()
            }
            
            self.logger.info(f"成功取得 TP 票號詳情: {tp_number}")
            return response_data
            
        except Exception as e:
            self.logger.error(f"取得 TP 票號詳情失敗: {tp_number}, 錯誤: {e}")
            return None
    
    def get_tp_tickets_batch(self, tp_numbers: List[str], fields: List[str] = None) -> Dict[str, Dict[str, Any]]:
        """
        批次查詢多個 TP 票號資訊
        
        Args:
            tp_numbers: TP 票號列表
            fields: 要返回的欄位列表
            
        Returns:
            Dict: 以票號為 key 的詳細資訊字典
        """
        import re
        
        if not tp_numbers:
            return {}
        
        # 預設欄位
        if fields is None:
            fields = ['summary', 'status', 'assignee', 'priority', 'created', 'updated']
        
        # 驗證所有 TP 票號格式
        tp_pattern = re.compile(r'^TP-\d+$')
        valid_tp_numbers = []
        invalid_tp_numbers = {}
        
        for tp_number in tp_numbers:
            if tp_pattern.match(tp_number):
                valid_tp_numbers.append(tp_number)
            else:
                invalid_tp_numbers[tp_number] = {
                    'error': f'TP 票號格式無效: {tp_number} (預期格式: TP-XXXXX)',
                    'valid': False
                }
        
        result = invalid_tp_numbers.copy()
        
        if not valid_tp_numbers:
            self.logger.warning("批次查詢中沒有有效的 TP 票號")
            return result
        
        try:
            # 使用 JQL 批次查詢
            jql = f"key in ({','.join(valid_tp_numbers)})"
            tickets_data = self.search_issues(jql, fields=fields, max_results=len(valid_tp_numbers))
            
            # 建立找到的票號集合
            found_tickets = set()
            
            # 處理找到的票號
            for ticket in tickets_data:
                ticket_key = ticket.get('key', '')
                if ticket_key in valid_tp_numbers:
                    found_tickets.add(ticket_key)
                    
                    fields_data = ticket.get('fields', {})
                    result[ticket_key] = {
                        'ticket_number': ticket_key,
                        'summary': fields_data.get('summary', ''),
                        'status': {
                            'name': fields_data.get('status', {}).get('name', ''),
                            'id': fields_data.get('status', {}).get('id', '')
                        },
                        'assignee': {
                            'display_name': fields_data.get('assignee', {}).get('displayName', '未指派'),
                            'account_id': fields_data.get('assignee', {}).get('accountId', '')
                        } if fields_data.get('assignee') else None,
                        'priority': {
                            'name': fields_data.get('priority', {}).get('name', '未設定'),
                            'id': fields_data.get('priority', {}).get('id', '')
                        } if fields_data.get('priority') else None,
                        'created': fields_data.get('created', ''),
                        'updated': fields_data.get('updated', ''),
                        'url': f"{self.server_url}/browse/{ticket_key}",
                        'valid': True
                    }
            
            # 處理未找到的票號
            for tp_number in valid_tp_numbers:
                if tp_number not in found_tickets:
                    result[tp_number] = {
                        'ticket_number': tp_number,
                        'error': f'TP 票號在 JIRA 中不存在: {tp_number}',
                        'valid': False
                    }
            
            self.logger.info(f"批次查詢完成，總共 {len(tp_numbers)} 個票號，找到 {len(found_tickets)} 個")
            return result
            
        except Exception as e:
            self.logger.error(f"批次查詢 TP 票號失敗: {e}")
            
            # 錯誤處理：為所有有效票號回傳錯誤資訊
            for tp_number in valid_tp_numbers:
                if tp_number not in result:
                    result[tp_number] = {
                        'ticket_number': tp_number,
                        'error': f'批次查詢失敗: {str(e)}',
                        'valid': False
                    }
            
            return result
    
    def get_performance_stats(self) -> Dict:
        """取得效能統計資訊"""
        return {
            'server_url': self.auth_manager.server_url,
            'username': self.auth_manager.username,
            'client_type': 'JiraClient',
            'features': ['Issue 查詢', 'Issue 創建', 'Issue 更新', 'Bug 報告', 'TP 票號驗證', 'TP 票號批次查詢']
        }