#!/bin/bash

echo "======================================"
echo "USM 文字格式 - 使用示範"
echo "======================================"
echo ""

echo "1. 查看範例檔案"
echo "--------------------------------------"
head -30 docs/usm_example_from_db.usm
echo "... (更多內容請參考完整檔案)"
echo ""

echo "2. 執行測試"
echo "--------------------------------------"
python test_usm_parser.py
echo ""

echo "3. 範例：從文字建立地圖"
echo "--------------------------------------"
cat << 'EXAMPLE' > /tmp/test_map.usm
[@ecommerce] root: 電商平台
  desc: 線上購物平台

  [@product_mgmt] feature: 商品管理
    team: 後端團隊
    
    [@add_product] story: 新增商品
      desc: 讓商家可以新增商品到系統
      jira: SHOP-001
      as_a: 商家
      i_want: 能夠新增商品
      so_that: 可以在平台上販售
      
  [@order_mgmt] feature: 訂單管理
    team: 後端團隊
    
    [@create_order] story: 建立訂單
      desc: 顧客可以建立新訂單
      jira: SHOP-010
      as_a: 顧客
      i_want: 能夠建立訂單
      related: @add_product
EXAMPLE

echo "已建立範例檔案：/tmp/test_map.usm"
echo ""
cat /tmp/test_map.usm
echo ""

echo "4. 使用 Python 解析"
echo "--------------------------------------"
python3 << 'PYCODE'
import sys
sys.path.insert(0, 'app')

from services.usm_text_parser import parse_usm_text

with open('/tmp/test_map.usm', 'r') as f:
    text = f.read()

nodes = parse_usm_text(text)

print(f"成功解析 {len(nodes)} 個節點：")
for node in nodes:
    indent = "  " * node.level
    print(f"{indent}- [{node.node_id}] {node.title}")
    if node.jira_tickets:
        print(f"{indent}  Jira: {', '.join(node.jira_tickets)}")
    if node.related_ids:
        print(f"{indent}  Related: {', '.join(node.related_ids)}")
PYCODE

echo ""
echo "======================================"
echo "✓ 示範完成"
echo "======================================"
