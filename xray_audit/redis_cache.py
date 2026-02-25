from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import redis

from .config import Settings
from .models import ParsedEvent


class RedisCache:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.enabled = settings.redis_enabled
        self.client = None

        if self.enabled:
            self.client = redis.Redis.from_url(settings.redis_url, decode_responses=True)

    def _minute_bucket_key(self, event_time: datetime) -> str:
        return f"audit:domains:{self.settings.node_id}:{event_time.strftime('%Y%m%d%H%M')}"

    def _active_users_key(self) -> str:
        return f"audit:active_users:{self.settings.node_id}"

    def _recent_events_key(self) -> str:
        return f"audit:recent_events:{self.settings.node_id}"

    def _health_key(self) -> str:
        return f"audit:health:{self.settings.node_id}"

    def publish_health(self, payload: Dict[str, Any]) -> None:
        if not self.client:
            return

        key = self._health_key()
        normalized: Dict[str, str] = {}
        for k, v in payload.items():
            if isinstance(v, datetime):
                normalized[k] = v.isoformat()
            elif v is None:
                normalized[k] = ""
            else:
                normalized[k] = str(v)

        with self.client.pipeline() as pipe:
            pipe.hset(key, mapping=normalized)
            pipe.expire(key, 300)
            pipe.execute()

    def get_health(self) -> Optional[Dict[str, Any]]:
        if not self.client:
            return None
        key = self._health_key()
        data = self.client.hgetall(key)
        return data or None

    def update_from_events(self, events: List[ParsedEvent]) -> None:
        if not self.client or not events:
            return

        active_key = self._active_users_key()
        recent_key = self._recent_events_key()
        now_ts = int(datetime.utcnow().timestamp())

        with self.client.pipeline() as pipe:
            for ev in events:
                compact = {
                    "event_time": ev.event_time.isoformat(),
                    "event_type": ev.event_type,
                    "raw": ev.raw_line,
                }

                if ev.access is not None:
                    a = ev.access
                    compact.update(
                        {
                            "email": a.user_email,
                            "dest_host": a.dest_host,
                            "dest_raw": a.dest_raw,
                            "status": a.status,
                            "confidence": a.confidence,
                        }
                    )

                    if a.dest_host:
                        pipe.zincrby(self._minute_bucket_key(ev.event_time), 1, a.dest_host)
                        pipe.expire(self._minute_bucket_key(ev.event_time), 900)

                    if a.user_email and a.user_email != "unknown":
                        pipe.zadd(active_key, {a.user_email: int(ev.event_time.timestamp())})

                if ev.dns is not None:
                    d = ev.dns
                    compact.update(
                        {
                            "dns_server": d.dns_server,
                            "domain": d.domain,
                            "dns_status": d.dns_status,
                        }
                    )

                pipe.lpush(recent_key, json.dumps(compact, ensure_ascii=True))

            pipe.ltrim(recent_key, 0, 999)
            pipe.expire(recent_key, 900)
            pipe.zremrangebyscore(active_key, 0, now_ts - 3600)
            pipe.expire(active_key, 7200)
            pipe.execute()

    def top_domains(self, minutes: int, limit: int) -> List[Dict[str, Any]]:
        if not self.client:
            return []

        now = datetime.utcnow().replace(second=0, microsecond=0)
        keys: List[str] = []
        for i in range(minutes):
            keys.append(f"audit:domains:{self.settings.node_id}:{(now - timedelta(minutes=i)).strftime('%Y%m%d%H%M')}")

        existing = [k for k in keys if self.client.exists(k)]
        if not existing:
            return []

        temp_key = f"audit:tmp:domains:{self.settings.node_id}:{int(datetime.utcnow().timestamp())}"
        with self.client.pipeline() as pipe:
            pipe.zunionstore(temp_key, existing)
            pipe.expire(temp_key, 10)
            pipe.zrevrange(temp_key, 0, max(0, limit - 1), withscores=True)
            pipe.delete(temp_key)
            _, _, values, _ = pipe.execute()

        out: List[Dict[str, Any]] = []
        for domain, score in values:
            out.append({"domain": domain, "hits": int(score)})
        return out

    def active_users(self, seconds: int, limit: int) -> List[Dict[str, Any]]:
        if not self.client:
            return []

        key = self._active_users_key()
        now_ts = int(datetime.utcnow().timestamp())
        rows = self.client.zrevrangebyscore(
            key,
            max=now_ts,
            min=max(0, now_ts - seconds),
            start=0,
            num=limit,
            withscores=True,
        )

        out: List[Dict[str, Any]] = []
        for email, score in rows:
            out.append({"user_email": email, "last_seen_unix": int(score)})
        return out
