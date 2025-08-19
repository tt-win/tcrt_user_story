#!/usr/bin/env python3
"""
臨時腳本：分析 Lark 測試案例表格的欄位結構
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.services.lark_client import LarkAuthManager, LarkTableManager, LarkRecordManager
import json
from pprint import pprint


def analyze_lark_table():
    """分析 Lark 表格結構"""
    
    # 初始化認證管理器
    auth_manager = LarkAuthManager()
    
    # 從 URL 提取資訊
    wiki_token = "Q4XxwaS2Cif80DkAku9lMKuAgof"
    table_id = "tbl4SVQt73VfL690"
    
    print(f"正在分析 Lark 表格...")
    print(f"Wiki Token: {wiki_token}")
    print(f"Table ID: {table_id}")
    print("-" * 60)
    
    # 初始化表格管理器
    table_manager = LarkTableManager(auth_manager)
    
    try:
        # 1. 先將 wiki_token 轉換為 obj_token
        print("1. 解析 Wiki Token...")
        obj_token = table_manager.get_obj_token(wiki_token)
        if not obj_token:
            print("無法解析 wiki_token 為 obj_token")
            return
        print(f"Obj Token: {obj_token}")
        
        # 2. 獲取表格欄位資訊
        print("2. 獲取表格欄位資訊...")
        # 直接測試API調用
        token = auth_manager.get_tenant_access_token()
        print(f"Access Token: {token[:20]}...")
        
        import requests
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        
        # 測試不同的API路徑
        api_urls = [
            f"https://open.larksuite.com/open-apis/bitable/v1/apps/{obj_token}/tables/{table_id}/fields",
            f"https://open.larksuite.com/open-apis/bitable/v1/apps/{obj_token}/tables/{table_id}",
            f"https://open.larksuite.com/open-apis/bitable/v1/apps/{obj_token}/tables"
        ]
        
        for i, url in enumerate(api_urls, 1):
            print(f"測試API {i}: {url}")
            response = requests.get(url, headers=headers, timeout=30)
            print(f"  狀態碼: {response.status_code}")
            if response.status_code == 200:
                result = response.json()
                if result.get('code') == 0:
                    print(f"  成功！資料長度: {len(str(result))}")
                    if i == 1:  # 欄位API
                        fields = result.get('data', {}).get('items', [])
                        print(f"  找到 {len(fields)} 個欄位")
                    break
                else:
                    print(f"  API錯誤: {result.get('msg')} (code: {result.get('code')})")
            else:
                error_text = response.text[:200]
                print(f"  HTTP錯誤: {error_text}")
        
        # 如果以上都失敗，使用原來的方法
        fields = table_manager.get_table_fields(table_id, wiki_token)
        
        if fields:
            print(f"找到 {len(fields)} 個欄位：")
            for field in fields:
                print(f"  - {field.get('field_name', 'Unknown')}: {field.get('type', 'Unknown')} ({field.get('field_id', 'No ID')})")
                if field.get('property'):
                    print(f"    屬性: {field['property']}")
            print()
        else:
            print("無法獲取欄位資訊")
            return
        
        # 3. 獲取記錄資料 (前5筆)
        print("3. 獲取記錄資料 (前5筆)...")
        record_manager = LarkRecordManager(auth_manager)
        
        records = record_manager.get_all_records(table_id, wiki_token)[:5]
        
        if records:
            print(f"找到 {len(records)} 筆記錄：")
            for i, record in enumerate(records, 1):
                print(f"\n記錄 {i}:")
                print(f"  Record ID: {record.get('record_id', 'Unknown')}")
                
                # 顯示欄位值
                if 'fields' in record:
                    for field_id, value in record['fields'].items():
                        # 找到對應的欄位名稱
                        field_name = "Unknown"
                        for field in fields:
                            if field.get('field_id') == field_id:
                                field_name = field.get('field_name', 'Unknown')
                                break
                        
                        print(f"    {field_name} ({field_id}): {value}")
        else:
            print("無法獲取記錄資料")
        
        # 4. 產生欄位結構分析
        print("\n" + "=" * 60)
        print("4. 欄位結構分析")
        print("=" * 60)
        
        field_analysis = {}
        for field in fields:
            field_name = field.get('field_name', 'Unknown')
            field_type = field.get('type', 'Unknown')
            field_id = field.get('field_id', 'Unknown')
            
            field_analysis[field_name] = {
                'field_id': field_id,
                'type': field_type,
                'property': field.get('property', {}),
                'sample_values': []
            }
        
        # 收集範例資料
        if records:
            for record in records:
                if 'fields' in record:
                    for field_id, value in record['fields'].items():
                        # 找到對應的欄位
                        for field_name, field_info in field_analysis.items():
                            if field_info['field_id'] == field_id:
                                if value not in field_info['sample_values']:
                                    field_info['sample_values'].append(value)
                                break
        
        # 輸出完整分析
        print("\n完整欄位分析:")
        for field_name, field_info in field_analysis.items():
            print(f"\n欄位: {field_name}")
            print(f"  ID: {field_info['field_id']}")
            print(f"  類型: {field_info['type']}")
            print(f"  屬性: {json.dumps(field_info['property'], ensure_ascii=False, indent=4)}")
            print(f"  範例值: {field_info['sample_values'][:3]}")  # 只顯示前3個範例
        
        # 5. 產生 Pydantic 模型建議
        print("\n" + "=" * 60)
        print("5. Pydantic 模型建議")
        print("=" * 60)
        
        print("根據分析結果，建議的 TestCase 模型欄位：\n")
        
        type_mapping = {
            'Text': 'str',
            'Number': 'int',
            'SingleSelect': 'str',  # 使用 Enum
            'MultiSelect': 'List[str]',
            'DateTime': 'Optional[datetime]',
            'Checkbox': 'bool',
            'URL': 'str',
            'Attachment': 'List[Attachment]',
            'Formula': 'str',  # 通常是計算欄位
            'User': 'str',  # 使用者ID或名稱
        }
        
        for field_name, field_info in field_analysis.items():
            field_type = field_info['type']
            python_type = type_mapping.get(field_type, 'Any')
            
            # 基於欄位名稱調整類型
            if 'date' in field_name.lower() or 'time' in field_name.lower():
                python_type = 'Optional[datetime]'
            elif field_name.lower() in ['id', 'number', 'count']:
                python_type = 'Optional[int]'
            elif 'url' in field_name.lower() or 'link' in field_name.lower():
                python_type = 'Optional[str]'
            
            field_var_name = field_name.lower().replace(' ', '_').replace('-', '_')
            print(f"    {field_var_name}: {python_type} = Field(None, description=\"{field_name}\")")
        
    except Exception as e:
        print(f"錯誤: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    analyze_lark_table()