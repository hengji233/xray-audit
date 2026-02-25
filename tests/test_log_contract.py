from __future__ import annotations

from pathlib import Path

from xray_audit.error_parser import parse_error_line
from xray_audit.parser import parse_line


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _lines(name: str) -> list[str]:
    raw = (FIXTURE_DIR / name).read_text(encoding="utf-8")
    return [line for line in raw.splitlines() if line.strip()]


def test_access_fixture_contract() -> None:
    rows = [parse_line(line) for line in _lines("access_samples.log")]

    assert all(row is not None for row in rows)
    assert rows[0].event_type == "access"
    assert rows[0].access is not None
    assert rows[0].access.user_email == "alice@example.com"
    assert rows[0].access.dest_host == "example.com"

    assert rows[1].event_type == "access"
    assert rows[1].access is not None
    assert rows[1].access.status == "rejected"
    assert rows[1].access.is_domain is False

    assert rows[2].event_type == "access"
    assert rows[2].access is not None
    assert rows[2].access.user_email == "unknown"
    assert rows[2].access.dest_host == "updates.example.net"

    assert rows[3].event_type == "unknown"


def test_dns_fixture_contract() -> None:
    rows = [parse_line(line) for line in _lines("dns_samples.log")]

    assert all(row is not None for row in rows)
    assert all(row.event_type == "dns" for row in rows)
    assert rows[0].dns is not None
    assert rows[0].dns.domain == "api.github.com."
    assert rows[0].dns.elapsed_ms == 12

    assert rows[1].dns is not None
    assert rows[1].dns.dns_status == "cache HIT:"
    assert rows[1].dns.elapsed_ms == 0

    assert rows[2].dns is not None
    assert rows[2].dns.error_text == "rcode:3"


def test_error_fixture_contract() -> None:
    rows = [parse_error_line(line) for line in _lines("error_samples.log")]

    assert all(row is not None for row in rows)
    assert rows[0].level == "debug"
    assert rows[0].category in {"routing", "debug_trace"}

    assert rows[1].level == "info"
    assert rows[1].category == "probe_invalid_vless"
    assert rows[1].is_noise is True

    assert rows[2].level == "warning"
    assert rows[2].category in {"auth_error", "runtime_warning"}
    assert rows[2].dest_host == "api.telegram.org"

    assert rows[3].level == "error"
    assert rows[3].category in {"network_timeout", "runtime_error"}
