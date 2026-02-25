from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_csv(name: str, default: str) -> tuple[str, ...]:
    raw = os.getenv(name, default)
    parts = [x.strip() for x in raw.split(",")]
    return tuple(x for x in parts if x)


def _load_env_file_if_present() -> None:
    env_file = os.getenv("AUDIT_ENV_FILE", ".env")
    if not os.path.exists(env_file):
        return

    with open(env_file, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"").strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


@dataclass(frozen=True)
class Settings:
    node_id: str
    log_path: str
    error_log_path: str
    error_log_enabled: bool
    error_min_level: str
    error_drop_noise: bool
    flush_interval_seconds: float
    batch_size: int
    poll_interval_seconds: float

    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str
    mysql_db: str
    mysql_charset: str

    redis_url: str
    redis_enabled: bool

    api_host: str
    api_port: int
    collector_embedded: bool

    drop_api_to_api: bool
    drop_loopback_traffic: bool
    drop_invalid_vless_probe: bool
    exclude_detours: tuple[str, ...]

    retention_days: int
    retention_cleanup_interval_seconds: int
    retention_delete_batch_size: int

    geoip_enabled: bool
    geoip_provider_url: str
    geoip_timeout_seconds: float
    geoip_cache_ttl_hours: int
    geoip_batch_limit: int

    ai_summary_enabled: bool
    ai_summary_interval_seconds: int
    ai_summary_window_minutes: int
    ai_summary_max_items: int
    ai_api_base_url: str
    ai_api_key: str
    ai_api_model: str
    ai_api_timeout_seconds: float
    tg_bot_token: str
    tg_chat_id: str

    runtime_config_refresh_seconds: float

    auth_enabled: bool
    auth_allow_anonymous_health: bool
    auth_jwt_secret: str
    auth_jwt_exp_seconds: int
    auth_cookie_name: str
    auth_cookie_secure: bool
    auth_cookie_samesite: str
    auth_cookie_domain: str
    auth_login_rate_limit: int
    auth_login_rate_window_seconds: int

    admin_bootstrap_username: str
    admin_bootstrap_password: str

    @staticmethod
    def from_env() -> "Settings":
        _load_env_file_if_present()
        auth_secret = os.getenv("AUDIT_AUTH_JWT_SECRET", "").strip()
        if not auth_secret:
            auth_secret = "change-this-secret-in-production"
        return Settings(
            node_id=os.getenv("AUDIT_NODE_ID", "node-1"),
            log_path=os.getenv("AUDIT_LOG_PATH", "/var/log/xray/access.log"),
            error_log_path=os.getenv("AUDIT_ERROR_LOG_PATH", "/var/log/xray/error.log"),
            error_log_enabled=_env_bool("AUDIT_ERROR_LOG_ENABLED", True),
            error_min_level=os.getenv("AUDIT_ERROR_MIN_LEVEL", "warning").strip().lower(),
            error_drop_noise=_env_bool("AUDIT_ERROR_DROP_NOISE", False),
            flush_interval_seconds=float(os.getenv("AUDIT_FLUSH_INTERVAL_SECONDS", "1")),
            batch_size=int(os.getenv("AUDIT_BATCH_SIZE", "300")),
            poll_interval_seconds=float(os.getenv("AUDIT_POLL_INTERVAL_SECONDS", "0.2")),
            mysql_host=os.getenv("AUDIT_MYSQL_HOST", "127.0.0.1"),
            mysql_port=int(os.getenv("AUDIT_MYSQL_PORT", "3306")),
            mysql_user=os.getenv("AUDIT_MYSQL_USER", "xray_audit"),
            mysql_password=os.getenv("AUDIT_MYSQL_PASSWORD", "change-me"),
            mysql_db=os.getenv("AUDIT_MYSQL_DB", "xray_audit"),
            mysql_charset=os.getenv("AUDIT_MYSQL_CHARSET", "utf8mb4"),
            redis_url=os.getenv("AUDIT_REDIS_URL", "redis://127.0.0.1:6379/0"),
            redis_enabled=_env_bool("AUDIT_REDIS_ENABLED", True),
            api_host=os.getenv("AUDIT_API_HOST", "127.0.0.1"),
            api_port=int(os.getenv("AUDIT_API_PORT", "8088")),
            collector_embedded=_env_bool("AUDIT_COLLECTOR_EMBEDDED", False),
            drop_api_to_api=_env_bool("AUDIT_DROP_API_TO_API", True),
            drop_loopback_traffic=_env_bool("AUDIT_DROP_LOOPBACK_TRAFFIC", True),
            drop_invalid_vless_probe=_env_bool("AUDIT_DROP_INVALID_VLESS_PROBE", False),
            exclude_detours=_env_csv("AUDIT_EXCLUDE_DETOURS", ""),
            retention_days=int(os.getenv("AUDIT_RETENTION_DAYS", "30")),
            retention_cleanup_interval_seconds=int(os.getenv("AUDIT_RETENTION_CLEANUP_INTERVAL_SECONDS", "3600")),
            retention_delete_batch_size=int(os.getenv("AUDIT_RETENTION_DELETE_BATCH_SIZE", "5000")),
            geoip_enabled=_env_bool("AUDIT_GEOIP_ENABLED", True),
            geoip_provider_url=os.getenv("AUDIT_GEOIP_PROVIDER_URL", "https://whois.pconline.com.cn/ipJson.jsp"),
            geoip_timeout_seconds=float(os.getenv("AUDIT_GEOIP_TIMEOUT_SECONDS", "3")),
            geoip_cache_ttl_hours=int(os.getenv("AUDIT_GEOIP_CACHE_TTL_HOURS", "168")),
            geoip_batch_limit=int(os.getenv("AUDIT_GEOIP_BATCH_LIMIT", "200")),
            ai_summary_enabled=_env_bool("AUDIT_AI_SUMMARY_ENABLED", False),
            ai_summary_interval_seconds=int(os.getenv("AUDIT_AI_SUMMARY_INTERVAL_SECONDS", "1800")),
            ai_summary_window_minutes=int(os.getenv("AUDIT_AI_SUMMARY_WINDOW_MINUTES", "60")),
            ai_summary_max_items=int(os.getenv("AUDIT_AI_SUMMARY_MAX_ITEMS", "200")),
            ai_api_base_url=os.getenv("AUDIT_AI_API_BASE_URL", ""),
            ai_api_key=os.getenv("AUDIT_AI_API_KEY", ""),
            ai_api_model=os.getenv("AUDIT_AI_API_MODEL", "gpt-4o-mini"),
            ai_api_timeout_seconds=float(os.getenv("AUDIT_AI_API_TIMEOUT_SECONDS", "20")),
            tg_bot_token=os.getenv("AUDIT_TG_BOT_TOKEN", ""),
            tg_chat_id=os.getenv("AUDIT_TG_CHAT_ID", ""),
            runtime_config_refresh_seconds=float(os.getenv("AUDIT_RUNTIME_CONFIG_REFRESH_SECONDS", "3")),
            auth_enabled=_env_bool("AUDIT_AUTH_ENABLED", True),
            auth_allow_anonymous_health=_env_bool("AUDIT_AUTH_ALLOW_ANONYMOUS_HEALTH", False),
            auth_jwt_secret=auth_secret,
            auth_jwt_exp_seconds=int(os.getenv("AUDIT_AUTH_JWT_EXP_SECONDS", "43200")),
            auth_cookie_name=os.getenv("AUDIT_AUTH_COOKIE_NAME", "xray_audit_session"),
            auth_cookie_secure=_env_bool("AUDIT_AUTH_COOKIE_SECURE", True),
            auth_cookie_samesite=os.getenv("AUDIT_AUTH_COOKIE_SAMESITE", "lax").strip().lower(),
            auth_cookie_domain=os.getenv("AUDIT_AUTH_COOKIE_DOMAIN", "").strip(),
            auth_login_rate_limit=int(os.getenv("AUDIT_AUTH_LOGIN_RATE_LIMIT", "8")),
            auth_login_rate_window_seconds=int(os.getenv("AUDIT_AUTH_LOGIN_RATE_WINDOW_SECONDS", "300")),
            admin_bootstrap_username=os.getenv("AUDIT_ADMIN_BOOTSTRAP_USERNAME", "admin").strip(),
            admin_bootstrap_password=os.getenv("AUDIT_ADMIN_BOOTSTRAP_PASSWORD", "ChangeMe123!").strip(),
        )
