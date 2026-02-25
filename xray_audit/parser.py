from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from datetime import datetime
from typing import Optional, Tuple

from .models import AccessEvent, DNSEvent, ParsedEvent

_ACCESS_RE = re.compile(
    r"^from\s+(?P<src>\S+)\s+(?P<status>accepted|rejected)\s+(?P<dest>\S+)(?:\s+\[(?P<detour>[^\]]+)\])?(?P<tail>.*)$"
)
_DNS_RE = re.compile(
    r"^(?P<server>.+?)\s+(?P<status>got answer:|cache HIT:|cache OPTIMISTE:)\s+(?P<domain>\S+)\s+->\s+\[(?P<ips>[^\]]*)\](?P<tail>.*)$"
)


def _parse_timestamp_prefix(line: str) -> Tuple[Optional[datetime], str]:
    parts = line.strip().split(" ", 2)
    if len(parts) < 3:
        return None, ""
    stamp = f"{parts[0]} {parts[1]}"
    body = parts[2].strip()
    for fmt in ("%Y/%m/%d %H:%M:%S.%f", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(stamp, fmt), body
        except ValueError:
            continue
    return None, ""


def _parse_duration_ms(raw: str) -> Optional[int]:
    token = raw.strip().replace("\u00b5s", "us")
    if not token:
        return None
    m = re.match(r"^(\d+(?:\.\d+)?)(ns|us|ms|s|m|h)$", token)
    if not m:
        return None

    value = float(m.group(1))
    unit = m.group(2)
    if unit == "ns":
        return int(value / 1_000_000)
    if unit == "us":
        return int(value / 1_000)
    if unit == "ms":
        return int(value)
    if unit == "s":
        return int(value * 1000)
    if unit == "m":
        return int(value * 60_000)
    if unit == "h":
        return int(value * 3_600_000)
    return None


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _split_host_port(dest: str) -> Tuple[str, Optional[int]]:
    raw = dest.strip()
    for prefix in ("tcp:", "udp:"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
            break

    if raw.startswith("["):
        m = re.match(r"^\[(.+)\](?::(\d+))?$", raw)
        if m:
            host = m.group(1)
            port = int(m.group(2)) if m.group(2) else None
            return host, port

    if _is_ip(raw):
        return raw, None

    if raw.count(":") == 1:
        host, maybe_port = raw.rsplit(":", 1)
        if maybe_port.isdigit():
            return host, int(maybe_port)

    if raw.count(":") > 1:
        try:
            ipaddress.ip_address(raw)
            return raw, None
        except ValueError:
            host, maybe_port = raw.rsplit(":", 1)
            if maybe_port.isdigit():
                return host, int(maybe_port)

    return raw, None


def _parse_access(event_time: datetime, body: str) -> Optional[AccessEvent]:
    m = _ACCESS_RE.match(body)
    if not m:
        return None

    src = m.group("src")
    status = m.group("status")
    dest_raw = m.group("dest")
    detour = (m.group("detour") or "").strip()
    tail = (m.group("tail") or "").strip()

    email = "unknown"
    reason = ""
    email_match = re.search(r"(?:^|\s)email:\s*(\S+)\s*$", tail)
    if email_match:
        reason = tail[: email_match.start()].strip()
        email = email_match.group(1).strip() or "unknown"
    else:
        reason = tail

    dest_host, dest_port = _split_host_port(dest_raw)
    is_domain = bool(dest_host) and not _is_ip(dest_host)
    confidence = "high" if is_domain else "low"

    return AccessEvent(
        event_time=event_time,
        user_email=email,
        src=src,
        dest_raw=dest_raw,
        dest_host=dest_host,
        dest_port=dest_port,
        status=status,
        detour=detour,
        reason=reason,
        is_domain=is_domain,
        confidence=confidence,
    )


def _parse_dns(event_time: datetime, body: str) -> Optional[DNSEvent]:
    m = _DNS_RE.match(body)
    if not m:
        return None

    ips_raw = m.group("ips").strip()
    ips = [x.strip() for x in ips_raw.split(",") if x.strip()]
    tail = (m.group("tail") or "").strip()

    error_text = ""
    err_match = re.search(r"<([^>]*)>", tail)
    if err_match:
        error_text = err_match.group(1).strip()
        tail = tail.replace(err_match.group(0), "").strip()

    elapsed_ms = _parse_duration_ms(tail) if tail else None

    return DNSEvent(
        event_time=event_time,
        dns_server=m.group("server").strip(),
        domain=m.group("domain").strip(),
        ips_json=json.dumps(ips, ensure_ascii=True),
        dns_status=m.group("status").strip(),
        elapsed_ms=elapsed_ms,
        error_text=error_text,
    )


def parse_line(raw_line: str) -> Optional[ParsedEvent]:
    event_time, body = _parse_timestamp_prefix(raw_line)
    if event_time is None:
        return None

    normalized_raw = raw_line.rstrip("\r\n")
    raw_hash = hashlib.sha256(normalized_raw.encode("utf-8", errors="replace")).hexdigest()

    access = _parse_access(event_time, body)
    if access is not None:
        return ParsedEvent(
            event_time=event_time,
            event_type="access",
            raw_line=normalized_raw,
            raw_hash=raw_hash,
            access=access,
        )

    dns = _parse_dns(event_time, body)
    if dns is not None:
        return ParsedEvent(
            event_time=event_time,
            event_type="dns",
            raw_line=normalized_raw,
            raw_hash=raw_hash,
            dns=dns,
        )

    return ParsedEvent(
        event_time=event_time,
        event_type="unknown",
        raw_line=normalized_raw,
        raw_hash=raw_hash,
    )
