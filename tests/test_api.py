from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

import xray_audit.api as api_module


class _StubRedisCache:
    enabled = False

    def get_health(self):
        return None

    def top_domains(self, minutes: int, limit: int):
        return []

    def active_users(self, seconds: int, limit: int):
        return []


class _StubQueryService:
    def collector_state(self, file_path: str):
        return None

    def recent_events(self, seconds: int, limit: int):
        return []

    def query_events(
        self,
        dt_from,
        dt_to,
        email,
        dest_host,
        status,
        detour,
        is_domain,
        page,
        page_size,
    ):
        return 1, [
            {
                "event_time": "2026-02-18T00:00:00",
                "event_type": "access",
                "raw_line": "line",
                "user_email": "u@example.com",
                "dest_host": "example.com",
            }
        ]

    def user_visits_paged(self, email, dt_from, dt_to, page, page_size):
        return 1, [{"event_time": "2026-02-18T00:00:00", "user_email": email}]

    def list_users(self, dt_from, dt_to, page, page_size):
        return 1, [{"user_email": "u@example.com", "count": 1, "last_seen": "2026-02-18T00:00:00", "unique_dest_host_count": 1}]

    def top_domains(self, seconds: int, limit: int):
        return [{"domain": "example.com", "hits": 1}]

    def active_users(self, seconds: int, limit: int):
        return [{"user_email": "u@example.com", "last_seen_unix": 1700000000}]

    def summary_stats(self, window_seconds: int):
        return {"total_events": 10, "unique_users": 2, "unique_domains": 3, "qpm": 120.0}

    def query_error_events(
        self,
        dt_from,
        dt_to,
        level,
        category,
        include_noise,
        keyword,
        page,
        page_size,
    ):
        return 1, [{"event_time": "2026-02-18T00:00:00", "level": "warning", "category": "runtime_warning"}]

    def error_summary_stats(self, window_seconds: int):
        return {
            "total": 3,
            "error_count": 1,
            "warning_count": 2,
            "info_count": 0,
            "noise_count": 0,
            "top_categories": [{"category": "runtime_warning", "hits": 2}],
        }


class _StubGeoIPService:
    def lookup_batch(self, ips):
        out = {}
        for ip in ips:
            out[ip] = {"ip": ip, "label": "Test / City", "status": "ok", "source": "pconline"}
        return out


class _StubRuntimeConfig:
    def get_bool(self, key: str, fallback: bool):
        return fallback

    def get_int(self, key: str, fallback: int):
        return fallback


def _client() -> TestClient:
    api_module.settings = replace(
        api_module.settings,
        auth_enabled=False,
        auth_allow_anonymous_health=True,
    )
    api_module.query_service = _StubQueryService()
    api_module.redis_cache = _StubRedisCache()
    api_module.geoip_service = _StubGeoIPService()
    api_module.runtime_config = _StubRuntimeConfig()
    return TestClient(api_module.app)


def test_events_query_invalid_datetime_returns_400() -> None:
    client = _client()
    resp = client.get("/api/v1/events/query", params={"from": "bad", "to": "2026-02-18T00:00:00"})
    assert resp.status_code == 400


def test_events_query_bad_page_size_returns_400() -> None:
    client = _client()
    resp = client.get(
        "/api/v1/events/query",
        params={
            "from": "2026-02-18T00:00:00",
            "to": "2026-02-18T01:00:00",
            "page_size": 9999,
        },
    )
    assert resp.status_code == 400


def test_events_query_success() -> None:
    client = _client()
    resp = client.get(
        "/api/v1/events/query",
        params={
            "from": "2026-02-18T00:00:00",
            "to": "2026-02-18T01:00:00",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1


def test_users_list_page_out_of_range_returns_400() -> None:
    client = _client()
    resp = client.get(
        "/api/v1/users/list",
        params={
            "from": "2026-02-18T00:00:00",
            "to": "2026-02-18T01:00:00",
            "page": 0,
        },
    )
    assert resp.status_code == 400


def test_summary_supports_hour_window() -> None:
    client = _client()
    resp = client.get("/api/v1/stats/summary", params={"window": "1h"})
    assert resp.status_code == 200
    assert resp.json()["window"] == "1h"


def test_geoip_batch_success() -> None:
    client = _client()
    resp = client.post("/api/v1/geoip/batch", json={"ips": ["8.8.8.8"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert "8.8.8.8" in body["items"]


def test_query_errors_success() -> None:
    client = _client()
    resp = client.get(
        "/api/v1/errors/query",
        params={
            "from": "2026-02-18T00:00:00",
            "to": "2026-02-18T01:00:00",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_error_summary_success() -> None:
    client = _client()
    resp = client.get("/api/v1/errors/summary", params={"window": "1h"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 3


def test_health_contains_monitor_fields() -> None:
    client = _client()
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "collector_lag_seconds" in body
    assert "api_metrics" in body
    assert "alerts" in body


def test_metrics_endpoint_text() -> None:
    client = _client()
    resp = client.get("/api/v1/metrics")
    assert resp.status_code == 200
    text = resp.text
    assert "xray_audit_api_requests_total" in text
    assert "xray_audit_api_responses_5xx_total" in text
