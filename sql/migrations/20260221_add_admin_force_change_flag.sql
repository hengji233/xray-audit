SET @db := DATABASE();
SET @col_exists := (
  SELECT COUNT(1)
  FROM information_schema.columns
  WHERE table_schema = @db
    AND table_name = 'audit_admin_users'
    AND column_name = 'must_change_password'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE audit_admin_users ADD COLUMN must_change_password TINYINT(1) NOT NULL DEFAULT 0 AFTER is_enabled',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- If bootstrap account has never logged in, force password change on next login.
UPDATE audit_admin_users
SET must_change_password = 1
WHERE username = 'admin'
  AND last_login_at IS NULL;
