# Automation Hub — Webhook Reference

TCRT integrates with CI in **two ways**:

- **Inbound**: CI calls `POST /api/v1/webhooks/ci/{token}/run-status` when a
  run finishes (or any time mid-flight). HMAC-signed, no auth header.
- **Trigger + poll**: external software fires a suite via `POST .../trigger`
  and reads the result back via `GET .../runs/{tcrt_run_id}`. Token-auth, no
  signature — see "Trigger a suite & poll for the result" below.

Each team can create as many INBOUND webhooks as needed via the
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

## Trigger a suite & poll for the result

For external software that **kicks off a run and then wants the result** — as
opposed to receiving push callbacks — use the trigger + poll pair on an INBOUND
webhook bound to a suite (`script_group_id`). Both endpoints authenticate with
the path token alone (no signature), so each is a runnable one-line curl.

This pairs cleanly with how TCRT tracks CI today: the run row is kept current by
a background loop that **pulls** status and the Allure report from CI, so the
poll endpoint just exposes that already-synced state — it never calls CI inline.

> **Dedicated webhook job.** A webhook trigger runs on the suite's **own** CI
> job — `tcrt_{team}_{suite}_hook`, separate from the primary `tcrt_{team}_{suite}`
> job that Test Run Sets use — so the two trigger sources keep independent build
> history and queues. The webhook job is created lazily on the suite's first
> webhook trigger (no setup needed). Webhook runs also report to their own Allure
> project (`…-webhook`), so their report trend stays isolated from Test-Run-Set
> runs of the same suite.

### 1. Trigger

```
POST /api/v1/webhooks/ci/{token}/trigger
Content-Type: application/json        # body optional
```

Optional JSON body: `{ "branch": "…", "runner_label": "…", "inputs": {…} }`.
Returns immediately with a QUEUED handle. **Keep `tcrt_correlation_id`** — it's
the stable key for polling (`external_run_id` is a transient `queue:NNNN` at this
point and mutates to the build number later):

```json
{
  "run_id": 42,
  "tcrt_correlation_id": "5f8b4d8e-…",
  "external_run_id": "queue:123",
  "external_run_url": "https://ci.example/queue/item/123/",
  "status": "QUEUED"
}
```

### 2. Poll

```
GET /api/v1/webhooks/ci/{token}/runs/{tcrt_run_id}
```

`{tcrt_run_id}` is the `tcrt_correlation_id` from step 1. Poll until `status` is
terminal (`SUCCEEDED` / `FAILED` / `CANCELLED`). The lookup is scoped to runs
**this** webhook triggered (`triggered_by_webhook_id`), so a token can only read
back its own runs — never other runs in the team.

```json
{
  "run_id": 42,
  "tcrt_correlation_id": "5f8b4d8e-…",
  "status": "SUCCEEDED",
  "external_run_id": "12",
  "external_run_url": "https://ci.example/job/…/12/",
  "report_url": "https://allure.example/runs/12",
  "branch": "main",
  "started_at": "2026-05-18T10:20:30",
  "finished_at": "2026-05-18T10:24:11",
  "duration_ms": 221000,
  "error_summary": null,
  "last_synced_at": "2026-05-18T10:24:20"
}
```

### Sample trigger + poll loop

```bash
TCRT_BASE_URL="https://tcrt.internal"
TOKEN="…webhook-token…"

CID=$(curl -fsS -X POST "$TCRT_BASE_URL/api/v1/webhooks/ci/$TOKEN/trigger" \
  | jq -r .tcrt_correlation_id)

while :; do
  STATUS=$(curl -fsS "$TCRT_BASE_URL/api/v1/webhooks/ci/$TOKEN/runs/$CID" | jq -r .status)
  case "$STATUS" in
    SUCCEEDED|FAILED|CANCELLED) echo "done: $STATUS"; break ;;
    *) sleep 10 ;;
  esac
done
```

### Error codes

| HTTP | `detail.code` | Cause |
|---|---|---|
| 400 | `WEBHOOK_NOT_INBOUND` | Token belongs to an OUTBOUND webhook. |
| 403 | `WEBHOOK_INACTIVE` | Webhook was disabled by an admin. |
| 404 | `WEBHOOK_NOT_FOUND` | Unknown token. |
| 404 | `AUTOMATION_RUN_NOT_MATCHED` | No run with that id was triggered by this webhook. |
| 429 | `WEBHOOK_RATE_LIMITED` | >120 req/min on this token; honour `Retry-After`. |
