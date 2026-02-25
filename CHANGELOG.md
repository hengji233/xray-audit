# Changelog

All notable changes to this project will be documented in this file.

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
