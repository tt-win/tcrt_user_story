"""
測試 USM 文字格式解析器
"""

import sys
import os

# 加入路徑以便 import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from services.usm_text_parser import (
    parse_usm_text, 
    export_to_usm_text,
    convert_usm_nodes_to_db_format,
    ParseError
)


def test_basic_parsing():
    """測試基本解析"""
    print("=== 測試基本解析 ===\n")
    
    text = """
# 這是註解
[@test_root] root: 測試系統
  desc: 這是測試系統的描述
  
  [@feature1] feature: 功能1
    team: 開發團隊
    
    [@story1] story: 故事1
      desc: 故事1的描述
      jira: TEST-001, TEST-002
      as_a: 使用者
      i_want: 能夠登入
      so_that: 可以使用系統
"""
    
    try:
        nodes = parse_usm_text(text)
        print(f"成功解析 {len(nodes)} 個節點:\n")
        
        for node in nodes:
            print(f"- [{node.node_id}] {node.node_type}: {node.title}")
            print(f"  Level: {node.level}, Parent: {node.parent_id}")
            print(f"  Children: {node.children_ids}")
            if node.description:
                print(f"  Description: {node.description}")
            if node.jira_tickets:
                print(f"  Jira: {node.jira_tickets}")
            if node.as_a:
                print(f"  BDD: As a {node.as_a}, I want {node.i_want}")
            print()
        
        print("✓ 基本解析測試通過\n")
        return True
        
    except ParseError as e:
        print(f"✗ 解析錯誤: {e}\n")
        return False


def test_auto_id_generation():
    """測試自動 ID 生成"""
    print("=== 測試自動 ID 生成 ===\n")
    
    text = """
root: 系統
  
  feature: 功能A
    
    story: 故事A1
    
    story: 故事A2
"""
    
    try:
        nodes = parse_usm_text(text)
        print(f"成功解析 {len(nodes)} 個節點（自動生成 ID）:\n")
        
        for node in nodes:
            print(f"- [{node.node_id}] {node.node_type}: {node.title}")
        
        # 檢查 root 節點 ID 格式
        root = nodes[0]
        if root.node_id and root.node_id.startswith('root_'):
            print(f"\n✓ Root ID 格式正確: {root.node_id}")
        
        # 檢查一般節點 ID 格式
        if len(nodes) > 1:
            node = nodes[1]
            if node.node_id and node.node_id.startswith('node_'):
                print(f"✓ Node ID 格式正確: {node.node_id}")
        
        print("\n✓ 自動 ID 生成測試通過\n")
        return True
        
    except ParseError as e:
        print(f"✗ 解析錯誤: {e}\n")
        return False


def test_export():
    """測試匯出"""
    print("=== 測試匯出 ===\n")
    
    # 模擬資料庫格式的節點
    nodes = [
        {
            'node_id': 'root_abc123',
            'title': '測試系統',
            'node_type': 'root',
            'description': '系統描述',
            'parent_id': None,
            'children_ids': ['feature1'],
            'related_ids': [],
            'comment': None,
            'jira_tickets': [],
            'product': None,
            'team': None,
            'team_tags': [],
            'aggregated_tickets': [],
            'position_x': 0,
            'position_y': 0,
            'level': 0,
            'as_a': None,
            'i_want': None,
            'so_that': None,
        },
        {
            'node_id': 'feature1',
            'title': '功能1',
            'node_type': 'feature_category',
            'description': None,
            'parent_id': 'root_abc123',
            'children_ids': ['story1'],
            'related_ids': [],
            'comment': None,
            'jira_tickets': [],
            'product': None,
            'team': '開發團隊',
            'team_tags': [],
            'aggregated_tickets': [],
            'position_x': 0,
            'position_y': 0,
            'level': 1,
            'as_a': None,
            'i_want': None,
            'so_that': None,
        },
        {
            'node_id': 'story1',
            'title': '故事1',
            'node_type': 'user_story',
            'description': '故事描述',
            'parent_id': 'feature1',
            'children_ids': [],
            'related_ids': [],
            'comment': None,
            'jira_tickets': ['TEST-001', 'TEST-002'],
            'product': None,
            'team': None,
            'team_tags': [],
            'aggregated_tickets': [],
            'position_x': 0,
            'position_y': 0,
            'level': 2,
            'as_a': '使用者',
            'i_want': '能夠登入',
            'so_that': '使用系統',
        },
    ]
    
    try:
        text = export_to_usm_text(nodes)
        print("匯出的 USM 文字:\n")
        print(text)
        print("\n✓ 匯出測試通過\n")
        return True
        
    except Exception as e:
        print(f"✗ 匯出錯誤: {e}\n")
        return False


def test_multiline_fields():
    """測試多行欄位"""
    print("=== 測試多行欄位 ===\n")
    
    text = """
[@test] root: 測試
  desc: |
    第一行描述
    第二行描述
    第三行描述
  comment: |
    這是註解
    可以很長
"""
    
    try:
        nodes = parse_usm_text(text)
        node = nodes[0]
        
        print(f"節點: {node.title}")
        print(f"Description:\n{node.description}\n")
        print(f"Comment:\n{node.comment}\n")
        
        if node.description and '\n' in node.description:
            print("✓ 多行 description 解析正確")
        
        if node.comment and '\n' in node.comment:
            print("✓ 多行 comment 解析正確")
        
        print("\n✓ 多行欄位測試通過\n")
        return True
        
    except ParseError as e:
        print(f"✗ 解析錯誤: {e}\n")
        return False


def test_related_nodes():
    """測試關聯節點"""
    print("=== 測試關聯節點 ===\n")
    
    text = """
[@node_a] root: 節點A

[@node_b] feature: 節點B
  related: @node_a

[@node_c] story: 節點C
  related: @node_a, @node_b
"""
    
    try:
        nodes = parse_usm_text(text)
        
        for node in nodes:
            print(f"- [{node.node_id}] {node.title}")
            if node.related_ids:
                print(f"  Related: {node.related_ids}")
        
        # 檢查關聯
        node_b = nodes[1]
        if 'node_a' in node_b.related_ids:
            print("\n✓ 單一關聯解析正確")
        
        node_c = nodes[2]
        if 'node_a' in node_c.related_ids and 'node_b' in node_c.related_ids:
            print("✓ 多重關聯解析正確")
        
        print("\n✓ 關聯節點測試通過\n")
        return True
        
    except ParseError as e:
        print(f"✗ 解析錯誤: {e}\n")
        return False


def test_error_handling():
    """測試錯誤處理"""
    print("=== 測試錯誤處理 ===\n")
    
    # 測試重複 ID
    text1 = """
[@dup] root: 節點1
[@dup] feature: 節點2
"""
    
    try:
        parse_usm_text(text1)
        print("✗ 應該要拋出重複 ID 錯誤")
        return False
    except ParseError as e:
        print(f"✓ 正確捕捉重複 ID 錯誤: {e}")
    
    # 測試 user_story 有子節點
    text2 = """
[@parent] story: 父節點
  [@child] story: 子節點
"""
    
    try:
        parse_usm_text(text2)
        print("✗ 應該要拋出 user_story 不可有子節點錯誤")
        return False
    except ParseError as e:
        print(f"✓ 正確捕捉 user_story 子節點錯誤: {e}")
    
    print("\n✓ 錯誤處理測試通過\n")
    return True


def test_round_trip():
    """測試往返轉換（parse -> export -> parse）"""
    print("=== 測試往返轉換 ===\n")
    
    original_text = """
[@system] root: 測試系統
  desc: 系統描述
  
  [@feature1] feature: 功能1
    team: 團隊A
    
    [@story1] story: 故事1
      jira: TEST-001
      as_a: 使用者
      i_want: 登入
"""
    
    try:
        # Parse
        nodes1 = parse_usm_text(original_text)
        
        # Convert to DB format
        db_nodes = convert_usm_nodes_to_db_format(nodes1, map_id=1)
        
        # Export
        exported_text = export_to_usm_text(db_nodes)
        
        print("匯出的文字:\n")
        print(exported_text)
        
        # Parse again
        nodes2 = parse_usm_text(exported_text)
        
        # Compare
        if len(nodes1) == len(nodes2):
            print(f"\n✓ 節點數量一致: {len(nodes1)}")
        
        for n1, n2 in zip(nodes1, nodes2):
            if n1.node_id == n2.node_id and n1.title == n2.title:
                print(f"✓ 節點 {n1.node_id} 一致")
        
        print("\n✓ 往返轉換測試通過\n")
        return True
        
    except Exception as e:
        print(f"✗ 錯誤: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def main():
    """執行所有測試"""
    print("=" * 60)
    print("USM 文字格式解析器測試")
    print("=" * 60)
    print()
    
    tests = [
        test_basic_parsing,
        test_auto_id_generation,
        test_export,
        test_multiline_fields,
        test_related_nodes,
        test_error_handling,
        test_round_trip,
    ]
    
    results = []
    for test in tests:
        result = test()
        results.append(result)
    
    print("=" * 60)
    print(f"測試結果: {sum(results)}/{len(results)} 通過")
    print("=" * 60)
    
    if all(results):
        print("✓ 所有測試通過!")
        return 0
    else:
        print("✗ 部分測試失敗")
        return 1


if __name__ == '__main__':
    sys.exit(main())
