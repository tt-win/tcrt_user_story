# Jenkins shell snippet — ship allure-results to TCRT (TCRT proxies to Allure)
#
# Drop this block into the `post.always` (or equivalent) section of an existing
# Jenkinsfile / Groovy pipeline script for hand-managed Jenkins jobs. Note:
# TCRT-generated suite + single-script jobs already include this logic — you
# only need this for jobs you maintain yourself.
#
# Why this shape: Jenkins agents typically live on a different host from TCRT,
# so they can't reach an Allure server running on TCRT's loopback. The clean
# split is "Jenkins ships archive to TCRT; TCRT — co-located with Allure — does
# the upload + generate-report handshake locally". The Jenkins side stays
# simple and only needs ONE URL: the existing TCRT webhook URL.
#
# Required pytest invocation (in your Test stage):
#   pytest --alluredir="${WORKSPACE}/allure-results" <your test paths>
#
# Required env vars:
#   TCRT_WEBHOOK_URL    full webhook URL (TCRT_BASE_URL + /api/v1/webhooks/ci/<token>/run-status).
#                       The allure-results upload URL is derived from this — the
#                       allure-results endpoint shares the same token prefix.
#
# Promote Groovy-only values into env vars before the sh block:
#   script {
#     env.TCRT_WEBHOOK_RUN_ID = params.tcrt_run_id ?: ''
#     env.TCRT_WEBHOOK_STATUS = currentBuild.currentResult ?: 'UNKNOWN'
#   }

set +e

ALLURE_REPORT_URL=""

# --- 1. Archive allure-results and ship to TCRT --------------------------
if [ -n "${TCRT_WEBHOOK_URL:-}" ] && [ -d "${WORKSPACE}/allure-results" ]; then
  ALLURE_UPLOAD_URL="${TCRT_WEBHOOK_URL%/run-status}/allure-results"
  tar czf "${WORKSPACE}/allure-results.tgz" -C "${WORKSPACE}" allure-results \
    || echo "Failed to archive allure-results (non-fatal)"

  if [ -f "${WORKSPACE}/allure-results.tgz" ]; then
    RESP=$(curl -sS -X POST "${ALLURE_UPLOAD_URL}" \
      -F "tcrt_run_id=${TCRT_WEBHOOK_RUN_ID}" \
      -F "results=@${WORKSPACE}/allure-results.tgz" \
      || echo "")
    if [ -n "$RESP" ]; then
      ALLURE_REPORT_URL=$(echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('report_url') or '')" 2>/dev/null || echo "")
    fi
    # The proxy already wrote report_url onto the run before returning, so the
    # subsequent status webhook doesn't strictly need to repeat it — but doing
    # so makes the run-status webhook self-describing.
  fi
fi

set -e

# --- 2. Notify TCRT with status (+ report_url when available) ------------
if [ -n "${TCRT_WEBHOOK_URL:-}" ]; then
  if [ -n "${ALLURE_REPORT_URL}" ]; then
    PAYLOAD=$(printf '{"tcrt_run_id":"%s","status":"%s","report_url":"%s"}' \
      "$TCRT_WEBHOOK_RUN_ID" "$TCRT_WEBHOOK_STATUS" "$ALLURE_REPORT_URL")
  else
    PAYLOAD=$(printf '{"tcrt_run_id":"%s","status":"%s"}' \
      "$TCRT_WEBHOOK_RUN_ID" "$TCRT_WEBHOOK_STATUS")
  fi
  curl -fsS -X POST "$TCRT_WEBHOOK_URL" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" \
    || echo "TCRT webhook delivery failed (non-fatal)"
fi
