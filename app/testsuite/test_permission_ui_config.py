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
