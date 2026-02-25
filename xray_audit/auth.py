from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import bcrypt
import jwt
import redis
from fastapi import Request

from .config import Settings
from .storage import AuditQueryService


@dataclass
class AuthUser:
    username: str
    token_version: int
    must_change_password: bool = False


class AuthService:
    def __init__(self, settings: Settings, query_service: AuditQueryService) -> None:
        self.settings = settings
        self.query_service = query_service
        self._redis = self._build_redis_client()

    def bootstrap_admin_if_needed(self) -> None:
        if not self.settings.auth_enabled:
            return
        if self.query_service.admin_user_count() > 0:
            return
        username = self.settings.admin_bootstrap_username.strip()
        password = self.settings.admin_bootstrap_password.strip()
        if not username or not password:
            return
        password_hash = self.hash_password(password)
        self.query_service.admin_user_create(
            username=username,
            password_hash=password_hash,
            must_change_password=True,
        )
        self.query_service.auth_event_insert(
            event_type="bootstrap_admin",
            username=username,
            source_ip="127.0.0.1",
            user_agent="bootstrap",
        )

    def authenticate(self, username: str, password: str, source_ip: str, user_agent: str) -> Optional[AuthUser]:
        if self._is_rate_limited(username=username, source_ip=source_ip):
            self.query_service.auth_event_insert(
                event_type="login_rate_limited",
                username=username,
                source_ip=source_ip,
                user_agent=user_agent,
            )
            return None

        row = self.query_service.admin_user_get(username)
        if not row:
            self._record_login_fail(username=username, source_ip=source_ip, user_agent=user_agent)
            return None
        if int(row.get("is_enabled", 0) or 0) != 1:
            self._record_login_fail(username=username, source_ip=source_ip, user_agent=user_agent)
            return None

        password_hash = str(row.get("password_hash", "") or "")
        if not self.verify_password(password, password_hash):
            self._record_login_fail(username=username, source_ip=source_ip, user_agent=user_agent)
            return None

        self.query_service.admin_user_update_login_success(username)
        self.query_service.auth_event_insert(
            event_type="login_success",
            username=username,
            source_ip=source_ip,
            user_agent=user_agent,
        )
        self._clear_fail_count(username=username, source_ip=source_ip)
        return AuthUser(
            username=username,
            token_version=int(row.get("token_version", 0) or 0),
            must_change_password=bool(int(row.get("must_change_password", 0) or 0)),
        )

    def get_current_user(self, request: Request) -> Optional[AuthUser]:
        token = request.cookies.get(self.settings.auth_cookie_name, "")
        if not token:
            return None
        payload = self._decode_token(token)
        if payload is None:
            return None
        username = str(payload.get("username", "") or "")
        if not username:
            return None
        token_version = int(payload.get("token_version", 0) or 0)

        row = self.query_service.admin_user_get(username)
        if not row:
            return None
        if int(row.get("is_enabled", 0) or 0) != 1:
            return None
        current_version = int(row.get("token_version", 0) or 0)
        if token_version != current_version:
            return None

        return AuthUser(
            username=username,
            token_version=current_version,
            must_change_password=bool(int(row.get("must_change_password", 0) or 0)),
        )

    def change_password(
        self, username: str, old_password: str, new_password: str, source_ip: str, user_agent: str
    ) -> bool:
        row = self.query_service.admin_user_get(username)
        if not row:
            return False
        old_hash = str(row.get("password_hash", "") or "")
        if not self.verify_password(old_password, old_hash):
            self.query_service.auth_event_insert(
                event_type="password_change_fail",
                username=username,
                source_ip=source_ip,
                user_agent=user_agent,
            )
            return False

        new_hash = self.hash_password(new_password)
        self.query_service.admin_user_change_password(username=username, new_password_hash=new_hash)
        self.query_service.auth_event_insert(
            event_type="password_change",
            username=username,
            source_ip=source_ip,
            user_agent=user_agent,
        )
        return True

    def logout(self, username: str, source_ip: str, user_agent: str) -> None:
        self.query_service.admin_user_bump_token_version(username)
        self.query_service.auth_event_insert(
            event_type="logout",
            username=username,
            source_ip=source_ip,
            user_agent=user_agent,
        )

    def create_token(self, user: AuthUser) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user.username,
            "username": user.username,
            "token_version": int(user.token_version),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=self.settings.auth_jwt_exp_seconds)).timestamp()),
        }
        return jwt.encode(payload, self.settings.auth_jwt_secret, algorithm="HS256")

    @staticmethod
    def hash_password(password: str) -> str:
        raw = password.encode("utf-8")
        return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode("utf-8")

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
        except Exception:
            return False

    def _decode_token(self, token: str) -> Optional[Dict[str, Any]]:
        try:
            payload = jwt.decode(token, self.settings.auth_jwt_secret, algorithms=["HS256"])
            return payload if isinstance(payload, dict) else None
        except Exception:
            return None

    def _build_redis_client(self):
        try:
            if not self.settings.redis_enabled:
                return None
            return redis.Redis.from_url(self.settings.redis_url, decode_responses=True)
        except Exception:
            return None

    def _fail_key(self, username: str, source_ip: str) -> str:
        return f"audit:auth:fail:{source_ip}:{username.lower()}"

    def _is_rate_limited(self, username: str, source_ip: str) -> bool:
        if not self._redis:
            return False
        try:
            key = self._fail_key(username, source_ip)
            current = self._redis.get(key)
            count = int(current or 0)
            return count >= self.settings.auth_login_rate_limit
        except Exception:
            return False

    def _record_login_fail(self, username: str, source_ip: str, user_agent: str) -> None:
        self.query_service.auth_event_insert(
            event_type="login_fail",
            username=username,
            source_ip=source_ip,
            user_agent=user_agent,
        )
        if not self._redis:
            return
        try:
            key = self._fail_key(username, source_ip)
            value = int(self._redis.incr(key))
            if value <= 1:
                self._redis.expire(key, self.settings.auth_login_rate_window_seconds)
        except Exception:
            return

    def _clear_fail_count(self, username: str, source_ip: str) -> None:
        if not self._redis:
            return
        try:
            self._redis.delete(self._fail_key(username, source_ip))
        except Exception:
            return


def extract_client_ip(request: Request) -> str:
    cf_ip = (request.headers.get("CF-Connecting-IP") or "").strip()
    if cf_ip:
        return cf_ip
    xff = (request.headers.get("X-Forwarded-For") or "").strip()
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return "0.0.0.0"


def sanitize_user_agent(request: Request) -> str:
    ua = (request.headers.get("User-Agent") or "").strip()
    if len(ua) > 500:
        return ua[:500]
    return ua


def validate_password_strength(password: str) -> Optional[str]:
    if len(password) < 10:
        return "password must be at least 10 characters"
    if len(password) > 128:
        return "password must be <= 128 characters"
    categories = 0
    categories += 1 if any("a" <= c <= "z" for c in password) else 0
    categories += 1 if any("A" <= c <= "Z" for c in password) else 0
    categories += 1 if any(c.isdigit() for c in password) else 0
    categories += 1 if any(not c.isalnum() for c in password) else 0
    if categories < 3:
        return "password must contain at least 3 character categories"
    return None


def unix_now() -> int:
    return int(time.time())
