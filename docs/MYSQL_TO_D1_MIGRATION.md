# MySQL To D1 Migration

This runbook moves an existing Xray Audit database to D1 with a full copy, a
short final delta window, explicit verification, and a reversible application
cutover. Practice the complete procedure against a disposable D1 database
before scheduling production work.

## Preconditions And Ownership

- Complete `D1_DEPLOYMENT.md` through remote migration application and Worker deployment.
- Confirm the retained MySQL data plus indexes fits comfortably below the applicable D1 limit: 10 GB paid or 500 MB free.
- Use Workers Paid for production migration and operation.
- Confirm the workload is compatible with D1's 100-parameter statement limit and single-threaded query execution.
- Back up MySQL and test restoration. Record the backup time and binlog coordinates when binary logging is available.
- Schedule a maintenance window for the final delta and collector/API cutover.
- Assign one operator to control writers and one to verify counts and application behavior.
- Confirm Xray logs, the MySQL session, and stored naive timestamps represent UTC. The migration treats naive MySQL datetimes as UTC.

The Worker exposes `migration_import` and `migration_stats` operations, not raw
SQL. The bundled `python -m xray_audit.migrate_to_d1` command reads a
repeatable-read, read-only MySQL snapshot; pages by stable primary key; preserves
IDs; converts datetimes to UTC ISO strings; sends at most 50 rows per request;
and checkpoints each successful batch. Pass credentials through the environment
or a secret manager, never command arguments.

The migration host needs both source and destination settings even though the
running application uses only one backend:

```dotenv
AUDIT_MYSQL_HOST=127.0.0.1
AUDIT_MYSQL_PORT=3306
AUDIT_MYSQL_USER=xray_audit_migration
AUDIT_MYSQL_PASSWORD=
AUDIT_MYSQL_DB=xray_audit
AUDIT_STORAGE_BACKEND=d1
AUDIT_D1_GATEWAY_URL=https://YOUR-WORKER-URL.example
AUDIT_D1_GATEWAY_TOKEN=
```

Populate blank secrets only in the protected migration environment. By default,
checkpoint JSON is written outside the repository under `~/.xray-audit/`. Use
`--resume-file` to choose another protected path. Keep each checkpoint with the
D1 database it describes and do not reuse it against another database.

## Table Order

Import in this order so parent IDs exist before child rows:

1. `audit_raw_events`
2. `audit_access_events`
3. `audit_dns_events`
4. `audit_error_events`
5. `audit_auth_events`
6. `audit_admin_users`
7. `audit_runtime_config`
8. `audit_runtime_config_history`
9. `audit_job_state`
10. `collector_state`
11. `audit_ip_geo_cache`

The gateway upserts migration rows by primary key, making checkpoint replay
idempotent while restoring the source values. A conflicting non-primary unique
key fails the batch instead of being silently ignored. Verification remains
required. Never import child tables ahead of `audit_raw_events`.

## Phase 1: Dry Run

1. Restore a recent MySQL backup to a non-production instance or use a read-only snapshot.
2. Create a disposable D1 database and apply all Worker migrations.
3. Scan and serialize every source row without calling D1 or writing a checkpoint:

```bash
python -m xray_audit.migrate_to_d1 --dry-run --batch-size 50
```

4. Import the snapshot into disposable D1. The command automatically compares all MySQL and D1 table counts at the end:

```bash
python -m xray_audit.migrate_to_d1 --batch-size 50 --resume-file /protected/path/dry-run.json
```

5. Compare counts by table and by day, plus minimum and maximum timestamps. Spot-check rows containing nulls, Unicode text, long raw lines, DNS JSON, and admin password hashes.
6. Run the API against disposable D1 and verify login, recent events, filtered queries, errors, users, summaries, runtime config, GeoIP cache, health, and retention.
7. Measure import duration and query latency. Reduce import batch concurrency if normal queries stall; D1 processes each database on a single thread.
8. Delete the disposable database and retain only a sanitized migration report.

Do not continue until dry-run counts and behavior agree. Resolve schema or data
conversion issues in a new Worker migration or the reviewed migration client,
then repeat the dry run.

## Phase 2: Full Copy

Choose a UTC high-water mark `T0` immediately before the full copy and record
the maximum primary key for every append-only table. The source collector may
continue writing during this phase. Import only append-only tables through
those exact primary-key bounds; mutable current state is deferred until writers
stop.

```bash
python -m xray_audit.migrate_to_d1 \
  --tables audit_raw_events audit_access_events audit_dns_events \
  audit_error_events audit_auth_events audit_runtime_config_history \
  --end-pk audit_raw_events=RAW_T0 \
  --end-pk audit_access_events=ACCESS_T0 \
  --end-pk audit_dns_events=DNS_T0 \
  --end-pk audit_error_events=ERROR_T0 \
  --end-pk audit_auth_events=AUTH_T0 \
  --end-pk audit_runtime_config_history=CONFIG_HISTORY_T0 \
  --batch-size 50 --resume-file /protected/path/full-copy.json
```

1. Record baseline MySQL counts and min/max IDs for all tables.
2. Import append-only rows up to each recorded high-water ID in table order: raw, access, DNS, error, auth, and runtime-config history.
3. Defer mutable current-state tables (`audit_admin_users`, `audit_runtime_config`, `audit_job_state`, `collector_state`, and `audit_ip_geo_cache`) until all writers are stopped. Migration import is insert-only and cannot overwrite a row imported earlier.
4. Persist checkpoints outside both databases so the import can resume without guessing.
5. Request `migration_stats` from the authenticated gateway and compare it with source counts at the high-water marks.
6. Re-run missing batches. Do not truncate D1 or restart a successful full copy solely because a request timed out; query stats and checkpoints first.

Limit importer concurrency. Multiple HTTP requests do not make a single D1
database parallel and can increase contention or rate limiting.

## Phase 3: Final Delta And Cutover

Announce the maintenance window before stopping writers.

1. Stop the MySQL-backed collector. If the API permits writes such as auth events, password changes, runtime configuration, or GeoIP cache updates, place it in maintenance mode or stop it too.
2. Verify no collector or API process remains able to write MySQL. Check systemd, containers, scheduled jobs, and manually started processes.
3. Record final high-water IDs and timestamp `T1` in MySQL.
4. Import every row after the full-copy high-water marks through the final marks, in table order.
5. Import current admin users, runtime config, job state, collector state, and GeoIP cache for the first and only time. If any were imported earlier, use a fresh D1 database and repeat the migration; `migration_import` will ignore rather than update conflicting keys.
6. Run all verification checks below. Keep MySQL intact and read-only.
7. Configure both Python services with `AUDIT_STORAGE_BACKEND=d1`, the Worker URL, and the protected gateway token.
8. Start the API first and verify health and login. Start exactly one collector second.
9. Confirm new post-cutover events appear in D1 and collector lag returns to normal.
10. End maintenance only after the acceptance checks pass.

Run the final delta with a new checkpoint. Use each full-copy high-water mark
as an exclusive lower bound and each final mark as an inclusive upper bound.
This transfers only rows added during the full-copy window:

```bash
python -m xray_audit.migrate_to_d1 \
  --tables audit_raw_events audit_access_events audit_dns_events \
  audit_error_events audit_auth_events audit_runtime_config_history \
  --start-pk audit_raw_events=RAW_T0 --end-pk audit_raw_events=RAW_T1 \
  --start-pk audit_access_events=ACCESS_T0 --end-pk audit_access_events=ACCESS_T1 \
  --start-pk audit_dns_events=DNS_T0 --end-pk audit_dns_events=DNS_T1 \
  --start-pk audit_error_events=ERROR_T0 --end-pk audit_error_events=ERROR_T1 \
  --start-pk audit_auth_events=AUTH_T0 --end-pk audit_auth_events=AUTH_T1 \
  --start-pk audit_runtime_config_history=CONFIG_HISTORY_T0 \
  --end-pk audit_runtime_config_history=CONFIG_HISTORY_T1 \
  --batch-size 50 --resume-file /protected/path/final-delta.json
```

Then import the mutable tables exactly once and verify all tables:

```bash
python -m xray_audit.migrate_to_d1 \
  --tables audit_admin_users audit_runtime_config audit_job_state \
  collector_state audit_ip_geo_cache \
  --batch-size 50 --resume-file /protected/path/final-state.json
python -m xray_audit.migrate_to_d1 --verify-only
```

Any count mismatch exits nonzero. The command verifies counts, not row content,
so continue with the independent comparisons below.

`collector_state` controls log offsets. Verify its final value carefully to avoid
skipped lines or a large replay. The ingestion uniqueness constraints make many
replays harmless, but they do not justify running two collectors concurrently.

## Verification Checklist

- `migration_stats` equals final MySQL counts for every imported table, accounting for any deliberately excluded retention range.
- Counts match by UTC day for raw, access, DNS, error, auth, and config-history tables.
- Minimum and maximum IDs and timestamps match the intended source range.
- Sampled parent/child relationships join correctly for access and DNS events.
- Sampled raw hashes, text fields, JSON fields, booleans, nulls, and UTC timestamps match.
- Admin login succeeds and forced-password-change state is preserved.
- Recent events, filtered event queries, errors, user lists, domain totals, summaries, runtime configuration, and GeoIP lookups return plausible results.
- `/api/v1/health` reports `storage_backend=d1` and succeeds without storage or collector alerts.
- A new access event and a new error event arrive after cutover.
- Retention cleanup succeeds on D1 with bounded delete batches.
- Worker errors, D1 rows read/written, database size, collector retries, write failures, and lag remain acceptable during observation.

Counts alone are insufficient because they do not prove field content. Include
deterministic samples and critical keyed tables in the comparison.

## Rollback

Rollback is straightforward only while MySQL is still current. Define an
observation deadline and do not delete or modify the source during it.

Before any D1-only writes:

1. Stop the D1-backed collector and API.
2. Restore the previous MySQL environment configuration.
3. Verify the MySQL collector state still points to the correct source log position.
4. Start the MySQL API, verify it, then start exactly one MySQL collector.
5. Confirm ingestion and lag, then reopen access.

After D1 has accepted writes, do not simply switch back. The Worker has no
general D1-to-MySQL exporter, and doing so would lose D1-only auth, config,
cache, and event changes. Keep services stopped or read-only, export and
reconcile the D1 delta with a reviewed one-off process, verify it in MySQL, then
follow the rollback sequence. If reconciliation cannot be completed inside the
window, fix forward on D1 or restore D1 using the Cloudflare recovery mechanism
available to the account.

## Security And Cost Controls

- Use a MySQL migration account with read-only access and revoke it after acceptance.
- Keep MySQL credentials, the gateway bearer token, and Cloudflare deployment credentials separate.
- Never write tokens, source addresses, user destinations, or raw event samples to migration logs.
- Encrypt backups and checkpoint files, restrict permissions, and delete temporary exports after the rollback window.
- Estimate Worker requests as imported rows divided by batch size for each table, plus retries and verification. D1 rows written and storage also contribute to cost.
- Repeated full imports consume writes even when rows are ignored. Resume from checkpoints and use focused final deltas.
- Keep retention enabled and alert well before the database size limit; reaching the limit during ingestion is an outage condition.
