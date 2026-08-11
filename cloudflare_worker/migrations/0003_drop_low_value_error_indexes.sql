-- Error list filters are infrequent; the time covering index bounds those scans
-- while avoiding two additional index writes for every error event.
DROP INDEX IF EXISTS idx_err_level_time;
DROP INDEX IF EXISTS idx_err_category_time;
