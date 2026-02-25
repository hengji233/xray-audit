from __future__ import annotations

import hashlib
import ipaddress
import re
from datetime import datetime
from typing import Optional, Tuple

from .models import ParsedErrorEvent

_LINE_RE = re.compile(
    r"^(?P<date>\d{4}/\d{2}/\d{2})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)\s+"
    r"\[(?P<level>[A-Za-z]+)\]\s+"
    r"(?:(?:\[(?P<sid>\d+)\])\s+)?"
    r"(?:(?P<component>[A-Za-z0-9_./-]+):\s+)?"
    r"(?P<message>.*)$"
)
_SRC_RE = re.compile(r"\bfrom\s+(?P<src>\S+)")
_DEST_RE = re.compile(r"\bfor\s+(?P<dest>(?:tcp|udp):\S+)")
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_DIGITS_RE = re.compile(r"\b\d+\b")


def parse_error_line(raw_line: str) -> Optional[ParsedErrorEvent]:
    normalized = raw_line.rstrip("\r\n")
    match = _LINE_RE.match(normalized.strip())
    if not match:
        return None

    dt_raw = f"{match.group('date')} {match.group('time')}"
    event_time = _parse_datetime(dt_raw)
    if event_time is None:
        return None

    level = _normalize_level(match.group("level") or "unknown")
    session_raw = (match.group("sid") or "").strip()
    session_id = int(session_raw) if session_raw.isdigit() else None
    component = (match.group("component") or "").strip()
    message = (match.group("message") or "").strip()

    src = ""
    src_m = _SRC_RE.search(message)
    if src_m:
        src = src_m.group("src").strip()

    dest_raw = ""
    dest_host = ""
    dest_port: Optional[int] = None
    dest_m = _DEST_RE.search(message)
    if dest_m:
        dest_raw = dest_m.group("dest").strip()
        dest_host, dest_port = _split_host_port(dest_raw)

    category = _classify(component=component, message=message, level=level)
    is_noise = category in {"probe_invalid_vless", "api_loopback", "scan_noise"}

    signature = _normalize_message_signature(component=component, message=message)
    signature_hash = hashlib.sha256(signature.encode("utf-8", errors="replace")).hexdigest()
    raw_hash = hashlib.sha256(normalized.encode("utf-8", errors="replace")).hexdigest()

    return ParsedErrorEvent(
        event_time=event_time,
        level=level,
        session_id=session_id,
        component=component,
        message=message,
        src=src,
        dest_raw=dest_raw,
        dest_host=dest_host,
        dest_port=dest_port,
        category=category,
        signature_hash=signature_hash,
        is_noise=is_noise,
        raw_line=normalized,
        raw_hash=raw_hash,
    )


def level_rank(level: str) -> int:
    mapping = {
        "debug": 10,
        "info": 20,
        "warning": 30,
        "error": 40,
        "unknown": 0,
    }
    return mapping.get((level or "").strip().lower(), 0)


def _normalize_level(raw: str) -> str:
    value = (raw or "").strip().lower()
    if value in {"debug", "info", "warning", "error"}:
        return value
    return "unknown"


def _parse_datetime(raw: str) -> Optional[datetime]:
    for fmt in ("%Y/%m/%d %H:%M:%S.%f", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _classify(component: str, message: str, level: str) -> str:
    c = component.lower()
    m = message.lower()

    if ("proxy/vless/encoding" in c or "proxy/vless/encoding" in m) and "invalid request version" in m:
        return "probe_invalid_vless"
    if "127.0.0.1" in m and "detour [api]" in m:
        return "api_loopback"
    if "dns" in c or "dns" in m:
        if "timeout" in m or "failed" in m or "error" in m:
            return "dns_error"
        return "dns_info"
    if "timeout" in m or "deadline exceeded" in m or "i/o timeout" in m:
        return "network_timeout"
    if "refused" in m or "connection reset" in m:
        return "network_refused"
    if "invalid user" in m or "failed to find user" in m or "unauthorized" in m:
        return "auth_error"
    if "dispatch" in c or "dispatcher" in c:
        return "routing"
    if level == "error":
        return "runtime_error"
    if level == "warning":
        return "runtime_warning"
    if level == "debug":
        return "debug_trace"
    return "runtime_info"


def _normalize_message_signature(component: str, message: str) -> str:
    norm = _IPV4_RE.sub("<ip>", message)
    norm = _DIGITS_RE.sub("<num>", norm)
    return f"{component.lower()}|{norm.strip().lower()}"


def _split_host_port(dest: str) -> Tuple[str, Optional[int]]:
    raw = dest.strip()
    for prefix in ("tcp:", "udp:"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
            break

    if raw.startswith("["):
        m = re.match(r"^\[(.+)\](?::(\d+))?$", raw)
        if m:
            return m.group(1), int(m.group(2)) if m.group(2) else None

    if raw.count(":") == 1:
        host, maybe_port = raw.rsplit(":", 1)
        if maybe_port.isdigit():
            return host, int(maybe_port)

    if _is_ip(raw):
        return raw, None
    return raw, None


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False
