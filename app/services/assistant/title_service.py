"""對話標題自動摘要：借用既有 `AssistantLLMService` 對「首則 user + 首則 assistant 文字」做單句摘要。

無 tool-calling（`tools=[]`），失敗／未設定一律回傳 `None`，由呼叫端（`ConversationService.maybe_generate_title`）
fallback 成使用者原文截斷,不重試、不拋例外（本模組不改變任何持久化狀態）。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.services.assistant.assistant_llm_service import get_assistant_llm_service

_TITLE_PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "assistant" / "title.md"

_QUOTE_STRIP_CHARS = "「」『』\"'`　 \t"


@lru_cache(maxsize=1)
def _load_title_prompt() -> str:
    return _TITLE_PROMPT_PATH.read_text(encoding="utf-8")


def _clean_title(raw_content: str, *, max_chars: int) -> Optional[str]:
    first_line = next((line.strip() for line in raw_content.splitlines() if line.strip()), "")
    cleaned = first_line.strip(_QUOTE_STRIP_CHARS)
    if not cleaned:
        return None
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars].rstrip() + "…"
    return cleaned


async def generate_title(*, user_text: str, assistant_text: str, max_chars: int) -> Optional[str]:
    """回傳 LLM 生成的短標題;未設定/呼叫失敗/清洗後為空一律回傳 None。"""
    llm_service = get_assistant_llm_service()
    try:
        result = await llm_service.call(
            system_prompt=_load_title_prompt(),
            messages=[{"role": "user", "content": f"使用者：{user_text}\n助手：{assistant_text}"}],
            tools=[],
        )
    except Exception:  # noqa: BLE001 — best-effort 摘要：任何呼叫層例外（未設定、連線、逾時、
        # 非預期回應格式）都必須 fallback，不得讓對話標題永久停留在 NULL。
        return None
    if not result.content:
        return None
    return _clean_title(result.content, max_chars=max_chars)
