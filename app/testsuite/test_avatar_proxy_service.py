"""Unit tests for the avatar proxy service (placeholder + host allowlist)."""

from __future__ import annotations

import pytest

from app.services.avatar_proxy_service import AvatarProxyService


@pytest.fixture
def service() -> AvatarProxyService:
    return AvatarProxyService()


def test_user_and_lark_proxy_urls(service: AvatarProxyService):
    assert service.user_proxy_url(42) == "/api/avatars/users/42"
    assert service.lark_proxy_url("ou_abc") == "/api/avatars/lark/ou_abc"


def test_placeholder_svg_is_local_image(service: AvatarProxyService):
    payload = service.placeholder_svg(name="Alice Chen", seed="42")
    assert payload.content_type.startswith("image/svg+xml")
    assert b"<svg" in payload.body
    assert b"AC" in payload.body or b"A" in payload.body


def test_initials_prefer_cjk_first_char(service: AvatarProxyService):
    assert service.initials_for("王小明") == "王"
    assert service.initials_for("Alice Bob") == "AB"


@pytest.mark.asyncio
async def test_fetch_upstream_rejects_disallowed_host(service: AvatarProxyService):
    result = await service.fetch_upstream("https://evil.example/avatar.png")
    assert result is None


@pytest.mark.asyncio
async def test_resolve_falls_back_to_placeholder_without_upstream(service: AvatarProxyService):
    payload = await service.resolve(
        cache_key="user:1",
        upstream_url=None,
        display_name="Tester",
        seed="1",
    )
    assert payload.content_type.startswith("image/svg+xml")
    assert b"T" in payload.body

    # Second call should hit the in-process cache.
    again = await service.resolve(
        cache_key="user:1",
        upstream_url=None,
        display_name="Tester",
        seed="1",
    )
    assert again.cache_hit is True
