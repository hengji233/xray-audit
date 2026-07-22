# Docker Deployment

This folder contains production-oriented container assets.

## Files
- `Dockerfile`: multi-stage build (frontend + backend runtime)
- `docker-compose.yml`: `api`, `collector`, optional `ai_summary`
- `entrypoint.sh`: optional auto-migrate hook
- `collector_healthcheck.py`: collector health probe via Redis state key

## Run

```bash
cp ../.env.example .env
# edit .env values (storage, Redis, auth, and log path mapping)
docker compose up -d
```

For MySQL, keep `AUDIT_STORAGE_BACKEND=mysql` and configure the `AUDIT_MYSQL_*`
values. For D1, follow `docs/D1_DEPLOYMENT.md`, then set
`AUDIT_STORAGE_BACKEND=d1`, `AUDIT_D1_GATEWAY_URL`, and
`AUDIT_D1_GATEWAY_TOKEN`. The token is a secret and must not be baked into the
image or committed in `.env`.

Redis is optional for both backends. Keep it enabled when low-latency dashboard
aggregates are useful; set `AUDIT_REDIS_ENABLED=false` when no reachable Redis
service is available. D1 does not replace Redis.

## Upgrade

```bash
docker compose pull
docker compose up -d
```

## Optional auto-migrate

Set in `.env`:

```bash
AUDIT_AUTO_MIGRATE=true
```

Use with caution on production and still keep SQL migration review in release process.
This hook runs Python database initialization. D1 schema migrations must instead
be applied from `cloudflare_worker` with Wrangler before containers start.
