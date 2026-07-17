#!/bin/sh
set -eu

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-9999}"
UVICORN_LOG_LEVEL="${UVICORN_LOG_LEVEL:-info}"
UVICORN_PROXY_HEADERS="${UVICORN_PROXY_HEADERS:-1}"
FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-*}"
SKIP_DATABASE_BOOTSTRAP="${SKIP_DATABASE_BOOTSTRAP:-0}"

# Default worker count from the *resolved* main DB engine (env DATABASE_URL or
# config.yaml) when WEB_CONCURRENCY is unset/empty: SQLite → 1 (single-file DB);
# MySQL / PostgreSQL → 5. Explicit WEB_CONCURRENCY always wins.
# The Python helper is the single source of truth shared with the runtime settings
# API; the env-pattern case below is only a fallback when the helper cannot run.
_default_web_concurrency() {
    if value="$(uv run python scripts/print_inferred_web_concurrency.py 2>/dev/null)" \
        && [ -n "$value" ]; then
        echo "$value"
        return
    fi
    case "${DATABASE_URL:-}" in
        mysql://*|mysql+*|postgresql://*|postgresql+*|postgres://*|postgres+*)
            echo 5
            ;;
        *)
            echo 1
            ;;
    esac
}
# Keep WEB_CONCURRENCY itself untouched: overwriting an exported empty string
# would leak the resolved number into the uvicorn child process, and the runtime
# settings API would then misreport source=configured instead of inferred_default.
if [ -z "${WEB_CONCURRENCY:-}" ]; then
    RESOLVED_WEB_CONCURRENCY="$(_default_web_concurrency)"
else
    RESOLVED_WEB_CONCURRENCY="$WEB_CONCURRENCY"
fi

if [ "$SKIP_DATABASE_BOOTSTRAP" != "1" ]; then
    # 外部 DB 服務（docker-compose.app.yml 本身不含 DB，見檔頭註解）在容器啟動當下
    # 可能還沒開始接受連線（例如另一個 compose stack 剛啟動、managed DB 剛建立）。
    # database_init.py 的 exit code 不區分「連不上」與「migration 本身失敗」，所以這裡
    # 用有上限的重試涵蓋開機當下的短暫競態，而不是無限重試——真正持續性的失敗
    # （帳密錯誤、migration bug）重試到上限後一樣會失敗並印出最後一次的錯誤訊息；
    # 跨容器重建的重試上限交給 database_init.py 自己的 BOOTSTRAP_MAX_UPGRADE_ATTEMPTS
    # 與 failure marker 機制處理，這裡只管本次啟動內的連線競態。
    BOOTSTRAP_WAIT_ATTEMPTS="${BOOTSTRAP_WAIT_ATTEMPTS:-10}"
    BOOTSTRAP_WAIT_SECONDS="${BOOTSTRAP_WAIT_SECONDS:-3}"
    attempt=1
    while true; do
        echo "Running database bootstrap (attempt ${attempt}/${BOOTSTRAP_WAIT_ATTEMPTS})..."
        if uv run python database_init.py; then
            break
        fi
        if [ "$attempt" -ge "$BOOTSTRAP_WAIT_ATTEMPTS" ]; then
            echo "Database bootstrap failed after ${BOOTSTRAP_WAIT_ATTEMPTS} attempts. Aborting." >&2
            exit 1
        fi
        echo "Database bootstrap failed; retrying in ${BOOTSTRAP_WAIT_SECONDS}s (could be the DB service still starting up)..." >&2
        sleep "$BOOTSTRAP_WAIT_SECONDS"
        attempt=$((attempt + 1))
    done
else
    echo "Skipping database bootstrap because SKIP_DATABASE_BOOTSTRAP=1"
fi

set -- uv run uvicorn app.main:app --host "$HOST" --port "$PORT" --log-level "$UVICORN_LOG_LEVEL"

if [ "$UVICORN_PROXY_HEADERS" = "1" ]; then
    set -- "$@" --proxy-headers --forwarded-allow-ips "$FORWARDED_ALLOW_IPS"
fi

# 背景服務（排程器 / automation ticker）已改由 DB advisory-lock leader 選舉確保跨 worker/副本
# 僅單一執行，故 WEB_CONCURRENCY 可 >1；此處據以啟用多 worker。
echo "WEB_CONCURRENCY=${RESOLVED_WEB_CONCURRENCY} (resolved main DB engine default applies only when unset)"
if [ "$RESOLVED_WEB_CONCURRENCY" != "1" ]; then
    set -- "$@" --workers "$RESOLVED_WEB_CONCURRENCY"
fi

exec "$@"
