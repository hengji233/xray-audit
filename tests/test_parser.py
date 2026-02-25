from xray_audit.parser import parse_line


def test_parse_access_line() -> None:
    line = "2026/02/18 10:00:00.123456 from 1.2.3.4:12345 accepted tcp:example.com:443 [socks-in -> direct] email: user@example.com"
    ev = parse_line(line)

    assert ev is not None
    assert ev.event_type == "access"
    assert ev.access is not None
    assert ev.access.user_email == "user@example.com"
    assert ev.access.dest_host == "example.com"
    assert ev.access.dest_port == 443
    assert ev.access.is_domain is True


def test_parse_dns_line() -> None:
    line = "2026/02/18 10:00:01.000001 8.8.8.8 got answer: example.com. -> [1.1.1.1, 8.8.8.8] 23ms"
    ev = parse_line(line)

    assert ev is not None
    assert ev.event_type == "dns"
    assert ev.dns is not None
    assert ev.dns.domain == "example.com."
    assert ev.dns.elapsed_ms == 23


def test_parse_unknown_but_valid_timestamp() -> None:
    line = "2026/02/18 10:00:02.000001 something not matching access or dns"
    ev = parse_line(line)

    assert ev is not None
    assert ev.event_type == "unknown"


def test_parse_invalid_line_returns_none() -> None:
    assert parse_line("bad line") is None
