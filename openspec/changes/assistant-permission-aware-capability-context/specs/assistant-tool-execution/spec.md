## ADDED Requirements

### Requirement: 能力自述工具

工具目錄 MUST 提供 read-only local 工具 `describe_capabilities`（`execution_mode=local`、不走 ASGI loopback、`team_check=none`、`PermissionType.READ`、`risk_level=read`），全域與 team 對話皆可用。其結果 MUST 為結構化事實，包含：對話 scope、使用者角色、該回合允許的權限等級、被隱藏的寫入能力類別、隱藏原因（`global_scope`／`role_insufficient`）與補救方式；projection allowlist MUST 涵蓋上述欄位。

該工具 MUST NOT 回傳使用者識別資料、其他 team 的資料或端點／參數細節。被隱藏的能力類別 MUST 與同一回合 capability context 的推導來源一致（工具 registry 全集減去過濾後集合）。

#### Scenario: VIEWER 查詢自身能力

- **WHEN** VIEWER 角色使用者在 team 對話中，助手呼叫 `describe_capabilities`
- **THEN** 工具回傳角色 `viewer`、允許權限僅 read、被隱藏的寫入能力類別與原因 `role_insufficient`，且不發出 loopback 請求

#### Scenario: 全域對話可用

- **WHEN** 使用者在全域（無 team）對話中，助手呼叫 `describe_capabilities`
- **THEN** 工具成功回傳，scope 為 `global`、原因含 `global_scope`；其餘 mutation 仍依既有 scope 規則不可用

#### Scenario: 具備權限者無受限敘述

- **WHEN** ADMIN 角色使用者在 team 對話中，助手呼叫 `describe_capabilities`
- **THEN** 回傳的被隱藏能力類別為空，且不含角色不足的原因

## MODIFIED Requirements

### Requirement: executor 為必要權限防線

executor MUST 於每次工具執行前，以 `check_team_permission` 強制驗證使用者具備該工具宣告的 `PermissionType`；驗證失敗即拒絕，不發出 loopback 請求。此檢查為必要防線——部分既有 web 端點（如 test-run-configs、test-run-items、附件端點）本身沒有 in-handler 權限檢查，MUST NOT 假設被呼叫端點會把關。回合開始時的工具目錄預過濾（只把有權限的工具送進 LLM）為引導性質的第一層。

預過濾 MUST 伴隨同一回合的 capability context（見 capability `assistant-agent-loop`），使模型知道目錄曾被過濾及其原因；MUST NOT 讓被過濾的能力對模型表現為「系統不存在此功能」。

#### Scenario: VIEWER 無法透過無檢查端點寫入

- **WHEN** VIEWER 角色的回合中，LLM 產生 create_test_run_config 工具呼叫（該端點本身無權限檢查）
- **THEN** executor 以宣告的 WRITE 權限檢查拒絕，不發出 loopback 請求

#### Scenario: VIEWER 只看得到唯讀工具

- **WHEN** VIEWER 角色使用者開啟一個回合
- **THEN** LLM 收到的 tools 僅含 read 類工具

#### Scenario: 預過濾伴隨過濾原因

- **WHEN** 任一回合的工具目錄因 scope 或角色而被預過濾
- **THEN** 同一回合送往 LLM 的 system prompt MUST 含說明過濾原因的 capability context
