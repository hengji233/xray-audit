from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class AccessEvent:
    event_time: datetime
    user_email: str
    src: str
    dest_raw: str
    dest_host: str
    dest_port: Optional[int]
    status: str
    detour: str
    reason: str
    is_domain: bool
    confidence: str


@dataclass
class DNSEvent:
    event_time: datetime
    dns_server: str
    domain: str
    ips_json: str
    dns_status: str
    elapsed_ms: Optional[int]
    error_text: str


@dataclass
class ParsedEvent:
    event_time: datetime
    event_type: str
    raw_line: str
    raw_hash: str
    access: Optional[AccessEvent] = None
    dns: Optional[DNSEvent] = None


@dataclass
class ParsedErrorEvent:
    event_time: datetime
    level: str
    session_id: Optional[int]
    component: str
    message: str
    src: str
    dest_raw: str
    dest_host: str
    dest_port: Optional[int]
    category: str
    signature_hash: str
    is_noise: bool
    raw_line: str
    raw_hash: str
