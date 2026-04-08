"""OpenRouter wrapper for the rewritten QA AI Helper.

設計目標：
- 支援 seed / seed_refine / testcase stage，並暫時保留 legacy repair alias
- 若未設定 OpenRouter key，提供 deterministic local fallback
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

import aiohttp

from app.config import get_settings

QAAIHelperLLMStage = Literal["seed", "seed_refine", "testcase", "repair"]

logger = logging.getLogger(__name__)
OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"


@dataclass
class QAAIHelperLLMResult:
    content: str
    usage: Dict[str, int]
    cost: float
    cost_note: str
    model_name: Optional[str] = None
    response_id: Optional[str] = None


class QAAIHelperLLMService:
    def __init__(self) -> None:
        self._settings = get_settings()

    @property
    def _openrouter_key(self) -> str:
        return (self._settings.openrouter.api_key or "").strip()

    def _stage_config(self, stage: QAAIHelperLLMStage):
        if stage == "seed":
            return self._settings.ai.qa_ai_helper.models.seed
        if stage == "seed_refine":
            return (
                self._settings.ai.qa_ai_helper.models.seed_refine
                or self._settings.ai.qa_ai_helper.models.seed
            )
        if stage == "repair":
            return (
                self._settings.ai.qa_ai_helper.models.repair
                or self._settings.ai.qa_ai_helper.models.testcase
            )
        return self._settings.ai.qa_ai_helper.models.testcase

    def resolve_stage_model_id(self, stage: QAAIHelperLLMStage) -> str:
        stage_cfg = self._stage_config(stage)
        return str(stage_cfg.model or "").strip()

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
            headers["X-Title"] = "TCRT QA AI Helper"
        return headers

    @staticmethod
    def _extract_usage(data: Dict[str, Any]) -> Dict[str, int]:
        usage_raw = data.get("usage") or {}
        prompt_tokens = int(usage_raw.get("prompt_tokens") or usage_raw.get("promptTokens") or 0)
        completion_tokens = int(
            usage_raw.get("completion_tokens") or usage_raw.get("completionTokens") or 0
        )
        total_tokens = int(
            usage_raw.get("total_tokens") or usage_raw.get("totalTokens") or (prompt_tokens + completion_tokens)
        )
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }

    @staticmethod
    def _extract_content(data: Dict[str, Any]) -> str:
        choices = data.get("choices") or []
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message") or {}
            content = message.get("content")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts: List[str] = []
                for item in content:
                    if isinstance(item, str):
                        parts.append(item.strip())
                        continue
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        parts.append(item["text"].strip())
                return "\n".join(part for part in parts if part).strip()
        raw_content = data.get("output_text") or data.get("content") or data.get("text") or ""
        return str(raw_content).strip()

    async def call_stage(
        self,
        *,
        stage: QAAIHelperLLMStage,
        prompt: str,
        max_tokens: int = 4000,
    ) -> QAAIHelperLLMResult:
        model_name = self.resolve_stage_model_id(stage)
        if not self._openrouter_key:
            return self._fallback_result(stage=stage, prompt=prompt, model_name=model_name)

        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "temperature": float(self._stage_config(stage).temperature),
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                OPENROUTER_CHAT_COMPLETIONS_URL,
                headers=self._base_headers(),
                json=payload,
                timeout=aiohttp.ClientTimeout(total=90),
            ) as response:
                text_body = await response.text()
                if response.status >= 400:
                    raise RuntimeError(
                        f"qa_ai_helper {stage} 模型呼叫失敗: HTTP {response.status} {text_body}"
                    )
                data = json.loads(text_body)
                return QAAIHelperLLMResult(
                    content=self._extract_content(data),
                    usage=self._extract_usage(data),
                    cost=float(data.get("cost") or data.get("total_cost") or 0.0),
                    cost_note="",
                    model_name=model_name,
                    response_id=data.get("id"),
                )

    def _fallback_result(
        self,
        *,
        stage: QAAIHelperLLMStage,
        prompt: str,
        model_name: str,
    ) -> QAAIHelperLLMResult:
        logger.warning("qa_ai_helper 未設定 OpenRouter key，改用 deterministic fallback: stage=%s", stage)
        try:
            payload = self._fallback_generate_from_prompt(prompt, stage)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"qa_ai_helper fallback 產生失敗: {exc}") from exc
        return QAAIHelperLLMResult(
            content=json.dumps(payload, ensure_ascii=False),
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            cost=0.0,
            cost_note="fallback",
            model_name=f"fallback:{model_name or stage}",
            response_id=None,
        )

    @staticmethod
    def _extract_json_blob(prompt: str, marker: str, default: Any) -> Any:
        raw = str(prompt or "")
        marker_with_eq = f"{marker}="
        start = raw.find(marker_with_eq)
        if start < 0:
            return default
        start += len(marker_with_eq)
        blob = raw[start:].split("\n", 1)[0].strip()
        try:
            return json.loads(blob)
        except Exception:
            return default

    def _fallback_generate_from_prompt(
        self,
        prompt: str,
        stage: QAAIHelperLLMStage,
    ) -> Dict[str, Any]:
        generation_items = self._extract_json_blob(prompt, "GENERATION_ITEMS", [])
        seed_items = self._extract_json_blob(prompt, "SEED_ITEMS", [])
        seed_comments = self._extract_json_blob(prompt, "SEED_COMMENTS", [])
        invalid_outputs = self._extract_json_blob(prompt, "INVALID_OUTPUTS", [])
        items = generation_items if generation_items else invalid_outputs
        if stage in {"seed", "seed_refine"}:
            items = generation_items if generation_items else seed_items
            comments_by_ref = {
                str(item.get("seed_reference_key") or "").strip(): str(item.get("comment_text") or "").strip()
                for item in seed_comments
                if isinstance(item, dict) and str(item.get("seed_reference_key") or "").strip()
            }
            outputs: List[Dict[str, Any]] = []
            for index, item in enumerate(items):
                item_index = int(item.get("item_index", index))
                title = str(
                    item.get("title_hint")
                    or item.get("seed_summary")
                    or item.get("intent")
                    or f"Seed {item_index + 1}"
                ).strip()
                required_assertions = item.get("required_assertions", []) or []
                seed_body = ""
                if required_assertions:
                    first_assertion = required_assertions[0]
                    if isinstance(first_assertion, dict):
                        seed_body = str(first_assertion.get("text") or "").strip()
                if not seed_body:
                    seed_body = str(item.get("seed_body") or title or f"Seed body {item_index + 1}").strip()
                coverage = item.get("coverage") or item.get("coverage_tags") or ["Happy Path"]
                if not isinstance(coverage, list):
                    coverage = [str(coverage)]
                seed_reference_key = str(
                    item.get("seed_reference_key")
                    or item.get("seed_id")
                    or item.get("item_key")
                    or f"seed-{item_index + 1}"
                ).strip()
                comment_text = comments_by_ref.get(seed_reference_key)
                if comment_text:
                    title = f"{title} | {comment_text}".strip()
                    seed_body = f"{seed_body}\n\n註解：{comment_text}".strip()
                outputs.append(
                    {
                        "item_index": item_index,
                        "seed_reference_key": seed_reference_key,
                        "section_id": str(item.get("section_id") or "").strip(),
                        "verification_item_ref": str(
                            item.get("verification_item_ref")
                            or item.get("verification_item_id")
                            or item.get("item_key")
                            or ""
                        ).strip(),
                        "check_condition_ids": item.get("check_condition_ids") or [],
                        "seed_summary": title,
                        "seed_body": seed_body,
                        "coverage_tags": [str(value).strip() for value in coverage if str(value).strip()] or ["Happy Path"],
                    }
                )
            return {"outputs": outputs}
        outputs: List[Dict[str, Any]] = []
        for index, item in enumerate(items):
            item_index = int(item.get("item_index", index))
            title = str(item.get("title_hint") or item.get("intent") or f"Testcase {item_index + 1}").strip()
            preconditions = [str(value).strip() for value in item.get("precondition_hints", []) if str(value).strip()]
            steps = [str(value).strip() for value in item.get("step_hints", []) if str(value).strip()]
            expected_results = [
                str(value).strip() for value in item.get("expected_hints", []) if str(value).strip()
            ]
            required_assertions = item.get("required_assertions", []) or []
            if len(preconditions) < 1:
                preconditions = ["已準備符合需求的測試資料", "使用者具備執行本案例所需權限"]
            if len(steps) < 1:
                steps = ["進入目標頁面或操作入口", "執行需求描述的主要操作", "檢查系統回應與畫面結果"]
            if len(expected_results) < 1:
                if required_assertions:
                    expected_results = [str(required_assertions[0].get("text") or "系統符合需求規則")]
                else:
                    expected_results = ["系統符合該案例預期結果"]
            outputs.append(
                {
                    "item_index": item_index,
                    "seed_reference_key": str(
                        item.get("seed_reference_key")
                        or item.get("seed_id")
                        or item.get("item_key")
                        or f"seed-{item_index + 1}"
                    ).strip(),
                    "title": title,
                    "priority": str(item.get("priority") or "Medium"),
                    "preconditions": preconditions,
                    "steps": steps,
                    "expected_results": expected_results,
                }
            )
        return {"outputs": outputs}


_qa_ai_helper_llm_service: Optional[QAAIHelperLLMService] = None


def get_qa_ai_helper_llm_service() -> QAAIHelperLLMService:
    global _qa_ai_helper_llm_service
    if _qa_ai_helper_llm_service is None:
        _qa_ai_helper_llm_service = QAAIHelperLLMService()
    return _qa_ai_helper_llm_service
