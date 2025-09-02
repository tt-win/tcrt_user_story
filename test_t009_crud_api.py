#!/usr/bin/env python3
"""
T009 Test Run Config CRUD API 測試腳本
測試 TP 票號在 Create、Read、Update 操作中的完整支援
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import os
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.database import get_db
from app.models.database_models import Base, Team as TeamDB, TestRunConfig as TestRunConfigDB
from app.models.test_run_config import TestRunStatus

# 建立測試資料庫
TEST_DB_FILE = "./test_t009_unique.db"
SQLALCHEMY_DATABASE_URL = f"sqlite:///{TEST_DB_FILE}"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 建立測試客戶端
client = TestClient(app)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

def setup_test_db():
    """設定測試資料庫"""
    # 清理現有的測試資料庫檔案
    if os.path.exists(TEST_DB_FILE):
        os.remove(TEST_DB_FILE)
    
    Base.metadata.create_all(bind=engine)
    
    # 建立測試團隊
    db = TestingSessionLocal()
    test_team = TeamDB(id=1, name="Test Team", description="測試團隊")
    db.add(test_team)
    db.commit()
    db.close()

def cleanup_test_db():
    """清理測試資料庫"""
    try:
        db = TestingSessionLocal()
        db.query(TestRunConfigDB).delete()
        db.query(TeamDB).delete()
        db.commit()
        db.close()
        Base.metadata.drop_all(bind=engine)
        
        # 刪除資料庫檔案
        if os.path.exists(TEST_DB_FILE):
            os.remove(TEST_DB_FILE)
    except Exception as e:
        pass  # 忽略清理錯誤

def test_create_config_with_tp_tickets():
    """測試建立配置包含 TP 票號"""
    setup_test_db()
    app.dependency_overrides[get_db] = override_get_db
    
    tp_tickets = ["TP-12345", "TP-67890", "TP-11111"]
    
    config_data = {
        "name": "測試配置 with TP",
        "description": "包含 TP 票號的測試配置",
        "test_version": "v1.0.0",
        "test_environment": "staging",
        "build_number": "build-123",
        "related_tp_tickets": tp_tickets,
        "status": "draft"
    }
    
    response = client.post("/api/teams/1/test-run-configs/", json=config_data)
    
    assert response.status_code == 201
    data = response.json()
    
    # 驗證基本欄位
    assert data['name'] == config_data['name']
    assert data['description'] == config_data['description']
    assert data['test_version'] == config_data['test_version']
    
    # 驗證 TP 票號正確返回
    assert data['related_tp_tickets'] == tp_tickets
    assert len(data['related_tp_tickets']) == 3
    
    # 驗證資料庫中的資料
    db = TestingSessionLocal()
    config_db = db.query(TestRunConfigDB).filter(TestRunConfigDB.id == data['id']).first()
    assert config_db is not None
    
    # 驗證 JSON 序列化
    assert config_db.related_tp_tickets_json == json.dumps(tp_tickets)
    
    # 驗證搜尋索引
    expected_search = " ".join(tp_tickets)
    assert config_db.tp_tickets_search == expected_search
    
    db.close()
    cleanup_test_db()
    app.dependency_overrides.clear()
    print("✅ 建立配置 (含 TP 票號) 測試通過")

def test_create_config_without_tp_tickets():
    """測試建立配置不含 TP 票號"""
    setup_test_db()
    app.dependency_overrides[get_db] = override_get_db
    
    config_data = {
        "name": "測試配置 without TP",
        "description": "不包含 TP 票號的測試配置",
        "status": "active"
    }
    
    response = client.post("/api/teams/1/test-run-configs/", json=config_data)
    
    assert response.status_code == 201
    data = response.json()
    
    # 驗證 TP 票號為空列表
    assert data['related_tp_tickets'] == []
    
    # 驗證資料庫中的資料
    db = TestingSessionLocal()
    config_db = db.query(TestRunConfigDB).filter(TestRunConfigDB.id == data['id']).first()
    assert config_db.related_tp_tickets_json is None
    assert config_db.tp_tickets_search is None
    
    db.close()
    cleanup_test_db()
    app.dependency_overrides.clear()
    print("✅ 建立配置 (不含 TP 票號) 測試通過")

def test_read_config_with_tp_tickets():
    """測試讀取配置包含 TP 票號"""
    setup_test_db()
    app.dependency_overrides[get_db] = override_get_db
    
    # 先建立配置
    tp_tickets = ["TP-99999", "TP-88888"]
    config_data = {
        "name": "讀取測試配置",
        "related_tp_tickets": tp_tickets
    }
    
    create_response = client.post("/api/teams/1/test-run-configs/", json=config_data)
    assert create_response.status_code == 201
    config_id = create_response.json()['id']
    
    # 測試單個配置讀取
    response = client.get(f"/api/teams/1/test-run-configs/{config_id}")
    
    assert response.status_code == 200
    data = response.json()
    assert data['related_tp_tickets'] == tp_tickets
    
    # 測試列表讀取 (摘要格式)
    list_response = client.get("/api/teams/1/test-run-configs/")
    
    assert list_response.status_code == 200
    configs = list_response.json()
    assert len(configs) == 1
    
    # 驗證摘要中的 TP 票號資訊
    summary = configs[0]
    assert summary['related_tp_tickets'] == tp_tickets
    assert summary['tp_tickets_count'] == 2
    
    cleanup_test_db()
    app.dependency_overrides.clear()
    print("✅ 讀取配置 (含 TP 票號) 測試通過")

def test_update_config_tp_tickets():
    """測試更新配置的 TP 票號"""
    setup_test_db()
    app.dependency_overrides[get_db] = override_get_db
    
    # 建立初始配置
    initial_tp_tickets = ["TP-11111"]
    config_data = {
        "name": "更新測試配置",
        "related_tp_tickets": initial_tp_tickets
    }
    
    create_response = client.post("/api/teams/1/test-run-configs/", json=config_data)
    assert create_response.status_code == 201
    config_id = create_response.json()['id']
    
    # 更新 TP 票號
    updated_tp_tickets = ["TP-22222", "TP-33333", "TP-44444"]
    update_data = {
        "related_tp_tickets": updated_tp_tickets,
        "description": "已更新的描述"
    }
    
    response = client.put(f"/api/teams/1/test-run-configs/{config_id}", json=update_data)
    
    assert response.status_code == 200
    data = response.json()
    
    # 驗證更新後的 TP 票號
    assert data['related_tp_tickets'] == updated_tp_tickets
    assert data['description'] == update_data['description']
    
    # 驗證資料庫中的更新
    db = TestingSessionLocal()
    config_db = db.query(TestRunConfigDB).filter(TestRunConfigDB.id == config_id).first()
    assert config_db.related_tp_tickets_json == json.dumps(updated_tp_tickets)
    assert config_db.tp_tickets_search == " ".join(updated_tp_tickets)
    
    db.close()
    cleanup_test_db()
    app.dependency_overrides.clear()
    print("✅ 更新配置 TP 票號測試通過")

def test_update_config_clear_tp_tickets():
    """測試清空配置的 TP 票號"""
    setup_test_db()
    app.dependency_overrides[get_db] = override_get_db
    
    # 建立包含 TP 票號的配置
    config_data = {
        "name": "清空測試配置",
        "related_tp_tickets": ["TP-12345", "TP-67890"]
    }
    
    create_response = client.post("/api/teams/1/test-run-configs/", json=config_data)
    config_id = create_response.json()['id']
    
    # 清空 TP 票號
    update_data = {
        "related_tp_tickets": []
    }
    
    response = client.put(f"/api/teams/1/test-run-configs/{config_id}", json=update_data)
    
    assert response.status_code == 200
    data = response.json()
    assert data['related_tp_tickets'] == []
    
    # 驗證資料庫中清空
    db = TestingSessionLocal()
    config_db = db.query(TestRunConfigDB).filter(TestRunConfigDB.id == config_id).first()
    assert config_db.related_tp_tickets_json is None
    assert config_db.tp_tickets_search is None
    
    db.close()
    cleanup_test_db()
    app.dependency_overrides.clear()
    print("✅ 清空 TP 票號測試通過")

def test_partial_update_without_tp_tickets():
    """測試部分更新不影響 TP 票號"""
    setup_test_db()
    app.dependency_overrides[get_db] = override_get_db
    
    # 建立包含 TP 票號的配置
    original_tp_tickets = ["TP-99999"]
    config_data = {
        "name": "部分更新測試",
        "description": "原始描述",
        "related_tp_tickets": original_tp_tickets
    }
    
    create_response = client.post("/api/teams/1/test-run-configs/", json=config_data)
    config_id = create_response.json()['id']
    
    # 僅更新描述，不碰 TP 票號
    update_data = {
        "description": "更新後的描述"
    }
    
    response = client.put(f"/api/teams/1/test-run-configs/{config_id}", json=update_data)
    
    assert response.status_code == 200
    data = response.json()
    assert data['description'] == "更新後的描述"
    assert data['related_tp_tickets'] == original_tp_tickets  # TP 票號應該保持不變
    
    cleanup_test_db()
    app.dependency_overrides.clear()
    print("✅ 部分更新 (不影響 TP 票號) 測試通過")

def test_restart_config_copies_tp_tickets():
    """測試重啟配置時複製 TP 票號"""
    setup_test_db()
    app.dependency_overrides[get_db] = override_get_db
    
    # 建立包含 TP 票號的配置
    original_tp_tickets = ["TP-RESTART-1", "TP-RESTART-2"]
    config_data = {
        "name": "重啟測試配置",
        "related_tp_tickets": original_tp_tickets
    }
    
    create_response = client.post("/api/teams/1/test-run-configs/", json=config_data)
    config_id = create_response.json()['id']
    
    # 重啟配置
    restart_data = {
        "mode": "all",
        "name": "重啟後的配置"
    }
    
    response = client.post(f"/api/teams/1/test-run-configs/{config_id}/restart", json=restart_data)
    
    assert response.status_code == 200
    restart_result = response.json()
    new_config_id = restart_result['new_config_id']
    
    # 驗證新配置包含相同的 TP 票號
    new_config_response = client.get(f"/api/teams/1/test-run-configs/{new_config_id}")
    new_config_data = new_config_response.json()
    
    assert new_config_data['related_tp_tickets'] == original_tp_tickets
    assert new_config_data['name'] == "重啟後的配置"
    
    cleanup_test_db()
    app.dependency_overrides.clear()
    print("✅ 重啟配置複製 TP 票號測試通過")

def test_statistics_includes_tp_tickets():
    """測試統計資訊包含 TP 票號統計"""
    setup_test_db()
    app.dependency_overrides[get_db] = override_get_db
    
    # 建立多個配置，部分包含 TP 票號
    configs = [
        {"name": "Config 1", "related_tp_tickets": ["TP-1", "TP-2"]},
        {"name": "Config 2", "related_tp_tickets": ["TP-3"]},
        {"name": "Config 3", "related_tp_tickets": []},  # 空 TP 票號
        {"name": "Config 4"}  # 無 TP 票號欄位
    ]
    
    for config in configs:
        response = client.post("/api/teams/1/test-run-configs/", json=config)
        assert response.status_code == 201
    
    # 取得統計資訊
    stats_response = client.get("/api/teams/1/test-run-configs/statistics")
    
    assert stats_response.status_code == 200
    stats = stats_response.json()
    
    # 驗證 TP 票號統計
    assert stats['total_configs'] == 4
    assert stats['configs_with_tp_tickets'] == 2  # 只有 Config 1 和 2 有 TP 票號
    assert stats['total_tp_tickets'] == 3  # TP-1, TP-2, TP-3
    assert stats['average_tp_per_config'] == 0.75  # 3 tickets / 4 configs
    
    cleanup_test_db()
    app.dependency_overrides.clear()
    print("✅ 統計資訊包含 TP 票號測試通過")

def test_json_serialization_edge_cases():
    """測試 JSON 序列化的邊緣情況"""
    setup_test_db()
    app.dependency_overrides[get_db] = override_get_db
    
    # 測試各種邊緣情況
    test_cases = [
        {"name": "Empty list", "related_tp_tickets": []},
        {"name": "Single ticket", "related_tp_tickets": ["TP-SINGLE"]},
        {"name": "Many tickets", "related_tp_tickets": [f"TP-{i}" for i in range(1, 51)]}  # 50個票號
    ]
    
    for test_case in test_cases:
        response = client.post("/api/teams/1/test-run-configs/", json=test_case)
        assert response.status_code == 201
        
        data = response.json()
        assert data['related_tp_tickets'] == test_case['related_tp_tickets']
        
        # 驗證資料庫序列化正確
        db = TestingSessionLocal()
        config_db = db.query(TestRunConfigDB).filter(TestRunConfigDB.id == data['id']).first()
        
        if test_case['related_tp_tickets']:
            expected_json = json.dumps(test_case['related_tp_tickets'])
            expected_search = " ".join(test_case['related_tp_tickets'])
            assert config_db.related_tp_tickets_json == expected_json
            assert config_db.tp_tickets_search == expected_search
        else:
            assert config_db.related_tp_tickets_json is None
            assert config_db.tp_tickets_search is None
        
        db.close()
    
    cleanup_test_db()
    app.dependency_overrides.clear()
    print("✅ JSON 序列化邊緣情況測試通過")

def run_all_tests():
    """執行所有測試"""
    print("🧪 開始執行 T009 Test Run Config CRUD API 測試...")
    print("=" * 70)
    
    try:
        test_create_config_with_tp_tickets()
        test_create_config_without_tp_tickets()
        test_read_config_with_tp_tickets()
        test_update_config_tp_tickets()
        test_update_config_clear_tp_tickets()
        test_partial_update_without_tp_tickets()
        test_restart_config_copies_tp_tickets()
        test_statistics_includes_tp_tickets()
        test_json_serialization_edge_cases()
        
        print("=" * 70)
        print("🎉 所有測試通過！T009 CRUD API 實作成功")
        print("✨ 功能驗證:")
        print("  • Create 操作正確處理 TP 票號序列化")
        print("  • Read 操作正確反序列化 TP 票號")
        print("  • Update 操作支援部分/完整 TP 票號更新")
        print("  • Restart 操作正確複製 TP 票號")
        print("  • 摘要格式包含 TP 票號統計")
        print("  • 統計資訊包含完整 TP 票號分析")
        print("  • JSON 序列化/搜尋索引同步機制")
        print("  • 邊緣情況處理 (空列表、單票號、大量票號)")
        return True
        
    except Exception as e:
        print(f"❌ 測試失敗: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)