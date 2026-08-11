from __future__ import annotations

import threading
from dataclasses import replace
from typing import Any, Dict

from .config import Settings
from .control_store import ControlStore
from .memory_storage import MemoryStorage
from .storage_factory import create_storage_pair


_CONTROL_METHODS = {
    "collector_state",
    "admin_user_count", "admin_user_get", "admin_user_create", "admin_user_update_login_success",
    "admin_user_bump_token_version", "admin_user_change_password", "auth_event_insert",
    "runtime_config_all", "runtime_config_upsert", "runtime_config_history",
}
_ERROR_METHODS = {"query_error_events", "error_summary_stats", "error_summary_payload"}


class RoutedQueryService:
    def __init__(self, control: ControlStore, audit_query: Any, error_query: MemoryStorage) -> None:
        self.control = control
        self._audit_query = audit_query
        self._error_query = error_query
        self._lock = threading.RLock()

    def replace_audit_query(self, query: Any) -> None:
        with self._lock:
            self._audit_query = query

    def __getattr__(self, name: str) -> Any:
        target = self.control if name in _CONTROL_METHODS else self._error_query if name in _ERROR_METHODS else self._audit_query
        return getattr(target, name)


class RoutedIngestor:
    """Persist collector cursors locally while routing audit events externally."""

    def __init__(self, control: ControlStore, audit_ingestor: Any, error_storage: MemoryStorage) -> None:
        self.control = control
        self._audit_ingestor = audit_ingestor
        self._error_storage = error_storage

    def load_state(self, file_path: str):
        return self.control.load_state(file_path)

    def save_state(self, file_path: str, inode: int | None, offset: int) -> None:
        self.control.save_state(file_path, inode, offset)

    def ingest_events(self, events, node_id: str):
        return self._audit_ingestor.ingest_events(events, node_id)

    def ingest_error_events(self, events, node_id: str):
        return self._error_storage.ingest_error_events(events, node_id)

    def prune_old_events(self, retention_days: int, delete_batch_size: int) -> int:
        return self._audit_ingestor.prune_old_events(retention_days, delete_batch_size)

    def close(self) -> None:
        return None


class StorageManager:
    def __init__(self, settings: Settings) -> None:
        self.base_settings = settings
        self.control = ControlStore(settings)
        self._error_storage = MemoryStorage(settings)
        self._lock = threading.RLock()
        initial = self._settings_for_initial_backend(settings)
        try:
            audit_ingestor, query = create_storage_pair(initial)
            query.collector_state(initial.log_path)
            self.active_settings = initial
        except Exception:
            self.active_settings = replace(settings, storage_backend="memory")
            audit_ingestor, query = create_storage_pair(self.active_settings)
        self._audit_ingestor = audit_ingestor
        self.ingestor = RoutedIngestor(self.control, audit_ingestor, self._error_storage)
        self.query = RoutedQueryService(self.control, query, self._error_storage)

    def _settings_for_initial_backend(self, settings: Settings) -> Settings:
        saved = self.control.load_storage_config()
        backend = saved["active_backend"] if saved["exists"] else settings.storage_backend
        if backend not in {"memory", "mysql", "d1"}:
            backend = "memory"
        if backend == "memory":
            return replace(settings, storage_backend="memory")
        try:
            return self._candidate_settings(backend, saved["config"], saved["secrets"])
        except Exception:
            return replace(settings, storage_backend="memory")

    def _candidate_settings(self, backend: str, config: Dict[str, Any], secrets: Dict[str, str]) -> Settings:
        if backend not in {"memory", "mysql", "d1"}:
            raise ValueError("backend must be memory, mysql, or d1")
        values: Dict[str, Any] = {"storage_backend": backend}
        allowed = {
            "mysql_host", "mysql_port", "mysql_user", "mysql_db", "mysql_charset",
            "d1_gateway_url", "d1_timeout_seconds", "d1_batch_size", "d1_max_retries",
        }
        values.update({key: value for key, value in config.items() if key in allowed})
        if secrets.get("mysql_password"):
            values["mysql_password"] = secrets["mysql_password"]
        if secrets.get("d1_gateway_token"):
            values["d1_gateway_token"] = secrets["d1_gateway_token"]
        return replace(self.base_settings, **values)

    def public_config(self) -> Dict[str, Any]:
        saved = self.control.load_storage_config()
        defaults = self.base_settings
        config = {
            "mysql_host": saved["config"].get("mysql_host", defaults.mysql_host),
            "mysql_port": int(saved["config"].get("mysql_port", defaults.mysql_port)),
            "mysql_user": saved["config"].get("mysql_user", defaults.mysql_user),
            "mysql_db": saved["config"].get("mysql_db", defaults.mysql_db),
            "mysql_charset": saved["config"].get("mysql_charset", defaults.mysql_charset),
            "d1_gateway_url": saved["config"].get("d1_gateway_url", defaults.d1_gateway_url),
            "d1_timeout_seconds": float(saved["config"].get("d1_timeout_seconds", defaults.d1_timeout_seconds)),
            "d1_batch_size": int(saved["config"].get("d1_batch_size", defaults.d1_batch_size)),
            "d1_max_retries": int(saved["config"].get("d1_max_retries", defaults.d1_max_retries)),
            "mysql_password_configured": bool(saved["secrets"].get("mysql_password")),
            "d1_gateway_token_configured": bool(saved["secrets"].get("d1_gateway_token")),
        }
        return {
            "active_backend": self.active_settings.storage_backend,
            "pending_backend": saved["pending_backend"], "status": saved["status"], "config": config,
            "memory": {
                "max_access_events": defaults.memory_max_access_events,
                "max_error_events": defaults.memory_max_error_events,
                "max_dns_events": defaults.memory_max_dns_events,
                "persistent": False, "data_lost_on_restart": True,
            },
        }

    def save_pending(self, backend: str, config: Dict[str, Any]) -> None:
        secrets = {
            key: str(config[key]) for key in ("mysql_password", "d1_gateway_token") if config.get(key)
        }
        plain = {
            key: value for key, value in config.items()
            if key not in {"mysql_password", "d1_gateway_token"}
        }
        self.control.save_storage_config(backend, plain, secrets)

    def test(self, backend: str, config: Dict[str, Any] | None = None) -> None:
        saved = self.control.load_storage_config()
        merged = {**saved["config"], **(config or {})}
        secrets = dict(saved["secrets"])
        for key in ("mysql_password", "d1_gateway_token"):
            if (config or {}).get(key):
                secrets[key] = str(config[key])
        candidate = self._candidate_settings(backend, merged, secrets)
        ingestor, query = create_storage_pair(candidate)
        try:
            query.collector_state(candidate.log_path)
        finally:
            ingestor.close()
            close = getattr(query, "close", None)
            if close:
                close()

    def activate(self, backend: str) -> tuple[Settings, Any]:
        saved = self.control.load_storage_config()
        candidate = self._candidate_settings(backend, saved["config"], saved["secrets"])
        new_ingestor, new_query = create_storage_pair(candidate)
        try:
            new_query.collector_state(candidate.log_path)
        except Exception:
            new_ingestor.close()
            close = getattr(new_query, "close", None)
            if close:
                close()
            raise
        with self._lock:
            old_ingestor = self._audit_ingestor
            old_query = self.query._audit_query
            self._audit_ingestor = new_ingestor
            self.ingestor = RoutedIngestor(self.control, new_ingestor, self._error_storage)
            self.query.replace_audit_query(new_query)
            self.active_settings = candidate
            self.control.mark_storage_active(backend)
        old_ingestor.close()
        close = getattr(old_query, "close", None)
        if close and old_query is not old_ingestor:
            close()
        return candidate, self.ingestor

    def close(self) -> None:
        self._audit_ingestor.close()
        query = self.query._audit_query
        close = getattr(query, "close", None)
        if close and query is not self._audit_ingestor:
            close()
        self._error_storage.close()
