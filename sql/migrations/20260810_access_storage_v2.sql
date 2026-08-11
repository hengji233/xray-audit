-- v0.2.0 intentionally discards the old audit event history. Back up first.
DROP TABLE IF EXISTS audit_dns_events;
DROP TABLE IF EXISTS audit_error_events;
DROP TABLE IF EXISTS audit_access_events;
DROP TABLE IF EXISTS audit_raw_events;

CREATE TABLE audit_access_events (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  event_time DATETIME(6) NOT NULL,
  user_email VARCHAR(191) NOT NULL,
  src VARCHAR(64) NOT NULL,
  dest_host VARCHAR(191) NOT NULL,
  dest_port SMALLINT UNSIGNED NULL,
  protocol VARCHAR(8) NOT NULL,
  status VARCHAR(16) NOT NULL,
  detour VARCHAR(128) NOT NULL,
  reason VARCHAR(255) NOT NULL,
  is_domain TINYINT(1) NOT NULL,
  node_id VARCHAR(32) NOT NULL,
  event_hash BINARY(16) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uniq_event_hash_time_node (event_hash, event_time, node_id),
  KEY idx_user_time (user_email, event_time, id),
  KEY idx_dest_host_time (dest_host, event_time, id),
  KEY idx_event_time (event_time, id)
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4;
