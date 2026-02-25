from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .config import Settings
from .storage import AuditQueryService


@dataclass(frozen=True)
class RuntimeConfigField:
    config_key: str
    group: str
    label: str
    description: str
    value_type: str
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    options: Optional[Tuple[str, ...]] = None


GROUP_LABELS: Dict[str, str] = {
    "collector": "Collector",
    "filter": "Filter",
    "retention": "Retention",
    "geoip": "GeoIP",
    "cache": "Cache",
}


EDITABLE_FIELDS: Dict[str, RuntimeConfigField] = {
    "AUDIT_BATCH_SIZE": RuntimeConfigField(
        config_key="AUDIT_BATCH_SIZE",
        group="collector",
        label="Batch Size",
        description="Maximum parsed rows buffered before flush.",
        value_type="int",
        min_value=1,
        max_value=20000,
    ),
    "AUDIT_FLUSH_INTERVAL_SECONDS": RuntimeConfigField(
        config_key="AUDIT_FLUSH_INTERVAL_SECONDS",
        group="collector",
        label="Flush Interval Seconds",
        description="Maximum flush interval even if batch is not full.",
        value_type="float",
        min_value=0.1,
        max_value=30.0,
    ),
    "AUDIT_POLL_INTERVAL_SECONDS": RuntimeConfigField(
        config_key="AUDIT_POLL_INTERVAL_SECONDS",
        group="collector",
        label="Poll Interval Seconds",
        description="Tailer sleep interval when no new lines.",
        value_type="float",
        min_value=0.05,
        max_value=10.0,
    ),
    "AUDIT_ERROR_MIN_LEVEL": RuntimeConfigField(
        config_key="AUDIT_ERROR_MIN_LEVEL",
        group="filter",
        label="Error Min Level",
        description="Minimum level to ingest from error log.",
        value_type="enum",
        options=("debug", "info", "warning", "error"),
    ),
    "AUDIT_ERROR_DROP_NOISE": RuntimeConfigField(
        config_key="AUDIT_ERROR_DROP_NOISE",
        group="filter",
        label="Drop Error Noise",
        description="Drop known noisy error categories at collector side.",
        value_type="bool",
    ),
    "AUDIT_DROP_API_TO_API": RuntimeConfigField(
        config_key="AUDIT_DROP_API_TO_API",
        group="filter",
        label="Drop API->API",
        description="Drop access events with detour exactly 'api -> api'.",
        value_type="bool",
    ),
    "AUDIT_DROP_LOOPBACK_TRAFFIC": RuntimeConfigField(
        config_key="AUDIT_DROP_LOOPBACK_TRAFFIC",
        group="filter",
        label="Drop Loopback Traffic",
        description="Drop loopback source/destination access traffic.",
        value_type="bool",
    ),
    "AUDIT_DROP_INVALID_VLESS_PROBE": RuntimeConfigField(
        config_key="AUDIT_DROP_INVALID_VLESS_PROBE",
        group="filter",
        label="Drop Invalid VLESS Probe",
        description="Drop rejected invalid-request-version VLESS probe noise.",
        value_type="bool",
    ),
    "AUDIT_EXCLUDE_DETOURS": RuntimeConfigField(
        config_key="AUDIT_EXCLUDE_DETOURS",
        group="filter",
        label="Exclude Detours",
        description="Comma separated detours to drop.",
        value_type="csv",
    ),
    "AUDIT_RETENTION_DAYS": RuntimeConfigField(
        config_key="AUDIT_RETENTION_DAYS",
        group="retention",
        label="Retention Days",
        description="Keep at most this many days in audit tables.",
        value_type="int",
        min_value=1,
        max_value=3650,
    ),
    "AUDIT_RETENTION_CLEANUP_INTERVAL_SECONDS": RuntimeConfigField(
        config_key="AUDIT_RETENTION_CLEANUP_INTERVAL_SECONDS",
        group="retention",
        label="Retention Cleanup Interval Seconds",
        description="How often retention cleanup job runs.",
        value_type="int",
        min_value=60,
        max_value=86400,
    ),
    "AUDIT_RETENTION_DELETE_BATCH_SIZE": RuntimeConfigField(
        config_key="AUDIT_RETENTION_DELETE_BATCH_SIZE",
        group="retention",
        label="Retention Delete Batch Size",
        description="Rows deleted per retention SQL batch.",
        value_type="int",
        min_value=100,
        max_value=200000,
    ),
    "AUDIT_GEOIP_ENABLED": RuntimeConfigField(
        config_key="AUDIT_GEOIP_ENABLED",
        group="geoip",
        label="GeoIP Enabled",
        description="Enable remote GeoIP lookups for source IP.",
        value_type="bool",
    ),
    "AUDIT_GEOIP_TIMEOUT_SECONDS": RuntimeConfigField(
        config_key="AUDIT_GEOIP_TIMEOUT_SECONDS",
        group="geoip",
        label="GeoIP Timeout Seconds",
        description="HTTP timeout for GeoIP provider requests.",
        value_type="float",
        min_value=0.5,
        max_value=30.0,
    ),
    "AUDIT_GEOIP_CACHE_TTL_HOURS": RuntimeConfigField(
        config_key="AUDIT_GEOIP_CACHE_TTL_HOURS",
        group="geoip",
        label="GeoIP Cache TTL Hours",
        description="Cache time for IP geo results in DB.",
        value_type="int",
        min_value=1,
        max_value=8760,
    ),
    "AUDIT_GEOIP_BATCH_LIMIT": RuntimeConfigField(
        config_key="AUDIT_GEOIP_BATCH_LIMIT",
        group="geoip",
        label="GeoIP Batch Limit",
        description="Maximum IP count allowed in one batch API call.",
        value_type="int",
        min_value=1,
        max_value=2000,
    ),
    "AUDIT_REDIS_ENABLED": RuntimeConfigField(
        config_key="AUDIT_REDIS_ENABLED",
        group="cache",
        label="Redis Enabled",
        description="Enable redis-backed realtime cache paths.",
        value_type="bool",
    ),
    "AUDIT_AI_SUMMARY_ENABLED": RuntimeConfigField(
        config_key="AUDIT_AI_SUMMARY_ENABLED",
        group="collector",
        label="AI Summary Enabled",
        description="Toggle AI summary worker loop without restart.",
        value_type="bool",
    ),
    "AUDIT_AI_SUMMARY_INTERVAL_SECONDS": RuntimeConfigField(
        config_key="AUDIT_AI_SUMMARY_INTERVAL_SECONDS",
        group="collector",
        label="AI Summary Interval Seconds",
        description="Polling interval for AI summary worker.",
        value_type="int",
        min_value=10,
        max_value=86400,
    ),
    "AUDIT_AI_SUMMARY_WINDOW_MINUTES": RuntimeConfigField(
        config_key="AUDIT_AI_SUMMARY_WINDOW_MINUTES",
        group="collector",
        label="AI Summary Window Minutes",
        description="Window size for AI summary payload.",
        value_type="int",
        min_value=1,
        max_value=1440,
    ),
    "AUDIT_AI_SUMMARY_MAX_ITEMS": RuntimeConfigField(
        config_key="AUDIT_AI_SUMMARY_MAX_ITEMS",
        group="collector",
        label="AI Summary Max Items",
        description="Maximum aggregated rows passed to LLM summary.",
        value_type="int",
        min_value=20,
        max_value=5000,
    ),
}


def _defaults_from_settings(settings: Settings) -> Dict[str, Any]:
    return {
        "AUDIT_BATCH_SIZE": settings.batch_size,
        "AUDIT_FLUSH_INTERVAL_SECONDS": settings.flush_interval_seconds,
        "AUDIT_POLL_INTERVAL_SECONDS": settings.poll_interval_seconds,
        "AUDIT_ERROR_MIN_LEVEL": settings.error_min_level,
        "AUDIT_ERROR_DROP_NOISE": settings.error_drop_noise,
        "AUDIT_DROP_API_TO_API": settings.drop_api_to_api,
        "AUDIT_DROP_LOOPBACK_TRAFFIC": settings.drop_loopback_traffic,
        "AUDIT_DROP_INVALID_VLESS_PROBE": settings.drop_invalid_vless_probe,
        "AUDIT_EXCLUDE_DETOURS": ",".join(settings.exclude_detours),
        "AUDIT_RETENTION_DAYS": settings.retention_days,
        "AUDIT_RETENTION_CLEANUP_INTERVAL_SECONDS": settings.retention_cleanup_interval_seconds,
        "AUDIT_RETENTION_DELETE_BATCH_SIZE": settings.retention_delete_batch_size,
        "AUDIT_GEOIP_ENABLED": settings.geoip_enabled,
        "AUDIT_GEOIP_TIMEOUT_SECONDS": settings.geoip_timeout_seconds,
        "AUDIT_GEOIP_CACHE_TTL_HOURS": settings.geoip_cache_ttl_hours,
        "AUDIT_GEOIP_BATCH_LIMIT": settings.geoip_batch_limit,
        "AUDIT_REDIS_ENABLED": settings.redis_enabled,
        "AUDIT_AI_SUMMARY_ENABLED": settings.ai_summary_enabled,
        "AUDIT_AI_SUMMARY_INTERVAL_SECONDS": settings.ai_summary_interval_seconds,
        "AUDIT_AI_SUMMARY_WINDOW_MINUTES": settings.ai_summary_window_minutes,
        "AUDIT_AI_SUMMARY_MAX_ITEMS": settings.ai_summary_max_items,
    }


class RuntimeConfigManager:
    def __init__(self, settings: Settings, query_service: AuditQueryService) -> None:
        self.settings = settings
        self.query_service = query_service
        self._lock = threading.Lock()
        self._defaults = _defaults_from_settings(settings)
        self._overrides: Dict[str, Any] = {}
        self._override_meta: Dict[str, Dict[str, Any]] = {}
        self._last_refresh = 0.0
        self._ttl_seconds = max(1.0, float(settings.runtime_config_refresh_seconds))

    def refresh(self, force: bool = False) -> None:
        now = time.monotonic()
        with self._lock:
            if not force and (now - self._last_refresh) < self._ttl_seconds:
                return
            rows = self.query_service.runtime_config_all()
            overrides: Dict[str, Any] = {}
            meta: Dict[str, Dict[str, Any]] = {}
            for row in rows:
                key = str(row.get("config_key", "") or "")
                if key not in EDITABLE_FIELDS:
                    continue
                raw_json = row.get("value_json")
                if raw_json is None:
                    continue
                try:
                    parsed = json.loads(str(raw_json))
                except Exception:
                    continue
                try:
                    value = _normalize_value(EDITABLE_FIELDS[key], parsed)
                except Exception:
                    continue
                overrides[key] = value
                meta[key] = {
                    "updated_by": row.get("updated_by"),
                    "updated_at": row.get("updated_at"),
                }

            self._overrides = overrides
            self._override_meta = meta
            self._last_refresh = now

    def get(self, key: str, fallback: Any = None) -> Any:
        self.refresh()
        with self._lock:
            if key in self._overrides:
                return self._overrides[key]
        if key in self._defaults:
            return self._defaults[key]
        return fallback

    def get_bool(self, key: str, fallback: bool) -> bool:
        value = self.get(key, fallback)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        txt = str(value).strip().lower()
        return txt in {"1", "true", "yes", "on"}

    def get_int(self, key: str, fallback: int) -> int:
        value = self.get(key, fallback)
        try:
            return int(value)
        except Exception:
            return fallback

    def get_float(self, key: str, fallback: float) -> float:
        value = self.get(key, fallback)
        try:
            return float(value)
        except Exception:
            return fallback

    def get_csv_tuple(self, key: str, fallback: Tuple[str, ...]) -> Tuple[str, ...]:
        value = self.get(key, ",".join(fallback))
        if isinstance(value, list):
            return tuple(str(x).strip() for x in value if str(x).strip())
        parts = [x.strip() for x in str(value).split(",")]
        return tuple(x for x in parts if x)

    def schema_items(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for key, field in EDITABLE_FIELDS.items():
            out.append(
                {
                    "config_key": key,
                    "group": field.group,
                    "group_label": GROUP_LABELS.get(field.group, field.group),
                    "label": field.label,
                    "description": field.description,
                    "value_type": field.value_type,
                    "min_value": field.min_value,
                    "max_value": field.max_value,
                    "options": list(field.options or []),
                    "default_value": self._defaults.get(key),
                    "editable": True,
                    "sensitive": False,
                }
            )
        return out

    def current_items(self) -> List[Dict[str, Any]]:
        self.refresh()
        out: List[Dict[str, Any]] = []
        with self._lock:
            for key in EDITABLE_FIELDS.keys():
                if key in self._overrides:
                    value = self._overrides[key]
                    source = "db"
                    meta = self._override_meta.get(key, {})
                else:
                    value = self._defaults.get(key)
                    source = "env"
                    meta = {}
                out.append(
                    {
                        "config_key": key,
                        "value": value,
                        "source": source,
                        "updated_by": meta.get("updated_by"),
                        "updated_at": meta.get("updated_at"),
                    }
                )
        return out

    def update_items(self, values: Dict[str, Any], changed_by: str, source_ip: str) -> List[Dict[str, Any]]:
        if not isinstance(values, dict):
            raise ValueError("values must be an object")
        normalized: Dict[str, Any] = {}
        for key, raw_value in values.items():
            if key not in EDITABLE_FIELDS:
                raise ValueError(f"unsupported config key: {key}")
            normalized[key] = _normalize_value(EDITABLE_FIELDS[key], raw_value)

        self.query_service.runtime_config_upsert(
            values=normalized,
            changed_by=changed_by,
            source_ip=source_ip,
        )
        self.refresh(force=True)
        return self.current_items()


def _normalize_value(field: RuntimeConfigField, raw: Any) -> Any:
    if field.value_type == "bool":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return raw != 0
        txt = str(raw).strip().lower()
        if txt in {"1", "true", "yes", "on"}:
            return True
        if txt in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"{field.config_key} expects bool")

    if field.value_type == "int":
        try:
            value = int(raw)
        except Exception as err:
            raise ValueError(f"{field.config_key} expects int: {err}")
        _check_range(field, float(value))
        return value

    if field.value_type == "float":
        try:
            value = float(raw)
        except Exception as err:
            raise ValueError(f"{field.config_key} expects float: {err}")
        _check_range(field, value)
        return value

    if field.value_type == "enum":
        value = str(raw).strip().lower()
        options = set(field.options or ())
        if value not in options:
            raise ValueError(f"{field.config_key} expects one of {sorted(options)}")
        return value

    if field.value_type == "csv":
        if isinstance(raw, list):
            values = [str(x).strip() for x in raw if str(x).strip()]
            return ",".join(values)
        values = [x.strip() for x in str(raw).split(",")]
        return ",".join([x for x in values if x])

    return str(raw)


def _check_range(field: RuntimeConfigField, value: float) -> None:
    if field.min_value is not None and value < field.min_value:
        raise ValueError(f"{field.config_key} must be >= {field.min_value}")
    if field.max_value is not None and value > field.max_value:
        raise ValueError(f"{field.config_key} must be <= {field.max_value}")
