from __future__ import annotations

import ipaddress
import json
from typing import Any, Dict, List

import httpx

from .config import Settings
from .runtime_config import RuntimeConfigManager
from .storage import AuditQueryService


class GeoIPService:
    def __init__(
        self,
        settings: Settings,
        query_service: AuditQueryService,
        runtime_config: RuntimeConfigManager | None = None,
    ) -> None:
        self.settings = settings
        self.query_service = query_service
        self.runtime_config = runtime_config

    def _runtime_bool(self, key: str, fallback: bool) -> bool:
        if self.runtime_config is None:
            return fallback
        return self.runtime_config.get_bool(key, fallback)

    def _runtime_int(self, key: str, fallback: int) -> int:
        if self.runtime_config is None:
            return fallback
        return self.runtime_config.get_int(key, fallback)

    def _runtime_float(self, key: str, fallback: float) -> float:
        if self.runtime_config is None:
            return fallback
        return self.runtime_config.get_float(key, fallback)

    def lookup_batch(self, ips: List[str]) -> Dict[str, Dict[str, Any]]:
        batch_limit = self._runtime_int("AUDIT_GEOIP_BATCH_LIMIT", self.settings.geoip_batch_limit)
        cache_ttl_hours = self._runtime_int("AUDIT_GEOIP_CACHE_TTL_HOURS", self.settings.geoip_cache_ttl_hours)
        geoip_enabled = self._runtime_bool("AUDIT_GEOIP_ENABLED", self.settings.geoip_enabled)
        geoip_timeout_seconds = self._runtime_float("AUDIT_GEOIP_TIMEOUT_SECONDS", self.settings.geoip_timeout_seconds)

        normalized: List[str] = []
        seen = set()
        for raw in ips:
            ip = normalize_ip(raw)
            if not ip or ip in seen:
                continue
            normalized.append(ip)
            seen.add(ip)
            if len(normalized) >= batch_limit:
                break

        if not normalized:
            return {}

        try:
            cached = self.query_service.geo_cache_get(normalized, ttl_hours=cache_ttl_hours)
        except Exception:
            cached = {}
        missing = [ip for ip in normalized if ip not in cached]

        fetched_rows: List[Dict[str, Any]] = []
        if missing and geoip_enabled:
            with httpx.Client(timeout=geoip_timeout_seconds) as client:
                for ip in missing:
                    fetched_rows.append(self._lookup_one(client, ip))

            try:
                self.query_service.geo_cache_upsert(fetched_rows)
            except Exception:
                pass

        fetched_map = {str(row["ip"]): row for row in fetched_rows}
        out: Dict[str, Dict[str, Any]] = {}
        for ip in normalized:
            row = cached.get(ip) or fetched_map.get(ip)
            if not row:
                continue
            out[ip] = _project_row(ip, row)
        return out

    def _lookup_one(self, client: httpx.Client, ip: str) -> Dict[str, Any]:
        try:
            resp = client.get(
                self.settings.geoip_provider_url,
                params={"ip": ip, "json": "true"},
                headers={"User-Agent": "xray-audit/0.1"},
            )
            resp.raise_for_status()
            payload = _parse_provider_json(resp.content)
            err = str(payload.get("err", "") or "").strip()
            has_location = any(str(payload.get(key, "") or "").strip() for key in ("pro", "city", "addr"))
            status = "ok" if has_location or not err else "error"

            return {
                "ip": ip,
                "country": "",
                "region": str(payload.get("pro", "") or "").strip(),
                "city": str(payload.get("city", "") or "").strip(),
                "isp": "",
                "addr": str(payload.get("addr", "") or "").strip(),
                "status": status,
                "source": "pconline",
                "raw": payload,
            }
        except Exception as err:
            return {
                "ip": ip,
                "country": "",
                "region": "",
                "city": "",
                "isp": "",
                "addr": "",
                "status": "error",
                "source": "pconline",
                "raw": {"error": str(err)},
            }


def normalize_ip(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""

    if value.startswith("[") and "]" in value:
        value = value[1 : value.index("]")]
    elif value.count(":") == 1:
        host, maybe_port = value.rsplit(":", 1)
        if maybe_port.isdigit():
            value = host

    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return ""

    if ip.is_loopback or ip.is_private or ip.is_multicast or ip.is_link_local or ip.is_reserved:
        return ""
    return str(ip)


def _parse_provider_json(content: bytes) -> Dict[str, Any]:
    attempts: List[str] = []
    for encoding in ("utf-8", "gb18030", "gbk"):
        try:
            txt = content.decode(encoding, errors="strict").strip()
            payload = _strip_callback_wrapper(txt)
            return json.loads(payload)
        except Exception as err:
            attempts.append(f"{encoding}:{err}")
            continue
    raise ValueError("failed to decode provider payload: " + "; ".join(attempts))


def _strip_callback_wrapper(raw: str) -> str:
    txt = raw.strip()
    if txt.startswith("{") and txt.endswith("}"):
        return txt
    # Some endpoints can return callback(...) wrapper.
    lpos = txt.find("(")
    rpos = txt.rfind(")")
    if lpos >= 0 and rpos > lpos:
        inner = txt[lpos + 1 : rpos].strip()
        if inner.startswith("{") and inner.endswith("}"):
            return inner
    return txt


def _project_row(ip: str, row: Dict[str, Any]) -> Dict[str, Any]:
    region = str(row.get("region", "") or "").strip()
    city = str(row.get("city", "") or "").strip()
    addr = str(row.get("addr", "") or "").strip()
    status = str(row.get("status", "") or "ok")
    if status != "ok" and (region or city or addr):
        status = "ok"

    pieces = [region, city, addr]
    label = " / ".join([x for x in pieces if x])
    if not label:
        label = "unknown" if status == "ok" else "lookup_failed"

    return {
        "ip": ip,
        "country": str(row.get("country", "") or ""),
        "region": region,
        "city": city,
        "isp": str(row.get("isp", "") or ""),
        "addr": addr,
        "status": status,
        "source": str(row.get("source", "pconline")),
        "label": label,
        "updated_at": row.get("updated_at"),
    }
