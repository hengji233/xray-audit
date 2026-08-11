-- Reduce D1 write amplification and align indexes with actual query predicates.
DROP INDEX IF EXISTS idx_raw_type_time;

DROP INDEX IF EXISTS idx_access_dest_time;
DROP INDEX IF EXISTS idx_access_status;
DROP INDEX IF EXISTS idx_access_detour;
CREATE INDEX IF NOT EXISTS idx_access_domain_time
  ON audit_access_events(event_time, dest_host)
  WHERE is_domain = 1 AND dest_host <> '';

DROP INDEX IF EXISTS idx_err_time;
DROP INDEX IF EXISTS idx_err_noise_time;
DROP INDEX IF EXISTS idx_err_sig_time;
CREATE INDEX IF NOT EXISTS idx_err_time_category_sig
  ON audit_error_events(event_time, category, signature_hash);
