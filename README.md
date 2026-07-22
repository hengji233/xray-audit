# Xray Audit

No-source-change Xray audit backend and admin frontend.

This repository is designed to be published independently from Xray-core. It consumes Xray runtime logs and does not require shipping Xray source code.

## What It Does

- Tails Xray access/error logs
- Parses access, DNS, and error events
- Stores structured events in MySQL or Cloudflare D1 through an authenticated Worker gateway
- Caches realtime aggregates in Redis
- Serves APIs and Vue3 admin dashboard with FastAPI

## Layout

- `xray_audit/`: backend code (collector, API, auth, runtime config)
- `web_admin/`: Vue3 + TS admin frontend
- `sql/`: schema and migrations
- `deploy/`: nginx/systemd/logrotate examples
- `docker/`: Dockerfile and compose deployment
- `cloudflare_worker/`: authenticated D1 storage gateway and D1 schema migrations
- `docs/`: handoff memory, SOP, compatibility contract
- `tests/`: backend tests

## Quick Start (MySQL)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Set the blank database and auth secrets in .env.
# Keep AUDIT_STORAGE_BACKEND=mysql.
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

## Quick Start (Cloudflare D1)

D1 is accessed through the Worker gateway; the Python processes never connect
to D1 directly. A Workers Paid plan is recommended for production because it
provides the practical capacity and operational headroom expected by a
continuous audit workload.

```bash
cd cloudflare_worker
npm install
npx wrangler login
npx wrangler d1 create xray-audit
# Put the returned database_id in wrangler.jsonc.
npx wrangler secret put GATEWAY_TOKEN
npx wrangler d1 migrations apply xray-audit --remote
npm run deploy
```

Configure Python with `AUDIT_STORAGE_BACKEND=d1`, the deployed
`AUDIT_D1_GATEWAY_URL`, and the same secret in `AUDIT_D1_GATEWAY_TOKEN`, then
start the collector and API as shown above. Do not run `xray_audit.init_db` for
D1. See [D1 deployment](docs/D1_DEPLOYMENT.md) for limits, verification,
security, Redis, Docker, and systemd guidance.

MySQL migration supports resumable bounded copies with `--start-pk` and
`--end-pk`; see [MySQL to D1 migration](docs/MYSQL_TO_D1_MIGRATION.md) before
moving production data.

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

- `AUDIT_STORAGE_BACKEND` and the matching `AUDIT_MYSQL_*` or `AUDIT_D1_*` values
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

## Database Migrations

Run all required migrations before app upgrade:

```bash
mysql -uUSER -p DBNAME < sql/migrations/20260218_add_audit_access_indexes.sql
mysql -uUSER -p DBNAME < sql/migrations/20260218_add_geo_cache_table.sql
mysql -uUSER -p DBNAME < sql/migrations/20260218_add_error_and_job_state.sql
mysql -uUSER -p DBNAME < sql/migrations/20260219_add_auth_and_runtime_config.sql
mysql -uUSER -p DBNAME < sql/migrations/20260220_add_error_fulltext_index.sql
mysql -uUSER -p DBNAME < sql/migrations/20260221_add_admin_force_change_flag.sql
```

For D1, apply the Worker migrations before deploying the corresponding Python
version:

```bash
cd cloudflare_worker
npx wrangler d1 migrations apply xray-audit --remote
```

For an existing MySQL installation, follow
[MySQL to D1 migration](docs/MYSQL_TO_D1_MIGRATION.md). Do not point MySQL and
D1 collectors at the same log file concurrently.

## CI/CD

- CI workflow: `.github/workflows/ci.yml`
  - `pytest -q`
  - frontend build (`npm install && npm run build`)
  - D1 gateway typecheck and tests
  - D1 migrations applied to a local Wrangler database
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
- Store the Worker gateway token only in Wrangler secrets and the protected Python runtime environment.

## Compatibility Contract

See `docs/XRAY_LOG_COMPAT.md`.

Compatibility is maintained using log fixtures and parser tests, not by shipping Xray source code.
