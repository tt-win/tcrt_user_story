"""Assistant 服務層例外；API 層依 `error_code` 映射 HTTP 狀態碼。"""

from __future__ import annotations


class AssistantError(Exception):
    """所有 assistant 服務例外的基底。"""

    error_code: str = "ASSISTANT_ERROR"
    http_status: int = 500

    def __init__(self, message: str | None = None):
        super().__init__(message or self.error_code)


class AssistantNotConfiguredError(AssistantError):
    error_code = "ASSISTANT_NOT_CONFIGURED"
    http_status = 503


class ConversationNotFoundError(AssistantError):
    """對話不存在或不屬於當前使用者——一律回 404，不揭露是否存在。"""

    error_code = "CONVERSATION_NOT_FOUND"
    http_status = 404


class ConversationHasActiveTurnError(AssistantError):
    error_code = "CONVERSATION_HAS_ACTIVE_TURN"
    http_status = 409


class IdempotencyKeyReusedError(AssistantError):
    """同一 client_message_id 帶不同內容重送。"""

    error_code = "IDEMPOTENCY_KEY_REUSED"
    http_status = 409


class AdmissionDeniedError(AssistantError):
    """rate limit bucket / 跨 worker admission counter / lease 佔用 / 本機 slot 不足。"""

    error_code = "ADMISSION_DENIED"
    http_status = 429


class TurnLeaseBusyError(AssistantError):
    """該對話已有進行中 turn 佔用 lease。"""

    error_code = "TURN_LEASE_BUSY"
    http_status = 429


class ScopeInvalidError(AssistantError):
    """對話為 global 或綁定 team 已刪除，不可再產生 mutation/新 turn。"""

    error_code = "SCOPE_INVALID"
    http_status = 409


class PendingActionNotFoundError(AssistantError):
    error_code = "PENDING_ACTION_NOT_FOUND"
    http_status = 404


class PendingActionNotClaimableError(AssistantError):
    """CAS 認領失敗：已被處理或已過期。"""

    error_code = "PENDING_ACTION_NOT_CLAIMABLE"
    http_status = 409


class ConfirmationStaleError(AssistantError):
    """confirm 前重算 fingerprint 與建立時不同：資源已變更，需重新確認。

    可選 `new_summary` / `new_fingerprint`：live recheck（claim Tx A 內）偵測到
    變更時帶出，供 API 層 CAS 更新確認卡後再回 409（與 pre-claim 路徑一致）。
    """

    error_code = "CONFIRMATION_STALE"
    http_status = 409

    def __init__(
        self,
        message: str | None = None,
        *,
        new_summary: dict | None = None,
        new_fingerprint: str | None = None,
    ):
        super().__init__(
            message or "target changed, please review the updated summary and confirm again"
        )
        self.new_summary = new_summary
        self.new_fingerprint = new_fingerprint


class TeamScopeMismatchError(AssistantError):
    """`resource_team_check` resolver 判定目標資源不屬於對話綁定 team。"""

    error_code = "TEAM_SCOPE_MISMATCH"
    http_status = 403


class ToolPermissionDeniedError(AssistantError):
    error_code = "TOOL_PERMISSION_DENIED"
    http_status = 403


class CredentialWriteRejectedError(AssistantError):
    """聊天寫入 credential 值被拒（見 spec assistant-data-boundary）。"""

    error_code = "CREDENTIAL_WRITE_REJECTED"
    http_status = 422


class ConfirmationSummaryUnresolvableError(AssistantError):
    """high_impact/irreversible 工具無法解析穩定 target identity/version，fail-closed。"""

    error_code = "CONFIRMATION_SUMMARY_UNRESOLVABLE"
    http_status = 422


class SensitivePayloadEncryptionUnavailableError(AssistantError):
    error_code = "SENSITIVE_PAYLOAD_ENCRYPTION_UNAVAILABLE"
    http_status = 503


class MessageTooLongError(AssistantError):
    error_code = "MESSAGE_TOO_LONG"
    http_status = 422
