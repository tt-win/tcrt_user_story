#!/usr/bin/env python3
"""QA AI Helper Step 3: AI matrix blueprint (高階模型).

讀取 Step 2 (normalize) 的 JSON 輸出，呼叫高階模型以 AC 為單位拆出
matrix blueprint（assertions / dimensions / constraints），
驗證輸出結構，輸出 JSON 供人工檢查或後續程式使用。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Set

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import requests

from app.config import get_settings

OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL_ALIAS = {
    "google/gemini-3-flash": "google/gemini-3-flash-preview",
    "gemini-3-flash": "google/gemini-3-flash-preview",
}

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _extract_json_object(text: str) -> Dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("模型回傳空內容")
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(raw[start : end + 1])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError as exc:
            raise ValueError(f"模型回傳非合法 JSON: {exc}") from exc
    raise ValueError("模型回傳中找不到 JSON object")


def _normalize_model_name(value: str) -> str:
    normalized = str(value or "").strip()
    return MODEL_ALIAS.get(normalized, normalized)


# ---------------------------------------------------------------------------
# OpenRouter API
# ---------------------------------------------------------------------------


def _base_headers() -> Dict[str, str]:
    settings = get_settings()
    api_key = (settings.openrouter.api_key or "").strip()
    if not api_key:
        raise RuntimeError("OpenRouter API key 未設定")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    base_url = settings.app.get_base_url() if settings.app else ""
    if base_url:
        headers["HTTP-Referer"] = base_url
        headers["X-Title"] = "TCRT QA AI Helper Matrix"
    return headers


def _call_openrouter(*, model: str, prompt: str, max_tokens: int) -> Dict[str, Any]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    response = requests.post(
        OPENROUTER_CHAT_COMPLETIONS_URL,
        headers=_base_headers(),
        json=payload,
        timeout=180,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"OpenRouter 呼叫失敗: HTTP {response.status_code} {response.text}")
    return response.json()


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def _build_matrix_prompt(
    *,
    ticket_key: str,
    canonical_language: str,
    normalized: Dict[str, Any],
) -> str:
    schema = {
        "scenarios": [
            {
                "scenario_key": "ac.scenario_001",
                "title": "",
                "source_refs": ["ac.scenario_001"],
                "assertions": [
                    {
                        "assertion_key": "as-001",
                        "text": "",
                        "source_refs": ["ac.scenario_001", "crt-001"],
                    }
                ],
                "dimensions": [
                    {
                        "dimension_key": "entry_source",
                        "label": "",
                        "selection_mode": "single_select",
                        "options": [
                            {
                                "option_key": "audience_list",
                                "text": "",
                                "source_refs": ["ac.scenario_001"],
                            }
                        ],
                    }
                ],
                "constraints": [
                    {
                        "constraint_type": "mutex_dimension",
                        "dimension_key": "entry_source",
                        "reason": "same axis options are mutually exclusive",
                        "source_refs": ["ac.scenario_001"],
                    }
                ],
                "forbidden_combinations": [
                    {
                        "all": [
                            {"dimension_key": "creation_type", "option_key": "import_based"},
                            {"dimension_key": "field", "option_key": "calculation_time_zone"},
                        ],
                        "reason": "",
                        "source_refs": ["crt-001"],
                    }
                ],
                "applicability_rules": [
                    {
                        "target_dimension_key": "field",
                        "target_option_key": "calculation_time_zone",
                        "applicable_if_all": [
                            {"dimension_key": "creation_type", "option_key": "rule_based"},
                            {"dimension_key": "calculation_mode", "option_key": "automatic"},
                        ],
                        "reason": "",
                        "source_refs": ["crt-001"],
                    }
                ],
                "unresolved_constraints": [],
            }
        ]
    }
    canonical_sections = normalized.get("canonical_sections") or {}
    return (
        "你是 QA AI Helper 的高階 AC matrix planner。\n"
        "你的工作是：根據已正規化的 canonical JSON，以 Acceptance Criteria 為單位拆出 matrix blueprint，供本地程式後續產生 plan。\n"
        "嚴格遵守以下規則：\n"
        "1. 一次只處理已存在的 AC scenario，不可新增 scenario。\n"
        "2. 你的輸出是 matrix blueprint，不是 testcase，也不是最終 plan。\n"
        "3. 只拆出該 AC 真正要驗證的 assertions、dimensions、options、constraints。\n"
        "4. 只有在可證明可同時成立時，才保留可做 cross-product 的 dimensions；明顯互斥或不確定者，請用 constraints / unresolved_constraints 表達，不要自行硬乘。\n"
        "5. 每個 assertion / dimension / option / constraint 都必須帶 source_refs，且 source_refs 只能引用 canonical item keys 或 scenario keys。\n"
        "6. 若 AC 內存在 filter、option、狀態或入口等明示組合維度，請拆出 dimension；若只是補充說明、例子或背景，不要誤當 dimension。\n"
        "7. 只輸出 JSON object，禁止 Markdown、說明文字或 code fence。\n\n"
        f"TICKET_KEY={ticket_key}\n"
        f"CANONICAL_LANGUAGE={canonical_language}\n"
        f"NORMALIZED_CANONICAL_JSON={_json_dumps(canonical_sections)}\n"
        f"OUTPUT_SCHEMA={_json_dumps(schema)}\n"
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@dataclass
class ValidationSummary:
    ok: bool
    errors: List[str]
    warnings: List[str]


def _collect_valid_canonical_refs(normalized: Dict[str, Any]) -> Set[str]:
    canonical_sections = normalized.get("canonical_sections") or {}
    refs: Set[str] = set()
    for item in canonical_sections.get("criteria") or []:
        item_key = str((item or {}).get("item_key") or "").strip()
        if item_key:
            refs.add(item_key)
    for item in canonical_sections.get("technical_specifications") or []:
        item_key = str((item or {}).get("item_key") or "").strip()
        if item_key:
            refs.add(item_key)
    for item in canonical_sections.get("acceptance_criteria") or []:
        scenario_key = str((item or {}).get("scenario_key") or "").strip()
        if scenario_key:
            refs.add(scenario_key)
    return refs


def _validate_matrix_blueprint(
    *,
    normalized: Dict[str, Any],
    matrix_blueprint: Dict[str, Any],
) -> ValidationSummary:
    errors: List[str] = []
    warnings: List[str] = []
    valid_refs = _collect_valid_canonical_refs(normalized)
    known_scenarios = {
        str((item or {}).get("scenario_key") or "").strip()
        for item in ((normalized.get("canonical_sections") or {}).get("acceptance_criteria") or [])
        if str((item or {}).get("scenario_key") or "").strip()
    }

    def _validate_source_refs(path: str, refs: Any) -> None:
        if not isinstance(refs, list) or not refs:
            errors.append(f"{path}.source_refs 必須是非空陣列")
            return
        for ref in refs:
            normalized_ref = str(ref or "").strip()
            if normalized_ref not in valid_refs:
                errors.append(f"{path}.source_refs 包含未知 canonical ref: {normalized_ref}")

    scenarios = matrix_blueprint.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        errors.append("matrix_blueprint.scenarios 必須是非空陣列")
        return ValidationSummary(ok=False, errors=errors, warnings=warnings)

    for index, scenario in enumerate(scenarios):
        if not isinstance(scenario, dict):
            errors.append(f"matrix_blueprint.scenarios[{index}] 必須是 object")
            continue
        scenario_key = str(scenario.get("scenario_key") or "").strip()
        if scenario_key not in known_scenarios:
            errors.append(f"matrix_blueprint.scenarios[{index}].scenario_key 未知: {scenario_key}")
        if not str(scenario.get("title") or "").strip():
            errors.append(f"matrix_blueprint.scenarios[{index}].title 不可為空")
        _validate_source_refs(f"matrix_blueprint.scenarios[{index}]", scenario.get("source_refs"))

        assertions = scenario.get("assertions")
        if not isinstance(assertions, list) or not assertions:
            errors.append(f"matrix_blueprint.scenarios[{index}].assertions 必須是非空陣列")
        else:
            for assert_index, assertion in enumerate(assertions):
                if not isinstance(assertion, dict):
                    errors.append(f"matrix_blueprint.scenarios[{index}].assertions[{assert_index}] 必須是 object")
                    continue
                if not str(assertion.get("assertion_key") or "").strip():
                    errors.append(f"matrix_blueprint.scenarios[{index}].assertions[{assert_index}].assertion_key 不可為空")
                if not str(assertion.get("text") or "").strip():
                    errors.append(f"matrix_blueprint.scenarios[{index}].assertions[{assert_index}].text 不可為空")
                _validate_source_refs(
                    f"matrix_blueprint.scenarios[{index}].assertions[{assert_index}]",
                    assertion.get("source_refs"),
                )

        dimensions = scenario.get("dimensions")
        if not isinstance(dimensions, list):
            errors.append(f"matrix_blueprint.scenarios[{index}].dimensions 必須是陣列")
        else:
            for dim_index, dimension in enumerate(dimensions):
                if not isinstance(dimension, dict):
                    errors.append(f"matrix_blueprint.scenarios[{index}].dimensions[{dim_index}] 必須是 object")
                    continue
                if not str(dimension.get("dimension_key") or "").strip():
                    errors.append(f"matrix_blueprint.scenarios[{index}].dimensions[{dim_index}].dimension_key 不可為空")
                options = dimension.get("options")
                if not isinstance(options, list) or not options:
                    errors.append(f"matrix_blueprint.scenarios[{index}].dimensions[{dim_index}].options 必須是非空陣列")
                    continue
                for option_index, option in enumerate(options):
                    if not isinstance(option, dict):
                        errors.append(f"matrix_blueprint.scenarios[{index}].dimensions[{dim_index}].options[{option_index}] 必須是 object")
                        continue
                    if not str(option.get("option_key") or "").strip():
                        errors.append(
                            f"matrix_blueprint.scenarios[{index}].dimensions[{dim_index}].options[{option_index}].option_key 不可為空"
                        )
                    _validate_source_refs(
                        f"matrix_blueprint.scenarios[{index}].dimensions[{dim_index}].options[{option_index}]",
                        option.get("source_refs"),
                    )

        for field_name in ("constraints", "forbidden_combinations", "applicability_rules", "unresolved_constraints"):
            value = scenario.get(field_name)
            if not isinstance(value, list):
                errors.append(f"matrix_blueprint.scenarios[{index}].{field_name} 必須是陣列")

    return ValidationSummary(ok=not errors, errors=errors, warnings=warnings)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QA AI Helper Step 3: AI matrix blueprint (高階模型)")
    parser.add_argument("--input", required=True, type=Path, help="Step 2 (normalize) 輸出的 JSON 檔路徑")
    parser.add_argument(
        "--model",
        default="google/gemini-3.1-pro-preview",
        help="高階 matrix planner 使用的 OpenRouter model id，預設 google/gemini-3.1-pro-preview",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=10000,
        help="max_tokens，預設 10000",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="輸出 JSON 檔路徑；未指定則根據 input 檔名自動產生",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    model = _normalize_model_name(args.model)

    normalized_payload = json.loads(args.input.read_text(encoding="utf-8"))
    ticket_key = normalized_payload.get("ticket_key", "UNKNOWN")
    canonical_language = normalized_payload.get("canonical_language", "en")

    prompt = _build_matrix_prompt(
        ticket_key=ticket_key,
        canonical_language=canonical_language,
        normalized=normalized_payload,
    )
    response = _call_openrouter(model=model, prompt=prompt, max_tokens=int(args.max_tokens))
    raw_content = str((((response.get("choices") or [{}])[0].get("message") or {}).get("content") or "")).strip()
    matrix_blueprint = _extract_json_object(raw_content)

    validation = _validate_matrix_blueprint(
        normalized=normalized_payload,
        matrix_blueprint=matrix_blueprint,
    )

    usage = response.get("usage") or {}
    matrix_scenarios = matrix_blueprint.get("scenarios") or []

    result = {
        "ticket_key": ticket_key,
        "model": model,
        "scenarios": matrix_scenarios,
        "usage": {
            "prompt_tokens": int(usage.get("prompt_tokens") or usage.get("promptTokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or usage.get("completionTokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or usage.get("totalTokens") or 0),
        },
        "validation": {
            "ok": validation.ok,
            "errors": validation.errors,
            "warnings": validation.warnings,
        },
        "raw_model_content": raw_content,
    }

    output_path = args.output or (
        PROJECT_ROOT / "scripts" / "output" / f"matrix_{ticket_key.lower()}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"ticket_key={ticket_key}")
    print(f"model={model}")
    print(f"output={output_path}")
    print(f"scenarios={len(matrix_scenarios)}")
    print(f"dimensions={sum(len((s or {}).get('dimensions') or []) for s in matrix_scenarios)}")
    print(f"assertions={sum(len((s or {}).get('assertions') or []) for s in matrix_scenarios)}")
    print(f"unresolved_constraints={sum(len((s or {}).get('unresolved_constraints') or []) for s in matrix_scenarios)}")
    print(f"validation_ok={validation.ok}")
    if validation.errors:
        print("validation_errors=" + "; ".join(validation.errors))
    if validation.warnings:
        print("validation_warnings=" + "; ".join(validation.warnings))
    return 0 if validation.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
