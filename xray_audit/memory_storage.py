from __future__ import annotations

import json
import threading
from collections import Counter, deque
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

from .config import Settings
from .models import ParsedErrorEvent, ParsedEvent


def _now() -> datetime:
    return datetime.utcnow()


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _capacity(settings: Settings, name: str, fallback: int) -> int:
    try:
        return max(1, int(getattr(settings, name, fallback)))
    except (TypeError, ValueError):
        return fallback


class MemoryStorage:
    """Thread-safe, process-local storage implementing both storage interfaces."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.RLock()
        self._access_events: Deque[Dict[str, Any]] = deque(
            maxlen=_capacity(settings, "memory_max_access_events", 100_000)
        )
        self._error_events: Deque[Dict[str, Any]] = deque(
            maxlen=_capacity(settings, "memory_max_error_events", 20_000)
        )
        self._collector_states: Dict[str, Dict[str, Any]] = {}
        self._admin_users: Dict[str, Dict[str, Any]] = {}
        self._auth_events: List[Dict[str, Any]] = []
        self._runtime_config: Dict[str, Dict[str, Any]] = {}
        self._runtime_config_history: List[Dict[str, Any]] = []
        self._job_states: Dict[str, str] = {}
        self._geo_cache: Dict[str, Dict[str, Any]] = {}
        self._next_event_id = 1
        self._next_error_id = 1
        self._next_admin_id = 1
        self._next_config_history_id = 1

    def close(self) -> None:
        return None

    def load_state(self, file_path: str) -> Tuple[Optional[int], int]:
        with self._lock:
            row = self._collector_states.get(file_path)
            if row is None:
                return None, 0
            return row.get("inode"), int(row.get("last_offset", 0))

    def save_state(self, file_path: str, inode: Optional[int], offset: int) -> None:
        with self._lock:
            self._collector_states[file_path] = {
                "file_path": file_path,
                "inode": inode,
                "last_offset": int(offset),
                "updated_at": _now(),
            }

    def collector_state(self, file_path: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._collector_states.get(file_path)
            return deepcopy(row) if row is not None else None

    def ingest_events(self, events: List[ParsedEvent], node_id: str) -> Dict[str, int]:
        counts = {"raw": 0, "access": 0, "dns": 0}
        with self._lock:
            for event in events:
                if event.access is None:
                    continue
                event_id = self._next_event_id
                self._next_event_id += 1
                access = event.access
                protocol = access.dest_raw.split(":", 1)[0] if access.dest_raw.startswith(("tcp:", "udp:")) else ""
                self._access_events.append(
                    {
                        "id": event_id,
                        "event_time": _utc_naive(access.event_time),
                        "user_email": access.user_email,
                        "src": access.src,
                        "dest_host": access.dest_host,
                        "dest_port": access.dest_port,
                        "protocol": protocol,
                        "status": access.status,
                        "detour": access.detour,
                        "reason": access.reason,
                        "is_domain": 1 if access.is_domain else 0,
                        "node_id": node_id,
                    }
                )
                counts["access"] += 1
        return counts

    def ingest_error_events(self, events: List[ParsedErrorEvent], node_id: str) -> int:
        with self._lock:
            for event in events:
                self._error_events.append(
                    {
                        "id": self._next_error_id,
                        "event_time": _utc_naive(event.event_time),
                        "level": event.level,
                        "session_id": event.session_id,
                        "component": event.component,
                        "message": event.message,
                        "src": event.src,
                        "dest_raw": event.dest_raw,
                        "dest_host": event.dest_host,
                        "dest_port": event.dest_port,
                        "category": event.category,
                        "signature_hash": event.signature_hash,
                        "is_noise": 1 if event.is_noise else 0,
                        "node_id": node_id,
                    }
                )
                self._next_error_id += 1
        return len(events)

    def prune_old_events(self, retention_days: int, delete_batch_size: int) -> int:
        return 0

    def admin_user_count(self) -> int:
        with self._lock:
            return len(self._admin_users)

    def admin_user_get(self, username: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._admin_users.get(username)
            return deepcopy(row) if row is not None else None

    def admin_user_create(self, username: str, password_hash: str, must_change_password: bool = False) -> None:
        with self._lock:
            if username in self._admin_users:
                raise ValueError(f"admin user already exists: {username}")
            now = _now()
            self._admin_users[username] = {
                "id": self._next_admin_id,
                "username": username,
                "password_hash": password_hash,
                "token_version": 0,
                "is_enabled": 1,
                "must_change_password": 1 if must_change_password else 0,
                "last_login_at": None,
                "created_at": now,
                "updated_at": now,
            }
            self._next_admin_id += 1

    def admin_user_update_login_success(self, username: str) -> None:
        with self._lock:
            row = self._admin_users.get(username)
            if row is not None:
                now = _now()
                row["last_login_at"] = now
                row["updated_at"] = now

    def admin_user_bump_token_version(self, username: str) -> None:
        with self._lock:
            row = self._admin_users.get(username)
            if row is not None:
                row["token_version"] = int(row["token_version"]) + 1
                row["updated_at"] = _now()

    def admin_user_change_password(self, username: str, new_password_hash: str) -> None:
        with self._lock:
            row = self._admin_users.get(username)
            if row is not None:
                row["password_hash"] = new_password_hash
                row["token_version"] = int(row["token_version"]) + 1
                row["must_change_password"] = 0
                row["updated_at"] = _now()

    def auth_event_insert(self, event_type: str, username: str, source_ip: str, user_agent: str) -> None:
        with self._lock:
            self._auth_events.append(
                {
                    "event_type": event_type,
                    "username": username,
                    "source_ip": source_ip,
                    "user_agent": user_agent,
                    "event_time": _now(),
                }
            )

    def runtime_config_all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return deepcopy([self._runtime_config[key] for key in sorted(self._runtime_config)])

    def runtime_config_upsert(self, values: Dict[str, Any], changed_by: str, source_ip: str) -> None:
        with self._lock:
            for key, value in values.items():
                now = _now()
                new_json = json.dumps(value, ensure_ascii=False)
                old = self._runtime_config.get(key)
                old_json = old.get("value_json") if old else None
                self._runtime_config[key] = {
                    "config_key": key,
                    "value_json": new_json,
                    "value_type": type(value).__name__,
                    "scope": "runtime",
                    "updated_by": changed_by,
                    "updated_at": now,
                }
                self._runtime_config_history.append(
                    {
                        "id": self._next_config_history_id,
                        "config_key": key,
                        "old_value_json": old_json,
                        "new_value_json": new_json,
                        "changed_by": changed_by,
                        "source_ip": source_ip,
                        "changed_at": now,
                    }
                )
                self._next_config_history_id += 1

    def runtime_config_history(self, page: int, page_size: int) -> Tuple[int, List[Dict[str, Any]]]:
        with self._lock:
            rows = sorted(
                self._runtime_config_history,
                key=lambda row: (row["changed_at"], row["id"]),
                reverse=True,
            )
            return len(rows), deepcopy(self._page(rows, page, page_size))

    def recent_events(self, seconds: int, limit: int) -> List[Dict[str, Any]]:
        threshold = _now() - timedelta(seconds=seconds)
        with self._lock:
            rows = [self._event_result(row) for row in self._access_events if row["event_time"] >= threshold]
            rows.sort(key=lambda row: (row["event_time"], row["id"]), reverse=True)
            return deepcopy(rows[:limit])

    def user_visits(self, email: str, dt_from: datetime, dt_to: datetime, limit: int) -> List[Dict[str, Any]]:
        dt_from, dt_to = _utc_naive(dt_from), _utc_naive(dt_to)
        with self._lock:
            rows = [
                self._access_result(row)
                for row in self._access_events
                if row["user_email"] == email and dt_from <= row["event_time"] <= dt_to
            ]
            rows.sort(key=lambda row: row["event_time"], reverse=True)
            return deepcopy(rows[:limit])

    def user_visits_paged(
        self, email: str, dt_from: datetime, dt_to: datetime, page: int, page_size: int
    ) -> Tuple[int, List[Dict[str, Any]]]:
        dt_from, dt_to = _utc_naive(dt_from), _utc_naive(dt_to)
        with self._lock:
            matched = [
                row
                for row in self._access_events
                if row["user_email"] == email and dt_from <= row["event_time"] <= dt_to
            ]
            matched.sort(key=lambda row: (row["event_time"], row["id"]), reverse=True)
            return len(matched), deepcopy(
                [self._access_result(row) for row in self._page(matched, page, page_size)]
            )

    def query_events(
        self,
        dt_from: datetime,
        dt_to: datetime,
        email: Optional[str],
        dest_host: Optional[str],
        status: Optional[str],
        detour: Optional[str],
        is_domain: Optional[bool],
        page: int,
        page_size: int,
    ) -> Tuple[int, List[Dict[str, Any]]]:
        dt_from, dt_to = _utc_naive(dt_from), _utc_naive(dt_to)
        with self._lock:
            matched = []
            for row in self._access_events:
                if not dt_from <= row["event_time"] <= dt_to:
                    continue
                if email and row["user_email"] != email:
                    continue
                if dest_host and dest_host not in row["dest_host"]:
                    continue
                if status and row["status"] != status:
                    continue
                if detour and detour not in row["detour"]:
                    continue
                if is_domain is not None and bool(row["is_domain"]) != is_domain:
                    continue
                matched.append(row)
            matched.sort(key=lambda row: (row["event_time"], row["id"]), reverse=True)
            return len(matched), deepcopy(
                [self._event_result(row) for row in self._page(matched, page, page_size)]
            )

    def list_users(
        self, dt_from: datetime, dt_to: datetime, page: int, page_size: int
    ) -> Tuple[int, List[Dict[str, Any]]]:
        dt_from, dt_to = _utc_naive(dt_from), _utc_naive(dt_to)
        with self._lock:
            grouped: Dict[str, List[Dict[str, Any]]] = {}
            for row in self._access_events:
                email = row["user_email"]
                if email and email != "unknown" and dt_from <= row["event_time"] <= dt_to:
                    grouped.setdefault(email, []).append(row)
            rows = [
                {
                    "user_email": email,
                    "count": len(events),
                    "last_seen": max(event["event_time"] for event in events),
                    "unique_dest_host_count": len({event["dest_host"] for event in events if event["dest_host"]}),
                }
                for email, events in grouped.items()
            ]
            rows.sort(key=lambda row: row["last_seen"], reverse=True)
            return len(rows), deepcopy(self._page(rows, page, page_size))

    def summary_stats(self, window_seconds: int) -> Dict[str, Any]:
        threshold = _now() - timedelta(seconds=window_seconds)
        with self._lock:
            rows = [row for row in self._access_events if row["event_time"] >= threshold]
            total = len(rows)
            return {
                "total_events": total,
                "unique_users": len({row["user_email"] for row in rows if row["user_email"] not in {"", "unknown"}}),
                "unique_domains": len({row["dest_host"] for row in rows if row["dest_host"] and row["is_domain"]}),
                "qpm": round(total / max(window_seconds / 60.0, 1e-6), 2),
            }

    def query_error_events(
        self,
        dt_from: datetime,
        dt_to: datetime,
        level: Optional[str],
        category: Optional[str],
        include_noise: bool,
        keyword: Optional[str],
        page: int,
        page_size: int,
    ) -> Tuple[int, List[Dict[str, Any]]]:
        dt_from, dt_to = _utc_naive(dt_from), _utc_naive(dt_to)
        needle = (keyword or "").strip().lower()
        with self._lock:
            matched = []
            for row in self._error_events:
                if not dt_from <= row["event_time"] <= dt_to:
                    continue
                if level and row["level"] != level:
                    continue
                if category and row["category"] != category:
                    continue
                if not include_noise and row["is_noise"]:
                    continue
                if needle and not any(needle in str(row[field]).lower() for field in ("component", "message", "src", "dest_raw")):
                    continue
                matched.append(row)
            matched.sort(key=lambda row: (row["event_time"], row["id"]), reverse=True)
            return len(matched), deepcopy(self._page(matched, page, page_size))

    def error_summary_stats(self, window_seconds: int) -> Dict[str, Any]:
        threshold = _now() - timedelta(seconds=window_seconds)
        with self._lock:
            rows = [row for row in self._error_events if row["event_time"] >= threshold]
            levels = Counter(row["level"] for row in rows)
            categories = Counter(row["category"] for row in rows)
            top_categories = [
                {"category": category, "hits": hits}
                for category, hits in sorted(categories.items(), key=lambda item: (-item[1], item[0]))[:10]
            ]
            return {
                "total": len(rows),
                "error_count": levels["error"],
                "warning_count": levels["warning"],
                "info_count": levels["info"],
                "noise_count": sum(bool(row["is_noise"]) for row in rows),
                "top_categories": top_categories,
            }

    def error_summary_payload(self, dt_from: datetime, dt_to: datetime, max_items: int) -> Dict[str, Any]:
        dt_from, dt_to = _utc_naive(dt_from), _utc_naive(dt_to)
        with self._lock:
            rows = [row for row in self._error_events if dt_from < row["event_time"] <= dt_to]
            level_category_counts = Counter((row["level"], row["category"]) for row in rows)
            level_category = [
                {"level": key[0], "category": key[1], "hits": hits}
                for key, hits in sorted(level_category_counts.items(), key=lambda item: (-item[1], item[0]))[:max_items]
            ]
            signature_groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
            for row in rows:
                signature_groups.setdefault((row["category"], row["signature_hash"]), []).append(row)
            signatures = []
            for (category, signature_hash), events in signature_groups.items():
                sample = events[0]
                signatures.append(
                    {
                        "category": category,
                        "signature_hash": signature_hash,
                        "hits": len(events),
                        "latest_time": max(event["event_time"] for event in events),
                        "min_level": min(event["level"] for event in events),
                        "max_level": max(event["level"] for event in events),
                        "component": sample["component"],
                        "sample_message": sample["message"],
                    }
                )
            signatures.sort(key=lambda row: (-row["hits"], row["category"], row["signature_hash"]))
            recent = sorted(rows, key=lambda row: (row["event_time"], row["id"]), reverse=True)[:max_items]
            recent_fields = ("event_time", "level", "category", "component", "message", "src", "dest_raw")
            return deepcopy(
                {
                    "from": dt_from,
                    "to": dt_to,
                    "total": len(rows),
                    "level_category": level_category,
                    "top_signatures": signatures[:max_items],
                    "recent_examples": [{key: row[key] for key in recent_fields} for row in recent],
                }
            )

    def job_state_get(self, key: str) -> Optional[str]:
        with self._lock:
            return self._job_states.get(key)

    def job_state_set(self, key: str, value: str) -> None:
        with self._lock:
            self._job_states[key] = value

    def geo_cache_get(self, ips: List[str], ttl_hours: int) -> Dict[str, Dict[str, Any]]:
        threshold = _now() - timedelta(hours=ttl_hours)
        with self._lock:
            return deepcopy(
                {ip: self._geo_cache[ip] for ip in ips if ip in self._geo_cache and self._geo_cache[ip]["updated_at"] >= threshold}
            )

    def geo_cache_upsert(self, rows: List[Dict[str, Any]]) -> None:
        with self._lock:
            for source in rows:
                ip = str(source.get("ip", ""))
                self._geo_cache[ip] = {
                    "ip": ip,
                    "country": source.get("country", ""),
                    "region": source.get("region", ""),
                    "city": source.get("city", ""),
                    "isp": source.get("isp", ""),
                    "addr": source.get("addr", ""),
                    "status": source.get("status", "ok"),
                    "source": source.get("source", "pconline"),
                    "updated_at": _now(),
                }

    def top_domains(self, seconds: int, limit: int) -> List[Dict[str, Any]]:
        threshold = _now() - timedelta(seconds=seconds)
        with self._lock:
            counts = Counter(
                row["dest_host"]
                for row in self._access_events
                if row["event_time"] >= threshold and row["dest_host"] and row["is_domain"]
            )
            return [
                {"domain": domain, "hits": hits}
                for domain, hits in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
            ]

    def active_users(self, seconds: int, limit: int) -> List[Dict[str, Any]]:
        threshold = _now() - timedelta(seconds=seconds)
        with self._lock:
            latest: Dict[str, datetime] = {}
            for row in self._access_events:
                email = row["user_email"]
                if email and row["event_time"] >= threshold:
                    latest[email] = max(latest.get(email, row["event_time"]), row["event_time"])
            ordered = sorted(latest.items(), key=lambda item: item[1], reverse=True)[:limit]
            return [
                {
                    "user_email": email,
                    "last_seen_unix": int(seen.replace(tzinfo=timezone.utc).timestamp()),
                }
                for email, seen in ordered
            ]

    @staticmethod
    def _page(rows: List[Dict[str, Any]], page: int, page_size: int) -> List[Dict[str, Any]]:
        offset = (page - 1) * page_size
        return rows[offset : offset + page_size]

    @staticmethod
    def _access_result(row: Dict[str, Any]) -> Dict[str, Any]:
        fields = (
            "event_time",
            "user_email",
            "src",
            "dest_host",
            "dest_port",
            "protocol",
            "status",
            "detour",
            "reason",
            "is_domain",
            "node_id",
        )
        return {field: row[field] for field in fields}

    @staticmethod
    def _event_result(row: Dict[str, Any]) -> Dict[str, Any]:
        result = {
            "id": row["id"],
            "event_time": row["event_time"],
            "node_id": row["node_id"],
        }
        for field in (
            "user_email", "src", "dest_host", "dest_port", "protocol", "status", "detour", "reason", "is_domain",
        ):
            result[field] = row.get(field)
        return result
