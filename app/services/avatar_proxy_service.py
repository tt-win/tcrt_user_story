"""Avatar proxy: fetch upstream avatars server-side with short-lived cache.

Browsers never contact Feishu CDN / Gravatar directly. On upstream failure the
service returns a locally generated SVG initials placeholder.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Optional
from xml.sax.saxutils import escape

import httpx

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 3600
FETCH_TIMEOUT_SECONDS = 8.0
MAX_AVATAR_BYTES = 2 * 1024 * 1024

# Soft allowlist: only fetch known avatar upstream hosts (SSRF guard).
_ALLOWED_HOST_SUFFIXES = (
    "feishucdn.com",
    "larksuite.com",
    "feishu.cn",
    "gravatar.com",
    "googleusercontent.com",
)


@dataclass
class AvatarPayload:
    body: bytes
    content_type: str
    cache_hit: bool = False


@dataclass
class _CacheEntry:
    body: bytes
    content_type: str
    expires_at: float


class AvatarProxyService:
    """In-process short-lived avatar cache + upstream fetch + SVG fallback."""

    def __init__(self) -> None:
        self._cache: dict[str, _CacheEntry] = {}

    def user_proxy_url(self, user_id: int) -> str:
        return f"/api/avatars/users/{int(user_id)}"

    def lark_proxy_url(self, lark_user_id: str) -> str:
        return f"/api/avatars/lark/{lark_user_id}"

    def clear_cache(self) -> None:
        self._cache.clear()

    def _get_cached(self, key: str) -> Optional[AvatarPayload]:
        entry = self._cache.get(key)
        if not entry:
            return None
        if entry.expires_at < time.monotonic():
            self._cache.pop(key, None)
            return None
        return AvatarPayload(body=entry.body, content_type=entry.content_type, cache_hit=True)

    def _store(self, key: str, body: bytes, content_type: str) -> AvatarPayload:
        self._cache[key] = _CacheEntry(
            body=body,
            content_type=content_type,
            expires_at=time.monotonic() + CACHE_TTL_SECONDS,
        )
        return AvatarPayload(body=body, content_type=content_type, cache_hit=False)

    @staticmethod
    def _host_allowed(url: str) -> bool:
        try:
            from urllib.parse import urlparse

            host = (urlparse(url).hostname or "").lower()
        except Exception:  # noqa: BLE001
            return False
        if not host:
            return False
        return any(host == suffix or host.endswith(f".{suffix}") for suffix in _ALLOWED_HOST_SUFFIXES)

    async def fetch_upstream(self, url: Optional[str]) -> Optional[AvatarPayload]:
        if not url or not str(url).strip().startswith("http"):
            return None
        url = str(url).strip()
        if not self._host_allowed(url):
            logger.warning("Avatar upstream host rejected: %s", url[:120])
            return None

        cache_key = f"url:{hashlib.sha256(url.encode('utf-8')).hexdigest()}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=FETCH_TIMEOUT_SECONDS) as client:
                response = await client.get(url)
            if response.status_code != 200:
                logger.info("Avatar upstream HTTP %s for %s", response.status_code, url[:120])
                return None
            content_type = (response.headers.get("content-type") or "image/jpeg").split(";")[0].strip()
            if not content_type.startswith("image/"):
                logger.info("Avatar upstream non-image content-type %s", content_type)
                return None
            body = response.content
            if not body or len(body) > MAX_AVATAR_BYTES:
                return None
            return self._store(cache_key, body, content_type)
        except Exception as exc:  # noqa: BLE001
            logger.info("Avatar upstream fetch failed: %s", exc)
            return None

    @staticmethod
    def initials_for(name: Optional[str], fallback: str = "?") -> str:
        text = (name or "").strip()
        if not text:
            return fallback[:2]
        # Prefer first grapheme-ish char for CJK; two letters for Latin names.
        parts = [p for p in text.replace(",", " ").split() if p]
        if len(parts) >= 2 and parts[0][0].isascii() and parts[1][0].isascii():
            return (parts[0][0] + parts[1][0]).upper()
        return text[0].upper()

    def placeholder_svg(self, *, name: Optional[str] = None, seed: str = "") -> AvatarPayload:
        initials = escape(self.initials_for(name))
        # Stable soft color from seed/name.
        digest = hashlib.sha256((seed or name or initials).encode("utf-8")).hexdigest()
        hue = int(digest[:2], 16) * 360 // 255
        bg = f"hsl({hue}, 42%, 55%)"
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">'
            f'<rect width="128" height="128" rx="64" fill="{bg}"/>'
            f'<text x="64" y="64" dy="0.35em" text-anchor="middle" '
            f'font-family="Noto Sans, Noto Sans TC, sans-serif" font-size="52" font-weight="600" fill="#fff">'
            f"{initials}</text></svg>"
        )
        return AvatarPayload(body=svg.encode("utf-8"), content_type="image/svg+xml; charset=utf-8")

    async def resolve(
        self,
        *,
        cache_key: str,
        upstream_url: Optional[str],
        display_name: Optional[str],
        seed: str,
    ) -> AvatarPayload:
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        upstream = await self.fetch_upstream(upstream_url)
        if upstream:
            # Re-key under the logical cache key as well.
            return self._store(cache_key, upstream.body, upstream.content_type)

        placeholder = self.placeholder_svg(name=display_name, seed=seed)
        # Cache placeholders briefly too, to avoid hammering a dead upstream.
        return self._store(cache_key, placeholder.body, placeholder.content_type)


_avatar_proxy_service: Optional[AvatarProxyService] = None


def get_avatar_proxy_service() -> AvatarProxyService:
    global _avatar_proxy_service
    if _avatar_proxy_service is None:
        _avatar_proxy_service = AvatarProxyService()
    return _avatar_proxy_service
