"""AI-assisted automation script ↔ manual test case link suggestions.

Suggestion-only surface. Returns ranked candidate manual cases for a given
test function so the user can click "Accept" to create a regular link via
the existing `POST .../links` endpoint.

Privacy guard (see proposal D6): the prompt sent to the LLM contains ONLY a
strict whitelist of fields. Function bodies, fixture contents, and content
from other tests in the same file MUST NOT leave the service boundary.
"""

from __future__ import annotations

import ast
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import ActionType, AuditSeverity, ResourceType, audit_service
from app.config import get_settings
from app.models.database_models import AutomationScript, TestCaseLocal


logger = logging.getLogger(__name__)


_OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
_DEFAULT_MODEL = "google/gemini-3-flash-preview"
_DEFAULT_TIMEOUT_SECONDS = 10
_PROMPT_VERSION = "ai-link-suggest.v1"

# Minimum confidence the service surfaces back to the client (per spec D7).
MIN_CONFIDENCE = 0.60
MAX_LIMIT = 10
DEFAULT_LIMIT = 5
CANDIDATE_PRESELECT_TOP_K = 50
SUMMARY_TRUNCATE_CHARS = 300


_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class AILinkSuggestError(ValueError):
    """Raised on input validation issues (script / test not found)."""


@dataclass
class CandidateCase:
    id: int
    number: str
    title: str
    summary: str


@dataclass
class Suggestion:
    test_case_id: int
    test_case_number: str
    title: str
    confidence: float
    rationale: str


@dataclass
class SuggestResult:
    suggestions: list[Suggestion]
    model: str
    prompt_version: str
    error_summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "suggestions": [
                {
                    "test_case_id": s.test_case_id,
                    "test_case_number": s.test_case_number,
                    "title": s.title,
                    "confidence": s.confidence,
                    "rationale": s.rationale,
                }
                for s in self.suggestions
            ],
            "model": self.model,
            "prompt_version": self.prompt_version,
            "error_summary": self.error_summary,
        }


class AILinkSuggestService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def suggest(
        self,
        *,
        team_id: int,
        script_id: int,
        test_name: str,
        limit: int = DEFAULT_LIMIT,
        actor: str | None = None,
        http_client_factory=None,
    ) -> SuggestResult:
        if not test_name.strip():
            raise AILinkSuggestError("test_name must be a non-empty string")
        limit = max(1, min(int(limit) if limit else DEFAULT_LIMIT, MAX_LIMIT))

        script = await self._load_script(team_id, script_id)
        prompt_input = _build_prompt_input(script, test_name, await self._load_candidate_cases(team_id, script, test_name))

        result = await _call_openrouter_or_fallback(
            prompt_input=prompt_input,
            limit=limit,
            http_client_factory=http_client_factory,
        )

        # Service-level confidence filter (spec D7).
        filtered = [s for s in result.suggestions if s.confidence >= MIN_CONFIDENCE]
        # Preserve descending confidence ordering.
        filtered.sort(key=lambda s: s.confidence, reverse=True)
        result.suggestions = filtered[:limit]

        await self._audit(
            team_id=team_id,
            script=script,
            test_name=test_name,
            result=result,
            actor=actor,
        )
        return result

    async def _load_script(self, team_id: int, script_id: int) -> AutomationScript:
        row = await self.session.execute(
            select(AutomationScript).where(
                AutomationScript.id == script_id,
                AutomationScript.team_id == team_id,
            )
        )
        script = row.scalar_one_or_none()
        if script is None:
            raise AILinkSuggestError(f"Automation script {script_id} not found")
        return script

    async def _load_candidate_cases(
        self, team_id: int, script: AutomationScript, test_name: str
    ) -> list[CandidateCase]:
        rows = await self.session.execute(
            select(
                TestCaseLocal.id,
                TestCaseLocal.test_case_number,
                TestCaseLocal.title,
                TestCaseLocal.steps,
                TestCaseLocal.expected_result,
            ).where(TestCaseLocal.team_id == team_id)
        )
        cases = [
            CandidateCase(
                id=row[0],
                number=row[1],
                title=row[2] or "",
                summary=_join_case_summary(row[3], row[4]),
            )
            for row in rows.all()
        ]
        if not cases:
            return []
        seed_tokens = _tokenize(f"{test_name} {script.ref_path or ''}")
        ranked = sorted(
            cases,
            key=lambda c: _token_overlap_score(seed_tokens, c),
            reverse=True,
        )
        return ranked[:CANDIDATE_PRESELECT_TOP_K]

    async def _audit(
        self,
        *,
        team_id: int,
        script: AutomationScript,
        test_name: str,
        result: SuggestResult,
        actor: str | None,
    ) -> None:
        try:
            await audit_service.log_action(
                user_id=int(actor) if actor and actor.isdigit() else 0,
                username=actor or "ai-link-suggest",
                role="system",
                action_type=ActionType.READ,
                resource_type=ResourceType.AUTOMATION_SCRIPT,
                resource_id=str(script.id),
                team_id=team_id,
                details={
                    "script_id": script.id,
                    "test_name": test_name,
                    "suggestions_count": len(result.suggestions),
                    "model": result.model,
                    "prompt_version": result.prompt_version,
                    "error_summary": result.error_summary,
                },
                action_brief=f"AI link suggestions for script={script.id} test={test_name}",
                severity=AuditSeverity.INFO,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to write AI link suggest audit: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# Pure helpers (testable in isolation)
# ---------------------------------------------------------------------------


def _join_case_summary(steps: str | None, expected_result: str | None) -> str:
    parts = [steps or "", expected_result or ""]
    joined = " ".join(p for p in parts if p).strip()
    return joined[:SUMMARY_TRUNCATE_CHARS]


def _tokenize(text: str) -> set[str]:
    return {tok for tok in _TOKEN_PATTERN.findall(text.lower()) if len(tok) > 1}


def _token_overlap_score(seed_tokens: set[str], case: CandidateCase) -> int:
    if not seed_tokens:
        return 0
    case_tokens = _tokenize(f"{case.number} {case.title} {case.summary}")
    return len(seed_tokens & case_tokens)


def _extract_target_test(content: str | None, test_name: str) -> tuple[str | None, list[str]]:
    """Return (docstring, file_imports) for the target test in a Python file.

    Function bodies are deliberately NOT extracted — only the docstring (a
    self-contained string) and module-level imports (a list of module names).
    """
    if not content:
        return None, []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return None, []

    docstring: str | None = None
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == test_name
        ):
            docstring = ast.get_docstring(node)
            break
        if isinstance(node, ast.ClassDef) and node.name == test_name:
            docstring = ast.get_docstring(node)
            break

    imports: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names if alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return docstring, imports


def _build_prompt_input(
    script: AutomationScript, test_name: str, candidates: list[CandidateCase]
) -> dict[str, Any]:
    """Compose the strict-whitelist payload that will be sent to the LLM.

    SECURITY: Only the fields listed here may leave the service boundary —
    test_name, docstring (string literal), file_imports (module names only),
    ref_path, script_format, and candidate case metadata. Anything else (test
    body, fixture content, neighbouring tests) is explicitly NOT included.
    """
    docstring, file_imports = _extract_target_test(script.cached_content, test_name)
    script_format = (
        script.script_format.value
        if hasattr(script.script_format, "value")
        else str(script.script_format)
    )
    return {
        "test_name": test_name,
        "docstring": docstring,
        "file_imports": file_imports,
        "ref_path": script.ref_path,
        "script_format": script_format,
        "candidate_cases": [
            {
                "id": c.id,
                "number": c.number,
                "title": c.title,
                "summary": c.summary,
            }
            for c in candidates
        ],
    }


async def _call_openrouter_or_fallback(
    *,
    prompt_input: dict[str, Any],
    limit: int,
    http_client_factory,
) -> SuggestResult:
    """Wraps the LLM call. Any failure path lands on a fail-open empty result."""
    api_key = (get_settings().openrouter.api_key or "").strip()
    if not api_key:
        return SuggestResult(
            suggestions=[],
            model=_DEFAULT_MODEL,
            prompt_version=_PROMPT_VERSION,
            error_summary="ai_disabled",
        )
    if not prompt_input["candidate_cases"]:
        return SuggestResult(
            suggestions=[],
            model=_DEFAULT_MODEL,
            prompt_version=_PROMPT_VERSION,
            error_summary="no_candidate_cases",
        )

    system_prompt = (
        "You match an automated test function to manual test cases. Reply "
        "with a JSON object: {\"suggestions\": [{\"test_case_id\": <int>, "
        "\"confidence\": <float 0..1>, \"rationale\": <short string>}]}. "
        "Use only the supplied candidate_cases. Be conservative: omit cases "
        "you are not confident about. Confidence MUST reflect actual match "
        "strength, not optimism."
    )
    user_prompt = json.dumps({"limit": limit, **prompt_input}, ensure_ascii=False)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": _DEFAULT_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 800,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }

    client_cm = (
        http_client_factory()
        if http_client_factory is not None
        else httpx.AsyncClient(timeout=httpx.Timeout(_DEFAULT_TIMEOUT_SECONDS))
    )
    try:
        async with client_cm as client:
            response = await client.post(_OPENROUTER_CHAT_URL, json=body, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except httpx.TimeoutException:
        return SuggestResult([], _DEFAULT_MODEL, _PROMPT_VERSION, "timeout")
    except httpx.HTTPStatusError as exc:
        return SuggestResult([], _DEFAULT_MODEL, _PROMPT_VERSION, f"http_{exc.response.status_code}")
    except (httpx.RequestError, ValueError):
        return SuggestResult([], _DEFAULT_MODEL, _PROMPT_VERSION, "request_failed")
    except Exception:  # noqa: BLE001
        return SuggestResult([], _DEFAULT_MODEL, _PROMPT_VERSION, "unexpected_error")

    return _parse_openrouter_response(payload, prompt_input["candidate_cases"])


def _parse_openrouter_response(
    payload: dict[str, Any], candidate_cases: list[dict[str, Any]]
) -> SuggestResult:
    """Pull suggestions out of an OpenRouter chat-completions payload."""
    choices = payload.get("choices") or []
    if not choices:
        return SuggestResult([], _DEFAULT_MODEL, _PROMPT_VERSION, "no_choices")
    content = (choices[0].get("message") or {}).get("content", "")
    try:
        parsed = json.loads(content)
    except (TypeError, ValueError):
        return SuggestResult([], _DEFAULT_MODEL, _PROMPT_VERSION, "non_json_response")

    raw_suggestions = parsed.get("suggestions") if isinstance(parsed, dict) else None
    if not isinstance(raw_suggestions, list):
        return SuggestResult([], _DEFAULT_MODEL, _PROMPT_VERSION, "missing_suggestions")

    case_by_id = {c["id"]: c for c in candidate_cases}
    cleaned: list[Suggestion] = []
    for item in raw_suggestions:
        if not isinstance(item, dict):
            continue
        try:
            tc_id = int(item.get("test_case_id"))
        except (TypeError, ValueError):
            continue
        case = case_by_id.get(tc_id)
        if case is None:
            # LLM hallucinated a case id outside the supplied candidate list.
            continue
        try:
            confidence = float(item.get("confidence"))
        except (TypeError, ValueError):
            continue
        cleaned.append(
            Suggestion(
                test_case_id=tc_id,
                test_case_number=case["number"],
                title=case["title"],
                confidence=confidence,
                rationale=str(item.get("rationale") or "")[:500],
            )
        )
    return SuggestResult(cleaned, _DEFAULT_MODEL, _PROMPT_VERSION, None)
