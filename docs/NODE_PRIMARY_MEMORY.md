# Node Memory: primary-node

## Snapshot Baseline
- Last updated (UTC): 2026-02-25T08:00:00Z
- Host (masked): `38.55.*.*:22`
- Public domain (masked): `audit.example.com`
- Runtime Linux user: `audituser`
- Deployment root: `/home/audituser/xray_audit`
- Xray log root: `/usr/local/x-ui`
- Proxy chain: Cloudflare -> Nginx -> FastAPI (`127.0.0.1:8088`)

## Runtime Paths And Processes
- Access log: `/usr/local/x-ui/access.log`
- Error log: `/usr/local/x-ui/error.log`
- API command: `.venv/bin/python -m xray_audit.run_api`
- Collector command: `.venv/bin/python -m xray_audit.collector_runner`
- Frontend dist: `/home/audituser/xray_audit/xray_audit/frontend_dist`

## Database And Cache Context
- MySQL database name: masked in public docs
- Redis enabled for realtime aggregates (toggle by runtime config)
- Core validated tables:
  - `audit_admin_users`
  - `audit_runtime_config`
  - `audit_runtime_config_history`
  - `audit_auth_events`
  - `audit_error_events`

## Operational Commands
- Process check:
  - `ps -ef | grep -E 'xray_audit.run_api|xray_audit.collector_runner' | grep -v grep`
- API smoke:
  - `curl -I https://audit.example.com/`
  - `curl -s https://audit.example.com/api/v1/health`
- Disk check:
  - `df -h`
  - `find / -xdev -type f -size +50M -printf '%s %p\n' 2>/dev/null | sort -nr | head`

## Known Risks And Gotchas
- This node has small root disk; binlog + cache growth can trigger collector stop indirectly.
- Redis write protection on persistence error can break collector health/cache writes.
- User-process/nohup style process management is fragile; prefer systemd or compose restart policies.

## Sensitive Data Policy (Partial Masking)
- Never store full passwords/tokens/secrets.
- Keep domain/IP masked in public handoff docs.
- Never include DSN strings with embedded credentials.

## Milestone Changelog
- 2026-02-18
  - baseline deployment validated (collector + API + dashboard)
- 2026-02-19
  - auth/config features deployed and verified
- 2026-02-20
  - metrics endpoint and timezone query fixes deployed
- 2026-02-25
  - standalone release packaging assets prepared for public repository
