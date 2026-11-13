# Update Architecture

## Release Model
Each version has an immutable venv under `/opt/xray-audit/releases/<version>`. The
`/opt/xray-audit/current` symlink selects the running version, while mutable state and
configuration live outside releases. Reinstalling into a partially existing
version directory is rejected.

## Update Procedure
```bash
sudo ./scripts/install.sh --version vNEXT --unattended
```

The installer verifies remote artifacts, prepares the new release before
changing `current`, preserves existing secrets, atomically switches the link,
restarts systemd, and polls the health endpoint for up to 30 seconds.

Existing configuration is preserved unless the corresponding command-line option
is supplied. A release without its completion marker is rejected; inspect and
remove an incomplete release directory before retrying. A failed switch restores
the previous environment, systemd unit and release link and reloads systemd.

## Failure And Rollback
On failed health, the installer stops the failed service and restores the
previous symlink when one existed. It then attempts to restart the prior
release. Diagnose with:

```bash
sudo systemctl status xray-audit-api --no-pager
sudo journalctl -u xray-audit-api -n 100 --no-pager
readlink -f /opt/xray-audit/current
```

Manual rollback uses a temporary symlink plus atomic rename:

```bash
sudo ln -s /opt/xray-audit/releases/PREVIOUS /opt/xray-audit/.current.rollback
sudo mv -Tf /opt/xray-audit/.current.rollback /opt/xray-audit/current
sudo systemctl restart xray-audit-api
curl -fsS http://127.0.0.1:8088/api/v1/health
```

Do not mutate an existing release venv. Do not remove the previous known-good
release until the new version has passed operational observation. The local
control database schema must remain backward compatible. MySQL and D1 schema
migrations require their own backup and forward-compatible rollback procedure.

## Release Assets
Tag workflow output contains one wheel and `SHA256SUMS`. The frontend is built
before wheel creation. GitHub Release assets and the container release share
the same tag, but host updates must remain pinned to explicit versions.
