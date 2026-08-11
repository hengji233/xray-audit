# Storage Modes

## Memory
`memory` is the fresh systemd installation default. It requires no SQL server,
credentials, schema initialization, or migration command. It is intended for a
small single-node deployment and the default one-API topology.

Access events are held in a bounded, thread-safe ring buffer and are lost on
process restart. DNS and unknown access-log lines are not stored. Error events
always use a separate bounded process-local ring buffer, regardless of the
selected access backend. The local SQLite control database persists login users,
runtime settings, collector cursors, and encrypted backend credentials, but
never audit events.

## MySQL
MySQL is an explicitly configured persistent access-log mode. Operators provision
the server, credentials, schema, migrations, backups, and availability. The
host installer never installs MySQL and never invokes `xray-audit-initdb`.
The settings page can save an encrypted password, test connectivity, and
activate MySQL after explicit confirmation. It does not create the database or
run schema migrations automatically. Version 0.2.0 uses one compact
`audit_access_events` table, stores no raw log text, and defaults to 30-day
retention. DNS, unknown, and error events are never written to MySQL.

## Cloudflare D1
D1 is accessed only through the authenticated Worker gateway. It uses the same
access-only contract as MySQL. Operators deploy
the Worker and migrations separately, then configure gateway URL and token.
See `D1_DEPLOYMENT.md` and `MYSQL_TO_D1_MIGRATION.md`.

## Redis
Redis is an optional cache and realtime aggregation dependency, not the source
of truth. Fresh systemd installation disables it. Enabling it is an operator
decision and requires separate security, persistence, and capacity controls.

Never point two collectors at the same Xray logs unless the chosen storage
contract explicitly supports duplicate ingestion and coordinated offsets.
