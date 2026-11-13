"""Exercise the installer with isolated files and simulated system commands."""
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name == "nt", reason="requires Linux shell tools")


def test_install_update_and_rollback(tmp_path):
    source = (Path(__file__).parents[1] / "scripts/install.sh").read_text()
    env_dir = tmp_path / "etc"
    unit = tmp_path / "service"
    root = tmp_path / "releases-root"
    data = tmp_path / "data"
    logs = tmp_path / "logs"
    logs.mkdir()
    script = tmp_path / "install.sh"
    source = source.replace("ENV_DIR=/etc/xray-audit", f"ENV_DIR={env_dir}")
    source = source.replace("UNIT_FILE=/etc/systemd/system/$SERVICE", f"UNIT_FILE={unit}")
    source = source.replace("SERVICE_USER=audituser", "SERVICE_USER=test-user")
    script.write_text(source)
    bindir = tmp_path / "bin"
    bindir.mkdir()

    def command(name, body):
        p = bindir / name
        p.write_text("#!/bin/bash\nset -e\n" + body + "\n")
        p.chmod(0o755)

    command("id", 'if [[ "${1:-}" == -u ]]; then echo 0; else exit 0; fi')
    command("getent", "exit 0")
    command("install", 'args=(); while (($#)); do if [[ $1 == -o || $1 == -g ]]; then shift 2; else args+=("$1"); shift; fi; done; exec /usr/bin/install "${args[@]}"')
    command("systemctl", 'echo "$*" >> "$CALLS"; exit 0')
    command("runuser", 'exit 1')
    command("curl", '[[ ! -f "$FAIL_HEALTH" ]]')
    command("sleep", 'exit 0')
    command("python3", '''
if [[ $1 == -m && $2 == venv ]]; then
  mkdir -p "$3/bin"
  cat > "$3/bin/python" <<'EOF'
#!/bin/bash
exit 0
EOF
  chmod +x "$3/bin/python"
  touch "$3/bin/xray-audit-api"
  chmod +x "$3/bin/xray-audit-api"
fi''')
    wheel = tmp_path / "xray_audit-1.0-py3-none-any.whl"
    wheel.write_text("test")
    calls = tmp_path / "calls"
    fail = tmp_path / "fail"
    env = {**os.environ, "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
           "XRAY_AUDIT_WHEEL": str(wheel), "CALLS": str(calls), "FAIL_HEALTH": str(fail)}

    def run(version, *options):
        return subprocess.run(["bash", str(script), "--version", version, "--unattended", *map(str, options)],
                              env=env, text=True, capture_output=True)

    first = run("1.0", "--install-root", root, "--data-dir", data,
                "--xray-log-dir", logs, "--listen-port", "9001")
    assert first.returncode == 0, first.stderr
    saved_env = (env_dir / "xray-audit.env").read_text()
    saved_unit = unit.read_text()
    assert "AUDIT_API_PORT=9001" in saved_env
    assert "unreadable" in first.stderr
    update = run("2.0")
    assert update.returncode == 0, update.stderr
    assert (env_dir / "xray-audit.env").read_text() == saved_env
    assert (root / "current").resolve() == root / "releases/2.0"
    fail.touch()
    failed = run("3.0", "--listen-port", "9002")
    assert failed.returncode != 0
    assert (root / "current").resolve() == root / "releases/2.0"
    assert (env_dir / "xray-audit.env").read_text() == saved_env
    assert unit.read_text() == saved_unit
    assert "daemon-reload" in calls.read_text()
    incomplete = root / "releases/4.0/venv"
    incomplete.mkdir(parents=True)
    assert run("4.0").returncode != 0
    assert (root / "current").resolve() == root / "releases/2.0"
