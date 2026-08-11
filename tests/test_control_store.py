from __future__ import annotations

from dataclasses import replace

from xray_audit.config import Settings
from xray_audit.control_store import ControlStore
from xray_audit.storage_manager import StorageManager


def _settings(tmp_path):
    return replace(
        Settings.from_env(),
        storage_backend="memory",
        control_db_path=str(tmp_path / "control.db"),
        control_key="",
        redis_enabled=False,
    )


def test_control_store_persists_auth_and_runtime_config(tmp_path) -> None:
    settings = _settings(tmp_path)
    store = ControlStore(settings)
    store.admin_user_create("admin", "hash", must_change_password=True)
    store.runtime_config_upsert({"AUDIT_BATCH_SIZE": 10}, changed_by="admin", source_ip="127.0.0.1")

    reopened = ControlStore(settings)
    assert reopened.admin_user_get("admin")["must_change_password"] == 1
    assert reopened.runtime_config_all()[0]["value_json"] == "10"
    assert reopened.runtime_config_history(1, 10)[0] == 1


def test_storage_credentials_are_encrypted_and_never_returned(tmp_path) -> None:
    settings = _settings(tmp_path)
    manager = StorageManager(settings)
    manager.save_pending(
        "mysql",
        {"mysql_host": "db.internal", "mysql_password": "top-secret-password"},
    )

    raw = (tmp_path / "control.db").read_bytes()
    assert b"top-secret-password" not in raw
    public = manager.public_config()
    assert public["config"]["mysql_password_configured"] is True
    assert "mysql_password" not in public["config"]
    assert public["pending_backend"] == "mysql"


def test_default_storage_manager_uses_non_persistent_memory(tmp_path) -> None:
    manager = StorageManager(_settings(tmp_path))
    status = manager.public_config()
    assert status["active_backend"] == "memory"
    assert status["memory"]["persistent"] is False
    assert status["memory"]["data_lost_on_restart"] is True


def test_collector_cursor_persists_without_persisting_audit_events(tmp_path) -> None:
    settings = _settings(tmp_path)
    manager = StorageManager(settings)
    manager.ingestor.save_state("/var/log/xray/access.log", 42, 12345)

    reopened = StorageManager(settings)
    assert reopened.ingestor.load_state("/var/log/xray/access.log") == (42, 12345)
    assert reopened.query.recent_events(seconds=3600, limit=10) == []
