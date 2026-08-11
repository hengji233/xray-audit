from __future__ import annotations

from typing import Protocol

from .config import Settings
from .d1_storage import D1Ingestor, D1QueryService
from .memory_storage import MemoryStorage
from .storage import AuditQueryService, MySQLIngestor

_memory_instances: dict[int, MemoryStorage] = {}


def _memory_storage(settings: Settings) -> MemoryStorage:
    return _memory_instances.setdefault(id(settings), MemoryStorage(settings))


class Ingestor(Protocol):
    def close(self) -> None: ...


class QueryService(Protocol):
    pass


def create_ingestor(settings: Settings) -> MySQLIngestor | D1Ingestor | MemoryStorage:
    backend = settings.storage_backend.strip().lower()
    if backend == "mysql":
        return MySQLIngestor(settings)
    if backend == "d1":
        return D1Ingestor(settings)
    if backend == "memory":
        return _memory_storage(settings)
    raise ValueError(f"unsupported storage backend: {settings.storage_backend}")


def create_query_service(settings: Settings) -> AuditQueryService | D1QueryService | MemoryStorage:
    backend = settings.storage_backend.strip().lower()
    if backend == "mysql":
        return AuditQueryService(settings)
    if backend == "d1":
        return D1QueryService(settings)
    if backend == "memory":
        return _memory_storage(settings)
    raise ValueError(f"unsupported storage backend: {settings.storage_backend}")


def create_storage_pair(settings: Settings):
    if settings.storage_backend.strip().lower() == "memory":
        storage = MemoryStorage(settings)
        return storage, storage
    return create_ingestor(settings), create_query_service(settings)
