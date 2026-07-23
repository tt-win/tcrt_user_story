"""聚合全部工具（tool-matrix.md + local skill tools）。`tool_registry.get_tool_registry()` 唯一入口。"""

from __future__ import annotations

from app.services.assistant.tools_batch_actions import build_batch_actions_tool
from app.services.assistant.tools_batch_planning import TOOLS as _BATCH_PLANNING_TOOLS
from app.services.assistant.tools_misc import TOOLS as _MISC_TOOLS
from app.services.assistant.tools_skills import TOOLS as _SKILL_TOOLS
from app.services.assistant.tools_test_case_sets import TOOLS as _TEST_CASE_SET_TOOLS
from app.services.assistant.tools_test_cases import TOOLS as _TEST_CASE_TOOLS
from app.services.assistant.tools_test_runs import TOOLS as _TEST_RUN_TOOLS

_LOOPBACK_TOOLS = [*_MISC_TOOLS, *_TEST_CASE_TOOLS, *_TEST_CASE_SET_TOOLS, *_TEST_RUN_TOOLS]
# skill tools 是 local read；不進 batch_execute_actions 的 child enum。
ALL_TOOLS = [
    *_LOOPBACK_TOOLS,
    *_SKILL_TOOLS,
    *_BATCH_PLANNING_TOOLS,
    build_batch_actions_tool([tool.name for tool in _LOOPBACK_TOOLS if tool.is_write()]),
]
