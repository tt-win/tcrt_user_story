"""Embedding service for knowledge graph.

支援兩種 provider：
- ``openrouter`` — 走 https://openrouter.ai/api/v1/embeddings（OpenAI 相容格式）
- ``openai`` — 走 ``base_url`` 指定的 OpenAI 相容端點（自架、LMStudio、vLLM 等）

兩者都使用相同的 OpenAI 風格 request/response shape。LMStudio 等
OpenAI 相容 server 通常不需要 API key，可將 ``EMBEDDING_API_KEY`` 留空。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from app.config import EmbeddingConfig

LOGGER = logging.getLogger(__name__)

# Default endpoints per provider.  For unknown / "openai" provider, the
# ``base_url`` config field is required.
_PROVIDER_ENDPOINTS: dict[str, str] = {
    "openrouter": "https://openrouter.ai/api/v1/embeddings",
}


class EmbeddingError(RuntimeError):
    pass


class EmbeddingRateLimitError(EmbeddingError):
    """Raised when the embedding provider returns HTTP 429.

    Carries the ``Retry-After`` header value (in seconds) so the caller can
    back off appropriately.
    """

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class EmbeddingService:
    """Embedding service with SQLite persistent cache."""

    def __init__(self, config: EmbeddingConfig) -> None:
        self._config = config
        self._cache_lock = threading.Lock()
        self._cache_conn: sqlite3.Connection | None = None
        self._http: httpx.AsyncClient | None = None
        if config.cache_path and config.cache_path.lower() != "none":
            self._init_cache(config.cache_path)

    def _init_cache(self, cache_path: str) -> None:
        path = Path(cache_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS embedding_cache (
                content_hash TEXT PRIMARY KEY,
                model TEXT NOT NULL,
                dimensions INTEGER NOT NULL,
                embedding BLOB NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_model_dims ON embedding_cache(model, dimensions)"
        )
        conn.commit()
        self._cache_conn = conn
        LOGGER.info("Embedding cache initialized at %s", cache_path)

    def _make_hash(self, content: str) -> str:
        key = f"{content}|{self._config.model}|{self._config.dimensions}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def get_cached(self, content: str) -> list[float] | None:
        if not self._cache_conn:
            return None
        content_hash = self._make_hash(content)
        with self._cache_lock:
            cursor = self._cache_conn.execute(
                "SELECT embedding FROM embedding_cache WHERE content_hash = ?",
                (content_hash,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        try:
            return json.loads(row[0].decode("utf-8"))
        except Exception:  # noqa: BLE001
            return None

    def set_cached(self, content: str, embedding: list[float]) -> None:
        if not self._cache_conn:
            return
        content_hash = self._make_hash(content)
        with self._cache_lock:
            self._cache_conn.execute(
                """
                INSERT OR REPLACE INTO embedding_cache (content_hash, model, dimensions, embedding, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    content_hash,
                    self._config.model,
                    self._config.dimensions,
                    json.dumps(embedding).encode("utf-8"),
                    time.time(),
                ),
            )
            self._cache_conn.commit()

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            headers = {"Content-Type": "application/json"}
            if self._config.api_key:
                headers["Authorization"] = f"Bearer {self._config.api_key}"
            self._http = httpx.AsyncClient(timeout=60.0, headers=headers)
        return self._http

    def _resolve_endpoint(self) -> str:
        """Resolve the embedding endpoint URL based on provider + base_url.

        - ``openrouter`` → hardcoded OpenRouter URL
        - ``openai`` (or any other OpenAI-compatible provider) → ``base_url``;
          if not set, fall back to ``https://api.openai.com/v1/embeddings``.

        Raises ``EmbeddingError`` if no endpoint can be determined.
        """
        provider = self._config.provider.lower()
        if provider == "openrouter":
            return _PROVIDER_ENDPOINTS["openrouter"]
        if self._config.base_url:
            base = self._config.base_url.rstrip("/")
            # Convenience: if the base_url already contains /v1, just append
            # /embeddings; otherwise append /v1/embeddings.
            if base.endswith("/v1"):
                return f"{base}/embeddings"
            return f"{base}/v1/embeddings"
        if provider == "openai":
            return "https://api.openai.com/v1/embeddings"
        raise EmbeddingError(
            f"Cannot resolve embedding endpoint for provider={provider!r}: "
            f"set EMBEDDING_BASE_URL or use provider=openrouter/openai"
        )

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        """Call an OpenAI-compatible /embeddings endpoint and return embeddings.

        Shared by ``openrouter`` (via the hardcoded URL) and ``openai`` (via
        ``base_url``).  Both speak the same request / response shape:
            request:  {"model": ..., "input": [...], "dimensions"?: int}
            response: {"data": [{"embedding": [...]}, ...]}
        """
        endpoint = self._resolve_endpoint()
        http = await self._get_http()
        payload: dict[str, Any] = {
            "model": self._config.model,
            "input": texts,
        }
        if self._config.dimensions:
            payload["dimensions"] = self._config.dimensions
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = await http.post(endpoint, json=payload)
                # Surface rate-limit / auth / server errors as a distinct
                # EmbeddingError so the caller can log + decide whether to
                # retry the whole batch.
                if resp.status_code == 429:
                    retry_after = resp.headers.get("retry-after")
                    wait_s = int(retry_after) if (retry_after and retry_after.isdigit()) else None
                    raise EmbeddingRateLimitError(
                        f"Embedding API rate limit (HTTP 429); retry_after={wait_s}s",
                        retry_after=wait_s,
                    )
                if resp.status_code >= 500:
                    raise EmbeddingError(
                        f"Embedding API server error: HTTP {resp.status_code} body={resp.text[:200]}"
                    )
                if resp.status_code >= 400:
                    # 4xx other than 429 is a permanent error: bad request,
                    # auth, model-not-found, etc.  Surface immediately.
                    raise EmbeddingError(
                        f"Embedding API rejected request: HTTP {resp.status_code} body={resp.text[:200]}"
                    )
                resp.raise_for_status()
                # Parse JSON defensively: an unexpected body shape should not
                # bubble as a bare KeyError.
                try:
                    data = resp.json()
                except Exception as exc:  # noqa: BLE001
                    raise EmbeddingError(
                        f"Embedding API returned non-JSON body: {resp.text[:200]}"
                    ) from exc
                if not isinstance(data, dict):
                    raise EmbeddingError(
                        f"Embedding API returned non-object JSON: {type(data).__name__}"
                    )
                if "error" in data and "data" not in data:
                    # Some providers return {"error": {...}} with status 200.
                    raise EmbeddingError(
                        f"Embedding API returned error object: {data['error']}"
                    )
                if "data" not in data:
                    raise EmbeddingError(
                        f"Embedding API response missing 'data' field; keys={list(data.keys())}"
                    )
                rows = data["data"]
                if not isinstance(rows, list):
                    raise EmbeddingError(
                        f"Embedding API 'data' is not a list: {type(rows).__name__}"
                    )
                embeddings: list[list[float]] = []
                for i, item in enumerate(rows):
                    if not isinstance(item, dict) or "embedding" not in item:
                        raise EmbeddingError(
                            f"Embedding API data[{i}] missing 'embedding' field"
                        )
                    embeddings.append(item["embedding"])
                if self._config.dimensions and any(len(e) != self._config.dimensions for e in embeddings):
                    raise EmbeddingError(
                        f"Embedding dimensions mismatch: expected {self._config.dimensions}, "
                        f"got {[len(e) for e in embeddings]}"
                    )
                return embeddings
            except EmbeddingRateLimitError as exc:
                # 429: surface immediately.  The caller (write service) decides
                # whether to wait + retry the whole batch or skip.  We do not
                # silently re-loop because a 3-attempt retry would just sleep
                # ~7s and hit the same wall.
                LOGGER.error(
                    "Embedding API rate-limited: %s (retry_after=%s)",
                    exc, exc.retry_after,
                )
                raise
            except EmbeddingError as exc:
                # 4xx / non-retryable — log full body once, give up.
                LOGGER.error("Embedding attempt %d failed (non-retryable): %s", attempt + 1, exc)
                raise
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                wait = 2 ** attempt
                LOGGER.warning("Embedding attempt %d failed: %s, retrying in %ds", attempt + 1, exc, wait)
                await asyncio.sleep(wait)
        raise EmbeddingError(f"Embedding API failed after 3 attempts: {last_exc}")

    # ---- Backwards-compatible alias (kept for tests + older call sites) ----

    async def _embed_openrouter(self, texts: list[str]) -> list[list[float]]:
        """Deprecated: use ``_embed`` which dispatches on provider."""
        return await self._embed(texts)

    def _truncate(self, text: str) -> str:
        # Simple char-based truncation (4 chars ~ 1 token heuristic, conservative)
        max_chars = self._config.max_tokens_per_text * 4
        if len(text) > max_chars:
            return text[:max_chars]
        return text

    async def embed_one(self, text: str) -> list[float]:
        text = self._truncate(text)
        cached = self.get_cached(text)
        if cached is not None:
            return cached
        result = await self._embed([text])
        embedding = result[0]
        self.set_cached(text, embedding)
        return embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts in batches.

        Splits the input into sub-batches of ``batch_size`` and runs them with
        ``concurrency``-wide parallelism.  With the default ``concurrency=1``
        this is sequential; with ``concurrency=8`` up to 8 sub-batches are
        in-flight at once, fully utilizing HTTP keep-alive + the provider's
        GPU.  The first sub-batch is the one passed in; subsequent ones are
        derived from the same list.  If the input has only one sub-batch
        (i.e. ``len(texts) <= batch_size``) concurrency has no effect.
        """
        if not texts:
            return []
        texts = [self._truncate(t) for t in texts]
        # 拆分 cached / not-cached
        results: list[list[float] | None] = [None] * len(texts)
        miss_indices: list[int] = []
        miss_texts: list[str] = []
        for idx, text in enumerate(texts):
            cached = self.get_cached(text)
            if cached is not None:
                results[idx] = cached
            else:
                miss_indices.append(idx)
                miss_texts.append(text)

        if not miss_texts:
            return [r for r in results if r is not None]

        # Split miss_texts into sub-batches of batch_size, preserving order
        batch_size = self._config.batch_size
        chunks: list[tuple[list[int], list[str]]] = []
        for start in range(0, len(miss_texts), batch_size):
            batch_texts = miss_texts[start : start + batch_size]
            batch_indices = miss_indices[start : start + batch_size]
            chunks.append((batch_indices, batch_texts))

        # Run chunks with concurrency-wide parallelism.  asyncio.Semaphore
        # bounds in-flight requests; gather() preserves input order.
        concurrency = max(1, self._config.concurrency)
        if concurrency == 1 or len(chunks) == 1:
            chunk_embeddings = [await self._embed(t) for _, t in chunks]
        else:
            sem = asyncio.Semaphore(concurrency)

            async def _run_one(idx_batch: tuple[list[int], list[str]]) -> list[list[float]]:
                async with sem:
                    return await self._embed(idx_batch[1])

            chunk_embeddings = await asyncio.gather(
                *(_run_one(c) for c in chunks)
            )

        # Stitch results back into the original `results` slots and update cache.
        for (indices, batch_texts), embeddings in zip(chunks, chunk_embeddings):
            for idx, text, emb in zip(indices, batch_texts, embeddings):
                results[idx] = emb
                self.set_cached(text, emb)

        return [r for r in results if r is not None]

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None
        if self._cache_conn is not None:
            self._cache_conn.close()
            self._cache_conn = None
