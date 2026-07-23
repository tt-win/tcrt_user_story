"""Tests for EmbeddingService error handling (OpenRouter transient / rate-limit / 4xx).

These tests use a mock httpx.AsyncClient so no real network call is made.
The real backfill run on 2026-07-23 hit ``KeyError: 'data'`` because
OpenRouter returned an error object without a ``data`` field; the
production code now distinguishes transient vs permanent failures.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import EmbeddingConfig
from app.services.knowledge.embedding_service import (
    EmbeddingError,
    EmbeddingRateLimitError,
    EmbeddingService,
)


def _mock_response(
    status_code: int,
    body: dict[str, Any] | str,
    headers: dict[str, str] | None = None,
) -> MagicMock:
    """Build a stand-in for ``httpx.Response`` for testing the parser."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    if isinstance(body, str):
        resp.text = body
        resp.json.side_effect = json.JSONDecodeError("not json", body, 0)
    else:
        resp.text = json.dumps(body)
        resp.json.return_value = body
    resp.raise_for_status.side_effect = None
    return resp


def _make_svc() -> EmbeddingService:
    cfg = EmbeddingConfig(
        model="m",
        dimensions=4,
        provider="openrouter",
        api_key="test-key",
        cache_path="",  # disable SQLite
    )
    return EmbeddingService(cfg)


# ---- success path ----


@pytest.mark.asyncio
async def test_embed_openrouter_parses_data_field() -> None:
    """Sanity: a normal response with 'data' field is parsed."""
    svc = _make_svc()
    resp = _mock_response(
        200,
        {"data": [{"embedding": [0.1, 0.2, 0.3, 0.4]}]},
    )
    http = MagicMock()
    http.post = AsyncMock(return_value=resp)
    svc._http = http  # bypass lazy init
    out = await svc._embed_openrouter(["hi"])
    assert out == [[0.1, 0.2, 0.3, 0.4]]


# ---- 4xx (non-429) — non-retryable ----


@pytest.mark.asyncio
async def test_4xx_does_not_retry() -> None:
    """4xx (auth / bad request) is permanent — do not retry, raise immediately."""
    svc = _make_svc()
    resp = _mock_response(
        401,
        {"error": {"message": "invalid api key", "code": 401}},
    )
    http = MagicMock()
    http.post = AsyncMock(return_value=resp)
    svc._http = http
    with pytest.raises(EmbeddingError) as exc:
        await svc._embed_openrouter(["hi"])
    assert "401" in str(exc.value)
    # Only one HTTP call should have been made.
    assert http.post.await_count == 1


@pytest.mark.asyncio
async def test_4xx_with_bare_text_body_raises() -> None:
    """4xx with text body (e.g. HTML error page) still surfaces the status."""
    svc = _make_svc()
    resp = _mock_response(400, "Bad Request")
    http = MagicMock()
    http.post = AsyncMock(return_value=resp)
    svc._http = http
    with pytest.raises(EmbeddingError) as exc:
        await svc._embed_openrouter(["hi"])
    assert "400" in str(exc.value)


# ---- 5xx — retryable (handled by retry loop) ----


@pytest.mark.asyncio
async def test_5xx_raises_with_body_in_message() -> None:
    """5xx error includes the response body in the message for debugging."""
    svc = _make_svc()
    resp = _mock_response(
        500,
        {"error": "internal server error"},
    )
    http = MagicMock()
    http.post = AsyncMock(return_value=resp)
    svc._http = http
    with pytest.raises(EmbeddingError) as exc:
        await svc._embed_openrouter(["hi"])
    assert "500" in str(exc.value)
    assert "internal server error" in str(exc.value)


# ---- 429 — rate limit ----


@pytest.mark.asyncio
async def test_429_carries_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 429 with Retry-After header raises EmbeddingRateLimitError carrying it.

    The retry loop catches the rate-limit error and sleeps; we patch
    ``asyncio.sleep`` to be instant so the test doesn't actually wait 5s.
    """
    import app.services.knowledge.embedding_service as mod

    monkeypatch.setattr(mod.asyncio, "sleep", AsyncMock())

    svc = _make_svc()
    resp = _mock_response(
        429,
        {"error": "rate limit exceeded"},
        headers={"retry-after": "5"},
    )
    http = MagicMock()
    http.post = AsyncMock(return_value=resp)
    svc._http = http
    with pytest.raises(EmbeddingRateLimitError) as exc:
        await svc._embed_openrouter(["hi"])
    assert exc.value.retry_after == 5


# ---- 200 with malformed body ----


@pytest.mark.asyncio
async def test_200_missing_data_field_raises_with_keys() -> None:
    """The original 2026-07-23 production bug: 200 with an 'error' object and
    no 'data' field. Must now raise EmbeddingError (not bare KeyError) and
    surface the error object for debugging."""
    svc = _make_svc()
    resp = _mock_response(
        200,
        {"error": {"message": "model overloaded", "type": "server_error"}},
    )
    http = MagicMock()
    http.post = AsyncMock(return_value=resp)
    svc._http = http
    with pytest.raises(EmbeddingError) as exc:
        await svc._embed_openrouter(["hi"])
    assert "error object" in str(exc.value)
    assert "model overloaded" in str(exc.value)


@pytest.mark.asyncio
async def test_200_missing_data_no_error_raises_with_keys() -> None:
    """200 with no 'data' AND no 'error' field: also surfaces the keys
    that were actually returned (defensive against future shape changes)."""
    svc = _make_svc()
    resp = _mock_response(200, {"usage": {"prompt_tokens": 5}})
    http = MagicMock()
    http.post = AsyncMock(return_value=resp)
    svc._http = http
    with pytest.raises(EmbeddingError) as exc:
        await svc._embed_openrouter(["hi"])
    assert "missing 'data' field" in str(exc.value)
    assert "usage" in str(exc.value)


@pytest.mark.asyncio
async def test_200_non_object_json_raises() -> None:
    """Body is valid JSON but the top-level value is a list, not a dict."""
    svc = _make_svc()
    # Use a real dict-shaped mock so resp.json() succeeds; then make the
    # parsed value be a list by overriding json() to return a list.
    resp = _mock_response(200, {})
    resp.json = MagicMock(return_value=[1, 2, 3])
    http = MagicMock()
    http.post = AsyncMock(return_value=resp)
    svc._http = http
    with pytest.raises(EmbeddingError) as exc:
        await svc._embed_openrouter(["hi"])
    assert "non-object" in str(exc.value)


@pytest.mark.asyncio
async def test_200_data_not_list_raises() -> None:
    svc = _make_svc()
    resp = _mock_response(200, {"data": "not a list"})
    http = MagicMock()
    http.post = AsyncMock(return_value=resp)
    svc._http = http
    with pytest.raises(EmbeddingError) as exc:
        await svc._embed_openrouter(["hi"])
    assert "not a list" in str(exc.value)


@pytest.mark.asyncio
async def test_200_row_missing_embedding_raises() -> None:
    svc = _make_svc()
    resp = _mock_response(200, {"data": [{"object": "embedding"}]})  # no 'embedding' key
    http = MagicMock()
    http.post = AsyncMock(return_value=resp)
    svc._http = http
    with pytest.raises(EmbeddingError) as exc:
        await svc._embed_openrouter(["hi"])
    assert "missing 'embedding'" in str(exc.value)


# ---- dimension validation ----


@pytest.mark.asyncio
async def test_dimension_mismatch_raises() -> None:
    svc = _make_svc()
    resp = _mock_response(
        200,
        {"data": [{"embedding": [0.1, 0.2]}]},  # only 2 dims
    )
    http = MagicMock()
    http.post = AsyncMock(return_value=resp)
    svc._http = http
    with pytest.raises(EmbeddingError) as exc:
        await svc._embed_openrouter(["hi"])
    assert "dimensions mismatch" in str(exc.value)


# ---- provider dispatch (openai + base_url) ----


def test_resolve_endpoint_openrouter_uses_hardcoded_url() -> None:
    """Provider=openrouter → hardcoded openrouter.ai URL, base_url ignored."""
    cfg = EmbeddingConfig(
        model="m", dimensions=4, provider="openrouter", api_key="k",
        base_url="https://should-be-ignored.example.com",
        cache_path="",
    )
    svc = EmbeddingService(cfg)
    assert svc._resolve_endpoint() == "https://openrouter.ai/api/v1/embeddings"


def test_resolve_endpoint_openai_uses_base_url() -> None:
    """Provider=openai + base_url → uses base_url + /v1/embeddings."""
    cfg = EmbeddingConfig(
        model="m", dimensions=4, provider="openai", base_url="https://lmstudio.example.com",
        cache_path="",
    )
    svc = EmbeddingService(cfg)
    assert svc._resolve_endpoint() == "https://lmstudio.example.com/v1/embeddings"


def test_resolve_endpoint_openai_base_url_with_v1_suffix() -> None:
    """If base_url already ends in /v1, just append /embeddings (don't double)."""
    cfg = EmbeddingConfig(
        model="m", dimensions=4, provider="openai",
        base_url="https://lmstudio.example.com/v1",
        cache_path="",
    )
    svc = EmbeddingService(cfg)
    assert svc._resolve_endpoint() == "https://lmstudio.example.com/v1/embeddings"


def test_resolve_endpoint_openai_no_base_url_falls_back_to_openai() -> None:
    """No base_url for provider=openai → fall back to api.openai.com."""
    cfg = EmbeddingConfig(
        model="m", dimensions=4, provider="openai",
        cache_path="",
    )
    svc = EmbeddingService(cfg)
    assert svc._resolve_endpoint() == "https://api.openai.com/v1/embeddings"


def test_resolve_endpoint_unknown_provider_without_base_url_raises() -> None:
    """An unrecognized provider with no base_url must fail fast, not silently
    route to a wrong URL."""
    cfg = EmbeddingConfig(
        model="m", dimensions=4, provider="custom-thing", cache_path="",
    )
    svc = EmbeddingService(cfg)
    with pytest.raises(EmbeddingError) as exc:
        svc._resolve_endpoint()
    assert "EMBEDDING_BASE_URL" in str(exc.value)


@pytest.mark.asyncio
async def test_embed_one_dispatches_to_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """embed_one must call the resolved endpoint URL (not hardcoded openrouter)."""
    cfg = EmbeddingConfig(
        model="custom-model", dimensions=4, provider="openai",
        base_url="https://my-llm.example.com/v1",
        cache_path="",
    )
    svc = EmbeddingService(cfg)
    resp = _mock_response(200, {"data": [{"embedding": [0.5, 0.5, 0.5, 0.5]}]})
    http = MagicMock()
    http.post = AsyncMock(return_value=resp)
    svc._http = http

    out = await svc.embed_one("hi")
    assert out == [0.5, 0.5, 0.5, 0.5]
    # Verify the URL hit was the custom one, NOT openrouter.ai
    called_url = http.post.await_args.args[0]
    assert called_url == "https://my-llm.example.com/v1/embeddings"
    # And the model was passed through
    called_payload = http.post.await_args.kwargs["json"]
    assert called_payload["model"] == "custom-model"


# ---- concurrency (asyncio.gather with semaphore) ----


def _make_concurrency_svc(concurrency: int) -> EmbeddingService:
    cfg = EmbeddingConfig(
        model="m", dimensions=4, provider="openai",
        base_url="https://x.example.com/v1",
        batch_size=10,
        concurrency=concurrency,
        cache_path="",
    )
    return EmbeddingService(cfg)


@pytest.mark.asyncio
async def test_concurrency_1_runs_sequentially(monkeypatch: pytest.MonkeyPatch) -> None:
    """concurrency=1: chunks run one after another (no gather)."""
    svc = _make_concurrency_svc(1)
    in_flight = 0
    max_in_flight = 0
    call_count = 0

    async def _fake_post(*args, **kwargs):
        nonlocal in_flight, max_in_flight, call_count
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        call_count += 1
        n = len(kwargs["json"]["input"])
        return _mock_response(200, {"data": [{"embedding": [0.1] * 4} for _ in range(n)]})

    http = MagicMock()
    http.post = AsyncMock(side_effect=_fake_post)
    svc._http = http

    # 30 texts → 3 chunks of 10
    out = await svc.embed_batch([f"text {i}" for i in range(30)])
    assert len(out) == 30
    assert call_count == 3
    assert max_in_flight == 1  # never more than 1 concurrent


@pytest.mark.asyncio
async def test_concurrency_4_runs_in_parallel(monkeypatch: pytest.MonkeyPatch) -> None:
    """concurrency=4: up to 4 chunks in flight at once."""
    svc = _make_concurrency_svc(4)
    in_flight = 0
    max_in_flight = 0
    call_count = 0

    async def _fake_post(*args, **kwargs):
        nonlocal in_flight, max_in_flight, call_count
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.05)  # simulate slow API
        in_flight -= 1
        call_count += 1
        n = len(kwargs["json"]["input"])
        return _mock_response(200, {"data": [{"embedding": [0.1] * 4} for _ in range(n)]})

    http = MagicMock()
    http.post = AsyncMock(side_effect=_fake_post)
    svc._http = http

    # 80 texts → 8 chunks of 10, semaphore=4 → at most 4 concurrent
    out = await svc.embed_batch([f"text {i}" for i in range(80)])
    assert len(out) == 80
    assert call_count == 8
    assert max_in_flight == 4  # bounded by semaphore


@pytest.mark.asyncio
async def test_concurrency_8_with_2_chunks_runs_2_in_parallel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """concurrency=8 but only 2 chunks of 100 → at most 2 concurrent."""
    svc = _make_concurrency_svc(8)
    in_flight = 0
    max_in_flight = 0
    call_count = 0

    async def _fake_post(*args, **kwargs):
        nonlocal in_flight, max_in_flight, call_count
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.05)
        in_flight -= 1
        call_count += 1
        n = len(kwargs["json"]["input"])
        return _mock_response(200, {"data": [{"embedding": [0.1] * 4} for _ in range(n)]})

    http = MagicMock()
    http.post = AsyncMock(side_effect=_fake_post)
    svc._http = http

    # 20 texts, batch_size=10 → 2 chunks
    out = await svc.embed_batch([f"text {i}" for i in range(20)])
    assert len(out) == 20
    assert call_count == 2
    assert max_in_flight == 2  # only 2 chunks, semaphore is 8 but only 2 chunks exist


@pytest.mark.asyncio
async def test_concurrency_preserves_order() -> None:
    """Output order must match input order even with parallelism."""
    svc = _make_concurrency_svc(4)
    http = MagicMock()
    async def _fake_post(*args, **kwargs):
        # Each text gets a unique embedding so we can check order
        embeds = []
        for text in kwargs["json"]["input"]:
            # The text is "text N", extract N
            n_idx = int(text.split()[1])
            embeds.append({"embedding": [float(n_idx)] * 4})
        await asyncio.sleep(0.01)  # add jitter
        return _mock_response(200, {"data": embeds})

    http.post = AsyncMock(side_effect=_fake_post)
    svc._http = http

    # 50 texts, batch_size=10 → 5 chunks
    out = await svc.embed_batch([f"text {i}" for i in range(50)])
    # Output must be in input order
    assert len(out) == 50
    for i, emb in enumerate(out):
        assert emb[0] == float(i), f"position {i} got embedding {emb}"


@pytest.mark.asyncio
async def test_concurrency_skips_cached_texts(tmp_path) -> None:
    """Cached texts don't get re-embedded even with concurrency > 1."""
    cfg = EmbeddingConfig(
        model="m", dimensions=4, provider="openai",
        base_url="https://x.example.com/v1",
        batch_size=10,
        concurrency=4,
        cache_path=str(tmp_path / "cache.db"),  # enable SQLite
    )
    svc = EmbeddingService(cfg)
    # Manually populate cache for first 20 items
    for i in range(20):
        svc.set_cached(f"text {i}", [float(i)] * 4)

    call_count = 0
    async def _fake_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        n = len(kwargs["json"]["input"])
        return _mock_response(200, {"data": [{"embedding": [0.0] * 4} for _ in range(n)]})

    http = MagicMock()
    http.post = AsyncMock(side_effect=_fake_post)
    svc._http = http

    # 30 texts: first 20 cached, last 10 not. Should be 1 API call.
    out = await svc.embed_batch([f"text {i}" for i in range(30)])
    assert len(out) == 30
    assert call_count == 1
    # First 20 must come from cache
    for i in range(20):
        assert out[i][0] == float(i)
    # Last 10 are from the API (all zeros)
    for i in range(20, 30):
        assert out[i] == [0.0] * 4
