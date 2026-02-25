SET @db := DATABASE();
SET @idx_exists := (
  SELECT COUNT(1)
  FROM information_schema.statistics
  WHERE table_schema = @db
    AND table_name = 'audit_error_events'
    AND index_name = 'ft_err_lookup'
);
SET @sql := IF(
  @idx_exists = 0,
  'ALTER TABLE audit_error_events ADD FULLTEXT KEY ft_err_lookup (component, message, src, dest_raw)',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
