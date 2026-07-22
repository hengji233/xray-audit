from __future__ import annotations

import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .config import Settings
from .models import ParsedErrorEvent, ParsedEvent


_TIMESTAMP_FIELDS = {
    "changed_at",
    "created_at",
    "event_time",
    "from",
    "ingested_at",
    "last_login_at",
    "last_seen",
    "latest_time",
    "updated_at",
    "to",
}

_RETRYABLE_OPERATIONS = {
    "active_users",
    "admin_user_count",
    "admin_user_get",
    "admin_user_update_login_success",
    "collector_state",
    "error_summary_payload",
    "error_summary_stats",
    "geo_cache_get",
    "geo_cache_upsert",
    "ingest_error_events",
    "ingest_events",
    "job_state_get",
    "job_state_set",
    "list_users",
    "load_state",
    "migration_import",
    "migration_stats",
    "prune_old_events",
    "query_error_events",
    "query_events",
    "recent_events",
    "runtime_config_all",
    "runtime_config_history",
    "save_state",
    "summary_stats",
    "top_domains",
    "user_visits",
    "user_visits_paged",
}


class D1StorageError(RuntimeError):
    def __init__(self, code: str, message: str, retryable: bool = False, status_code: int | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.retryable = retryable
        self.status_code = status_code


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return _iso_utc(value)
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    return value


def _parse_datetime(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _normalize(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {name: _normalize(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if key in _TIMESTAMP_FIELDS:
        return _parse_datetime(value)
    return value


class _D1Client:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        gateway = settings.d1_gateway_url.strip().rstrip("/")
        token = settings.d1_gateway_token.strip()
        if not gateway or not token:
            raise ValueError("AUDIT_D1_GATEWAY_URL and AUDIT_D1_GATEWAY_TOKEN are required for D1 storage")
        self.gateway = gateway
        self.max_retries = max(0, settings.d1_max_retries)
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=settings.d1_timeout_seconds)
        self.headers = {"Authorization": f"Bearer {token}"}

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def call(self, operation: str, payload: Dict[str, Any]) -> Any:
        url = f"{self.gateway}/v1/storage/{operation}"
        max_retries = self.max_retries if operation in _RETRYABLE_OPERATIONS else 0
        for attempt in range(max_retries + 1):
            try:
                response = self.client.post(url, headers=self.headers, json=_serialize(payload))
                try:
                    envelope = response.json()
                except ValueError as err:
                    raise D1StorageError(
                        "INVALID_RESPONSE", "storage gateway returned invalid JSON",
                        response.status_code == 429 or response.status_code >= 500,
                        response.status_code,
                    ) from err

                if not isinstance(envelope, dict):
                    raise D1StorageError("INVALID_RESPONSE", "storage gateway response must be an object")
                if envelope.get("ok") is True and "data" in envelope:
                    return _normalize(envelope["data"])

                error = envelope.get("error") if isinstance(envelope.get("error"), dict) else {}
                raise D1StorageError(
                    str(error.get("code") or "HTTP_ERROR"),
                    str(error.get("message") or f"storage gateway returned HTTP {response.status_code}"),
                    bool(error.get("retryable")) or response.status_code == 429 or response.status_code >= 500,
                    response.status_code,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as err:
                failure = D1StorageError("NETWORK_ERROR", str(err), True)
            except D1StorageError as err:
                failure = err

            if not failure.retryable or attempt >= max_retries:
                raise failure
            time.sleep(min(0.1 * (2**attempt), 1.0))
        raise AssertionError("unreachable")


class D1Ingestor:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self._client = _D1Client(settings, client)
        self.batch_size = min(50, max(1, settings.d1_batch_size))

    def close(self) -> None:
        self._client.close()

    def load_state(self, file_path: str) -> Tuple[Optional[int], int]:
        row = self._client.call("load_state", {"file_path": file_path})
        if not row:
            return None, 0
        inode = row.get("inode")
        return (None if inode is None else int(inode)), int(row.get("last_offset", 0))

    def save_state(self, file_path: str, inode: Optional[int], offset: int) -> None:
        self._client.call(
            "save_state",
            {"file_path": file_path, "inode": None if inode is None else str(inode), "offset": str(offset)},
        )

    def ingest_events(self, events: List[ParsedEvent], node_id: str) -> Dict[str, int]:
        counts = {"raw": 0, "access": 0, "dns": 0}
        for start in range(0, len(events), self.batch_size):
            batch = events[start : start + self.batch_size]
            payload = [self._event_payload(event) for event in batch]
            self._client.call("ingest_events", {"events": payload, "node_id": node_id})
            counts["raw"] += len(batch)
            counts["access"] += sum(event.access is not None for event in batch)
            counts["dns"] += sum(event.dns is not None for event in batch)
        return counts

    def ingest_error_events(self, events: List[ParsedErrorEvent], node_id: str) -> int:
        inserted = 0
        for start in range(0, len(events), self.batch_size):
            batch = events[start : start + self.batch_size]
            self._client.call(
                "ingest_error_events",
                {"events": [_serialize(asdict(event)) for event in batch], "node_id": node_id},
            )
            inserted += len(batch)
        return inserted

    def prune_old_events(self, retention_days: int, delete_batch_size: int) -> int:
        if retention_days <= 0 or delete_batch_size <= 0:
            return 0
        total = 0
        while True:
            data = self._client.call(
                "prune_old_events",
                {"retention_days": retention_days, "delete_batch_size": min(delete_batch_size, 500)},
            )
            deleted = int(data.get("deleted", 0))
            total += deleted
            if deleted == 0:
                return total

    @staticmethod
    def _event_payload(event: ParsedEvent) -> Dict[str, Any]:
        payload = _serialize(asdict(event))
        if event.dns is not None:
            try:
                payload["dns"]["ips_json"] = json.loads(event.dns.ips_json)
            except (TypeError, json.JSONDecodeError):
                payload["dns"]["ips_json"] = event.dns.ips_json
        return payload


class D1QueryService:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self._client = _D1Client(settings, client)
        self.batch_size = min(50, max(1, settings.d1_batch_size))
        self.geo_batch_size = 99

    def close(self) -> None:
        self._client.close()

    def _call(self, operation: str, **payload: Any) -> Any:
        return self._client.call(operation, payload)

    @staticmethod
    def _paged(data: Dict[str, Any]) -> Tuple[int, List[Dict[str, Any]]]:
        return int(data.get("total", 0)), list(data.get("items") or [])

    def collector_state(self, file_path: str) -> Optional[Dict[str, Any]]:
        return self._call("collector_state", file_path=file_path)

    def admin_user_count(self) -> int:
        return int(self._call("admin_user_count").get("count", 0))

    def admin_user_get(self, username: str) -> Optional[Dict[str, Any]]:
        return self._call("admin_user_get", username=username)

    def admin_user_create(self, username: str, password_hash: str, must_change_password: bool = False) -> None:
        self._call("admin_user_create", username=username, password_hash=password_hash, must_change_password=must_change_password)

    def admin_user_update_login_success(self, username: str) -> None:
        self._call("admin_user_update_login_success", username=username)

    def admin_user_bump_token_version(self, username: str) -> None:
        self._call("admin_user_bump_token_version", username=username)

    def admin_user_change_password(self, username: str, new_password_hash: str) -> None:
        self._call("admin_user_change_password", username=username, new_password_hash=new_password_hash)

    def auth_event_insert(self, event_type: str, username: str, source_ip: str, user_agent: str) -> None:
        self._call("auth_event_insert", event_type=event_type, username=username, source_ip=source_ip, user_agent=user_agent)

    def runtime_config_all(self) -> List[Dict[str, Any]]:
        return list(self._call("runtime_config_all") or [])

    def runtime_config_upsert(self, values: Dict[str, Any], changed_by: str, source_ip: str) -> None:
        if values:
            self._call("runtime_config_upsert", items=values, changed_by=changed_by, source_ip=source_ip)

    def runtime_config_history(self, page: int, page_size: int) -> Tuple[int, List[Dict[str, Any]]]:
        return self._paged(self._call("runtime_config_history", page=page, page_size=page_size))

    def recent_events(self, seconds: int, limit: int) -> List[Dict[str, Any]]:
        return list(self._call("recent_events", seconds=seconds, limit=limit) or [])

    def user_visits(self, email: str, dt_from: datetime, dt_to: datetime, limit: int) -> List[Dict[str, Any]]:
        return list(self._call("user_visits", email=email, **{"from": dt_from, "to": dt_to}, limit=limit) or [])

    def user_visits_paged(self, email: str, dt_from: datetime, dt_to: datetime, page: int, page_size: int) -> Tuple[int, List[Dict[str, Any]]]:
        return self._paged(self._call("user_visits_paged", email=email, **{"from": dt_from, "to": dt_to}, page=page, page_size=page_size))

    def query_events(self, dt_from: datetime, dt_to: datetime, email: Optional[str], dest_host: Optional[str], status: Optional[str], detour: Optional[str], is_domain: Optional[bool], page: int, page_size: int) -> Tuple[int, List[Dict[str, Any]]]:
        return self._paged(self._call("query_events", **{"from": dt_from, "to": dt_to}, email=email, dest_host=dest_host, status=status, detour=detour, is_domain=is_domain, page=page, page_size=page_size))

    def list_users(self, dt_from: datetime, dt_to: datetime, page: int, page_size: int) -> Tuple[int, List[Dict[str, Any]]]:
        return self._paged(self._call("list_users", **{"from": dt_from, "to": dt_to}, page=page, page_size=page_size))

    def summary_stats(self, window_seconds: int) -> Dict[str, Any]:
        return dict(self._call("summary_stats", window_seconds=window_seconds))

    def query_error_events(self, dt_from: datetime, dt_to: datetime, level: Optional[str], category: Optional[str], include_noise: bool, keyword: Optional[str], page: int, page_size: int) -> Tuple[int, List[Dict[str, Any]]]:
        return self._paged(self._call("query_error_events", **{"from": dt_from, "to": dt_to}, level=level, category=category, include_noise=include_noise, keyword=keyword, page=page, page_size=page_size))

    def error_summary_stats(self, window_seconds: int) -> Dict[str, Any]:
        return dict(self._call("error_summary_stats", window_seconds=window_seconds))

    def error_summary_payload(self, dt_from: datetime, dt_to: datetime, max_items: int) -> Dict[str, Any]:
        return dict(self._call("error_summary_payload", **{"from": dt_from, "to": dt_to}, max_items=max_items))

    def job_state_get(self, key: str) -> Optional[str]:
        row = self._call("job_state_get", key=key)
        return None if not row else str(row.get("value_text", ""))

    def job_state_set(self, key: str, value: str) -> None:
        self._call("job_state_set", key=key, value=value)

    def geo_cache_get(self, ips: List[str], ttl_hours: int) -> Dict[str, Dict[str, Any]]:
        found: Dict[str, Dict[str, Any]] = {}
        for start in range(0, len(ips), self.geo_batch_size):
            found.update(self._call("geo_cache_get", ips=ips[start : start + self.geo_batch_size], ttl_hours=ttl_hours))
        return found

    def geo_cache_upsert(self, rows: List[Dict[str, Any]]) -> None:
        for start in range(0, len(rows), self.batch_size):
            self._call("geo_cache_upsert", rows=rows[start : start + self.batch_size])

    def top_domains(self, seconds: int, limit: int) -> List[Dict[str, Any]]:
        return list(self._call("top_domains", seconds=seconds, limit=limit) or [])

    def active_users(self, seconds: int, limit: int) -> List[Dict[str, Any]]:
        rows = list(self._call("active_users", seconds=seconds, limit=limit) or [])
        for row in rows:
            last_seen = row.pop("last_seen", None)
            row["last_seen_unix"] = int(last_seen.replace(tzinfo=timezone.utc).timestamp()) if isinstance(last_seen, datetime) else 0
        return rows
