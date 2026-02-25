from xray_audit.config import Settings
from xray_audit.filtering import should_drop_event
from xray_audit.parser import parse_line


def _settings(**kwargs):
    base = dict(
        node_id="n",
        log_path="/tmp/a.log",
        error_log_path="/tmp/e.log",
        error_log_enabled=True,
        error_min_level="warning",
        error_drop_noise=False,
        flush_interval_seconds=1.0,
        batch_size=100,
        poll_interval_seconds=0.2,
        mysql_host="127.0.0.1",
        mysql_port=3306,
        mysql_user="u",
        mysql_password="p",
        mysql_db="d",
        mysql_charset="utf8mb4",
        redis_url="redis://127.0.0.1:6379/0",
        redis_enabled=False,
        api_host="127.0.0.1",
        api_port=8088,
        collector_embedded=False,
        drop_api_to_api=True,
        drop_loopback_traffic=True,
        drop_invalid_vless_probe=False,
        exclude_detours=(),
        retention_days=30,
        retention_cleanup_interval_seconds=3600,
        retention_delete_batch_size=5000,
        geoip_enabled=False,
        geoip_provider_url="https://whois.pconline.com.cn/ipJson.jsp",
        geoip_timeout_seconds=3.0,
        geoip_cache_ttl_hours=168,
        geoip_batch_limit=200,
        ai_summary_enabled=False,
        ai_summary_interval_seconds=1800,
        ai_summary_window_minutes=60,
        ai_summary_max_items=200,
        ai_api_base_url="",
        ai_api_key="",
        ai_api_model="gpt-4o-mini",
        ai_api_timeout_seconds=20.0,
        tg_bot_token="",
        tg_chat_id="",
        runtime_config_refresh_seconds=3.0,
        auth_enabled=True,
        auth_allow_anonymous_health=False,
        auth_jwt_secret="test-secret",
        auth_jwt_exp_seconds=43200,
        auth_cookie_name="xray_audit_session",
        auth_cookie_secure=False,
        auth_cookie_samesite="lax",
        auth_cookie_domain="",
        auth_login_rate_limit=8,
        auth_login_rate_window_seconds=300,
        admin_bootstrap_username="admin",
        admin_bootstrap_password="ChangeMe123!",
    )
    base.update(kwargs)
    return Settings(**base)


def test_drop_api_to_api() -> None:
    ev = parse_line("2026/02/18 10:00:00.123456 from 127.0.0.1:50000 accepted tcp:127.0.0.1:62789 [api -> api]")
    assert ev is not None
    assert should_drop_event(ev, _settings()) is True


def test_drop_by_custom_detour() -> None:
    ev = parse_line("2026/02/18 10:00:00.123456 from 1.2.3.4:50000 accepted tcp:example.com:443 [dns_inbound -> hkt] email: a")
    assert ev is not None
    assert should_drop_event(ev, _settings(exclude_detours=("dns_inbound -> hkt",))) is True


def test_keep_normal_event() -> None:
    ev = parse_line("2026/02/18 10:00:00.123456 from 1.2.3.4:50000 accepted tcp:example.com:443 [inbound-443 -> hkt] email: a")
    assert ev is not None
    assert should_drop_event(ev, _settings()) is False


def test_drop_invalid_vless_probe_when_enabled() -> None:
    ev = parse_line("2026/02/18 10:00:00.123456 from 1.2.3.4:50000 rejected  proxy/vless/encoding: invalid request version")
    assert ev is not None
    assert should_drop_event(ev, _settings(drop_invalid_vless_probe=True)) is True
