"""有效 team（effective team）的單一解析點（spec assistant-tool-execution
「in-process loopback 執行與 team_id 注入」）。

- team-bound 對話：目標 team 一律為對話綁定的 `conversation.team_id`。
- 全域對話：目標 team 為該 turn 的 context team 快照（`turn.context_team_id`）。
- 兩者皆無 → `None`，代表本回合不得執行任何需要 team 的工具（fail-closed）。

executor / API / agent 迴圈都 MUST 經此函式取得 team，不得各自讀 `conversation.team_id`
或 `turn.context_team_id`——任一處漏改就是「功能不通」或「跨 team 越權」。
"""

from __future__ import annotations

from typing import Any, Optional


def effective_team_id(conversation: Any, turn: Any) -> Optional[int]:
    if getattr(conversation, "scope_type", None) == "team":
        return getattr(conversation, "team_id", None)
    return getattr(turn, "context_team_id", None)
