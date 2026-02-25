CREATE TABLE IF NOT EXISTS audit_error_events (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  event_time DATETIME(6) NOT NULL,
  level VARCHAR(16) NOT NULL,
  session_id BIGINT NULL,
  component VARCHAR(191) NOT NULL,
  message TEXT NOT NULL,
  src VARCHAR(255) NOT NULL,
  dest_raw VARCHAR(512) NOT NULL,
  dest_host VARCHAR(191) NOT NULL,
  dest_port INT NULL,
  category VARCHAR(64) NOT NULL,
  signature_hash CHAR(64) NOT NULL,
  is_noise TINYINT(1) NOT NULL,
  raw_line TEXT NOT NULL,
  raw_hash CHAR(64) NOT NULL,
  node_id VARCHAR(32) NOT NULL,
  ingested_at DATETIME(6) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uniq_err_raw_hash_time_node (raw_hash, event_time, node_id),
  KEY idx_err_event_time (event_time),
  KEY idx_err_level_time (level, event_time),
  KEY idx_err_category_time (category, event_time),
  KEY idx_err_noise_time (is_noise, event_time),
  KEY idx_err_sig_time (signature_hash, event_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS audit_job_state (
  state_key VARCHAR(128) NOT NULL,
  value_text TEXT NOT NULL,
  updated_at DATETIME(6) NOT NULL,
  PRIMARY KEY (state_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
