from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

import pymysql

from .config import Settings
from .d1_storage import _D1Client


@dataclass(frozen=True)
class TableSpec:
    name: str
    primary_key: str
    columns: tuple[str, ...]


TABLE_SPECS = (
    TableSpec("audit_access_events", "id", ("id", "event_time", "user_email", "src", "dest_host", "dest_port", "protocol", "status", "detour", "reason", "is_domain", "node_id", "event_hash")),
    TableSpec("audit_auth_events", "id", ("id", "event_type", "username", "source_ip", "user_agent", "event_time")),
    TableSpec("audit_admin_users", "id", ("id", "username", "password_hash", "token_version", "is_enabled", "must_change_password", "last_login_at", "created_at", "updated_at")),
    TableSpec("audit_runtime_config", "config_key", ("config_key", "value_json", "value_type", "scope", "updated_by", "updated_at")),
    TableSpec("audit_runtime_config_history", "id", ("id", "config_key", "old_value_json", "new_value_json", "changed_by", "source_ip", "changed_at")),
    TableSpec("audit_job_state", "state_key", ("state_key", "value_text", "updated_at")),
    TableSpec("collector_state", "id", ("id", "file_path", "inode", "last_offset", "updated_at")),
    TableSpec("audit_ip_geo_cache", "ip", ("ip", "country", "region", "city", "isp", "addr", "status", "source", "raw_json", "updated_at")),
)
TABLES_BY_NAME = {spec.name: spec for spec in TABLE_SPECS}
JSON_COLUMNS = {"ips_json", "value_json", "old_value_json", "new_value_json", "raw_json"}
INT64_COLUMNS = {"id", "session_id", "inode", "last_offset"}
NUMERIC_PRIMARY_KEYS = {spec.name for spec in TABLE_SPECS if spec.primary_key == "id"}
RESUME_VERSION = 1


class Source(Protocol):
    def fetch_page(
        self, spec: TableSpec, last_pk: Any, batch_size: int, end_pk: Any = None
    ) -> list[Mapping[str, Any]]: ...

    def count(self, spec: TableSpec, start_pk: Any = None, end_pk: Any = None) -> int: ...


class Gateway(Protocol):
    def call(self, operation: str, payload: dict[str, Any]) -> Any: ...


class MySQLSource:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def start_read_only_snapshot(self) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")

    def fetch_page(
        self, spec: TableSpec, last_pk: Any, batch_size: int, end_pk: Any = None
    ) -> list[Mapping[str, Any]]:
        columns = ", ".join(f"`{column}`" for column in spec.columns)
        filters: list[str] = []
        params: list[Any] = []
        if last_pk is not None:
            filters.append(f"`{spec.primary_key}` > %s")
            params.append(last_pk)
        if end_pk is not None:
            filters.append(f"`{spec.primary_key}` <= %s")
            params.append(end_pk)
        where = f" WHERE {' AND '.join(filters)}" if filters else ""
        sql = f"SELECT {columns} FROM `{spec.name}`{where} ORDER BY `{spec.primary_key}` LIMIT %s"
        params.append(batch_size)
        with self.connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return list(cursor.fetchall())

    def count(self, spec: TableSpec, start_pk: Any = None, end_pk: Any = None) -> int:
        filters: list[str] = []
        params: list[Any] = []
        if start_pk is not None:
            filters.append(f"`{spec.primary_key}` > %s")
            params.append(start_pk)
        if end_pk is not None:
            filters.append(f"`{spec.primary_key}` <= %s")
            params.append(end_pk)
        where = f" WHERE {' AND '.join(filters)}" if filters else ""
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) AS total FROM `{spec.name}`{where}", tuple(params))
            row = cursor.fetchone()
        return int(row["total"] or 0)


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return _iso_utc(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"unsupported JSON value type: {type(value).__name__}")


def serialize_row(row: Mapping[str, Any]) -> dict[str, Any]:
    serialized: dict[str, Any] = {}
    for column, value in row.items():
        if isinstance(value, datetime):
            value = _iso_utc(value)
        elif isinstance(value, date):
            value = value.isoformat()
        elif isinstance(value, Decimal):
            value = int(value) if value == value.to_integral_value() else float(value)
        if column in INT64_COLUMNS and value is not None:
            value = str(value)
        if column in JSON_COLUMNS and value is not None and not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_json_default)
        serialized[column] = value
    return serialized


def load_resume(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": RESUME_VERSION, "tables": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read valid resume state from {path}") from exc
    if not isinstance(state, dict) or state.get("version") != RESUME_VERSION or not isinstance(state.get("tables"), dict):
        raise ValueError(f"unsupported resume state in {path}")
    return state


def save_resume(path: Path, state: Mapping[str, Any]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(state, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


class MigrationRunner:
    def __init__(
        self,
        source: Source,
        gateway: Gateway | None,
        batch_size: int,
        resume_file: Path,
        dry_run: bool = False,
        start_pks: Mapping[str, Any] | None = None,
        end_pks: Mapping[str, Any] | None = None,
        output: Callable[[str], None] = print,
    ) -> None:
        if not 1 <= batch_size <= 50:
            raise ValueError("batch size must be between 1 and 50")
        if gateway is None and not dry_run:
            raise ValueError("a D1 gateway is required unless --dry-run is used")
        self.source = source
        self.gateway = gateway
        self.batch_size = batch_size
        self.resume_file = resume_file.expanduser().resolve()
        self.dry_run = dry_run
        self.start_pks = dict(start_pks or {})
        self.end_pks = dict(end_pks or {})
        self.output = output

    def migrate(self, specs: Sequence[TableSpec]) -> None:
        state = load_resume(self.resume_file)
        for spec in specs:
            checkpoint = state["tables"].get(spec.name, {})
            start_pk = self.start_pks.get(spec.name)
            end_pk = self.end_pks.get(spec.name)
            if checkpoint and (
                checkpoint.get("start_pk") != start_pk or checkpoint.get("end_pk") != end_pk
            ):
                raise ValueError(f"resume bounds do not match current bounds for {spec.name}")
            if checkpoint.get("complete"):
                self.output(f"{spec.name}: already complete")
                continue

            last_pk = checkpoint.get("last_pk", start_pk)
            migrated = int(checkpoint.get("rows", 0))
            scanned = 0
            while True:
                rows = self.source.fetch_page(spec, last_pk, self.batch_size, end_pk)
                if not rows:
                    if not self.dry_run:
                        state["tables"][spec.name] = {
                            "complete": True,
                            "last_pk": last_pk,
                            "rows": migrated,
                            "start_pk": start_pk,
                            "end_pk": end_pk,
                        }
                        save_resume(self.resume_file, state)
                    break

                payload = [serialize_row(row) for row in rows]
                last_pk = rows[-1][spec.primary_key]
                scanned += len(payload)
                if not self.dry_run:
                    assert self.gateway is not None
                    self.gateway.call("migration_import", {"table": spec.name, "rows": payload})
                    migrated += len(payload)
                    state["tables"][spec.name] = {
                        "complete": False,
                        "last_pk": last_pk,
                        "rows": migrated,
                        "start_pk": start_pk,
                        "end_pk": end_pk,
                    }
                    save_resume(self.resume_file, state)

            total = scanned if self.dry_run else migrated
            action = "would import" if self.dry_run else "imported"
            self.output(f"{spec.name}: {action} {total} rows")

    def verify(self, specs: Sequence[TableSpec]) -> bool:
        if self.gateway is None:
            raise ValueError("a D1 gateway is required for verification")
        stats = self.gateway.call(
            "migration_stats",
            {
                "start_pks": {key: str(value) for key, value in self.start_pks.items()},
                "end_pks": {key: str(value) for key, value in self.end_pks.items()},
            },
        )
        if not isinstance(stats, dict):
            raise ValueError("D1 migration_stats returned an invalid response")

        matches = True
        for spec in specs:
            mysql_count = self.source.count(
                spec, self.start_pks.get(spec.name), self.end_pks.get(spec.name)
            )
            try:
                d1_count = int(stats[spec.name])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"D1 migration_stats omitted a valid count for {spec.name}") from exc
            status = "OK" if mysql_count == d1_count else "MISMATCH"
            self.output(f"{spec.name}: MySQL={mysql_count} D1={d1_count} {status}")
            matches = matches and mysql_count == d1_count
        return matches


def _batch_size(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if not 1 <= parsed <= 50:
        raise argparse.ArgumentTypeError("must be between 1 and 50")
    return parsed


def select_tables(values: Iterable[str] | None) -> tuple[TableSpec, ...]:
    if not values:
        return TABLE_SPECS
    requested = {name.strip() for value in values for name in value.split(",") if name.strip()}
    unknown = sorted(requested - TABLES_BY_NAME.keys())
    if unknown:
        raise ValueError(f"unknown table(s): {', '.join(unknown)}")
    return tuple(spec for spec in TABLE_SPECS if spec.name in requested)


def parse_pk_bounds(values: Iterable[str] | None) -> dict[str, Any]:
    bounds: dict[str, Any] = {}
    for item in values or ():
        table, separator, raw = item.partition("=")
        if not separator or table not in TABLES_BY_NAME or not raw:
            raise ValueError(f"invalid primary-key bound: {item}")
        if table in NUMERIC_PRIMARY_KEYS:
            try:
                bounds[table] = int(raw)
            except ValueError as exc:
                raise ValueError(f"primary-key bound for {table} must be an integer") from exc
        else:
            bounds[table] = raw
    return bounds


def default_resume_file(settings: Settings) -> Path:
    identity = f"{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_db}|{settings.d1_gateway_url}"
    fingerprint = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return Path.home() / ".xray-audit" / f"d1-migration-{fingerprint}.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migrate xray-audit data from MySQL to Cloudflare D1")
    parser.add_argument("--dry-run", action="store_true", help="scan rows without calling D1 or updating resume state")
    parser.add_argument("--batch-size", type=_batch_size, default=50, help="rows per D1 request (1-50)")
    parser.add_argument("--tables", nargs="+", metavar="TABLE", help="table names, separated by spaces or commas")
    parser.add_argument("--resume-file", type=Path, help="checkpoint JSON path (default: outside the repository)")
    parser.add_argument("--verify-only", action="store_true", help="compare MySQL and D1 counts without importing")
    parser.add_argument(
        "--start-pk", action="append", metavar="TABLE=VALUE",
        help="import rows with primary key greater than VALUE; repeat per table",
    )
    parser.add_argument(
        "--end-pk", action="append", metavar="TABLE=VALUE",
        help="import rows with primary key less than or equal to VALUE; repeat per table",
    )
    return parser


def _redact(message: str, settings: Settings) -> str:
    for secret in (settings.mysql_password, settings.d1_gateway_token):
        if secret:
            message = message.replace(secret, "[REDACTED]")
    return re.sub(r"(?i)(authorization:\s*bearer\s+)\S+", r"\1[REDACTED]", message)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.dry_run and args.verify_only:
        parser.error("--dry-run and --verify-only cannot be used together")

    settings = Settings.from_env()
    try:
        specs = select_tables(args.tables)
        start_pks = parse_pk_bounds(args.start_pk)
        end_pks = parse_pk_bounds(args.end_pk)
        selected = {spec.name for spec in specs}
        unused = (start_pks.keys() | end_pks.keys()) - selected
        if unused:
            raise ValueError(f"bounds supplied for unselected table(s): {', '.join(sorted(unused))}")
        resume_file = args.resume_file or default_resume_file(settings)
        connection = pymysql.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            database=settings.mysql_db,
            charset=settings.mysql_charset,
            autocommit=False,
            cursorclass=pymysql.cursors.DictCursor,
        )
        gateway = None
        try:
            gateway = None if args.dry_run else _D1Client(settings)
            source = MySQLSource(connection)
            source.start_read_only_snapshot()
            runner = MigrationRunner(
                source, gateway, args.batch_size, resume_file, args.dry_run,
                start_pks=start_pks, end_pks=end_pks,
            )
            if args.verify_only:
                return 0 if runner.verify(specs) else 1
            runner.migrate(specs)
            if args.dry_run:
                return 0
            return 0 if runner.verify(specs) else 1
        finally:
            try:
                if gateway is not None:
                    gateway.close()
            finally:
                connection.rollback()
                connection.close()
    except Exception as exc:
        print(f"migration failed: {_redact(str(exc), settings)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
