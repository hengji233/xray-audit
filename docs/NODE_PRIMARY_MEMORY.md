# Node Memory: primary-node

## Snapshot Baseline
- Last updated (UTC): 2026-07-28T13:01:00Z
- Host: omitted from public documentation
- Public domain: omitted from public documentation
- Runtime Linux user: `audituser`
- Deployment root: `/opt/xray-audit` with active link `/opt/xray-audit/current`
- Xray log root: operator-selected; never record a real node path when it identifies infrastructure
- Proxy chain: Cloudflare -> Nginx -> FastAPI (`127.0.0.1:8088`)

## Runtime Paths And Processes
- Access log: `<xray-log-dir>/access.log`
- Error log: `<xray-log-dir>/error.log`
- API command: `/opt/xray-audit/current/venv/bin/xray-audit-api`
- Collector mode: embedded in API by default
- Frontend dist: wheel package `xray_audit/frontend_dist`

## Database And Cache Context
- MySQL database name: masked in public docs
- Redis enabled for realtime aggregates (toggle by runtime config)
- Core validated tables:
  - `audit_admin_users`
  - `audit_runtime_config`
  - `audit_runtime_config_history`
  - `audit_auth_events`
  - `audit_access_events` (v0.2.0 access-only schema)

## Operational Commands
- Install/update: `sudo ./scripts/install.sh --version vX.Y.Z --unattended`
- Service check: `systemctl status xray-audit-api --no-pager`
- Process check:
  - `ps -ef | grep -E 'xray_audit.run_api|xray_audit.collector_runner' | grep -v grep`
- API smoke:
  - `curl -I https://audit.example.invalid/`
  - `curl -s https://audit.example.invalid/api/v1/health`
- Disk check:
  - `df -h`
  - `find / -xdev -type f -size +50M -printf '%s %p\n' 2>/dev/null | sort -nr | head`

## Known Risks And Gotchas
- Memory audit events are intentionally process-local and disappear on restart.
- This node has small root disk; binlog + cache growth can trigger collector stop indirectly.
- Redis write protection on persistence error can break collector health/cache writes.
- User-process/nohup style process management is fragile; prefer systemd or compose restart policies.

## Sensitive Data Policy
- Never store passwords, tokens, or secrets.
- Never record a real production domain or IP in public handoff docs.
- Never include DSN strings with embedded credentials.

## Long-Term Requirements And Recovery
The node follows the five requirements in `AI_CONTEXT.md`: independent Xray
deployment, wheel+systemd, memory/no-SQL default, one embedded-collector API,
and atomic verified updates. Recovery starts from the memory index, inspects
`/opt/xray-audit/current` and systemd without copying secrets, checks loopback health, and
restores the prior version link on failure.

## Milestone Changelog
- 2026-02-18
  - baseline deployment validated (collector + API + dashboard)
- 2026-02-19
  - auth/config features deployed and verified
- 2026-02-20
  - metrics endpoint and timezone query fixes deployed
- 2026-02-25
  - standalone release packaging assets prepared for public repository
- 2026-07-21
  - MySQL remains the node baseline; documented D1 as an alternate backend with a controlled migration runbook
- 2026-07-24
  - implemented memory-first storage, local control persistence, versioned wheel/systemd paths, and context recovery contract
- 2026-07-28
  - wheel/systemd release deployed and verified with memory storage, embedded collection, persistent cursors, TLS reverse proxy, and no SQL dependency
- 2026-07-30
  - Cloudflare Worker Gateway and D1 schema deployed; encrypted D1 credentials activated and persistent audit ingestion verified
- 2026-07-31
  - production API frequency analyzed; D1 indexes and query plans optimized, low-value indexes removed, and dashboard polling reduced from 3 to 15 seconds
