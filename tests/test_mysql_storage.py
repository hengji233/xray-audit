from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from xray_audit.error_parser import parse_error_line
from xray_audit.parser import parse_line
from xray_audit.storage import AuditQueryService, MySQLIngestor


class FakeCursor:
    def __init__(self, fetch_rows=None, rowcounts=None):
        self.executed = []
        self.executemany_calls = []
        self.fetch_rows = list(fetch_rows or [])
        self.rowcounts = list(rowcounts or [])
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        if self.rowcounts:
            self.rowcount = self.rowcounts.pop(0)

    def executemany(self, sql, params):
        self.executemany_calls.append((sql, list(params)))

    def fetchone(self):
        return self.fetch_rows.pop(0)

    def fetchall(self):
        return self.fetch_rows.pop(0)


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _ingestor(cursor):
    ingestor = MySQLIngestor.__new__(MySQLIngestor)
    ingestor.conn = FakeConnection(cursor)
    ingestor._ensure_conn = lambda: None
    return ingestor


def _query_service(cursor):
    service = AuditQueryService.__new__(AuditQueryService)

    @contextmanager
    def fake_conn():
        yield FakeConnection(cursor)

    service._conn = fake_conn
    return service


def test_mysql_ingest_writes_only_access_v2_fields() -> None:
    access = parse_line(
        "2026/08/10 10:00:00.123456 from 1.2.3.4:50000 accepted "
        "tcp:example.com:443 [inbound -> direct] email: user@example.com"
    )
    dns = parse_line("2026/08/10 10:00:01 dns got answer: example.com -> [1.2.3.4] 1ms")
    assert access is not None and dns is not None

    cursor = FakeCursor()
    ingestor = _ingestor(cursor)
    counts = ingestor.ingest_events([access, dns], "node-a")

    assert counts == {"raw": 0, "access": 1, "dns": 0}
    assert ingestor.conn.commits == 1
    assert len(cursor.executemany_calls) == 1
    sql, rows = cursor.executemany_calls[0]
    assert "audit_access_events" in sql
    assert "raw_line" not in sql
    assert "dest_raw" not in sql
    assert "confidence" not in sql
    assert "audit_raw_events" not in sql
    assert rows[0][5] == "tcp"
    assert rows[0][10] == "node-a"
    assert rows[0][11] == bytes.fromhex(access.raw_hash[:32])
    assert len(rows[0][11]) == 16


def test_mysql_dns_and_error_events_do_not_touch_database() -> None:
    dns = parse_line("2026/08/10 10:00:01 dns got answer: example.com -> [1.2.3.4] 1ms")
    error = parse_error_line("2026/08/10 10:00:02 [Warning] transport/internet: test")
    assert dns is not None and error is not None

    ingestor = MySQLIngestor.__new__(MySQLIngestor)
    ingestor._ensure_conn = lambda: (_ for _ in ()).throw(AssertionError("database accessed"))
    assert ingestor.ingest_events([dns], "node-a") == {"raw": 0, "access": 0, "dns": 0}
    assert ingestor.ingest_error_events([error], "node-a") == 0


def test_mysql_query_events_uses_access_table_and_v2_fields() -> None:
    cursor = FakeCursor(fetch_rows=[{"total": 1}, [{"id": 7}]])
    service = _query_service(cursor)
    start = datetime(2026, 8, 10, 9, 0, 0)
    end = datetime(2026, 8, 10, 11, 0, 0)

    total, rows = service.query_events(start, end, "user@example.com", "example", None, None, True, 1, 20)

    assert total == 1
    assert rows == [{"id": 7}]
    sql = " ".join(statement for statement, _ in cursor.executed)
    assert "audit_access_events" in sql
    assert "audit_raw_events" not in sql
    assert "audit_dns_events" not in sql
    assert "raw_line" not in sql
    assert "dest_raw" not in sql
    assert "confidence" not in sql
    assert "protocol" in sql
    assert "node_id" in sql


def test_mysql_error_queries_return_empty_without_connection() -> None:
    service = AuditQueryService.__new__(AuditQueryService)
    service._conn = lambda: (_ for _ in ()).throw(AssertionError("database accessed"))
    now = datetime(2026, 8, 10, 10, 0, 0)

    assert service.query_error_events(now, now, None, None, False, None, 1, 20) == (0, [])
    assert service.error_summary_stats(60) == {
        "total": 0,
        "error_count": 0,
        "warning_count": 0,
        "info_count": 0,
        "noise_count": 0,
        "top_categories": [],
    }
    assert service.error_summary_payload(now, now, 10)["total"] == 0


def test_mysql_prune_only_deletes_access_and_auth_in_batches() -> None:
    cursor = FakeCursor(rowcounts=[2, 1, 0, 0])
    ingestor = _ingestor(cursor)

    assert ingestor.prune_old_events(30, 2) == 3

    sql = " ".join(statement for statement, _ in cursor.executed)
    assert "audit_access_events" in sql
    assert "audit_auth_events" in sql
    assert "audit_raw_events" not in sql
    assert "audit_dns_events" not in sql
    assert "audit_error_events" not in sql
    assert "audit_runtime_config_history" not in sql


def test_mysql_schema_has_only_access_event_storage() -> None:
    schema = (Path(__file__).parents[1] / "sql" / "schema.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS audit_access_events" in schema
    assert "event_hash BINARY(16) NOT NULL" in schema
    assert "uniq_event_hash_time_node (event_hash, event_time, node_id)" in schema
    assert "CREATE TABLE IF NOT EXISTS audit_raw_events" not in schema
    assert "CREATE TABLE IF NOT EXISTS audit_dns_events" not in schema
    assert "CREATE TABLE IF NOT EXISTS audit_error_events" not in schema
    assert schema.count("KEY idx_") == 11
    assert "KEY idx_event_time_user" not in schema
    assert "ROW_FORMAT=DYNAMIC" in schema
