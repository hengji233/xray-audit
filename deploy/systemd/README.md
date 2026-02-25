# Xray Audit systemd Deployment

This folder provides hardened service units for running the stack as `audituser`.

## Preconditions
- Code path: `/home/audituser/xray_audit`
- Python env path: `/home/audituser/xray_audit/.venv`
- Optional env file: `/etc/xray-audit.env`

## Install
```bash
sudo cp tools/xray_audit/deploy/systemd/xray-audit-api.service /etc/systemd/system/
sudo cp tools/xray_audit/deploy/systemd/xray-audit-collector.service /etc/systemd/system/
sudo cp tools/xray_audit/deploy/systemd/xray-audit-ai-summary.service /etc/systemd/system/
sudo systemctl daemon-reload
```

## Enable and Start
```bash
sudo systemctl enable --now xray-audit-api
sudo systemctl enable --now xray-audit-collector
# optional
sudo systemctl enable --now xray-audit-ai-summary
```

## Verify
```bash
sudo systemctl status xray-audit-api --no-pager
sudo systemctl status xray-audit-collector --no-pager
sudo journalctl -u xray-audit-api -n 100 --no-pager
sudo journalctl -u xray-audit-collector -n 100 --no-pager
```

## Migration from nohup
Before enabling systemd, stop old background processes to avoid duplicates:
```bash
pkill -f 'xray_audit.run_api' || true
pkill -f 'xray_audit.collector_runner' || true
pkill -f 'xray_audit.ai_summary' || true
```

