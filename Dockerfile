# syntax=docker/dockerfile:1

# ---- builder stage：安裝 build-essential 並建立 venv，最終映像不含編譯工具鏈 ----
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# ---- runtime stage：僅含執行期所需（venv + 應用程式 + curl），非 root 執行 ----
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# curl 供 HEALTHCHECK 使用；default-mysql-client/postgresql-client 供開機升版前備份/回退
# （mysqldump/mysql、pg_dump/pg_restore）使用；建立固定 uid/gid 的非 root 使用者（10001）
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl default-mysql-client postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --home-dir /app --shell /usr/sbin/nologin app

# 複製 builder 階段建好的 venv，以及應用程式碼（keys/、*.db、.venv 等已由 .dockerignore 排除）
COPY . .
COPY --from=builder /app/.venv /app/.venv

# 預建金鑰目錄與升版前備份目錄並把 /app 交給非 root 使用者；
# named volume 掛到 /app/keys、/app/db_backups 時會沿用此 ownership
RUN chmod +x docker/app-entrypoint.sh \
    && mkdir -p /app/keys /app/db_backups \
    && chown -R app:app /app

USER app

EXPOSE 9999

# 映像層級健康檢查（不僅依賴 compose）
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=12 \
    CMD curl -fsS http://127.0.0.1:9999/health || exit 1

ENTRYPOINT ["./docker/app-entrypoint.sh"]
