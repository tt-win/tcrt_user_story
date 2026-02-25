import asyncio
import logging

import pytest

import app.services.jira_testcase_helper_llm_service as llm_module
from app.services.jira_testcase_helper_llm_service import JiraTestCaseHelperLLMService


class _TimeoutClientSession:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def post(self, *args, **kwargs):
        raise asyncio.TimeoutError()


@pytest.mark.asyncio
async def test_post_json_with_retry_includes_context_for_empty_exception(
    monkeypatch, caplog
):
    service = JiraTestCaseHelperLLMService()
    monkeypatch.setattr(llm_module.aiohttp, "ClientSession", _TimeoutClientSession)

    payload = {
        "model": "openai/gpt-5.2",
        "messages": [{"role": "user", "content": "hello"}],
        "response_format": {"type": "json_object"},
    }

    caplog.set_level(logging.WARNING)
    with pytest.raises(RuntimeError) as exc_info:
        await service._post_json_with_retry(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": "Bearer test"},
            payload=payload,
            timeout_seconds=5,
            retries=2,
        )

    err_text = str(exc_info.value)
    assert "OpenRouter 呼叫失敗（已重試 2 次）" in err_text
    assert "type=TimeoutError" in err_text
    assert "model=openai/gpt-5.2" in err_text
    assert "response_format=True" in err_text
    assert any("type=TimeoutError" in record.getMessage() for record in caplog.records)


def test_extract_error_detail_from_openrouter_error_json():
    raw = (
        '{"error":{"message":"rate limit exceeded","type":"rate_limit_exceeded",'
        '"code":"429","param":"model"}}'
    )
    detail = JiraTestCaseHelperLLMService._extract_error_detail(raw)

    assert detail["detail"] == "rate limit exceeded"
    assert detail["error_type"] == "rate_limit_exceeded"
    assert detail["error_code"] == "429"
    assert detail["error_param"] == "model"
