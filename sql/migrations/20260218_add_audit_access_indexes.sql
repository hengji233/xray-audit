-- Idempotent index migration for audit_access_events
SET @db_name = DATABASE();

SET @idx_exists = (
  SELECT COUNT(1)
  FROM information_schema.statistics
  WHERE table_schema = @db_name
    AND table_name = 'audit_access_events'
    AND index_name = 'idx_event_time_user'
);
SET @sql = IF(
  @idx_exists = 0,
  'ALTER TABLE audit_access_events ADD INDEX idx_event_time_user (event_time, user_email)',
  'SELECT ''skip idx_event_time_user'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx_exists = (
  SELECT COUNT(1)
  FROM information_schema.statistics
  WHERE table_schema = @db_name
    AND table_name = 'audit_access_events'
    AND index_name = 'idx_event_time_dest_host'
);
SET @sql = IF(
  @idx_exists = 0,
  'ALTER TABLE audit_access_events ADD INDEX idx_event_time_dest_host (event_time, dest_host)',
  'SELECT ''skip idx_event_time_dest_host'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx_exists = (
  SELECT COUNT(1)
  FROM information_schema.statistics
  WHERE table_schema = @db_name
    AND table_name = 'audit_access_events'
    AND index_name = 'idx_event_time_detour'
);
SET @sql = IF(
  @idx_exists = 0,
  'ALTER TABLE audit_access_events ADD INDEX idx_event_time_detour (event_time, detour)',
  'SELECT ''skip idx_event_time_detour'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx_exists = (
  SELECT COUNT(1)
  FROM information_schema.statistics
  WHERE table_schema = @db_name
    AND table_name = 'audit_access_events'
    AND index_name = 'idx_event_time_status'
);
SET @sql = IF(
  @idx_exists = 0,
  'ALTER TABLE audit_access_events ADD INDEX idx_event_time_status (event_time, status)',
  'SELECT ''skip idx_event_time_status'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
