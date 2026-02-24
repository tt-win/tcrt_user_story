"""
JIRA Test Case Helper - 統一 OpenRouter 呼叫服務
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Sequence

import aiohttp

from app.config import get_settings

HelperStage = Literal["analysis", "coverage", "testcase", "audit"]

logger = logging.getLogger(__name__)
LEGACY_STAGE_MODEL_ALIASES: Dict[str, str] = {
    "google/gemini-3-flash": "google/gemini-3-flash-preview",
}


@dataclass
class LLMStageResult:
    content: str
    usage: Dict[str, int]
    cost: float
    cost_note: str
    response_id: Optional[str] = None
    finish_reason: Optional[str] = None


class JiraTestCaseHelperLLMService:
    """集中管理 helper 各階段的 OpenRouter 呼叫。"""

    def __init__(self):
        self._settings = get_settings()

    @property
    def _openrouter_key(self) -> str:
        return (self._settings.openrouter.api_key or "").strip()

    def _stage_config(self, stage: HelperStage):
        return getattr(self._settings.ai.jira_testcase_helper.models, stage)

    @staticmethod
    def _resolve_stage_model_id(model_id: str) -> str:
        normalized = str(model_id or "").strip()
        return LEGACY_STAGE_MODEL_ALIASES.get(normalized, normalized)

    def resolve_stage_model_id(self, stage: HelperStage) -> str:
        stage_cfg = self._stage_config(stage)
        return self._resolve_stage_model_id(stage_cfg.model)

    def _base_headers(self) -> Dict[str, str]:
        if not self._openrouter_key:
            raise RuntimeError("OpenRouter API key 未設定")

        headers = {
            "Authorization": f"Bearer {self._openrouter_key}",
            "Content-Type": "application/json",
        }
        base_url = self._settings.app.get_base_url() if self._settings.app else ""
        if base_url:
            headers["HTTP-Referer"] = base_url
            headers["X-Title"] = "TCRT Jira Test Case Helper"
        return headers

    def _extract_usage_and_cost(self, data: Dict[str, Any]) -> tuple[Dict[str, int], float, str]:
        usage_raw = data.get("usage") or {}
        prompt_tokens = usage_raw.get("prompt_tokens") or usage_raw.get("promptTokens") or 0
        completion_tokens = (
            usage_raw.get("completion_tokens") or usage_raw.get("completionTokens") or 0
        )
        total_tokens = usage_raw.get("total_tokens") or usage_raw.get("totalTokens")
        if total_tokens is None:
            total_tokens = prompt_tokens + completion_tokens

        usage = {
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(completion_tokens or 0),
            "total_tokens": int(total_tokens or 0),
        }

        cost_value = (
            usage_raw.get("total_cost")
            or usage_raw.get("cost")
            or data.get("total_cost")
            or data.get("cost")
        )
        if cost_value is None:
            return usage, 0.0, "（費用未知）"
        try:
            return usage, float(cost_value), ""
        except (TypeError, ValueError):
            return usage, 0.0, "（費用未知）"

    @staticmethod
    def _coerce_content_text(raw: Any) -> str:
        if isinstance(raw, str):
            return raw.strip()
        if isinstance(raw, dict):
            fragments: List[str] = []
            for key in ("text", "content", "value", "output_text", "arguments"):
                candidate = raw.get(key)
                normalized = JiraTestCaseHelperLLMService._coerce_content_text(candidate)
                if normalized:
                    fragments.append(normalized)
            return "\n".join(fragments).strip()
        if isinstance(raw, list):
            fragments: List[str] = []
            for item in raw:
                if isinstance(item, str):
                    normalized = item.strip()
                    if normalized:
                        fragments.append(normalized)
                    continue
                if not isinstance(item, dict):
                    continue
                candidate = (
                    item.get("text")
                    or item.get("content")
                    or item.get("value")
                    or item.get("output_text")
                )
                if isinstance(candidate, str) and candidate.strip():
                    fragments.append(candidate.strip())
            return "\n".join(fragments).strip()
        return ""

    @classmethod
    def _extract_response_content(cls, data: Dict[str, Any]) -> str:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            fallback = cls._coerce_content_text(
                data.get("output_text") or data.get("content") or data.get("text")
            )
            return fallback
        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message") if isinstance(choice.get("message"), dict) else {}

        candidates: List[Any] = [
            message.get("content"),
            choice.get("text"),
            message.get("reasoning"),
            message.get("refusal"),
            message.get("output_text"),
            data.get("output_text"),
            data.get("content"),
        ]
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                function_payload = (
                    tool_call.get("function")
                    if isinstance(tool_call.get("function"), dict)
                    else {}
                )
                candidates.append(function_payload.get("arguments"))

        for candidate in candidates:
            content = cls._coerce_content_text(candidate)
            if content:
                return content
        return ""

    @staticmethod
    def _is_response_format_unsupported_error(exc: Exception) -> bool:
        message = str(exc or "").lower()
        if "response_format" not in message and "json_object" not in message:
            return False
        unsupported_signals = (
            "not support",
            "unsupported",
            "invalid",
            "unknown",
            "unrecognized",
            "not available",
            "does not support",
            "not allowed",
        )
        return any(signal in message for signal in unsupported_signals)

    async def _post_json_with_retry(
        self,
        *,
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
        timeout_seconds: int,
        retries: int = 3,
    ) -> Dict[str, Any]:
        last_error: Optional[Exception] = None
        timeout = aiohttp.ClientTimeout(total=max(1, timeout_seconds))

        for attempt in range(1, max(1, retries) + 1):
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(url, headers=headers, json=payload) as response:
                        text_body = await response.text()
                        if response.status == 429 and attempt < retries:
                            retry_after = response.headers.get("Retry-After")
                            wait_seconds = 1.5 * attempt
                            if retry_after:
                                try:
                                    wait_seconds = float(retry_after)
                                except ValueError:
                                    pass
                            await asyncio.sleep(wait_seconds)
                            continue

                        if response.status >= 400:
                            detail = text_body
                            try:
                                error_payload = json.loads(text_body)
                                if isinstance(error_payload, dict):
                                    detail = (
                                        error_payload.get("error", {}).get("message")
                                        or error_payload.get("message")
                                        or text_body
                                    )
                            except json.JSONDecodeError:
                                pass
                            raise RuntimeError(
                                f"OpenRouter API 失敗 ({response.status}): {detail}"
                            )

                        try:
                            return json.loads(text_body)
                        except json.JSONDecodeError as exc:
                            raise RuntimeError("OpenRouter 回傳非 JSON 內容") from exc
            except Exception as exc:
                last_error = exc
                if attempt >= retries:
                    break
                wait_seconds = min(2 ** (attempt - 1), 4)
                logger.warning(
                    "OpenRouter 呼叫失敗（第 %s/%s 次）: %s，%.1fs 後重試",
                    attempt,
                    retries,
                    exc,
                    wait_seconds,
                )
                await asyncio.sleep(wait_seconds)

        if last_error is not None:
            raise last_error
        raise RuntimeError("OpenRouter 呼叫失敗")

    @staticmethod
    def strip_json_fences(content: str) -> str:
        normalized = (content or "").strip()
        if not normalized.startswith("```"):
            return normalized

        lines = normalized.splitlines()
        if not lines:
            return normalized

        first_line = lines[0].strip().lower()
        if not first_line.startswith("```"):
            return normalized

        body_lines = lines[1:]
        if body_lines and body_lines[0].strip().lower() in {"json", "jsonc"}:
            body_lines = body_lines[1:]

        if body_lines and body_lines[-1].strip().startswith("```"):
            body_lines = body_lines[:-1]

        return "\n".join(body_lines).strip()

    @staticmethod
    def _extract_first_json_block(text: str) -> Optional[str]:
        source = str(text or "")
        start: Optional[int] = None
        stack: List[str] = []
        in_string = False
        escaped = False

        for idx, ch in enumerate(source):
            if in_string:
                if escaped:
                    escaped = False
                    continue
                if ch == "\\":
                    escaped = True
                    continue
                if ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
                continue

            if ch in "{[":
                if start is None:
                    start = idx
                stack.append(ch)
                continue

            if ch in "}]":
                if not stack:
                    continue
                top = stack.pop()
                if (top == "{" and ch != "}") or (top == "[" and ch != "]"):
                    return None
                if not stack and start is not None:
                    return source[start : idx + 1]

        return None

    @staticmethod
    def _escape_unescaped_newlines_in_strings(text: str) -> str:
        source = str(text or "")
        result: List[str] = []
        in_string = False
        escaped = False

        for ch in source:
            if in_string:
                if escaped:
                    result.append(ch)
                    escaped = False
                    continue
                if ch == "\\":
                    result.append(ch)
                    escaped = True
                    continue
                if ch == '"':
                    result.append(ch)
                    in_string = False
                    continue
                if ch == "\n":
                    result.append("\\n")
                    continue
                if ch == "\r":
                    result.append("\\r")
                    continue
                result.append(ch)
                continue

            result.append(ch)
            if ch == '"':
                in_string = True

        return "".join(result)

    @staticmethod
    def _remove_trailing_commas(text: str) -> str:
        source = str(text or "")
        result: List[str] = []
        in_string = False
        escaped = False
        length = len(source)
        idx = 0

        while idx < length:
            ch = source[idx]
            if in_string:
                result.append(ch)
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                idx += 1
                continue

            if ch == '"':
                in_string = True
                result.append(ch)
                idx += 1
                continue

            if ch == ",":
                lookahead = idx + 1
                while lookahead < length and source[lookahead] in {" ", "\t", "\r", "\n"}:
                    lookahead += 1
                if lookahead < length and source[lookahead] in {"]", "}"}:
                    idx += 1
                    continue

            result.append(ch)
            idx += 1

        return "".join(result)

    @staticmethod
    def _insert_missing_commas(text: str) -> str:
        """嘗試修復常見的缺逗號 JSON（object key/value 或 array item 之間）。"""

        source = str(text or "")
        if not source:
            return source

        result: List[str] = []
        in_string = False
        escaped = False
        idx = 0
        length = len(source)
        stack: List[Dict[str, str]] = []

        def _top() -> Optional[Dict[str, str]]:
            return stack[-1] if stack else None

        def _set_parent_value_consumed() -> None:
            parent = _top()
            if not parent:
                return
            if parent["type"] == "object" and parent["expecting"] == "value":
                parent["expecting"] = "comma_or_end"
            elif parent["type"] == "array" and parent["expecting"] == "value_or_end":
                parent["expecting"] = "comma_or_end"

        while idx < length:
            ch = source[idx]

            if in_string:
                result.append(ch)
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                    ctx = _top()
                    if ctx:
                        if ctx["type"] == "object":
                            if ctx["expecting"] == "key_or_end":
                                ctx["expecting"] = "colon"
                            elif ctx["expecting"] == "value":
                                ctx["expecting"] = "comma_or_end"
                        elif ctx["type"] == "array" and ctx["expecting"] == "value_or_end":
                            ctx["expecting"] = "comma_or_end"
                idx += 1
                continue

            if ch in {" ", "\t", "\r", "\n"}:
                result.append(ch)
                idx += 1
                continue

            ctx = _top()
            if ctx:
                if ctx["type"] == "object" and ctx["expecting"] == "comma_or_end" and ch == '"':
                    result.append(",")
                    ctx["expecting"] = "key_or_end"
                elif (
                    ctx["type"] == "array"
                    and ctx["expecting"] == "comma_or_end"
                    and ch not in {",", "]"}
                ):
                    result.append(",")
                    ctx["expecting"] = "value_or_end"

            ctx = _top()
            if ch == '"':
                in_string = True
                result.append(ch)
                idx += 1
                continue

            if ch == "{":
                result.append(ch)
                _set_parent_value_consumed()
                stack.append({"type": "object", "expecting": "key_or_end"})
                idx += 1
                continue

            if ch == "[":
                result.append(ch)
                _set_parent_value_consumed()
                stack.append({"type": "array", "expecting": "value_or_end"})
                idx += 1
                continue

            if ch == "}":
                result.append(ch)
                if stack and stack[-1]["type"] == "object":
                    stack.pop()
                    _set_parent_value_consumed()
                idx += 1
                continue

            if ch == "]":
                result.append(ch)
                if stack and stack[-1]["type"] == "array":
                    stack.pop()
                    _set_parent_value_consumed()
                idx += 1
                continue

            if ch == ":":
                result.append(ch)
                if ctx and ctx["type"] == "object":
                    ctx["expecting"] = "value"
                idx += 1
                continue

            if ch == ",":
                result.append(ch)
                if ctx:
                    if ctx["type"] == "object":
                        ctx["expecting"] = "key_or_end"
                    elif ctx["type"] == "array":
                        ctx["expecting"] = "value_or_end"
                idx += 1
                continue

            literal_start = idx
            while idx < length and source[idx] not in {" ", "\t", "\r", "\n", ",", "]", "}"}:
                result.append(source[idx])
                idx += 1

            if idx > literal_start:
                ctx_after_literal = _top()
                if ctx_after_literal:
                    if (
                        ctx_after_literal["type"] == "object"
                        and ctx_after_literal["expecting"] == "value"
                    ):
                        ctx_after_literal["expecting"] = "comma_or_end"
                    elif (
                        ctx_after_literal["type"] == "array"
                        and ctx_after_literal["expecting"] == "value_or_end"
                    ):
                        ctx_after_literal["expecting"] = "comma_or_end"

        return "".join(result)

    @classmethod
    def parse_json_payload(cls, content: str) -> Any:
        raw = str(content or "").strip()
        if not raw:
            raise ValueError("LLM 回傳內容為空")

        candidates: List[str] = []

        def _add_candidate(value: Optional[str]) -> None:
            normalized = str(value or "").strip()
            if normalized and normalized not in candidates:
                candidates.append(normalized)

        _add_candidate(raw)
        stripped = cls.strip_json_fences(raw)
        _add_candidate(stripped)
        _add_candidate(cls._extract_first_json_block(stripped))
        if stripped != raw:
            _add_candidate(cls._extract_first_json_block(raw))

        last_error: Optional[Exception] = None
        for candidate in candidates:
            variants: List[str] = []

            def _add_variant(value: str) -> None:
                if value not in variants:
                    variants.append(value)

            _add_variant(candidate)
            escaped_newlines = cls._escape_unescaped_newlines_in_strings(candidate)
            _add_variant(escaped_newlines)
            _add_variant(cls._remove_trailing_commas(candidate))
            _add_variant(cls._remove_trailing_commas(escaped_newlines))
            missing_commas = cls._insert_missing_commas(candidate)
            _add_variant(missing_commas)
            _add_variant(cls._remove_trailing_commas(missing_commas))
            missing_commas_escaped = cls._insert_missing_commas(escaped_newlines)
            _add_variant(missing_commas_escaped)
            _add_variant(cls._remove_trailing_commas(missing_commas_escaped))

            for variant in variants:
                try:
                    return json.loads(variant)
                except json.JSONDecodeError as exc:
                    last_error = exc
                    continue

        if last_error is not None:
            raise ValueError(f"LLM JSON 解析失敗: {last_error}") from last_error
        raise ValueError("LLM JSON 解析失敗")

    async def call_stage(
        self,
        *,
        stage: HelperStage,
        prompt: str,
        system_prompt_override: Optional[str] = None,
        max_tokens: Optional[int] = None,
        expect_json: bool = False,
    ) -> LLMStageResult:
        stage_cfg = self._stage_config(stage)
        headers = self._base_headers()

        messages: List[Dict[str, str]] = []
        system_prompt = system_prompt_override or stage_cfg.system_prompt
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        resolved_model_id = self._resolve_stage_model_id(stage_cfg.model)
        if resolved_model_id != stage_cfg.model:
            logger.warning(
                "偵測到舊版 helper model id `%s`，已自動改用 `%s`",
                stage_cfg.model,
                resolved_model_id,
            )
        resolved_max_tokens: Optional[int] = None
        if max_tokens is not None:
            try:
                resolved_max_tokens = max(1, int(max_tokens))
            except (TypeError, ValueError):
                logger.warning("收到非法 max_tokens=%r，忽略並改用模型預設上限", max_tokens)
        logger.info(
            "Helper LLM 呼叫: stage=%s model=%s temperature=%.3f max_tokens=%s expect_json=%s",
            stage,
            resolved_model_id,
            stage_cfg.temperature,
            resolved_max_tokens if resolved_max_tokens is not None else "unset(default)",
            expect_json,
        )

        payload = {
            "model": resolved_model_id,
            "messages": messages,
            "temperature": stage_cfg.temperature,
        }
        if resolved_max_tokens is not None:
            payload["max_tokens"] = resolved_max_tokens
        if expect_json:
            payload["response_format"] = {"type": "json_object"}
        try:
            data = await self._post_json_with_retry(
                url=stage_cfg.api_url,
                headers=headers,
                payload=payload,
                timeout_seconds=stage_cfg.timeout,
                retries=3,
            )
        except Exception as exc:
            if expect_json and self._is_response_format_unsupported_error(exc):
                logger.warning(
                    "模型 `%s` 不支援 response_format=json_object，改用 prompt 規範 fallback",
                    resolved_model_id,
                )
                payload.pop("response_format", None)
                data = await self._post_json_with_retry(
                    url=stage_cfg.api_url,
                    headers=headers,
                    payload=payload,
                    timeout_seconds=stage_cfg.timeout,
                    retries=3,
                )
            else:
                raise
        content = self._extract_response_content(data)
        finish_reason = (
            (data.get("choices") or [{}])[0].get("finish_reason")
            if isinstance((data.get("choices") or [{}])[0], dict)
            else None
        )
        if not content:
            logger.warning(
                "OpenRouter 回傳空內容: stage=%s model=%s finish_reason=%s response_id=%s",
                stage,
                resolved_model_id,
                finish_reason,
                data.get("id"),
            )
            raise RuntimeError("OpenRouter 回傳內容為空")

        usage, cost, cost_note = self._extract_usage_and_cost(data)
        return LLMStageResult(
            content=content,
            usage=usage,
            cost=cost,
            cost_note=cost_note,
            response_id=data.get("id"),
            finish_reason=finish_reason,
        )

    async def create_embedding(
        self,
        text: str,
        *,
        model: str = "baai/bge-m3",
        api_url: str = "https://openrouter.ai/api/v1/embeddings",
    ) -> Sequence[float]:
        headers = self._base_headers()
        payload = {
            "model": model,
            "input": [text],
        }
        data = await self._post_json_with_retry(
            url=api_url,
            headers=headers,
            payload=payload,
            timeout_seconds=60,
            retries=3,
        )
        items = data.get("data", [])
        if not items:
            raise RuntimeError("Embedding 回傳為空")
        embedding = items[0].get("embedding")
        if not isinstance(embedding, list) or not embedding:
            raise RuntimeError("Embedding 格式錯誤")
        return embedding


_jira_testcase_helper_llm_service: Optional[JiraTestCaseHelperLLMService] = None


def get_jira_testcase_helper_llm_service() -> JiraTestCaseHelperLLMService:
    global _jira_testcase_helper_llm_service
    if _jira_testcase_helper_llm_service is None:
        _jira_testcase_helper_llm_service = JiraTestCaseHelperLLMService()
    return _jira_testcase_helper_llm_service
