import asyncio
import time
from types import SimpleNamespace

import httpx
import pytest

from app.api import lark_users
from app.main import app
from app.services.lark_client import LarkClient


class _FakeBoundary:
    async def run_read(self, callback):
        return SimpleNamespace(
            user_id="u-1",
            name="User",
            avatar_240=None,
            avatar_640=None,
            avatar_origin=None,
        )

    async def run_write(self, callback):
        return None


@pytest.mark.asyncio
async def test_slow_lark_call_does_not_block_version_request(monkeypatch):
    def _slow_user_lookup(user_id):
        time.sleep(2)
        return {"avatar": {"avatar_240": "https://example.test/avatar.png"}}

    def _fake_init(self, *args, **kwargs):
        self.user_manager = SimpleNamespace(get_user_by_id=_slow_user_lookup)

    monkeypatch.setattr(LarkClient, "__init__", _fake_init)

    started_at = time.perf_counter()
    slow_request = asyncio.create_task(
        lark_users.get_lark_user_basic("u-1", main_boundary=_FakeBoundary())
    )
    await asyncio.sleep(0.05)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/version/")
        elapsed = time.perf_counter() - started_at

    assert response.status_code == 200
    assert elapsed < 1
    assert (await slow_request).avatar == "https://example.test/avatar.png"
