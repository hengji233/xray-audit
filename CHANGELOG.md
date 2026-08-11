# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [0.2.0] - 2026-08-10

### Changed
- Persist only parsed access events across MySQL, D1, and memory backends.
- Replace raw/access joins with one compact access table and three query indexes.
- Keep recent error events only in a bounded process-local ring buffer.
- Stop persisting DNS, unknown, raw log text, and error log records.
- Add collector backpressure so storage outages cannot grow pending batches without bound.
- Mark error API responses as non-persistent and update the dashboard contract.

### Operations
- Existing audit event history may be discarded when applying the v0.2.0 schema.
- Rebuild the MySQL `xray_audit` database from `sql/schema.sql` before activating v0.2.0.
- Apply D1 migration `0004_access_storage_v2.sql` before deploying the v0.2.0 Worker.
- The standalone AI error-summary worker is unsupported because errors are process-local.

### Added
- Selectable MySQL or Cloudflare D1 storage backends.
- Authenticated Cloudflare Worker gateway with a fixed storage operation allowlist and D1 schema migrations.
- Resumable, bounded MySQL-to-D1 migration tooling with count verification.
- Cloudflare D1 deployment and MySQL-to-D1 migration runbooks.
- CI type checking, tests, and local migration application for the D1 gateway.

### Changed
- Quick-start, environment, Docker, systemd, and handoff documentation now covers MySQL and D1 storage modes.
- Example secret fields are blank so the repository does not provide deployable credentials.

## [0.1.0] - 2026-02-25

### Added
- Built-in auth with JWT HttpOnly cookie and forced first-login password change.
- Runtime config center (`env` defaults + DB overrides) with audit history.
- Errors pipeline (parse, query, summary) and Errors page in frontend.
- GeoIP batch lookup endpoint with cache.
- Monitoring endpoints (`/api/v1/health`, `/api/v1/metrics`).
- Docker packaging (`docker/Dockerfile`, `docker/docker-compose.yml`).
- GitHub workflows for CI, GHCR release, and CodeQL.
- Docs memory index and handoff SOP.

### Changed
- Retention cleanup now includes auth/config history tables.
- Error keyword query uses FULLTEXT-first with LIKE fallback.
- Frontend date-range query conversion normalized to UTC.

### Notes
- This release is the standalone snapshot baseline for the public `zcl19/xray-audit` repository.
