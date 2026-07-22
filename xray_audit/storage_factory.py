from __future__ import annotations

from typing import Protocol

from .config import Settings
from .d1_storage import D1Ingestor, D1QueryService
from .storage import AuditQueryService, MySQLIngestor


class Ingestor(Protocol):
    def close(self) -> None: ...


class QueryService(Protocol):
    pass


def create_ingestor(settings: Settings) -> MySQLIngestor | D1Ingestor:
    backend = settings.storage_backend.strip().lower()
    if backend == "mysql":
        return MySQLIngestor(settings)
    if backend == "d1":
        return D1Ingestor(settings)
    raise ValueError(f"unsupported storage backend: {settings.storage_backend}")


def create_query_service(settings: Settings) -> AuditQueryService | D1QueryService:
    backend = settings.storage_backend.strip().lower()
    if backend == "mysql":
        return AuditQueryService(settings)
    if backend == "d1":
        return D1QueryService(settings)
    raise ValueError(f"unsupported storage backend: {settings.storage_backend}")
