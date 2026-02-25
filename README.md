# Xray Audit

No-source-change Xray audit backend and admin frontend.

This repository is designed to be published independently from Xray-core. It consumes Xray runtime logs and does not require shipping Xray source code.

## What It Does

- Tails Xray access/error logs
- Parses access, DNS, and error events
- Stores structured events in MySQL
- Caches realtime aggregates in Redis
- Serves APIs and Vue3 admin dashboard with FastAPI

## Layout

- `xray_audit/`: backend code (collector, API, auth, runtime config)
- `web_admin/`: Vue3 + TS admin frontend
- `sql/`: schema and migrations
- `deploy/`: nginx/systemd/logrotate examples
- `docker/`: Dockerfile and compose deployment
- `docs/`: handoff memory, SOP, compatibility contract
- `tests/`: backend tests

## Quick Start (Local)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m xray_audit.init_db
python -m xray_audit.collector_runner
```

In another shell:

```bash
source .venv/bin/activate
python -m xray_audit.run_api
```

Frontend build:

```bash
cd web_admin
npm install
npm run build
```

## API Surface

- Auth/config:
  - `POST /api/v1/auth/login`
  - `POST /api/v1/auth/logout`
  - `GET /api/v1/auth/me`
  - `POST /api/v1/auth/change-password`
  - `GET /api/v1/config/schema`
  - `GET /api/v1/config/current`
  - `PUT /api/v1/config/current`
  - `GET /api/v1/config/history`
- Audit:
  - `GET /api/v1/events/recent`
  - `GET /api/v1/events/query`
  - `GET /api/v1/errors/query`
  - `GET /api/v1/errors/summary`
  - `GET /api/v1/users/list`
  - `GET /api/v1/users/{email}/visits`
  - `GET /api/v1/domains/top`
  - `GET /api/v1/users/active`
  - `GET /api/v1/stats/summary`
  - `POST /api/v1/geoip/batch`
- Monitoring:
  - `GET /api/v1/health`
  - `GET /api/v1/metrics`

## Docker + GHCR Deployment

Primary release path is `ghcr.io/zcl19/xray-audit:<tag>`.

1) Clone and prepare env:

```bash
git clone https://github.com/zcl19/xray-audit.git
cd xray-audit/docker
cp ../.env.example .env
```

2) Set at least these values in `docker/.env`:

- `AUDIT_MYSQL_HOST`
- `AUDIT_MYSQL_USER`
- `AUDIT_MYSQL_PASSWORD`
- `AUDIT_MYSQL_DB`
- `AUDIT_REDIS_URL`
- `AUDIT_AUTH_JWT_SECRET`
- `AUDIT_HOST_XRAY_LOG_DIR` (for example `/usr/local/x-ui`)

3) Start:

```bash
docker compose up -d
```

4) Upgrade:

```bash
docker compose pull
docker compose up -d
```

5) Rollback:

- Pin `XRAY_AUDIT_IMAGE=ghcr.io/zcl19/xray-audit:vX.Y.Z` in `docker/.env`
- Run `docker compose up -d`

## Migrations

Run all required migrations before app upgrade:

```bash
mysql -uUSER -p DBNAME < sql/migrations/20260218_add_audit_access_indexes.sql
mysql -uUSER -p DBNAME < sql/migrations/20260218_add_geo_cache_table.sql
mysql -uUSER -p DBNAME < sql/migrations/20260218_add_error_and_job_state.sql
mysql -uUSER -p DBNAME < sql/migrations/20260219_add_auth_and_runtime_config.sql
mysql -uUSER -p DBNAME < sql/migrations/20260220_add_error_fulltext_index.sql
mysql -uUSER -p DBNAME < sql/migrations/20260221_add_admin_force_change_flag.sql
```

## CI/CD

- CI workflow: `.github/workflows/ci.yml`
  - `pytest -q`
  - frontend build (`npm install && npm run build`)
  - docs sensitivity gate
- Release workflow: `.github/workflows/release.yml`
  - trigger on tag `v*`
  - multi-arch image publish to GHCR
  - GitHub Release creation

## Standalone Snapshot Export (from monorepo)

If you are operating from `Xray-core/tools/xray_audit` and need a clean standalone repo snapshot:

```bash
mkdir -p ../xray-audit
rsync -av --delete tools/xray_audit/ ../xray-audit/
cd ../xray-audit
git init
git branch -M main
git add .
git commit -m "chore: bootstrap xray-audit from tools/xray_audit snapshot"
```

## Security Notes

- Do not commit real credentials into docs or `.env.example`.
- Keep production deployment pinned to version tags, not bare `latest`.
- Rotate bootstrap admin password after first login.

## Compatibility Contract

See `docs/XRAY_LOG_COMPAT.md`.

Compatibility is maintained using log fixtures and parser tests, not by shipping Xray source code.
