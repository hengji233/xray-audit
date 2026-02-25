#!/usr/bin/env python3
from __future__ import annotations

import os
import sys


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


if not _env_bool("AUDIT_REDIS_ENABLED", True):
    sys.exit(0)

try:
    import redis
except Exception:
    sys.exit(1)

try:
    node_id = os.getenv("AUDIT_NODE_ID", "node-1")
    redis_url = os.getenv("AUDIT_REDIS_URL", "redis://127.0.0.1:6379/0")
    key = f"audit:health:{node_id}"

    client = redis.Redis.from_url(redis_url, decode_responses=True)
    payload = client.hgetall(key)
    if not payload:
        sys.exit(1)

    # A collector that is running should at least publish one of these fields.
    if payload.get("started_at") or payload.get("last_flush_time") or payload.get("lines_read_total"):
        sys.exit(0)
except Exception:
    pass

sys.exit(1)
