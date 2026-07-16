import asyncio
from types import SimpleNamespace

import aiohttp
import pytest
from fastapi import HTTPException

from app.api import attachments


class _FakeContent:
    def __init__(self, chunks):
        self._chunks = chunks

    async def iter_chunked(self, chunk_size):
        assert chunk_size == 8192
        for chunk in self._chunks:
            yield chunk


class _FakeResponse:
    def __init__(self, status_code=200, headers=None, chunks=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.content = _FakeContent(chunks or [b"payload"])
        self.released = False

    def release(self):
        self.released = True


class _FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.closed = False

    async def get(self, *args, **kwargs):
        if self.error:
            raise self.error
        return self.response

    async def close(self):
        self.closed = True


def _install_session(monkeypatch, response=None, error=None):
    session = _FakeSession(response=response, error=error)
    monkeypatch.setattr(
        attachments.aiohttp,
        "ClientSession",
        lambda *args, **kwargs: session,
    )
    return session


@pytest.fixture
def proxy_dependencies(monkeypatch):
    client = SimpleNamespace(
        auth_manager=SimpleNamespace(get_tenant_access_token=lambda: "token")
    )

    async def _get_lark_client_for_team(*args, **kwargs):
        return client, SimpleNamespace()

    monkeypatch.setattr(
        attachments,
        "get_lark_client_for_team",
        _get_lark_client_for_team,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("upstream_status", "expected_status"),
    [(401, 401), (404, 404), (500, 502)],
)
async def test_lark_attachment_proxy_preserves_upstream_status_mapping(
    monkeypatch,
    proxy_dependencies,
    upstream_status,
    expected_status,
):
    upstream = _FakeResponse(status_code=upstream_status)
    session = _install_session(monkeypatch, response=upstream)

    with pytest.raises(HTTPException) as exc_info:
        await attachments.download_attachment_proxy(
            team_id=1,
            file_url="https://example.test/file",
            db=SimpleNamespace(),
            main_boundary=SimpleNamespace(),
        )

    assert exc_info.value.status_code == expected_status
    assert upstream.released is True
    assert session.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (asyncio.TimeoutError(), 504),
        (aiohttp.ClientConnectionError("offline"), 502),
    ],
)
async def test_lark_attachment_proxy_preserves_transport_error_mapping(
    monkeypatch,
    proxy_dependencies,
    error,
    expected_status,
):
    _install_session(monkeypatch, error=error)

    with pytest.raises(HTTPException) as exc_info:
        await attachments.download_attachment_proxy(
            team_id=1,
            file_url="https://example.test/file",
            db=SimpleNamespace(),
            main_boundary=SimpleNamespace(),
        )

    assert exc_info.value.status_code == expected_status


@pytest.mark.asyncio
async def test_lark_attachment_proxy_preserves_download_headers(
    monkeypatch,
    proxy_dependencies,
):
    upstream = _FakeResponse(
        headers={
            "content-type": "application/pdf",
            "content-length": "7",
        },
        chunks=[b"pay", b"load"],
    )
    session = _install_session(monkeypatch, response=upstream)

    response = await attachments.download_attachment_proxy(
        team_id=1,
        file_url="https://example.test/file",
        filename="測試.pdf",
        db=SimpleNamespace(),
        main_boundary=SimpleNamespace(),
    )
    body = b"".join([chunk async for chunk in response.body_iterator])

    assert body == b"payload"
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-length"] == "7"
    assert response.headers["content-disposition"] == (
        "attachment; filename*=UTF-8''%E6%B8%AC%E8%A9%A6.pdf"
    )
    assert upstream.released is True
    assert session.closed is True
