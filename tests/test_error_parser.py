from xray_audit.error_parser import level_rank, parse_error_line


def test_parse_error_line_with_session_and_component() -> None:
    line = "2026/02/18 10:11:55.397153 [Warning] [12345] proxy/vless/inbound: received request for tcp:example.com:443"
    ev = parse_error_line(line)
    assert ev is not None
    assert ev.level == "warning"
    assert ev.session_id == 12345
    assert ev.component == "proxy/vless/inbound"
    assert ev.dest_raw == "tcp:example.com:443"
    assert ev.dest_host == "example.com"
    assert ev.dest_port == 443


def test_parse_probe_invalid_vless_noise() -> None:
    line = "2026/02/18 10:11:55.397153 [Info] proxy/vless/encoding: invalid request version from 1.2.3.4:2222"
    ev = parse_error_line(line)
    assert ev is not None
    assert ev.category == "probe_invalid_vless"
    assert ev.is_noise is True


def test_level_rank_order() -> None:
    assert level_rank("debug") < level_rank("info")
    assert level_rank("info") < level_rank("warning")
    assert level_rank("warning") < level_rank("error")
