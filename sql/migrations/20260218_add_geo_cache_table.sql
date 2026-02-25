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
