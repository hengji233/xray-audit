from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from xray_audit.config import Settings
from xray_audit.d1_storage import D1Ingestor, D1QueryService, D1StorageError
from xray_audit.memory_storage import MemoryStorage
from xray_audit.models import AccessEvent, DNSEvent, ParsedErrorEvent, ParsedEvent
from xray_audit.storage import AuditQueryService, MySQLIngestor
from xray_audit.storage_factory import create_ingestor, create_query_service


def _settings(**changes) -> Settings:
    values = {
        "storage_backend": "d1",
        "d1_gateway_url": "https://storage.example.test/base/",
        "d1_gateway_token": "secret",
        "d1_timeout_seconds": 2.0,
        "d1_batch_size": 50,
        "d1_max_retries": 0,
    }
    values.update(changes)
    return replace(Settings.from_env(), **values)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_protocol_authorization_payload_and_datetime_normalization() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("Authorization")
        seen["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={"ok": True, "data": {"total": 1, "items": [{"event_time": "2026-07-21T12:30:00.123456Z"}]}},
        )

    service = D1QueryService(_settings(), _client(handler))
    total, rows = service.user_visits_paged(
        "user@example.com",
        datetime(2026, 7, 21, 8, 0, tzinfo=timezone(timedelta(hours=8))),
        datetime(2026, 7, 21, 9, 0, tzinfo=timezone(timedelta(hours=8))),
        1,
        20,
    )

    assert seen["url"] == "https://storage.example.test/base/v1/storage/user_visits_paged"
    assert seen["authorization"] == "Bearer secret"
    assert '"from":"2026-07-21T00:00:00.000000Z"' in seen["body"]
    assert total == 1
    assert rows[0]["event_time"] == datetime(2026, 7, 21, 12, 30, 0, 123456)


def test_structured_error_is_exposed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "ok": False,
                "error": {"code": "INVALID_INPUT", "message": "bad window", "retryable": False},
            },
        )

    service = D1QueryService(_settings(), _client(handler))
    with pytest.raises(D1StorageError) as raised:
        service.summary_stats(300)

    assert raised.value.code == "INVALID_INPUT"
    assert raised.value.message == "bad window"
    assert raised.value.retryable is False
    assert raised.value.status_code == 400


def test_retryable_gateway_error_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0
    monkeypatch.setattr("xray_audit.d1_storage.time.sleep", lambda _: None)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(
                503,
                json={"ok": False, "error": {"code": "D1_BUSY", "message": "busy", "retryable": True}},
            )
        return httpx.Response(200, json={"ok": True, "data": {"total_events": 2}})

    service = D1QueryService(_settings(d1_max_retries=2), _client(handler))
    assert service.summary_stats(60) == {"total_events": 2}
    assert attempts == 3


def test_non_idempotent_operation_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0
    monkeypatch.setattr("xray_audit.d1_storage.time.sleep", lambda _: None)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            503,
            json={"ok": False, "error": {"code": "D1_BUSY", "message": "busy", "retryable": True}},
        )

    service = D1QueryService(_settings(d1_max_retries=3), _client(handler))
    with pytest.raises(D1StorageError):
        service.admin_user_bump_token_version("admin")
    assert attempts == 1


def test_ingestor_serializes_only_access_events() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "data": {"count": 2}})

    event_time = datetime(2026, 7, 21, 12, 34, 56, 789)
    events = [
        ParsedEvent(
            event_time=event_time,
            event_type="access",
            raw_line="access line",
            raw_hash="a" * 64,
            access=AccessEvent(
                event_time=event_time,
                user_email="user@example.com",
                src="1.2.3.4:5000",
                dest_raw="tcp:example.com:443",
                dest_host="example.com",
                dest_port=443,
                status="accepted",
                detour="in -> out",
                reason="",
                is_domain=True,
                confidence="high",
            ),
        ),
        ParsedEvent(
            event_time=event_time,
            event_type="dns",
            raw_line="dns line",
            raw_hash="b" * 64,
            dns=DNSEvent(
                event_time=event_time,
                dns_server="8.8.8.8",
                domain="example.net",
                ips_json='["203.0.113.1"]',
                dns_status="success",
                elapsed_ms=12,
                error_text="",
            ),
        ),
    ]

    ingestor = D1Ingestor(_settings(), _client(handler))
    assert ingestor.ingest_events(events, "node-a") == {"raw": 0, "access": 1, "dns": 0}

    body = json.loads(requests[0].read())
    assert body["node_id"] == "node-a"
    assert body["events"][0]["event_time"] == "2026-07-21T12:34:56.000789Z"
    assert body["events"][0]["access"]["is_domain"] is True
    assert body["events"][0]["access"]["dest_port"] == 443
    assert body["events"][0]["access"]["protocol"] == "tcp"
    assert body["events"][0]["event_hash"] == "a" * 64
    assert "raw_line" not in body["events"][0]
    assert len(body["events"]) == 1


def test_ingestor_does_not_send_error_events() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "data": {"count": 1}})

    event = ParsedErrorEvent(
        event_time=datetime(2026, 7, 21, 12, 0),
        level="warning",
        session_id=42,
        component="proxy/vless",
        message="connection failed",
        src="1.2.3.4:5000",
        dest_raw="tcp:example.com:443",
        dest_host="example.com",
        dest_port=443,
        category="network",
        signature_hash="c" * 64,
        is_noise=True,
        raw_line="warning line",
        raw_hash="d" * 64,
    )

    ingestor = D1Ingestor(_settings(), _client(handler))
    assert ingestor.ingest_error_events([event], "node-a") == 0
    assert requests == []


def test_collector_state_uses_decimal_strings_for_int64_values() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        if request.url.path.endswith("/save_state"):
            seen.update(payload)
            return httpx.Response(200, json={"ok": True, "data": {"saved": True}})
        return httpx.Response(
            200,
            json={"ok": True, "data": {"inode": "9223372036854775807", "last_offset": "4294967296"}},
        )

    ingestor = D1Ingestor(_settings(), _client(handler))
    assert ingestor.load_state("/logs/access.log") == (9223372036854775807, 4294967296)
    ingestor.save_state("/logs/access.log", 9223372036854775807, 4294967296)
    assert seen == {
        "file_path": "/logs/access.log",
        "inode": "9223372036854775807",
        "offset": "4294967296",
    }


def test_factory_selects_memory_by_default_and_d1_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings.from_env()
    monkeypatch.setattr(MySQLIngestor, "__init__", lambda self, _: None)

    assert isinstance(create_ingestor(settings), MemoryStorage)
    assert isinstance(create_query_service(settings), MemoryStorage)

    d1_settings = _settings()
    assert isinstance(create_ingestor(d1_settings), D1Ingestor)
    assert isinstance(create_query_service(d1_settings), D1QueryService)
