"""
Lark 多維表格 to User Story Map 匯入服務
完整實現 - 正確的父子關係映射
"""
import logging
from typing import Dict, List, Any, Optional, Tuple
import re
import uuid


class LarkUSMImportService:
    """處理 Lark 多維表格到 USM 的匯入"""
    
    def __init__(self, lark_client=None):
        """
        初始化服務
        
        Args:
            lark_client: Lark 客戶端實例（來自 lark_client.py）
        """
        self.lark_client = lark_client
        self.logger = logging.getLogger(__name__)
    
    async def fetch_lark_table(self, url: str) -> List[Dict[str, Any]]:
        """
        從 Lark URL 獲取多維表格數據
        
        Args:
            url: Lark 多維表格的分享 URL
            
        Returns:
            表格數據列表
        """
        try:
            if not self.lark_client:
                raise ValueError("Lark 客戶端未初始化")
            
            # 解析 URL 提取 token
            tokens = self._extract_tokens_from_url(url)
            if not tokens:
                raise ValueError("無效的 Lark URL，無法提取 token")
            
            wiki_token, table_id = tokens
            
            # 使用 Lark 客戶端獲取記錄
            records = self.lark_client.get_all_records(table_id, wiki_token)
            
            if not records:
                raise Exception("無法獲取 Lark 表格數據")
            
            # 轉換 Lark 記錄格式為 USM 格式
            converted_records = self._convert_lark_records(records)
            
            return converted_records
                
        except Exception as e:
            self.logger.error(f"獲取 Lark 表格失敗: {str(e)}")
            raise Exception(f"獲取 Lark 表格失敗: {str(e)}")
    
    def _extract_tokens_from_url(self, url: str) -> Optional[Tuple[str, str]]:
        """
        從 Lark URL 提取 wiki_token 和 table_id
        
        Args:
            url: Lark URL
            
        Returns:
            (wiki_token, table_id) 或 None
        """
        # 格式: https://igxy0zaeo1r.sg.larksuite.com/wiki/Q4XxwaS2Cif80DkAku9lMKuAgof?...&table=tbl2Yy9f8MTOtQPP
        
        # 提取 wiki token
        wiki_match = re.search(r'/wiki/([A-Za-z0-9]+)', url)
        if not wiki_match:
            return None
        
        wiki_token = wiki_match.group(1)
        
        # 提取 table ID
        table_match = re.search(r'[?&]table=([A-Za-z0-9]+)', url)
        if not table_match:
            return None
        
        table_id = table_match.group(1)
        
        return wiki_token, table_id
    
    def _convert_lark_records(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        將 Lark 記錄格式轉換為 USM 格式
        
        Args:
            records: Lark API 返回的記錄列表
            
        Returns:
            轉換後的記錄列表（帶 Story.No 主鍵）
        """
        converted = []
        
        for record in records:
            fields = record.get('fields', {})
            
            # 提取 Story.No 作為主鍵
            story_no = self._get_field_value(fields, 'Story.No')
            
            # 提取 Parent Tickets（從連結物件列表中）
            parent_tickets = fields.get('Parent Tickets', [])
            parent_story_no = None
            if isinstance(parent_tickets, list) and len(parent_tickets) > 0:
                parent_story_no = parent_tickets[0].get('text')
            
            converted_record = {
                'story_no': story_no,  # Story.No 作為主鍵
                'record_id': record.get('record_id', ''),
                'features': self._get_field_value(fields, 'Features'),
                'criteria': self._get_field_value(fields, 'Criteria'),
                'as_a': self._get_field_value(fields, 'As a'),
                'i_want': self._get_field_value(fields, 'I want'),
                'so_that': self._get_field_value(fields, 'So that'),
                'tcg': self._parse_jira_tickets(self._get_field_value(fields, 'TCG')),
                'parent_story_no': parent_story_no,  # 父 Story.No
                'children': []  # 將在構建關係後填充
            }
            
            converted.append(converted_record)
        
        # 構建父子關係
        self._build_parent_child_relationships(converted)
        
        return converted
    
    def _get_field_value(self, fields: Dict, field_name: str) -> Any:
        """
        從 Lark 記錄的 fields 中獲取字段值
        
        Args:
            fields: Lark 記錄的 fields 字典
            field_name: 字段名
            
        Returns:
            字段值
        """
        value = fields.get(field_name)
        
        if not value:
            return ""
        
        # 如果是列表（連結物件或多行文本）
        if isinstance(value, list):
            if len(value) == 0:
                return ""
            item = value[0]
            
            # 如果是連結物件，提取 text 欄位
            if isinstance(item, dict):
                # 連結物件有 "text" 欄位
                if 'text' in item:
                    return item.get('text', '')
                # 否則轉換為字符串
                return str(item)
            
            # 純字符串
            return str(item)
        
        # 如果是字典（複雜類型），提取文本
        if isinstance(value, dict):
            return value.get('text', str(value))
        
        # 基本類型
        return str(value) if value else ""
    
    def _build_parent_child_relationships(self, records: List[Dict[str, Any]]) -> None:
        """
        根據 Parent Tickets 欄位構建父子關係
        
        使用 Story.No 作為主鍵，確保關係正確映射
        
        Args:
            records: 轉換後的記錄列表（將被修改）
        """
        # 建立 Story.No → 記錄的快速查找表
        story_no_map = {record['story_no']: record for record in records}
        
        for record in records:
            parent_story_no = record.get('parent_story_no')
            
            # 如果有父節點，將此記錄添加到父節點的 children 列表
            if parent_story_no and parent_story_no in story_no_map:
                parent_record = story_no_map[parent_story_no]
                if record not in parent_record['children']:
                    parent_record['children'].append(record)
    
    def convert_to_usm_nodes(
        self,
        records: List[Dict[str, Any]],
        root_name: str,
        team_id: int
    ) -> Dict[str, Any]:
        """
        將 Lark 記錄轉換為 USM 節點結構
        
        核心邏輯：
        1. 使用 Story.No 作為節點 ID 的唯一鍵
        2. 根據是否有子節點判斷類型（有子節點 = Feature，無子節點 = User Story）
        3. 扁平化記錄並建立映射
        4. 根據 Parent Story.No 建立父子關係
        5. 計算節點位置和層級
        
        Args:
            records: Lark 記錄列表（可能是嵌套的）
            root_name: 根節點名稱
            team_id: 團隊 ID
            
        Returns:
            USM 數據結構
        """
        # 第一步：扁平化所有記錄並建立 Story.No → 記錄 的映射（去重）
        all_records = []
        seen_story_nos = set()  # 用於去重
        story_no_map = {}  # Story.No → 記錄
        
        def flatten_records(records_list):
            for record in records_list:
                story_no = record.get('story_no', '')
                
                # 避免重複添加同一筆記錄
                if story_no and story_no in seen_story_nos:
                    continue
                
                if story_no:
                    seen_story_nos.add(story_no)
                    story_no_map[story_no] = record
                
                all_records.append(record)
                
                # 遞歸處理子記錄
                children = record.get('children', [])
                if children:
                    flatten_records(children)
        
        flatten_records(records)
        
        # 第二步：分析節點類型（根據是否有子節點）
        # 先建立一次遍歷以確定所有 Story.No 有哪些子節點
        has_children = set()
        for record in all_records:
            children = record.get('children', [])
            if children:
                story_no = record.get('story_no')
                has_children.add(story_no)
        
        # 第三步：生成根節點 ID（使用真實 ID 而不是 "root"）
        root_node_id = f"root_{uuid.uuid4().hex[:8]}"
        
        # 第四步：建立節點映射表
        node_map: Dict[str, Dict[str, Any]] = {}
        
        # 4.1 建立根節點（node_type 應該是 "root"）
        root_node = {
            "id": root_node_id,
            "title": root_name,
            "description": "",
            "node_type": "root",
            "parent_id": None,
            "children_ids": [],
            "related_ids": [],
            "jira_tickets": [],
            "as_a": "",
            "i_want": "",
            "so_that": "",
            "position_x": 250.0,
            "position_y": 250.0,
            "level": 0,
            "story_no": "",  # 根節點沒有 Story.No
        }
        node_map[root_node_id] = root_node
        
        # 4.2 為每個記錄建立節點
        for record in all_records:
            story_no = record.get('story_no', '')
            parent_story_no = record.get('parent_story_no')
            
            # 使用 Story.No 作為節點 ID
            node_id = story_no if story_no else f"node_{uuid.uuid4().hex[:8]}"
            
            # 判斷節點類型：有子節點 = Feature，無子節點 = User Story
            is_feature = story_no in has_children
            node_type = "feature_category" if is_feature else "user_story"
            
            # 確定父節點 ID：優先使用 parent_story_no（若存在）否則使用根節點
            if parent_story_no and parent_story_no in story_no_map:
                parent_id = parent_story_no
            else:
                parent_id = root_node_id
            
            # 解析 JIRA tickets（tcg 已在轉換時解析）
            jira_tickets = record.get('tcg', [])
            if isinstance(jira_tickets, str):
                jira_tickets = self._parse_jira_tickets(jira_tickets)
            
            node = {
                "id": node_id,
                "story_no": story_no,  # 保存原始 Story.No
                "title": record.get('features', ''),
                "description": record.get('criteria', ''),
                "node_type": node_type,
                "parent_id": parent_id,
                "children_ids": [],
                "related_ids": [],
                "jira_tickets": jira_tickets,
                "as_a": record.get('as_a', ''),
                "i_want": record.get('i_want', ''),
                "so_that": record.get('so_that', ''),
                "position_x": 0.0,
                "position_y": 0.0,
                "level": 0,
            }
            
            node_map[node_id] = node
        
        # 第五步：構建父子關係（確保完整的雙向關聯）
        for node_id, node in node_map.items():
            if node_id == root_node_id:
                continue
            
            parent_id = node["parent_id"]
            # 確保 parent_id 存在於 node_map 中
            if parent_id and parent_id in node_map:
                parent_node = node_map[parent_id]
                if node_id not in parent_node["children_ids"]:
                    parent_node["children_ids"].append(node_id)
        
        # 第六步：計算節點位置
        self._assign_node_positions(node_map)
        
        # 第七步：構建 USM 數據結構
        usm_data = {
            "map_name": root_name,
            "team_id": team_id,
            "nodes": list(node_map.values()),
            "root_node_id": root_node_id,
        }
        
        return usm_data
    
    def _assign_node_positions(self, node_map: Dict[str, Dict[str, Any]]):
        """
        為節點分配位置（按層級）
        
        Args:
            node_map: 節點映射表（將被修改）
        """
        # 計算每個節點的層級 - 使用迭代方式避免遞歸
        # 根節點的 node_type 為 "root"，層級為 0
        root_node_id = None
        for node_id, node in node_map.items():
            if node.get("node_type") == "root":
                root_node_id = node_id
                break
        
        if not root_node_id:
            # 如果找不到 root 類型的節點，使用 parent_id 為 None 的節點作為根
            for node_id, node in node_map.items():
                if node.get("parent_id") is None:
                    root_node_id = node_id
                    break
        
        level_map = {}
        if root_node_id:
            level_map[root_node_id] = 0
        
        # 多次迭代直到所有節點的層級都確定
        max_iterations = 100
        for _ in range(max_iterations):
            unchanged = True
            for node_id, node in node_map.items():
                if node_id in level_map:
                    continue
                
                parent_id = node["parent_id"]
                if parent_id and parent_id in level_map:
                    level_map[node_id] = level_map[parent_id] + 1
                    unchanged = False
            
            if unchanged:
                break
        
        # 設置未確定層級的節點為 0（防止錯誤）
        for node_id in node_map:
            if node_id not in level_map:
                level_map[node_id] = 0
        
        # 按層級分組節點
        nodes_by_level = {}
        for node_id, level in level_map.items():
            if level not in nodes_by_level:
                nodes_by_level[level] = []
            nodes_by_level[level].append(node_id)
        
        # 分配位置
        base_x = 250.0
        base_y = 250.0
        
        for level, node_ids in sorted(nodes_by_level.items()):
            y = base_y + (level * 100)  # 垂直間距
            num_nodes = len(node_ids)
            x_spacing = 150 if num_nodes > 1 else 0
            start_x = base_x - (num_nodes - 1) * x_spacing / 2
            
            for idx, node_id in enumerate(node_ids):
                node = node_map[node_id]
                node["position_x"] = float(start_x + idx * x_spacing)
                node["position_y"] = float(y)
                node["level"] = level
    
    def _parse_jira_tickets(self, tcg_field: str) -> List[str]:
        """
        解析 TCG 欄位為 JIRA tickets 列表
        
        Args:
            tcg_field: TCG 欄位內容
            
        Returns:
            JIRA tickets 列表
        """
        if not tcg_field:
            return []
        
        tickets = []
        # 嘗試提取所有 TCG-XXX 格式的票號
        matches = re.findall(r'TCG-\d+', str(tcg_field))
        tickets.extend(matches)
        
        # 如果沒找到，嘗試按逗號或換行分隔
        if not tickets and tcg_field:
            parts = re.split(r'[,\n]', tcg_field)
            for part in parts:
                part = part.strip()
                if part:
                    tickets.append(part)
        
        return tickets
    
    def validate_import_data(self, data: Dict[str, Any]) -> Tuple[bool, str]:
        """
        驗證匯入數據
        
        Args:
            data: 匯入數據
            
        Returns:
            (是否有效, 錯誤訊息)
        """
        if not data.get("map_name"):
            return False, "地圖名稱不能為空"
        
        if not data.get("team_id"):
            return False, "團隊 ID 不能為空"
        
        if not data.get("nodes"):
            return False, "沒有節點數據"
        
        if len(data["nodes"]) == 0:
            return False, "節點列表不能為空"
        
        # 驗證必須有根節點
        root_node_id = data.get("root_node_id")
        if not root_node_id:
            return False, "根節點 ID 未定義"
        
        # 驗證父子關係完整性
        nodes = data["nodes"]
        node_ids = {node["id"] for node in nodes}
        
        # 確保根節點存在
        root_found = False
        for node in nodes:
            if node["id"] == root_node_id:
                root_found = True
                break
        
        if not root_found:
            return False, f"根節點 {root_node_id} 不存在"
        
        for node in nodes:
            parent_id = node.get("parent_id")
            if parent_id and parent_id not in node_ids:
                return False, f"節點 {node['id']} 的父節點 {parent_id} 不存在"
            
            for child_id in node.get("children_ids", []):
                if child_id not in node_ids:
                    return False, f"節點 {node['id']} 的子節點 {child_id} 不存在"
        
        return True, ""
