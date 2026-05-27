# Automation Hub — Webhook Reference

TCRT integrates with CI in **two directions**:

- **Inbound**: CI calls `POST /api/v1/webhooks/ci/{token}/run-status` when a
  run finishes (or any time mid-flight). HMAC-signed, no auth header.
- **Outbound**: TCRT POSTs events (`script.linked`, `run.triggered`,
  `run.completed`, etc.) to URLs configured per team. Same HMAC scheme.

Each team can create as many INBOUND or OUTBOUND webhooks as needed via the
Webhooks settings page or the admin API at
`/api/teams/{team_id}/automation-webhooks`.

---

## Inbound: CI → TCRT

### Endpoint

```
POST /api/v1/webhooks/ci/{token}/run-status
Content-Type: application/json
X-TCRT-Signature: sha256=<hex>     # or raw <hex>
X-TCRT-Delivery: <unique-id>       # optional, used as idempotency hint
```

Public — **no auth header**. The path-segment token plus HMAC signature is
the credential pair.

### Payload schema

```json
{
  "tcrt_run_id": "5f8b4d8e-…",     // TCRT correlation id (preferred matcher)
  "external_run_id": "queue:123",  // CI-side id (fallback matcher)
  "status": "SUCCEEDED",            // see status mapping below
  "external_run_url": "https://ci.example/run/123",
  "started_at": "2026-05-18T10:20:30Z",
  "finished_at": "2026-05-18T10:24:11Z",
  "duration_ms": 221000,
  "error_summary": "…optional, terminal only…",
  "report_url": "https://allure.example/runs/123"
}
```

**Required**: `status` plus either `tcrt_run_id` (preferred) or
`external_run_id` to match the existing `automation_runs` row.

### Status mapping

TCRT normalises common CI vocabularies into the `automation_run_status` enum:

| Incoming | Becomes |
|---|---|
| `QUEUED` | `QUEUED` |
| `RUNNING` | `RUNNING` |
| `SUCCEEDED` / `SUCCESS` / `PASSED` / `COMPLETED` | `SUCCEEDED` |
| `FAILED` / `FAILURE` / `ERROR` / `UNSTABLE` | `FAILED` |
| `CANCELLED` / `ABORTED` | `CANCELLED` |
| anything else | `UNKNOWN` |

Terminal runs (`SUCCEEDED` / `FAILED` / `CANCELLED`) **cannot** be reverted to a
non-terminal state by a stale payload.

### Signing

`X-TCRT-Signature` is `HMAC-SHA256(body_bytes, webhook.secret).hexdigest()`.
Both `sha256=<hex>` and bare `<hex>` are accepted. Signature mismatch yields
401 `WEBHOOK_SIGNATURE_INVALID`.

### Idempotency

Send a stable `X-TCRT-Delivery` per logical event (e.g. `runId-attemptN`).
TCRT records the latest delivery id in `webhook.last_status` for observability.
Because terminal-state transitions are one-way, duplicate deliveries of the
same terminal status are effectively idempotent.

### Sample curl

```bash
TCRT_BASE_URL="https://tcrt.internal"
TOKEN="…webhook-token…"
SECRET="…webhook-secret…"
PAYLOAD='{"tcrt_run_id":"'"$TCRT_RUN_ID"'","status":"SUCCEEDED","external_run_url":"'"$BUILD_URL"'","duration_ms":'"$DURATION_MS"'}'
SIG=$(printf '%s' "$PAYLOAD" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')

curl -X POST "$TCRT_BASE_URL/api/v1/webhooks/ci/$TOKEN/run-status" \
  -H "Content-Type: application/json" \
  -H "X-TCRT-Signature: sha256=$SIG" \
  -H "X-TCRT-Delivery: $BUILD_ID" \
  -d "$PAYLOAD"
```

### Error codes

| HTTP | `detail.code` | Cause |
|---|---|---|
| 400 | `INVALID_PAYLOAD` | Body wasn't a JSON object. |
| 400 | `WEBHOOK_NOT_INBOUND` | Token belongs to an OUTBOUND webhook. |
| 401 | `WEBHOOK_SIGNATURE_INVALID` | HMAC mismatch or missing header. |
| 403 | `WEBHOOK_INACTIVE` | Webhook was disabled by an admin. |
| 404 | `WEBHOOK_NOT_FOUND` | Unknown token. |
| 404 | `AUTOMATION_RUN_NOT_MATCHED` | No `automation_runs` row matched. |

---

## Outbound: TCRT → your endpoint

Configure an OUTBOUND webhook with a `target_url` and an `events` array. An
empty `events` array means **wildcard** — receives every event. Otherwise, only
matching events are delivered.

### Event types

| Event | Fired when | Payload `data` shape |
|---|---|---|
| `script.linked` | A test case is linked to a script | `{link_id, script_id, test_case_id, link_type, actor_user_id}` |
| `script.unlinked` | A link is deleted | `{link_id, script_id, actor_user_id}` |
| `run.triggered` | User triggers a script or suite run | `{run_id, automation_script_id, script_group_id, workflow_id, branch, status, external_run_id, external_run_url, tcrt_correlation_id}` |
| `run.tracked` | Any run status update (incl. inbound webhook ingest, cancel, reconcile) | `{run_id, automation_script_id, script_group_id, workflow_id, branch, status, external_run_id, external_run_url, report_url, tcrt_correlation_id, duration_ms}` |
| `run.completed` | Run transitions to a terminal status | same shape as `run.tracked` |

### Envelope

Every outbound delivery POSTs JSON in this shape:

```json
{
  "event": "run.completed",
  "delivery_id": "uuid",
  "occurred_at": "2026-05-18T10:24:11Z",
  "team_id": 7,
  "data": { … see table above … }
}
```

Headers:
- `Content-Type: application/json`
- `X-TCRT-Event: <event-name>`
- `X-TCRT-Delivery: <delivery-id>`
- `X-TCRT-Signature: sha256=<hex>` over the raw body bytes.

### Failure handling

Outbound delivery is **fire-and-forget**: any non-2xx, timeout, or connection
error is logged on the webhook row as `<EVENT>_FAILED [<status_code>]` in
`last_status`. The Webhooks settings page colour-codes failed deliveries red
so admins can spot misconfigured endpoints. There is **no automatic retry**;
the receiver is expected to be tolerant of dropped events and reconcile via
the read APIs if needed.

### Test pings

The Webhooks UI exposes a "Send test ping" action per OUTBOUND webhook
(`POST /api/teams/{id}/automation-webhooks/{webhook_id}/test-ping`) that fires
a synthetic `event: "test"` delivery. Use it to verify connectivity and HMAC
config before going live.
