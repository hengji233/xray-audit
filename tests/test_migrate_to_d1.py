from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from xray_audit.migrate_to_d1 import (
    MigrationRunner,
    TABLE_SPECS,
    TableSpec,
    load_resume,
    parse_pk_bounds,
    select_tables,
    serialize_row,
)


class StubSource:
    def __init__(self, rows=None, counts=None):
        self.rows = list(rows or [])
        self.counts = counts or {}
        self.fetches = []

    def fetch_page(self, spec, last_pk, batch_size, end_pk=None):
        self.fetches.append((spec.name, last_pk, batch_size, end_pk))
        available = [
            row for row in self.rows
            if (last_pk is None or row[spec.primary_key] > last_pk)
            and (end_pk is None or row[spec.primary_key] <= end_pk)
        ]
        return available[:batch_size]

    def count(self, spec, start_pk=None, end_pk=None):
        return self.counts[spec.name]


class StubGateway:
    def __init__(self, stats=None):
        self.calls = []
        self.stats = stats or {}

    def call(self, operation, payload):
        self.calls.append((operation, payload))
        return self.stats if operation == "migration_stats" else {"imported": len(payload["rows"])}


class InterruptingGateway(StubGateway):
    def call(self, operation, payload):
        if operation == "migration_import" and len(self.calls) == 1:
            raise RuntimeError("interrupted")
        return super().call(operation, payload)


def test_table_selection_always_uses_fk_safe_canonical_order() -> None:
    names = [spec.name for spec in TABLE_SPECS]
    assert len(names) == 8
    assert names[0] == "audit_access_events"
    assert [spec.name for spec in select_tables(["audit_access_events,audit_job_state"])] == [
        "audit_access_events",
        "audit_job_state",
    ]


def test_row_serialization_canonicalizes_datetimes_and_json() -> None:
    row = serialize_row(
        {
            "id": 7,
            "created_at": datetime(2026, 7, 21, 12, 34, 56, 123456),
            "updated_at": datetime(2026, 7, 21, 10, 0, tzinfo=timezone(timedelta(hours=2))),
            "value_json": {"message": "cafe", "when": datetime(2026, 7, 21, 8, 0)},
        }
    )
    assert row["created_at"] == "2026-07-21T12:34:56.123456Z"
    assert row["updated_at"] == "2026-07-21T08:00:00.000000Z"
    assert row["value_json"] == '{"message":"cafe","when":"2026-07-21T08:00:00.000000Z"}'


def test_resume_handles_string_primary_keys_and_checkpoints_each_chunk(tmp_path: Path) -> None:
    spec = TableSpec("audit_job_state", "state_key", ("state_key", "value_text", "updated_at"))
    source = StubSource(
        rows=[
            {"state_key": "a", "value_text": "1", "updated_at": datetime(2026, 1, 1)},
            {"state_key": "b", "value_text": "2", "updated_at": datetime(2026, 1, 2)},
            {"state_key": "c", "value_text": "3", "updated_at": datetime(2026, 1, 3)},
        ]
    )
    gateway = StubGateway()
    resume = tmp_path / "resume.json"
    runner = MigrationRunner(source, gateway, 2, resume, output=lambda _: None)

    runner.migrate((spec,))

    imports = [payload for operation, payload in gateway.calls if operation == "migration_import"]
    assert [len(payload["rows"]) for payload in imports] == [2, 1]
    assert source.fetches == [(spec.name, None, 2, None), (spec.name, "b", 2, None), (spec.name, "c", 2, None)]
    assert load_resume(resume)["tables"][spec.name] == {"complete": True, "last_pk": "c", "rows": 3, "start_pk": None, "end_pk": None}
    assert not list(tmp_path.glob("*.tmp"))

    second_gateway = StubGateway()
    MigrationRunner(source, second_gateway, 2, resume, output=lambda _: None).migrate((spec,))
    assert second_gateway.calls == []


def test_dry_run_does_not_call_gateway_or_write_resume(tmp_path: Path) -> None:
    spec = TableSpec("audit_access_events", "id", ("id",))
    source = StubSource(rows=[{"id": 1}, {"id": 2}])
    resume = tmp_path / "resume.json"
    MigrationRunner(source, None, 1, resume, dry_run=True, output=lambda _: None).migrate((spec,))
    assert not resume.exists()


def test_resume_preserves_numeric_primary_key_type(tmp_path: Path) -> None:
    spec = TableSpec("audit_access_events", "id", ("id",))
    resume = tmp_path / "resume.json"
    MigrationRunner(
        StubSource(rows=[{"id": 10}, {"id": 20}]),
        StubGateway(),
        50,
        resume,
        output=lambda _: None,
    ).migrate((spec,))

    last_pk = load_resume(resume)["tables"][spec.name]["last_pk"]
    assert last_pk == 20
    assert isinstance(last_pk, int)


def test_resume_continues_after_last_accepted_chunk(tmp_path: Path) -> None:
    spec = TableSpec("audit_access_events", "id", ("id",))
    source = StubSource(rows=[{"id": 1}, {"id": 2}, {"id": 3}])
    resume = tmp_path / "resume.json"
    gateway = InterruptingGateway()

    try:
        MigrationRunner(source, gateway, 1, resume, output=lambda _: None).migrate((spec,))
    except RuntimeError as exc:
        assert str(exc) == "interrupted"
    else:
        raise AssertionError("migration should have been interrupted")

    assert load_resume(resume)["tables"][spec.name]["last_pk"] == 1
    resumed_gateway = StubGateway()
    MigrationRunner(source, resumed_gateway, 1, resume, output=lambda _: None).migrate((spec,))
    imported_ids = [
        payload["rows"][0]["id"]
        for operation, payload in resumed_gateway.calls
        if operation == "migration_import"
    ]
    assert imported_ids == ["2", "3"]


def test_verification_reports_mismatch_and_returns_false() -> None:
    specs = TABLE_SPECS[:2]
    source = StubSource(counts={specs[0].name: 4, specs[1].name: 2})
    gateway = StubGateway(stats={specs[0].name: 4, specs[1].name: 1})
    output = []

    matched = MigrationRunner(source, gateway, 50, Path("unused.json"), output=output.append).verify(specs)

    assert matched is False
    assert gateway.calls == [("migration_stats", {"start_pks": {}, "end_pks": {}})]
    assert output[-1].endswith("MISMATCH")


def test_large_int64_values_are_serialized_as_decimal_strings() -> None:
    large = 2**63 - 1
    row = serialize_row({"id": large, "inode": large - 2, "last_offset": large - 3})
    assert row == {"id": str(large), "inode": str(large - 2), "last_offset": str(large - 3)}


def test_primary_key_bounds_limit_incremental_scan(tmp_path: Path) -> None:
    spec = TableSpec("audit_access_events", "id", ("id",))
    source = StubSource(rows=[{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}])
    gateway = StubGateway()
    MigrationRunner(
        source, gateway, 50, tmp_path / "resume.json",
        start_pks={spec.name: 1}, end_pks={spec.name: 3}, output=lambda _: None,
    ).migrate((spec,))
    imported = gateway.calls[0][1]["rows"]
    assert imported == [{"id": "2"}, {"id": "3"}]
    assert source.fetches[0] == (spec.name, 1, 50, 3)
    assert parse_pk_bounds(["audit_access_events=9007199254740993", "audit_job_state=cursor"]) == {
        "audit_access_events": 9007199254740993,
        "audit_job_state": "cursor",
    }
