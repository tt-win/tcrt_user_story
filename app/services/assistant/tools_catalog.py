"""聚合全部 65 個工具（tool-matrix.md）。`tool_registry.get_tool_registry()` 唯一入口。"""

from __future__ import annotations

from app.services.assistant.tools_misc import TOOLS as _MISC_TOOLS
from app.services.assistant.tools_test_case_sets import TOOLS as _TEST_CASE_SET_TOOLS
from app.services.assistant.tools_test_cases import TOOLS as _TEST_CASE_TOOLS
from app.services.assistant.tools_test_runs import TOOLS as _TEST_RUN_TOOLS
from app.services.assistant.tools_batch_actions import build_batch_actions_tool

_LOOPBACK_TOOLS = [*_MISC_TOOLS, *_TEST_CASE_TOOLS, *_TEST_CASE_SET_TOOLS, *_TEST_RUN_TOOLS]
ALL_TOOLS = [*_LOOPBACK_TOOLS, build_batch_actions_tool([tool.name for tool in _LOOPBACK_TOOLS if tool.is_write()])]
