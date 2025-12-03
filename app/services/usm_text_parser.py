"""
USM 文字格式解析器

支援將 USM 文字格式轉換為資料庫模型，以及反向匯出
"""

import re
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import secrets


class ParseError(Exception):
    """解析錯誤"""
    def __init__(self, line_num: int, message: str):
        self.line_num = line_num
        self.message = message
        super().__init__(f"Line {line_num}: {message}")


class Line:
    """代表一行文字"""
    def __init__(self, line_num: int, content: str, indent: int):
        self.line_num = line_num
        self.content = content
        self.indent = indent
        self.is_node = False
        self.is_property = False


class USMNode:
    """USM 節點"""
    def __init__(self):
        self.node_id: Optional[str] = None
        self.title: str = ""
        self.node_type: str = ""
        self.description: Optional[str] = None
        self.comment: Optional[str] = None
        self.jira_tickets: List[str] = []
        self.product: Optional[str] = None
        self.team: Optional[str] = None
        self.team_tags: List[str] = []
        self.related_ids: List[str] = []
        self.as_a: Optional[str] = None
        self.i_want: Optional[str] = None
        self.so_that: Optional[str] = None
        
        # 樹狀結構
        self.parent_id: Optional[str] = None
        self.children_ids: List[str] = []
        self.level: int = 0
        
        # 位置（解析時不處理，由前端自動佈局）
        self.position_x: float = 0
        self.position_y: float = 0
        
        # 聚合資料（解析時不處理）
        self.aggregated_tickets: List[str] = []
        
        # 元資料
        self.line_num: int = 0


class USMParser:
    """USM 文字格式解析器"""
    
    # 節點類型映射
    NODE_TYPE_MAP = {
        "root": "root",
        "feature": "feature_category",
        "story": "user_story",
    }
    
    def __init__(self):
        self.nodes: List[USMNode] = []
        self.node_id_map: Dict[str, USMNode] = {}
        self.indent_size: Optional[int] = None
        
    def parse(self, text: str) -> List[USMNode]:
        """
        解析 USM 文字格式
        
        Args:
            text: USM 格式文字
            
        Returns:
            節點列表
            
        Raises:
            ParseError: 解析錯誤
        """
        lines = self._preprocess(text)
        self._parse_nodes(lines)
        self._validate()
        self._resolve_relations()
        self._calculate_positions()
        return self.nodes
    
    def _preprocess(self, text: str) -> List[Line]:
        """
        預處理文字
        
        - 移除註解
        - 處理空行
        - 計算縮排
        - 偵測縮排大小
        """
        lines: List[Line] = []
        
        for line_num, raw_line in enumerate(text.split('\n'), start=1):
            # 轉換 tab 為空格
            raw_line = raw_line.replace('\t', '    ')
            
            # 移除行尾空白
            raw_line = raw_line.rstrip()
            
            # 跳過空行和註解
            if not raw_line or raw_line.lstrip().startswith('#'):
                continue
            
            # 計算縮排
            indent = len(raw_line) - len(raw_line.lstrip())
            content = raw_line.lstrip()
            
            # 偵測縮排大小（第一個有縮排的行）
            if self.indent_size is None and indent > 0:
                self.indent_size = indent
            
            lines.append(Line(line_num, content, indent))
        
        # 如果沒偵測到縮排，預設 2
        if self.indent_size is None:
            self.indent_size = 2
            
        return lines
    
    def _parse_nodes(self, lines: List[Line]):
        """解析節點"""
        node_stack: List[Tuple[int, USMNode]] = []  # (level, node)
        current_node: Optional[USMNode] = None
        multiline_field: Optional[str] = None
        multiline_content: List[str] = []
        
        for line in lines:
            # 計算層級
            if self.indent_size and self.indent_size > 0:
                level = line.indent // self.indent_size
            else:
                level = 0
            
            # 檢查是否為節點定義（包含冒號）
            if ':' in line.content:
                # 先處理前一個節點的多行欄位
                if multiline_field and current_node:
                    self._set_node_field(current_node, multiline_field, 
                                       '\n'.join(multiline_content))
                    multiline_field = None
                    multiline_content = []
                
                # 嘗試解析為節點
                node = self._try_parse_node(line, level)
                if node:
                    # 新節點
                    current_node = node
                    
                    # 維護節點堆疊和父子關係
                    while node_stack and node_stack[-1][0] >= level:
                        node_stack.pop()
                    
                    if node_stack:
                        parent_level, parent_node = node_stack[-1]
                        node.parent_id = parent_node.node_id
                        if node.node_id:
                            parent_node.children_ids.append(node.node_id)
                    
                    node_stack.append((level, node))
                    self.nodes.append(node)
                    
                    if node.node_id:
                        self.node_id_map[node.node_id] = node
                    
                    continue
                
                # 不是節點，嘗試解析為屬性
                if current_node:
                    key, value = self._parse_property(line)
                    if value.strip() == '|':
                        # 多行欄位開始
                        multiline_field = key
                        multiline_content = []
                    else:
                        self._set_node_field(current_node, key, value)
            else:
                # 多行內容
                if multiline_field and current_node:
                    multiline_content.append(line.content)
        
        # 處理最後的多行欄位
        if multiline_field and current_node:
            self._set_node_field(current_node, multiline_field,
                               '\n'.join(multiline_content))
    
    def _try_parse_node(self, line: Line, level: int) -> Optional[USMNode]:
        """
        嘗試解析為節點
        
        格式: [@node_id] 節點類型: 標題
        """
        # 正則表達式：可選的 [@id]、節點類型、冒號、標題
        pattern = r'^(?:\[@([^\]]+)\]\s+)?(\w+):\s*(.+)$'
        match = re.match(pattern, line.content)
        
        if not match:
            return None
        
        custom_id, node_type, title = match.groups()
        
        # 驗證節點類型 - 如果不是有效的節點類型，返回 None（當作屬性處理）
        if node_type not in self.NODE_TYPE_MAP:
            return None
        
        node = USMNode()
        node.line_num = line.line_num
        node.title = title.strip()
        node.node_type = self.NODE_TYPE_MAP[node_type]
        node.level = level
        
        # 處理 node_id
        if custom_id:
            # 自訂 ID
            if custom_id in self.node_id_map:
                raise ParseError(line.line_num,
                               f"重複的 node_id: {custom_id}")
            node.node_id = custom_id
        else:
            # 自動生成 ID
            if node.node_type == "root":
                node.node_id = f"root_{secrets.token_hex(4)}"
            else:
                # 使用時間戳（毫秒）
                import time
                node.node_id = f"node_{int(time.time() * 1000)}"
        
        return node
    
    def _parse_property(self, line: Line) -> Tuple[str, str]:
        """解析屬性行"""
        parts = line.content.split(':', 1)
        if len(parts) != 2:
            raise ParseError(line.line_num,
                           f"無效的屬性格式: {line.content}")
        
        key = parts[0].strip()
        value = parts[1].strip()
        return key, value
    
    def _set_node_field(self, node: USMNode, key: str, value: str):
        """設定節點欄位"""
        key = key.lower()
        
        if key == 'desc':
            node.description = value
        elif key == 'comment':
            node.comment = value
        elif key == 'jira':
            # 逗號分隔
            node.jira_tickets = [t.strip() for t in value.split(',') if t.strip()]
        elif key == 'product':
            node.product = value
        elif key == 'team':
            node.team = value
        elif key == 'team_tags':
            node.team_tags = [t.strip() for t in value.split(',') if t.strip()]
        elif key == 'related':
            # 解析關聯節點，支援 @id 或直接 id
            related = []
            for ref in value.split(','):
                ref = ref.strip()
                if ref.startswith('@'):
                    ref = ref[1:]
                if ref:
                    related.append(ref)
            node.related_ids = related
        elif key == 'as_a':
            node.as_a = value
        elif key == 'i_want':
            node.i_want = value
        elif key == 'so_that':
            node.so_that = value
        else:
            # 忽略未知欄位
            pass
    
    def _validate(self):
        """驗證節點"""
        for node in self.nodes:
            # 檢查 user_story 不可有子節點
            if node.node_type == 'user_story' and node.children_ids:
                raise ParseError(node.line_num,
                               f"User Story 節點不可有子節點: {node.title}")
            
            # 檢查必要欄位
            if not node.title:
                raise ParseError(node.line_num, "節點必須有標題")
    
    def _resolve_relations(self):
        """解析關聯"""
        for node in self.nodes:
            # 驗證 related_ids 中的節點是否存在
            for related_id in node.related_ids[:]:
                if related_id not in self.node_id_map:
                    # 警告：引用不存在的節點
                    # 這裡可以選擇拋出錯誤或僅移除無效引用
                    node.related_ids.remove(related_id)
    
    def _calculate_positions(self):
        """計算節點位置（基本佈局）"""
        ROOT_START_X = 250.0
        ROOT_START_Y = 250.0
        CHILD_HORIZONTAL_OFFSET = 150.0
        SIBLING_VERTICAL_SPACING = 100.0
        
        # 簡單的佈局算法：根據層級和順序
        level_counters = {}
        
        for node in self.nodes:
            level = node.level
            
            if level not in level_counters:
                level_counters[level] = 0
            
            node.position_x = ROOT_START_X + level * CHILD_HORIZONTAL_OFFSET
            node.position_y = ROOT_START_Y + level_counters[level] * SIBLING_VERTICAL_SPACING
            
            level_counters[level] += 1


class USMExporter:
    """USM 文字格式匯出器"""
    
    # 反向節點類型映射
    NODE_TYPE_REVERSE_MAP = {
        "root": "root",
        "feature_category": "feature",
        "user_story": "story",
    }
    
    def __init__(self, indent_size: int = 2):
        self.indent_size = indent_size
    
    def export(self, nodes: List[Dict]) -> str:
        """
        匯出為 USM 文字格式
        
        Args:
            nodes: 節點列表（資料庫格式）
            
        Returns:
            USM 格式文字
        """
        # 建立節點映射
        node_map = {n['node_id']: n for n in nodes}
        
        # 找出根節點
        root_nodes = [n for n in nodes if not n.get('parent_id')]
        
        lines = []
        lines.append("# USM 文字格式")
        lines.append(f"# 匯出時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        
        # 遞迴匯出節點
        for root in root_nodes:
            self._export_node(root, node_map, lines, 0)
        
        return '\n'.join(lines)
    
    def _export_node(self, node: Dict, node_map: Dict, 
                    lines: List[str], level: int):
        """遞迴匯出節點"""
        indent = ' ' * (level * self.indent_size)
        
        # 節點定義行
        node_id = node['node_id']
        node_type = self.NODE_TYPE_REVERSE_MAP.get(
            node.get('node_type', ''), 'feature')
        title = node['title']
        
        lines.append(f"{indent}[@{node_id}] {node_type}: {title}")
        
        # 屬性
        prop_indent = indent + ' ' * self.indent_size
        
        if node.get('description'):
            desc = node['description']
            if '\n' in desc:
                lines.append(f"{prop_indent}desc: |")
                for desc_line in desc.split('\n'):
                    lines.append(f"{prop_indent}  {desc_line}")
            else:
                lines.append(f"{prop_indent}desc: {desc}")
        
        if node.get('comment'):
            comment = node['comment']
            if '\n' in comment:
                lines.append(f"{prop_indent}comment: |")
                for comment_line in comment.split('\n'):
                    lines.append(f"{prop_indent}  {comment_line}")
            else:
                lines.append(f"{prop_indent}comment: {comment}")
        
        if node.get('jira_tickets'):
            jira = ', '.join(node['jira_tickets'])
            lines.append(f"{prop_indent}jira: {jira}")
        
        if node.get('product'):
            lines.append(f"{prop_indent}product: {node['product']}")
        
        if node.get('team'):
            lines.append(f"{prop_indent}team: {node['team']}")
        
        if node.get('team_tags'):
            tags = ', '.join(node['team_tags'])
            lines.append(f"{prop_indent}team_tags: {tags}")
        
        if node.get('related_ids'):
            related = ', '.join(f"@{rid}" for rid in node['related_ids'])
            lines.append(f"{prop_indent}related: {related}")
        
        if node.get('as_a'):
            lines.append(f"{prop_indent}as_a: {node['as_a']}")
        
        if node.get('i_want'):
            lines.append(f"{prop_indent}i_want: {node['i_want']}")
        
        if node.get('so_that'):
            lines.append(f"{prop_indent}so_that: {node['so_that']}")
        
        # 子節點
        children_ids = node.get('children_ids', [])
        if children_ids:
            lines.append("")  # 空行分隔
            for child_id in children_ids:
                if child_id in node_map:
                    self._export_node(node_map[child_id], node_map, 
                                    lines, level + 1)
                    lines.append("")  # 子節點間空行


# 便利函數

def parse_usm_text(text: str) -> List[USMNode]:
    """解析 USM 文字格式"""
    parser = USMParser()
    return parser.parse(text)


def export_to_usm_text(nodes: List[Dict], indent_size: int = 2) -> str:
    """匯出為 USM 文字格式"""
    exporter = USMExporter(indent_size)
    return exporter.export(nodes)


def convert_usm_nodes_to_db_format(nodes: List[USMNode], 
                                   map_id: int) -> List[Dict]:
    """
    轉換 USM 節點為資料庫格式
    
    Args:
        nodes: USM 節點列表
        map_id: Map ID
        
    Returns:
        資料庫格式的節點列表
    """
    db_nodes = []
    
    for node in nodes:
        db_node = {
            'map_id': map_id,
            'node_id': node.node_id,
            'title': node.title,
            'description': node.description,
            'node_type': node.node_type,
            'parent_id': node.parent_id,
            'children_ids': node.children_ids,
            'related_ids': node.related_ids,
            'comment': node.comment,
            'jira_tickets': node.jira_tickets,
            'product': node.product,
            'team': node.team,
            'team_tags': node.team_tags,
            'aggregated_tickets': node.aggregated_tickets,
            'position_x': node.position_x,
            'position_y': node.position_y,
            'level': node.level,
            'as_a': node.as_a,
            'i_want': node.i_want,
            'so_that': node.so_that,
        }
        
        db_nodes.append(db_node)
    
    return db_nodes
