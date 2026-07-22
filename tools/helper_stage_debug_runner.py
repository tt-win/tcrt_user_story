#!/usr/bin/env python3
"""AI Helper stage debug runner (local-only, git-ignored).

用途：逐階段執行 JIRA -> Requirement IR -> Analysis -> Coverage -> Testcase -> Audit -> Final Testcase，
並把每個階段的輸入/輸出/LLM 回應保存到本地檔案，供排障回放。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Literal, Optional, Sequence

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import get_settings
from app.services.jira_client import JiraClient
from app.services.jira_testcase_helper_llm_service import (  # noqa: E402
    JiraTestCaseHelperLLMService,
    LLMStageResult,
    get_jira_testcase_helper_llm_service,
)
from app.services.jira_testcase_helper_prompt_service import (  # noqa: E402
    JiraTestCaseHelperPromptService,
    get_jira_testcase_helper_prompt_service,
)
from app.services.jira_testcase_helper_service import (  # noqa: E402
    JiraTestCaseHelperService,
    _parse_tcg_ticket_key,
    _locale_label,
)

StageName = Literal[
    "requirement_ir",
    "analysis",
    "coverage",
    "testcase",
    "audit",
    "final_testcase",
]

STAGE_SEQUENCE: List[StageName] = [
    "requirement_ir",
    "analysis",
    "coverage",
    "testcase",
    "audit",
    "final_testcase",
]
STAGE_INDEX = {name: idx + 1 for idx, name in enumerate(STAGE_SEQUENCE)}
LOCALE_OPTIONS = ["zh-TW", "zh-CN", "en"]



def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()



def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)



def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    return str(value)



def _json_dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=_json_default)



def _adf_to_text(node: Any) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_adf_to_text(item) for item in node)
    if not isinstance(node, dict):
        return str(node)

    node_type = str(node.get("type") or "").strip()
    if node_type == "text":
        return str(node.get("text") or "")
    if node_type == "hardBreak":
        return "\n"

    content = node.get("content")
    rendered = _adf_to_text(content)

    if node_type in {"paragraph", "heading"}:
        return rendered + "\n"
    if node_type in {"tableCell", "tableHeader"}:
        return rendered.strip() + "\t"
    if node_type == "tableRow":
        return rendered.rstrip("\t") + "\n"
    if node_type == "table":
        return rendered + "\n"
    return rendered


@dataclass
class RecordedCall:
    index: int
    stage: str
    model: str
    max_tokens: int
    expect_json: bool
    started_at: str
    ended_at: str
    ok: bool
    prompt: str
    response_content: str
    response_id: Optional[str]
    finish_reason: Optional[str]
    usage: Dict[str, Any]
    cost: float
    cost_note: str
    error: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "stage": self.stage,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "expect_json": self.expect_json,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "ok": self.ok,
            "prompt": self.prompt,
            "response_content": self.response_content,
            "response_id": self.response_id,
            "finish_reason": self.finish_reason,
            "usage": self.usage,
            "cost": self.cost,
            "cost_note": self.cost_note,
            "error": self.error,
        }


class RecordedLLMService:
    """包裝既有 LLM service，保留每次 call_stage 的完整輸入與輸出。"""

    def __init__(self, inner: JiraTestCaseHelperLLMService):
        self.inner = inner
        self.calls: List[RecordedCall] = []

    def reset_calls(self) -> None:
        self.calls = []

    def export_calls(self) -> List[Dict[str, Any]]:
        return [call.to_dict() for call in self.calls]

    async def call_stage(
        self,
        *,
        stage: str,
        prompt: str,
        system_prompt_override: Optional[str] = None,
        max_tokens: int = 4000,
        expect_json: bool = False,
    ) -> LLMStageResult:
        idx = len(self.calls) + 1
        started_at = _now_iso()
        model = ""
        try:
            model = str(getattr(self.inner._stage_config(stage), "model", ""))
        except Exception:
            model = ""
        try:
            result = await self.inner.call_stage(
                stage=stage,
                prompt=prompt,
                system_prompt_override=system_prompt_override,
                max_tokens=max_tokens,
                expect_json=expect_json,
            )
            ended_at = _now_iso()
            self.calls.append(
                RecordedCall(
                    index=idx,
                    stage=stage,
                    model=model,
                    max_tokens=max_tokens,
                    expect_json=expect_json,
                    started_at=started_at,
                    ended_at=ended_at,
                    ok=True,
                    prompt=prompt,
                    response_content=result.content,
                    response_id=result.response_id,
                    finish_reason=result.finish_reason,
                    usage=dict(result.usage or {}),
                    cost=float(result.cost or 0.0),
                    cost_note=str(result.cost_note or ""),
                    error="",
                )
            )
            return result
        except Exception as exc:
            ended_at = _now_iso()
            self.calls.append(
                RecordedCall(
                    index=idx,
                    stage=stage,
                    model=model,
                    max_tokens=max_tokens,
                    expect_json=expect_json,
                    started_at=started_at,
                    ended_at=ended_at,
                    ok=False,
                    prompt=prompt,
                    response_content="",
                    response_id=None,
                    finish_reason=None,
                    usage={},
                    cost=0.0,
                    cost_note="",
                    error=f"{exc}\n{traceback.format_exc()}",
                )
            )
            raise

    async def create_embedding(self, text: str, *, model: str = "baai/bge-m3", api_url: str = "https://openrouter.ai/api/v1/embeddings") -> Sequence[float]:
        return await self.inner.create_embedding(text, model=model, api_url=api_url)


class HelperStageDebugRunner:
    def __init__(
        self,
        *,
        run_id: str,
        base_dir: Path,
        review_locale: str,
        output_locale: str,
        initial_middle: str,
        ticket_key: str,
    ):
        self.run_id = run_id
        self.base_dir = base_dir
        self.run_dir = base_dir / run_id
        self.review_locale = review_locale
        self.output_locale = output_locale
        self.initial_middle = initial_middle
        self.ticket_key = ticket_key

        self.settings = get_settings()
        self.prompt_service: JiraTestCaseHelperPromptService = (
            get_jira_testcase_helper_prompt_service()
        )
        self._inner_llm = get_jira_testcase_helper_llm_service()
        self.llm_service = RecordedLLMService(self._inner_llm)
        self.service = JiraTestCaseHelperService(
            db=None,  # type: ignore[arg-type]
            llm_service=self.llm_service,  # type: ignore[arg-type]
            prompt_service=self.prompt_service,
        )
        self.jira_client = JiraClient()

        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._write_manifest()

    @classmethod
    def from_existing_run(
        cls,
        *,
        run_id: str,
        base_dir: Path,
        ticket_key: Optional[str],
        review_locale: Optional[str],
        output_locale: Optional[str],
        initial_middle: Optional[str],
    ) -> "HelperStageDebugRunner":
        run_dir = base_dir / run_id
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.exists():
            if not ticket_key:
                raise ValueError("找不到 manifest.json，請提供 --ticket-key")
            return cls(
                run_id=run_id,
                base_dir=base_dir,
                review_locale=review_locale or "zh-TW",
                output_locale=output_locale or "zh-TW",
                initial_middle=initial_middle or "010",
                ticket_key=ticket_key,
            )

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return cls(
            run_id=run_id,
            base_dir=base_dir,
            review_locale=review_locale or str(manifest.get("review_locale") or "zh-TW"),
            output_locale=output_locale or str(manifest.get("output_locale") or "zh-TW"),
            initial_middle=initial_middle or str(manifest.get("initial_middle") or "010"),
            ticket_key=ticket_key or str(manifest.get("ticket_key") or ""),
        )

    def _write_manifest(self) -> None:
        manifest = {
            "run_id": self.run_id,
            "created_at": _now_iso(),
            "ticket_key": self.ticket_key,
            "review_locale": self.review_locale,
            "output_locale": self.output_locale,
            "initial_middle": self.initial_middle,
            "run_dir": str(self.run_dir),
            "stage_sequence": STAGE_SEQUENCE,
        }
        path = self.run_dir / "manifest.json"
        _ensure_parent(path)
        path.write_text(_json_dump(manifest), encoding="utf-8")

    def _stage_json_path(self, stage: StageName) -> Path:
        return self.run_dir / f"{STAGE_INDEX[stage]:02d}-{stage}.json"

    def _stage_md_path(self, stage: StageName) -> Path:
        return self.run_dir / f"{STAGE_INDEX[stage]:02d}-{stage}.md"

    def load_stage(self, stage: StageName) -> Dict[str, Any]:
        path = self._stage_json_path(stage)
        if not path.exists():
            raise FileNotFoundError(f"找不到階段檔案: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _save_stage_artifact(self, stage: StageName, artifact: Dict[str, Any]) -> Dict[str, Any]:
        json_path = self._stage_json_path(stage)
        md_path = self._stage_md_path(stage)
        _ensure_parent(json_path)
        json_path.write_text(_json_dump(artifact), encoding="utf-8")
        md_path.write_text(self.render_stage(stage=stage, artifact=artifact), encoding="utf-8")
        return artifact

    def _prepare_stage(self) -> None:
        self.llm_service.reset_calls()

    def _common_error(self, exc: Exception) -> Dict[str, Any]:
        return {
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }

    async def _fetch_ticket_payload(self, ticket_key: str) -> Dict[str, Any]:
        issue = await asyncio.to_thread(
            self.jira_client.get_issue,
            ticket_key,
            ["summary", "description", "components", "status", "issuetype", "priority"],
        )
        if not issue:
            raise ValueError(f"JIRA 找不到 ticket: {ticket_key}")
        fields = issue.get("fields", {}) if isinstance(issue, dict) else {}
        summary = str(fields.get("summary") or "").strip()
        raw_description = fields.get("description")
        description = _adf_to_text(raw_description).strip()
        if not description:
            description = str(raw_description or "").strip()
        components = [
            str(item.get("name") or "").strip()
            for item in (fields.get("components") or [])
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        server_url = (self.settings.jira.server_url or "").rstrip("/")
        ticket_url = f"{server_url}/browse/{ticket_key}" if server_url else None
        return {
            "ticket_key": ticket_key,
            "summary": summary,
            "description": description,
            "components": components,
            "url": ticket_url,
            "raw": issue,
        }

    def _fake_session(self) -> Any:
        return SimpleNamespace(
            review_locale=SimpleNamespace(value=self.review_locale),
            output_locale=SimpleNamespace(value=self.output_locale),
            ticket_key=self.ticket_key,
            initial_middle=self.initial_middle,
        )

    async def run_requirement_ir_stage(self, *, force: bool = False) -> Dict[str, Any]:
        stage: StageName = "requirement_ir"
        existing = self._stage_json_path(stage)
        if existing.exists() and not force:
            return self.load_stage(stage)

        started_at = _now_iso()
        self._prepare_stage()
        inputs: Dict[str, Any] = {"ticket_key": self.ticket_key}
        try:
            ticket_payload = await self._fetch_ticket_payload(self.ticket_key)
            requirement_markdown = str(ticket_payload.get("description") or "").strip()
            if not requirement_markdown:
                raise ValueError("JIRA description 為空，無法產生 Requirement IR")
            ir_result = await self.service.build_requirement_ir(
                session_data=self._fake_session(),
                ticket_payload=ticket_payload,
                requirement_markdown=requirement_markdown,
                similar_cases="",
            )
            outputs = {
                "ticket_payload": ticket_payload,
                "requirement_markdown": requirement_markdown,
                "requirement_ir_result": ir_result,
                "requirement_ir": ir_result.get("requirement_ir") or {},
            }
            artifact = {
                "stage": stage,
                "status": "ok",
                "started_at": started_at,
                "ended_at": _now_iso(),
                "inputs": inputs,
                "llm_calls": self.llm_service.export_calls(),
                "outputs": outputs,
                "error": None,
                "meta": {
                    "review_locale": self.review_locale,
                    "ticket_key": self.ticket_key,
                },
            }
            return self._save_stage_artifact(stage, artifact)
        except Exception as exc:
            artifact = {
                "stage": stage,
                "status": "error",
                "started_at": started_at,
                "ended_at": _now_iso(),
                "inputs": inputs,
                "llm_calls": self.llm_service.export_calls(),
                "outputs": {},
                "error": self._common_error(exc),
                "meta": {
                    "review_locale": self.review_locale,
                    "ticket_key": self.ticket_key,
                },
            }
            self._save_stage_artifact(stage, artifact)
            raise

    async def run_analysis_stage(self, *, force: bool = False) -> Dict[str, Any]:
        stage: StageName = "analysis"
        existing = self._stage_json_path(stage)
        if existing.exists() and not force:
            return self.load_stage(stage)

        req_artifact = self.load_stage("requirement_ir")
        if req_artifact.get("status") != "ok":
            raise ValueError("requirement_ir 階段非成功狀態，無法執行 analysis")

        ticket_payload = req_artifact["outputs"]["ticket_payload"]
        requirement_markdown = req_artifact["outputs"]["requirement_markdown"]
        requirement_ir_payload = req_artifact["outputs"].get("requirement_ir") or {}

        review_language = _locale_label(self.review_locale)
        ticket_summary = str(ticket_payload.get("summary") or "")
        ticket_components = ", ".join(ticket_payload.get("components") or []) or "N/A"
        requirement_ir_json = json.dumps(
            requirement_ir_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        analysis_prompt = self.prompt_service.render_machine_stage_prompt(
            "analysis",
            {
                "review_language": review_language,
                "ticket_key": self.ticket_key,
                "ticket_summary": ticket_summary,
                "ticket_description": requirement_markdown,
                "ticket_components": ticket_components,
                "similar_cases": "",
                "requirement_ir_json": requirement_ir_json,
            },
        )

        started_at = _now_iso()
        self._prepare_stage()
        try:
            analysis_call = await self.service._call_json_stage_with_retry(
                stage="analysis",
                prompt=analysis_prompt,
                review_language=review_language,
                stage_name="Analysis",
                schema_example='{"sec":[{"g":"功能名稱","it":[{"id":"010.001","t":"...","det":["..."],"chk":["..."],"exp":["..."],"rid":["REQ-001"]}]}],"it":[{"id":"010.001","t":"...","det":["..."],"chk":["..."],"exp":["..."],"rid":["REQ-001"]}]}',
                max_tokens=3200,
            )
            analysis_payload_raw = analysis_call.get("payload_raw") or {}
            analysis_payload = self.service._normalize_analysis_payload(analysis_payload_raw)
            if bool(self.settings.ai.jira_testcase_helper.enable_ir_first):
                analysis_payload = self.service._augment_analysis_with_ir(
                    analysis_payload=analysis_payload,
                    requirement_ir=requirement_ir_payload,
                )

            artifact = {
                "stage": stage,
                "status": "ok",
                "started_at": started_at,
                "ended_at": _now_iso(),
                "inputs": {
                    "ticket_key": self.ticket_key,
                    "review_locale": self.review_locale,
                },
                "llm_calls": self.llm_service.export_calls(),
                "outputs": {
                    "analysis_prompt": analysis_prompt,
                    "analysis_call": analysis_call,
                    "analysis": analysis_payload,
                },
                "error": None,
                "meta": {
                    "analysis_item_count": len(analysis_payload.get("it") or []),
                },
            }
            return self._save_stage_artifact(stage, artifact)
        except Exception as exc:
            artifact = {
                "stage": stage,
                "status": "error",
                "started_at": started_at,
                "ended_at": _now_iso(),
                "inputs": {
                    "ticket_key": self.ticket_key,
                    "review_locale": self.review_locale,
                },
                "llm_calls": self.llm_service.export_calls(),
                "outputs": {
                    "analysis_prompt": analysis_prompt,
                },
                "error": self._common_error(exc),
                "meta": {},
            }
            self._save_stage_artifact(stage, artifact)
            raise

    async def run_coverage_stage(self, *, force: bool = False) -> Dict[str, Any]:
        stage: StageName = "coverage"
        existing = self._stage_json_path(stage)
        if existing.exists() and not force:
            return self.load_stage(stage)

        req_artifact = self.load_stage("requirement_ir")
        analysis_artifact = self.load_stage("analysis")
        if req_artifact.get("status") != "ok" or analysis_artifact.get("status") != "ok":
            raise ValueError("requirement_ir/analysis 階段非成功狀態，無法執行 coverage")

        requirement_ir_payload = req_artifact["outputs"].get("requirement_ir") or {}
        analysis_payload = analysis_artifact["outputs"].get("analysis") or {}

        review_language = _locale_label(self.review_locale)
        requirement_ir_json = json.dumps(requirement_ir_payload, ensure_ascii=False, separators=(",", ":"))
        analysis_json = json.dumps(analysis_payload, ensure_ascii=False, separators=(",", ":"))
        coverage_prompt = self.prompt_service.render_machine_stage_prompt(
            "coverage",
            {
                "review_language": review_language,
                "requirement_ir_json": requirement_ir_json,
                "expanded_requirements_json": analysis_json,
            },
        )

        started_at = _now_iso()
        self._prepare_stage()
        try:
            helper_cfg = self.settings.ai.jira_testcase_helper
            coverage_backfill_max_rounds = max(
                0,
                int(getattr(helper_cfg, "coverage_backfill_max_rounds", 1) or 0),
            )
            coverage_backfill_chunk_size = max(
                1,
                int(getattr(helper_cfg, "coverage_backfill_chunk_size", 12) or 12),
            )

            coverage_call = await self.service._call_coverage_with_retry(
                prompt=coverage_prompt,
                review_language=review_language,
                stage_name="Coverage",
                schema_example='{"sec":[{"g":"功能名稱","seed":[{"g":"功能名稱","t":"...","cat":"happy","st":"ok","ref":["010.001"],"rid":["REQ-001"]}]}],"seed":[{"g":"功能名稱","t":"...","cat":"happy","st":"ok","ref":["010.001"],"rid":["REQ-001"]}],"trace":{"analysis_item_count":0,"covered_item_count":0,"missing_ids":[],"missing_sections":[]}}',
                max_tokens=3200,
            )
            coverage_payload = self.service._normalize_coverage_payload(
                coverage_call.get("payload_raw") or {},
                analysis_payload,
            )

            completeness = self.service.validate_coverage_completeness(
                analysis_payload=analysis_payload,
                coverage_payload=coverage_payload,
            )
            backfill_rounds = 0
            backfill_batch_count = 0
            deterministic_backfill_applied = False
            deterministic_backfill_seed_count = 0

            while (
                bool(helper_cfg.enable_ir_first)
                and not completeness.get("is_complete")
                and backfill_rounds < coverage_backfill_max_rounds
            ):
                backfill_rounds += 1
                missing_ids_all = [
                    str(item_id).strip()
                    for item_id in (completeness.get("missing_ids") or [])
                    if str(item_id).strip()
                ]
                missing_sections_all = [
                    str(section).strip()
                    for section in (completeness.get("missing_sections") or [])
                    if str(section).strip()
                ]
                missing_id_chunks: List[List[str]] = []
                if missing_ids_all:
                    for idx in range(0, len(missing_ids_all), coverage_backfill_chunk_size):
                        missing_id_chunks.append(
                            missing_ids_all[idx : idx + coverage_backfill_chunk_size]
                        )
                else:
                    missing_id_chunks.append([])

                for chunk_index, missing_ids_chunk in enumerate(missing_id_chunks, start=1):
                    if completeness.get("is_complete"):
                        break
                    if not missing_ids_chunk and not missing_sections_all:
                        break
                    backfill_batch_count += 1
                    backfill_prompt = self.prompt_service.render_machine_stage_prompt(
                        "coverage_backfill",
                        {
                            "review_language": review_language,
                            "requirement_ir_json": requirement_ir_json,
                            "expanded_requirements_json": analysis_json,
                            "current_coverage_json": json.dumps(
                                coverage_payload, ensure_ascii=False, separators=(",", ":")
                            ),
                            "missing_ids_json": json.dumps(
                                missing_ids_chunk, ensure_ascii=False, separators=(",", ":")
                            ),
                            "missing_sections_json": json.dumps(
                                missing_sections_all if chunk_index == 1 else [],
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        },
                    )
                    backfill_call = await self.service._call_coverage_with_retry(
                        prompt=backfill_prompt,
                        review_language=review_language,
                        stage_name=f"Coverage backfill round {backfill_rounds} batch {chunk_index}/{len(missing_id_chunks)}",
                        schema_example='{"seed":[{"g":"功能名稱","t":"...","cat":"happy","st":"ok","ref":["010.001"],"rid":["REQ-001"]}],"trace":{"resolved_ids":["010.001"],"resolved_sections":["功能名稱"]}}',
                        max_tokens=2200,
                    )
                    backfill_payload = self.service._normalize_coverage_payload(
                        backfill_call.get("payload_raw") or {},
                        analysis_payload,
                    )
                    coverage_payload = self.service._merge_coverage_payload(
                        base_payload=coverage_payload,
                        backfill_payload=backfill_payload,
                        analysis_payload=analysis_payload,
                    )
                    completeness = self.service.validate_coverage_completeness(
                        analysis_payload=analysis_payload,
                        coverage_payload=coverage_payload,
                    )

            if (
                bool(helper_cfg.enable_ir_first)
                and coverage_backfill_max_rounds > 0
                and not completeness.get("is_complete")
            ):
                missing_ids = [
                    str(item_id).strip()
                    for item_id in (completeness.get("missing_ids") or [])
                    if str(item_id).strip()
                ]
                missing_sections = [
                    str(section).strip()
                    for section in (completeness.get("missing_sections") or [])
                    if str(section).strip()
                ]
                deterministic_backfill_payload = self.service._build_deterministic_coverage_backfill(
                    analysis_payload=analysis_payload,
                    requirement_ir=requirement_ir_payload,
                    missing_ids=missing_ids,
                    missing_sections=missing_sections,
                )
                deterministic_backfill_payload = self.service._normalize_coverage_payload(
                    deterministic_backfill_payload,
                    analysis_payload,
                )
                deterministic_seeds = deterministic_backfill_payload.get("seed") or []
                if deterministic_seeds:
                    deterministic_backfill_applied = True
                    deterministic_backfill_seed_count = len(deterministic_seeds)
                    coverage_payload = self.service._merge_coverage_payload(
                        base_payload=coverage_payload,
                        backfill_payload=deterministic_backfill_payload,
                        analysis_payload=analysis_payload,
                    )
                    completeness = self.service.validate_coverage_completeness(
                        analysis_payload=analysis_payload,
                        coverage_payload=coverage_payload,
                    )

            coverage_payload["trace"] = {
                **(
                    coverage_payload.get("trace")
                    if isinstance(coverage_payload.get("trace"), dict)
                    else {}
                ),
                "analysis_item_count": completeness.get("analysis_item_count", 0),
                "covered_item_count": completeness.get("covered_item_count", 0),
                "missing_ids": completeness.get("missing_ids", []),
                "missing_sections": completeness.get("missing_sections", []),
                "backfill_rounds": backfill_rounds,
                "backfill_batch_count": backfill_batch_count,
                "coverage_backfill_chunk_size": coverage_backfill_chunk_size,
                "deterministic_backfill_applied": deterministic_backfill_applied,
                "deterministic_backfill_seed_count": deterministic_backfill_seed_count,
            }

            stage1_payload = self.service._build_stage1_entries(
                analysis_payload=analysis_payload,
                coverage_payload=coverage_payload,
                initial_middle=self.initial_middle,
            )
            stage1_payload["lang"] = self.review_locale

            artifact = {
                "stage": stage,
                "status": "ok",
                "started_at": started_at,
                "ended_at": _now_iso(),
                "inputs": {
                    "ticket_key": self.ticket_key,
                    "review_locale": self.review_locale,
                },
                "llm_calls": self.llm_service.export_calls(),
                "outputs": {
                    "coverage_prompt": coverage_prompt,
                    "coverage_call": coverage_call,
                    "coverage": coverage_payload,
                    "completeness": completeness,
                    "pretestcase": stage1_payload,
                },
                "error": None,
                "meta": {
                    "seed_count": len(coverage_payload.get("seed") or []),
                    "entry_count": len(stage1_payload.get("en") or []),
                },
            }
            return self._save_stage_artifact(stage, artifact)
        except Exception as exc:
            artifact = {
                "stage": stage,
                "status": "error",
                "started_at": started_at,
                "ended_at": _now_iso(),
                "inputs": {
                    "ticket_key": self.ticket_key,
                    "review_locale": self.review_locale,
                },
                "llm_calls": self.llm_service.export_calls(),
                "outputs": {
                    "coverage_prompt": coverage_prompt,
                },
                "error": self._common_error(exc),
                "meta": {},
            }
            self._save_stage_artifact(stage, artifact)
            raise

    async def run_testcase_stage(self, *, force: bool = False) -> Dict[str, Any]:
        stage: StageName = "testcase"
        existing = self._stage_json_path(stage)
        if existing.exists() and not force:
            return self.load_stage(stage)

        req_artifact = self.load_stage("requirement_ir")
        coverage_artifact = self.load_stage("coverage")
        if req_artifact.get("status") != "ok" or coverage_artifact.get("status") != "ok":
            raise ValueError("requirement_ir/coverage 階段非成功狀態，無法執行 testcase")

        ticket_payload = req_artifact["outputs"].get("ticket_payload") or {}
        stage1_payload = coverage_artifact["outputs"].get("pretestcase") or {}
        stage1_payload = self.service._normalize_stage1_payload_for_generation(
            stage1_payload=stage1_payload,
            initial_middle=self.initial_middle,
        )

        entries = stage1_payload.get("en") or []
        if not entries:
            raise ValueError("pretestcase 條目為空，無法產生 testcase")

        ticket_summary = str(ticket_payload.get("summary") or "")
        ticket_description = str(ticket_payload.get("description") or "")
        ticket_components = ", ".join(ticket_payload.get("components") or []) or "N/A"
        output_language = _locale_label(self.output_locale)
        stage1_sections = self.service._group_stage1_sections(stage1_payload)

        started_at = _now_iso()
        self._prepare_stage()
        try:
            generated_testcases_all: List[Dict[str, Any]] = []
            section_outputs: List[Dict[str, Any]] = []

            for section in stage1_sections:
                section_name = str(section.get("g") or "未分類").strip() or "未分類"
                section_no = str(section.get("sn") or "").strip()
                section_entries = [
                    dict(item)
                    for item in (section.get("en") or [])
                    if isinstance(item, dict)
                ]
                if not section_entries:
                    continue
                section_payload = self.service._build_single_section_stage1_payload(
                    stage1_payload=stage1_payload,
                    section=section,
                )
                section_stage1_json = json.dumps(section_payload, ensure_ascii=False, separators=(",", ":"))
                section_context = await self.service._query_generation_similar_cases(
                    ticket_key=self.ticket_key,
                    ticket_summary=ticket_summary,
                    ticket_description=ticket_description,
                    section_name=section_name,
                    section_entries=section_entries,
                )
                testcase_prompt = self.prompt_service.render_machine_stage_prompt(
                    "testcase",
                    {
                        "output_language": output_language,
                        "ticket_key": self.ticket_key,
                        "ticket_summary": ticket_summary,
                        "ticket_description": ticket_description,
                        "ticket_components": ticket_components,
                        "coverage_questions_json": section_stage1_json,
                        "similar_cases": section_context,
                        "section_name": section_name,
                        "section_no": section_no,
                        "retry_hint": "",
                    },
                )
                testcase_call = await self.service._call_json_stage_with_retry(
                    stage="testcase",
                    prompt=testcase_prompt,
                    review_language=output_language,
                    stage_name=f"Testcase ({section_name})",
                    schema_example='{"tc":[{"id":"TCG-123.010.010","t":"...","pre":["..."],"s":["..."],"exp":["..."]}]}',
                    max_tokens=3600,
                )
                testcase_payload = testcase_call.get("payload_raw") or {}
                raw_section_testcases = testcase_payload.get("tc", [])
                if not isinstance(raw_section_testcases, list):
                    raise ValueError(f"Section {section_name} Testcase 回傳 JSON 結構錯誤")
                section_generated = self.service._enforce_testcase_ids(
                    testcases=raw_section_testcases,
                    entries=section_entries,
                    ticket_key=self.ticket_key,
                )

                incomplete_entries = self.service._collect_incomplete_section_entries(
                    section_entries,
                    section_generated,
                )
                if incomplete_entries:
                    supplement_payload = self.service._build_single_section_stage1_payload(
                        stage1_payload=stage1_payload,
                        section={
                            "g": section_name,
                            "sn": section_no,
                            "en": incomplete_entries,
                        },
                    )
                    supplement_prompt = self.prompt_service.render_machine_stage_prompt(
                        "testcase_supplement",
                        {
                            "output_language": output_language,
                            "ticket_key": self.ticket_key,
                            "coverage_questions_json": json.dumps(
                                supplement_payload, ensure_ascii=False, separators=(",", ":")
                            ),
                            "testcase_json": json.dumps(
                                {"tc": section_generated}, ensure_ascii=False, separators=(",", ":")
                            ),
                            "similar_cases": section_context,
                            "section_name": section_name,
                            "section_no": section_no,
                            "retry_hint": "請補齊缺漏 testcase，並輸出完整 JSON。",
                        },
                    )
                    supplement_call = await self.service._call_json_stage_with_retry(
                        stage="testcase",
                        prompt=supplement_prompt,
                        review_language=output_language,
                        stage_name=f"Testcase supplement ({section_name})",
                        schema_example='{"tc":[{"id":"TCG-123.010.020","t":"...","pre":["..."],"s":["..."],"exp":["..."]}]}',
                        max_tokens=2800,
                    )
                    supplement_raw = ((supplement_call.get("payload_raw") or {}).get("tc") or [])
                    supplement_aligned = self.service._enforce_testcase_ids(
                        testcases=supplement_raw if isinstance(supplement_raw, list) else [],
                        entries=incomplete_entries,
                        ticket_key=self.ticket_key,
                    )
                    section_generated = self.service._merge_supplement_cases(
                        base_cases=section_generated,
                        supplement_cases=supplement_aligned,
                    )

                for idx, entry in enumerate(section_entries):
                    if idx >= len(section_generated):
                        section_generated.append(
                            self.service._build_deterministic_testcase_from_entry(
                                ticket_key=self.ticket_key,
                                entry=entry,
                            )
                        )
                        continue
                    if self.service._is_generated_testcase_complete(section_generated[idx]):
                        continue
                    section_generated[idx] = self.service._build_deterministic_testcase_from_entry(
                        ticket_key=self.ticket_key,
                        entry=entry,
                    )

                section_generated = self.service._validate_generated_testcases(
                    testcases=section_generated
                )
                generated_testcases_all.extend(section_generated)
                section_outputs.append(
                    {
                        "g": section_name,
                        "sn": section_no,
                        "context": section_context,
                        "tc": section_generated,
                    }
                )

            artifact = {
                "stage": stage,
                "status": "ok",
                "started_at": started_at,
                "ended_at": _now_iso(),
                "inputs": {
                    "ticket_key": self.ticket_key,
                    "output_locale": self.output_locale,
                },
                "llm_calls": self.llm_service.export_calls(),
                "outputs": {
                    "pretestcase": stage1_payload,
                    "section_outputs": section_outputs,
                    "testcases": generated_testcases_all,
                    "testcase_markdown": self.service._testcase_markdown(generated_testcases_all),
                },
                "error": None,
                "meta": {
                    "section_count": len(section_outputs),
                    "testcase_count": len(generated_testcases_all),
                },
            }
            return self._save_stage_artifact(stage, artifact)
        except Exception as exc:
            artifact = {
                "stage": stage,
                "status": "error",
                "started_at": started_at,
                "ended_at": _now_iso(),
                "inputs": {
                    "ticket_key": self.ticket_key,
                    "output_locale": self.output_locale,
                },
                "llm_calls": self.llm_service.export_calls(),
                "outputs": {},
                "error": self._common_error(exc),
                "meta": {},
            }
            self._save_stage_artifact(stage, artifact)
            raise

    async def run_audit_stage(self, *, force: bool = False) -> Dict[str, Any]:
        stage: StageName = "audit"
        existing = self._stage_json_path(stage)
        if existing.exists() and not force:
            return self.load_stage(stage)

        testcase_artifact = self.load_stage("testcase")
        if testcase_artifact.get("status") != "ok":
            raise ValueError("testcase 階段非成功狀態，無法執行 audit")

        req_artifact = self.load_stage("requirement_ir")
        ticket_payload = req_artifact.get("outputs", {}).get("ticket_payload", {})
        ticket_summary = str(ticket_payload.get("summary") or "")
        ticket_description = str(ticket_payload.get("description") or "")

        stage1_payload = testcase_artifact["outputs"].get("pretestcase") or {}
        stage1_sections = self.service._group_stage1_sections(stage1_payload)
        section_generated_map = {
            f"{str(item.get('sn') or '').strip()}::{str(item.get('g') or '').strip()}": item
            for item in (testcase_artifact["outputs"].get("section_outputs") or [])
            if isinstance(item, dict)
        }

        output_language = _locale_label(self.output_locale)

        started_at = _now_iso()
        self._prepare_stage()
        try:
            audited_testcases_all: List[Dict[str, Any]] = []
            audited_sections: List[Dict[str, Any]] = []

            for section in stage1_sections:
                section_name = str(section.get("g") or "未分類").strip() or "未分類"
                section_no = str(section.get("sn") or "").strip()
                section_entries = [
                    dict(item)
                    for item in (section.get("en") or [])
                    if isinstance(item, dict)
                ]
                if not section_entries:
                    continue
                section_key = f"{section_no}::{section_name}"
                section_generated = (
                    section_generated_map.get(section_key, {}).get("tc")
                    if isinstance(section_generated_map.get(section_key), dict)
                    else []
                )
                section_generated = (
                    section_generated if isinstance(section_generated, list) else []
                )
                section_context = await self.service._query_generation_similar_cases(
                    ticket_key=self.ticket_key,
                    ticket_summary=ticket_summary,
                    ticket_description=ticket_description,
                    section_name=section_name,
                    section_entries=section_entries,
                )
                section_payload = self.service._build_single_section_stage1_payload(
                    stage1_payload=stage1_payload,
                    section=section,
                )
                section_stage1_json = json.dumps(section_payload, ensure_ascii=False, separators=(",", ":"))

                audit_prompt = self.prompt_service.render_machine_stage_prompt(
                    "audit",
                    {
                        "output_language": output_language,
                        "ticket_key": self.ticket_key,
                        "coverage_questions_json": section_stage1_json,
                        "testcase_json": json.dumps(
                            {"tc": section_generated}, ensure_ascii=False, separators=(",", ":")
                        ),
                        "similar_cases": section_context,
                        "section_name": section_name,
                        "section_no": section_no,
                        "retry_hint": "",
                    },
                )
                audit_call = await self.service._call_json_stage_with_retry(
                    stage="audit",
                    prompt=audit_prompt,
                    review_language=output_language,
                    stage_name=f"Audit ({section_name})",
                    schema_example='{"tc":[{"id":"TCG-123.010.010","t":"...","pre":["..."],"s":["..."],"exp":["..."]}]}',
                    max_tokens=3600,
                )
                audit_payload = audit_call.get("payload_raw") or {}
                audited_raw = audit_payload.get("tc", [])
                if not isinstance(audited_raw, list):
                    raise ValueError(f"Section {section_name} Audit 回傳 JSON 結構錯誤")
                section_audited = self.service._enforce_testcase_ids(
                    testcases=audited_raw,
                    entries=section_entries,
                    ticket_key=self.ticket_key,
                )

                for idx, entry in enumerate(section_entries):
                    if idx >= len(section_audited):
                        section_audited.append(
                            self.service._build_deterministic_testcase_from_entry(
                                ticket_key=self.ticket_key,
                                entry=entry,
                            )
                        )
                        continue
                    if self.service._is_generated_testcase_complete(section_audited[idx]):
                        continue
                    section_audited[idx] = self.service._build_deterministic_testcase_from_entry(
                        ticket_key=self.ticket_key,
                        entry=entry,
                    )

                section_audited = self.service._validate_generated_testcases(
                    testcases=section_audited
                )
                audited_testcases_all.extend(section_audited)
                audited_sections.append(
                    {
                        "g": section_name,
                        "sn": section_no,
                        "tc": section_audited,
                        "context": section_context,
                    }
                )

            artifact = {
                "stage": stage,
                "status": "ok",
                "started_at": started_at,
                "ended_at": _now_iso(),
                "inputs": {
                    "ticket_key": self.ticket_key,
                    "output_locale": self.output_locale,
                },
                "llm_calls": self.llm_service.export_calls(),
                "outputs": {
                    "section_outputs": audited_sections,
                    "testcases": audited_testcases_all,
                    "testcase_markdown": self.service._testcase_markdown(audited_testcases_all),
                },
                "error": None,
                "meta": {
                    "section_count": len(audited_sections),
                    "testcase_count": len(audited_testcases_all),
                },
            }
            return self._save_stage_artifact(stage, artifact)
        except Exception as exc:
            artifact = {
                "stage": stage,
                "status": "error",
                "started_at": started_at,
                "ended_at": _now_iso(),
                "inputs": {
                    "ticket_key": self.ticket_key,
                    "output_locale": self.output_locale,
                },
                "llm_calls": self.llm_service.export_calls(),
                "outputs": {},
                "error": self._common_error(exc),
                "meta": {},
            }
            self._save_stage_artifact(stage, artifact)
            raise

    async def run_final_testcase_stage(self, *, force: bool = False) -> Dict[str, Any]:
        stage: StageName = "final_testcase"
        existing = self._stage_json_path(stage)
        if existing.exists() and not force:
            return self.load_stage(stage)

        audit_artifact = self.load_stage("audit")
        if audit_artifact.get("status") != "ok":
            raise ValueError("audit 階段非成功狀態，無法產生 final_testcase")

        started_at = _now_iso()
        self._prepare_stage()
        try:
            audited_cases = audit_artifact.get("outputs", {}).get("testcases") or []
            validated = self.service._validate_generated_testcases(testcases=audited_cases)
            artifact = {
                "stage": stage,
                "status": "ok",
                "started_at": started_at,
                "ended_at": _now_iso(),
                "inputs": {
                    "ticket_key": self.ticket_key,
                    "source_stage": "audit",
                },
                "llm_calls": self.llm_service.export_calls(),
                "outputs": {
                    "testcases": validated,
                    "testcase_markdown": self.service._testcase_markdown(validated),
                },
                "error": None,
                "meta": {
                    "testcase_count": len(validated),
                },
            }
            return self._save_stage_artifact(stage, artifact)
        except Exception as exc:
            artifact = {
                "stage": stage,
                "status": "error",
                "started_at": started_at,
                "ended_at": _now_iso(),
                "inputs": {
                    "ticket_key": self.ticket_key,
                    "source_stage": "audit",
                },
                "llm_calls": self.llm_service.export_calls(),
                "outputs": {},
                "error": self._common_error(exc),
                "meta": {},
            }
            self._save_stage_artifact(stage, artifact)
            raise

    async def run_stage(self, stage: StageName, *, force: bool = False) -> Dict[str, Any]:
        if stage == "requirement_ir":
            return await self.run_requirement_ir_stage(force=force)
        if stage == "analysis":
            return await self.run_analysis_stage(force=force)
        if stage == "coverage":
            return await self.run_coverage_stage(force=force)
        if stage == "testcase":
            return await self.run_testcase_stage(force=force)
        if stage == "audit":
            return await self.run_audit_stage(force=force)
        if stage == "final_testcase":
            return await self.run_final_testcase_stage(force=force)
        raise ValueError(f"未知 stage: {stage}")

    async def run_all(self, *, force: bool = False) -> Dict[str, Dict[str, Any]]:
        outputs: Dict[str, Dict[str, Any]] = {}
        for stage in STAGE_SEQUENCE:
            outputs[stage] = await self.run_stage(stage, force=force)
            if outputs[stage].get("status") != "ok":
                break
        return outputs

    def render_stage(self, *, stage: StageName, artifact: Optional[Dict[str, Any]] = None) -> str:
        payload = artifact or self.load_stage(stage)
        lines: List[str] = []
        lines.append(f"# Stage: {stage}")
        lines.append("")
        lines.append(f"- run_id: {self.run_id}")
        lines.append(f"- status: {payload.get('status')}")
        lines.append(f"- started_at: {payload.get('started_at')}")
        lines.append(f"- ended_at: {payload.get('ended_at')}")
        lines.append("")

        lines.append("## Inputs")
        lines.append("```json")
        lines.append(_json_dump(payload.get("inputs") or {}))
        lines.append("```")
        lines.append("")

        llm_calls = payload.get("llm_calls") or []
        lines.append(f"## LLM Calls ({len(llm_calls)})")
        if not llm_calls:
            lines.append("(none)")
        for call in llm_calls:
            lines.append("")
            lines.append(
                f"### Call #{call.get('index')} stage={call.get('stage')} ok={call.get('ok')} model={call.get('model')}"
            )
            lines.append(f"- finish_reason: {call.get('finish_reason')}")
            lines.append(f"- response_id: {call.get('response_id')}")
            lines.append("#### Prompt")
            lines.append("```text")
            lines.append(str(call.get("prompt") or ""))
            lines.append("```")
            lines.append("#### Response")
            lines.append("```text")
            lines.append(str(call.get("response_content") or ""))
            lines.append("```")
            if call.get("error"):
                lines.append("#### Error")
                lines.append("```text")
                lines.append(str(call.get("error") or ""))
                lines.append("```")

        lines.append("")
        lines.append("## Outputs")
        lines.append("```json")
        lines.append(_json_dump(payload.get("outputs") or {}))
        lines.append("```")
        lines.append("")

        lines.append("## Error")
        lines.append("```json")
        lines.append(_json_dump(payload.get("error")))
        lines.append("```")
        lines.append("")

        lines.append("## Meta")
        lines.append("```json")
        lines.append(_json_dump(payload.get("meta") or {}))
        lines.append("```")
        return "\n".join(lines)


def _stage_choice(value: str) -> StageName:
    normalized = str(value or "").strip().lower()
    if normalized not in STAGE_SEQUENCE:
        raise argparse.ArgumentTypeError(f"不支援 stage: {value}")
    return normalized  # type: ignore[return-value]


def _list_existing_runs(base_dir: Path) -> List[Dict[str, Any]]:
    if not base_dir.exists():
        return []
    runs: List[Dict[str, Any]] = []
    for path in sorted(
        [item for item in base_dir.iterdir() if item.is_dir()],
        key=lambda item: item.name,
        reverse=True,
    ):
        manifest_path = path / "manifest.json"
        manifest: Dict[str, Any] = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                manifest = {}
        stage_status: Dict[str, str] = {}
        for stage in STAGE_SEQUENCE:
            stage_file = path / f"{STAGE_INDEX[stage]:02d}-{stage}.json"
            if not stage_file.exists():
                stage_status[stage] = "missing"
                continue
            try:
                stage_payload = json.loads(stage_file.read_text(encoding="utf-8"))
                stage_status[stage] = str(stage_payload.get("status") or "unknown")
            except Exception:
                stage_status[stage] = "broken"
        runs.append(
            {
                "run_id": path.name,
                "path": str(path),
                "manifest": manifest,
                "stage_status": stage_status,
            }
        )
    return runs


def _prompt_text(prompt: str, *, default: Optional[str] = None) -> str:
    suffix = f" [{default}]" if default not in (None, "") else ""
    value = input(f"{prompt}{suffix}: ").strip()
    if value:
        return value
    return str(default or "")


def _prompt_yes_no(prompt: str, *, default: bool = False) -> bool:
    default_mark = "Y/n" if default else "y/N"
    value = input(f"{prompt} ({default_mark}): ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes", "1", "true"}


def _prompt_menu(title: str, options: List[str], *, allow_back: bool = False) -> Optional[int]:
    print("\n" + title)
    for idx, option in enumerate(options, start=1):
        print(f"  {idx}. {option}")
    if allow_back:
        print("  0. 返回")
    while True:
        raw = input("請輸入選項編號: ").strip()
        if allow_back and raw == "0":
            return None
        if raw.isdigit():
            num = int(raw)
            if 1 <= num <= len(options):
                return num - 1
        print("輸入無效，請重新輸入。")


def _prompt_locale(prompt: str, *, default: str) -> str:
    options = [f"{code} ({_locale_label(code)})" for code in LOCALE_OPTIONS]
    default_index = LOCALE_OPTIONS.index(default) if default in LOCALE_OPTIONS else 0
    print(f"\n{prompt}")
    for idx, option in enumerate(options, start=1):
        default_tag = " (預設)" if idx - 1 == default_index else ""
        print(f"  {idx}. {option}{default_tag}")
    while True:
        raw = input(f"請輸入選項編號 [{default_index + 1}]: ").strip()
        if not raw:
            return LOCALE_OPTIONS[default_index]
        if raw.isdigit():
            num = int(raw)
            if 1 <= num <= len(LOCALE_OPTIONS):
                return LOCALE_OPTIONS[num - 1]
        print("輸入無效，請重新輸入。")


def _prompt_ticket_key(default: Optional[str] = None) -> str:
    while True:
        value = _prompt_text("請輸入 TCG 單號", default=default or "")
        try:
            return _parse_tcg_ticket_key(value)
        except Exception as exc:
            print(f"TCG 單號格式錯誤: {exc}")


def _prompt_initial_middle(default: str = "010") -> str:
    while True:
        value = _prompt_text("請輸入起始 middle（10 遞增，三位數）", default=default).strip()
        if re.fullmatch(r"\d{3}", value) and int(value) % 10 == 0 and 10 <= int(value) <= 990:
            return value
        print("格式錯誤，請輸入 010~990 且 10 遞增（例如 010、020）。")


def _print_run_summary(base_dir: Path) -> None:
    runs = _list_existing_runs(base_dir)
    if not runs:
        print("\n目前沒有任何 run。")
        return
    print("\n既有 Runs:")
    for item in runs:
        run_id = item["run_id"]
        manifest = item.get("manifest") or {}
        ticket_key = str(manifest.get("ticket_key") or "-")
        created_at = str(manifest.get("created_at") or "-")
        status_brief = ", ".join(
            f"{stage}:{item['stage_status'].get(stage, 'missing')}"
            for stage in STAGE_SEQUENCE
        )
        print(f"- {run_id} | ticket={ticket_key} | created_at={created_at}")
        print(f"  {status_brief}")


def _select_run_id(base_dir: Path) -> Optional[str]:
    runs = _list_existing_runs(base_dir)
    if not runs:
        print("目前沒有可選 run，請先執行完整流程。")
        return None
    options = [
        f"{item['run_id']} (ticket={str((item.get('manifest') or {}).get('ticket_key') or '-')})"
        for item in runs
    ]
    selected = _prompt_menu("請選擇 run", options, allow_back=True)
    if selected is None:
        return None
    return runs[selected]["run_id"]


async def _cmd_tui(args: argparse.Namespace) -> int:
    base_dir = Path(args.base_dir).resolve()
    base_dir.mkdir(parents=True, exist_ok=True)

    print("AI Helper Stage Debug Runner - 互動式 TUI")
    print(f"Artifacts 路徑: {base_dir}")

    while True:
        action = _prompt_menu(
            "主選單",
            [
                "執行完整流程（run all stages）",
                "重跑單一階段（stage-run）",
                "檢視階段輸出（show）",
                "列出既有 runs",
                "離開",
            ],
        )
        if action == 0:
            ticket_key = _prompt_ticket_key()
            run_id = _prompt_text(
                "請輸入 run-id（可留空自動產生）",
                default=datetime.now().strftime("%Y%m%d-%H%M%S"),
            )
            review_locale = _prompt_locale("請選擇需求檢視語系", default="zh-TW")
            output_locale = _prompt_locale("請選擇 testcase 輸出語系", default="zh-TW")
            initial_middle = _prompt_initial_middle("010")
            force = _prompt_yes_no("是否強制覆寫已存在的階段檔案", default=False)
            ns = argparse.Namespace(
                base_dir=str(base_dir),
                run_id=run_id,
                ticket_key=ticket_key,
                review_locale=review_locale,
                output_locale=output_locale,
                initial_middle=initial_middle,
                force=force,
            )
            try:
                await _cmd_run(ns)
            except Exception as exc:
                print(f"執行失敗: {exc}")
        elif action == 1:
            run_id = _select_run_id(base_dir)
            if not run_id:
                continue
            stage_idx = _prompt_menu(
                "請選擇要重跑的階段",
                STAGE_SEQUENCE,
                allow_back=True,
            )
            if stage_idx is None:
                continue
            stage = STAGE_SEQUENCE[stage_idx]
            force = _prompt_yes_no("是否強制重跑該階段", default=True)
            ns = argparse.Namespace(
                base_dir=str(base_dir),
                run_id=run_id,
                stage=stage,
                ticket_key=None,
                review_locale=None,
                output_locale=None,
                initial_middle=None,
                force=force,
                from_existing=True,
            )
            try:
                await _cmd_stage_run(ns)
            except Exception as exc:
                print(f"執行失敗: {exc}")
        elif action == 2:
            run_id = _select_run_id(base_dir)
            if not run_id:
                continue
            stage_idx = _prompt_menu(
                "請選擇要檢視的階段",
                STAGE_SEQUENCE,
                allow_back=True,
            )
            if stage_idx is None:
                continue
            stage = STAGE_SEQUENCE[stage_idx]
            format_idx = _prompt_menu(
                "輸出格式",
                ["markdown（完整可讀）", "json（原始 artifact）"],
                allow_back=True,
            )
            if format_idx is None:
                continue
            output_format = "markdown" if format_idx == 0 else "json"
            ns = argparse.Namespace(
                base_dir=str(base_dir),
                run_id=run_id,
                stage=stage,
                format=output_format,
                ticket_key=None,
                review_locale=None,
                output_locale=None,
                initial_middle=None,
                from_existing=True,
            )
            try:
                await _cmd_show(ns)
            except Exception as exc:
                print(f"讀取失敗: {exc}")
        elif action == 3:
            _print_run_summary(base_dir)
        elif action == 4:
            print("已離開。")
            return 0


def _build_runner_from_args(args: argparse.Namespace) -> HelperStageDebugRunner:
    base_dir = Path(args.base_dir).resolve()
    base_dir.mkdir(parents=True, exist_ok=True)

    run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    if getattr(args, "from_existing", False):
        return HelperStageDebugRunner.from_existing_run(
            run_id=run_id,
            base_dir=base_dir,
            ticket_key=getattr(args, "ticket_key", None),
            review_locale=getattr(args, "review_locale", None),
            output_locale=getattr(args, "output_locale", None),
            initial_middle=getattr(args, "initial_middle", None),
        )

    ticket_key = str(getattr(args, "ticket_key", "") or "").strip().upper()
    if not ticket_key:
        raise ValueError("請提供 --ticket-key")
    return HelperStageDebugRunner(
        run_id=run_id,
        base_dir=base_dir,
        review_locale=getattr(args, "review_locale", "zh-TW"),
        output_locale=getattr(args, "output_locale", "zh-TW"),
        initial_middle=getattr(args, "initial_middle", "010"),
        ticket_key=ticket_key,
    )


async def _cmd_run(args: argparse.Namespace) -> int:
    runner = _build_runner_from_args(args)
    outputs = await runner.run_all(force=args.force)
    print(_json_dump({"run_id": runner.run_id, "run_dir": str(runner.run_dir), "stages": {k: v.get("status") for k, v in outputs.items()}}))
    return 0


async def _cmd_stage_run(args: argparse.Namespace) -> int:
    args.from_existing = True
    runner = _build_runner_from_args(args)
    stage: StageName = args.stage
    result = await runner.run_stage(stage, force=args.force)
    print(_json_dump({"run_id": runner.run_id, "run_dir": str(runner.run_dir), "stage": stage, "status": result.get("status")}))
    return 0


async def _cmd_show(args: argparse.Namespace) -> int:
    args.from_existing = True
    runner = _build_runner_from_args(args)
    stage: StageName = args.stage
    if args.format == "json":
        print(_json_dump(runner.load_stage(stage)))
        return 0
    print(runner.render_stage(stage=stage))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Helper stage debug runner")
    parser.add_argument(
        "--base-dir",
        default=".tmp/helper-debug-runs",
        help="artifact base directory (default: .tmp/helper-debug-runs)",
    )

    subparsers = parser.add_subparsers(dest="command", required=False)

    tui_parser = subparsers.add_parser("tui", help="interactive TUI mode")
    tui_parser.set_defaults(command="tui")

    run_parser = subparsers.add_parser("run", help="run all stages")
    run_parser.add_argument("--ticket-key", required=True)
    run_parser.add_argument("--run-id", default=None)
    run_parser.add_argument("--review-locale", default="zh-TW")
    run_parser.add_argument("--output-locale", default="zh-TW")
    run_parser.add_argument("--initial-middle", default="010")
    run_parser.add_argument("--force", action="store_true")

    stage_parser = subparsers.add_parser("stage-run", help="run one stage")
    stage_parser.add_argument("--run-id", required=True)
    stage_parser.add_argument("--stage", required=True, type=_stage_choice)
    stage_parser.add_argument("--ticket-key", default=None)
    stage_parser.add_argument("--review-locale", default=None)
    stage_parser.add_argument("--output-locale", default=None)
    stage_parser.add_argument("--initial-middle", default=None)
    stage_parser.add_argument("--force", action="store_true")

    show_parser = subparsers.add_parser("show", help="show one stage artifact")
    show_parser.add_argument("--run-id", required=True)
    show_parser.add_argument("--stage", required=True, type=_stage_choice)
    show_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    show_parser.add_argument("--ticket-key", default=None)
    show_parser.add_argument("--review-locale", default=None)
    show_parser.add_argument("--output-locale", default=None)
    show_parser.add_argument("--initial-middle", default=None)

    return parser


async def _main_async(argv: Optional[Sequence[str]] = None) -> int:
    argv_list = list(argv) if argv is not None else list(sys.argv[1:])
    if not argv_list:
        return await _cmd_tui(argparse.Namespace(base_dir=".tmp/helper-debug-runs"))

    parser = build_parser()
    args = parser.parse_args(argv_list)
    if args.command in {None, "tui"}:
        return await _cmd_tui(args)
    if args.command == "run":
        return await _cmd_run(args)
    if args.command == "stage-run":
        return await _cmd_stage_run(args)
    if args.command == "show":
        return await _cmd_show(args)
    parser.print_help()
    return 1


def main() -> int:
    try:
        return asyncio.run(_main_async())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
