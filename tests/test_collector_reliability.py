from __future__ import annotations

from typing import Callable, Optional

import pytest

from xray_audit.collector import AuditCollector
from xray_audit.config import Settings


ACCESS_LINE = (
    "2026/02/18 10:00:00.123456 from 1.2.3.4:12345 accepted "
    "tcp:example.com:443 [socks-in -> direct] email: user@example.com"
)
DNS_LINE = "2026/02/18 10:00:01.000001 8.8.8.8 got answer: example.com. -> [1.1.1.1] 23ms"
UNKNOWN_LINE = "2026/02/18 10:00:02.000001 something not matching access or dns"
FILTERED_LINE = (
    "2026/02/18 10:00:03.000001 from 127.0.0.1:50000 accepted "
    "tcp:127.0.0.1:62789 [api -> api]"
)
ERROR_LINE = (
    "2026/02/18 10:11:55.397153 [Warning] [12345] "
    "proxy/vless/inbound: received request for tcp:example.com:443"
)


def _settings(**overrides: object) -> Settings:
    values = dict(
        node_id="node-test",
        log_path="access.log",
        error_log_path="error.log",
        error_log_enabled=False,
        error_min_level="warning",
        error_drop_noise=False,
        flush_interval_seconds=30.0,
        batch_size=100,
        poll_interval_seconds=0.05,
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
        geoip_provider_url="",
        geoip_timeout_seconds=3.0,
        geoip_cache_ttl_hours=168,
        geoip_batch_limit=200,
        ai_summary_enabled=False,
        ai_summary_interval_seconds=1800,
        ai_summary_window_minutes=60,
        ai_summary_max_items=200,
        ai_api_base_url="",
        ai_api_key="",
        ai_api_model="",
        ai_api_timeout_seconds=20.0,
        tg_bot_token="",
        tg_chat_id="",
        runtime_config_refresh_seconds=3.0,
        auth_enabled=False,
        auth_allow_anonymous_health=True,
        auth_jwt_secret="test-secret",
        auth_jwt_exp_seconds=43200,
        auth_cookie_name="session",
        auth_cookie_secure=False,
        auth_cookie_samesite="lax",
        auth_cookie_domain="",
        auth_login_rate_limit=8,
        auth_login_rate_window_seconds=300,
        admin_bootstrap_username="admin",
        admin_bootstrap_password="password",
    )
    values.update(overrides)
    return Settings(**values)


class FakeTailer:
    def __init__(
        self,
        reads: list[tuple[list[str], tuple[int, int]]],
        on_empty: Optional[Callable[[], None]] = None,
    ) -> None:
        self.reads = list(reads)
        self.on_empty = on_empty
        self.cursor: tuple[Optional[int], int] = (None, 0)
        self.read_calls = 0

    def set_state(self, inode: Optional[int], offset: int) -> None:
        self.cursor = (inode, offset)

    def state(self) -> tuple[Optional[int], int]:
        return self.cursor

    def read_new_lines(self, max_lines: int) -> list[str]:
        self.read_calls += 1
        if self.reads:
            lines, cursor = self.reads.pop(0)
            self.cursor = cursor
            return lines
        if self.on_empty is not None:
            self.on_empty()
        return []

    def close(self) -> None:
        pass


class FakeIngestor:
    def __init__(self) -> None:
        self.collector: Optional[AuditCollector] = None
        self.event_calls: list[list[object]] = []
        self.error_calls: list[list[object]] = []
        self.saved_states: list[tuple[str, Optional[int], int]] = []
        self.fail_event_writes = 0
        self.stop_after_event_writes: Optional[int] = None
        self.stop_after_error_write = False

    def runtime_config_all(self) -> list[dict[str, object]]:
        return []

    def load_state(self, log_path: str) -> tuple[None, int]:
        return None, 0

    def save_state(self, log_path: str, inode: Optional[int], offset: int) -> None:
        self.saved_states.append((log_path, inode, offset))

    def ingest_events(self, events: list[object], node_id: str) -> dict[str, int]:
        self.event_calls.append(list(events))
        if self.fail_event_writes:
            self.fail_event_writes -= 1
            raise RuntimeError("controlled write failure")
        if self.stop_after_event_writes == len(self.event_calls):
            assert self.collector is not None
            self.collector._stop_event.set()
        return {"raw": 0, "access": len(events), "dns": 0}

    def ingest_error_events(self, events: list[object], node_id: str) -> int:
        self.error_calls.append(list(events))
        if self.stop_after_error_write:
            assert self.collector is not None
            self.collector._stop_event.set()
        return len(events)

    def prune_old_events(self, retention_days: int, delete_batch_size: int) -> int:
        return 0


def _collector(settings: Settings, ingestor: FakeIngestor) -> AuditCollector:
    collector = AuditCollector(settings, ingestor=ingestor, query_service=ingestor)
    ingestor.collector = collector
    return collector


def test_only_access_events_are_passed_to_ingestor(monkeypatch: pytest.MonkeyPatch) -> None:
    ingestor = FakeIngestor()
    collector = _collector(_settings(), ingestor)
    collector.tailer = FakeTailer(
        [([ACCESS_LINE, DNS_LINE, UNKNOWN_LINE], (11, 300))],
        on_empty=collector._stop_event.set,
    )
    monkeypatch.setattr("xray_audit.collector.time.sleep", lambda _: None)

    collector.run_forever()

    assert len(ingestor.event_calls) == 1
    assert [event.event_type for event in ingestor.event_calls[0]] == ["access"]
    assert ingestor.saved_states == [("access.log", 11, 300)]


def test_failed_write_retries_original_batch_before_reading_more(monkeypatch: pytest.MonkeyPatch) -> None:
    ingestor = FakeIngestor()
    ingestor.fail_event_writes = 1
    ingestor.stop_after_event_writes = 2
    collector = _collector(_settings(batch_size=1), ingestor)
    tailer = FakeTailer(
        [([ACCESS_LINE], (12, 100)), ([ACCESS_LINE.replace("example.com", "later.example")], (12, 200))]
    )
    collector.tailer = tailer
    monkeypatch.setattr("xray_audit.collector.time.sleep", lambda _: None)

    collector.run_forever()

    assert tailer.read_calls == 1
    assert len(ingestor.event_calls) == 2
    assert ingestor.event_calls[0] == ingestor.event_calls[1]
    assert len(ingestor.event_calls[1]) == 1
    assert ingestor.saved_states == [("access.log", 12, 100)]


def test_access_cursor_is_not_advanced_until_write_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    ingestor = FakeIngestor()
    ingestor.fail_event_writes = 1
    ingestor.stop_after_event_writes = 2
    collector = _collector(_settings(batch_size=1), ingestor)
    collector.tailer = FakeTailer([([ACCESS_LINE], (13, 150))])
    monkeypatch.setattr("xray_audit.collector.time.sleep", lambda _: None)

    collector.run_forever()

    assert len(ingestor.event_calls) == 2
    assert ingestor.saved_states == [("access.log", 13, 150)]


def test_error_events_use_ingestor_and_advance_error_cursor() -> None:
    ingestor = FakeIngestor()
    ingestor.stop_after_error_write = True
    collector = _collector(_settings(error_log_enabled=True, batch_size=1), ingestor)
    collector.tailer = FakeTailer([])
    collector.error_tailer = FakeTailer([([ERROR_LINE], (21, 210))])

    collector.run_forever()

    assert len(ingestor.error_calls) == 1
    assert ingestor.error_calls[0][0].level == "warning"
    assert ingestor.event_calls == []
    assert ingestor.saved_states[-1] == ("error.log", 21, 210)
    assert all(path == "error.log" for path, _, _ in ingestor.saved_states)


@pytest.mark.parametrize(
    "lines",
    [
        [DNS_LINE, UNKNOWN_LINE],
        [FILTERED_LINE],
        ["not a parseable log line"],
    ],
)
def test_inputs_without_persistable_access_still_advance_cursor(lines: list[str]) -> None:
    ingestor = FakeIngestor()
    collector = _collector(_settings(), ingestor)
    collector.tailer = FakeTailer([(lines, (31, 310))], on_empty=collector._stop_event.set)

    collector.run_forever()

    assert ingestor.event_calls == []
    assert ingestor.saved_states == [("access.log", 31, 310)]
