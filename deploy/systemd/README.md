# Xray Audit systemd Deployment

This folder provides hardened service units for wheel installations running as `audituser`.

## Preconditions
- Current release link: `/opt/xray-audit/current`
- Python env path: `/opt/xray-audit/current/venv`
- Required env file: `/etc/xray-audit/xray-audit.env`
- Writable data path: `/var/lib/xray-audit`
- Read-only Xray log path: `/var/log/xray`

## Install
```bash
sudo cp deploy/systemd/xray-audit-api.service /etc/systemd/system/
sudo systemctl daemon-reload
```

## Enable and Start
```bash
sudo systemctl enable --now xray-audit-api
```

The API unit is the default topology and embeds collection through
`AUDIT_COLLECTOR_EMBEDDED=true`. Do not also enable the collector unit. The
collector and AI summary units remain examples for intentional split-process
deployments and require equivalent hardening for their writable paths.

## Verify
```bash
sudo systemctl status xray-audit-api --no-pager
sudo journalctl -u xray-audit-api -n 100 --no-pager
curl -fsS http://127.0.0.1:8088/api/v1/health
```

## Migration from nohup
Before enabling systemd, stop old background processes to avoid duplicates:
```bash
pkill -f 'xray_audit.run_api' || true
pkill -f 'xray_audit.collector_runner' || true # embedded API replaces it
pkill -f 'xray_audit.ai_summary' || true
```

