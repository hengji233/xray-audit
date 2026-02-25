from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import AuthService, extract_client_ip, sanitize_user_agent, validate_password_strength
from .collector import AuditCollector
from .config import Settings
from .geoip import GeoIPService
from .redis_cache import RedisCache
from .runtime_config import RuntimeConfigManager
from .storage import AuditQueryService

settings = Settings.from_env()
query_service = AuditQueryService(settings)
runtime_config = RuntimeConfigManager(settings, query_service)
redis_cache = RedisCache(settings)
geoip_service = GeoIPService(settings, query_service, runtime_config=runtime_config)
auth_service = AuthService(settings, query_service)
collector: AuditCollector | None = None
API_ALERT_WINDOW_SECONDS = 300


class ApiMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests_total = 0
        self._responses_401_total = 0
        self._responses_5xx_total = 0
        self._recent_request_ts: List[float] = []
        self._recent_5xx_ts: List[float] = []
        self._last_5xx_at: Optional[datetime] = None

    def record(self, status_code: int) -> None:
        now = time.time()
        with self._lock:
            self._requests_total += 1
            self._recent_request_ts.append(now)
            if status_code == 401:
                self._responses_401_total += 1
            if status_code >= 500:
                self._responses_5xx_total += 1
                self._recent_5xx_ts.append(now)
                self._last_5xx_at = datetime.utcnow()
            self._prune(now)

    def snapshot(self) -> Dict[str, Any]:
        now = time.time()
        with self._lock:
            self._prune(now)
            requests_5m = len(self._recent_request_ts)
            responses_5xx_5m = len(self._recent_5xx_ts)
            error_rate_5xx_5m = (responses_5xx_5m / requests_5m) if requests_5m > 0 else 0.0
            return {
                "requests_total": self._requests_total,
                "responses_401_total": self._responses_401_total,
                "responses_5xx_total": self._responses_5xx_total,
                "requests_5m": requests_5m,
                "responses_5xx_5m": responses_5xx_5m,
                "error_rate_5xx_5m": round(error_rate_5xx_5m, 6),
                "last_5xx_at": self._last_5xx_at,
            }

    def _prune(self, now_ts: float) -> None:
        threshold = now_ts - API_ALERT_WINDOW_SECONDS
        while self._recent_request_ts and self._recent_request_ts[0] < threshold:
            self._recent_request_ts.pop(0)
        while self._recent_5xx_ts and self._recent_5xx_ts[0] < threshold:
            self._recent_5xx_ts.pop(0)


api_metrics = ApiMetrics()

app = FastAPI(title="Xray Audit API", version="0.2.0")

_frontend_dist_dir = Path(__file__).resolve().parent / "frontend_dist"
_dashboard_dir = Path(__file__).resolve().parent / "dashboard"
if _dashboard_dir.exists():
    app.mount("/dashboard", StaticFiles(directory=str(_dashboard_dir), html=True), name="dashboard")
_frontend_assets_dir = _frontend_dist_dir / "assets"
if _frontend_assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(_frontend_assets_dir)), name="frontend-assets")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


class UpdateRuntimeConfigRequest(BaseModel):
    items: Dict[str, Any] = Field(default_factory=dict)


class GeoIPBatchRequest(BaseModel):
    ips: List[str] = Field(default_factory=list)


@app.on_event("startup")
def startup() -> None:
    auth_service.bootstrap_admin_if_needed()
    global collector
    if settings.collector_embedded:
        collector = AuditCollector(settings)
        collector.start()


@app.on_event("shutdown")
def shutdown() -> None:
    if collector is not None:
        collector.stop()


@app.middleware("http")
async def auth_and_cache_control(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/v1"):
        if settings.auth_enabled and request.method.upper() != "OPTIONS":
            allow_unauth = path == "/api/v1/auth/login" or path == "/api/v1/auth/me"
            if path in {"/api/v1/health", "/api/v1/metrics"} and settings.auth_allow_anonymous_health:
                allow_unauth = True
            if not allow_unauth:
                user = auth_service.get_current_user(request)
                if user is None:
                    api_metrics.record(401)
                    return JSONResponse(status_code=401, content={"detail": "unauthorized"}, headers={"Cache-Control": "no-store"})
                request.state.auth_user = user
                if user.must_change_password and path not in {
                    "/api/v1/auth/me",
                    "/api/v1/auth/change-password",
                    "/api/v1/auth/logout",
                }:
                    api_metrics.record(403)
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "password change required"},
                        headers={"Cache-Control": "no-store"},
                    )
        try:
            response = await call_next(request)
        except Exception:
            api_metrics.record(500)
            raise
        api_metrics.record(int(response.status_code))
        response.headers["Cache-Control"] = "no-store"
        return response

    response = await call_next(request)
    if path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


def _require_user(request: Request) -> str:
    if not settings.auth_enabled:
        return "system"
    user = getattr(request.state, "auth_user", None)
    if user is None:
        user = auth_service.get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    return user.username


def _set_auth_cookie(response: Response, token: str) -> None:
    domain = settings.auth_cookie_domain if settings.auth_cookie_domain else None
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        max_age=settings.auth_jwt_exp_seconds,
        domain=domain,
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    domain = settings.auth_cookie_domain if settings.auth_cookie_domain else None
    response.delete_cookie(
        key=settings.auth_cookie_name,
        domain=domain,
        path="/",
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        httponly=True,
    )


@app.post("/api/v1/auth/login")
def login(payload: LoginRequest, request: Request, response: Response) -> Dict[str, Any]:
    if not settings.auth_enabled:
        raise HTTPException(status_code=400, detail="auth is disabled")
    username = payload.username.strip()
    source_ip = extract_client_ip(request)
    user_agent = sanitize_user_agent(request)

    user = auth_service.authenticate(
        username=username,
        password=payload.password,
        source_ip=source_ip,
        user_agent=user_agent,
    )
    if user is None:
        raise HTTPException(status_code=401, detail="invalid username or password")

    token = auth_service.create_token(user)
    _set_auth_cookie(response, token)
    return {
        "username": user.username,
        "expires_in": settings.auth_jwt_exp_seconds,
        "must_change_password": user.must_change_password,
    }


@app.post("/api/v1/auth/logout")
def logout(request: Request, response: Response) -> Dict[str, Any]:
    username = _require_user(request)
    auth_service.logout(
        username=username,
        source_ip=extract_client_ip(request),
        user_agent=sanitize_user_agent(request),
    )
    _clear_auth_cookie(response)
    return {"ok": True}


@app.get("/api/v1/auth/me")
def me(request: Request) -> Dict[str, Any]:
    if not settings.auth_enabled:
        return {"username": "system", "auth_enabled": False, "must_change_password": False}
    user = auth_service.get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    return {
        "username": user.username,
        "auth_enabled": True,
        "must_change_password": user.must_change_password,
    }


@app.post("/api/v1/auth/change-password")
def change_password(payload: ChangePasswordRequest, request: Request, response: Response) -> Dict[str, Any]:
    username = _require_user(request)
    err = validate_password_strength(payload.new_password)
    if err:
        raise HTTPException(status_code=400, detail=err)

    ok = auth_service.change_password(
        username=username,
        old_password=payload.old_password,
        new_password=payload.new_password,
        source_ip=extract_client_ip(request),
        user_agent=sanitize_user_agent(request),
    )
    if not ok:
        raise HTTPException(status_code=400, detail="old password is incorrect")

    refreshed = auth_service.authenticate(
        username=username,
        password=payload.new_password,
        source_ip=extract_client_ip(request),
        user_agent=sanitize_user_agent(request),
    )
    if refreshed is not None:
        _set_auth_cookie(response, auth_service.create_token(refreshed))
    return {"ok": True}


@app.get("/api/v1/config/schema")
def config_schema(request: Request) -> Dict[str, Any]:
    _require_user(request)
    return {"items": runtime_config.schema_items()}


@app.get("/api/v1/config/current")
def config_current(request: Request) -> Dict[str, Any]:
    _require_user(request)
    return {"items": runtime_config.current_items()}


@app.put("/api/v1/config/current")
def config_update(payload: UpdateRuntimeConfigRequest, request: Request) -> Dict[str, Any]:
    username = _require_user(request)
    try:
        items = runtime_config.update_items(
            values=payload.items,
            changed_by=username,
            source_ip=extract_client_ip(request),
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))
    return {"items": items}


@app.get("/api/v1/config/history")
def config_history(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
) -> Dict[str, Any]:
    _require_user(request)
    total, rows = query_service.runtime_config_history(page=page, page_size=page_size)
    return {"total": total, "page": page, "page_size": page_size, "items": rows}


@app.get("/")
def root() -> FileResponse:
    index_path = _frontend_dist_dir / "index.html"
    if not index_path.exists():
        index_path = _dashboard_dir / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="dashboard not found")
    return FileResponse(index_path)


@app.get("/api/v1/health")
def health(request: Request) -> Dict[str, Any]:
    if settings.auth_enabled and not settings.auth_allow_anonymous_health:
        _require_user(request)

    state = query_service.collector_state(settings.log_path)
    error_state = query_service.collector_state(settings.error_log_path) if settings.error_log_enabled else None
    cache_health = redis_cache.get_health()
    local_stats = collector.stats_snapshot() if collector is not None else None
    api_metrics_snapshot = api_metrics.snapshot()
    collector_lag_seconds = _calc_collector_lag_seconds(
        now_utc=datetime.utcnow(),
        local_stats=local_stats,
        db_state=state,
        db_error_state=error_state,
    )
    alerts = _build_alerts(collector_lag_seconds=collector_lag_seconds, api_metrics_snapshot=api_metrics_snapshot)

    return {
        "node_id": settings.node_id,
        "collector_embedded": settings.collector_embedded,
        "log_path": settings.log_path,
        "error_log_path": settings.error_log_path,
        "db_state": state,
        "db_error_state": error_state,
        "redis_health": cache_health,
        "local_stats": local_stats,
        "collector_lag_seconds": collector_lag_seconds,
        "api_metrics": api_metrics_snapshot,
        "alerts": alerts,
        "runtime_config_refresh_seconds": settings.runtime_config_refresh_seconds,
        "now": datetime.utcnow().isoformat(),
    }


@app.get("/api/v1/metrics")
def metrics(request: Request) -> PlainTextResponse:
    if settings.auth_enabled and not settings.auth_allow_anonymous_health:
        _require_user(request)

    state = query_service.collector_state(settings.log_path)
    error_state = query_service.collector_state(settings.error_log_path) if settings.error_log_enabled else None
    local_stats = collector.stats_snapshot() if collector is not None else None
    api_snapshot = api_metrics.snapshot()
    lag = _calc_collector_lag_seconds(
        now_utc=datetime.utcnow(),
        local_stats=local_stats,
        db_state=state,
        db_error_state=error_state,
    )
    lines = [
        f"xray_audit_api_requests_total {api_snapshot['requests_total']}",
        f"xray_audit_api_responses_401_total {api_snapshot['responses_401_total']}",
        f"xray_audit_api_responses_5xx_total {api_snapshot['responses_5xx_total']}",
        f"xray_audit_api_requests_5m {api_snapshot['requests_5m']}",
        f"xray_audit_api_responses_5xx_5m {api_snapshot['responses_5xx_5m']}",
        f"xray_audit_api_error_rate_5xx_5m {api_snapshot['error_rate_5xx_5m']}",
    ]
    if lag is not None:
        lines.append(f"xray_audit_collector_lag_seconds {lag}")
    if local_stats is not None:
        db_write_fail_total = int(local_stats.get("db_write_fail_total", 0) or 0)
        db_last_write_latency_ms = float(local_stats.get("db_last_write_latency_ms", 0) or 0)
        lines.append(f"xray_audit_collector_db_write_fail_total {db_write_fail_total}")
        lines.append(f"xray_audit_collector_db_last_write_latency_ms {db_last_write_latency_ms}")
    return PlainTextResponse(content="\n".join(lines) + "\n")


@app.get("/api/v1/events/recent")
def recent_events(
    request: Request,
    seconds: int = Query(default=10, ge=1, le=3600),
    limit: int = Query(default=200, ge=1, le=2000),
) -> Dict[str, Any]:
    _require_user(request)
    rows = query_service.recent_events(seconds=seconds, limit=limit)
    return {"seconds": seconds, "limit": limit, "items": rows}


@app.get("/api/v1/events/query")
def query_events(
    request: Request,
    from_ts: str = Query(alias="from"),
    to_ts: str = Query(alias="to"),
    email: str | None = Query(default=None),
    dest_host: str | None = Query(default=None),
    status: str | None = Query(default=None),
    detour: str | None = Query(default=None),
    is_domain: bool | None = Query(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=50),
) -> Dict[str, Any]:
    _require_user(request)
    dt_from = _parse_datetime_or_400(from_ts, "from")
    dt_to = _parse_datetime_or_400(to_ts, "to")
    _validate_time_range(dt_from, dt_to)
    _validate_pagination(page=page, page_size=page_size, max_page_size=500)

    total, rows = query_service.query_events(
        dt_from=dt_from,
        dt_to=dt_to,
        email=email,
        dest_host=dest_host,
        status=status,
        detour=detour,
        is_domain=is_domain,
        page=page,
        page_size=page_size,
    )
    return {
        "from": dt_from.isoformat(),
        "to": dt_to.isoformat(),
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": rows,
    }


@app.get("/api/v1/users/{email}/visits")
def user_visits(
    request: Request,
    email: str,
    from_ts: str | None = Query(default=None, alias="from"),
    to_ts: str | None = Query(default=None, alias="to"),
    page: int = Query(default=1),
    page_size: int = Query(default=100),
    limit: int | None = Query(default=None),
) -> Dict[str, Any]:
    _require_user(request)
    dt_to = _parse_datetime_or_400(to_ts, "to") if to_ts else datetime.utcnow()
    dt_from = _parse_datetime_or_400(from_ts, "from") if from_ts else (dt_to - timedelta(days=1))
    _validate_time_range(dt_from, dt_to)

    if limit is not None:
        if limit < 1 or limit > 5000:
            raise HTTPException(status_code=400, detail="limit must be between 1 and 5000")
        page = 1
        page_size = limit
    else:
        _validate_pagination(page=page, page_size=page_size, max_page_size=500)

    total, rows = query_service.user_visits_paged(
        email=email,
        dt_from=dt_from,
        dt_to=dt_to,
        page=page,
        page_size=page_size,
    )
    return {
        "email": email,
        "from": dt_from.isoformat(),
        "to": dt_to.isoformat(),
        "total": total,
        "page": page,
        "page_size": page_size,
        "limit": page_size,
        "items": rows,
    }


@app.get("/api/v1/users/list")
def list_users(
    request: Request,
    from_ts: str = Query(alias="from"),
    to_ts: str = Query(alias="to"),
    page: int = Query(default=1),
    page_size: int = Query(default=50),
) -> Dict[str, Any]:
    _require_user(request)
    dt_from = _parse_datetime_or_400(from_ts, "from")
    dt_to = _parse_datetime_or_400(to_ts, "to")
    _validate_time_range(dt_from, dt_to)
    _validate_pagination(page=page, page_size=page_size, max_page_size=500)

    total, rows = query_service.list_users(
        dt_from=dt_from,
        dt_to=dt_to,
        page=page,
        page_size=page_size,
    )
    return {
        "from": dt_from.isoformat(),
        "to": dt_to.isoformat(),
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": rows,
    }


@app.get("/api/v1/domains/top")
def top_domains(
    request: Request,
    window: str = Query(default="5m"),
    limit: int = Query(default=20, ge=1, le=500),
) -> Dict[str, Any]:
    _require_user(request)
    seconds = _parse_window_to_seconds(window)

    redis_enabled = runtime_config.get_bool("AUDIT_REDIS_ENABLED", settings.redis_enabled)
    items: List[Dict[str, Any]] = []
    if redis_enabled and redis_cache.enabled and seconds == 300:
        items = redis_cache.top_domains(minutes=5, limit=limit)

    if not items:
        items = query_service.top_domains(seconds=seconds, limit=limit)

    return {"window": window, "limit": limit, "items": items}


@app.get("/api/v1/users/active")
def active_users(
    request: Request,
    seconds: int = Query(default=30, ge=1, le=3600),
    limit: int = Query(default=200, ge=1, le=5000),
) -> Dict[str, Any]:
    _require_user(request)
    redis_enabled = runtime_config.get_bool("AUDIT_REDIS_ENABLED", settings.redis_enabled)
    items: List[Dict[str, Any]] = []
    if redis_enabled and redis_cache.enabled:
        items = redis_cache.active_users(seconds=seconds, limit=limit)

    if not items:
        items = query_service.active_users(seconds=seconds, limit=limit)

    return {"seconds": seconds, "limit": limit, "items": items}


@app.get("/api/v1/stats/summary")
def stats_summary(request: Request, window: str = Query(default="5m")) -> Dict[str, Any]:
    _require_user(request)
    seconds = _parse_window_to_seconds(window)
    stats = query_service.summary_stats(window_seconds=seconds)
    return {"window": window, **stats}


@app.get("/api/v1/errors/query")
def query_errors(
    request: Request,
    from_ts: str = Query(alias="from"),
    to_ts: str = Query(alias="to"),
    level: str | None = Query(default=None),
    category: str | None = Query(default=None),
    include_noise: bool = Query(default=False),
    keyword: str | None = Query(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=50),
) -> Dict[str, Any]:
    _require_user(request)
    dt_from = _parse_datetime_or_400(from_ts, "from")
    dt_to = _parse_datetime_or_400(to_ts, "to")
    _validate_time_range(dt_from, dt_to)
    _validate_pagination(page=page, page_size=page_size, max_page_size=500)
    if level and level not in {"debug", "info", "warning", "error", "unknown"}:
        raise HTTPException(status_code=400, detail="invalid level")

    total, rows = query_service.query_error_events(
        dt_from=dt_from,
        dt_to=dt_to,
        level=level,
        category=category,
        include_noise=include_noise,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return {
        "from": dt_from.isoformat(),
        "to": dt_to.isoformat(),
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": rows,
    }


@app.get("/api/v1/errors/summary")
def error_summary(request: Request, window: str = Query(default="1h")) -> Dict[str, Any]:
    _require_user(request)
    seconds = _parse_window_to_seconds(window)
    data = query_service.error_summary_stats(window_seconds=seconds)
    return {"window": window, **data}


@app.post("/api/v1/geoip/batch")
def geoip_batch(request: Request, payload: GeoIPBatchRequest) -> Dict[str, Any]:
    _require_user(request)
    batch_limit = runtime_config.get_int("AUDIT_GEOIP_BATCH_LIMIT", settings.geoip_batch_limit)
    if len(payload.ips) > batch_limit:
        raise HTTPException(status_code=400, detail=f"ips length must be <= {batch_limit}")
    items = geoip_service.lookup_batch(payload.ips)
    return {"count": len(items), "items": items}


@app.get("/{full_path:path}")
def spa_fallback(full_path: str) -> FileResponse:
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="not found")

    if full_path:
        candidate = (_frontend_dist_dir / full_path).resolve()
        dist_root = _frontend_dist_dir.resolve()
        if dist_root in candidate.parents and candidate.is_file():
            return FileResponse(candidate)

    index_path = _frontend_dist_dir / "index.html"
    if not index_path.exists():
        index_path = _dashboard_dir / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="frontend not found")
    return FileResponse(index_path)


def _parse_datetime_or_400(raw: str, field_name: str) -> datetime:
    normalized = raw.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=f"invalid datetime format for {field_name}: {err}")

    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _validate_time_range(dt_from: datetime, dt_to: datetime) -> None:
    if dt_from > dt_to:
        raise HTTPException(status_code=400, detail="'from' must be less than or equal to 'to'")


def _validate_pagination(page: int, page_size: int, max_page_size: int) -> None:
    if page < 1:
        raise HTTPException(status_code=400, detail="page must be >= 1")
    if page_size < 1 or page_size > max_page_size:
        raise HTTPException(status_code=400, detail=f"page_size must be between 1 and {max_page_size}")


def _parse_window_to_seconds(window: str) -> int:
    raw = window.strip().lower()
    if raw.endswith("h") and raw[:-1].isdigit():
        value = int(raw[:-1]) * 3600
        if value < 1:
            raise HTTPException(status_code=400, detail="window must be greater than 0")
        return value
    if raw.endswith("m") and raw[:-1].isdigit():
        value = int(raw[:-1]) * 60
        if value < 1:
            raise HTTPException(status_code=400, detail="window must be greater than 0")
        return value
    if raw.endswith("s") and raw[:-1].isdigit():
        value = int(raw[:-1])
        if value < 1:
            raise HTTPException(status_code=400, detail="window must be greater than 0")
        return value
    raise HTTPException(status_code=400, detail="window format must be like '5m', '1h' or '30s'")


def _as_utc_naive(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _calc_collector_lag_seconds(
    now_utc: datetime,
    local_stats: Optional[Dict[str, Any]],
    db_state: Optional[Dict[str, Any]],
    db_error_state: Optional[Dict[str, Any]],
) -> Optional[int]:
    candidates: List[datetime] = []
    if local_stats:
        for key in ("last_flush_time", "last_event_time", "last_error_event_time"):
            dt = _as_utc_naive(local_stats.get(key))
            if dt is not None:
                candidates.append(dt)
    if db_state:
        dt = _as_utc_naive(db_state.get("updated_at"))
        if dt is not None:
            candidates.append(dt)
    if db_error_state:
        dt = _as_utc_naive(db_error_state.get("updated_at"))
        if dt is not None:
            candidates.append(dt)
    if not candidates:
        return None
    latest = max(candidates)
    return max(0, int((now_utc - latest).total_seconds()))


def _build_alerts(collector_lag_seconds: Optional[int], api_metrics_snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    alerts: List[Dict[str, Any]] = []
    if collector_lag_seconds is not None and collector_lag_seconds > 30:
        alerts.append(
            {
                "code": "collector_lag",
                "severity": "critical" if collector_lag_seconds > 120 else "warning",
                "message": f"collector lag is {collector_lag_seconds}s",
            }
        )

    requests_5m = int(api_metrics_snapshot.get("requests_5m", 0) or 0)
    errors_5xx_5m = int(api_metrics_snapshot.get("responses_5xx_5m", 0) or 0)
    error_rate_5xx_5m = float(api_metrics_snapshot.get("error_rate_5xx_5m", 0.0) or 0.0)
    if requests_5m >= 20 and (errors_5xx_5m >= 5 or error_rate_5xx_5m >= 0.05):
        alerts.append(
            {
                "code": "api_5xx_rate",
                "severity": "critical" if errors_5xx_5m >= 20 else "warning",
                "message": f"api 5xx in 5m: {errors_5xx_5m}/{requests_5m} ({round(error_rate_5xx_5m * 100, 2)}%)",
            }
        )
    return alerts
