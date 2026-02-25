export interface AccessEventRow {
  id?: number;
  event_time: string;
  event_type: string;
  raw_line: string;
  node_id?: string;
  user_email?: string;
  src?: string;
  dest_raw?: string;
  dest_host?: string;
  dest_port?: number | null;
  status?: string;
  detour?: string;
  reason?: string;
  is_domain?: number | boolean;
  confidence?: string;
  dns_server?: string;
  domain?: string;
  ips_json?: string;
  dns_status?: string;
  elapsed_ms?: number | null;
  error_text?: string;
}

export interface HealthResponse {
  node_id: string;
  collector_embedded: boolean;
  log_path: string;
  error_log_path?: string;
  db_state: Record<string, unknown> | null;
  db_error_state?: Record<string, unknown> | null;
  redis_health: Record<string, unknown> | null;
  local_stats: Record<string, unknown> | null;
  collector_lag_seconds?: number | null;
  api_metrics?: Record<string, unknown> | null;
  alerts?: Array<{ code: string; severity: string; message: string }>;
  now: string;
}

export interface QueryResponse<T> {
  total: number;
  page: number;
  page_size: number;
  items: T[];
}

export interface SummaryStats {
  window: string;
  total_events: number;
  unique_users: number;
  unique_domains: number;
  qpm: number;
}

export interface DomainHit {
  domain: string;
  hits: number;
}

export interface ActiveUser {
  user_email: string;
  last_seen_unix: number;
}

export interface UserSummary {
  user_email: string;
  count: number;
  last_seen: string;
  unique_dest_host_count: number;
}

export interface GeoIPItem {
  ip: string;
  country: string;
  region: string;
  city: string;
  isp: string;
  addr: string;
  status: string;
  source: string;
  label: string;
  updated_at?: string;
}

export interface ErrorEventRow {
  id: number;
  event_time: string;
  level: string;
  session_id: number | null;
  component: string;
  message: string;
  src: string;
  dest_raw: string;
  dest_host?: string;
  dest_port?: number | null;
  category: string;
  signature_hash: string;
  is_noise: number | boolean;
  node_id: string;
}

export interface ErrorCategoryHit {
  category: string;
  hits: number;
}

export interface ErrorSummary {
  window: string;
  total: number;
  error_count: number;
  warning_count: number;
  info_count: number;
  noise_count: number;
  top_categories: ErrorCategoryHit[];
}

export interface AuthMe {
  username: string;
  auth_enabled?: boolean;
  must_change_password?: boolean;
}

export interface RuntimeConfigSchemaItem {
  config_key: string;
  group: string;
  group_label: string;
  label: string;
  description: string;
  value_type: string;
  min_value?: number | null;
  max_value?: number | null;
  options?: string[];
  default_value?: unknown;
  editable: boolean;
  sensitive: boolean;
}

export interface RuntimeConfigCurrentItem {
  config_key: string;
  value: unknown;
  source: "env" | "db";
  updated_by?: string | null;
  updated_at?: string | null;
}

export interface RuntimeConfigHistoryItem {
  id: number;
  config_key: string;
  old_value_json: string | null;
  new_value_json: string;
  changed_by: string;
  source_ip: string;
  changed_at: string;
}
