"""
資料庫表格模型定義

使用 SQLAlchemy 建立資料庫結構，包含 Team, TestCase, TestRun 表格
以及相關的關聯表格。
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum, Boolean, Float, UniqueConstraint, Index
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime
from typing import Optional

# 從現有的資料模型導入枚舉類型
from .lark_types import Priority, TestResultStatus
from .team import TeamStatus
from .test_run_config import TestRunStatus

Base = declarative_base()

class Team(Base):
    """團隊表格"""
    __tablename__ = "teams"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    
    # Lark 相關配置
    wiki_token = Column(String(255), nullable=False)
    test_case_table_id = Column(String(255), nullable=False)
    # 移除 test_run_table_id，改用 TestRunConfig 表格處理
    
    # JIRA 相關配置
    jira_project_key = Column(String(10), nullable=True)
    default_assignee = Column(String(255), nullable=True)
    issue_type = Column(String(50), default="Bug")
    
    # 團隊設定
    enable_notifications = Column(Boolean, default=True)
    auto_create_bugs = Column(Boolean, default=False)
    default_priority = Column(Enum(Priority), default=Priority.MEDIUM)
    
    # 狀態與時間
    status = Column(Enum(TeamStatus), default=TeamStatus.ACTIVE)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 統計資訊
    test_case_count = Column(Integer, default=0)
    last_sync_at = Column(DateTime, nullable=True)
    
    # 關聯關係
    test_run_configs = relationship("TestRunConfig", back_populates="team")


class TestRunConfig(Base):
    """測試執行配置表格"""
    __tablename__ = "test_run_configs"
    
    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    
    # 基本資訊
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    table_id = Column(String(255), nullable=True)
    
    # 測試執行元資料
    test_version = Column(String(50), nullable=True)
    test_environment = Column(String(100), nullable=True)
    build_number = Column(String(100), nullable=True)
    
    # 狀態與時間
    status = Column(Enum(TestRunStatus), default=TestRunStatus.DRAFT)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    
    # 統計資訊
    total_test_cases = Column(Integer, default=0)
    executed_cases = Column(Integer, default=0)
    passed_cases = Column(Integer, default=0)
    failed_cases = Column(Integer, default=0)
    
    # 系統欄位
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_sync_at = Column(DateTime, nullable=True)
    
    # 關聯關係
    team = relationship("Team", back_populates="test_run_configs")
    # 本地測試執行項目
    items = relationship("TestRunItem", back_populates="config", cascade="all, delete-orphan")


class TCGRecord(Base):
    """TCG 記錄表格"""
    __tablename__ = "tcg_records"
    
    # 使用 TCG 單號作為主鍵，避免重複
    tcg_number = Column(String(50), primary_key=True, index=True)
    record_id = Column(String(255), nullable=False, index=True)
    title = Column(Text, nullable=True)
    
    # 系統欄位
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TestRunItem(Base):
    """本地儲存的測試執行項目（來自本產品挑選的 Test Case）"""
    __tablename__ = "test_run_items"

    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    config_id = Column(Integer, ForeignKey("test_run_configs.id"), nullable=False, index=True)

    # 從 Test Case 複製的重要欄位（建立時擷取）
    test_case_number = Column(String(100), nullable=False, index=True)
    title = Column(Text, nullable=False)
    priority = Column(Enum(Priority), default=Priority.MEDIUM)
    precondition = Column(Text, nullable=True)
    steps = Column(Text, nullable=True)
    expected_result = Column(Text, nullable=True)

    # 執行資訊
    assignee_id = Column(String(64), nullable=True)
    assignee_name = Column(String(255), nullable=True)
    assignee_en_name = Column(String(255), nullable=True)
    assignee_email = Column(String(255), nullable=True)
    assignee_json = Column(Text, nullable=True)  # 原始 assignee 結構（JSON 字串）
    test_result = Column(Enum(TestResultStatus), nullable=True)
    executed_at = Column(DateTime, nullable=True)
    execution_duration = Column(Integer, nullable=True)
    # 注意：環境與版本屬於 TestRunConfig 層級，不在項目層儲存

    # 多值/關聯/原始欄位（JSON 字串保存）
    attachments_json = Column(Text, nullable=True)
    user_story_map_json = Column(Text, nullable=True)
    tcg_json = Column(Text, nullable=True)
    parent_record_json = Column(Text, nullable=True)
    raw_fields_json = Column(Text, nullable=True)

    # 系統欄位
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 關聯
    config = relationship("TestRunConfig", back_populates="items")

    __table_args__ = (
        UniqueConstraint('config_id', 'test_case_number', name='uq_test_run_item_config_case'),
        Index('ix_test_run_items_team', 'team_id'),
        Index('ix_test_run_items_result', 'test_result'),
        Index('ix_test_run_items_priority', 'priority'),
    )


# 建立資料庫表格的函數
def create_database_tables():
    """創建所有資料庫表格"""
    from app.database import engine
    Base.metadata.create_all(bind=engine)
    print("資料庫表格已創建完成")
