# ADR-001: Event Catalog & Emit Helper Location

## Status
Accepted

## Context
The `audit-ops-event-envelope` change introduces a shared **event catalog** and **emit helper** (`emit_event` / `safe_emit_event`) used by both:
- **Audit subsystem** (writes to audit DB)
- **Ops logging subsystem** (writes to Python stdlib logging → ring buffer)

Existing codebase layering:
- `app/audit/` — audit DB, models, service, middleware
- `app/services/automation/` — automation hub business logic (run_service, allure_proxy, etc.)
- `app/utils/system_log_buffer.py` — ring buffer handler (captures stdlib logging)
- `app/api/audit.py` — audit REST API

## Decision
Place the new observability primitives in **`app/services/observability/`**:

```
app/services/observability/
├── __init__.py
├── event_catalog.py      # EventCatalog, EventDef, registry, validation
├── emit.py               # emit_event, safe_emit_event, exceptions
└── enums.py              # Impact, Outcome, OpLevel (shared enums)
```

### Rationale
1. **Service-layer alignment** — `app/services/` is the established home for cross-cutting business capabilities (automation, auth, QA AI helper). Observability is a cross-cutting capability.
2. **No circular imports** — `app/services/automation/*` already imports from `app/services/automation/providers/` and `app/services/automation/provider_registry.py`. Placing observability under `app/services/` keeps import graph acyclic: `automation → observability`, not `observability → automation`.
3. **Avoids `app/utils/` pollution** — `app/utils/` is for stateless utilities (redaction, date parsing, etc.). Catalog + emit are stateful (registry, validation) and have business logic.
4. **Avoids `app/audit/` coupling** — Audit is a *consumer* of the catalog (writes audit DB), not the owner. Ops logging is a separate consumer.
5. **Future-proof** — If we add metrics, tracing, or OpenTelemetry later, they live alongside as sibling modules.

## Consequences
- **New module** `app.services.observability` added to `pyproject.toml` / `uv` workspace (no new deps).
- Import path: `from app.services.observability import emit_event, safe_emit_event, EventCatalog, Impact, Outcome, OpLevel`
- `app/services/automation/run_service.py` and `allure_proxy.py` will import from `app.services.observability`.
- `app/audit/audit_service.py` will import from `app.services.observability` (replaces direct DB writes with `safe_emit_event`).

## Alternatives Considered
| Option | Rejected Because |
|--------|------------------|
| `app/observability/` (top-level) | Inconsistent with existing `app/services/` pattern; creates new top-level package |
| `app/utils/observability.py` | Too large for `utils/`; catalog is stateful registry, not stateless util |
| `app/audit/observability.py` | Couples ops logging to audit; audit is one consumer |
| `app/services/automation/observability.py` | Too narrow; audit & system-log-viewer also need it |

## Validation
- `uv run python -c "from app.services.observability import EventCatalog; print('OK')"` works after implementation.
- No import cycles detected by `pydeps` or `madge` (when run).