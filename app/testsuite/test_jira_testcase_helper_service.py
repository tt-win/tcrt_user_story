import asyncio
import json
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.auth.models import UserRole
from app.database import run_sync
from app.models.database_models import (
    Base,
    Team,
    TestCaseLocal,
    TestCaseSection,
    TestCaseSet,
    User,
)
from app.models.test_case_helper import (
    HelperAnalyzeRequest,
    HelperCommitRequest,
    HelperCommitTestCaseItem,
    HelperDraftUpsertRequest,
    HelperGenerateRequest,
    HelperNormalizeRequest,
    HelperPhase,
    HelperPhaseStatus,
    HelperSessionStartRequest,
    HelperSessionUpdateRequest,
    HelperTicketFetchRequest,
)
from app.models.lark_types import Priority
from app.services.jira_testcase_helper_service import JiraTestCaseHelperService


class FakeLLMService:
    def __init__(self, *, slow_analysis: bool = False):
        self.analysis_calls = 0
        self.slow_analysis = slow_analysis

    async def call_stage(self, *, stage, prompt, system_prompt_override=None, max_tokens=4000):
        if stage == "analysis":
            self.analysis_calls += 1
            prompt_text = str(prompt or "")
            if "可編輯 Markdown" in prompt_text:
                return SimpleNamespace(
                    content="# Requirement\n\n- Login flow\n- OTP support",
                    usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                    cost=0.0,
                    cost_note="",
                    response_id="normalize-1",
                )
            if "需求結構化引擎" in prompt_text:
                return SimpleNamespace(
                    content=json.dumps(
                        {
                            "ticket": {
                                "key": "TCG-130078",
                                "summary": "登入流程優化",
                                "components": ["Auth"],
                            },
                            "scenarios": [
                                {
                                    "rid": "REQ-001",
                                    "g": "Auth",
                                    "t": "登入與 OTP 驗證",
                                    "ac": ["登入成功", "OTP 驗證流程"],
                                    "rules": ["OTP 過期應阻擋登入"],
                                }
                            ],
                            "reference_columns": [],
                        },
                        ensure_ascii=False,
                    ),
                    usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                    cost=0.0,
                    cost_note="",
                    response_id="requirement-ir-1",
                )
            if self.slow_analysis:
                await asyncio.sleep(0.4)
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "sec": [
                            {
                                "g": "Auth",
                                "it": [
                                      {
                                          "id": "010.001",
                                          "t": "登入成功",
                                          "det": ["帳號密碼正確"],
                                          "rid": ["REQ-001"],
                                      },
                                      {
                                          "id": "010.002",
                                          "t": "OTP 驗證",
                                          "det": ["OTP 有效且未過期"],
                                          "rid": ["REQ-001"],
                                      },
                                  ],
                              }
                          ]
                    },
                    ensure_ascii=False,
                ),
                usage={"prompt_tokens": 21, "completion_tokens": 34, "total_tokens": 55},
                cost=0.0,
                cost_note="",
                response_id="analysis-2",
            )

        if stage == "coverage":
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "seed": [
                            {
                                "g": "Auth",
                                "t": "登入成功流程",
                                "cat": "happy",
                                "st": "ok",
                                "ref": ["010.001"],
                            },
                            {
                                "g": "Auth",
                                "t": "OTP 過期錯誤",
                                "cat": "negative",
                                "st": "ok",
                                "ref": ["010.002"],
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                usage={"prompt_tokens": 20, "completion_tokens": 28, "total_tokens": 48},
                cost=0.0,
                cost_note="",
                response_id="coverage-1",
            )

        if stage == "testcase":
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "tc": [
                            {
                                "id": "TEMP-1",
                                "t": "登入成功流程",
                                "pre": ["使用者已開啟登入頁"],
                                "s": ["輸入正確帳密", "按下登入"],
                                "exp": ["登入成功"],
                                "priority": "High",
                            },
                            {
                                "id": "TEMP-2",
                                "t": "OTP 過期錯誤",
                                "pre": ["使用者已完成帳密驗證"],
                                "s": ["輸入過期 OTP", "送出"],
                                "exp": ["顯示 OTP 過期"],
                                "priority": "Medium",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                usage={"prompt_tokens": 30, "completion_tokens": 40, "total_tokens": 70},
                cost=0.0,
                cost_note="",
                response_id="testcase-1",
            )

        if stage == "audit":
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "tc": [
                            {
                                "id": "AUDIT-TEMP-1",
                                "t": "登入成功流程（審核）",
                                "pre": ["使用者已開啟登入頁"],
                                "s": ["輸入正確帳密", "按下登入"],
                                "exp": ["登入成功"],
                                "priority": "High",
                            },
                            {
                                "id": "AUDIT-TEMP-2",
                                "t": "OTP 過期錯誤（審核）",
                                "pre": ["使用者已完成帳密驗證"],
                                "s": ["輸入過期 OTP", "送出"],
                                "exp": ["顯示 OTP 過期"],
                                "priority": "Medium",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                usage={"prompt_tokens": 25, "completion_tokens": 35, "total_tokens": 60},
                cost=0.0,
                cost_note="",
                response_id="audit-1",
            )

        raise AssertionError(f"Unexpected stage: {stage}")

    async def create_embedding(self, text, model="", api_url=""):
        return [0.1, 0.2, 0.3]

    @staticmethod
    def strip_json_fences(content):
        return content


class FakeLLMServiceMalformedAnalysisCoverage(FakeLLMService):
    async def call_stage(self, *, stage, prompt, system_prompt_override=None, max_tokens=4000):
        if stage == "analysis":
            if "需求結構化引擎" in str(prompt or ""):
                return SimpleNamespace(
                    content=json.dumps(
                        {
                            "ticket": {"key": "TCG-130078", "summary": "登入流程優化"},
                            "scenarios": [
                                {"rid": "REQ-001", "g": "Auth", "t": "登入成功", "ac": ["帳密正確"]}
                            ],
                            "reference_columns": [],
                        },
                        ensure_ascii=False,
                    ),
                    usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                    cost=0.0,
                    cost_note="",
                    response_id="requirement-ir-malformed-1",
                )
            self.analysis_calls += 1
            return SimpleNamespace(
                content=(
                    "```json\n"
                    "{\n"
                    '  "sec": [\n'
                    "    {\n"
                    '      "g": "Auth",\n'
                    '      "it": [\n'
                    "        {\n"
                    '          "id": "010.001",\n'
                    '          "t": "登入成功\n'
                    '流程",\n'
                    '          "det": ["帳號密碼正確"]\n'
                    "        }\n"
                    "      ]\n"
                    "    }\n"
                    "  ],\n"
                    '  "it": [\n'
                    "    {\n"
                    '      "id": "010.001",\n'
                    '      "t": "登入成功\n'
                    '流程",\n'
                    '      "det": ["帳號密碼正確"]\n'
                    "    }\n"
                    "  ]\n"
                    "}\n"
                    "```"
                ),
                usage={"prompt_tokens": 21, "completion_tokens": 34, "total_tokens": 55},
                cost=0.0,
                cost_note="",
                response_id="analysis-malformed-2",
            )

        if stage == "coverage":
            return SimpleNamespace(
                content=(
                    "coverage 結果如下：\n"
                    "```json\n"
                    "{\n"
                    '  "seed": [\n'
                    "    {\n"
                    '      "g": "Auth",\n'
                    '      "t": "登入成功流程",\n'
                    '      "cat": "happy",\n'
                    '      "st": "ok",\n'
                    '      "ref": ["010.001"],\n'
                    "    }\n"
                    "  ],\n"
                    "}\n"
                    "```"
                ),
                usage={"prompt_tokens": 20, "completion_tokens": 28, "total_tokens": 48},
                cost=0.0,
                cost_note="",
                response_id="coverage-malformed-1",
            )

        return await super().call_stage(
            stage=stage,
            prompt=prompt,
            system_prompt_override=system_prompt_override,
            max_tokens=max_tokens,
        )


class FakeLLMServiceCoverageRepair(FakeLLMService):
    def __init__(self):
        super().__init__()
        self.coverage_calls = 0

    async def call_stage(self, *, stage, prompt, system_prompt_override=None, max_tokens=4000):
        if stage == "coverage":
            self.coverage_calls += 1
            if self.coverage_calls == 1:
                return SimpleNamespace(
                    content=(
                        '{\n'
                        '  "seed": [\n'
                        "    {\n"
                        '      "g": "Auth",\n'
                        '      "t": "登入成功流程,\n'
                        '      "cat": "happy",\n'
                        '      "st": "ok",\n'
                        '      "ref": ["010.001"]\n'
                        "    }\n"
                        "  ]\n"
                        "}\n"
                    ),
                    usage={"prompt_tokens": 22, "completion_tokens": 31, "total_tokens": 53},
                    cost=0.0,
                    cost_note="",
                    response_id="coverage-broken-1",
                )
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "sec": [
                            {
                                "g": "Auth",
                                "seed": [
                                    {
                                        "g": "Auth",
                                        "t": "登入成功流程",
                                        "cat": "happy",
                                        "st": "ok",
                                        "ref": ["010.001"],
                                    }
                                ],
                            }
                        ],
                        "seed": [
                            {
                                "g": "Auth",
                                "t": "登入成功流程",
                                "cat": "happy",
                                "st": "ok",
                                "ref": ["010.001"],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                usage={"prompt_tokens": 16, "completion_tokens": 20, "total_tokens": 36},
                cost=0.0,
                cost_note="",
                response_id="coverage-repair-2",
            )

        return await super().call_stage(
            stage=stage,
            prompt=prompt,
            system_prompt_override=system_prompt_override,
            max_tokens=max_tokens,
        )


class FakeLLMServiceCoverageBackfill(FakeLLMService):
    def __init__(self):
        super().__init__()
        self.coverage_calls = 0
        self.backfill_calls = 0

    async def call_stage(self, *, stage, prompt, system_prompt_override=None, max_tokens=4000):
        prompt_text = str(prompt or "")
        if stage == "analysis":
            if "需求結構化引擎" in prompt_text:
                return SimpleNamespace(
                    content=json.dumps(
                        {
                            "ticket": {"key": "TCG-93178", "summary": "Reference 規則"},
                            "scenarios": [
                                {
                                    "rid": "REQ-001",
                                    "g": "Search",
                                    "t": "Reference 欄位顯示",
                                    "ac": ["固定欄位需維持顯示"],
                                    "rules": ["水平滾動時固定欄位不可消失"],
                                },
                                {
                                    "rid": "REQ-002",
                                    "g": "Search",
                                    "t": "響應式排版",
                                    "ac": ["不同寬度不出現水平捲軸"],
                                    "rules": ["縮窄時允許折疊非固定欄位"],
                                },
                            ],
                            "reference_columns": [],
                        },
                        ensure_ascii=False,
                    ),
                    usage={"prompt_tokens": 12, "completion_tokens": 18, "total_tokens": 30},
                    cost=0.0,
                    cost_note="",
                    response_id="requirement-ir-93178",
                )
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "sec": [
                            {
                                "g": "Reference",
                                "it": [
                                    {
                                        "id": "010.001",
                                        "t": "固定欄位顯示",
                                        "det": ["列數/關聯帳號/關聯項目/關聯度固定"],
                                        "rid": ["REQ-001", "REF-001"],
                                    },
                                    {
                                        "id": "010.002",
                                        "t": "響應式折疊規則",
                                        "det": ["縮窄時保留固定欄位可見"],
                                        "rid": ["REQ-002", "REF-002"],
                                    },
                                ],
                            }
                        ],
                        "it": [
                            {
                                "id": "010.001",
                                "t": "固定欄位顯示",
                                "det": ["列數/關聯帳號/關聯項目/關聯度固定"],
                                "rid": ["REQ-001", "REF-001"],
                            },
                            {
                                "id": "010.002",
                                "t": "響應式折疊規則",
                                "det": ["縮窄時保留固定欄位可見"],
                                "rid": ["REQ-002", "REF-002"],
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                usage={"prompt_tokens": 20, "completion_tokens": 28, "total_tokens": 48},
                cost=0.0,
                cost_note="",
                response_id="analysis-93178",
            )

        if stage == "coverage":
            if "覆蓋補全器" in prompt_text:
                self.backfill_calls += 1
                return SimpleNamespace(
                    content=json.dumps(
                        {
                            "seed": [
                                {
                                    "g": "Reference",
                                    "t": "窄螢幕折疊仍保留固定欄位",
                                    "cat": "boundary",
                                    "st": "ok",
                                    "ref": ["010.002"],
                                    "rid": ["REQ-002", "REF-002"],
                                }
                            ]
                        },
                        ensure_ascii=False,
                    ),
                    usage={"prompt_tokens": 11, "completion_tokens": 16, "total_tokens": 27},
                    cost=0.0,
                    cost_note="",
                    response_id="coverage-backfill-1",
                )

            self.coverage_calls += 1
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "seed": [
                            {
                                "g": "Reference",
                                "t": "固定欄位水平滾動可見",
                                "cat": "happy",
                                "st": "ok",
                                "ref": ["010.001"],
                                "rid": ["REQ-001", "REF-001"],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                usage={"prompt_tokens": 18, "completion_tokens": 24, "total_tokens": 42},
                cost=0.0,
                cost_note="",
                response_id="coverage-93178",
            )

        return await super().call_stage(
            stage=stage,
            prompt=prompt,
            system_prompt_override=system_prompt_override,
            max_tokens=max_tokens,
        )


class FakeLLMServiceCoverageNeedsDeterministicFallback(FakeLLMService):
    def __init__(self):
        super().__init__()
        self.coverage_calls = 0
        self.backfill_calls = 0

    async def call_stage(self, *, stage, prompt, system_prompt_override=None, max_tokens=4000):
        prompt_text = str(prompt or "")
        if stage == "analysis":
            if "需求結構化引擎" in prompt_text:
                return SimpleNamespace(
                    content=json.dumps(
                        {
                            "ticket": {"key": "TCG-93178", "summary": "Reference 規則"},
                            "scenarios": [
                                {"rid": "REQ-001", "g": "Reference", "t": "欄位一", "ac": ["A"]},
                                {"rid": "REQ-002", "g": "Reference", "t": "欄位二", "ac": ["B"]},
                                {"rid": "REQ-003", "g": "Reference", "t": "欄位三", "ac": ["C"]},
                                {"rid": "REQ-004", "g": "Reference", "t": "欄位四", "ac": ["D"]},
                                {"rid": "REQ-005", "g": "Reference", "t": "欄位五", "ac": ["E"]},
                            ],
                            "reference_columns": [
                                {"rid": "REF-001", "column": "欄位一"},
                                {"rid": "REF-002", "column": "欄位二"},
                                {"rid": "REF-003", "column": "欄位三"},
                                {"rid": "REF-004", "column": "欄位四"},
                                {"rid": "REF-005", "column": "欄位五"},
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    usage={"prompt_tokens": 10, "completion_tokens": 16, "total_tokens": 26},
                    cost=0.0,
                    cost_note="",
                    response_id="requirement-ir-deterministic",
                )
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "sec": [
                            {
                                "g": "Reference",
                                "it": [
                                    {
                                        "id": "010.001",
                                        "t": "欄位一檢核",
                                        "det": ["第一欄位"],
                                        "rid": ["REQ-001", "REF-001"],
                                    },
                                    {
                                        "id": "010.002",
                                        "t": "欄位二檢核",
                                        "det": ["第二欄位"],
                                        "rid": ["REQ-002", "REF-002"],
                                    },
                                    {
                                        "id": "010.003",
                                        "t": "欄位三檢核",
                                        "det": ["第三欄位"],
                                        "rid": ["REQ-003", "REF-003"],
                                    },
                                    {
                                        "id": "010.004",
                                        "t": "欄位四檢核",
                                        "det": ["第四欄位"],
                                        "rid": ["REQ-004", "REF-004"],
                                    },
                                    {
                                        "id": "010.005",
                                        "t": "欄位五檢核",
                                        "det": ["第五欄位"],
                                        "rid": ["REQ-005", "REF-005"],
                                    },
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                usage={"prompt_tokens": 20, "completion_tokens": 24, "total_tokens": 44},
                cost=0.0,
                cost_note="",
                response_id="analysis-deterministic",
            )

        if stage == "coverage":
            if "覆蓋補全器" in prompt_text:
                self.backfill_calls += 1
                return SimpleNamespace(
                    content=json.dumps({"seed": []}, ensure_ascii=False),
                    usage={"prompt_tokens": 8, "completion_tokens": 6, "total_tokens": 14},
                    cost=0.0,
                    cost_note="",
                    response_id=f"coverage-backfill-empty-{self.backfill_calls}",
                )
            self.coverage_calls += 1
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "seed": [
                            {
                                "g": "Reference",
                                "t": "欄位一檢核",
                                "cat": "happy",
                                "st": "ok",
                                "ref": ["010.001"],
                                "rid": ["REQ-001", "REF-001"],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                usage={"prompt_tokens": 16, "completion_tokens": 20, "total_tokens": 36},
                cost=0.0,
                cost_note="",
                response_id="coverage-deterministic",
            )

        return await super().call_stage(
            stage=stage,
            prompt=prompt,
            system_prompt_override=system_prompt_override,
            max_tokens=max_tokens,
        )


class FakeLLMServiceCoverageEmptyResponse(FakeLLMService):
    def __init__(self):
        super().__init__()
        self.coverage_calls = 0

    async def call_stage(self, *, stage, prompt, system_prompt_override=None, max_tokens=4000):
        if stage == "coverage":
            self.coverage_calls += 1
            if self.coverage_calls <= 2:
                raise RuntimeError("OpenRouter 回傳內容為空")
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "seed": [
                            {
                                "g": "Auth",
                                "t": "登入成功流程",
                                "cat": "happy",
                                "st": "ok",
                                "ref": ["010.001"],
                                "rid": ["REQ-001"],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                usage={"prompt_tokens": 9, "completion_tokens": 11, "total_tokens": 20},
                cost=0.0,
                cost_note="",
                response_id="coverage-after-empty",
            )
        return await super().call_stage(
            stage=stage,
            prompt=prompt,
            system_prompt_override=system_prompt_override,
            max_tokens=max_tokens,
        )


class FakeLLMServiceCoverageHardFailure(FakeLLMService):
    async def call_stage(self, *, stage, prompt, system_prompt_override=None, max_tokens=4000):
        if stage == "coverage":
            raise RuntimeError("coverage llm unavailable")
        return await super().call_stage(
            stage=stage,
            prompt=prompt,
            system_prompt_override=system_prompt_override,
            max_tokens=max_tokens,
        )


class FakeLLMServiceTestcaseAuditFailure(FakeLLMService):
    async def call_stage(self, *, stage, prompt, system_prompt_override=None, max_tokens=4000):
        if stage in {"testcase", "audit"}:
            raise RuntimeError(f"{stage} llm unavailable")
        return await super().call_stage(
            stage=stage,
            prompt=prompt,
            system_prompt_override=system_prompt_override,
            max_tokens=max_tokens,
        )


def test_requirement_normalization_prompt_preserves_acceptance_criteria_structure():
    service = JiraTestCaseHelperService(db=None, llm_service=FakeLLMService())

    prompt = service._build_requirement_normalization_prompt(
        review_locale="zh-TW",
        ticket_key="TCG-130078",
        summary="登入流程優化",
        description="As a user... Acceptance Criteria: 1) ... 2) ...",
        components=["Auth"],
    )

    assert "保留 User Story、AC、Scenario 的層級結構" in prompt
    assert "欄位定義轉清單" in prompt
    assert "請勿使用 Markdown Table" in prompt


@pytest.fixture
def helper_db(tmp_path):
    db_path = tmp_path / "helper_service_test.db"

    sync_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_pre_ping=True,
    )
    async_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"timeout": 30},
        pool_pre_ping=True,
    )

    SyncSessionLocal = sessionmaker(bind=sync_engine, autocommit=False, autoflush=False)
    AsyncSessionLocal = async_sessionmaker(
        bind=async_engine,
        expire_on_commit=False,
        autoflush=False,
        class_=AsyncSession,
    )

    Base.metadata.create_all(bind=sync_engine)

    yield {
        "sync": SyncSessionLocal,
        "async": AsyncSessionLocal,
        "async_engine": async_engine,
        "sync_engine": sync_engine,
    }

    asyncio.run(async_engine.dispose())
    sync_engine.dispose()


def _seed_basic_data(sync_session_factory):
    with sync_session_factory() as session:
        team = Team(
            name="Helper QA Team",
            description="",
            wiki_token="wiki-helper-team",
            test_case_table_id="tbl-helper-team",
        )
        session.add(team)
        session.commit()

        user = User(
            username="helper-admin",
            email="helper-admin@example.com",
            hashed_password="hashed-password",
            role=UserRole.SUPER_ADMIN,
            is_active=True,
            is_verified=True,
        )
        session.add(user)
        session.commit()

        test_set = TestCaseSet(
            team_id=team.id,
            name=f"Helper-Set-{team.id}",
            description="",
            is_default=True,
        )
        session.add(test_set)
        session.commit()

        return {
            "team_id": team.id,
            "user_id": user.id,
            "set_id": test_set.id,
        }


@pytest.mark.asyncio
async def test_helper_session_lifecycle_and_phase_transitions(helper_db, monkeypatch):
    seeded = _seed_basic_data(helper_db["sync"])

    import app.services.jira_testcase_helper_service as helper_service_module

    fake_llm = FakeLLMService()
    monkeypatch.setattr(
        helper_service_module.JiraClient,
        "get_issue",
        lambda self, key, fields=None: {
            "key": key,
            "fields": {
                "summary": "登入流程優化",
                "description": "新增 OTP 驗證與錯誤提示",
                "components": [{"name": "Auth"}],
            },
        },
    )

    async with helper_db["async"]() as async_db:
        service = JiraTestCaseHelperService(async_db, llm_service=fake_llm)

        async def _empty_similar_cases(_):
            return ""

        service._query_similar_cases = _empty_similar_cases

        started = await service.start_session(
            team_id=seeded["team_id"],
            user_id=seeded["user_id"],
            request=HelperSessionStartRequest(
                test_case_set_id=seeded["set_id"],
                output_locale="zh-TW",
                review_locale="zh-TW",
                initial_middle="010",
            ),
        )
        assert started.current_phase.value == "init"

        ticket = await service.fetch_ticket(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperTicketFetchRequest(ticket_key="TCG-130078"),
        )
        assert ticket.ticket_key == "TCG-130078"

        normalized = await service.normalize_requirement(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperNormalizeRequest(force=False),
        )
        assert normalized.session.current_phase.value == "requirement"
        assert normalized.session.phase_status.value == "waiting_confirm"
        assert "Requirement" in (normalized.markdown or "")

        analyzed = await service.analyze_and_build_pretestcase(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperAnalyzeRequest(
                requirement_markdown=normalized.markdown,
                retry=False,
            ),
        )
        assert analyzed.session.current_phase.value == "pretestcase"
        assert analyzed.session.phase_status.value == "waiting_confirm"
        assert analyzed.payload["pretestcase"]["en"][0]["cid"] == "010.010"
        assert analyzed.payload["pretestcase"]["en"][1]["cid"] == "010.020"
        requirement_ir_draft = next(
            (draft for draft in analyzed.session.drafts if draft.phase == "requirement_ir"),
            None,
        )
        assert requirement_ir_draft is not None
        assert requirement_ir_draft.payload["requirement_ir"]["scenarios"][0]["rid"] == "REQ-001"

        generated = await service.generate_testcases(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperGenerateRequest(
                pretestcase_payload=analyzed.payload["pretestcase"],
                retry=False,
            ),
        )
        assert generated.session.current_phase.value == "testcase"
        assert generated.session.phase_status.value == "waiting_confirm"
        assert len(generated.payload["tc"]) == 2
        assert generated.payload["tc"][0]["id"] == "TCG-130078.010.010"
        assert generated.payload["tc"][1]["id"] == "TCG-130078.010.020"
        assert generated.payload["tc"][0]["section_path"] == "010 Auth"
        assert generated.payload["tc"][1]["section_path"] == "010 Auth"


@pytest.mark.asyncio
async def test_analyze_stage_parses_malformed_llm_json_payload(helper_db, monkeypatch):
    seeded = _seed_basic_data(helper_db["sync"])
    import app.services.jira_testcase_helper_service as helper_service_module

    monkeypatch.setattr(
        helper_service_module.JiraClient,
        "get_issue",
        lambda self, key, fields=None: {
            "key": key,
            "fields": {
                "summary": "登入流程優化",
                "description": "新增 OTP 驗證與錯誤提示",
                "components": [{"name": "Auth"}],
            },
        },
    )

    async with helper_db["async"]() as async_db:
        service = JiraTestCaseHelperService(
            async_db,
            llm_service=FakeLLMServiceMalformedAnalysisCoverage(),
        )

        async def _empty_similar_cases(_):
            return ""

        service._query_similar_cases = _empty_similar_cases

        started = await service.start_session(
            team_id=seeded["team_id"],
            user_id=seeded["user_id"],
            request=HelperSessionStartRequest(
                test_case_set_id=seeded["set_id"],
                output_locale="zh-TW",
                review_locale="zh-TW",
                initial_middle="010",
            ),
        )

        await service.fetch_ticket(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperTicketFetchRequest(ticket_key="TCG-130078"),
        )

        normalized = await service.normalize_requirement(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperNormalizeRequest(force=False),
        )

        analyzed = await service.analyze_and_build_pretestcase(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperAnalyzeRequest(
                requirement_markdown=normalized.markdown,
                retry=False,
            ),
        )

        assert analyzed.session.current_phase.value == "pretestcase"
        assert analyzed.session.phase_status.value == "waiting_confirm"
        assert analyzed.payload["pretestcase"]["en"][0]["cid"] == "010.010"


@pytest.mark.asyncio
async def test_fetch_ticket_allows_transition_back_to_requirement_from_analysis(helper_db, monkeypatch):
    seeded = _seed_basic_data(helper_db["sync"])
    import app.services.jira_testcase_helper_service as helper_service_module

    monkeypatch.setattr(
        helper_service_module.JiraClient,
        "get_issue",
        lambda self, key, fields=None: {
            "key": key,
            "fields": {
                "summary": "登入流程優化",
                "description": "新增 OTP 驗證與錯誤提示",
                "components": [{"name": "Auth"}],
            },
        },
    )

    async with helper_db["async"]() as async_db:
        service = JiraTestCaseHelperService(async_db, llm_service=FakeLLMService())

        started = await service.start_session(
            team_id=seeded["team_id"],
            user_id=seeded["user_id"],
            request=HelperSessionStartRequest(
                test_case_set_id=seeded["set_id"],
                output_locale="zh-TW",
                review_locale="zh-TW",
                initial_middle="010",
            ),
        )

        await service.fetch_ticket(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperTicketFetchRequest(ticket_key="TCG-130078"),
        )

        await service.update_session(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperSessionUpdateRequest(
                current_phase=HelperPhase.ANALYSIS,
                phase_status=HelperPhaseStatus.FAILED,
            ),
        )

        ticket = await service.fetch_ticket(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperTicketFetchRequest(ticket_key="TCG-130078"),
        )
        assert ticket.ticket_key == "TCG-130078"

        updated = await service.get_session(
            team_id=seeded["team_id"],
            session_id=started.id,
        )
        assert updated.current_phase.value == "requirement"
        assert updated.phase_status.value == "idle"


@pytest.mark.asyncio
async def test_analyze_directly_after_ticket_fetch_without_requirement_stage(helper_db, monkeypatch):
    seeded = _seed_basic_data(helper_db["sync"])
    import app.services.jira_testcase_helper_service as helper_service_module

    monkeypatch.setattr(
        helper_service_module.JiraClient,
        "get_issue",
        lambda self, key, fields=None: {
            "key": key,
            "fields": {
                "summary": "登入流程優化",
                "description": "新增 OTP 驗證與錯誤提示",
                "components": [{"name": "Auth"}],
            },
        },
    )

    async with helper_db["async"]() as async_db:
        fake_llm = FakeLLMService()
        fake_llm.analysis_calls = 1
        service = JiraTestCaseHelperService(async_db, llm_service=fake_llm)

        async def _empty_similar_cases(_):
            return ""

        service._query_similar_cases = _empty_similar_cases

        started = await service.start_session(
            team_id=seeded["team_id"],
            user_id=seeded["user_id"],
            request=HelperSessionStartRequest(
                test_case_set_id=seeded["set_id"],
                output_locale="zh-TW",
                review_locale="zh-TW",
                initial_middle="010",
            ),
        )

        await service.fetch_ticket(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperTicketFetchRequest(ticket_key="TCG-130078"),
        )

        analyzed = await service.analyze_and_build_pretestcase(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperAnalyzeRequest(retry=False),
        )

        assert analyzed.session.current_phase.value == "pretestcase"
        assert analyzed.session.phase_status.value == "waiting_confirm"
        requirement_draft = next(
            (draft for draft in analyzed.session.drafts if draft.phase == "requirement"),
            None,
        )
        assert requirement_draft is not None
        assert "新增 OTP 驗證與錯誤提示" in str(requirement_draft.markdown or "")


@pytest.mark.asyncio
async def test_analyze_stage_retries_coverage_regenerate_first_then_repair(helper_db, monkeypatch):
    seeded = _seed_basic_data(helper_db["sync"])
    import app.services.jira_testcase_helper_service as helper_service_module

    monkeypatch.setattr(
        helper_service_module.JiraClient,
        "get_issue",
        lambda self, key, fields=None: {
            "key": key,
            "fields": {
                "summary": "登入流程優化",
                "description": "新增 OTP 驗證與錯誤提示",
                "components": [{"name": "Auth"}],
            },
        },
    )

    async with helper_db["async"]() as async_db:
        service = JiraTestCaseHelperService(
            async_db,
            llm_service=FakeLLMServiceCoverageRepair(),
        )
        service.settings.ai.jira_testcase_helper.enable_ir_first = False

        async def _empty_similar_cases(_):
            return ""

        service._query_similar_cases = _empty_similar_cases

        started = await service.start_session(
            team_id=seeded["team_id"],
            user_id=seeded["user_id"],
            request=HelperSessionStartRequest(
                test_case_set_id=seeded["set_id"],
                output_locale="zh-TW",
                review_locale="zh-TW",
                initial_middle="010",
            ),
        )

        await service.fetch_ticket(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperTicketFetchRequest(ticket_key="TCG-130078"),
        )

        normalized = await service.normalize_requirement(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperNormalizeRequest(force=False),
        )

        analyzed = await service.analyze_and_build_pretestcase(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperAnalyzeRequest(
                requirement_markdown=normalized.markdown,
                retry=False,
            ),
        )

        coverage_draft = next(
            (d for d in analyzed.session.drafts if d.phase == "coverage"),
            None,
        )
        assert coverage_draft is not None
        assert coverage_draft.payload["regenerate_applied"] is True
        assert coverage_draft.payload["repair_applied"] is False
        assert analyzed.session.current_phase.value == "pretestcase"
        assert analyzed.session.phase_status.value == "waiting_confirm"


@pytest.mark.asyncio
async def test_commit_schema_validation_and_section_fallback(helper_db):
    seeded = _seed_basic_data(helper_db["sync"])

    async with helper_db["async"]() as async_db:
        service = JiraTestCaseHelperService(async_db, llm_service=FakeLLMService())

        started = await service.start_session(
            team_id=seeded["team_id"],
            user_id=seeded["user_id"],
            request=HelperSessionStartRequest(
                test_case_set_id=seeded["set_id"],
                output_locale="zh-TW",
                review_locale="zh-TW",
                initial_middle="010",
            ),
        )

        result = await service.commit_testcases(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperCommitRequest(
                testcases=[
                    HelperCommitTestCaseItem(
                        id="TCG-130078.010.010",
                        t="深層 section fallback",
                        pre=["前置"],
                        s=["步驟一"],
                        exp=["結果一"],
                        priority="Medium",
                        section_path="A/B/C/D/E/F",
                    ),
                    HelperCommitTestCaseItem(
                        id="TCG-130078.010.020",
                        t="正常 section 建立",
                        pre=["前置"],
                        s=["步驟一"],
                        exp=["結果一"],
                        priority="High",
                        section_path="Auth/Login",
                    ),
                ]
            ),
        )

        assert result["created_count"] == 2
        assert result["section_fallback_count"] == 1

    with helper_db["sync"]() as session:
        created_numbers = {
            row.test_case_number
            for row in session.query(TestCaseLocal)
            .filter(TestCaseLocal.team_id == seeded["team_id"])
            .all()
        }
        assert "TCG-130078.010.010" in created_numbers
        assert "TCG-130078.010.020" in created_numbers
        numbered_section = (
            session.query(TestCaseSection)
            .filter(TestCaseSection.test_case_set_id == seeded["set_id"], TestCaseSection.name == "010 Auth")
            .first()
        )
        assert numbered_section is not None


@pytest.mark.asyncio
async def test_generate_reindexes_section_middle_number_from_pretestcase_payload(helper_db, monkeypatch):
    seeded = _seed_basic_data(helper_db["sync"])
    import app.services.jira_testcase_helper_service as helper_service_module

    monkeypatch.setattr(
        helper_service_module.JiraClient,
        "get_issue",
        lambda self, key, fields=None: {
            "key": key,
            "fields": {
                "summary": "流程改版",
                "description": "測試 section middle number",
                "components": [{"name": "Core"}],
            },
        },
    )

    async with helper_db["async"]() as async_db:
        service = JiraTestCaseHelperService(async_db, llm_service=FakeLLMService())

        started = await service.start_session(
            team_id=seeded["team_id"],
            user_id=seeded["user_id"],
            request=HelperSessionStartRequest(
                test_case_set_id=seeded["set_id"],
                output_locale="zh-TW",
                review_locale="zh-TW",
                initial_middle="010",
            ),
        )
        await service.fetch_ticket(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperTicketFetchRequest(ticket_key="TCG-130078"),
        )

        generated = await service.generate_testcases(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperGenerateRequest(
                pretestcase_payload={
                    "en": [
                        {"g": "功能 1", "t": "案例一", "cat": "happy", "st": "ok", "cid": "999.999"},
                        {"g": "功能 2", "t": "案例二", "cat": "happy", "st": "ok", "cid": "001.001"},
                    ]
                },
                retry=False,
            ),
        )

        assert generated.payload["tc"][0]["id"] == "TCG-130078.010.010"
        assert generated.payload["tc"][1]["id"] == "TCG-130078.020.010"
        assert generated.payload["tc"][0]["section_path"] == "010 功能 1"
        assert generated.payload["tc"][1]["section_path"] == "020 功能 2"


@pytest.mark.asyncio
async def test_commit_is_transactional_on_duplicate_number(helper_db):
    seeded = _seed_basic_data(helper_db["sync"])

    with helper_db["sync"]() as session:
        existing = TestCaseLocal(
            team_id=seeded["team_id"],
            test_case_set_id=seeded["set_id"],
            test_case_number="TCG-130078.010.010",
            title="Existing",
            priority=Priority.MEDIUM,
            precondition="",
            steps="",
            expected_result="",
        )
        session.add(existing)
        session.commit()

    async with helper_db["async"]() as async_db:
        service = JiraTestCaseHelperService(async_db, llm_service=FakeLLMService())

        started = await service.start_session(
            team_id=seeded["team_id"],
            user_id=seeded["user_id"],
            request=HelperSessionStartRequest(
                test_case_set_id=seeded["set_id"],
                output_locale="zh-TW",
                review_locale="zh-TW",
                initial_middle="010",
            ),
        )

        with pytest.raises(ValueError):
            await service.commit_testcases(
                team_id=seeded["team_id"],
                session_id=started.id,
                request=HelperCommitRequest(
                    testcases=[
                        HelperCommitTestCaseItem(
                            id="TCG-130078.010.010",
                            t="duplicate",
                            pre=["前置"],
                            s=["步驟"],
                            exp=["結果"],
                            priority="Medium",
                            section_path="Auth",
                        ),
                        HelperCommitTestCaseItem(
                            id="TCG-130078.010.020",
                            t="should rollback",
                            pre=["前置"],
                            s=["步驟"],
                            exp=["結果"],
                            priority="Medium",
                            section_path="Auth",
                        ),
                    ]
                ),
            )

    with helper_db["sync"]() as session:
        count = session.query(TestCaseLocal).filter(TestCaseLocal.team_id == seeded["team_id"]).count()
        assert count == 1


@pytest.mark.asyncio
async def test_stage1_id_allocator_uses_ten_step_increment(helper_db):
    seeded = _seed_basic_data(helper_db["sync"])

    async with helper_db["async"]() as async_db:
        service = JiraTestCaseHelperService(async_db, llm_service=FakeLLMService())

        stage1 = service._build_stage1_entries(
            analysis_payload={
                "it": [
                    {"id": "010.001", "t": "A", "det": ["a"]},
                    {"id": "020.001", "t": "B", "det": ["b"]},
                ]
            },
            coverage_payload={
                "seed": [
                    {"g": "Auth", "t": "A1", "cat": "happy", "st": "ok", "ref": ["010.001"], "idx": 1},
                    {"g": "Auth", "t": "A2", "cat": "negative", "st": "ok", "ref": ["010.001"], "idx": 2},
                    {"g": "Profile", "t": "B1", "cat": "happy", "st": "ok", "ref": ["020.001"], "idx": 3},
                ]
            },
            initial_middle="010",
        )

        assert stage1["sec"][0]["sn"] == "010"
        assert stage1["sec"][1]["sn"] == "020"
        assert stage1["sec"][0]["en"][0]["tn"] == "010"
        assert stage1["sec"][0]["en"][1]["tn"] == "020"
        assert stage1["sec"][1]["en"][0]["tn"] == "010"


def test_normalize_coverage_payload_splits_multi_ref_seed_into_single_item_refs():
    service = JiraTestCaseHelperService(db=None, llm_service=FakeLLMService())
    analysis_payload = {
        "sec": [
            {
                "g": "Reference",
                "it": [
                    {"id": "010.001", "t": "欄位一", "det": [], "rid": ["REQ-001", "REF-001"]},
                    {"id": "010.002", "t": "欄位二", "det": [], "rid": ["REQ-002", "REF-002"]},
                ],
            }
        ],
        "it": [
            {"id": "010.001", "t": "欄位一", "det": [], "rid": ["REQ-001", "REF-001"]},
            {"id": "010.002", "t": "欄位二", "det": [], "rid": ["REQ-002", "REF-002"]},
        ],
    }
    coverage_payload = {
        "seed": [
            {
                "g": "Reference",
                "t": "欄位一與欄位二檢核",
                "cat": "happy",
                "st": "ok",
                "ref": ["010.001", "010.002"],
                "rid": ["REF-001~REF-002"],
            },
            {
                "g": "Reference",
                "t": "欄位一與欄位二檢核",
                "cat": "happy",
                "st": "ok",
                "ref": ["010.001~010.002"],
                "rid": ["REF-001,REF-002"],
            },
        ]
    }

    normalized = service._normalize_coverage_payload(coverage_payload, analysis_payload)

    refs = [seed["ref"] for seed in normalized["seed"]]
    assert refs == [["010.001"], ["010.002"]]
    assert all(len(seed["ref"]) == 1 for seed in normalized["seed"])
    assert normalized["seed"][0]["rid"] == ["REQ-001", "REF-001"]
    assert normalized["seed"][1]["rid"] == ["REQ-002", "REF-002"]


def test_normalize_coverage_payload_reclassifies_happy_seed_by_semantic_signals():
    service = JiraTestCaseHelperService(db=None, llm_service=FakeLLMService())
    analysis_payload = {
        "sec": [
            {
                "g": "Auth",
                "it": [
                    {
                        "id": "010.001",
                        "t": "登入失敗處理",
                        "det": ["密碼錯誤應顯示錯誤訊息"],
                        "chk": ["輸入錯誤密碼"],
                        "exp": ["提示 invalid credentials"],
                        "rid": ["REQ-001"],
                    },
                    {
                        "id": "010.002",
                        "t": "關聯列表排序",
                        "det": ["窄螢幕固定欄位與排序仍正確"],
                        "chk": ["切換寬度到最小值並檢查排序"],
                        "exp": ["排序結果在邊界寬度仍一致"],
                        "rid": ["REQ-002"],
                    },
                ],
            }
        ],
        "it": [
            {
                "id": "010.001",
                "t": "登入失敗處理",
                "det": ["密碼錯誤應顯示錯誤訊息"],
                "chk": ["輸入錯誤密碼"],
                "exp": ["提示 invalid credentials"],
                "rid": ["REQ-001"],
            },
            {
                "id": "010.002",
                "t": "關聯列表排序",
                "det": ["窄螢幕固定欄位與排序仍正確"],
                "chk": ["切換寬度到最小值並檢查排序"],
                "exp": ["排序結果在邊界寬度仍一致"],
                "rid": ["REQ-002"],
            },
        ],
    }
    coverage_payload = {
        "seed": [
            {
                "g": "Auth",
                "t": "登入失敗處理",
                "cat": "happy",
                "st": "ok",
                "ref": ["010.001"],
                "rid": ["REQ-001"],
            },
            {
                "g": "Auth",
                "t": "關聯列表排序",
                "cat": "happy",
                "st": "ok",
                "ref": ["010.002"],
                "rid": ["REQ-002"],
            },
        ]
    }

    normalized = service._normalize_coverage_payload(coverage_payload, analysis_payload)
    cat_by_ref = {seed["ref"][0]: seed["cat"] for seed in normalized["seed"]}

    assert cat_by_ref["010.001"] == "negative"
    assert cat_by_ref["010.002"] == "boundary"


def test_normalize_coverage_payload_keeps_all_happy_when_no_negative_or_boundary_signal():
    service = JiraTestCaseHelperService(db=None, llm_service=FakeLLMService())
    analysis_payload = {
        "sec": [
            {
                "g": "Search",
                "it": [
                    {"id": "010.001", "t": "案例 A 檢核", "det": [], "rid": ["REQ-001"]},
                    {"id": "010.002", "t": "案例 B 檢核", "det": [], "rid": ["REQ-002"]},
                    {"id": "010.003", "t": "案例 C 檢核", "det": [], "rid": ["REQ-003"]},
                ],
            }
        ],
        "it": [
            {"id": "010.001", "t": "案例 A 檢核", "det": [], "rid": ["REQ-001"]},
            {"id": "010.002", "t": "案例 B 檢核", "det": [], "rid": ["REQ-002"]},
            {"id": "010.003", "t": "案例 C 檢核", "det": [], "rid": ["REQ-003"]},
        ],
    }
    coverage_payload = {
        "seed": [
            {"g": "Search", "t": "案例 A 檢核", "cat": "happy", "st": "ok", "ref": ["010.001"]},
            {"g": "Search", "t": "案例 B 檢核", "cat": "happy", "st": "ok", "ref": ["010.002"]},
            {"g": "Search", "t": "案例 C 檢核", "cat": "happy", "st": "ok", "ref": ["010.003"]},
        ]
    }

    normalized = service._normalize_coverage_payload(coverage_payload, analysis_payload)
    categories = [seed["cat"] for seed in normalized["seed"]]

    assert categories == ["happy", "happy", "happy"]


def test_deterministic_backfill_does_not_force_reference_item_to_boundary():
    service = JiraTestCaseHelperService(db=None, llm_service=FakeLLMService())
    analysis_payload = {
        "sec": [
            {
                "g": "Reference",
                "it": [
                    {
                        "id": "010.001",
                        "t": "關聯帳號欄位檢核",
                        "det": ["驗證顯示內容正確"],
                        "chk": ["顯示關聯帳號欄位"],
                        "exp": ["欄位值與來源一致"],
                        "rid": ["REQ-001", "REF-001"],
                    }
                ],
            }
        ],
        "it": [
            {
                "id": "010.001",
                "t": "關聯帳號欄位檢核",
                "det": ["驗證顯示內容正確"],
                "chk": ["顯示關聯帳號欄位"],
                "exp": ["欄位值與來源一致"],
                "rid": ["REQ-001", "REF-001"],
            }
        ],
    }
    requirement_ir = {
        "reference_columns": [
            {"rid": "REF-001", "column": "關聯帳號"},
        ]
    }
    payload = service._build_deterministic_coverage_backfill(
        analysis_payload=analysis_payload,
        requirement_ir=requirement_ir,
        missing_ids=["010.001"],
        missing_sections=[],
    )
    assert payload["seed"]
    assert payload["seed"][0]["cat"] == "happy"


@pytest.mark.asyncio
async def test_long_analysis_does_not_block_concurrent_read_latency(helper_db, monkeypatch):
    seeded = _seed_basic_data(helper_db["sync"])

    import app.services.jira_testcase_helper_service as helper_service_module

    monkeypatch.setattr(
        helper_service_module.JiraClient,
        "get_issue",
        lambda self, key, fields=None: {
            "key": key,
            "fields": {
                "summary": "登入流程優化",
                "description": "新增 OTP 驗證與錯誤提示",
                "components": [{"name": "Auth"}],
            },
        },
    )

    fake_llm = FakeLLMService(slow_analysis=True)

    async with helper_db["async"]() as async_db:
        service = JiraTestCaseHelperService(async_db, llm_service=fake_llm)

        async def _empty_similar_cases(_):
            return ""

        service._query_similar_cases = _empty_similar_cases

        started = await service.start_session(
            team_id=seeded["team_id"],
            user_id=seeded["user_id"],
            request=HelperSessionStartRequest(
                test_case_set_id=seeded["set_id"],
                output_locale="zh-TW",
                review_locale="zh-TW",
                initial_middle="010",
            ),
        )

        await service.fetch_ticket(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperTicketFetchRequest(ticket_key="TCG-130078"),
        )
        await service.upsert_draft(
            team_id=seeded["team_id"],
            session_id=started.id,
            phase="requirement",
            request=HelperDraftUpsertRequest(
                markdown="# Requirement\n\n- Login flow",
                payload={"review_locale": "zh-TW"},
                increment_version=True,
            ),
        )
        fake_llm.analysis_calls = 1

        analyze_task = asyncio.create_task(
            service.analyze_and_build_pretestcase(
                team_id=seeded["team_id"],
                session_id=started.id,
                request=HelperAnalyzeRequest(
                    requirement_markdown="# Requirement\n\n- Login flow",
                    retry=False,
                ),
            )
        )

        await asyncio.sleep(0.06)

        async with helper_db["async"]() as read_db:
            read_start = time.perf_counter()

            def _count_sets(sync_db):
                return sync_db.query(TestCaseSet).filter(TestCaseSet.team_id == seeded["team_id"]).count()

            count = await run_sync(read_db, _count_sets)
            read_latency = time.perf_counter() - read_start

        analyzed = await analyze_task

        assert count == 1
        assert read_latency < 0.3
        assert analyzed.session.current_phase.value == "pretestcase"


def test_requirement_ir_normalization_parses_reference_table_semantics():
    service = JiraTestCaseHelperService(db=None, llm_service=FakeLLMService())
    markdown = """
| 欄位 | New | Sortable | Fixed LR | Format Rules | Cross Page Param | Edit Note |
| --- | --- | --- | --- | --- | --- | --- |
| 關聯帳號 | v | v | L | string | account_id | 20250203 edited |
""".strip()

    ir_payload = service._normalize_requirement_ir_payload(
        {},
        ticket_key="TCG-93178",
        summary="Reference 欄位規則調整",
        components=["Search"],
        requirement_markdown=markdown,
    )
    assert ir_payload["reference_columns"]
    first_col = ir_payload["reference_columns"][0]
    assert first_col["column"] == "關聯帳號"
    assert first_col["new_column"] is True
    assert first_col["sortable"] is True
    assert first_col["fixed_lr"] == "left"
    assert first_col["cross_page_param"] == "account_id"
    assert "20250203 edited" in first_col["edit_note"]


@pytest.mark.asyncio
async def test_tcg_93178_regression_backfill_improves_pretestcase_coverage(helper_db, monkeypatch):
    seeded = _seed_basic_data(helper_db["sync"])
    import app.services.jira_testcase_helper_service as helper_service_module

    monkeypatch.setattr(
        helper_service_module.JiraClient,
        "get_issue",
        lambda self, key, fields=None: {
            "key": key,
            "fields": {
                "summary": "Reference 欄位規則調整",
                "description": (
                    "| 欄位 | New | Sortable | Fixed LR | Format Rules | Cross Page Param | Edit Note |\n"
                    "| --- | --- | --- | --- | --- | --- | --- |\n"
                    "| 關聯帳號 | v | v | L | string | account_id | 20250203 edited |\n"
                    "| 關聯項目 |  | v | R | number | item_id | 20250204 edited |\n"
                ),
                "components": [{"name": "Search"}],
            },
        },
    )

    fake_llm = FakeLLMServiceCoverageBackfill()
    async with helper_db["async"]() as async_db:
        service = JiraTestCaseHelperService(async_db, llm_service=fake_llm)
        service.settings.ai.jira_testcase_helper.enable_ir_first = True
        service.settings.ai.jira_testcase_helper.coverage_backfill_max_rounds = 1

        async def _empty_similar_cases(_):
            return ""

        service._query_similar_cases = _empty_similar_cases

        started = await service.start_session(
            team_id=seeded["team_id"],
            user_id=seeded["user_id"],
            request=HelperSessionStartRequest(
                test_case_set_id=seeded["set_id"],
                output_locale="zh-TW",
                review_locale="zh-TW",
                initial_middle="010",
            ),
        )
        await service.fetch_ticket(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperTicketFetchRequest(ticket_key="TCG-93178"),
        )

        analyzed = await service.analyze_and_build_pretestcase(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperAnalyzeRequest(retry=False),
        )
        assert analyzed.session.current_phase.value == "pretestcase"
        assert len(analyzed.payload["pretestcase"]["en"]) == 2
        coverage_trace = analyzed.payload["coverage"]["trace"]
        assert coverage_trace["missing_ids"] == []
        assert coverage_trace["missing_sections"] == []
        assert coverage_trace["backfill_rounds"] == 1
        assert fake_llm.backfill_calls == 1

        ir_draft = next(
            (draft for draft in analyzed.session.drafts if draft.phase == "requirement_ir"),
            None,
        )
        assert ir_draft is not None
        reference_columns = ir_draft.payload["requirement_ir"]["reference_columns"]
        assert len(reference_columns) >= 2
        assert reference_columns[0]["fixed_lr"] == "left"
        assert reference_columns[1]["fixed_lr"] == "right"


@pytest.mark.asyncio
async def test_coverage_uses_deterministic_backfill_when_llm_backfill_still_missing(helper_db, monkeypatch):
    seeded = _seed_basic_data(helper_db["sync"])
    import app.services.jira_testcase_helper_service as helper_service_module

    monkeypatch.setattr(
        helper_service_module.JiraClient,
        "get_issue",
        lambda self, key, fields=None: {
            "key": key,
            "fields": {
                "summary": "Reference 欄位規則調整",
                "description": "欄位一到欄位五都要可獨立檢核",
                "components": [{"name": "Search"}],
            },
        },
    )

    fake_llm = FakeLLMServiceCoverageNeedsDeterministicFallback()
    async with helper_db["async"]() as async_db:
        service = JiraTestCaseHelperService(async_db, llm_service=fake_llm)
        service.settings.ai.jira_testcase_helper.enable_ir_first = True
        service.settings.ai.jira_testcase_helper.coverage_backfill_max_rounds = 1
        service.settings.ai.jira_testcase_helper.coverage_backfill_chunk_size = 2

        async def _empty_similar_cases(_):
            return ""

        service._query_similar_cases = _empty_similar_cases

        started = await service.start_session(
            team_id=seeded["team_id"],
            user_id=seeded["user_id"],
            request=HelperSessionStartRequest(
                test_case_set_id=seeded["set_id"],
                output_locale="zh-TW",
                review_locale="zh-TW",
                initial_middle="010",
            ),
        )
        await service.fetch_ticket(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperTicketFetchRequest(ticket_key="TCG-93178"),
        )

        analyzed = await service.analyze_and_build_pretestcase(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperAnalyzeRequest(retry=False),
        )
        assert analyzed.session.current_phase.value == "pretestcase"
        coverage_trace = analyzed.payload["coverage"]["trace"]
        assert coverage_trace["missing_ids"] == []
        assert coverage_trace["deterministic_backfill_applied"] is True
        assert coverage_trace["deterministic_backfill_seed_count"] >= 1
        assert coverage_trace["backfill_batch_count"] == 2
        entries = analyzed.payload["pretestcase"]["en"]
        assert len(entries) == 5
        categories = [str(entry.get("cat") or "") for entry in entries]
        assert "happy" in categories
        assert categories.count("boundary") < len(categories)
        assert fake_llm.backfill_calls == 2


@pytest.mark.asyncio
async def test_coverage_empty_response_retries_then_succeeds(helper_db, monkeypatch):
    seeded = _seed_basic_data(helper_db["sync"])
    import app.services.jira_testcase_helper_service as helper_service_module

    monkeypatch.setattr(
        helper_service_module.JiraClient,
        "get_issue",
        lambda self, key, fields=None: {
            "key": key,
            "fields": {
                "summary": "登入流程優化",
                "description": "新增 OTP 驗證與錯誤提示",
                "components": [{"name": "Auth"}],
            },
        },
    )

    fake_llm = FakeLLMServiceCoverageEmptyResponse()
    async with helper_db["async"]() as async_db:
        service = JiraTestCaseHelperService(async_db, llm_service=fake_llm)

        async def _empty_similar_cases(_):
            return ""

        service._query_similar_cases = _empty_similar_cases

        started = await service.start_session(
            team_id=seeded["team_id"],
            user_id=seeded["user_id"],
            request=HelperSessionStartRequest(
                test_case_set_id=seeded["set_id"],
                output_locale="zh-TW",
                review_locale="zh-TW",
                initial_middle="010",
            ),
        )
        await service.fetch_ticket(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperTicketFetchRequest(ticket_key="TCG-130078"),
        )

        analyzed = await service.analyze_and_build_pretestcase(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperAnalyzeRequest(retry=False),
        )
        assert analyzed.session.current_phase.value == "pretestcase"
        assert fake_llm.coverage_calls >= 3
        coverage_trace = analyzed.payload["coverage"]["trace"]
        assert coverage_trace["missing_ids"] == []


@pytest.mark.asyncio
async def test_coverage_gate_blocks_pretestcase_when_backfill_disabled(helper_db, monkeypatch):
    seeded = _seed_basic_data(helper_db["sync"])
    import app.services.jira_testcase_helper_service as helper_service_module

    monkeypatch.setattr(
        helper_service_module.JiraClient,
        "get_issue",
        lambda self, key, fields=None: {
            "key": key,
            "fields": {
                "summary": "Reference 欄位規則調整",
                "description": "固定欄位與響應式需求",
                "components": [{"name": "Search"}],
            },
        },
    )

    async with helper_db["async"]() as async_db:
        service = JiraTestCaseHelperService(
            async_db,
            llm_service=FakeLLMServiceCoverageBackfill(),
        )
        service.settings.ai.jira_testcase_helper.enable_ir_first = True
        service.settings.ai.jira_testcase_helper.coverage_backfill_max_rounds = 0
        service.settings.ai.jira_testcase_helper.coverage_force_complete = False

        async def _empty_similar_cases(_):
            return ""

        service._query_similar_cases = _empty_similar_cases

        started = await service.start_session(
            team_id=seeded["team_id"],
            user_id=seeded["user_id"],
            request=HelperSessionStartRequest(
                test_case_set_id=seeded["set_id"],
                output_locale="zh-TW",
                review_locale="zh-TW",
                initial_middle="010",
            ),
        )
        await service.fetch_ticket(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperTicketFetchRequest(ticket_key="TCG-93178"),
        )

        with pytest.raises(ValueError, match="Coverage 完整性檢查未通過"):
            await service.analyze_and_build_pretestcase(
                team_id=seeded["team_id"],
                session_id=started.id,
                request=HelperAnalyzeRequest(retry=False),
            )

        session = await service.get_session(
            team_id=seeded["team_id"],
            session_id=started.id,
        )
        assert session.current_phase.value == "analysis"
        assert session.phase_status.value == "failed"


@pytest.mark.asyncio
async def test_coverage_force_complete_uses_deterministic_fallback_when_llm_failed(helper_db, monkeypatch):
    seeded = _seed_basic_data(helper_db["sync"])
    import app.services.jira_testcase_helper_service as helper_service_module

    monkeypatch.setattr(
        helper_service_module.JiraClient,
        "get_issue",
        lambda self, key, fields=None: {
            "key": key,
            "fields": {
                "summary": "登入流程優化",
                "description": "新增 OTP 驗證與錯誤提示",
                "components": [{"name": "Auth"}],
            },
        },
    )

    async with helper_db["async"]() as async_db:
        service = JiraTestCaseHelperService(
            async_db,
            llm_service=FakeLLMServiceCoverageHardFailure(),
        )
        service.settings.ai.jira_testcase_helper.enable_ir_first = True
        service.settings.ai.jira_testcase_helper.coverage_backfill_max_rounds = 0
        service.settings.ai.jira_testcase_helper.coverage_force_complete = True

        async def _empty_similar_cases(_):
            return ""

        service._query_similar_cases = _empty_similar_cases

        started = await service.start_session(
            team_id=seeded["team_id"],
            user_id=seeded["user_id"],
            request=HelperSessionStartRequest(
                test_case_set_id=seeded["set_id"],
                output_locale="zh-TW",
                review_locale="zh-TW",
                initial_middle="010",
            ),
        )
        await service.fetch_ticket(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperTicketFetchRequest(ticket_key="TCG-130078"),
        )

        analyzed = await service.analyze_and_build_pretestcase(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperAnalyzeRequest(retry=False),
        )
        assert analyzed.session.current_phase.value == "pretestcase"
        assert len(analyzed.payload["pretestcase"]["en"]) >= 1
        coverage_trace = analyzed.payload["coverage"]["trace"]
        assert coverage_trace["missing_ids"] == []
        assert coverage_trace["coverage_fallback_applied"] is True


@pytest.mark.asyncio
async def test_generate_uses_deterministic_fallback_when_testcase_and_audit_llm_failed(
    helper_db,
    monkeypatch,
):
    seeded = _seed_basic_data(helper_db["sync"])
    import app.services.jira_testcase_helper_service as helper_service_module

    monkeypatch.setattr(
        helper_service_module.JiraClient,
        "get_issue",
        lambda self, key, fields=None: {
            "key": key,
            "fields": {
                "summary": "登入流程優化",
                "description": "新增 OTP 驗證與錯誤提示",
                "components": [{"name": "Auth"}],
            },
        },
    )

    async with helper_db["async"]() as async_db:
        service = JiraTestCaseHelperService(
            async_db,
            llm_service=FakeLLMServiceTestcaseAuditFailure(),
        )
        service.settings.ai.jira_testcase_helper.testcase_force_complete = True

        async def _empty_similar_cases(_):
            return ""

        service._query_similar_cases = _empty_similar_cases

        started = await service.start_session(
            team_id=seeded["team_id"],
            user_id=seeded["user_id"],
            request=HelperSessionStartRequest(
                test_case_set_id=seeded["set_id"],
                output_locale="zh-TW",
                review_locale="zh-TW",
                initial_middle="010",
            ),
        )
        await service.fetch_ticket(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperTicketFetchRequest(ticket_key="TCG-130078"),
        )
        analyzed = await service.analyze_and_build_pretestcase(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperAnalyzeRequest(retry=False),
        )

        generated = await service.generate_testcases(
            team_id=seeded["team_id"],
            session_id=started.id,
            request=HelperGenerateRequest(
                pretestcase_payload=analyzed.payload["pretestcase"],
                retry=False,
            ),
        )

        assert generated.session.current_phase.value == "testcase"
        assert generated.session.phase_status.value == "waiting_confirm"
        assert len(generated.payload["tc"]) == len(analyzed.payload["pretestcase"]["en"])
        assert len(generated.payload["testcase_fallback_sections"]) >= 1
        assert len(generated.payload["audit_fallback_sections"]) >= 1
