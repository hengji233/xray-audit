from __future__ import annotations

import json
import os
import re
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
        if not events:
            return {"raw": 0, "access": 0, "dns": 0}

        self._ensure_conn()
        raw_count = 0
        access_count = 0
        dns_count = 0

        try:
            with self.conn.cursor() as cur:
                for ev in events:
                    cur.execute(
                        """
                        INSERT INTO audit_raw_events(event_time, event_type, raw_line, raw_hash, node_id, ingested_at)
                        VALUES(%s, %s, %s, %s, %s, NOW(6))
                        ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id), raw_line=VALUES(raw_line)
                        """,
                        (ev.event_time, ev.event_type, ev.raw_line, ev.raw_hash, node_id),
                    )
                    raw_id = int(cur.lastrowid)
                    raw_count += 1

                    if ev.access is not None:
                        a = ev.access
                        cur.execute(
                            """
                            INSERT INTO audit_access_events(
                                raw_event_id, event_time, user_email, src, dest_raw, dest_host, dest_port,
                                status, detour, reason, is_domain, confidence
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON DUPLICATE KEY UPDATE
                                user_email=VALUES(user_email),
                                src=VALUES(src),
                                dest_raw=VALUES(dest_raw),
                                dest_host=VALUES(dest_host),
                                dest_port=VALUES(dest_port),
                                status=VALUES(status),
                                detour=VALUES(detour),
                                reason=VALUES(reason),
                                is_domain=VALUES(is_domain),
                                confidence=VALUES(confidence)
                            """,
                            (
                                raw_id,
                                a.event_time,
                                a.user_email,
                                a.src,
                                a.dest_raw,
                                a.dest_host,
                                a.dest_port,
                                a.status,
                                a.detour,
                                a.reason,
                                1 if a.is_domain else 0,
                                a.confidence,
                            ),
                        )
                        access_count += 1
                    elif ev.dns is not None:
                        d = ev.dns
                        cur.execute(
                            """
                            INSERT INTO audit_dns_events(
                                raw_event_id, event_time, dns_server, domain, ips_json, dns_status, elapsed_ms, error_text
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON DUPLICATE KEY UPDATE
                                dns_server=VALUES(dns_server),
                                domain=VALUES(domain),
                                ips_json=VALUES(ips_json),
                                dns_status=VALUES(dns_status),
                                elapsed_ms=VALUES(elapsed_ms),
                                error_text=VALUES(error_text)
                            """,
                            (
                                raw_id,
                                d.event_time,
                                d.dns_server,
                                d.domain,
                                d.ips_json,
                                d.dns_status,
                                d.elapsed_ms,
                                d.error_text,
                            ),
                        )
                        dns_count += 1
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        return {"raw": raw_count, "access": access_count, "dns": dns_count}

    def ingest_error_events(self, events: List[ParsedErrorEvent], node_id: str) -> int:
        if not events:
            return 0

        self._ensure_conn()
        inserted = 0

        try:
            with self.conn.cursor() as cur:
                for ev in events:
                    cur.execute(
                        """
                        INSERT INTO audit_error_events(
                            event_time, level, session_id, component, message,
                            src, dest_raw, dest_host, dest_port, category,
                            signature_hash, is_noise, raw_line, raw_hash, node_id, ingested_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(6))
                        ON DUPLICATE KEY UPDATE
                            level=VALUES(level),
                            session_id=VALUES(session_id),
                            component=VALUES(component),
                            message=VALUES(message),
                            src=VALUES(src),
                            dest_raw=VALUES(dest_raw),
                            dest_host=VALUES(dest_host),
                            dest_port=VALUES(dest_port),
                            category=VALUES(category),
                            signature_hash=VALUES(signature_hash),
                            is_noise=VALUES(is_noise),
                            raw_line=VALUES(raw_line),
                            ingested_at=NOW(6)
                        """,
                        (
                            ev.event_time,
                            ev.level,
                            ev.session_id,
                            ev.component,
                            ev.message,
                            ev.src,
                            ev.dest_raw,
                            ev.dest_host,
                            ev.dest_port,
                            ev.category,
                            ev.signature_hash,
                            1 if ev.is_noise else 0,
                            ev.raw_line,
                            ev.raw_hash,
                            node_id,
                        ),
                    )
                    inserted += 1
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        return inserted

    def prune_old_events(self, retention_days: int, delete_batch_size: int) -> int:
        if retention_days <= 0 or delete_batch_size <= 0:
            return 0

        self._ensure_conn()
        total_deleted = 0

        while True:
            try:
                with self.conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM audit_raw_events
                        WHERE id IN (
                            SELECT id FROM (
                                SELECT id
                                FROM audit_raw_events
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

        while True:
            try:
                with self.conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM audit_error_events
                        WHERE id IN (
                            SELECT id FROM (
                                SELECT id
                                FROM audit_error_events
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

        while True:
            try:
                with self.conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM audit_auth_events
                        WHERE id IN (
                            SELECT id FROM (
                                SELECT id
                                FROM audit_auth_events
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

        while True:
            try:
                with self.conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM audit_runtime_config_history
                        WHERE id IN (
                            SELECT id FROM (
                                SELECT id
                                FROM audit_runtime_config_history
                                WHERE changed_at < (NOW(6) - INTERVAL %s DAY)
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
                    r.id,
                    r.event_time,
                    r.event_type,
                    r.raw_line,
                    r.node_id,
                    a.user_email,
                    a.src,
                    a.dest_raw,
                    a.dest_host,
                    a.dest_port,
                    a.status,
                    a.detour,
                    a.reason,
                    a.is_domain,
                    a.confidence,
                    d.dns_server,
                    d.domain,
                    d.ips_json,
                    d.dns_status,
                    d.elapsed_ms,
                    d.error_text
                FROM audit_raw_events r
                LEFT JOIN audit_access_events a ON a.raw_event_id = r.id
                LEFT JOIN audit_dns_events d ON d.raw_event_id = r.id
                WHERE r.event_time >= (NOW(6) - INTERVAL %s SECOND)
                ORDER BY r.event_time DESC, r.id DESC
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
                    event_time,
                    user_email,
                    src,
                    dest_raw,
                    dest_host,
                    dest_port,
                    status,
                    detour,
                    reason,
                    is_domain,
                    confidence
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
                    event_time,
                    user_email,
                    src,
                    dest_raw,
                    dest_host,
                    dest_port,
                    status,
                    detour,
                    reason,
                    is_domain,
                    confidence
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
        filters: List[str] = ["r.event_type = %s", "r.event_time >= %s", "r.event_time <= %s"]
        params: List[Any] = ["access", dt_from, dt_to]

        if email:
            filters.append("a.user_email = %s")
            params.append(email)
        if dest_host:
            filters.append("a.dest_host LIKE %s")
            params.append(f"%{dest_host}%")
        if status:
            filters.append("a.status = %s")
            params.append(status)
        if detour:
            filters.append("a.detour LIKE %s")
            params.append(f"%{detour}%")
        if is_domain is not None:
            filters.append("a.is_domain = %s")
            params.append(1 if is_domain else 0)

        where_sql = " AND ".join(filters)
        joins_sql = """
            FROM audit_raw_events r
            LEFT JOIN audit_access_events a ON a.raw_event_id = r.id
            LEFT JOIN audit_dns_events d ON d.raw_event_id = r.id
        """
        offset = (page - 1) * page_size

        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) AS total {joins_sql} WHERE {where_sql}",
                tuple(params),
            )
            total = int(cur.fetchone()["total"])

            cur.execute(
                f"""
                SELECT
                    r.id,
                    r.event_time,
                    r.event_type,
                    r.raw_line,
                    r.node_id,
                    a.user_email,
                    a.src,
                    a.dest_raw,
                    a.dest_host,
                    a.dest_port,
                    a.status,
                    a.detour,
                    a.reason,
                    a.is_domain,
                    a.confidence,
                    d.dns_server,
                    d.domain,
                    d.ips_json,
                    d.dns_status,
                    d.elapsed_ms,
                    d.error_text
                {joins_sql}
                WHERE {where_sql}
                ORDER BY r.event_time DESC, r.id DESC
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
        filters: List[str] = ["event_time >= %s", "event_time <= %s"]
        params: List[Any] = [dt_from, dt_to]

        if level:
            filters.append("level = %s")
            params.append(level)
        if category:
            filters.append("category = %s")
            params.append(category)
        if not include_noise:
            filters.append("is_noise = 0")

        offset = (page - 1) * page_size

        def _run_query(extra_filter: str | None, extra_params: List[Any]) -> Tuple[int, List[Dict[str, Any]]]:
            where_parts = list(filters)
            query_params: List[Any] = list(params)
            if extra_filter:
                where_parts.append(extra_filter)
                query_params.extend(extra_params)
            where_sql = " AND ".join(where_parts)
            with self._conn() as conn, conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) AS total FROM audit_error_events WHERE {where_sql}", tuple(query_params))
                total = int(cur.fetchone()["total"])
                cur.execute(
                    f"""
                    SELECT
                        id,
                        event_time,
                        level,
                        session_id,
                        component,
                        message,
                        src,
                        dest_raw,
                        dest_host,
                        dest_port,
                        category,
                        signature_hash,
                        is_noise,
                        node_id
                    FROM audit_error_events
                    WHERE {where_sql}
                    ORDER BY event_time DESC, id DESC
                    LIMIT %s OFFSET %s
                    """,
                    tuple(query_params + [page_size, offset]),
                )
                return total, list(cur.fetchall())

        if not keyword:
            return _run_query(None, [])

        keyword_raw = keyword.strip()
        if not keyword_raw:
            return _run_query(None, [])

        fulltext_query = _to_fulltext_query(keyword_raw)
        if fulltext_query:
            try:
                total, rows = _run_query(
                    "MATCH(component, message, src, dest_raw) AGAINST (%s IN BOOLEAN MODE)",
                    [fulltext_query],
                )
                if total > 0:
                    return total, rows
            except pymysql.MySQLError:
                # Fallback to LIKE when FULLTEXT index is unavailable.
                pass

        kw = f"%{keyword_raw}%"
        return _run_query(
            "(component LIKE %s OR message LIKE %s OR src LIKE %s OR dest_raw LIKE %s)",
            [kw, kw, kw, kw],
        )

    def error_summary_stats(self, window_seconds: int) -> Dict[str, Any]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN level = 'error' THEN 1 ELSE 0 END) AS error_count,
                    SUM(CASE WHEN level = 'warning' THEN 1 ELSE 0 END) AS warning_count,
                    SUM(CASE WHEN level = 'info' THEN 1 ELSE 0 END) AS info_count,
                    SUM(CASE WHEN is_noise = 1 THEN 1 ELSE 0 END) AS noise_count
                FROM audit_error_events
                WHERE event_time >= (NOW(6) - INTERVAL %s SECOND)
                """,
                (window_seconds,),
            )
            row = cur.fetchone()

            cur.execute(
                """
                SELECT category, COUNT(*) AS hits
                FROM audit_error_events
                WHERE event_time >= (NOW(6) - INTERVAL %s SECOND)
                GROUP BY category
                ORDER BY hits DESC
                LIMIT 10
                """,
                (window_seconds,),
            )
            top_categories = list(cur.fetchall())

        total = int(row["total"] or 0)
        return {
            "total": total,
            "error_count": int(row["error_count"] or 0),
            "warning_count": int(row["warning_count"] or 0),
            "info_count": int(row["info_count"] or 0),
            "noise_count": int(row["noise_count"] or 0),
            "top_categories": top_categories,
        }

    def error_summary_payload(self, dt_from: datetime, dt_to: datetime, max_items: int) -> Dict[str, Any]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    level,
                    category,
                    COUNT(*) AS hits
                FROM audit_error_events
                WHERE event_time > %s AND event_time <= %s
                GROUP BY level, category
                ORDER BY hits DESC
                LIMIT %s
                """,
                (dt_from, dt_to, max_items),
            )
            level_category = list(cur.fetchall())

            cur.execute(
                """
                SELECT
                    category,
                    signature_hash,
                    COUNT(*) AS hits,
                    MAX(event_time) AS latest_time,
                    MIN(level) AS min_level,
                    MAX(level) AS max_level,
                    ANY_VALUE(component) AS component,
                    ANY_VALUE(message) AS sample_message
                FROM audit_error_events
                WHERE event_time > %s AND event_time <= %s
                GROUP BY category, signature_hash
                ORDER BY hits DESC
                LIMIT %s
                """,
                (dt_from, dt_to, max_items),
            )
            signatures = list(cur.fetchall())

            cur.execute(
                """
                SELECT
                    event_time, level, category, component, message, src, dest_raw
                FROM audit_error_events
                WHERE event_time > %s AND event_time <= %s
                ORDER BY event_time DESC, id DESC
                LIMIT %s
                """,
                (dt_from, dt_to, max_items),
            )
            recent_examples = list(cur.fetchall())

            cur.execute(
                """
                SELECT COUNT(*) AS total
                FROM audit_error_events
                WHERE event_time > %s AND event_time <= %s
                """,
                (dt_from, dt_to),
            )
            total = int(cur.fetchone()["total"] or 0)

        return {
            "from": dt_from,
            "to": dt_to,
            "total": total,
            "level_category": level_category,
            "top_signatures": signatures,
            "recent_examples": recent_examples,
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


def _to_fulltext_query(raw: str) -> str:
    tokens = [t.strip() for t in re.split(r"\s+", raw) if t.strip()]
    prepared: List[str] = []
    for token in tokens:
        safe = re.sub(r"[^\w\.\-:]+", "", token)
        if len(safe) < 2:
            continue
        prepared.append(f"+{safe}*")
        if len(prepared) >= 8:
            break
    if prepared:
        return " ".join(prepared)
    safe = re.sub(r"[^\w\.\-:]+", "", raw.strip())
    return f"+{safe}*" if len(safe) >= 2 else ""
