"""
資料庫表格模型定義

使用 SQLAlchemy 建立資料庫結構，包含 Team, TestCase, TestRun 表格
以及相關的關聯表格。
"""

import hashlib
import logging

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
    Enum,
    Boolean,
    Float,
    UniqueConstraint,
    Index,
    CheckConstraint,
    select,
    func,
    event,
)
from sqlalchemy.orm import relationship, declarative_base, column_property
from datetime import datetime
from enum import Enum as PyEnum

# 從現有的資料模型導入枚舉類型
from .lark_types import Priority, TestResultStatus
from .team import TeamStatus
from .test_run_config import TestRunStatus
from .test_run_set import TestRunSetStatus

# 導入認證相關枚舉
from ..auth.models import UserRole, PermissionType
from ..db_types import MediumText as Text, medium_text_type

Base = declarative_base()


def qa_ai_helper_large_text_type() -> Text:
    """QA AI Helper 大型 JSON payload 欄位型別。

    SQLite / PostgreSQL 保持一般 Text；MySQL 提升為 MEDIUMTEXT，
    避免大型 Jira ticket 或 draft payload 超過 64KB TEXT 限制。
    """

    return medium_text_type()


class SyncStatus(PyEnum):
    """本地與遠端（Lark）同步狀態"""

    SYNCED = "synced"
    PENDING = "pending"  # 本地有變更，待推送到 Lark
    CONFLICT = "conflict"  # 本地與遠端同時修改，需人工處理


class MCPMachineCredentialStatus(PyEnum):
    """MCP 機器憑證狀態"""

    ACTIVE = "active"
    REVOKED = "revoked"


class TeamAppTokenStatus(PyEnum):
    """Team app token 憑證狀態"""

    ACTIVE = "active"
    REVOKED = "revoked"


class AutomationProviderSlot(PyEnum):
    """Automation Hub provider slot"""

    STORAGE = "storage"
    CI = "ci"
    RESULT = "result"


class AutomationScriptFormat(PyEnum):
    """Automation script format"""

    PLAYWRIGHT_PY_ASYNC = "PLAYWRIGHT_PY_ASYNC"
    PYTEST = "PYTEST"
    PLAYWRIGHT_JS = "PLAYWRIGHT_JS"
    OTHER = "OTHER"


class AutomationScriptLinkType(PyEnum):
    """Automation script to test case relationship type"""

    PRIMARY = "PRIMARY"
    COVERS = "COVERS"
    REFERENCES = "REFERENCES"


class AutomationScriptGroupJobType(PyEnum):
    """Automation script group CI job type"""

    JENKINS = "JENKINS"


class AutomationRunStatus(PyEnum):
    """Automation run status mirrored from external CI"""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class AutomationRunTrigger(PyEnum):
    """Automation run trigger source"""

    USER = "USER"
    WEBHOOK = "WEBHOOK"
    SCHEDULE = "SCHEDULE"
    MCP = "MCP"


class AutomationWebhookDirection(PyEnum):
    """Automation webhook direction"""

    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class Team(Base):
    """團隊表格"""

    __tablename__ = "teams"

    id = Column(Integer, primary_key=True)
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
    enable_notifications = Column(Boolean, default=True, nullable=False)
    auto_create_bugs = Column(Boolean, default=False, nullable=False)
    default_priority = Column(Enum(Priority, values_callable=lambda values: [item.value for item in values], native_enum=False), default=Priority.MEDIUM)

    # 狀態與時間
    status = Column(Enum(TeamStatus, values_callable=lambda values: [item.value for item in values], native_enum=False), default=TeamStatus.ACTIVE)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 統計資訊
    test_case_count = Column(Integer, default=0)
    last_sync_at = Column(DateTime, nullable=True)

    # 關聯關係
    test_run_configs = relationship("TestRunConfig", back_populates="team")
    test_run_sets = relationship("TestRunSet", back_populates="team")
    test_case_sets = relationship("TestCaseSet", backref="team", cascade="all, delete-orphan")


class TestRunConfig(Base):
    """測試執行配置表格"""

    __tablename__ = "test_run_configs"

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)

    # 基本資訊
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)

    # 測試執行元資料
    test_version = Column(String(50), nullable=True)
    test_environment = Column(String(100), nullable=True)
    build_number = Column(String(100), nullable=True)

    # TP 開發單票號欄位
    related_tp_tickets_json = Column(Text, nullable=True, comment="相關 JIRA Tickets 票號 JSON 陣列")
    tp_tickets_search = Column(String(512), nullable=True, index=True, comment="JIRA Ticket 搜尋索引欄位")
    test_case_set_ids_json = Column(Text, nullable=True, comment="Test Case Set 範圍（JSON 陣列）")

    # 通知設定
    notifications_enabled = Column(Boolean, default=False, nullable=False, comment="是否啟用通知")
    notify_chat_ids_json = Column(Text, nullable=True, comment="選擇的 Lark chat IDs（JSON 陣列）")
    notify_chat_names_snapshot = Column(Text, nullable=True, comment="群組名稱快照（JSON 陣列）")
    notify_chats_search = Column(String(512), nullable=True, index=True, comment="群組名稱搜尋索引")

    # 狀態與時間
    status = Column(Enum(TestRunStatus, values_callable=lambda values: [item.value for item in values], native_enum=False), default=TestRunStatus.DRAFT)
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
    set_membership = relationship(
        "TestRunSetMembership",
        back_populates="config",
        uselist=False,
    )


class TestRunSet(Base):
    """測試執行集合表格"""

    __tablename__ = "test_run_sets"

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(Enum(TestRunSetStatus, values_callable=lambda values: [item.value for item in values], native_enum=False), default=TestRunSetStatus.ACTIVE, nullable=False)
    archived_at = Column(DateTime, nullable=True)
    related_tp_tickets_json = Column(Text, nullable=True, comment="相關 JIRA Tickets 票號 JSON 陣列")
    tp_tickets_search = Column(String(512), nullable=True, index=True, comment="JIRA Ticket 搜尋索引欄位")
    automation_suite_ids_json = Column(
        Text,
        nullable=True,
        comment=(
            "Automation Suites that this Test Run Set can trigger via the "
            "Run-as-Automation entry point. JSON array of automation_script_groups.id. "
            "Stored as text because SQLite/PG have no native int[] support; "
            "serialized/deserialized in Pydantic schemas (TestRunSetBase). "
            "See move-automation-execution-to-test-run-set."
        ),
    )
    default_automation_environment = Column(
        String(60),
        nullable=True,
        comment=(
            "Default automation environment name (matching an "
            "automation_environments.name for this team) preselected when "
            "triggering run-automation. NULL = no default. "
            "See manage-automation-environment-configs."
        ),
    )
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    team = relationship("Team", back_populates="test_run_sets")
    memberships = relationship(
        "TestRunSetMembership",
        back_populates="test_run_set",
        cascade="all, delete-orphan",
    )


class TestRunSetMembership(Base):
    """測試執行集合成員關聯表格"""

    __tablename__ = "test_run_set_memberships"
    __table_args__ = (
        UniqueConstraint("config_id", name="uq_test_run_set_membership_config"),
        Index("ix_test_run_set_memberships_team_config", "team_id", "config_id"),
        Index("ix_test_run_set_memberships_team_set", "team_id", "set_id"),
    )

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    set_id = Column(Integer, ForeignKey("test_run_sets.id", ondelete="CASCADE"), nullable=False)
    config_id = Column(Integer, ForeignKey("test_run_configs.id", ondelete="CASCADE"), nullable=False)
    position = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    test_run_set = relationship("TestRunSet", back_populates="memberships")
    config = relationship("TestRunConfig", back_populates="set_membership")


class TestRunItem(Base):
    """本地儲存的測試執行項目（來自本產品挑選的 Test Case）"""

    __tablename__ = "test_run_items"

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    config_id = Column(Integer, ForeignKey("test_run_configs.id"), nullable=False, index=True)

    # 使用 Test Case 編號建立唯一識別，其他詳情從 Test Case 讀取
    test_case_number = Column(String(100), nullable=False, index=True)

    # 執行資訊
    assignee_id = Column(String(64), nullable=True)
    assignee_name = Column(String(255), nullable=True)
    assignee_en_name = Column(String(255), nullable=True)
    assignee_email = Column(String(255), nullable=True)
    assignee_json = Column(Text, nullable=True)  # 原始 assignee 結構（JSON 字串）
    test_result = Column(Enum(TestResultStatus, values_callable=lambda values: [item.value for item in values], native_enum=False), nullable=True)
    executed_at = Column(DateTime, nullable=True)
    execution_duration = Column(Integer, nullable=True)
    # 注意：環境與版本屬於 TestRunConfig 層級，不在項目層儲存

    # 多值/關聯/原始欄位（JSON 字串保存）
    attachments_json = Column(Text, nullable=True)
    execution_results_json = Column(Text, nullable=True)
    user_story_map_json = Column(Text, nullable=True)
    tcg_json = Column(Text, nullable=True)
    parent_record_json = Column(Text, nullable=True)
    raw_fields_json = Column(Text, nullable=True)
    bug_tickets_json = Column(Text, nullable=True)  # Bug Tickets（JSON Array 格式存多個 JIRA ticket 編號）

    # 結果檔案追蹤欄位
    result_files_uploaded = Column(
        Boolean, default=False, nullable=False, comment="測試結果檔案是否已上傳到對應 Test Case"
    )
    result_files_count = Column(Integer, default=0, nullable=False, comment="上傳的結果檔案數量")
    upload_history_json = Column(Text, nullable=True, comment="檔案上傳歷史記錄（JSON 格式）")

    # 系統欄位
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 關聯
    config = relationship("TestRunConfig", back_populates="items")
    # 歷程關聯（若存在）
    histories = relationship("TestRunItemResultHistory", back_populates="item", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("config_id", "test_case_number", name="uq_test_run_item_config_case"),
        Index("ix_test_run_items_team", "team_id"),
        Index("ix_test_run_items_result", "test_result"),
        Index("ix_test_run_items_files_uploaded", "result_files_uploaded"),
    )

    # 只讀關聯：提供即時 Test Case 詳細資料
    test_case = relationship(
        "TestCaseLocal",
        primaryjoin="and_(TestRunItem.test_case_number == foreign(TestCaseLocal.test_case_number), "
        "TestRunItem.team_id == foreign(TestCaseLocal.team_id))",
        viewonly=True,
        uselist=False,
    )


class TestRunItemResultHistory(Base):
    """測試結果歷程表"""

    __tablename__ = "test_run_item_result_history"

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False, index=True)
    config_id = Column(Integer, ForeignKey("test_run_configs.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("test_run_items.id", ondelete="CASCADE"), nullable=False, index=True)

    prev_result = Column(Enum(TestResultStatus, values_callable=lambda values: [item.value for item in values], native_enum=False), nullable=True)
    new_result = Column(Enum(TestResultStatus, values_callable=lambda values: [item.value for item in values], native_enum=False), nullable=True)
    prev_executed_at = Column(DateTime, nullable=True)
    new_executed_at = Column(DateTime, nullable=True)

    changed_by_id = Column(String(64), nullable=True)
    changed_by_name = Column(String(255), nullable=True)
    change_source = Column(String(32), nullable=True)  # single, batch, api, sync, revert
    change_reason = Column(Text, nullable=True)
    changed_at = Column(DateTime, default=datetime.utcnow, index=True)

    # 關聯
    item = relationship("TestRunItem", back_populates="histories")

    __table_args__ = (
        Index("ix_result_history_team_config", "team_id", "config_id"),
        Index("ix_result_history_item_time", "item_id", "changed_at"),
    )


class LarkDepartment(Base):
    """Lark 部門信息表"""

    __tablename__ = "lark_departments"

    # 主鍵使用 Lark 部門 ID
    department_id = Column(String(100), primary_key=True)
    parent_department_id = Column(String(100), nullable=True, index=True)

    # 組織層級
    level = Column(Integer, default=0, index=True)
    path = Column(Text, nullable=True)  # 部門路徑，如: /root/dept1/dept2

    # Lark 部門屬性（JSON 存儲原始 API 響應）
    leaders_json = Column(Text, nullable=True)  # 部門領導信息
    group_chat_employee_types_json = Column(Text, nullable=True)  # 群聊員工類型

    # 統計信息
    direct_user_count = Column(Integer, default=0)  # 直屬用戶數
    total_user_count = Column(Integer, default=0)  # 總用戶數（包含子部門）

    # 狀態與時間
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_sync_at = Column(DateTime, nullable=True)

    # 關聯關係
    users = relationship("LarkUser", back_populates="primary_department")

    # 索引
    __table_args__ = (Index("ix_lark_dept_status", "status"),)


class TestCaseSet(Base):
    """測試案例集合表格

    用於組織測試案例，每個 Team 可以有多個 Test Case Set。
    """

    __tablename__ = "test_case_sets"
    __table_args__ = (
        UniqueConstraint("name", name="uq_test_case_set_name"),  # 全域名稱唯一
        Index("ix_test_case_sets_team", "team_id"),
    )

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)  # 全域唯一名稱
    description = Column(Text, nullable=True)
    is_default = Column(Boolean, default=False, nullable=False)  # 標記為預設 Set

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 關聯關係
    sections = relationship("TestCaseSection", back_populates="test_case_set", cascade="all, delete-orphan")
    test_cases = relationship("TestCaseLocal", back_populates="test_case_set")


class TestCaseSection(Base):
    """測試案例區段表格

    在 Test Case Set 內建立巢狀結構，類似資料夾分類。
    最多 5 層深度。
    """

    __tablename__ = "test_case_sections"
    __table_args__ = (
        UniqueConstraint(
            "test_case_set_id", "parent_section_id", "name", name="uq_section_name_in_parent"
        ),  # 同層級不可重複名稱
        Index("ix_sections_set_parent", "test_case_set_id", "parent_section_id"),
        Index("ix_sections_set_level", "test_case_set_id", "level"),
    )

    id = Column(Integer, primary_key=True)
    test_case_set_id = Column(Integer, ForeignKey("test_case_sets.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)

    # 巢狀結構
    parent_section_id = Column(Integer, ForeignKey("test_case_sections.id", ondelete="CASCADE"), nullable=True)
    level = Column(Integer, default=1, nullable=False)  # 1-5，表示深度
    sort_order = Column(Integer, default=0, nullable=False)  # 同層級排序

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 關聯關係
    test_case_set = relationship("TestCaseSet", back_populates="sections", foreign_keys=[test_case_set_id])
    parent_section = relationship(
        "TestCaseSection", remote_side=[id], foreign_keys=[parent_section_id], backref="child_sections"
    )
    test_cases = relationship("TestCaseLocal", back_populates="test_case_section")


class TestCaseLocal(Base):
    """測試案例本地中介資料表

    作為所有對 Lark Test Case 表的操作中介層，支援本地 upsert/update、索引查詢與差異同步。
    """

    __tablename__ = "test_cases"

    # 主鍵與關聯
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False, index=True)

    # Test Case Set 與 Section 關聯
    test_case_set_id = Column(Integer, ForeignKey("test_case_sets.id"), nullable=False, index=True)
    test_case_section_id = Column(Integer, ForeignKey("test_case_sections.id"), nullable=True)

    # 與 Lark 的關聯鍵
    lark_record_id = Column(String(255), nullable=True, unique=True, index=True)

    # 核心欄位
    test_case_number = Column(String(100), nullable=False)
    title = Column(Text, nullable=False)
    priority = Column(Enum(Priority, values_callable=lambda values: [item.value for item in values], native_enum=False), default=Priority.MEDIUM)
    precondition = Column(Text, nullable=True)
    steps = Column(Text, nullable=True)
    expected_result = Column(Text, nullable=True)

    # 測試結果與人員（對應 Lark 欄位，必要時使用 JSON 紀錄詳細結構）
    test_result = Column(Enum(TestResultStatus, values_callable=lambda values: [item.value for item in values], native_enum=False), nullable=True)
    assignee_json = Column(Text, nullable=True)

    # 關聯與多值欄位（JSON 字串保存）
    attachments_json = Column(Text, nullable=True)
    test_results_files_json = Column(Text, nullable=True)
    user_story_map_json = Column(Text, nullable=True)
    tcg_json = Column(Text, nullable=True)
    parent_record_json = Column(Text, nullable=True)
    raw_fields_json = Column(Text, nullable=True)
    test_data_json = Column(Text, nullable=True)

    # 版本與同步控制
    sync_status = Column(Enum(SyncStatus, values_callable=lambda values: [item.value for item in values], native_enum=False), default=SyncStatus.SYNCED, nullable=False, index=True)
    local_version = Column(Integer, default=1, nullable=False)
    lark_version = Column(Integer, nullable=True)
    checksum = Column(String(64), nullable=True, index=True)  # 可用來快速比較內容變更（例如 sha256 前 64）

    # 時間欄位策略
    # 注意：除初始同步（init）外，created_at/updated_at 以本地為主，不從 Lark 覆蓋
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    last_sync_at = Column(DateTime, nullable=True)

    # 保留 Lark 系統時間戳做為參考（毫秒 epoch 轉換後的 UTC）
    lark_created_at = Column(DateTime, nullable=True)
    lark_updated_at = Column(DateTime, nullable=True)

    # 關聯關係
    test_case_set = relationship("TestCaseSet", back_populates="test_cases")
    test_case_section = relationship("TestCaseSection", back_populates="test_cases")

    __table_args__ = (
        UniqueConstraint("team_id", "test_case_number", name="uq_test_cases_team_case_number"),
        Index("ix_test_cases_team_result", "team_id", "test_result"),
        Index("ix_test_cases_team_priority", "team_id", "priority"),
        Index("ix_test_cases_number", "test_case_number"),
        Index("ix_test_cases_set_section", "test_case_set_id", "test_case_section_id"),
    )


class QAAIHelperPromptProfile(Base):
    """Team-scoped custom style instructions for QA AI Helper prompt generation."""

    __tablename__ = "qa_ai_helper_prompt_profiles"
    __table_args__ = (
        UniqueConstraint("team_id", "name", name="uq_qa_ai_helper_prompt_profile_team_name"),
        Index("ix_qa_ai_helper_prompt_profiles_team_default", "team_id", "is_default"),
    )

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    testcase_instructions = Column(qa_ai_helper_large_text_type(), nullable=True)
    is_default = Column(Boolean, nullable=False, default=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    team = relationship("Team")


class QAAIHelperSession(Base):
    """Rewritten QA AI Helper session root."""

    __tablename__ = "qa_ai_helper_sessions"
    __table_args__ = (
        Index("ix_qa_ai_helper_sessions_team_status", "team_id", "status"),
        Index("ix_qa_ai_helper_sessions_team_updated", "team_id", "updated_at"),
        Index("ix_qa_ai_helper_sessions_ticket_key", "ticket_key"),
    )

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False, index=True)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    target_test_case_set_id = Column(
        Integer,
        ForeignKey("test_case_sets.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    ticket_key = Column(String(64), nullable=True, index=True)
    include_comments = Column(Boolean, nullable=False, default=False)
    output_locale = Column(String(16), nullable=False, default="zh-TW")
    canonical_language = Column(String(16), nullable=True)
    source_payload_json = Column(qa_ai_helper_large_text_type(), nullable=True)
    current_phase = Column(String(32), nullable=False, default="intake", index=True)
    current_screen = Column(String(32), nullable=True, index=True)
    status = Column(String(32), nullable=False, default="active", index=True)
    active_canonical_revision_id = Column(Integer, nullable=True)
    active_planned_revision_id = Column(Integer, nullable=True)
    active_draft_set_id = Column(Integer, nullable=True)
    active_ticket_snapshot_id = Column(Integer, nullable=True)
    active_requirement_plan_id = Column(Integer, nullable=True)
    active_seed_set_id = Column(Integer, nullable=True)
    active_testcase_draft_set_id = Column(Integer, nullable=True)
    selected_target_test_case_set_id = Column(Integer, nullable=True)
    prompt_profile_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_prompt_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    canonical_revisions = relationship(
        "QAAIHelperCanonicalRevision",
        back_populates="session",
        cascade="all, delete-orphan",
    )
    planned_revisions = relationship(
        "QAAIHelperPlannedRevision",
        back_populates="session",
        cascade="all, delete-orphan",
    )
    requirement_deltas = relationship(
        "QAAIHelperRequirementDelta",
        back_populates="session",
        cascade="all, delete-orphan",
    )
    draft_sets = relationship(
        "QAAIHelperDraftSet",
        back_populates="session",
        cascade="all, delete-orphan",
    )
    ticket_snapshots = relationship(
        "QAAIHelperTicketSnapshot",
        back_populates="session",
        cascade="all, delete-orphan",
    )
    requirement_plans = relationship(
        "QAAIHelperRequirementPlan",
        back_populates="session",
        cascade="all, delete-orphan",
    )
    seed_sets = relationship(
        "QAAIHelperSeedSet",
        back_populates="session",
        cascade="all, delete-orphan",
    )
    testcase_draft_sets = relationship(
        "QAAIHelperTestcaseDraftSet",
        back_populates="session",
        cascade="all, delete-orphan",
    )
    validation_runs = relationship(
        "QAAIHelperValidationRun",
        back_populates="session",
        cascade="all, delete-orphan",
    )
    telemetry_events = relationship(
        "QAAIHelperTelemetryEvent",
        back_populates="session",
        cascade="all, delete-orphan",
    )
    commit_links = relationship(
        "QAAIHelperCommitLink",
        back_populates="session",
        cascade="all, delete-orphan",
    )
    test_case_set = relationship("TestCaseSet", foreign_keys=[target_test_case_set_id])
    team = relationship("Team")
    created_by_user = relationship("User")


class QAAIHelperCanonicalRevision(Base):
    """Versioned canonical requirement source for the rewritten helper."""

    __tablename__ = "qa_ai_helper_canonical_revisions"
    __table_args__ = (
        UniqueConstraint("session_id", "revision_number", name="uq_qa_ai_helper_canonical_revision"),
        Index("ix_qa_ai_helper_canonical_revisions_session_status", "session_id", "status"),
    )

    id = Column(Integer, primary_key=True)
    session_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_number = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, default="editable", index=True)
    content_json = Column(qa_ai_helper_large_text_type(), nullable=False)
    canonical_language = Column(String(16), nullable=False, default="zh-TW")
    counter_settings_json = Column(qa_ai_helper_large_text_type(), nullable=False)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    session = relationship("QAAIHelperSession", back_populates="canonical_revisions")
    created_by_user = relationship("User")
    planned_revisions = relationship(
        "QAAIHelperPlannedRevision",
        back_populates="canonical_revision",
    )


class QAAIHelperPlannedRevision(Base):
    """Versioned deterministic planning output for the rewritten helper."""

    __tablename__ = "qa_ai_helper_planned_revisions"
    __table_args__ = (
        UniqueConstraint("session_id", "revision_number", name="uq_qa_ai_helper_planned_revision"),
        Index("ix_qa_ai_helper_planned_revisions_session_canonical", "session_id", "canonical_revision_id"),
        Index("ix_qa_ai_helper_planned_revisions_session_status", "session_id", "status"),
    )

    id = Column(Integer, primary_key=True)
    session_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    canonical_revision_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_canonical_revisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_number = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, default="editable", index=True)
    matrix_json = Column(qa_ai_helper_large_text_type(), nullable=False)
    applicability_overrides_json = Column(qa_ai_helper_large_text_type(), nullable=False)
    selected_references_json = Column(qa_ai_helper_large_text_type(), nullable=False)
    counter_settings_json = Column(qa_ai_helper_large_text_type(), nullable=False)
    impact_summary_json = Column(qa_ai_helper_large_text_type(), nullable=True)
    locked_at = Column(DateTime, nullable=True)
    locked_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    session = relationship("QAAIHelperSession", back_populates="planned_revisions")
    canonical_revision = relationship("QAAIHelperCanonicalRevision", back_populates="planned_revisions")
    locked_by_user = relationship("User")
    draft_sets = relationship(
        "QAAIHelperDraftSet",
        back_populates="planned_revision",
        cascade="all, delete-orphan",
    )
    validation_runs = relationship(
        "QAAIHelperValidationRun",
        back_populates="planned_revision",
        cascade="all, delete-orphan",
    )


class QAAIHelperRequirementDelta(Base):
    """Requirement delta raised from plan review."""

    __tablename__ = "qa_ai_helper_requirement_deltas"
    __table_args__ = (
        Index("ix_qa_ai_helper_requirement_deltas_session_created", "session_id", "created_at"),
        Index("ix_qa_ai_helper_requirement_deltas_source_plan", "source_planned_revision_id"),
    )

    id = Column(Integer, primary_key=True)
    session_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_canonical_revision_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_canonical_revisions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_planned_revision_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_planned_revisions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    delta_type = Column(String(16), nullable=False)
    target_scope = Column(String(64), nullable=False)
    target_requirement_key = Column(String(128), nullable=True)
    target_scenario_key = Column(String(128), nullable=True)
    proposed_content_json = Column(qa_ai_helper_large_text_type(), nullable=False)
    reason = Column(Text, nullable=False)
    created_from_phase = Column(String(32), nullable=False, default="planned")
    actor_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    applied_canonical_revision_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_canonical_revisions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    applied_at = Column(DateTime, nullable=True)

    session = relationship("QAAIHelperSession", back_populates="requirement_deltas")
    actor_user = relationship("User", foreign_keys=[actor_user_id])


class QAAIHelperDraftSet(Base):
    """Generated testcase draft set for one locked planned revision."""

    __tablename__ = "qa_ai_helper_draft_sets"
    __table_args__ = (
        Index("ix_qa_ai_helper_draft_sets_session_status", "session_id", "status"),
        Index("ix_qa_ai_helper_draft_sets_plan_status", "planned_revision_id", "status"),
    )

    id = Column(Integer, primary_key=True)
    session_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    planned_revision_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_planned_revisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = Column(String(32), nullable=False, default="active", index=True)
    generation_mode = Column(String(32), nullable=True)
    model_name = Column(String(255), nullable=True)
    summary_json = Column(qa_ai_helper_large_text_type(), nullable=True)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    committed_at = Column(DateTime, nullable=True)

    session = relationship("QAAIHelperSession", back_populates="draft_sets")
    planned_revision = relationship("QAAIHelperPlannedRevision", back_populates="draft_sets")
    created_by_user = relationship("User")
    drafts = relationship(
        "QAAIHelperDraft",
        back_populates="draft_set",
        cascade="all, delete-orphan",
    )


class QAAIHelperDraft(Base):
    """One testcase draft item inside a draft set."""

    __tablename__ = "qa_ai_helper_drafts"
    __table_args__ = (UniqueConstraint("draft_set_id", "item_key", name="uq_qa_ai_helper_draft_set_item_key"),)

    id = Column(Integer, primary_key=True)
    draft_set_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_draft_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_key = Column(String(128), nullable=False)
    testcase_id = Column(String(64), nullable=True, index=True)
    body_json = Column(qa_ai_helper_large_text_type(), nullable=False)
    trace_json = Column(qa_ai_helper_large_text_type(), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    draft_set = relationship("QAAIHelperDraftSet", back_populates="drafts")


class QAAIHelperValidationRun(Base):
    """Validation / repair run record for generated drafts."""

    __tablename__ = "qa_ai_helper_validation_runs"
    __table_args__ = (Index("ix_qa_ai_helper_validation_runs_draft_created", "draft_set_id", "created_at"),)

    id = Column(Integer, primary_key=True)
    session_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    planned_revision_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_planned_revisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    draft_set_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_draft_sets.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    run_type = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False, default="pending", index=True)
    summary_json = Column(qa_ai_helper_large_text_type(), nullable=True)
    errors_json = Column(qa_ai_helper_large_text_type(), nullable=True)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("QAAIHelperSession", back_populates="validation_runs")
    planned_revision = relationship("QAAIHelperPlannedRevision", back_populates="validation_runs")
    created_by_user = relationship("User")


class QAAIHelperTelemetryEvent(Base):
    """Telemetry event for the rewritten helper."""

    __tablename__ = "qa_ai_helper_telemetry_events"
    __table_args__ = (
        Index("ix_qa_ai_helper_telemetry_events_team_stage_time", "team_id", "stage", "created_at"),
        Index("ix_qa_ai_helper_telemetry_events_session_time", "session_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    session_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    planned_revision_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_planned_revisions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    draft_set_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_draft_sets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    stage = Column(String(32), nullable=False, index=True)
    event_name = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False)
    model_name = Column(String(255), nullable=True)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    duration_ms = Column(Integer, nullable=False, default=0)
    payload_json = Column(qa_ai_helper_large_text_type(), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("QAAIHelperSession", back_populates="telemetry_events")
    team = relationship("Team")
    user = relationship("User")


class QAAIHelperTicketSnapshot(Base):
    """Screen-2 readonly ticket snapshot for V3 helper."""

    __tablename__ = "qa_ai_helper_ticket_snapshots"
    __table_args__ = (Index("ix_qa_ai_helper_ticket_snapshots_session_status", "session_id", "status"),)

    id = Column(Integer, primary_key=True)
    session_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = Column(String(32), nullable=False, default="loaded", index=True)
    raw_ticket_markdown = Column(qa_ai_helper_large_text_type(), nullable=False)
    structured_requirement_json = Column(qa_ai_helper_large_text_type(), nullable=False)
    validation_summary_json = Column(qa_ai_helper_large_text_type(), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    session = relationship("QAAIHelperSession", back_populates="ticket_snapshots")
    requirement_plans = relationship(
        "QAAIHelperRequirementPlan",
        back_populates="ticket_snapshot",
        cascade="all, delete-orphan",
    )


class QAAIHelperRequirementPlan(Base):
    """Screen-3 verification workspace snapshot for V3 helper."""

    __tablename__ = "qa_ai_helper_requirement_plans"
    __table_args__ = (
        UniqueConstraint("session_id", "revision_number", name="uq_qa_ai_helper_requirement_plan_revision"),
        Index("ix_qa_ai_helper_requirement_plans_session_status", "session_id", "status"),
        Index("ix_qa_ai_helper_requirement_plans_ticket_snapshot", "ticket_snapshot_id"),
    )

    id = Column(Integer, primary_key=True)
    session_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ticket_snapshot_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_ticket_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_number = Column(Integer, nullable=False, default=1)
    status = Column(String(32), nullable=False, default="editing", index=True)
    section_start_number = Column(String(3), nullable=False, default="010")
    criteria_reference_json = Column(qa_ai_helper_large_text_type(), nullable=False)
    technical_reference_json = Column(qa_ai_helper_large_text_type(), nullable=True)
    autosave_summary_json = Column(qa_ai_helper_large_text_type(), nullable=True)
    locked_at = Column(DateTime, nullable=True)
    locked_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    session = relationship("QAAIHelperSession", back_populates="requirement_plans")
    ticket_snapshot = relationship("QAAIHelperTicketSnapshot", back_populates="requirement_plans")
    locked_by_user = relationship("User")
    sections = relationship(
        "QAAIHelperPlanSection",
        back_populates="requirement_plan",
        cascade="all, delete-orphan",
    )
    seed_sets = relationship(
        "QAAIHelperSeedSet",
        back_populates="requirement_plan",
        cascade="all, delete-orphan",
    )


class QAAIHelperPlanSection(Base):
    """One section inside a V3 requirement plan."""

    __tablename__ = "qa_ai_helper_plan_sections"
    __table_args__ = (
        UniqueConstraint("requirement_plan_id", "section_key", name="uq_qa_ai_helper_plan_section_key"),
        UniqueConstraint("requirement_plan_id", "section_id", name="uq_qa_ai_helper_plan_section_id"),
        Index("ix_qa_ai_helper_plan_sections_plan_order", "requirement_plan_id", "display_order"),
    )

    id = Column(Integer, primary_key=True)
    requirement_plan_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_requirement_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section_key = Column(String(128), nullable=False)
    section_id = Column(String(64), nullable=False)
    section_title = Column(Text, nullable=False)
    given_json = Column(qa_ai_helper_large_text_type(), nullable=False)
    when_json = Column(qa_ai_helper_large_text_type(), nullable=False)
    then_json = Column(qa_ai_helper_large_text_type(), nullable=False)
    display_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    requirement_plan = relationship("QAAIHelperRequirementPlan", back_populates="sections")
    verification_items = relationship(
        "QAAIHelperVerificationItem",
        back_populates="plan_section",
        cascade="all, delete-orphan",
    )
    seed_items = relationship("QAAIHelperSeedItem", back_populates="plan_section")


class QAAIHelperVerificationItem(Base):
    """One verification item entered on screen 3."""

    __tablename__ = "qa_ai_helper_verification_items"
    __table_args__ = (Index("ix_qa_ai_helper_verification_items_section_order", "plan_section_id", "display_order"),)

    id = Column(Integer, primary_key=True)
    plan_section_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_plan_sections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category = Column(String(32), nullable=False, index=True)
    summary = Column(Text, nullable=False)
    detail_json = Column(qa_ai_helper_large_text_type(), nullable=True)
    display_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    plan_section = relationship("QAAIHelperPlanSection", back_populates="verification_items")
    check_conditions = relationship(
        "QAAIHelperCheckCondition",
        back_populates="verification_item",
        cascade="all, delete-orphan",
    )
    seed_items = relationship("QAAIHelperSeedItem", back_populates="verification_item")


class QAAIHelperCheckCondition(Base):
    """One check condition under a verification item."""

    __tablename__ = "qa_ai_helper_check_conditions"
    __table_args__ = (Index("ix_qa_ai_helper_check_conditions_item_order", "verification_item_id", "display_order"),)

    id = Column(Integer, primary_key=True)
    verification_item_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_verification_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    condition_text = Column(Text, nullable=False)
    coverage_tag = Column(String(32), nullable=False, index=True)
    display_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    verification_item = relationship("QAAIHelperVerificationItem", back_populates="check_conditions")


class QAAIHelperSeedSet(Base):
    """Screen-4 seed review root."""

    __tablename__ = "qa_ai_helper_seed_sets"
    __table_args__ = (
        Index("ix_qa_ai_helper_seed_sets_session_status", "session_id", "status"),
        Index("ix_qa_ai_helper_seed_sets_requirement_status", "requirement_plan_id", "status"),
    )

    id = Column(Integer, primary_key=True)
    session_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requirement_plan_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_requirement_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = Column(String(32), nullable=False, default="draft", index=True)
    generation_round = Column(Integer, nullable=False, default=1)
    source_type = Column(String(32), nullable=False, default="initial")
    model_name = Column(String(255), nullable=True)
    generated_seed_count = Column(Integer, nullable=False, default=0)
    included_seed_count = Column(Integer, nullable=False, default=0)
    adoption_rate = Column(Float, nullable=False, default=0.0)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    session = relationship("QAAIHelperSession", back_populates="seed_sets")
    requirement_plan = relationship("QAAIHelperRequirementPlan", back_populates="seed_sets")
    created_by_user = relationship("User")
    seed_items = relationship(
        "QAAIHelperSeedItem",
        back_populates="seed_set",
        cascade="all, delete-orphan",
    )
    testcase_draft_sets = relationship(
        "QAAIHelperTestcaseDraftSet",
        back_populates="seed_set",
        cascade="all, delete-orphan",
    )


class QAAIHelperSeedItem(Base):
    """One seed item with local review state."""

    __tablename__ = "qa_ai_helper_seed_items"
    __table_args__ = (
        UniqueConstraint("seed_set_id", "seed_reference_key", name="uq_qa_ai_helper_seed_item_ref"),
        Index("ix_qa_ai_helper_seed_items_included", "seed_set_id", "included_for_testcase_generation"),
        Index("ix_qa_ai_helper_seed_items_verification_item", "verification_item_id"),
    )

    id = Column(Integer, primary_key=True)
    seed_set_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_seed_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_section_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_plan_sections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    verification_item_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_verification_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    check_condition_refs_json = Column(qa_ai_helper_large_text_type(), nullable=True)
    coverage_tags_json = Column(qa_ai_helper_large_text_type(), nullable=False)
    seed_reference_key = Column(String(128), nullable=False)
    seed_summary = Column(Text, nullable=False)
    seed_body_json = Column(qa_ai_helper_large_text_type(), nullable=False)
    comment_text = Column(Text, nullable=True)
    is_ai_generated = Column(Boolean, nullable=False, default=True)
    user_edited = Column(Boolean, nullable=False, default=False)
    included_for_testcase_generation = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    seed_set = relationship("QAAIHelperSeedSet", back_populates="seed_items")
    plan_section = relationship("QAAIHelperPlanSection", back_populates="seed_items")
    verification_item = relationship("QAAIHelperVerificationItem", back_populates="seed_items")
    testcase_drafts = relationship("QAAIHelperTestcaseDraft", back_populates="seed_item")
    commit_links = relationship("QAAIHelperCommitLink", back_populates="seed_item")


class QAAIHelperTestcaseDraftSet(Base):
    """Screen-5 testcase draft root."""

    __tablename__ = "qa_ai_helper_testcase_draft_sets"
    __table_args__ = (
        Index("ix_qa_ai_helper_testcase_draft_sets_session_status", "session_id", "status"),
        Index("ix_qa_ai_helper_testcase_draft_sets_seed_status", "seed_set_id", "status"),
    )

    id = Column(Integer, primary_key=True)
    session_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seed_set_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_seed_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = Column(String(32), nullable=False, default="draft", index=True)
    model_name = Column(String(255), nullable=True)
    generated_testcase_count = Column(Integer, nullable=False, default=0)
    selected_for_commit_count = Column(Integer, nullable=False, default=0)
    adoption_rate = Column(Float, nullable=False, default=0.0)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    prompt_profile_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_prompt_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    custom_instructions_snapshot = Column(qa_ai_helper_large_text_type(), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    committed_at = Column(DateTime, nullable=True)

    session = relationship("QAAIHelperSession", back_populates="testcase_draft_sets")
    seed_set = relationship("QAAIHelperSeedSet", back_populates="testcase_draft_sets")
    created_by_user = relationship("User")
    drafts = relationship(
        "QAAIHelperTestcaseDraft",
        back_populates="testcase_draft_set",
        cascade="all, delete-orphan",
    )
    commit_links = relationship(
        "QAAIHelperCommitLink",
        back_populates="testcase_draft_set",
        cascade="all, delete-orphan",
    )


class QAAIHelperTestcaseDraft(Base):
    """One testcase draft generated from one seed item."""

    __tablename__ = "qa_ai_helper_testcase_drafts"
    __table_args__ = (
        UniqueConstraint(
            "testcase_draft_set_id",
            "seed_reference_key",
            name="uq_qa_ai_helper_testcase_draft_ref",
        ),
        Index("ix_qa_ai_helper_testcase_drafts_selected", "testcase_draft_set_id", "selected_for_commit"),
        Index("ix_qa_ai_helper_testcase_drafts_seed_item", "seed_item_id"),
    )

    id = Column(Integer, primary_key=True)
    testcase_draft_set_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_testcase_draft_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seed_item_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_seed_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seed_reference_key = Column(String(128), nullable=False)
    assigned_testcase_id = Column(String(64), nullable=True, index=True)
    body_json = Column(qa_ai_helper_large_text_type(), nullable=False)
    is_ai_generated = Column(Boolean, nullable=False, default=True)
    user_edited = Column(Boolean, nullable=False, default=False)
    selected_for_commit = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    testcase_draft_set = relationship("QAAIHelperTestcaseDraftSet", back_populates="drafts")
    seed_item = relationship("QAAIHelperSeedItem", back_populates="testcase_drafts")
    commit_links = relationship("QAAIHelperCommitLink", back_populates="testcase_draft")


class QAAIHelperCommitLink(Base):
    """Created testcase provenance linking helper draft and final testcase."""

    __tablename__ = "qa_ai_helper_commit_links"
    __table_args__ = (
        Index("ix_qa_ai_helper_commit_links_session_committed", "session_id", "committed_at"),
        Index("ix_qa_ai_helper_commit_links_test_case", "test_case_id"),
    )

    id = Column(Integer, primary_key=True)
    session_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    testcase_draft_set_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_testcase_draft_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    testcase_draft_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_testcase_drafts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seed_item_id = Column(
        Integer,
        ForeignKey("qa_ai_helper_seed_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    test_case_id = Column(
        Integer,
        ForeignKey("test_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    test_case_set_id = Column(
        Integer,
        ForeignKey("test_case_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_ai_generated = Column(Boolean, nullable=False, default=True)
    selected_for_commit = Column(Boolean, nullable=False, default=True)
    committed_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    session = relationship("QAAIHelperSession", back_populates="commit_links")
    testcase_draft_set = relationship("QAAIHelperTestcaseDraftSet", back_populates="commit_links")
    testcase_draft = relationship("QAAIHelperTestcaseDraft", back_populates="commit_links")
    seed_item = relationship("QAAIHelperSeedItem", back_populates="commit_links")
    test_case = relationship("TestCaseLocal")
    test_case_set = relationship("TestCaseSet")


# Backward-compatible computed columns for TestRunItem snapshots
TestRunItem.title = column_property(
    select(TestCaseLocal.title)
    .where(TestCaseLocal.team_id == TestRunItem.team_id, TestCaseLocal.test_case_number == TestRunItem.test_case_number)
    .correlate_except(TestCaseLocal)
    .scalar_subquery()
)

TestRunItem.priority = column_property(
    select(TestCaseLocal.priority)
    .where(TestCaseLocal.team_id == TestRunItem.team_id, TestCaseLocal.test_case_number == TestRunItem.test_case_number)
    .correlate_except(TestCaseLocal)
    .scalar_subquery()
)

TestRunItem.precondition = column_property(
    select(TestCaseLocal.precondition)
    .where(TestCaseLocal.team_id == TestRunItem.team_id, TestCaseLocal.test_case_number == TestRunItem.test_case_number)
    .correlate_except(TestCaseLocal)
    .scalar_subquery()
)

TestRunItem.steps = column_property(
    select(TestCaseLocal.steps)
    .where(TestCaseLocal.team_id == TestRunItem.team_id, TestCaseLocal.test_case_number == TestRunItem.test_case_number)
    .correlate_except(TestCaseLocal)
    .scalar_subquery()
)

TestRunItem.expected_result = column_property(
    select(TestCaseLocal.expected_result)
    .where(TestCaseLocal.team_id == TestRunItem.team_id, TestCaseLocal.test_case_number == TestRunItem.test_case_number)
    .correlate_except(TestCaseLocal)
    .scalar_subquery()
)


class LarkUser(Base):
    """Lark 用戶信息表"""

    __tablename__ = "lark_users"

    # 主鍵使用 Lark 用戶 ID
    user_id = Column(String(100), primary_key=True)
    open_id = Column(String(100), nullable=True, unique=True, index=True)
    union_id = Column(String(100), nullable=True, unique=True, index=True)

    # 基本信息
    name = Column(String(255), nullable=True, index=True)
    en_name = Column(String(255), nullable=True)
    enterprise_email = Column(String(255), nullable=True, unique=True, index=True)

    # 部門歸屬
    primary_department_id = Column(String(100), ForeignKey("lark_departments.department_id"), nullable=True, index=True)
    department_ids_json = Column(Text, nullable=True)  # JSON 存儲所有部門ID列表

    # 職位信息
    description = Column(String(500), nullable=True)  # 職位描述
    job_title = Column(String(255), nullable=True)  # 職稱
    employee_type = Column(Integer, nullable=True, index=True)  # 員工類型（1=正式，6=實習等）
    employee_no = Column(String(100), nullable=True)  # 工號

    # 聯絡信息
    city = Column(String(100), nullable=True)
    country = Column(String(100), nullable=True)
    work_station = Column(String(255), nullable=True)
    mobile_visible = Column(Boolean, default=True)

    # 狀態信息（來自 Lark status 對象）
    is_activated = Column(Boolean, default=True, index=True)
    is_exited = Column(Boolean, default=False, index=True)
    is_frozen = Column(Boolean, default=False)
    is_resigned = Column(Boolean, default=False)
    is_unjoin = Column(Boolean, default=False)
    is_tenant_manager = Column(Boolean, default=False)

    # 頭像信息
    avatar_240 = Column(String(500), nullable=True)  # 240x240 頭像 URL
    avatar_640 = Column(String(500), nullable=True)  # 640x640 頭像 URL
    avatar_origin = Column(String(500), nullable=True)  # 原始頭像 URL

    # 時間信息
    join_time = Column(Integer, nullable=True)  # Lark 入職時間戳

    # 系統欄位
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_sync_at = Column(DateTime, nullable=True)

    # 關聯關係
    primary_department = relationship("LarkDepartment", back_populates="users")

    # 索引
    __table_args__ = (Index("ix_lark_user_status", "is_activated", "is_exited"),)


class SyncHistory(Base):
    """同步歷史記錄表"""

    __tablename__ = "sync_history"

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False, index=True)

    # 同步操作信息
    sync_type = Column(String(20), nullable=False, index=True)  # full, departments, users
    trigger_type = Column(String(20), nullable=False)  # manual, scheduled, api
    trigger_user = Column(String(255), nullable=True)  # 觸發用戶（手動同步時）

    # 同步狀態
    status = Column(String(20), nullable=False, index=True)  # started, running, completed, failed
    start_time = Column(DateTime, nullable=False, index=True)
    end_time = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)

    # 同步結果統計
    departments_discovered = Column(Integer, default=0)
    departments_created = Column(Integer, default=0)
    departments_updated = Column(Integer, default=0)
    users_discovered = Column(Integer, default=0)
    users_created = Column(Integer, default=0)
    users_updated = Column(Integer, default=0)
    users_duplicated = Column(Integer, default=0)
    api_calls = Column(Integer, default=0)

    # 錯誤信息
    error_message = Column(Text, nullable=True)
    error_details_json = Column(Text, nullable=True)  # JSON 存儲詳細錯誤信息

    # 同步結果詳情（JSON）
    result_summary_json = Column(Text, nullable=True)  # 完整結果摘要
    department_result_json = Column(Text, nullable=True)  # 部門同步結果
    user_result_json = Column(Text, nullable=True)  # 用戶同步結果

    # 系統欄位
    created_at = Column(DateTime, default=datetime.utcnow)

    # 關聯關係
    team = relationship("Team")

    # 索引
    __table_args__ = (Index("ix_sync_history_team_time", "team_id", "start_time"),)


class ScheduledService(Base):
    """可排程服務設定與執行狀態"""

    __tablename__ = "scheduled_services"
    __table_args__ = (
        UniqueConstraint("service_key", name="uq_scheduled_services_service_key"),
        Index("ix_scheduled_services_enabled_next_run", "enabled", "next_run_at"),
        Index("ix_scheduled_services_is_running", "is_running"),
        Index("ix_scheduled_services_last_run_status", "last_run_status"),
    )

    id = Column(Integer, primary_key=True)
    service_key = Column(String(100), nullable=False)
    display_name = Column(String(120), nullable=False)
    description = Column(Text, nullable=True)
    schedule_type = Column(String(20), nullable=False, default="daily")
    run_at_time = Column(String(5), nullable=True, comment="每日執行時間（HH:MM）")
    enabled = Column(Boolean, nullable=False, default=False)
    is_running = Column(Boolean, nullable=False, default=False)
    last_run_status = Column(String(20), nullable=True)
    last_run_message = Column(Text, nullable=True)
    last_error = Column(Text, nullable=True)
    last_run_started_at = Column(DateTime, nullable=True)
    last_run_finished_at = Column(DateTime, nullable=True)
    next_run_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


# ===================== 認證系統相關表格 =====================


class User(Base):
    """使用者表格（認證系統）"""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    # 大小寫不敏感唯一性由下方 uq_users_username_lower 函式索引保證(跨引擎一致),
    # 這裡不再用 unique=True(避免與 MySQL 預設 collation 已隱含的大小寫不敏感行為疊床架屋)。
    username = Column(String(50), nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True, index=True)
    hashed_password = Column(String(255), nullable=False)

    # Lark 關聯
    lark_user_id = Column(String(100), unique=True, nullable=True, index=True)

    # 基本資訊
    full_name = Column(String(255), nullable=True)
    role = Column(Enum(UserRole, values_callable=lambda values: [item.value for item in values], native_enum=False), nullable=False, default=UserRole.USER, index=True)

    # 狀態設定
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    is_verified = Column(Boolean, default=False, nullable=False)

    # 時間欄位
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_login_at = Column(DateTime, nullable=True)

    # 關聯關係
    team_permissions = relationship(
        "UserTeamPermission",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="UserTeamPermission.user_id",
    )
    active_sessions = relationship("ActiveSession", back_populates="user", cascade="all, delete-orphan")

    # 索引
    __table_args__ = (
        Index("ix_users_role_active", "role", "is_active"),
        Index("ix_users_email_active", "email", "is_active"),
        # 大小寫不敏感唯一性:對 lower(username) 建 unique index,讓 SQLite/PostgreSQL
        # 與 MySQL(預設 collation 已是 case-insensitive)行為一致。取代原本 username 欄位上
        # 的 unique=True(該寫法在 SQLite/PostgreSQL 上僅為大小寫敏感唯一)。
        Index("uq_users_username_lower", func.lower(username), unique=True),
    )


class UserPin(Base):
    """使用者釘選（Pin）表格：每位使用者可將 Test Case Set / Test Run Set /
    Test Run / Ad-hoc Run 釘選，釘選項目在列表中永遠置頂。Per-user。"""

    __tablename__ = "user_pins"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # team_id 反正規化保存，讓「某使用者在某團隊的所有釘選」可用單一查詢取回
    team_id = Column(Integer, nullable=False, index=True)
    entity_type = Column(String(50), nullable=False)  # test_case_set / test_run_set / test_run / adhoc_run
    entity_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "entity_type", "entity_id", name="uq_user_pin"),
        Index("ix_user_pins_user_team", "user_id", "team_id"),
    )


class UserTeamPermission(Base):
    """使用者團隊權限表格"""

    __tablename__ = "user_team_permissions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    permission = Column(Enum(PermissionType, values_callable=lambda values: [item.value for item in values], native_enum=False), nullable=False, index=True)

    # 時間欄位
    granted_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    granted_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # 關聯關係
    user = relationship("User", back_populates="team_permissions", foreign_keys=[user_id])
    team = relationship("Team")
    granted_by = relationship("User", foreign_keys=[granted_by_id])

    # 唯一索引：同一使用者在同一團隊只能有一種權限
    __table_args__ = (
        UniqueConstraint("user_id", "team_id", name="uq_user_team_permission"),
        Index("ix_user_team_perms_user", "user_id"),
        Index("ix_user_team_perms_team", "team_id"),
        Index("ix_user_team_perms_permission", "permission"),
    )


class ActiveSession(Base):
    """活躍会話表格（用於Token管理與撤銷）"""

    __tablename__ = "active_sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # JWT Token 資訊
    jti = Column(String(36), unique=True, nullable=False, index=True)  # JWT ID (UUID)
    token_type = Column(String(20), default="access", nullable=False)  # access, refresh

    # 会話資訊
    ip_address = Column(String(45), nullable=True)  # 支持 IPv6
    user_agent = Column(String(500), nullable=True)

    # 狀態與時間
    is_revoked = Column(Boolean, default=False, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    revoked_reason = Column(String(100), nullable=True)  # logout, admin_revoke, expired, etc.

    # 關聯關係
    user = relationship("User", back_populates="active_sessions")

    # 索引
    __table_args__ = (
        Index("ix_sessions_user_active", "user_id", "is_revoked"),
        Index("ix_sessions_expires", "expires_at"),
        Index("ix_sessions_jti_active", "jti", "is_revoked"),
    )


class LoginChallenge(Base):
    """登入 Challenge-Response 認證用的暫存 challenge（見 SessionService.store_challenge/
    verify_challenge）。`identifier` 是 username_or_email 字串、非 FK——即使該帳號不存在也要能
    發出 challenge（避免透過行為差異洩漏帳號是否存在），單一 identifier 同時只有一組有效
    challenge（見 __tablename__ 唯一性，重新申請會直接覆蓋前一組）。

    2026-07-14 從 in-process dict 改為 DB table：多 worker（WEB_CONCURRENCY>1）部署下，
    `/challenge` 與後續登入驗證這兩個請求若剛好落在不同 worker，各自的記憶體字典互不可見，
    會讓合法登入必定失敗。"""

    __tablename__ = "login_challenges"

    identifier = Column(String(255), primary_key=True)
    challenge = Column(String(64), nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PasswordResetToken(Base):
    """密碼重設令牌表格"""

    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # 令牌資訊
    token = Column(String(64), unique=True, nullable=False, index=True)  # 隨機產生的令牌

    # 狀態與時間
    is_used = Column(Boolean, default=False, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    used_at = Column(DateTime, nullable=True)

    # 安全資訊
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)

    # 關聯關係
    user = relationship("User")

    # 索引
    __table_args__ = (
        Index("ix_reset_tokens_user", "user_id", "is_used"),
        Index("ix_reset_tokens_expires", "expires_at"),
    )


class MCPMachineCredential(Base):
    """MCP 機器對機器存取憑證"""

    __tablename__ = "mcp_machine_credentials"
    __table_args__ = (
        UniqueConstraint("name", name="uq_mcp_machine_credentials_name"),
        UniqueConstraint("token_hash", name="uq_mcp_machine_credentials_token_hash"),
        Index("ix_mcp_machine_credentials_status", "status"),
        Index("ix_mcp_machine_credentials_expires_at", "expires_at"),
    )

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    token_hash = Column(String(128), nullable=False)
    permission = Column(String(32), nullable=False, default="mcp_read")
    status = Column(
        Enum(
            MCPMachineCredentialStatus,
            values_callable=lambda values: [item.value for item in values],
            native_enum=False,
        ),
        nullable=False,
        default=MCPMachineCredentialStatus.ACTIVE,
    )
    allow_all_teams = Column(Boolean, nullable=False, default=False)
    team_scope_json = Column(Text, nullable=True, comment="允許存取的 team_id 清單（JSON 陣列）")
    expires_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    created_by = relationship("User")


class TeamAppToken(Base):
    """Team-owned app token for external non-interactive API access."""

    __tablename__ = "team_app_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_team_app_tokens_token_hash"),
        Index("ix_team_app_tokens_owner_team_id", "owner_team_id"),
        Index("ix_team_app_tokens_status", "status"),
        Index("ix_team_app_tokens_expires_at", "expires_at"),
        Index("ix_team_app_tokens_created_by_user_id", "created_by_user_id"),
    )

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    owner_team_id = Column(
        Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    token_hash = Column(String(128), nullable=False)
    token_prefix = Column(String(16), nullable=False)
    status = Column(
        Enum(
            TeamAppTokenStatus,
            values_callable=lambda values: [item.value for item in values],
            native_enum=False,
        ),
        nullable=False,
        default=TeamAppTokenStatus.ACTIVE,
    )
    scopes_json = Column(Text, nullable=True, comment="允許的 operation scope 清單（JSON 陣列）")
    expires_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    revoked_at = Column(DateTime, nullable=True)

    owner_team = relationship("Team")
    created_by = relationship("User")


class AppTokenPin(Base):
    """Team-scoped 釘選（Pin）表格，供 /api/app/* 呼叫者（app token 或 legacy
    machine credential）建立/刪除；同團隊所有 token 共用同一份清單，與
    UserPin（per-user，僅供人類 Web UI 使用）完全獨立。"""

    __tablename__ = "app_token_pins"
    __table_args__ = (
        UniqueConstraint("owner_team_id", "entity_type", "entity_id", name="uq_app_token_pin"),
        Index("ix_app_token_pins_owner_team_id", "owner_team_id"),
    )

    id = Column(Integer, primary_key=True)
    owner_team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(Integer, nullable=False)
    created_by_credential_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    owner_team = relationship("Team")


class _AutomationProviderColumnsMixin:
    """Shared columns between team-scoped storage providers and org-scoped CI/result
    providers. The two ORM classes diverge only on team_id (team table only) and
    table-level constraints (slot CHECK + uniqueness key)."""

    id = Column(Integer, primary_key=True)
    provider_slot = Column(
        Enum(AutomationProviderSlot, values_callable=lambda values: [item.value for item in values], native_enum=False),
        nullable=False,
    )
    provider_type = Column(String(60), nullable=False)
    name = Column(String(100), nullable=False)
    config_json = Column(Text, nullable=False)
    credentials_encrypted = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    last_health_check_at = Column(DateTime, nullable=True)
    last_health_status = Column(String(40), nullable=True)
    created_by = Column(String(64), nullable=True)
    updated_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class TeamAutomationProvider(_AutomationProviderColumnsMixin, Base):
    """Per-team storage provider configuration (CI/result moved to SystemAutomationProvider)."""

    __tablename__ = "team_automation_providers"
    __table_args__ = (
        UniqueConstraint("team_id", "provider_slot", "name", name="uq_team_automation_provider_name"),
        Index("ix_team_automation_providers_team_slot_active", "team_id", "provider_slot", "is_active"),
        CheckConstraint("provider_slot = 'storage'", name="ck_team_provider_storage_only"),
    )

    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)

    team = relationship("Team", backref="automation_providers")


class SystemAutomationProvider(_AutomationProviderColumnsMixin, Base):
    """Org-scoped CI / Result provider — one config shared by all teams,
    managed by Super Admin via team-management's org-sync modal."""

    __tablename__ = "system_automation_providers"
    __table_args__ = (
        UniqueConstraint("provider_slot", "name", name="uq_system_automation_provider_name"),
        Index("ix_system_automation_providers_slot_active", "provider_slot", "is_active"),
        CheckConstraint("provider_slot IN ('ci', 'result')", name="ck_system_provider_ci_or_result_only"),
    )


class SystemSetting(Base):
    """Org-level, runtime-mutable key/value settings.

    Generic store for organization-wide toggles that must be changeable at
    runtime from the UI (no static config restart). Missing keys fall back to
    feature-specific defaults at the accessor layer, so an absent row means
    "default" rather than "off". First consumer: Automation Hub entry
    visibility (key ``automation_hub_entry_enabled``)."""

    __tablename__ = "system_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    updated_by = Column(String(64), nullable=True)


def _automation_script_ref_key_hash(
    team_id: int, provider_id: int, ref_repo: str, ref_path: str, ref_branch: str
) -> str:
    """SHA-256 digest of the 5 columns that logically identify a unique script ref.

    MySQL 的複合唯一索引在 utf8mb4 下有 3072-byte 上限；`ref_repo(255)+ref_path(500)+
    ref_branch(200)` 換算後遠超這個上限（見 e7c3a9d1f2b4 的修正註記）。改用固定長度的
    hash 欄位承載唯一性，原五欄仍保留供查詢使用。分隔字元用 ASCII unit separator
    （`\\x1f`），一般 repo/path/branch 字串不會出現這個字元，避免組合歧義
    （例如 `("a", "b/c")` 與 `("a/b", "c")` 若直接字串相接會撞在一起）。
    """
    parts = "\x1f".join([str(team_id), str(provider_id), ref_repo, ref_path, ref_branch])
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


class AutomationScript(Base):
    """Auto-discovered automation script cache"""

    __tablename__ = "automation_scripts"
    __table_args__ = (
        UniqueConstraint("ref_key_hash", name="uq_automation_script_ref"),
        Index("ix_automation_scripts_team_format", "team_id", "script_format"),
        Index("ix_automation_scripts_provider_synced", "provider_id", "last_synced_at"),
        Index(
            "ix_automation_scripts_team_provider_repo_branch",
            "team_id", "provider_id", "ref_repo", "ref_branch",
        ),
    )

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_id = Column(
        Integer,
        ForeignKey("team_automation_providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    script_format = Column(
        Enum(AutomationScriptFormat, values_callable=lambda values: [item.value for item in values], native_enum=False),
        nullable=False,
        default=AutomationScriptFormat.OTHER,
    )
    ref_repo = Column(String(255), nullable=False, server_default="")
    ref_path = Column(String(500), nullable=False)
    ref_branch = Column(String(200), nullable=False)
    # 見上方 _automation_script_ref_key_hash；由 before_insert event listener 自動計算
    # （team_id/provider_id/ref_repo/ref_path/ref_branch 建立後不可變，見
    # app/services/automation/script_service.py，故只需要 before_insert，不需要
    # before_update）。
    ref_key_hash = Column(String(64), nullable=False)
    cached_content = Column(medium_text_type(), nullable=True)
    cached_content_etag = Column(String(120), nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    tags_json = Column(Text, nullable=True)
    declared_vars_json = Column(
        Text,
        nullable=True,
        comment=(
            "Per-script declared variables discovered from source TCRT_VARS by "
            "smart-scan. JSON list of {name, secret, required, description}. "
            "Names only, no values. See manage-automation-environment-configs."
        ),
    )
    preferred_runner_label = Column(String(100), nullable=True)
    linked_test_case_count = Column(Integer, default=0, nullable=False)
    created_by = Column(String(64), nullable=True)
    updated_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    team = relationship("Team", backref="automation_scripts")
    provider = relationship("TeamAutomationProvider")
    case_links = relationship(
        "AutomationScriptCaseLink",
        back_populates="automation_script",
        cascade="all, delete-orphan",
    )


@event.listens_for(AutomationScript, "before_insert")
def _set_automation_script_ref_key_hash(mapper, connection, target: AutomationScript) -> None:
    # ref_repo has server_default="" — a row that never set it explicitly is still
    # None at the Python level until the DB applies the default, so mirror that
    # default here rather than let the hash computation see None.
    target.ref_key_hash = _automation_script_ref_key_hash(
        target.team_id, target.provider_id, target.ref_repo or "", target.ref_path, target.ref_branch
    )


class AutomationScriptCaseLink(Base):
    """Automation script to manual test case many-to-many link"""

    __tablename__ = "automation_script_case_links"
    __table_args__ = (
        UniqueConstraint("automation_script_id", "test_case_id", name="uq_automation_script_case_link"),
        Index("ix_automation_script_case_links_test_case_id", "test_case_id"),
        Index("ix_automation_script_case_links_team_id", "team_id"),
    )

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    automation_script_id = Column(
        Integer,
        ForeignKey("automation_scripts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    test_case_id = Column(Integer, ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False)
    link_type = Column(
        Enum(AutomationScriptLinkType, values_callable=lambda values: [item.value for item in values], native_enum=False),
        nullable=False,
        default=AutomationScriptLinkType.COVERS,
    )
    note = Column(Text, nullable=True)
    created_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    automation_script = relationship("AutomationScript", back_populates="case_links")
    test_case = relationship("TestCaseLocal")
    team = relationship("Team")


class AutomationEnvironment(Base):
    """Per-team, user-defined automation environment catalog (e.g. dev/sit/prod).

    Values live in TCRT (not the repo): environment-level shared params live in
    AutomationEnvironmentParam; per-script overrides live in
    AutomationScriptEnvVar. See manage-automation-environment-configs."""

    __tablename__ = "automation_environments"
    __table_args__ = (
        UniqueConstraint("team_id", "name", name="uq_automation_environment_name"),
        Index("ix_automation_environments_team_default", "team_id", "is_default"),
    )

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(60), nullable=False)
    label = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    is_default = Column(Boolean, default=False, nullable=False)
    created_by = Column(String(64), nullable=True)
    updated_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    team = relationship("Team", backref="automation_environments")
    params = relationship(
        "AutomationEnvironmentParam",
        back_populates="environment",
        cascade="all, delete-orphan",
    )


class AutomationEnvironmentParam(Base):
    """Environment-level shared parameter value (shared across the team's scripts).

    secret values are AES-256-GCM encrypted in value_encrypted; non-secret values
    live in value_plaintext. The effective value for a (script, env, key) is the
    per-script override if present, else this shared value."""

    __tablename__ = "automation_environment_params"
    __table_args__ = (
        UniqueConstraint("environment_id", "key", name="uq_automation_environment_param_key"),
    )

    id = Column(Integer, primary_key=True)
    environment_id = Column(
        Integer,
        ForeignKey("automation_environments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key = Column(String(120), nullable=False)
    is_secret = Column(Boolean, default=False, nullable=False)
    value_plaintext = Column(Text, nullable=True)
    value_encrypted = Column(Text, nullable=True)
    created_by = Column(String(64), nullable=True)
    updated_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    environment = relationship("AutomationEnvironment", back_populates="params")


class AutomationScriptEnvVar(Base):
    """Per-script override of an environment variable value.

    Tied to the script cache row (ON DELETE CASCADE, like
    AutomationScriptCaseLink). Normal re-sync updates the script row in place so
    overrides are preserved; explicit cache delete cascades them away. The
    effective value overrides the environment-level shared param of the same key."""

    __tablename__ = "automation_script_env_vars"
    __table_args__ = (
        UniqueConstraint(
            "automation_script_id", "environment_id", "key",
            name="uq_automation_script_env_var",
        ),
        Index("ix_automation_script_env_vars_team_path", "team_id", "script_ref_path"),
    )

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    automation_script_id = Column(
        Integer,
        ForeignKey("automation_scripts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    script_ref_path = Column(String(500), nullable=False)
    environment_id = Column(
        Integer,
        ForeignKey("automation_environments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key = Column(String(120), nullable=False)
    is_secret = Column(Boolean, default=False, nullable=False)
    value_plaintext = Column(Text, nullable=True)
    value_encrypted = Column(Text, nullable=True)
    created_by = Column(String(64), nullable=True)
    updated_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    automation_script = relationship("AutomationScript")
    environment = relationship("AutomationEnvironment")


class AutomationScriptGroup(Base):
    """Automation script logical group for executable suites"""

    __tablename__ = "automation_script_groups"
    __table_args__ = (
        UniqueConstraint("team_id", "name", name="uq_automation_script_group_name"),
        Index("ix_automation_script_groups_team_id", "team_id"),
    )

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    script_paths_json = Column(medium_text_type(), nullable=False)
    ref_repo = Column(String(255), nullable=False, server_default="")
    ci_job_name = Column(String(200), nullable=True)
    # Webhook-triggered runs execute on a dedicated CI job (separate build
    # history / queue / Allure project from Test-Run-Set runs). Lazily created
    # on the suite's first webhook trigger, so this stays NULL until then.
    ci_job_name_webhook = Column(String(200), nullable=True)
    ci_job_type = Column(
        Enum(AutomationScriptGroupJobType, values_callable=lambda values: [item.value for item in values], native_enum=False),
        nullable=True,
    )
    created_by = Column(String(64), nullable=True)
    updated_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    team = relationship("Team", backref="automation_script_groups")
    runs = relationship("AutomationRun", back_populates="script_group")


class AutomationRun(Base):
    """Automation run metadata mirrored from external CI"""

    __tablename__ = "automation_runs"
    __table_args__ = (
        UniqueConstraint("tcrt_correlation_id", name="uq_automation_runs_tcrt_correlation_id"),
        Index("ix_automation_runs_team_started", "team_id", "started_at"),
        Index("ix_automation_runs_script_started", "automation_script_id", "started_at"),
        Index("ix_automation_runs_group_started", "script_group_id", "started_at"),
        Index("ix_automation_runs_status_synced", "status", "last_synced_at"),
        Index("ix_automation_runs_tcrt_correlation_id", "tcrt_correlation_id"),
        Index("ix_automation_runs_test_run_set_started", "test_run_set_id", "started_at"),
    )

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    automation_script_id = Column(
        Integer,
        ForeignKey("automation_scripts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    script_group_id = Column(
        Integer,
        ForeignKey("automation_script_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    test_run_set_id = Column(
        Integer,
        ForeignKey("test_run_sets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment=(
            "Source Test Run Set that triggered this run. "
            "NULL for legacy hub-triggered runs and webhook-triggered runs. "
            "See move-automation-execution-to-test-run-set."
        ),
    )
    # Runs are CI runs; CI providers are org-scoped → FK to system table.
    provider_id = Column(Integer, ForeignKey("system_automation_providers.id"), nullable=False, index=True)
    external_run_id = Column(String(120), nullable=True, index=True)
    external_run_url = Column(String(500), nullable=True)
    status = Column(
        Enum(AutomationRunStatus, values_callable=lambda values: [item.value for item in values], native_enum=False),
        nullable=False,
        default=AutomationRunStatus.QUEUED,
    )
    triggered_by = Column(
        Enum(AutomationRunTrigger, values_callable=lambda values: [item.value for item in values], native_enum=False),
        nullable=False,
    )
    triggered_by_user_id = Column(String(64), nullable=True)
    triggered_by_webhook_id = Column(Integer, ForeignKey("automation_webhooks.id"), nullable=True)
    tcrt_correlation_id = Column(String(36), nullable=False)
    ci_correlation_id = Column(String(120), nullable=True)
    workflow_id = Column(String(200), nullable=False)
    branch = Column(String(200), nullable=False)
    inputs_json = Column(Text, nullable=True)
    runner_label = Column(String(100), nullable=True)
    environment = Column(
        String(60),
        nullable=True,
        comment=(
            "Automation environment name used for this run (name only, never "
            "values). NULL for runs triggered without an environment. "
            "See manage-automation-environment-configs."
        ),
    )
    report_url = Column(String(500), nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    error_summary = Column(Text, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    team = relationship("Team", backref="automation_runs")
    automation_script = relationship("AutomationScript")
    script_group = relationship("AutomationScriptGroup", back_populates="runs")
    provider = relationship("SystemAutomationProvider")
    triggered_by_webhook = relationship("AutomationWebhook")


class AutomationWebhook(Base):
    """Automation Hub inbound/outbound webhook configuration"""

    __tablename__ = "automation_webhooks"
    __table_args__ = (
        UniqueConstraint("token", name="uq_automation_webhooks_token"),
        Index("ix_automation_webhooks_team_direction_active", "team_id", "direction", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    direction = Column(
        Enum(AutomationWebhookDirection, values_callable=lambda values: [item.value for item in values], native_enum=False),
        nullable=False,
    )
    name = Column(String(100), nullable=False)
    token = Column(String(64), nullable=False, unique=True)
    secret = Column(String(128), nullable=True)
    target_url = Column(String(500), nullable=True)
    events_json = Column(Text, nullable=True)
    # Optional suite binding: INBOUND trigger webhooks fire this script group.
    script_group_id = Column(
        Integer,
        ForeignKey("automation_script_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_active = Column(Boolean, default=True, nullable=False)
    last_triggered_at = Column(DateTime, nullable=True)
    last_status = Column(String(40), nullable=True)
    created_by = Column(String(64), nullable=True)
    updated_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    team = relationship("Team", backref="automation_webhooks")
    script_group = relationship("AutomationScriptGroup")


class AutomationWebhookDelivery(Base):
    """Outbound webhook delivery history for failure visibility and replay."""

    __tablename__ = "automation_webhook_deliveries"
    __table_args__ = (
        Index("ix_automation_webhook_deliveries_team_created", "team_id", "created_at"),
        Index("ix_automation_webhook_deliveries_webhook_created", "webhook_id", "created_at"),
        Index("ix_automation_webhook_deliveries_delivery_id", "delivery_id"),
    )

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    webhook_id = Column(Integer, ForeignKey("automation_webhooks.id", ondelete="CASCADE"), nullable=False, index=True)
    event = Column(String(80), nullable=False)
    delivery_id = Column(String(36), nullable=False)
    target_url = Column(String(500), nullable=False)
    status = Column(String(20), nullable=False)
    status_code = Column(Integer, nullable=True)
    request_body = Column(medium_text_type(), nullable=False)
    response_body = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    team = relationship("Team", backref="automation_webhook_deliveries")
    webhook = relationship("AutomationWebhook", backref="deliveries")


# 建立資料庫表格的函數
logger = logging.getLogger(__name__)

# --- Ad-hoc Test Run Models ---


class AdHocRun(Base):
    """Ad-hoc 測試執行容器（相當於 Test Run Set，但專用於 Ad-hoc 模式）"""

    __tablename__ = "adhoc_runs"

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False, index=True)

    name = Column(String(120), nullable=False)
    description = Column(Text, nullable=True)
    jira_ticket = Column(String(255), nullable=True)
    status = Column(Enum(TestRunStatus, values_callable=lambda values: [item.value for item in values], native_enum=False), default=TestRunStatus.ACTIVE, nullable=False)

    # Enhanced Basic Settings (matching TestRunConfig)
    test_version = Column(String(50), nullable=True)
    test_environment = Column(String(100), nullable=True)
    build_number = Column(String(100), nullable=True)

    related_tp_tickets_json = Column(Text, nullable=True, comment="相關 JIRA Tickets 票號 JSON 陣列")
    tp_tickets_search = Column(String(512), nullable=True, index=True, comment="JIRA Ticket 搜尋索引欄位")

    notifications_enabled = Column(Boolean, default=False, nullable=False, comment="是否啟用通知")
    notify_chat_ids_json = Column(Text, nullable=True, comment="選擇的 Lark chat IDs（JSON 陣列）")
    notify_chat_names_snapshot = Column(Text, nullable=True, comment="群組名稱快照（JSON 陣列）")
    notify_chats_search = Column(String(512), nullable=True, index=True, comment="群組名稱搜尋索引")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    team = relationship("Team", backref="adhoc_runs")
    sheets = relationship("AdHocRunSheet", back_populates="run", cascade="all, delete-orphan")


class AdHocRunSheet(Base):
    """Ad-hoc 測試執行的 Sheet（相當於 Excel 的分頁）"""

    __tablename__ = "adhoc_run_sheets"

    id = Column(Integer, primary_key=True)
    adhoc_run_id = Column(Integer, ForeignKey("adhoc_runs.id", ondelete="CASCADE"), nullable=False, index=True)

    name = Column(String(100), nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    run = relationship("AdHocRun", back_populates="sheets")
    items = relationship("AdHocRunItem", back_populates="sheet", cascade="all, delete-orphan")


class AdHocRunItem(Base):
    """Ad-hoc 測試執行項目（相當於 Test Run Item，但不需要關聯 Test Case）"""

    __tablename__ = "adhoc_run_items"

    id = Column(Integer, primary_key=True)
    sheet_id = Column(Integer, ForeignKey("adhoc_run_sheets.id", ondelete="CASCADE"), nullable=False, index=True)

    # 排序
    row_index = Column(Integer, nullable=False, index=True)

    # 測試內容欄位 (比照 Test Run Item / Test Case)
    test_case_number = Column(String(100), nullable=True)  # 可以手動輸入或留空
    title = Column(Text, nullable=True)
    priority = Column(Enum(Priority, values_callable=lambda values: [item.value for item in values], native_enum=False), default=Priority.MEDIUM)
    precondition = Column(Text, nullable=True)
    steps = Column(Text, nullable=True)
    expected_result = Column(Text, nullable=True)
    jira_tickets = Column(Text, nullable=True)
    comments = Column(Text, nullable=True)
    bug_list = Column(Text, nullable=True)

    # 執行資訊
    test_result = Column(Enum(TestResultStatus, values_callable=lambda values: [item.value for item in values], native_enum=False), nullable=True)
    assignee_name = Column(String(255), nullable=True)
    executed_at = Column(DateTime, nullable=True)

    # 附件與結果 (JSON)
    attachments_json = Column(Text, nullable=True)  # 一般附件
    execution_results_json = Column(Text, nullable=True)  # 執行結果證明 (截圖等)
    meta_json = Column(Text, nullable=True)  # 其他元數據 (如樣式、顏色等)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    sheet = relationship("AdHocRunSheet", back_populates="items")
