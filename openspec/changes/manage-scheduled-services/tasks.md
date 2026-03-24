## 1. Scheduler Domain

- [x] 1.1 Add persistent `scheduled_services` data model and Alembic migration, then include it in bootstrap validation
- [x] 1.2 Refactor `app/services/scheduler.py` to expose a schedulable service registry, load persisted schedules on startup, and recover stale running states
- [x] 1.3 Implement scheduler status persistence for execution start/end, next run calculation, and last error/message updates

## 2. Service Management API

- [x] 2.1 Add Super Admin APIs under organization management to list available schedulable services with runtime status
- [x] 2.2 Add Super Admin APIs to enable/disable a scheduled service and update its daily execution time with validation
- [x] 2.3 Reuse existing organization sync service integration so the first schedulable service is `lark_org_sync`

## 3. TCRT UI Integration

- [x] 3.1 Add a Super Admin-only `Service 管理` tab to `team_management.html` and wire UI capability visibility rules
- [x] 3.2 Implement service management frontend in `app/static/js/team-management/main.js` with TCRT-consistent cards, state badges, and daily time controls
- [x] 3.3 Extend `app/static/css/team-management.css` and locale files so the new tab matches the existing TCRT modal/tab style while improving scannability

## 4. Verification

- [x] 4.1 Add focused tests for permission visibility, scheduler persistence/status APIs, and schedule validation
- [x] 4.2 Run focused pytest coverage for organization permission config and scheduled service management flows
