# Xray Audit Global Handoff Memory

## Snapshot Baseline
- Last updated (UTC): 2026-02-25T08:00:00Z
- Scope: standalone Xray audit stack (Python + MySQL + Redis + Vue3)
- Canonical repository: `zcl19/xray-audit`
- Core goal: user-level access/error audit with near-real-time dashboard and searchable history
- Deployment topology: Cloudflare -> Nginx -> FastAPI (`127.0.0.1:8088`)

## Architecture And Responsibilities
- `xray_audit.collector_runner`
  - tails Xray access/error logs
  - parses structured events
  - persists to MySQL
  - updates Redis near-realtime aggregates
  - executes retention cleanup
- `xray_audit.run_api` (FastAPI)
  - serves REST APIs under `/api/v1/*`
  - serves SPA assets from `xray_audit/frontend_dist`
  - enforces built-in auth using JWT HttpOnly cookie
  - exposes `/api/v1/health` and `/api/v1/metrics`
- `web_admin` (Vue3 + TS)
  - pages: Overview / Events / Errors / Users / Settings / System / Login
  - uses relative `/api/v1/*` paths for reverse-proxy compatibility

## Runtime Data Model
- Access pipeline:
  - `audit_raw_events`
  - `audit_access_events`
  - `audit_dns_events`
- Error pipeline:
  - `audit_error_events`
  - `audit_job_state`
- Runtime support:
  - `collector_state`
  - `audit_ip_geo_cache`
  - `audit_admin_users`
  - `audit_runtime_config`
  - `audit_runtime_config_history`
  - `audit_auth_events`

## Public API Surface
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

## Operational Commands
- Install and bootstrap:
  - `python3 -m venv .venv`
  - `source .venv/bin/activate`
  - `pip install -r requirements.txt`
  - `python -m xray_audit.init_db`
- Run processes:
  - `python -m xray_audit.collector_runner`
  - `python -m xray_audit.run_api`
  - `python -m xray_audit.ai_summary` (optional)
- Frontend build:
  - `cd web_admin && npm install && npm run build`
- Docker deployment:
  - `cd docker && docker compose up -d`

## Known Risks And Gotchas
- Under extreme load, Xray logging may drop lines.
- If disk usage reaches 100%, Redis persistence can fail and block writes.
- If collector is not managed by systemd/compose restart policy, crashes can stop ingestion.
- Cloudflare/browser cache can delay `index.html` updates.

## Conventions
- Time handling:
  - UI date-range input is local time.
  - API query timestamps are normalized to UTC ISO strings.
- Sensitivity policy:
  - partial masking only; no plaintext secrets in docs.
- Release policy:
  - version tags for production, avoid unpinned `latest` in fixed environments.

## Milestone Changelog
- 2026-02-18
  - baseline audit collector + API + dashboard online
- 2026-02-19
  - built-in auth and runtime config center added
- 2026-02-20
  - timezone query fix + health metrics + FULLTEXT optimization
- 2026-02-25
  - standalone-public packaging baseline added (`docker`, GHCR release workflow, compatibility contract docs)
