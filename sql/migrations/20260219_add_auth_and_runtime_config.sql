CREATE TABLE IF NOT EXISTS audit_admin_users (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  username VARCHAR(64) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  token_version INT NOT NULL DEFAULT 0,
  is_enabled TINYINT(1) NOT NULL DEFAULT 1,
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
