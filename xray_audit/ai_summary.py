from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import httpx

from .config import Settings
from .runtime_config import RuntimeConfigManager
from .storage import AuditQueryService

_STATE_KEY = "ai_error_summary_last_ts"


class ErrorSummaryWorker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.query = AuditQueryService(settings)
        self.runtime = RuntimeConfigManager(settings, self.query)

    def run_once(self) -> bool:
        now = datetime.utcnow()
        window_minutes = max(
            1,
            self.runtime.get_int("AUDIT_AI_SUMMARY_WINDOW_MINUTES", self.settings.ai_summary_window_minutes),
        )
        max_items = max(20, self.runtime.get_int("AUDIT_AI_SUMMARY_MAX_ITEMS", self.settings.ai_summary_max_items))
        dt_from = self._load_last_ts() or (now - timedelta(minutes=window_minutes))
        dt_to = now

        payload = self.query.error_summary_payload(
            dt_from=dt_from,
            dt_to=dt_to,
            max_items=max_items,
        )
        if int(payload.get("total", 0)) <= 0:
            self._save_last_ts(dt_to)
            return False

        summary_text = self._call_ai(payload)
        if not summary_text:
            return False

        self._send_telegram(summary_text, payload)
        self._save_last_ts(dt_to)
        return True

    def _load_last_ts(self) -> Optional[datetime]:
        raw = self.query.job_state_get(_STATE_KEY)
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    def _save_last_ts(self, ts: datetime) -> None:
        self.query.job_state_set(_STATE_KEY, ts.isoformat())

    def _call_ai(self, payload: Dict[str, Any]) -> str:
        base = self.settings.ai_api_base_url.strip().rstrip("/")
        model = self.settings.ai_api_model.strip()
        if not base or not model:
            raise RuntimeError("AUDIT_AI_API_BASE_URL or AUDIT_AI_API_MODEL is not configured")

        url = f"{base}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.settings.ai_api_key:
            headers["Authorization"] = f"Bearer {self.settings.ai_api_key}"

        system_prompt = (
            "You are an SRE security analyst. Summarize proxy error logs in concise Chinese. "
            "Output sections: 总览, 风险点, 可能原因, 建议动作. "
            "Use bullet lists and include counts."
        )
        user_prompt = _build_user_prompt(payload)
        body = {
            "model": model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        with httpx.Client(timeout=self.settings.ai_api_timeout_seconds) as client:
            resp = client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("AI response has no choices")
        message = choices[0].get("message") or {}
        content = str(message.get("content", "")).strip()
        if not content:
            raise RuntimeError("AI response content is empty")
        return content

    def _send_telegram(self, text: str, payload: Dict[str, Any]) -> None:
        token = self.settings.tg_bot_token.strip()
        chat_id = self.settings.tg_chat_id.strip()
        if not token or not chat_id:
            raise RuntimeError("AUDIT_TG_BOT_TOKEN or AUDIT_TG_CHAT_ID is not configured")

        header = (
            f"\U0001F6A8 Xray Error Summary\n"
            f"Window: {payload['from']} ~ {payload['to']}\n"
            f"Total: {payload['total']}\n\n"
        )
        msg = header + text
        if len(msg) > 3800:
            msg = msg[:3800] + "\n...(truncated)"

        api_url = f"https://api.telegram.org/bot{token}/sendMessage"
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                api_url,
                data={
                    "chat_id": chat_id,
                    "text": msg,
                    "disable_web_page_preview": "true",
                },
            )
            resp.raise_for_status()


def _build_user_prompt(payload: Dict[str, Any]) -> str:
    serializable = {
        "from": str(payload.get("from")),
        "to": str(payload.get("to")),
        "total": payload.get("total", 0),
        "level_category": payload.get("level_category", []),
        "top_signatures": payload.get("top_signatures", []),
        "recent_examples": payload.get("recent_examples", []),
    }
    return "请基于以下JSON做运维总结并给出可执行建议：\n" + json.dumps(serializable, ensure_ascii=False)


def run_forever() -> None:
    settings = Settings.from_env()
    worker = ErrorSummaryWorker(settings)
    while True:
        enabled = worker.runtime.get_bool("AUDIT_AI_SUMMARY_ENABLED", settings.ai_summary_enabled)
        try:
            if enabled:
                worker.run_once()
        except Exception as err:
            print(f"[ai-summary] error: {err}")
        interval = max(
            10,
            worker.runtime.get_int("AUDIT_AI_SUMMARY_INTERVAL_SECONDS", settings.ai_summary_interval_seconds),
        )
        time.sleep(interval)


def main() -> None:
    run_forever()
