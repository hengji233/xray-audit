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
# edit .env values (db/redis/jwt and log path mapping)
docker compose up -d
```

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
