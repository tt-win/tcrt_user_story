"""宣告式工具目錄框架（design D10/D11；spec assistant-tool-execution「工具矩陣為契約」）。

`AssistantTool` 為純資料宣告，不含業務邏輯。`build_registry()` 於載入時驗證：
名稱唯一、DELETE 端點預設 irreversible（豁免需明文列出）、path template 可對應
實際路由、共用 endpoint 的工具彼此欄位互斥（不得讓低風險工具暴露高風險欄位）。
任一缺漏使應用啟動失敗（fail-closed，見 tool-matrix.md「Coverage 結論」）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.auth.models import PermissionType

RiskLevel = str  # "read" | "idempotent_write" | "reversible_write" | "high_impact" | "irreversible"

READ = "read"
IDEMPOTENT_WRITE = "idempotent_write"
REVERSIBLE_WRITE = "reversible_write"
HIGH_IMPACT = "high_impact"
IRREVERSIBLE = "irreversible"

_VALID_RISK_LEVELS = {READ, IDEMPOTENT_WRITE, REVERSIBLE_WRITE, HIGH_IMPACT, IRREVERSIBLE}
_WRITE_RISK_LEVELS = {IDEMPOTENT_WRITE, REVERSIBLE_WRITE, HIGH_IMPACT, IRREVERSIBLE}

# DELETE 工具預設 irreversible；此清單為僅有的兩個豁免（design/tool-matrix「DELETE 豁免」）。
DELETE_RISK_EXEMPTIONS = frozenset({"unpin_entity", "remove_item_bug_ticket"})


@dataclass(frozen=True)
class AssistantTool:
    name: str
    method: str  # "GET"|"POST"|"PUT"|"DELETE"
    path_template: str  # 完整 Starlette route path（含 {team_id} 等 path param 名稱與 converter）
    summary: str  # 供 LLM 的簡短英文描述
    permission: PermissionType
    risk_level: RiskLevel
    execution_mode: str = "loopback"  # "loopback" | "batch_actions"（internal composite）

    path_params: tuple[str, ...] = ()  # LLM 可提供的 path 參數（team_id 由 executor 注入，不列於此）
    query_params: dict[str, dict[str, Any]] = field(default_factory=dict)  # name -> JSON schema fragment
    required_query: tuple[str, ...] = ()
    body_schema: Optional[dict[str, Any]] = None  # 完整 JSON Schema（object/properties/required），None=無 body
    fixed_body: dict[str, Any] = field(default_factory=dict)  # server-fixed 欄位，不進 LLM schema（如 operation=delete）
    multipart_file_param: Optional[str] = None  # 有值代表此工具走 multipart（file_ref -> 該欄位）

    team_check: str = "inject"  # "inject" | "resolve" | "none"（僅 discovery 類全域工具）
    resource_team_resolver: Optional[str] = None  # team_check="resolve" 時對應 resolvers 模組的函式名

    projection: tuple[str, ...] = ()  # 允許進入 LLM context 的欄位 allowlist（JSON path，"." 分隔）
    has_no_response_body: bool = False  # 204 No Content 端點：projection 合法為空，非遺漏
    definitive_pre_mutation_errors: tuple[int, ...] = ()  # v1 全部為空（矩陣保守預設，見通則）

    confirmation_action_key: Optional[str] = None  # i18n key，如 assistant.action.delete_test_case
    warning_key: Optional[str] = None  # assistant.warning.confirm_write / high_impact / irreversible
    target_resolver: Optional[str] = None  # 產生 confirmation 穩定 target identity 的 resolver 名稱

    sensitive_input_paths: tuple[str, ...] = ()  # 命中即加密 execution_payload（縱深防禦，見 D8）
    credential_check_fields: tuple[str, ...] = ()  # 需套用 reject_credential_test_data_value 的 body 欄位

    def is_write(self) -> bool:
        return self.risk_level in _WRITE_RISK_LEVELS

    def confirmation_tier(self) -> str:
        """兩級確認卡：輕量（idempotent/reversible）or 警告（high_impact/irreversible）。"""
        if self.risk_level in (HIGH_IMPACT, IRREVERSIBLE):
            return "warning"
        return "light"

    def to_llm_schema(self) -> dict[str, Any]:
        """OpenRouter `tools=` 陣列的單一 tool 定義。"""
        properties: dict[str, Any] = {}
        required: list[str] = []
        for name in self.path_params:
            properties[name] = {"type": "integer"}
            required.append(name)
        for name, schema in self.query_params.items():
            properties[name] = schema
            if name in self.required_query:
                required.append(name)
        if self.body_schema is not None:
            for name, schema in self.body_schema.get("properties", {}).items():
                properties[name] = schema
            required.extend(self.body_schema.get("required", []))
        if self.multipart_file_param:
            properties["file_ref"] = {
                "type": "string",
                "description": "先前使用者上傳於本對話的暫存檔參照（attachment_index）",
            }
            required.append("file_ref")
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.summary,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": sorted(set(required)),
                    "additionalProperties": False,
                },
            },
        }


class ToolRegistryError(RuntimeError):
    """registry 驗證失敗；MUST 導致應用啟動失敗（fail-closed）。"""


class ToolRegistry:
    def __init__(self, tools: list[AssistantTool]):
        self._tools: dict[str, AssistantTool] = {}
        for tool in tools:
            if tool.name in self._tools:
                raise ToolRegistryError(f"重複的工具名稱: {tool.name}")
            self._tools[tool.name] = tool
        self._validate_delete_risk()
        self._validate_required_metadata()

    def _validate_delete_risk(self) -> None:
        for tool in self._tools.values():
            if tool.method == "DELETE" and tool.risk_level != IRREVERSIBLE:
                if tool.name not in DELETE_RISK_EXEMPTIONS:
                    raise ToolRegistryError(
                        f"DELETE 工具 {tool.name} risk_level={tool.risk_level} 非 irreversible，"
                        f"且不在豁免清單 {sorted(DELETE_RISK_EXEMPTIONS)}"
                    )

    def _validate_required_metadata(self) -> None:
        for tool in self._tools.values():
            if tool.risk_level not in _VALID_RISK_LEVELS:
                raise ToolRegistryError(f"{tool.name}: 未知 risk_level {tool.risk_level}")
            if tool.team_check not in ("inject", "resolve", "none"):
                raise ToolRegistryError(f"{tool.name}: 未知 team_check {tool.team_check}")
            if tool.execution_mode not in ("loopback", "batch_actions"):
                raise ToolRegistryError(f"{tool.name}: 未知 execution_mode {tool.execution_mode}")
            if tool.execution_mode == "batch_actions" and tool.method != "COMPOSITE":
                raise ToolRegistryError(f"{tool.name}: batch_actions 必須使用 COMPOSITE method")
            if tool.team_check == "resolve" and not tool.resource_team_resolver:
                raise ToolRegistryError(f"{tool.name}: team_check=resolve 但缺 resource_team_resolver")
            if not tool.projection and not tool.has_no_response_body:
                raise ToolRegistryError(f"{tool.name}: 缺 projection allowlist")
            if tool.is_write():
                if not tool.confirmation_action_key:
                    raise ToolRegistryError(f"{tool.name}: write 工具缺 confirmation_action_key")
                if not tool.warning_key:
                    raise ToolRegistryError(f"{tool.name}: write 工具缺 warning_key")
                if not tool.target_resolver:
                    raise ToolRegistryError(f"{tool.name}: write 工具缺 target_resolver")
            if tool.definitive_pre_mutation_errors:
                # v1 封閉預設：矩陣尚未 allowlist 任何 4xx 為 definitive failure。
                raise ToolRegistryError(
                    f"{tool.name}: definitive_pre_mutation_errors 非空，需先更新 tool-matrix.md 並附測試"
                )

    def get(self, name: str) -> Optional[AssistantTool]:
        return self._tools.get(name)

    def all(self) -> list[AssistantTool]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def filter_by_permission(self, allowed: set[PermissionType]) -> list[AssistantTool]:
        """回合開始的工具目錄預過濾（design D2）：僅回傳使用者權限涵蓋的工具。"""
        return [t for t in self._tools.values() if t.permission in allowed]

    def discovery_only(self) -> list[AssistantTool]:
        """全域（無 team）對話僅提供 discovery 工具（design D2）。"""
        return [t for t in self._tools.values() if t.risk_level == READ and t.team_check == "none"]


_registry_singleton: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    global _registry_singleton
    if _registry_singleton is None:
        from app.services.assistant.tools_catalog import ALL_TOOLS

        _registry_singleton = ToolRegistry(ALL_TOOLS)
    return _registry_singleton
