# Delta Spec — etl-all-teams

> 對 `openspec/specs/etl-all-teams/spec.md` 的 delta：整個 capability 移除。
> Qdrant 向量檢索在 TCRT 內已無任何消費者（QA AI Helper 走 IR-first），
> 此 ETL 亦從未在 repo 內有實作。

## REMOVED Requirements

### Requirement: Synchronize Test Cases

**Reason**: Qdrant 支援整體移除；無任何功能消費 `test_cases` collection。
**Migration**: 無需遷移——repo 內沒有此 ETL 的實作，外部 Qdrant instance 可直接停用。

### Requirement: Synchronize USM Nodes

**Reason**: 同上；`usm_nodes` collection 無消費者。
**Migration**: 無。

### Requirement: Batch Processing

**Reason**: 隨 ETL capability 一併移除。
**Migration**: 無。

### Requirement: Error Handling and Recovery

**Reason**: 隨 ETL capability 一併移除。
**Migration**: 無。

### Requirement: Deterministic Point IDs

**Reason**: 隨 ETL capability 一併移除。
**Migration**: 無。
