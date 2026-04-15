#!/usr/bin/env python3
"""PoC: 從 JIRA ticket 讀入格式化需求，使用多模型並行產出檢驗項目後由高階模型統合。

架構：
  Phase 1 — 每個 Scenario × 三個便宜模型 並行產出壓縮格式的驗證條件
  Phase 2 — 一個高階模型統合所有 Scenario 的三模型結果，產出最終檢驗項目

Usage:
    python scripts/ac_inspection_poc.py --ticket-key TCG-XXXX
    python scripts/ac_inspection_poc.py --ticket-key TCG-XXXX --consolidation-model openai/gpt-4o
    python scripts/ac_inspection_poc.py --ticket-key TCG-XXXX --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import textwrap
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

# ---------------------------------------------------------------------------
# Project path setup
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.qa_ai_helper_preclean import build_output, fetch_issue, validate_output_structure

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

EXTRACTION_TEMPERATURE = 0.1

# Phase 2: 高階 consolidation model
DEFAULT_CONSOLIDATION_MODEL = "openai/gpt-5.3-chat"
CONSOLIDATION_TEMPERATURE = 0.1

# Prompt paths
DEFAULT_EXTRACTION_PROMPT = PROJECT_ROOT / "prompts" / "ac_inspection" / "extraction.md"
DEFAULT_CONSOLIDATION_PROMPT = PROJECT_ROOT / "prompts" / "ac_inspection" / "consolidation.md"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "scripts" / "output"
DEFAULT_OUTPUT_LANGUAGE = "繁體中文"


# ---------------------------------------------------------------------------
# Extraction model configs (Phase 1) — 各模型有不同專注角色
# ---------------------------------------------------------------------------
@dataclass
class ExtractionModelConfig:
    """一個 extraction 模型的設定，含角色與專注方向。"""

    model_id: str
    label: str  # A / B / C
    role_name: str  # 短名稱（用於 log 與 header）
    role_focus: str  # 注入 prompt 的專注方向描述


EXTRACTION_MODEL_CONFIGS: List["ExtractionModelConfig"] = [
    ExtractionModelConfig(
        model_id="openai/gpt-5.4-mini",
        label="A",
        role_name="Happy Path + Permission",
        role_focus=(
            "你專注於 **Happy Path（正常流程驗證）** 與 **基本 Permission（權限控制）**。\n"
            "- Happy Path：確認功能在標準輸入與正常操作下的預期行為全部正確。\n"
            "- 基本 Permission：確認不同角色/權限等級對此功能的存取控制是否符合需求。"
        ),
    ),
    ExtractionModelConfig(
        model_id="google/gemini-3-flash-preview",
        label="B",
        role_name="Edge Cases + Performance",
        role_focus=(
            "你專注於 **Edge Cases（邊界與異常輸入）** 與 **Performance/Concurrency（效能與並發）**。\n"
            "- Edge Cases：探索邊界值、空值、超長輸入、特殊字元、格式異常等非典型情境。\n"
            "- Performance：考慮高頻呼叫、大量資料、並發存取下的行為與限制。"
        ),
    ),
    ExtractionModelConfig(
        model_id="x-ai/grok-4.20",
        label="C",
        role_name="Error Handling + 進階 Permission + Abuse",
        role_focus=(
            "你專注於 **Error Handling（錯誤處理）**、**進階 Permission（權限繞過與提權）** 與 **Abuse（濫用防護）**。\n"
            "- Error Handling：確認系統在各種失敗情境（網路錯誤、逾時、依賴服務故障）下的容錯與回饋。\n"
            "- 進階 Permission：嘗試越權操作、權限繞過、未授權存取等攻擊向量。\n"
            "- Abuse：考慮惡意輸入、注入攻擊、重放攻擊、速率限制規避等濫用情境。"
        ),
    ),
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class LLMResult:
    """單次 LLM 呼叫的結果。"""

    model_requested: str
    model_actual: str
    content: str
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    elapsed_sec: float
    error: Optional[str] = None


@dataclass
class ScenarioExtractionResult:
    """一個 Scenario 在所有 extraction models 上的結果。"""

    scenario_index: int
    scenario_name: str
    results: List[LLMResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------
def _load_openrouter_api_key() -> str:
    """從環境變數或 config.yaml 讀取 OpenRouter API key。"""
    key = os.getenv("OPENROUTER_API_KEY", "")
    if key:
        return key

    config_path = PROJECT_ROOT / "config.yaml"
    if config_path.exists():
        try:
            cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            key = (cfg.get("openrouter") or {}).get("api_key", "")
        except Exception:
            pass
    return key or ""


# ---------------------------------------------------------------------------
# Structured output → text helpers
# ---------------------------------------------------------------------------
def _format_user_story(us: Dict[str, str]) -> str:
    """將 User Story dict 格式化為可讀文字。"""
    parts: list[str] = []
    if us.get("As a"):
        parts.append(f"As a {us['As a']},")
    if us.get("I want"):
        parts.append(f"I want {us['I want']},")
    if us.get("So that"):
        parts.append(f"So that {us['So that']}.")
    return "\n".join(parts) if parts else "(未提供 User Story)"


def _format_structured_section(section: Dict[str, Any]) -> str:
    """將 Criteria / Technical Specifications 的結構化 dict 格式化為可讀文字。"""
    if not section:
        return "(無)"
    lines: list[str] = []
    for category_name, category_data in section.items():
        items = category_data.get("items", [])
        if not items:
            continue
        lines.append(f"[{category_name}]")
        for item in items:
            name = item.get("name", "")
            desc = item.get("description", "")
            if desc:
                lines.append(f"- {name}: {desc}")
            else:
                lines.append(f"- {name}")
    return "\n".join(lines).strip() if lines else "(無)"


def _format_acceptance_criteria(scenarios: List[Dict[str, Any]]) -> str:
    """將所有 Acceptance Criteria scenarios 格式化為 Gherkin 可讀文字。"""
    if not scenarios:
        return "(無 Acceptance Criteria)"
    lines: list[str] = []
    for i, sc_wrapper in enumerate(scenarios, 1):
        sc = sc_wrapper.get("Scenario", {})
        name = sc.get("name", f"Scenario {i}")
        lines.append(f"Scenario {i}: {name}")
        for given in sc.get("Given", []):
            lines.append(f"  Given {given}")
        for when in sc.get("When", []):
            lines.append(f"  When {when}")
        for then in sc.get("Then", []):
            lines.append(f"  Then {then}")
    return "\n".join(lines).strip()


def _format_single_scenario_gherkin(sc_wrapper: Dict[str, Any], index: int) -> Tuple[str, str]:
    """將單一 Scenario 格式化為 (name, gherkin_text)。"""
    sc = sc_wrapper.get("Scenario", {})
    name = sc.get("name", f"Scenario {index}")
    lines: list[str] = []
    for given in sc.get("Given", []):
        lines.append(f"Given {given}")
    for when in sc.get("When", []):
        lines.append(f"When {when}")
    for then in sc.get("Then", []):
        lines.append(f"Then {then}")
    return name, "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------
def _render_template(template_path: Path, replacements: Dict[str, str]) -> str:
    """讀取 prompt 模板並替換 placeholder。"""
    if not template_path.exists():
        raise FileNotFoundError(f"Prompt 模板不存在：{template_path}")
    template = template_path.read_text(encoding="utf-8")
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def render_extraction_prompt(
    template_path: Path,
    *,
    user_story: str,
    criteria: str,
    tech_specs: str,
    scenario_name: str,
    scenario_gherkin: str,
    role_focus: str,
    output_language: str,
) -> str:
    """組裝單一 Scenario 的 extraction prompt（含角色專注方向）。"""
    return _render_template(
        template_path,
        {
            "user_story": user_story,
            "criteria": criteria,
            "tech_specs": tech_specs,
            "scenario_name": scenario_name,
            "scenario_gherkin": scenario_gherkin,
            "role_focus": role_focus,
            "output_language": output_language,
        },
    )


def _build_extraction_results_block(
    scenario_results: List[ScenarioExtractionResult],
    model_configs: List[ExtractionModelConfig],
) -> str:
    """將所有 Scenario 的三模型 extraction 結果組裝為 consolidation prompt 的文字區塊。"""
    blocks: list[str] = []
    for sr in scenario_results:
        blocks.append(f"## Scenario {sr.scenario_index}: {sr.scenario_name}")
        blocks.append("")
        for i, result in enumerate(sr.results):
            cfg = model_configs[i] if i < len(model_configs) else None
            label = cfg.label if cfg else str(i)
            role = cfg.role_name if cfg else "Unknown"
            model_name = result.model_actual if not result.error else result.model_requested
            blocks.append(f"### Model {label} ({model_name}) — 專注：{role}")
            if result.error:
                blocks.append(f"(此模型呼叫失敗：{result.error[:100]})")
            else:
                blocks.append(result.content)
            blocks.append("")
    return "\n".join(blocks).strip()


def render_consolidation_prompt(
    template_path: Path,
    *,
    user_story: str,
    acceptance_criteria: str,
    output_language: str,
    extraction_results: str,
) -> str:
    """組裝 consolidation prompt（按 Scenario 分組的三模型結果）。"""
    return _render_template(
        template_path,
        {
            "user_story": user_story,
            "acceptance_criteria": acceptance_criteria,
            "output_language": output_language,
            "extraction_results": extraction_results,
        },
    )


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------
async def call_llm(
    *,
    prompt: str,
    model: str,
    temperature: float,
    api_key: str,
    timeout_sec: int = 180,
) -> LLMResult:
    """呼叫 OpenRouter API，回傳 LLMResult。"""
    import aiohttp

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "TCRT AC Inspection PoC",
    }

    t0 = time.monotonic()
    try:
        timeout = aiohttp.ClientTimeout(total=timeout_sec)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(OPENROUTER_API_URL, json=payload, headers=headers) as resp:
                body = await resp.text()
                elapsed = time.monotonic() - t0
                if resp.status >= 400:
                    return LLMResult(
                        model_requested=model,
                        model_actual=model,
                        content="",
                        finish_reason="error",
                        prompt_tokens=0,
                        completion_tokens=0,
                        total_tokens=0,
                        elapsed_sec=elapsed,
                        error=f"HTTP {resp.status}: {body[:500]}",
                    )
                data = json.loads(body)
    except Exception as exc:
        elapsed = time.monotonic() - t0
        return LLMResult(
            model_requested=model,
            model_actual=model,
            content="",
            finish_reason="error",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            elapsed_sec=elapsed,
            error=str(exc),
        )

    choices = data.get("choices", [])
    usage = data.get("usage", {})
    if not choices:
        return LLMResult(
            model_requested=model,
            model_actual=data.get("model", model),
            content="",
            finish_reason="no_choices",
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            elapsed_sec=elapsed,
            error="LLM 回傳無 choices",
        )

    choice = choices[0]
    return LLMResult(
        model_requested=model,
        model_actual=data.get("model", model),
        content=choice.get("message", {}).get("content", ""),
        finish_reason=choice.get("finish_reason", "unknown"),
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        total_tokens=usage.get("total_tokens", 0),
        elapsed_sec=elapsed,
    )


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------
async def run(args: argparse.Namespace) -> int:
    total_t0 = time.monotonic()

    # ---- 1. 抓取 JIRA ticket ----
    print(f"[1/6] 抓取 JIRA ticket: {args.ticket_key} ...")
    try:
        issue = fetch_issue(args.ticket_key, args.include_comments)
    except Exception as exc:
        print(f"  錯誤：無法抓取 JIRA ticket - {exc}", file=sys.stderr)
        return 1
    print(f"  Summary: {issue['summary']}")
    print(f"  Description 長度: {len(issue['description'])} chars")
    if issue["comments"]:
        print(f"  Comments: {len(issue['comments'])} 則")

    # ---- 2. Preclean 解析 ----
    print("[2/6] Preclean 解析為結構化格式 ...")
    try:
        structured = build_output(issue["description"], issue["comments"])
        validate_output_structure(structured)
    except Exception as exc:
        print(f"  錯誤：Preclean 解析失敗 - {exc}", file=sys.stderr)
        return 1

    us_text = _format_user_story(structured.get("User Story Narrative", {}))
    criteria_text = _format_structured_section(structured.get("Criteria", {}))
    tech_specs_text = _format_structured_section(structured.get("Technical Specifications", {}))
    ac_text = _format_acceptance_criteria(structured.get("Acceptance Criteria", []))

    ac_scenarios = structured.get("Acceptance Criteria", [])
    ac_count = len(ac_scenarios)
    print(f"  User Story: {'有' if structured.get('User Story Narrative', {}).get('As a') else '缺'}")
    print(f"  Criteria 分類數: {len(structured.get('Criteria', {}))}")
    print(f"  Tech Specs 分類數: {len(structured.get('Technical Specifications', {}))}")
    print(f"  Acceptance Criteria Scenarios: {ac_count}")

    if ac_count == 0:
        print("  警告：未找到任何 Acceptance Criteria Scenario，無法產出檢驗項目。", file=sys.stderr)
        return 1

    # ---- 3. 為每個 Scenario 組裝 Extraction Prompt ----
    extraction_prompt_path = Path(args.extraction_prompt)
    if not extraction_prompt_path.is_absolute():
        extraction_prompt_path = PROJECT_ROOT / extraction_prompt_path

    print(
        f"[3/6] 為 {ac_count} 個 Scenario × {len(EXTRACTION_MODEL_CONFIGS)} 個角色模型 組裝 Extraction Prompt（模板: {extraction_prompt_path.name}）..."
    )

    # 解析各 Scenario，為每個 Scenario × 每個 model 組裝各自的 prompt
    # scenario_model_prompts[sc_list_idx][model_idx] = prompt string
    scenario_info: List[Tuple[int, str]] = []  # (index, name)
    scenario_model_prompts: List[List[str]] = []
    for i, sc_wrapper in enumerate(ac_scenarios, 1):
        sc_name, sc_gherkin = _format_single_scenario_gherkin(sc_wrapper, i)
        model_prompts: List[str] = []
        for cfg in EXTRACTION_MODEL_CONFIGS:
            try:
                prompt = render_extraction_prompt(
                    extraction_prompt_path,
                    user_story=us_text,
                    criteria=criteria_text,
                    tech_specs=tech_specs_text,
                    scenario_name=sc_name,
                    scenario_gherkin=sc_gherkin,
                    role_focus=cfg.role_focus,
                    output_language=args.output_language,
                )
            except Exception as exc:
                print(f"  錯誤：Scenario {i} ({sc_name}) × Model {cfg.label} Prompt 組裝失敗 - {exc}", file=sys.stderr)
                return 1
            model_prompts.append(prompt)
        scenario_info.append((i, sc_name))
        scenario_model_prompts.append(model_prompts)
        print(
            f"  Scenario {i}: {sc_name} — {len(model_prompts)} prompts, avg {sum(len(p) for p in model_prompts) // len(model_prompts)} chars"
        )

    total_calls = ac_count * len(EXTRACTION_MODEL_CONFIGS)
    print(f"  共 {ac_count} scenarios × {len(EXTRACTION_MODEL_CONFIGS)} models = {total_calls} 個並行呼叫")
    for cfg in EXTRACTION_MODEL_CONFIGS:
        print(f"    Model {cfg.label} ({cfg.model_id}): {cfg.role_name}")

    # ---- 3.5 Dry run ----
    if args.dry_run:
        consolidation_prompt_path = Path(args.consolidation_prompt)
        if not consolidation_prompt_path.is_absolute():
            consolidation_prompt_path = PROJECT_ROOT / consolidation_prompt_path

        output_dir = DEFAULT_OUTPUT_DIR
        output_dir.mkdir(parents=True, exist_ok=True)

        for sc_list_idx, (sc_idx, sc_name) in enumerate(scenario_info):
            for model_idx, cfg in enumerate(EXTRACTION_MODEL_CONFIGS):
                prompt = scenario_model_prompts[sc_list_idx][model_idx]
                print(
                    f"\n[DRY RUN] Scenario {sc_idx}: {sc_name} × Model {cfg.label} ({cfg.model_id}) — {cfg.role_name}"
                )
                print("=" * 80)
                print(prompt)
                print("=" * 80)

        print(f"\n  Extraction Models:")
        for cfg in EXTRACTION_MODEL_CONFIGS:
            print(f"    {cfg.label}: {cfg.model_id} — {cfg.role_name}")
        print(f"  Consolidation Model: {args.consolidation_model}")
        print(f"  Consolidation Prompt 模板: {consolidation_prompt_path.name}")
        print(f"  並行呼叫數: {total_calls}")

        # 儲存每個 Scenario × Model 的 prompt
        dry_path = output_dir / f"{args.ticket_key}_prompt_dry_run.md"
        dry_parts: list[str] = []
        for sc_list_idx, (sc_idx, sc_name) in enumerate(scenario_info):
            for model_idx, cfg in enumerate(EXTRACTION_MODEL_CONFIGS):
                prompt = scenario_model_prompts[sc_list_idx][model_idx]
                dry_parts.append(
                    f"# Scenario {sc_idx}: {sc_name} — Model {cfg.label} ({cfg.model_id}, {cfg.role_name})\n\n{prompt}"
                )
        dry_path.write_text("\n\n---\n\n".join(dry_parts), encoding="utf-8")
        print(f"\n  Extraction Prompts 已存至: {dry_path}")
        return 0

    # ---- 4. Phase 1：每個 Scenario × 三模型 並行 extraction ----
    api_key = _load_openrouter_api_key()
    if not api_key:
        print(
            "  錯誤：未設定 OpenRouter API key。\n"
            "  請在 config.yaml 的 openrouter.api_key 設定，或設定環境變數 OPENROUTER_API_KEY。",
            file=sys.stderr,
        )
        return 1

    print(f"[4/6] Phase 1：並行呼叫 {total_calls} 個 extraction tasks ...")
    for cfg in EXTRACTION_MODEL_CONFIGS:
        print(f"  Model {cfg.label}: {cfg.model_id} — {cfg.role_name}")
    for sc_idx, sc_name in scenario_info:
        print(f"  Scenario {sc_idx}: {sc_name}")

    # 建立所有 (scenario_list_idx, model_idx, task) 對應
    task_map: List[Tuple[int, int]] = []  # (scenario_list_idx, model_idx)
    tasks = []
    for sc_list_idx, (sc_idx, sc_name) in enumerate(scenario_info):
        for model_idx, cfg in enumerate(EXTRACTION_MODEL_CONFIGS):
            sc_prompt = scenario_model_prompts[sc_list_idx][model_idx]
            task = call_llm(
                prompt=sc_prompt,
                model=cfg.model_id,
                temperature=EXTRACTION_TEMPERATURE,
                api_key=api_key,
            )
            tasks.append(task)
            task_map.append((sc_list_idx, model_idx))

    all_results: List[LLMResult] = await asyncio.gather(*tasks)

    # 整理結果：按 Scenario 分組
    scenario_extraction_results: List[ScenarioExtractionResult] = []
    for sc_list_idx, (sc_idx, sc_name) in enumerate(scenario_info):
        ser = ScenarioExtractionResult(scenario_index=sc_idx, scenario_name=sc_name)
        scenario_extraction_results.append(ser)

    for flat_idx, (sc_list_idx, model_idx) in enumerate(task_map):
        scenario_extraction_results[sc_list_idx].results.append(all_results[flat_idx])

    # 報告 Phase 1 結果
    total_success = 0
    total_fail = 0
    for ser in scenario_extraction_results:
        sc_success = sum(1 for r in ser.results if not r.error)
        sc_fail = len(ser.results) - sc_success
        total_success += sc_success
        total_fail += sc_fail
        print(f"\n  Scenario {ser.scenario_index}: {ser.scenario_name}")
        for i, r in enumerate(ser.results):
            cfg = EXTRACTION_MODEL_CONFIGS[i] if i < len(EXTRACTION_MODEL_CONFIGS) else None
            role_tag = f" [{cfg.role_name}]" if cfg else ""
            status = "OK" if not r.error else f"FAIL: {r.error[:80]}"
            print(
                f"    [{status}] {r.model_requested}{role_tag} "
                f"({r.elapsed_sec:.1f}s, "
                f"{r.completion_tokens} completion tokens, "
                f"finish={r.finish_reason})"
            )

    print(f"\n  Phase 1 總計：{total_success} 成功 / {total_fail} 失敗（共 {total_calls} 呼叫）")

    if total_success == 0:
        print("  錯誤：所有 extraction 呼叫都失敗了！", file=sys.stderr)
        return 1

    # 檢查是否有整個 Scenario 全失敗的情況
    for ser in scenario_extraction_results:
        sc_success = sum(1 for r in ser.results if not r.error)
        if sc_success == 0:
            print(
                f"  警告：Scenario {ser.scenario_index} ({ser.scenario_name}) 的所有模型都失敗了！",
                file=sys.stderr,
            )

    # ---- 5. Phase 2：高階模型統合 ----
    consolidation_prompt_path = Path(args.consolidation_prompt)
    if not consolidation_prompt_path.is_absolute():
        consolidation_prompt_path = PROJECT_ROOT / consolidation_prompt_path

    extraction_results_block = _build_extraction_results_block(scenario_extraction_results, EXTRACTION_MODEL_CONFIGS)

    print(f"[5/6] Phase 2：呼叫高階模型統合（{args.consolidation_model}）...")
    try:
        consolidation_prompt = render_consolidation_prompt(
            consolidation_prompt_path,
            user_story=us_text,
            acceptance_criteria=ac_text,
            output_language=args.output_language,
            extraction_results=extraction_results_block,
        )
    except Exception as exc:
        print(f"  錯誤：Consolidation Prompt 組裝失敗 - {exc}", file=sys.stderr)
        return 1

    print(f"  Consolidation Prompt 長度: {len(consolidation_prompt)} chars")

    consolidation_result = await call_llm(
        prompt=consolidation_prompt,
        model=args.consolidation_model,
        temperature=CONSOLIDATION_TEMPERATURE,
        api_key=api_key,
        timeout_sec=300,
    )

    if consolidation_result.error:
        print(f"  錯誤：Consolidation 呼叫失敗 - {consolidation_result.error}", file=sys.stderr)
        return 1

    print(
        f"  完成！finish={consolidation_result.finish_reason}, "
        f"{consolidation_result.elapsed_sec:.1f}s, "
        f"{consolidation_result.completion_tokens} completion tokens"
    )
    if consolidation_result.finish_reason == "length":
        print("  警告：高階模型回應可能因 token 上限被截斷！", file=sys.stderr)

    # ---- 6. 輸出結果 ----
    print("[6/6] 輸出結果 ...")
    total_elapsed = time.monotonic() - total_t0

    # 組裝 extraction 摘要（per-scenario）
    extraction_summary_lines: list[str] = []
    for ser in scenario_extraction_results:
        extraction_summary_lines.append(f"  **Scenario {ser.scenario_index}: {ser.scenario_name}**")
        for i, r in enumerate(ser.results):
            cfg = EXTRACTION_MODEL_CONFIGS[i] if i < len(EXTRACTION_MODEL_CONFIGS) else None
            role_tag = f" ({cfg.role_name})" if cfg else ""
            status = "OK" if not r.error else "FAIL"
            extraction_summary_lines.append(
                f"  - **{r.model_requested}**{role_tag} → {r.model_actual} "
                f"[{status}, {r.elapsed_sec:.1f}s, "
                f"tokens: {r.prompt_tokens}+{r.completion_tokens}={r.total_tokens}]"
            )
    extraction_summary = "\n".join(extraction_summary_lines)

    # 組裝模型角色說明
    model_roles_lines: list[str] = []
    for cfg in EXTRACTION_MODEL_CONFIGS:
        model_roles_lines.append(f"  - **Model {cfg.label}** ({cfg.model_id}): {cfg.role_name}")
    model_roles = "\n".join(model_roles_lines)

    header = textwrap.dedent(f"""\
        # AC 檢驗項目（多模型統合）— {args.ticket_key}

        - **JIRA Summary**: {issue["summary"]}
        - **Scenarios**: {ac_count}
        - **Consolidation Model**: {consolidation_result.model_actual}
        - **Temperature**: extraction={EXTRACTION_TEMPERATURE}, consolidation={CONSOLIDATION_TEMPERATURE}
        - **並行呼叫數**: {total_calls}（{ac_count} scenarios × {len(EXTRACTION_MODEL_CONFIGS)} models）
        - **產生時間**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        - **總耗時**: {total_elapsed:.1f}s

        ## Extraction Models（角色分工）
        {model_roles}

        ## Extraction 結果摘要（per-Scenario）
        {extraction_summary}

        ## Consolidation
        - Model: {consolidation_result.model_actual}
        - Tokens: prompt={consolidation_result.prompt_tokens}, completion={consolidation_result.completion_tokens}
        - 耗時: {consolidation_result.elapsed_sec:.1f}s

        ---

    """)
    full_output = header + consolidation_result.content

    # 決定輸出路徑
    if args.output:
        output_path = Path(args.output)
    else:
        output_dir = DEFAULT_OUTPUT_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"{args.ticket_key}_inspection_{timestamp}.md"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(full_output, encoding="utf-8")
    print(f"  結果已存至: {output_path}")

    # 儲存各模型原始回應（per-scenario 結構）
    raw_dir = output_path.parent / f"{args.ticket_key}_raw_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    raw_dir.mkdir(parents=True, exist_ok=True)

    for ser in scenario_extraction_results:
        sc_dir = raw_dir / f"scenario_{ser.scenario_index}"
        sc_dir.mkdir(parents=True, exist_ok=True)
        for r in ser.results:
            label = r.model_requested.replace("/", "_")
            raw_path = sc_dir / f"extraction_{label}.txt"
            raw_path.write_text(r.content or f"(error: {r.error})", encoding="utf-8")

    consolidation_raw = raw_dir / "consolidation_prompt.md"
    consolidation_raw.write_text(consolidation_prompt, encoding="utf-8")
    print(f"  原始回應已存至: {raw_dir}/")

    # stdout 輸出
    print("\n" + "=" * 80)
    print(full_output)
    print("=" * 80)

    return 0


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="PoC: 多模型並行 extraction + 高階模型統合 — AC 檢驗項目產生器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            架構:
              Phase 1: 每個 Scenario × 三個角色模型 並行產出壓縮格式的驗證條件
                       Model A (openai/gpt-5.4-mini): Happy Path + 基本 Permission
                       Model B (google/gemini-3-flash-preview): Edge Cases + Performance
                       Model C (x-ai/grok-4.20): Error Handling + 進階 Permission + Abuse
              Phase 2: 高階模型統合所有 Scenario 的三模型結果，產出最終檢驗項目

            範例:
              # 基本用法（使用預設 consolidation model: openai/gpt-5.3-chat）
              python scripts/ac_inspection_poc.py --ticket-key TCG-12345

              # 指定高階統合模型
              python scripts/ac_inspection_poc.py --ticket-key TCG-12345 --consolidation-model openai/gpt-4o

              # Dry run（只看 extraction prompt，不呼叫 LLM）
              python scripts/ac_inspection_poc.py --ticket-key TCG-12345 --dry-run

              # 包含 JIRA comments
              python scripts/ac_inspection_poc.py --ticket-key TCG-12345 --include-comments
        """),
    )
    parser.add_argument(
        "--ticket-key",
        required=True,
        help="JIRA ticket key，例如 TCG-123456",
    )
    parser.add_argument(
        "--include-comments",
        action="store_true",
        help="一併抓取 JIRA ticket 的 comments 作為需求來源",
    )
    parser.add_argument(
        "--consolidation-model",
        default=DEFAULT_CONSOLIDATION_MODEL,
        help=f"Phase 2 統合用的高階模型 ID（預設: {DEFAULT_CONSOLIDATION_MODEL}）",
    )
    parser.add_argument(
        "--extraction-prompt",
        default=str(DEFAULT_EXTRACTION_PROMPT),
        help="Phase 1 extraction prompt 模板路徑",
    )
    parser.add_argument(
        "--consolidation-prompt",
        default=str(DEFAULT_CONSOLIDATION_PROMPT),
        help="Phase 2 consolidation prompt 模板路徑",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="輸出結果檔案路徑（預設: scripts/output/{ticket-key}_inspection_{timestamp}.md）",
    )
    parser.add_argument(
        "--output-language",
        default=DEFAULT_OUTPUT_LANGUAGE,
        help=f"LLM 輸出語言（預設: {DEFAULT_OUTPUT_LANGUAGE}）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只組裝 prompt 並輸出，不實際呼叫 LLM",
    )
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
