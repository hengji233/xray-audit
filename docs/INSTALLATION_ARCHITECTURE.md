# Installation Architecture

## Scope
`scripts/install.sh` installs a release wheel on a Linux host managed by
systemd. It creates no SQL database, applies no SQL schema, and does not alter
an Xray installation.

## Preconditions
- Linux with systemd and root access
- Bash, Python 3.10+, `venv`, `curl`, and `sha256sum`
- Xray access/error logs readable by `audituser`
- Outbound GitHub access unless `XRAY_AUDIT_WHEEL` names a local wheel

## Example
```bash
sudo ./scripts/install.sh --version v0.2.0 --unattended
```

Local artifact installation:

```bash
sudo XRAY_AUDIT_WHEEL=/srv/releases/xray_audit-0.2.0-py3-none-any.whl \
  ./scripts/install.sh --version 0.2.0 --unattended
```

Relevant options are `--install-root`, `--data-dir`, `--listen-host`,
`--listen-port`, `--xray-log-dir`, `--no-start`, and `--unattended`. Paths must
be absolute. The listener defaults to loopback.

## Installation Flow
1. Validate root privileges, options, and host commands.
2. Resolve the requested release or copy `XRAY_AUDIT_WHEEL`.
3. Verify downloaded wheel bytes against the release `SHA256SUMS`.
4. Create the system user and protected runtime directories.
5. Build a venv in `/opt/xray-audit/releases/<version>` and install the wheel.
6. Generate cryptographically random auth/bootstrap values without logging the JWT secret.
7. Preserve existing secrets during an update and install the env file as `root:audituser` mode `0640`.
8. Generate the systemd unit for the selected paths.
9. Atomically replace `/opt/xray-audit/current`, restart, and poll health.
10. Restore the previous link if health fails.

The bootstrap password is shown once only on first installation. It must be
rotated at first login. An operator using `--no-start` is responsible for the
first start and health check.

## Packaging Contract
The release workflow builds the frontend before the wheel. Runtime dependencies
and `xray_audit/frontend_dist` package data are declared in `pyproject.toml`.
Release validation must inspect the wheel and smoke-test its console entrypoint.
