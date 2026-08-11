-- D1 v0.2.0 stores parsed access events only. Existing audit event data may be discarded.
DROP TABLE IF EXISTS audit_dns_events;
DROP TABLE IF EXISTS audit_access_events;
DROP TABLE IF EXISTS audit_raw_events;
DROP TABLE IF EXISTS audit_error_events;

CREATE TABLE audit_access_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_time TEXT NOT NULL,
  user_email TEXT NOT NULL,
  src TEXT NOT NULL,
  dest_host TEXT NOT NULL,
  dest_port INTEGER,
  protocol TEXT NOT NULL,
  status TEXT NOT NULL,
  detour TEXT NOT NULL,
  reason TEXT NOT NULL,
  is_domain INTEGER NOT NULL CHECK(is_domain IN (0,1)),
  node_id TEXT NOT NULL,
  event_hash TEXT NOT NULL,
  UNIQUE(event_hash, event_time, node_id)
);

CREATE INDEX idx_access_user_time ON audit_access_events(user_email, event_time);
CREATE INDEX idx_access_domain_time ON audit_access_events(event_time, dest_host)
  WHERE is_domain = 1 AND dest_host <> '';
CREATE INDEX idx_access_time ON audit_access_events(event_time);
