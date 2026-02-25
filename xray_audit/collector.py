from __future__ import annotations

import signal
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from .config import Settings
from .error_parser import level_rank, parse_error_line
from .filtering import should_drop_event
from .models import ParsedErrorEvent, ParsedEvent
from .parser import parse_line
from .redis_cache import RedisCache
from .runtime_config import RuntimeConfigManager
from .storage import AuditQueryService, MySQLIngestor
from .tailer import LogTailer


@dataclass
class CollectorStats:
    started_at: datetime
    lines_read_total: int = 0
    parse_fail_total: int = 0
    filtered_total: int = 0
    error_lines_read_total: int = 0
    error_parse_fail_total: int = 0
    error_filtered_total: int = 0
    batches_flushed: int = 0
    raw_written_total: int = 0
    access_written_total: int = 0
    dns_written_total: int = 0
    error_written_total: int = 0
    retention_deleted_total: int = 0
    db_write_fail_total: int = 0
    db_last_write_latency_ms: float = 0.0
    last_event_time: Optional[datetime] = None
    last_error_event_time: Optional[datetime] = None
    last_flush_time: Optional[datetime] = None
    last_retention_time: Optional[datetime] = None
    last_error: str = ""
    inode: Optional[int] = None
    offset: int = 0
    error_inode: Optional[int] = None
    error_offset: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "started_at": self.started_at,
            "lines_read_total": self.lines_read_total,
            "parse_fail_total": self.parse_fail_total,
            "filtered_total": self.filtered_total,
            "error_lines_read_total": self.error_lines_read_total,
            "error_parse_fail_total": self.error_parse_fail_total,
            "error_filtered_total": self.error_filtered_total,
            "batches_flushed": self.batches_flushed,
            "raw_written_total": self.raw_written_total,
            "access_written_total": self.access_written_total,
            "dns_written_total": self.dns_written_total,
            "error_written_total": self.error_written_total,
            "retention_deleted_total": self.retention_deleted_total,
            "db_write_fail_total": self.db_write_fail_total,
            "db_last_write_latency_ms": self.db_last_write_latency_ms,
            "last_event_time": self.last_event_time,
            "last_error_event_time": self.last_error_event_time,
            "last_flush_time": self.last_flush_time,
            "last_retention_time": self.last_retention_time,
            "last_error": self.last_error,
            "inode": self.inode,
            "offset": self.offset,
            "error_inode": self.error_inode,
            "error_offset": self.error_offset,
        }


class AuditCollector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.ingestor = MySQLIngestor(settings)
        self.query_service = AuditQueryService(settings)
        self.runtime_config = RuntimeConfigManager(settings, self.query_service)
        self.redis_cache = RedisCache(settings)
        self.tailer = LogTailer(settings.log_path)
        self.error_tailer = LogTailer(settings.error_log_path) if settings.error_log_enabled else None

        self.stats = CollectorStats(started_at=datetime.utcnow())
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def close(self) -> None:
        self.tailer.close()
        if self.error_tailer is not None:
            self.error_tailer.close()
        self.ingestor.close()

    def stats_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return self.stats.as_dict()

    def _set_error(self, err: Exception) -> None:
        with self._lock:
            self.stats.last_error = str(err)

    def _publish_health(self) -> None:
        if not self.runtime_config.get_bool("AUDIT_REDIS_ENABLED", self.settings.redis_enabled):
            return
        payload = self.stats_snapshot()
        payload["node_id"] = self.settings.node_id
        self.redis_cache.publish_health(payload)

    def _flush(self, batch: List[ParsedEvent], error_batch: List[ParsedErrorEvent]) -> None:
        if not batch and not error_batch:
            return

        started = time.perf_counter()
        raw_counts = {"raw": 0, "access": 0, "dns": 0}
        if batch:
            raw_counts = self.ingestor.ingest_events(batch, node_id=self.settings.node_id)
            if self.runtime_config.get_bool("AUDIT_REDIS_ENABLED", self.settings.redis_enabled):
                self.redis_cache.update_from_events(batch)

        inode, offset = self.tailer.state()
        self.ingestor.save_state(self.settings.log_path, inode, offset)

        error_written = 0
        error_inode: Optional[int] = None
        error_offset: int = 0
        if self.error_tailer is not None:
            error_inode, error_offset = self.error_tailer.state()
            self.ingestor.save_state(self.settings.error_log_path, error_inode, error_offset)
            if error_batch:
                error_written = self.ingestor.ingest_error_events(error_batch, node_id=self.settings.node_id)

        with self._lock:
            self.stats.batches_flushed += 1
            self.stats.raw_written_total += raw_counts.get("raw", 0)
            self.stats.access_written_total += raw_counts.get("access", 0)
            self.stats.dns_written_total += raw_counts.get("dns", 0)
            self.stats.error_written_total += error_written
            self.stats.db_last_write_latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
            self.stats.last_flush_time = datetime.utcnow()
            self.stats.inode = inode
            self.stats.offset = offset
            self.stats.error_inode = error_inode
            self.stats.error_offset = error_offset
            self.stats.last_error = ""

        self._publish_health()

    def run_forever(self) -> None:
        inode, offset = self.ingestor.load_state(self.settings.log_path)
        self.tailer.set_state(inode, offset)

        with self._lock:
            self.stats.inode = inode
            self.stats.offset = offset
        if self.error_tailer is not None:
            err_inode, err_offset = self.ingestor.load_state(self.settings.error_log_path)
            self.error_tailer.set_state(err_inode, err_offset)
            with self._lock:
                self.stats.error_inode = err_inode
                self.stats.error_offset = err_offset

        last_flush = time.monotonic()
        last_retention = 0.0

        batch: List[ParsedEvent] = []
        error_batch: List[ParsedErrorEvent] = []

        while not self._stop_event.is_set():
            try:
                batch_size = max(1, self.runtime_config.get_int("AUDIT_BATCH_SIZE", self.settings.batch_size))
                flush_interval = max(
                    0.1,
                    self.runtime_config.get_float("AUDIT_FLUSH_INTERVAL_SECONDS", self.settings.flush_interval_seconds),
                )
                poll_interval = max(
                    0.05,
                    self.runtime_config.get_float("AUDIT_POLL_INTERVAL_SECONDS", self.settings.poll_interval_seconds),
                )
                min_error_level_rank = level_rank(
                    str(self.runtime_config.get("AUDIT_ERROR_MIN_LEVEL", self.settings.error_min_level)).strip().lower()
                )
                error_drop_noise = self.runtime_config.get_bool(
                    "AUDIT_ERROR_DROP_NOISE",
                    self.settings.error_drop_noise,
                )
                filter_settings = SimpleNamespace(
                    drop_api_to_api=self.runtime_config.get_bool(
                        "AUDIT_DROP_API_TO_API",
                        self.settings.drop_api_to_api,
                    ),
                    drop_loopback_traffic=self.runtime_config.get_bool(
                        "AUDIT_DROP_LOOPBACK_TRAFFIC",
                        self.settings.drop_loopback_traffic,
                    ),
                    drop_invalid_vless_probe=self.runtime_config.get_bool(
                        "AUDIT_DROP_INVALID_VLESS_PROBE",
                        self.settings.drop_invalid_vless_probe,
                    ),
                    exclude_detours=self.runtime_config.get_csv_tuple(
                        "AUDIT_EXCLUDE_DETOURS",
                        self.settings.exclude_detours,
                    ),
                )

                lines = self.tailer.read_new_lines(max_lines=max(64, batch_size * 4))
                error_lines: List[str] = []
                if self.error_tailer is not None:
                    error_lines = self.error_tailer.read_new_lines(max_lines=max(32, batch_size * 2))

                if lines:
                    for line in lines:
                        with self._lock:
                            self.stats.lines_read_total += 1

                        parsed = parse_line(line)
                        if parsed is None:
                            with self._lock:
                                self.stats.parse_fail_total += 1
                            continue
                        if should_drop_event(parsed, filter_settings):
                            with self._lock:
                                self.stats.filtered_total += 1
                            continue

                        batch.append(parsed)
                        with self._lock:
                            self.stats.last_event_time = parsed.event_time

                    inode, offset = self.tailer.state()
                    with self._lock:
                        self.stats.inode = inode
                        self.stats.offset = offset

                if error_lines:
                    for line in error_lines:
                        with self._lock:
                            self.stats.error_lines_read_total += 1

                        parsed_error = parse_error_line(line)
                        if parsed_error is None:
                            with self._lock:
                                self.stats.error_parse_fail_total += 1
                            continue

                        if level_rank(parsed_error.level) < min_error_level_rank:
                            with self._lock:
                                self.stats.error_filtered_total += 1
                            continue
                        if error_drop_noise and parsed_error.is_noise:
                            with self._lock:
                                self.stats.error_filtered_total += 1
                            continue

                        error_batch.append(parsed_error)
                        with self._lock:
                            self.stats.last_error_event_time = parsed_error.event_time

                    if self.error_tailer is not None:
                        err_inode, err_offset = self.error_tailer.state()
                        with self._lock:
                            self.stats.error_inode = err_inode
                            self.stats.error_offset = err_offset

                now = time.monotonic()
                should_flush = bool(batch or error_batch) and (
                    len(batch) >= batch_size
                    or len(error_batch) >= batch_size
                    or (now - last_flush) >= flush_interval
                )
                if should_flush:
                    self._flush(batch, error_batch)
                    batch = []
                    error_batch = []
                    last_flush = now

                # Retention policy: keep only recent history.
                retention_days = max(
                    1,
                    self.runtime_config.get_int("AUDIT_RETENTION_DAYS", self.settings.retention_days),
                )
                retention_cleanup_interval_seconds = max(
                    60,
                    self.runtime_config.get_int(
                        "AUDIT_RETENTION_CLEANUP_INTERVAL_SECONDS",
                        self.settings.retention_cleanup_interval_seconds,
                    ),
                )
                retention_delete_batch_size = max(
                    100,
                    self.runtime_config.get_int(
                        "AUDIT_RETENTION_DELETE_BATCH_SIZE",
                        self.settings.retention_delete_batch_size,
                    ),
                )
                if (
                    retention_days > 0
                    and (now - last_retention) >= retention_cleanup_interval_seconds
                ):
                    deleted = self.ingestor.prune_old_events(
                        retention_days=retention_days,
                        delete_batch_size=retention_delete_batch_size,
                    )
                    with self._lock:
                        self.stats.retention_deleted_total += deleted
                        self.stats.last_retention_time = datetime.utcnow()
                    self._publish_health()
                    last_retention = now

                if not lines and not error_lines:
                    self._publish_health()
                    time.sleep(poll_interval)
            except Exception as err:
                with self._lock:
                    self.stats.db_write_fail_total += 1
                self._set_error(err)
                self._publish_health()
                time.sleep(1)

        if batch or error_batch:
            self._flush(batch, error_batch)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self.run_forever, daemon=True, name="xray-audit-collector")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        self.close()


def run_collector() -> None:
    settings = Settings.from_env()
    collector = AuditCollector(settings)

    def _shutdown(*_: Any) -> None:
        collector.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    collector.start()
    while True:
        if collector._thread and not collector._thread.is_alive():
            break
        time.sleep(0.5)
