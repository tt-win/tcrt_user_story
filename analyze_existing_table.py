#!/usr/bin/env python3
"""
使用 jira_sync_v3 專案的 Lark Client 來分析表格結構
"""

import sys
import os
sys.path.append('/Users/hideman/code/jira_sync_v3')

from lark_client import LarkClient
import json
from pprint import pprint


def analyze_table():
    """分析表格結構"""
    
    # 使用實際的配置
    lark_client = LarkClient(
        app_id='cli_a8d1077685be102f',
        app_secret='***REMOVED***'
    )
    
    # 設定 wiki token
    wiki_token = 'Q4XxwaS2Cif80DkAku9lMKuAgof'
    lark_client.set_wiki_token(wiki_token)
    
    table_id = 'tbltzUlFtQPNX7t2'  # Test Run 表格
    
    print(f"正在分析表格 {table_id}...")
    print("-" * 60)
    
    try:
        # 1. 獲取欄位結構
        print("1. 獲取欄位結構...")
        fields = lark_client.get_table_fields(table_id)
        
        if fields:
            print(f"找到 {len(fields)} 個欄位：")
            for field in fields:
                field_name = field.get('field_name', 'Unknown')
                field_type = field.get('type', 'Unknown')
                field_id = field.get('field_id', 'Unknown')
                print(f"  - {field_name} ({field_type}) [{field_id}]")
        else:
            print("無法獲取欄位資訊")
            return
        
        # 2. 獲取記錄資料 (前3筆)
        print("\n2. 獲取記錄資料 (前3筆)...")
        records = lark_client.get_all_records(table_id)[:3]
        
        if records:
            print(f"找到 {len(records)} 筆記錄：")
            for i, record in enumerate(records, 1):
                print(f"\n記錄 {i}:")
                if 'fields' in record:
                    for field_id, value in record['fields'].items():
                        # 找對應的欄位名稱
                        field_name = field_id
                        for field in fields:
                            if field.get('field_id') == field_id:
                                field_name = field.get('field_name', field_id)
                                break
                        print(f"  {field_name}: {value}")
        
        # 3. 生成欄位分析報告
        print("\n" + "=" * 60)
        print("3. 欄位分析報告")
        print("=" * 60)
        
        for field in fields:
            field_name = field.get('field_name', 'Unknown')
            field_type = field.get('type', 'Unknown') 
            field_id = field.get('field_id', 'Unknown')
            property_info = field.get('property', {})
            
            print(f"\n欄位: {field_name}")
            print(f"  ID: {field_id}")
            print(f"  類型: {field_type}")
            
            if property_info:
                print(f"  屬性: {json.dumps(property_info, ensure_ascii=False, indent=4)}")
            
            # 從記錄中收集範例值
            sample_values = []
            for record in records:
                if 'fields' in record and field_id in record['fields']:
                    value = record['fields'][field_id]
                    if value not in sample_values:
                        sample_values.append(value)
            
            if sample_values:
                print(f"  範例值: {sample_values}")
        
        # 4. 生成 Pydantic 模型建議
        print("\n" + "=" * 60)
        print("4. TestRun 模型建議")
        print("=" * 60)
        
        print("class TestRun(BaseModel):")
        print('    """測試執行資料模型"""')
        
        for field in fields:
            field_name = field.get('field_name', 'Unknown')
            field_type = field.get('type', 'Unknown')
            field_id = field.get('field_id', 'Unknown')
            
            # 轉換成 Python 變數名
            var_name = field_name.lower().replace(' ', '_').replace('-', '_').replace('(', '').replace(')', '')
            
            # 根據 Lark 欄位類型推斷 Python 類型
            if field_type == 'Text':
                python_type = 'Optional[str]'
            elif field_type == 'Number':
                python_type = 'Optional[int]'
            elif field_type == 'SingleSelect':
                python_type = 'Optional[str]'  # 可以考慮用 Enum
            elif field_type == 'MultiSelect':
                python_type = 'List[str]'
            elif field_type == 'DateTime':
                python_type = 'Optional[datetime]'
            elif field_type == 'Checkbox':
                python_type = 'bool'
            elif field_type == 'User':
                python_type = 'Optional[str]'
            elif field_type == 'Url':
                python_type = 'Optional[str]'
            elif field_type == 'Attachment':
                python_type = 'List[Dict[str, Any]]'
            else:
                python_type = 'Optional[Any]'
            
            default_value = 'None'
            if field_type == 'MultiSelect':
                default_value = 'Field(default_factory=list)'
            elif field_type == 'Checkbox':
                default_value = 'False'
            else:
                default_value = 'None'
            
            print(f'    {var_name}: {python_type} = Field({default_value}, description="{field_name}")')
    
    except Exception as e:
        print(f"錯誤: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    analyze_table()