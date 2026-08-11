# Cloudflare D1 Deployment

This deployment mode keeps the collector, API, and optional Redis service on
the Python host. Python calls an authenticated Cloudflare Worker, and the Worker
performs an allowlisted set of operations against D1. It does not expose a raw
SQL endpoint.

## Plan And Limits

Use Workers Paid for production. Continuous ingestion is a poor fit for the
free plan's smaller database allowance and tighter daily usage budget. Confirm
current Cloudflare pricing and limits before rollout; Cloudflare can change
them independently of this project.

Design and operate within these D1 constraints:

- Maximum database size: 10 GB per database on paid plans and 500 MB on the free plan.
- Maximum bound parameters per SQL statement: 100.
- Each D1 database processes queries on a single thread. Long scans and large write bursts serialize other work.
- The gateway limits normal ingestion and migration imports to 50 rows per request.
- Retention is mandatory for sustained audit traffic. Estimate growth from a representative MySQL period before choosing `AUDIT_RETENTION_DAYS`.

D1 is suitable for modest audit workloads that benefit from a managed SQLite
database near the Worker. Keep MySQL when the projected retained data exceeds
the limit, write concurrency is high, or queries require MySQL-specific
features such as FULLTEXT behavior.

## Prerequisites

- A Cloudflare account with Workers and D1 enabled; Workers Paid is recommended.
- Node.js 22 or later and npm.
- Wrangler authentication with permission to manage Workers, D1, migrations, and secrets.
- A high-entropy gateway token generated with a cryptographically secure password manager or secret generator.
- The Python application host can make outbound HTTPS requests to the deployed Worker.

Run all Wrangler commands from `cloudflare_worker`.

## Create And Bind D1

```bash
npm install
npx wrangler login
npx wrangler d1 create xray-audit
```

Copy only the returned D1 database identifier into the `database_id` field in
`wrangler.jsonc`. The `binding` must remain `DB`, the name expected by the
Worker. A database ID is configuration, not an authentication secret, but it
should still not be confused with an API token.

For separate staging and production environments, use separate D1 databases,
Worker names, bindings, and secrets. Never test migrations against production.

## Set The Gateway Secret

```bash
npx wrangler secret put GATEWAY_TOKEN
```

Enter the token only at Wrangler's prompt. Do not put it in `wrangler.jsonc`, a
shell command argument, documentation, container image, or source control. The
same value is later supplied to Python as `AUDIT_D1_GATEWAY_TOKEN` through a
protected runtime environment file or secret manager. Use at least 32 random
characters; the Worker fails closed when the secret is missing or too short.

## Validate And Apply Migrations

Apply migrations locally first, then run the Worker checks:

```bash
npx wrangler d1 migrations apply xray-audit --local
npm run typecheck
npm test
```

Review the pending migration list and apply it remotely:

```bash
npx wrangler d1 migrations list xray-audit --remote
npx wrangler d1 migrations apply xray-audit --remote
```

Wrangler tracks applied migrations. Do not edit an already-applied migration;
add a new numbered migration instead. `python -m xray_audit.init_db` does not
provision D1 and is not a substitute for these commands.

## Deploy And Verify The Worker

```bash
npm run deploy
curl --fail --silent --show-error https://YOUR-WORKER-URL.example/health
```

Replace the placeholder with the deployed Worker URL. The health route proves
that the Worker runs but does not authenticate or query D1. Verify D1 through
the Python application after configuring it; avoid placing bearer tokens in
shell history through ad hoc `curl` commands.

## Configure Python

Set these values in the Python runtime environment:

```dotenv
AUDIT_STORAGE_BACKEND=d1
AUDIT_D1_GATEWAY_URL=https://YOUR-WORKER-URL.example
AUDIT_D1_GATEWAY_TOKEN=
AUDIT_D1_TIMEOUT_SECONDS=10
AUDIT_D1_BATCH_SIZE=50
AUDIT_D1_MAX_RETRIES=3
```

Populate the token only in the protected deployed environment. Keep the batch
size at or below 50. The URL must be the Worker origin without a trailing
storage operation path. MySQL variables are ignored in D1 mode but may remain
available for rollback.

Start the API and collector normally. Confirm `/api/v1/health` reports
`storage_backend` as `d1`, exercise recent events and a bounded date query, and
watch collector write-failure and lag metrics. A successful new event confirms
that the complete collector, Worker, and D1 write path works.

## Redis Policy

Redis is optional and independent of D1:

- Keep `AUDIT_REDIS_ENABLED=true` when Redis is reliable and low-latency top-domain and active-user views are desired.
- Set `AUDIT_REDIS_ENABLED=false` when Redis is unavailable; the application falls back to storage-backed queries where supported.
- Do not treat Redis as the source of truth or as a D1 backup.
- Protect Redis from public access, enforce authentication where supported, and monitor memory and persistence failures.

## Docker And systemd

For Docker, put the D1 variables in `docker/.env`; Compose passes them to the
API and collector. Do not enable `AUDIT_AUTO_MIGRATE` expecting D1 migrations:
apply those with Wrangler before `docker compose up -d`. Avoid embedding the
gateway token in the image or Compose YAML.

For systemd, place secrets in a root-owned environment file such as
`/etc/xray-audit.env`, set permissions to `0600`, and reference it with
`EnvironmentFile=` from both API and collector units. After changing storage
configuration, run `systemctl daemon-reload` if unit files changed, restart both
services, and inspect their journals. Never run MySQL and D1 collectors against
the same log file during a cutover.

## Security And Cost

- The gateway bearer token grants application-level read and write access. Rotate it after suspected exposure and update Worker and Python secrets together.
- Keep the Worker route HTTPS-only. Do not log authorization headers or request bodies containing sensitive audit data.
- Restrict Cloudflare account roles and CI credentials to the minimum resources required. Use separate deployment credentials from the gateway token.
- The unauthenticated `/health` response contains no D1 data; all `/v1/storage/*` operations require the bearer token.
- Audit records can include user identifiers, source addresses, destinations, and raw log lines. Apply retention and access policies appropriate to that data.
- Cost is driven by Workers requests and CPU plus D1 rows read, rows written, and storage. Ingestion request count is approximately events divided by the configured batch size, before retries.
- Indexed, bounded time queries cost less and block the single-threaded database for less time. Avoid broad dashboard ranges and monitor database size and usage in Cloudflare.
- Keep dashboard polling conservative. Overview refreshes every 15 seconds;
  event and error tables default to manual refresh. Production access-log
  analysis showed the three Overview aggregates accounted for about 98.8% of
  dashboard API calls before this change.
- D1 indexes are a write-cost tradeoff. Migrations `0002` and `0003` replace
  low-value indexes with time-bounded covering indexes. Do not add an index
  without checking both `EXPLAIN QUERY PLAN` and the extra rows written for
  every ingested event.
- On the verified workload, forcing `active_users` to `idx_access_time` reduced
  a representative query from 25,392 rows read to 8; Top Domains read 3 rows
  and the five-minute summary read 63 rows after optimization.
- The Workers Free write limit can still be exceeded by the event volume alone.
  Index tuning does not replace event sampling, category filtering, aggregation,
  or a paid plan when logical audit writes remain above the daily allowance.

## Operational Rollback

Worker code can be rolled back to a previously tested deployment, but D1 schema
migrations should be treated as forward-only. Before a schema change, export a
D1 backup or confirm the available Time Travel recovery window for the account.
For a storage-backend rollback to MySQL, follow the rollback section in
`MYSQL_TO_D1_MIGRATION.md`; data written only to D1 after cutover must be
reconciled before MySQL can again be authoritative.
