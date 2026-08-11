from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

from xray_audit.config import Settings
from xray_audit.memory_storage import MemoryStorage
from xray_audit.models import AccessEvent, DNSEvent, ParsedErrorEvent, ParsedEvent
from xray_audit.runtime_config import RuntimeConfigManager


def _storage(access: int = 10, dns: int = 10, error: int = 10) -> MemoryStorage:
    base = Settings.from_env()
    values = vars(base).copy()
    values.update(
        memory_max_access_events=access,
        memory_max_dns_events=dns,
        memory_max_error_events=error,
    )
    return MemoryStorage(SimpleNamespace(**values))


def _access(at: datetime, email: str, host: str, is_domain: bool = True) -> ParsedEvent:
    return ParsedEvent(
        event_time=at,
        event_type="access",
        raw_line=f"{email} {host}",
        raw_hash=f"{email}:{host}:{at}",
        access=AccessEvent(
            event_time=at,
            user_email=email,
            src="192.0.2.1:1234",
            dest_raw=f"tcp:{host}:443",
            dest_host=host,
            dest_port=443,
            status="accepted",
            detour="in -> direct",
            reason="",
            is_domain=is_domain,
            confidence="high",
        ),
    )


def _dns(at: datetime, domain: str) -> ParsedEvent:
    return ParsedEvent(
        event_time=at,
        event_type="dns",
        raw_line=f"dns {domain}",
        raw_hash=f"dns:{domain}:{at}",
        dns=DNSEvent(at, "8.8.8.8", domain, '["203.0.113.1"]', "success", 5, ""),
    )


def _error(at: datetime, level: str, category: str, noise: bool = False) -> ParsedErrorEvent:
    return ParsedErrorEvent(
        event_time=at,
        level=level,
        session_id=1,
        component="proxy/vless",
        message=f"{category} connection failed",
        src="192.0.2.1:1234",
        dest_raw="tcp:example.com:443",
        dest_host="example.com",
        dest_port=443,
        category=category,
        signature_hash=f"sig-{category}",
        is_noise=noise,
        raw_line="error line",
        raw_hash=f"raw-{category}-{at}",
    )


def test_bounded_event_buffers_evict_oldest_independently() -> None:
    storage = _storage(access=2, dns=1, error=1)
    now = datetime.utcnow()
    events = [
        _access(now - timedelta(seconds=3), "old@example.com", "old.example"),
        _access(now - timedelta(seconds=2), "mid@example.com", "mid.example"),
        _access(now - timedelta(seconds=1), "new@example.com", "new.example"),
        _dns(now - timedelta(seconds=2), "old-dns.example"),
        _dns(now - timedelta(seconds=1), "new-dns.example"),
    ]

    assert storage.ingest_events(events, "node-a") == {"raw": 0, "access": 3, "dns": 0}
    storage.ingest_error_events([_error(now, "warning", "old"), _error(now, "error", "new")], "node-a")

    recent = storage.recent_events(60, 20)
    assert {row["dest_host"] for row in recent} == {"mid.example", "new.example"}
    assert all("raw_line" not in row and "dest_raw" not in row for row in recent)
    total, errors = storage.query_error_events(now - timedelta(minutes=1), now + timedelta(minutes=1), None, None, True, None, 1, 10)
    assert total == 1
    assert errors[0]["category"] == "new"
    assert storage.prune_old_events(30, 100) == 0
    assert storage.close() is None


def test_admin_runtime_config_and_auxiliary_state_are_kept_in_memory() -> None:
    settings = replace(Settings.from_env(), runtime_config_refresh_seconds=1)
    storage = MemoryStorage(settings)
    storage.admin_user_create("admin", "hash-1", must_change_password=True)
    storage.admin_user_update_login_success("admin")
    storage.admin_user_change_password("admin", "hash-2")
    storage.admin_user_bump_token_version("admin")
    storage.auth_event_insert("login_success", "admin", "127.0.0.1", "pytest")

    admin = storage.admin_user_get("admin")
    assert storage.admin_user_count() == 1
    assert admin is not None
    assert admin["password_hash"] == "hash-2"
    assert admin["token_version"] == 2
    assert admin["must_change_password"] == 0
    assert admin["last_login_at"] is not None

    manager = RuntimeConfigManager(settings, storage)
    manager.update_items({"AUDIT_BATCH_SIZE": 42}, changed_by="admin", source_ip="127.0.0.1")
    manager.update_items({"AUDIT_BATCH_SIZE": 43}, changed_by="admin", source_ip="127.0.0.2")
    assert manager.get_int("AUDIT_BATCH_SIZE", 1) == 43
    total, history = storage.runtime_config_history(1, 1)
    assert total == 2
    assert history[0]["new_value_json"] == "43"
    assert history[0]["old_value_json"] == "42"

    storage.save_state("access.log", 123, 456)
    assert storage.load_state("access.log") == (123, 456)
    assert storage.collector_state("access.log")["last_offset"] == 456
    storage.job_state_set("summary", "2026-07-24T00:00:00")
    assert storage.job_state_get("summary") == "2026-07-24T00:00:00"
    storage.geo_cache_upsert([{"ip": "203.0.113.1", "country": "CN", "city": "Shanghai"}])
    assert storage.geo_cache_get(["203.0.113.1"], 1)["203.0.113.1"]["country"] == "CN"


def test_queries_and_statistics_apply_time_and_value_filters() -> None:
    storage = _storage()
    now = datetime.utcnow()
    storage.ingest_events(
        [
            _access(now - timedelta(seconds=40), "alice@example.com", "example.com"),
            _access(now - timedelta(seconds=30), "alice@example.com", "example.com"),
            _access(now - timedelta(seconds=20), "bob@example.com", "other.example"),
            _access(now - timedelta(hours=2), "stale@example.com", "stale.example"),
            _dns(now - timedelta(seconds=10), "dns.example"),
        ],
        "node-a",
    )
    storage.ingest_error_events(
        [
            _error(now - timedelta(seconds=20), "error", "network"),
            _error(now - timedelta(seconds=10), "warning", "network", noise=True),
            _error(now - timedelta(hours=2), "info", "stale"),
        ],
        "node-a",
    )
    start, end = now - timedelta(minutes=1), now + timedelta(seconds=1)

    total, rows = storage.query_events(start, end, "alice@example.com", "example", "accepted", "direct", True, 1, 10)
    assert total == 2
    assert [row["user_email"] for row in rows] == ["alice@example.com", "alice@example.com"]
    users_total, users = storage.list_users(start, end, 1, 10)
    assert users_total == 2
    assert {row["user_email"]: row["count"] for row in users} == {"alice@example.com": 2, "bob@example.com": 1}
    assert storage.summary_stats(60) == {"total_events": 3, "unique_users": 2, "unique_domains": 2, "qpm": 3.0}
    assert storage.top_domains(60, 10) == [{"domain": "example.com", "hits": 2}, {"domain": "other.example", "hits": 1}]

    error_total, errors = storage.query_error_events(start, end, None, "network", False, "connection", 1, 10)
    assert error_total == 1
    assert errors[0]["level"] == "error"
    assert storage.error_summary_stats(60) == {
        "total": 2,
        "error_count": 1,
        "warning_count": 1,
        "info_count": 0,
        "noise_count": 1,
        "top_categories": [{"category": "network", "hits": 2}],
    }
    payload = storage.error_summary_payload(start, end, 10)
    assert payload["total"] == 2
    assert payload["top_signatures"][0]["hits"] == 2
