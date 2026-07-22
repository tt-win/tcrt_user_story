## 1. Build Context and Runtime Image

- [ ] 1.1 擴充 `.dockerignore` 與 `.gitignore`，排除真實 env/config、backup、log、key/cert 與本機工具產物 → verify: automated ignore-contract test + `git check-ignore`
- [ ] 1.2 將 runtime COPY 改為 `--chown` 並移除整體 `chown -R` layer → verify: Dockerfile static test + `docker history`
- [ ] 1.3 依 PostgreSQL 官方 PGDG repository 安裝 `postgresql-client-16`，build 時驗證 `pg_dump`/`pg_restore` major → verify: clean image build + version commands

## 2. Compose Safety and Portability

- [ ] 2.1 讓 app Compose 對必要 storage paths fail fast，固定 container port 9999，並新增可設定的 loopback published host → verify: `docker compose config` positive/negative cases
- [ ] 2.2 新增可選 config override Compose，以 long bind syntax 與 `create_host_path: false` 掛載設定 → verify: base config succeeds without config；override missing/valid source cases
- [ ] 2.3 新增 Linux `host-gateway` mapping，將 proxy headers 改為 explicit trust，並限制 disposable DB published ports 到 loopback → verify: normalized Compose assertions

## 3. Configuration and Documentation

- [ ] 3.1 更新 `.env.docker.example`、`.env.example` 的 port、proxy、config override 與 host bind 說明 → verify: keys/comments align with Compose
- [ ] 3.2 修正 README 與 Docker setup 指令，統一使用 `--env-file .env.docker` 並記錄 config override／Linux host gateway／公開服務 opt-in → verify: all Docker app commands searched and reviewed
- [ ] 3.3 修正 database cutover 文件的 PostgreSQL client 版本敘述 → verify: docs no longer claim Bookworm default client matches PG16

## 4. Automated Verification

- [ ] 4.1 新增 Docker deployment static regression tests，涵蓋 ignore、port、proxy、config override、host gateway 與 PG client major contract → verify: targeted pytest passes
- [ ] 4.2 執行 shell syntax、Compose config、OpenSpec strict validation、targeted pytest 與相關 lint → verify: commands pass without reading real secrets
- [ ] 4.3 以乾淨 context build image，驗證 final user、healthcheck、PG16 client、敏感路徑缺漏與 layer size改善 → verify: Docker inspect/history and in-image assertions
- [ ] 4.4 以 disposable PostgreSQL 16 執行 backup/restore smoke；若本機環境不適合則記錄待驗證理由 → verify: dump and restore command evidence or explicit pending result
