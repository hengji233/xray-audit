# AI Context

## Purpose
This file is the first recovery point for an AI or human maintainer entering
the repository without prior conversation context.

## Long-Term Requirements
These five requirements remain in force across milestones unless the user
explicitly replaces them:

1. Support Linux script installation without requiring SQL to be installed or started; SQL settings must be manageable from the dashboard.
2. Continue evaluating compiled distribution options, while release wheel plus systemd is the current primary host installation path.
3. When SQL is absent, keep the dashboard available and use a small bounded in-memory audit buffer with no persistent audit log.
4. Maintain a documented update architecture with immutable releases, verified artifacts, atomic activation, health checks, and rollback.
5. Keep this recovery document and its linked memory index current so a new AI context can recover requirements, decisions, implementation state, and environment checks by reading the Markdown.

Supporting constraints: keep Xray Audit independent of Xray source changes and
use one embedded-collector API process by default so memory events are visible
to the dashboard. Split workers are opt-in for persistent storage deployments.

Never put a real host, public IP, domain, password, token, cookie, or DSN in
repository documentation. Use `127.0.0.1`, `example.invalid`, and placeholders.

## Current Deployment Contract
- Installer: `scripts/install.sh`
- Standard root: `/opt/xray-audit`
- Release: `/opt/xray-audit/releases/<version>`
- Active link: `/opt/xray-audit/current`
- Runtime environment: `/etc/xray-audit/xray-audit.env` (`0640`, `root:audituser`)
- Mutable data: `/var/lib/xray-audit`
- Service: `xray-audit-api.service`
- Health probe: `http://127.0.0.1:8088/api/v1/health`

The installer accepts a local wheel through `XRAY_AUDIT_WHEEL`; otherwise it
downloads a tagged GitHub release wheel and verifies it against `SHA256SUMS`.

## Implemented Storage Boundary
`memory` is the default audit backend. Audit events use bounded process-local
buffers and are lost on restart. A local SQLite control database below
`AUDIT_DATA_DIR` persists administrators, runtime settings, and encrypted
MySQL/D1 connection settings without persisting audit events. MySQL/D1 can be
tested and activated from the authenticated settings page.

## Recovery Protocol
1. Read this file, `HANDOFF_GLOBAL_MEMORY.md`, the relevant `NODE_*.md`, and `MEMORY_INDEX.json`.
2. Validate the index with `python -m json.tool docs/MEMORY_INDEX.json`.
3. Inspect `git status` and recent history; do not discard unowned changes.
4. Confirm the five long-term requirements before proposing architecture changes.
5. Reconstruct runtime state from systemd, `/opt/xray-audit/current`, release directories, and the protected env file without copying secrets into notes.
6. Verify service status and the loopback health endpoint before and after a change.
7. Update both memory Markdown files and the index after a completed milestone.

If the current release is unhealthy, repoint `/opt/xray-audit/current` atomically to the
last known-good directory, restart `xray-audit-api.service`, and verify health.
Do not delete the failed release until diagnosis is complete.
