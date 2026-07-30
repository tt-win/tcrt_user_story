"""Tests for avatar endpoint auth that supports Bearer and query token."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import avatars as avatars_module


@pytest.mark.asyncio
async def test_get_avatar_viewer_accepts_query_token(monkeypatch):
    fake_user = SimpleNamespace(id=7, is_active=True)

    async def _verify(token: str):
        assert token == "tok-query"
        return SimpleNamespace(user_id=7)

    monkeypatch.setattr(avatars_module.auth_service, "verify_token", _verify)
    monkeypatch.setattr(
        avatars_module.UserService,
        "get_user_by_id",
        AsyncMock(return_value=fake_user),
    )

    request = SimpleNamespace(state=SimpleNamespace())
    user = await avatars_module.get_avatar_viewer(
        request=request,
        main_boundary=SimpleNamespace(),
        credentials=None,
        access_token="tok-query",
    )
    assert user.id == 7
    assert request.state.current_user.id == 7


@pytest.mark.asyncio
async def test_get_avatar_viewer_rejects_missing_token():
    request = SimpleNamespace(state=SimpleNamespace())
    with pytest.raises(HTTPException) as exc:
        await avatars_module.get_avatar_viewer(
            request=request,
            main_boundary=SimpleNamespace(),
            credentials=None,
            access_token=None,
        )
    assert exc.value.status_code == 401
