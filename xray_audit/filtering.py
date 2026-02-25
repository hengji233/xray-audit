from __future__ import annotations

from .config import Settings
from .models import ParsedEvent


def should_drop_event(ev: ParsedEvent, settings: Settings) -> bool:
    if ev.access is None:
        return False

    a = ev.access

    if settings.drop_api_to_api and a.detour == "api -> api":
        return True

    if settings.exclude_detours and a.detour in settings.exclude_detours:
        return True

    if settings.drop_invalid_vless_probe:
        if (
            a.status == "rejected"
            and a.dest_raw == "proxy/vless/encoding:"
            and "invalid request version" in a.reason.lower()
        ):
            return True

    if settings.drop_loopback_traffic:
        src = a.src.lower()
        dst = a.dest_host.lower()
        if src.startswith("127.0.0.1") or src.startswith("[::1]") or src.startswith("::1"):
            return True
        if dst in {"127.0.0.1", "localhost", "::1", "[::1]"}:
            return True

    return False
