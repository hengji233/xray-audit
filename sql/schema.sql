CREATE TABLE IF NOT EXISTS audit_raw_events (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  event_time DATETIME(6) NOT NULL,
  event_type VARCHAR(16) NOT NULL,
  raw_line TEXT NOT NULL,
  raw_hash CHAR(64) NOT NULL,
  node_id VARCHAR(32) NOT NULL,
  ingested_at DATETIME(6) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uniq_raw_hash_time_node (raw_hash, event_time, node_id),
  KEY idx_event_time (event_time),
  KEY idx_event_type_time (event_type, event_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS audit_access_events (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  raw_event_id BIGINT UNSIGNED NOT NULL,
  event_time DATETIME(6) NOT NULL,
  user_email VARCHAR(191) NOT NULL,
  src VARCHAR(255) NOT NULL,
  dest_raw VARCHAR(512) NOT NULL,
  dest_host VARCHAR(191) NOT NULL,
  dest_port INT NULL,
  status VARCHAR(32) NOT NULL,
  detour VARCHAR(255) NOT NULL,
  reason TEXT NOT NULL,
  is_domain TINYINT(1) NOT NULL,
  confidence VARCHAR(16) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uniq_access_raw_event (raw_event_id),
  KEY idx_user_time (user_email, event_time),
  KEY idx_dest_host_time (dest_host, event_time),
  KEY idx_event_time (event_time),
  KEY idx_event_time_user (event_time, user_email),
  KEY idx_event_time_dest_host (event_time, dest_host),
  KEY idx_event_time_detour (event_time, detour),
  KEY idx_event_time_status (event_time, status),
  CONSTRAINT fk_access_raw_event FOREIGN KEY (raw_event_id)
    REFERENCES audit_raw_events(id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS audit_dns_events (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  raw_event_id BIGINT UNSIGNED NOT NULL,
  event_time DATETIME(6) NOT NULL,
  dns_server VARCHAR(255) NOT NULL,
  domain VARCHAR(191) NOT NULL,
  ips_json JSON NOT NULL,
  dns_status VARCHAR(64) NOT NULL,
  elapsed_ms INT NULL,
  error_text TEXT NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uniq_dns_raw_event (raw_event_id),
  KEY idx_domain_time (domain, event_time),
  KEY idx_event_time (event_time),
  CONSTRAINT fk_dns_raw_event FOREIGN KEY (raw_event_id)
    REFERENCES audit_raw_events(id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS collector_state (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  file_path VARCHAR(255) NOT NULL,
  inode BIGINT NULL,
  last_offset BIGINT NOT NULL,
  updated_at DATETIME(6) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uniq_file_path (file_path)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS audit_ip_geo_cache (
  ip VARCHAR(45) NOT NULL,
  country VARCHAR(64) NOT NULL,
  region VARCHAR(128) NOT NULL,
  city VARCHAR(128) NOT NULL,
  isp VARCHAR(128) NOT NULL,
  addr VARCHAR(255) NOT NULL,
  status VARCHAR(16) NOT NULL,
  source VARCHAR(32) NOT NULL,
  raw_json JSON NULL,
  updated_at DATETIME(6) NOT NULL,
  PRIMARY KEY (ip),
  KEY idx_updated_at (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

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
  KEY idx_err_sig_time (signature_hash, event_time),
  FULLTEXT KEY ft_err_lookup (component, message, src, dest_raw)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS audit_job_state (
  state_key VARCHAR(128) NOT NULL,
  value_text TEXT NOT NULL,
  updated_at DATETIME(6) NOT NULL,
  PRIMARY KEY (state_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS audit_admin_users (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  username VARCHAR(64) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  token_version INT NOT NULL DEFAULT 0,
  is_enabled TINYINT(1) NOT NULL DEFAULT 1,
  must_change_password TINYINT(1) NOT NULL DEFAULT 0,
  last_login_at DATETIME(6) NULL,
  created_at DATETIME(6) NOT NULL,
  updated_at DATETIME(6) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uniq_admin_username (username),
  KEY idx_admin_enabled (is_enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS audit_runtime_config (
  config_key VARCHAR(128) NOT NULL,
  value_json JSON NOT NULL,
  value_type VARCHAR(32) NOT NULL,
  scope VARCHAR(64) NOT NULL,
  updated_by VARCHAR(64) NOT NULL,
  updated_at DATETIME(6) NOT NULL,
  PRIMARY KEY (config_key),
  KEY idx_runtime_updated_at (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS audit_runtime_config_history (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  config_key VARCHAR(128) NOT NULL,
  old_value_json JSON NULL,
  new_value_json JSON NOT NULL,
  changed_by VARCHAR(64) NOT NULL,
  source_ip VARCHAR(64) NOT NULL,
  changed_at DATETIME(6) NOT NULL,
  PRIMARY KEY (id),
  KEY idx_config_changed_at (changed_at),
  KEY idx_config_key_changed_at (config_key, changed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS audit_auth_events (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  event_type VARCHAR(32) NOT NULL,
  username VARCHAR(64) NOT NULL,
  source_ip VARCHAR(64) NOT NULL,
  user_agent VARCHAR(500) NOT NULL,
  event_time DATETIME(6) NOT NULL,
  PRIMARY KEY (id),
  KEY idx_auth_event_time (event_time),
  KEY idx_auth_event_user_time (username, event_time),
  KEY idx_auth_event_type_time (event_type, event_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
