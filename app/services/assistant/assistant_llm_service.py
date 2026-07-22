"""OpenRouter tool-calling client（design D4；仿 `QAAIHelperLLMService` 的 aiohttp 慣例）。

與 QA AI Helper 的關鍵差異：
- 帶 `tools=`/`tool_choice="auto"`/`parallel_tool_calls=False`（LLM history 正規化，見 design D4）。
- **無 deterministic fallback**：`settings.openrouter.api_key` 缺失或 `assistant.enabled=False` 時
  直接拋 `AssistantNotConfiguredError`，不像 QA AI Helper 有離線退化模式（design D7：無 fallback）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

import aiohttp

from app.config import AssistantConfig, get_settings
from app.services.assistant.errors import AssistantNotConfiguredError

OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"


class AssistantLLMError(RuntimeError):
    """非預期的 OpenRouter 錯誤（非 context-length-exceeded）。"""


class AssistantLLMContextLengthError(AssistantLLMError):
    """provider 判定 request 超過 context window；agent loop 可裁掉最舊 exchange group 重試一次（design D4）。"""


@dataclass
class ParsedToolCall:
    provider_tool_call_id: Optional[str]
    name: str
    arguments: dict[str, Any]


@dataclass
class AssistantLLMResult:
    content: Optional[str]
    tool_calls: list[ParsedToolCall] = field(default_factory=list)
    finish_reason: Optional[str] = None
    model_name: Optional[str] = None
    response_id: Optional[str] = None


def _is_context_length_error(status: int, body_text: str) -> bool:
    if status != 400:
        return False
    lowered = body_text.lower()
    return "context" in lowered and ("length" in lowered or "too long" in lowered or "maximum" in lowered)


class AssistantLLMService:
    def __init__(self, settings=None):
        self._settings = settings or get_settings()

    @property
    def _config(self) -> AssistantConfig:
        return self._settings.ai.assistant

    def is_configured(self) -> bool:
        return bool(self._settings.openrouter.api_key) and self._config.enabled

    def _headers(self) -> dict[str, str]:
        api_key = self._settings.openrouter.api_key
        if not api_key:
            raise AssistantNotConfiguredError()
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        base_url = self._settings.app.get_base_url() if self._settings.app else ""
        if base_url:
            headers["HTTP-Referer"] = base_url
            headers["X-Title"] = "TCRT Assistant"
        return headers

    async def call(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AssistantLLMResult:
        """單次非串流 chat completion（design D4：v1 每次迭代非串流，UX 由 SSE 事件呈現）。"""
        if not self.is_configured():
            raise AssistantNotConfiguredError()

        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "temperature": self._config.temperature,
            # design D4「LLM history 正規化」：固定 false，讓模型一次只回一個 tool call；
            # agent loop 仍需防禦性處理 provider 回傳多筆的情況。
            "parallel_tool_calls": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        timeout = aiohttp.ClientTimeout(total=self._config.llm_timeout_seconds)
        async with aiohttp.ClientSession() as session:
            async with session.post(
                OPENROUTER_CHAT_COMPLETIONS_URL, headers=self._headers(), json=payload, timeout=timeout
            ) as response:
                text_body = await response.text()
                if response.status >= 400:
                    if _is_context_length_error(response.status, text_body):
                        raise AssistantLLMContextLengthError(f"OpenRouter context length exceeded: {text_body[:500]}")
                    raise AssistantLLMError(f"OpenRouter HTTP {response.status}: {text_body[:500]}")
                data = json.loads(text_body)

        return self._parse_response(data)

    def _parse_response(self, data: dict[str, Any]) -> AssistantLLMResult:
        choice = data["choices"][0]
        message = choice.get("message", {})
        finish_reason = choice.get("finish_reason")
        content = message.get("content")

        parsed_calls: list[ParsedToolCall] = []
        for raw_call in message.get("tool_calls") or []:
            fn = raw_call.get("function", {})
            raw_args = fn.get("arguments") or "{}"
            try:
                arguments = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            except (TypeError, ValueError):
                arguments = {}
            parsed_calls.append(
                ParsedToolCall(
                    provider_tool_call_id=raw_call.get("id"),
                    name=fn.get("name", ""),
                    arguments=arguments,
                )
            )

        return AssistantLLMResult(
            content=content,
            tool_calls=parsed_calls,
            finish_reason=finish_reason,
            model_name=data.get("model"),
            response_id=data.get("id"),
        )


_service_singleton: Optional[AssistantLLMService] = None


def get_assistant_llm_service() -> AssistantLLMService:
    global _service_singleton
    if _service_singleton is None:
        _service_singleton = AssistantLLMService()
    return _service_singleton
