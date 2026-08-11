from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pymysql

from .config import Settings
from .models import ParsedErrorEvent, ParsedEvent


class MySQLFactory:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def connect(self):
        return pymysql.connect(
            host=self.settings.mysql_host,
            port=self.settings.mysql_port,
            user=self.settings.mysql_user,
            password=self.settings.mysql_password,
            database=self.settings.mysql_db,
            charset=self.settings.mysql_charset,
            autocommit=False,
            cursorclass=pymysql.cursors.DictCursor,
        )


class MySQLIngestor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.factory = MySQLFactory(settings)
        self.conn = self.factory.connect()

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()

    def _ensure_conn(self) -> None:
        try:
            self.conn.ping(reconnect=True)
        except Exception:
            self.conn = self.factory.connect()

    def load_state(self, file_path: str) -> Tuple[Optional[int], int]:
        self._ensure_conn()
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT inode, last_offset FROM collector_state WHERE file_path=%s",
                (file_path,),
            )
            row = cur.fetchone()
            if not row:
                return None, 0
            return row.get("inode"), int(row.get("last_offset", 0))

    def save_state(self, file_path: str, inode: Optional[int], offset: int) -> None:
        self._ensure_conn()
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO collector_state(file_path, inode, last_offset, updated_at)
                VALUES(%s, %s, %s, NOW(6))
                ON DUPLICATE KEY UPDATE inode=VALUES(inode), last_offset=VALUES(last_offset), updated_at=NOW(6)
                """,
                (file_path, inode, offset),
            )
        self.conn.commit()

    def ingest_events(self, events: List[ParsedEvent], node_id: str) -> Dict[str, int]:
        access_events = [ev for ev in events if ev.access is not None]
        if not access_events:
            return {"raw": 0, "access": 0, "dns": 0}

        self._ensure_conn()
        try:
            with self.conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO audit_access_events(
                        event_time, user_email, src, dest_host, dest_port, protocol,
                        status, detour, reason, is_domain, node_id, event_hash
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        user_email=VALUES(user_email),
                        src=VALUES(src),
                        dest_host=VALUES(dest_host),
                        dest_port=VALUES(dest_port),
                        protocol=VALUES(protocol),
                        status=VALUES(status),
                        detour=VALUES(detour),
                        reason=VALUES(reason),
                        is_domain=VALUES(is_domain)
                    """,
                    [
                        (
                            ev.access.event_time,
                            ev.access.user_email,
                            ev.access.src,
                            ev.access.dest_host,
                            ev.access.dest_port,
                            ev.access.dest_raw.split(":", 1)[0]
                            if ev.access.dest_raw.startswith(("tcp:", "udp:"))
                            else "",
                            ev.access.status,
                            ev.access.detour,
                            ev.access.reason,
                            1 if ev.access.is_domain else 0,
                            node_id,
                            bytes.fromhex(ev.raw_hash[:32]),
                        )
                        for ev in access_events
                    ],
                )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        return {"raw": 0, "access": len(access_events), "dns": 0}

    def ingest_error_events(self, events: List[ParsedErrorEvent], node_id: str) -> int:
        return 0

    def prune_old_events(self, retention_days: int, delete_batch_size: int) -> int:
        if retention_days <= 0 or delete_batch_size <= 0:
            return 0

        self._ensure_conn()
        total_deleted = 0

        for table in ("audit_access_events", "audit_auth_events"):
            while True:
                try:
                    with self.conn.cursor() as cur:
                        cur.execute(
                            f"""
                        DELETE FROM {table}
                        WHERE id IN (
                            SELECT id FROM (
                                SELECT id
                                FROM {table}
                                WHERE event_time < (NOW(6) - INTERVAL %s DAY)
                                ORDER BY id
                                LIMIT %s
                            ) t
                        )
                        """,
                            (retention_days, delete_batch_size),
                        )
                        deleted = int(cur.rowcount)
                    self.conn.commit()
                except Exception:
                    self.conn.rollback()
                    raise

                total_deleted += deleted
                if deleted < delete_batch_size:
                    break

        return total_deleted


class AuditQueryService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.factory = MySQLFactory(settings)

    @contextmanager
    def _conn(self):
        conn = self.factory.connect()
        try:
            yield conn
        finally:
            conn.close()

    def collector_state(self, file_path: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT file_path, inode, last_offset, updated_at FROM collector_state WHERE file_path=%s",
                (file_path,),
            )
            row = cur.fetchone()
            return row

    def admin_user_count(self) -> int:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total FROM audit_admin_users")
            row = cur.fetchone()
            return int(row["total"] or 0)

    def admin_user_get(self, username: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, username, password_hash, token_version, is_enabled, must_change_password, last_login_at, created_at, updated_at
                FROM audit_admin_users
                WHERE username=%s
                LIMIT 1
                """,
                (username,),
            )
            return cur.fetchone()

    def admin_user_create(self, username: str, password_hash: str, must_change_password: bool = False) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_admin_users(
                    username, password_hash, token_version, is_enabled, must_change_password, created_at, updated_at
                )
                VALUES (%s, %s, 0, 1, %s, NOW(6), NOW(6))
                """,
                (username, password_hash, 1 if must_change_password else 0),
            )
            conn.commit()

    def admin_user_update_login_success(self, username: str) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE audit_admin_users
                SET last_login_at=NOW(6), updated_at=NOW(6)
                WHERE username=%s
                """,
                (username,),
            )
            conn.commit()

    def admin_user_bump_token_version(self, username: str) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE audit_admin_users
                SET token_version=token_version+1, updated_at=NOW(6)
                WHERE username=%s
                """,
                (username,),
            )
            conn.commit()

    def admin_user_change_password(self, username: str, new_password_hash: str) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE audit_admin_users
                SET password_hash=%s, token_version=token_version+1, must_change_password=0, updated_at=NOW(6)
                WHERE username=%s
                """,
                (new_password_hash, username),
            )
            conn.commit()

    def auth_event_insert(self, event_type: str, username: str, source_ip: str, user_agent: str) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_auth_events(event_type, username, source_ip, user_agent, event_time)
                VALUES (%s, %s, %s, %s, NOW(6))
                """,
                (event_type, username, source_ip, user_agent),
            )
            conn.commit()

    def runtime_config_all(self) -> List[Dict[str, Any]]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT config_key, value_json, value_type, scope, updated_by, updated_at
                FROM audit_runtime_config
                ORDER BY config_key
                """
            )
            return list(cur.fetchall())

    def runtime_config_upsert(self, values: Dict[str, Any], changed_by: str, source_ip: str) -> None:
        if not values:
            return
        with self._conn() as conn, conn.cursor() as cur:
            for key, value in values.items():
                cur.execute(
                    "SELECT value_json FROM audit_runtime_config WHERE config_key=%s LIMIT 1",
                    (key,),
                )
                old_row = cur.fetchone()
                old_json = old_row.get("value_json") if old_row else None
                new_json = json.dumps(value, ensure_ascii=False)
                value_type = type(value).__name__
                cur.execute(
                    """
                    INSERT INTO audit_runtime_config(config_key, value_json, value_type, scope, updated_by, updated_at)
                    VALUES (%s, %s, %s, %s, %s, NOW(6))
                    ON DUPLICATE KEY UPDATE
                        value_json=VALUES(value_json),
                        value_type=VALUES(value_type),
                        scope=VALUES(scope),
                        updated_by=VALUES(updated_by),
                        updated_at=NOW(6)
                    """,
                    (key, new_json, value_type, "runtime", changed_by),
                )
                cur.execute(
                    """
                    INSERT INTO audit_runtime_config_history(
                        config_key, old_value_json, new_value_json, changed_by, source_ip, changed_at
                    ) VALUES (%s, %s, %s, %s, %s, NOW(6))
                    """,
                    (key, old_json, new_json, changed_by, source_ip),
                )
            conn.commit()

    def runtime_config_history(self, page: int, page_size: int) -> Tuple[int, List[Dict[str, Any]]]:
        offset = (page - 1) * page_size
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total FROM audit_runtime_config_history")
            total = int(cur.fetchone()["total"] or 0)
            cur.execute(
                """
                SELECT id, config_key, old_value_json, new_value_json, changed_by, source_ip, changed_at
                FROM audit_runtime_config_history
                ORDER BY changed_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (page_size, offset),
            )
            return total, list(cur.fetchall())

    def recent_events(self, seconds: int, limit: int) -> List[Dict[str, Any]]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id, event_time, user_email, src, dest_host, dest_port,
                    protocol, status, detour, reason, is_domain, node_id
                FROM audit_access_events
                WHERE event_time >= (NOW(6) - INTERVAL %s SECOND)
                ORDER BY event_time DESC, id DESC
                LIMIT %s
                """,
                (seconds, limit),
            )
            return list(cur.fetchall())

    def user_visits(self, email: str, dt_from: datetime, dt_to: datetime, limit: int) -> List[Dict[str, Any]]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id, event_time, user_email, src, dest_host, dest_port,
                    protocol, status, detour, reason, is_domain, node_id
                FROM audit_access_events
                WHERE user_email = %s
                    AND event_time >= %s
                    AND event_time <= %s
                ORDER BY event_time DESC
                LIMIT %s
                """,
                (email, dt_from, dt_to, limit),
            )
            return list(cur.fetchall())

    def user_visits_paged(
        self, email: str, dt_from: datetime, dt_to: datetime, page: int, page_size: int
    ) -> Tuple[int, List[Dict[str, Any]]]:
        offset = (page - 1) * page_size
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS total
                FROM audit_access_events
                WHERE user_email = %s
                  AND event_time >= %s
                  AND event_time <= %s
                """,
                (email, dt_from, dt_to),
            )
            total = int(cur.fetchone()["total"])
            cur.execute(
                """
                SELECT
                    id, event_time, user_email, src, dest_host, dest_port,
                    protocol, status, detour, reason, is_domain, node_id
                FROM audit_access_events
                WHERE user_email = %s
                    AND event_time >= %s
                    AND event_time <= %s
                ORDER BY event_time DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (email, dt_from, dt_to, page_size, offset),
            )
            return total, list(cur.fetchall())

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
        filters: List[str] = ["event_time >= %s", "event_time <= %s"]
        params: List[Any] = [dt_from, dt_to]

        if email:
            filters.append("user_email = %s")
            params.append(email)
        if dest_host:
            filters.append("dest_host LIKE %s")
            params.append(f"%{dest_host}%")
        if status:
            filters.append("status = %s")
            params.append(status)
        if detour:
            filters.append("detour LIKE %s")
            params.append(f"%{detour}%")
        if is_domain is not None:
            filters.append("is_domain = %s")
            params.append(1 if is_domain else 0)

        where_sql = " AND ".join(filters)
        offset = (page - 1) * page_size

        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) AS total FROM audit_access_events WHERE {where_sql}",
                tuple(params),
            )
            total = int(cur.fetchone()["total"])

            cur.execute(
                f"""
                SELECT
                    id, event_time, user_email, src, dest_host, dest_port,
                    protocol, status, detour, reason, is_domain, node_id
                FROM audit_access_events
                WHERE {where_sql}
                ORDER BY event_time DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                tuple(params + [page_size, offset]),
            )
            return total, list(cur.fetchall())

    def list_users(
        self, dt_from: datetime, dt_to: datetime, page: int, page_size: int
    ) -> Tuple[int, List[Dict[str, Any]]]:
        offset = (page - 1) * page_size
        common_params = (dt_from, dt_to)
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS total
                FROM (
                    SELECT user_email
                    FROM audit_access_events
                    WHERE event_time >= %s
                      AND event_time <= %s
                      AND user_email <> ''
                      AND user_email <> 'unknown'
                    GROUP BY user_email
                ) t
                """,
                common_params,
            )
            total = int(cur.fetchone()["total"])

            cur.execute(
                """
                SELECT
                    user_email,
                    COUNT(*) AS count,
                    MAX(event_time) AS last_seen,
                    COUNT(DISTINCT CASE WHEN dest_host <> '' THEN dest_host ELSE NULL END) AS unique_dest_host_count
                FROM audit_access_events
                WHERE event_time >= %s
                  AND event_time <= %s
                  AND user_email <> ''
                  AND user_email <> 'unknown'
                GROUP BY user_email
                ORDER BY last_seen DESC
                LIMIT %s OFFSET %s
                """,
                (dt_from, dt_to, page_size, offset),
            )
            return total, list(cur.fetchall())

    def summary_stats(self, window_seconds: int) -> Dict[str, Any]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*)
                     FROM audit_access_events
                     WHERE event_time >= (NOW(6) - INTERVAL %s SECOND)) AS total_events,
                    (SELECT COUNT(DISTINCT user_email)
                     FROM audit_access_events
                     WHERE event_time >= (NOW(6) - INTERVAL %s SECOND)
                       AND user_email <> ''
                       AND user_email <> 'unknown') AS unique_users,
                    (SELECT COUNT(DISTINCT dest_host)
                     FROM audit_access_events
                     WHERE event_time >= (NOW(6) - INTERVAL %s SECOND)
                       AND dest_host <> ''
                       AND is_domain = 1) AS unique_domains
                """,
                (window_seconds, window_seconds, window_seconds),
            )
            row = cur.fetchone()

        total_events = int(row["total_events"] or 0)
        window_minutes = max(window_seconds / 60.0, 1e-6)
        return {
            "total_events": total_events,
            "unique_users": int(row["unique_users"] or 0),
            "unique_domains": int(row["unique_domains"] or 0),
            "qpm": round(total_events / window_minutes, 2),
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
        return 0, []

    def error_summary_stats(self, window_seconds: int) -> Dict[str, Any]:
        return {
            "total": 0,
            "error_count": 0,
            "warning_count": 0,
            "info_count": 0,
            "noise_count": 0,
            "top_categories": [],
        }

    def error_summary_payload(self, dt_from: datetime, dt_to: datetime, max_items: int) -> Dict[str, Any]:
        return {
            "from": dt_from,
            "to": dt_to,
            "total": 0,
            "level_category": [],
            "top_signatures": [],
            "recent_examples": [],
        }

    def job_state_get(self, key: str) -> Optional[str]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT value_text FROM audit_job_state WHERE state_key=%s", (key,))
            row = cur.fetchone()
            if not row:
                return None
            return str(row.get("value_text", ""))

    def job_state_set(self, key: str, value: str) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_job_state(state_key, value_text, updated_at)
                VALUES(%s, %s, NOW(6))
                ON DUPLICATE KEY UPDATE value_text=VALUES(value_text), updated_at=NOW(6)
                """,
                (key, value),
            )
            conn.commit()

    def geo_cache_get(self, ips: List[str], ttl_hours: int) -> Dict[str, Dict[str, Any]]:
        if not ips:
            return {}

        placeholders = ", ".join(["%s"] * len(ips))
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ip, country, region, city, isp, addr, status, source, updated_at
                FROM audit_ip_geo_cache
                WHERE ip IN ({placeholders})
                  AND updated_at >= (NOW(6) - INTERVAL %s HOUR)
                """,
                tuple(ips + [ttl_hours]),
            )
            rows = list(cur.fetchall())
        return {str(row["ip"]): row for row in rows}

    def geo_cache_upsert(self, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            return

        with self._conn() as conn, conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO audit_ip_geo_cache(
                    ip, country, region, city, isp, addr, status, source, raw_json, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(6))
                ON DUPLICATE KEY UPDATE
                    country=VALUES(country),
                    region=VALUES(region),
                    city=VALUES(city),
                    isp=VALUES(isp),
                    addr=VALUES(addr),
                    status=VALUES(status),
                    source=VALUES(source),
                    raw_json=VALUES(raw_json),
                    updated_at=NOW(6)
                """,
                [
                    (
                        row.get("ip", ""),
                        row.get("country", ""),
                        row.get("region", ""),
                        row.get("city", ""),
                        row.get("isp", ""),
                        row.get("addr", ""),
                        row.get("status", "ok"),
                        row.get("source", "pconline"),
                        json.dumps(row.get("raw", {}), ensure_ascii=False),
                    )
                    for row in rows
                ],
            )
            conn.commit()

    def top_domains(self, seconds: int, limit: int) -> List[Dict[str, Any]]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT dest_host AS domain, COUNT(*) AS hits
                FROM audit_access_events
                WHERE event_time >= (NOW(6) - INTERVAL %s SECOND)
                  AND dest_host <> ''
                  AND is_domain = 1
                GROUP BY dest_host
                ORDER BY hits DESC
                LIMIT %s
                """,
                (seconds, limit),
            )
            return list(cur.fetchall())

    def active_users(self, seconds: int, limit: int) -> List[Dict[str, Any]]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_email, UNIX_TIMESTAMP(MAX(event_time)) AS last_seen_unix
                FROM audit_access_events
                WHERE user_email <> ''
                  AND event_time >= (NOW(6) - INTERVAL %s SECOND)
                GROUP BY user_email
                ORDER BY last_seen_unix DESC
                LIMIT %s
                """,
                (seconds, limit),
            )
            return list(cur.fetchall())


def apply_schema(settings: Settings, schema_path: str) -> None:
    if not os.path.exists(schema_path):
        raise FileNotFoundError(schema_path)

    factory = MySQLFactory(settings)
    conn = factory.connect()
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            sql = f.read()

        with conn.cursor() as cur:
            for statement in [x.strip() for x in sql.split(";") if x.strip()]:
                cur.execute(statement)
        conn.commit()
    finally:
        conn.close()
