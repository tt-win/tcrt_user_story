from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.auth.permission_service import permission_service


@pytest.mark.asyncio
async def test_organization_mcp_token_tab_is_super_admin_only():
    super_admin = SimpleNamespace(id=1, role="super_admin")
    admin = SimpleNamespace(id=2, role="admin")
    user = SimpleNamespace(id=3, role="user")

    super_config = await permission_service.get_ui_config(super_admin, "organization")
    admin_config = await permission_service.get_ui_config(admin, "organization")
    user_config = await permission_service.get_ui_config(user, "organization")

    assert super_config["components"].get("tab-mcp-token") is True
    assert admin_config["components"].get("tab-mcp-token") is False
    assert user_config["components"].get("tab-mcp-token") is False


@pytest.mark.asyncio
async def test_organization_service_management_tab_is_super_admin_only():
    super_admin = SimpleNamespace(id=1, role="super_admin")
    admin = SimpleNamespace(id=2, role="admin")
    user = SimpleNamespace(id=3, role="user")

    super_config = await permission_service.get_ui_config(super_admin, "organization")
    admin_config = await permission_service.get_ui_config(admin, "organization")
    user_config = await permission_service.get_ui_config(user, "organization")

    assert super_config["components"].get("tab-service-management") is True
    assert admin_config["components"].get("tab-service-management") is False
    assert user_config["components"].get("tab-service-management") is False


@pytest.mark.asyncio
async def test_organization_automation_infra_tab_is_super_admin_only():
    """組織自動化基礎設施分頁的 action 必須是 advanced（不可是 view），
    否則 ADMIN 角色會意外取得可視權限（見 redesign-team-settings-information-architecture
    design.md D6）。"""
    super_admin = SimpleNamespace(id=1, role="super_admin")
    admin = SimpleNamespace(id=2, role="admin")
    user = SimpleNamespace(id=3, role="user")

    super_config = await permission_service.get_ui_config(super_admin, "organization")
    admin_config = await permission_service.get_ui_config(admin, "organization")
    user_config = await permission_service.get_ui_config(user, "organization")

    assert super_config["components"].get("tab-org-automation-infra") is True
    assert admin_config["components"].get("tab-org-automation-infra") is False
    assert user_config["components"].get("tab-org-automation-infra") is False


@pytest.mark.asyncio
async def test_organization_assistant_admin_tab_is_super_admin_only():
    """AI 助手設定分頁（原獨立頁面 /assistant-admin，見
    move-assistant-admin-into-organization-tab）沿用既有 organization_management:manage，
    僅 Super Admin 可見。"""
    super_admin = SimpleNamespace(id=1, role="super_admin")
    admin = SimpleNamespace(id=2, role="admin")
    user = SimpleNamespace(id=3, role="user")

    super_config = await permission_service.get_ui_config(super_admin, "organization")
    admin_config = await permission_service.get_ui_config(admin, "organization")
    user_config = await permission_service.get_ui_config(user, "organization")

    assert super_config["components"].get("tab-assistant-admin") is True
    assert admin_config["components"].get("tab-assistant-admin") is False
    assert user_config["components"].get("tab-assistant-admin") is False
