#!/bin/sh
set -eu

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-9999}"
UVICORN_LOG_LEVEL="${UVICORN_LOG_LEVEL:-info}"
UVICORN_PROXY_HEADERS="${UVICORN_PROXY_HEADERS:-1}"
FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-*}"
WEB_CONCURRENCY="${WEB_CONCURRENCY:-1}"
SKIP_DATABASE_BOOTSTRAP="${SKIP_DATABASE_BOOTSTRAP:-0}"

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
if [ "$WEB_CONCURRENCY" != "1" ]; then
    set -- "$@" --workers "$WEB_CONCURRENCY"
fi

exec "$@"
