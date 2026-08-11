from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken

from .config import Settings


class ControlStore:
    """Persistent local control plane. Audit events never enter this database."""

    def __init__(self, settings: Settings) -> None:
        self.path = settings.control_db_path
        self._lock = threading.RLock()
        if self.path != ":memory:":
            path = Path(self.path)
            path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._fernet = Fernet(self._load_key(settings))
        self._init_schema()

    def _load_key(self, settings: Settings) -> bytes:
        if settings.control_key:
            return settings.control_key.encode("ascii")
        if self.path == ":memory:":
            return Fernet.generate_key()
        key_path = Path(self.path).with_suffix(".key")
        if key_path.exists():
            return key_path.read_bytes().strip()
        key = Fernet.generate_key()
        fd = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(key + b"\n")
        return key

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS admin_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL, token_version INTEGER NOT NULL DEFAULT 0,
                    is_enabled INTEGER NOT NULL DEFAULT 1, must_change_password INTEGER NOT NULL DEFAULT 0,
                    last_login_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auth_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, username TEXT NOT NULL,
                    source_ip TEXT NOT NULL, user_agent TEXT NOT NULL, event_time TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS collector_state (
                    file_path TEXT PRIMARY KEY, inode INTEGER, last_offset INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runtime_config (
                    config_key TEXT PRIMARY KEY, value_json TEXT NOT NULL, value_type TEXT NOT NULL,
                    scope TEXT NOT NULL, updated_by TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runtime_config_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, config_key TEXT NOT NULL,
                    old_value_json TEXT, new_value_json TEXT NOT NULL, changed_by TEXT NOT NULL,
                    source_ip TEXT NOT NULL, changed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS storage_config (
                    id INTEGER PRIMARY KEY CHECK (id = 1), active_backend TEXT NOT NULL,
                    pending_backend TEXT, config_json TEXT NOT NULL, secrets_json TEXT NOT NULL,
                    status TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _row(row: sqlite3.Row | None) -> Optional[Dict[str, Any]]:
        return dict(row) if row is not None else None

    def admin_user_count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0])

    def admin_user_get(self, username: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._row(self._conn.execute("SELECT * FROM admin_users WHERE username=?", (username,)).fetchone())

    def admin_user_create(self, username: str, password_hash: str, must_change_password: bool = False) -> None:
        now = self._now()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO admin_users(username,password_hash,must_change_password,created_at,updated_at) VALUES(?,?,?,?,?)",
                (username, password_hash, int(must_change_password), now, now),
            )

    def admin_user_update_login_success(self, username: str) -> None:
        now = self._now()
        with self._lock, self._conn:
            self._conn.execute("UPDATE admin_users SET last_login_at=?,updated_at=? WHERE username=?", (now, now, username))

    def admin_user_bump_token_version(self, username: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE admin_users SET token_version=token_version+1,updated_at=? WHERE username=?",
                (self._now(), username),
            )

    def admin_user_change_password(self, username: str, new_password_hash: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE admin_users SET password_hash=?,token_version=token_version+1,must_change_password=0,updated_at=? WHERE username=?",
                (new_password_hash, self._now(), username),
            )

    def auth_event_insert(self, event_type: str, username: str, source_ip: str, user_agent: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO auth_events(event_type,username,source_ip,user_agent,event_time) VALUES(?,?,?,?,?)",
                (event_type, username, source_ip, user_agent, self._now()),
            )

    def runtime_config_all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._conn.execute("SELECT * FROM runtime_config ORDER BY config_key")]

    def runtime_config_upsert(self, values: Dict[str, Any], changed_by: str, source_ip: str) -> None:
        with self._lock, self._conn:
            for key, value in values.items():
                old = self._conn.execute("SELECT value_json FROM runtime_config WHERE config_key=?", (key,)).fetchone()
                old_json = old[0] if old else None
                new_json = json.dumps(value, ensure_ascii=False)
                now = self._now()
                self._conn.execute(
                    """INSERT INTO runtime_config(config_key,value_json,value_type,scope,updated_by,updated_at)
                    VALUES(?,?,?,?,?,?) ON CONFLICT(config_key) DO UPDATE SET value_json=excluded.value_json,
                    value_type=excluded.value_type,updated_by=excluded.updated_by,updated_at=excluded.updated_at""",
                    (key, new_json, type(value).__name__, "runtime", changed_by, now),
                )
                self._conn.execute(
                    "INSERT INTO runtime_config_history(config_key,old_value_json,new_value_json,changed_by,source_ip,changed_at) VALUES(?,?,?,?,?,?)",
                    (key, old_json, new_json, changed_by, source_ip, now),
                )

    def runtime_config_history(self, page: int, page_size: int) -> Tuple[int, List[Dict[str, Any]]]:
        offset = (page - 1) * page_size
        with self._lock:
            total = int(self._conn.execute("SELECT COUNT(*) FROM runtime_config_history").fetchone()[0])
            rows = self._conn.execute(
                "SELECT * FROM runtime_config_history ORDER BY id DESC LIMIT ? OFFSET ?", (page_size, offset)
            ).fetchall()
            return total, [dict(row) for row in rows]

    def load_state(self, file_path: str) -> Tuple[Optional[int], int]:
        row = self.collector_state(file_path)
        if row is None:
            return None, 0
        inode = row.get("inode")
        return (None if inode is None else int(inode)), int(row.get("last_offset", 0))

    def save_state(self, file_path: str, inode: Optional[int], offset: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO collector_state(file_path,inode,last_offset,updated_at) VALUES(?,?,?,?)
                ON CONFLICT(file_path) DO UPDATE SET inode=excluded.inode,
                last_offset=excluded.last_offset,updated_at=excluded.updated_at""",
                (file_path, inode, int(offset), self._now()),
            )

    def collector_state(self, file_path: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._row(
                self._conn.execute("SELECT * FROM collector_state WHERE file_path=?", (file_path,)).fetchone()
            )

    def save_storage_config(self, backend: str, config: Dict[str, Any], secrets: Dict[str, str]) -> None:
        current = self.load_storage_config()
        merged_config = {**current["config"], **config}
        merged_secrets = {**current["secrets"], **{key: value for key, value in secrets.items() if value}}
        encrypted = {
            key: self._fernet.encrypt(value.encode("utf-8")).decode("ascii") for key, value in merged_secrets.items()
        }
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO storage_config(id,active_backend,pending_backend,config_json,secrets_json,status,updated_at)
                VALUES(1,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET pending_backend=excluded.pending_backend,
                config_json=excluded.config_json,secrets_json=excluded.secrets_json,status=excluded.status,updated_at=excluded.updated_at""",
                (
                    current["active_backend"], backend, json.dumps(merged_config), json.dumps(encrypted),
                    "pending", self._now(),
                ),
            )

    def load_storage_config(self) -> Dict[str, Any]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM storage_config WHERE id=1").fetchone()
        if row is None:
            return {"exists": False, "active_backend": "memory", "pending_backend": None, "status": "active", "config": {}, "secrets": {}}
        encrypted = json.loads(row["secrets_json"] or "{}")
        secrets: Dict[str, str] = {}
        for key, value in encrypted.items():
            try:
                secrets[key] = self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
            except InvalidToken:
                raise ValueError("stored credentials cannot be decrypted with the configured control key")
        return {
            "exists": True,
            "active_backend": row["active_backend"], "pending_backend": row["pending_backend"],
            "status": row["status"], "config": json.loads(row["config_json"] or "{}"), "secrets": secrets,
        }

    def mark_storage_active(self, backend: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE storage_config SET active_backend=?,pending_backend=NULL,status='active',updated_at=? WHERE id=1",
                (backend, self._now()),
            )
