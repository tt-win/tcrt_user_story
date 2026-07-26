"""回合能力上下文（capability context；spec assistant-agent-loop「回合能力上下文」）。

工具目錄在回合開始會依對話 scope 與使用者角色預過濾（design D2），但送往 LLM 的
system prompt 是跨使用者共用的快取內容，完全不含角色／scope 資訊。模型因此無法分辨
「系統沒有這個功能」與「這個能力被你的角色或這個對話的 scope 過濾掉了」，實際觀察到
助手把權限限制誤述為能力限制（並反過來否認與權限有關）。

本模組把該回合的權威事實組成可 append 的區塊（MUST NOT 進入 prompt 快取，見 design D1），
並以同一組事實供 local 工具 `describe_capabilities` 回傳結構化版本。
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from app.auth.models import PermissionType, UserRole
from app.services.assistant.tool_registry import AssistantTool, ToolRegistry

NO_TEAM_CONTEXT = "no_team_context"
ROLE_INSUFFICIENT = "role_insufficient"

OTHER_WRITE = "other_write"

# 能力「類別」而非工具名列舉：context budget 有限，且描述長度不應隨工具數線性成長
# （design D3）。類別由 registry 全集減去回合過濾後集合推導，不維護第二份清單。
_CATEGORY_LABELS: dict[str, str] = {
    "test_case_write": "測試案例的建立／修改／刪除／搬移與附件",
    "test_case_set_write": "test case set 與 section 的建立／修改／刪除",
    "test_run_write": "test run 與 run set 的建立、修改、歸檔、狀態與報表",
    "test_run_item_write": "test run item 的新增、指派、結果回報與 bug ticket",
    "automation_write": "自動化執行的觸發、取消與校正",
    "pin_write": "釘選項目的新增與移除",
    "batch_write": "批次寫入（一次提交多個寫入動作）",
    OTHER_WRITE: "其他寫入類操作",
}

# 依序比對工具名的子字串；先命中者勝。順序很重要：run item / set / section 的規則
# 必須排在較寬鬆的 test_case / test_run 規則之前。
_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("automation_write", ("automation",)),
    ("pin_write", ("pin_entity",)),
    ("batch_write", ("batch_execute_actions",)),
    ("test_run_item_write", ("test_run_item", "run_item", "item_bug_ticket", "batch_update_results")),
    ("test_case_set_write", ("test_case_set", "test_case_section")),
    ("test_case_write", ("test_case", "test_set_impact")),
    ("test_run_write", ("test_run", "run_set", "run_between_sets", "runs_to_set")),
)

_PERMISSION_ORDER = (PermissionType.READ, PermissionType.WRITE, PermissionType.ADMIN)


def allowed_permissions_for_role(role: UserRole) -> set[PermissionType]:
    """角色→權限等級映射，鏡射 `permission_service._role_to_permission`（design D2 工具目錄預過濾）。"""
    if role in (UserRole.SUPER_ADMIN, UserRole.ADMIN):
        return {PermissionType.READ, PermissionType.WRITE, PermissionType.ADMIN}
    if role == UserRole.USER:
        return {PermissionType.READ, PermissionType.WRITE}
    return {PermissionType.READ}


def tools_for_turn(
    registry: ToolRegistry, *, team_id: Optional[int], role: UserRole
) -> list[AssistantTool]:
    """回合工具目錄預過濾（design D2）。單一來源：agent 迴圈與 `describe_capabilities` 共用，
    否則兩處各自實作會讓「模型看到的目錄」與「工具回報的事實」漂移。

    `team_id` 為本回合的**有效 team**（team 對話的綁定 team，或全域對話的 context team 快照；
    見 `team_context.effective_team_id`）。為空即無目標 team，只給 discovery（fail-closed）。
    """
    if team_id is None:
        return registry.discovery_only()
    return registry.filter_by_permission(allowed_permissions_for_role(role))


def permission_names(allowed: Iterable[PermissionType]) -> list[str]:
    allowed_set = set(allowed)
    return [p.value for p in _PERMISSION_ORDER if p in allowed_set]


def capability_category(tool_name: str) -> str:
    """工具名→能力類別；未命中任何規則時回傳 `OTHER_WRITE`（fallback 由測試守門）。"""
    for category, needles in _CATEGORY_RULES:
        if any(needle in tool_name for needle in needles):
            return category
    return OTHER_WRITE


def derive_withheld_capabilities(
    all_tools: Iterable[AssistantTool], allowed_tool_names: Iterable[str]
) -> list[dict[str, str]]:
    """由 registry 全集減去本回合過濾後集合，推導被隱藏的寫入能力類別（穩定排序）。

    只計入需要 read 以上權限的工具（`permission != READ`）——這正是「寫入能力」的定義邊界，
    並涵蓋 `preview_move_test_set_impact` 這類 risk=read 但需 WRITE 權限的工具。全域對話另有
    大量 team-scoped 唯讀工具被過濾，那由 scope 原因說明，不混入寫入能力類別。
    """
    allowed = set(allowed_tool_names)
    categories = {
        capability_category(tool.name)
        for tool in all_tools
        if tool.permission != PermissionType.READ and tool.name not in allowed
    }
    # 依 `_CATEGORY_LABELS` 宣告順序輸出（穩定且由重要性排序），不用字典序。
    return [
        {"id": category, "label": label}
        for category, label in _CATEGORY_LABELS.items()
        if category in categories
    ]


def build_capability_facts(
    *,
    role: UserRole,
    scope_type: Optional[str],
    team_id: Optional[int] = None,
    team_name: Optional[str] = None,
    all_tools: Iterable[AssistantTool],
    allowed_tool_names: Iterable[str],
) -> dict[str, Any]:
    """本回合的權威能力事實；同時供 prompt 區塊與 `describe_capabilities` 使用。

    `team_id`／`team_name` 為本回合的**有效 team**：team 對話取綁定 team，全域對話取該 turn 的
    context team 快照。為空代表無目標 team（原因 `no_team_context`）。
    """
    has_team = team_id is not None
    allowed_permissions = allowed_permissions_for_role(role)
    role_allows_write = PermissionType.WRITE in allowed_permissions
    withheld = derive_withheld_capabilities(all_tools, allowed_tool_names)

    reasons: list[str] = []
    if not has_team:
        reasons.append(NO_TEAM_CONTEXT)
    if withheld and not role_allows_write:
        reasons.append(ROLE_INSUFFICIENT)

    remediation: list[str] = []
    if NO_TEAM_CONTEXT in reasons:
        # 全域對話的目標 team 來自前端工作區（turn context team 快照）；使用者可以在介面切換
        # 工作區後重試——這是真的入口，與舊版「切換到 team 對話」的死路不同。
        remediation.append("在介面選定目標 team 的工作區後重新提出這個需求")
    if ROLE_INSUFFICIENT in reasons:
        remediation.append("向團隊管理員申請提升為具備 write 權限的角色")

    return {
        "scope": "team" if scope_type == "team" else "global",
        "team_id": team_id,
        "team_name": team_name if has_team else None,
        "role": role.value if isinstance(role, UserRole) else str(role),
        "allowed_permissions": permission_names(allowed_permissions),
        "withheld_capabilities": withheld,
        "reasons": reasons,
        "remediation": remediation,
    }


def append_capability_context(system_prompt: str, facts: dict[str, Any]) -> str:
    """把 capability context 接在組裝後的 system prompt 之後。

    MUST 以 append 實作、MUST NOT 依賴模板 token：DB 內的 system prompt 可由管理員任意編輯，
    token 一被刪掉就會靜默退回「把權限限制說成能力限制」的錯誤行為（design D2）。
    """
    return f"{system_prompt.rstrip()}\n\n{build_capability_context(facts)}"


def build_capability_context(facts: dict[str, Any]) -> str:
    """把能力事實渲染為 append 至 system prompt 末端的區塊（design D2：不依賴模板 token）。"""
    team_id = facts.get("team_id")
    if team_id is not None:
        team_name = facts.get("team_name") or f"Team-{team_id}"
        scope = facts.get("scope")
        origin = "對話綁定" if scope == "team" else "使用者目前的工作區（context team）"
        target_line = f"本回合目標 team：`{team_name}`（team_id={team_id}，來源：{origin}）"
    else:
        target_line = "本回合目標 team：無（此對話未綁定 team，且本回合未帶入工作區 team）"

    lines = [
        "## 本回合能力事實（權威，優先於上方任何一般性能力描述）",
        "",
        f"- {target_line}",
        f"- 使用者角色：`{facts.get('role')}`",
        f"- 本回合可用權限：{'／'.join(facts.get('allowed_permissions') or []) or '（無）'}",
    ]
    if team_id is not None:
        lines.append(
            "- 目標 team 消歧：使用者指名的 team 與上方目標 team 不一致時，必須先反問或請使用者"
            "在介面切換工作區後重試，不得自行選一個 team 執行寫入。"
        )

    withheld = facts.get("withheld_capabilities") or []
    reasons = facts.get("reasons") or []
    if not withheld:
        lines.append("- 本回合的寫入能力未受限；工具目錄即你的完整能力範圍。")
        return "\n".join(lines) + "\n"

    labels = "；".join(item["label"] for item in withheld)
    lines.append(f"- 已自本回合工具目錄移除的寫入能力：{labels}")
    if NO_TEAM_CONTEXT in reasons:
        lines.append(
            "- 移除原因 `no_team_context`：本回合沒有目標 team，因此所有 team-scoped 操作（含唯讀）"
            "都不在目錄中。這些功能在系統中存在，只是需要先確定要操作哪個 team。"
        )
    if ROLE_INSUFFICIENT in reasons:
        lines.append(
            f"- 移除原因 `role_insufficient`：角色 `{facts.get('role')}` 僅具唯讀權限，"
            "上述能力在系統中存在，只是本回合不可用。"
        )
    if NO_TEAM_CONTEXT in reasons and ROLE_INSUFFICIENT in reasons:
        lines.append("- 兩個原因並存：即使選定工作區 team，上述寫入操作本身仍需要 write 權限。")

    remediation = facts.get("remediation") or []
    if remediation:
        lines.append(f"- 正確補救路徑：{'；'.join(remediation)}。")
    guidance = (
        "- 回答準則：使用者要求上述能力時，必須歸因為缺少目標 team 或角色權限並給出上述補救路徑；"
        "不得聲稱系統沒有這個功能／此操作不可能，不得只說「我沒有這個工具」，"
        "也不得叫使用者「切換到某個 team 的對話」（沒有這個入口，要切換的是工作區）。"
    )
    if ROLE_INSUFFICIENT in reasons:
        guidance += (
            "由於原因包含 `role_insufficient`，**不得**以「請改用 TCRT 網頁介面」作為解法"
            "——同一權限限制在網頁介面同樣成立。"
        )
    lines.append(guidance + "需要結構化事實時可呼叫 `describe_capabilities`。")
    return "\n".join(lines) + "\n"
