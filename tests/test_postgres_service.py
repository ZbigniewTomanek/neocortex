import asyncpg
import pytest

from neocortex.config import PostgresConfig
from neocortex.postgres_service import PostgresService


@pytest.mark.asyncio
async def test_health_check(pg_service):
    health = await pg_service.health_check()
    assert health["status"] == "healthy"
    assert "vector" in health["extensions"]
    assert "pg_trgm" in health["extensions"]
    assert health["database"] == "neocortex"


@pytest.mark.asyncio
async def test_fetchval(pg_service):
    result = await pg_service.fetchval("SELECT 1 + 1")
    assert result == 2


async def test_connect_disables_statement_cache(monkeypatch):
    """Pooled connections switch search_path per graph schema, so cached plans must be off.

    With asyncpg's default statement cache a plan prepared under one graph schema is reused
    under another and the server raises InvalidCachedStatementError ("cached plan must not
    change result type"), which cannot be auto-retried inside a transaction.
    """
    captured: dict[str, object] = {}

    async def fake_create_pool(*args, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(asyncpg, "create_pool", fake_create_pool)

    service = PostgresService(PostgresConfig())
    await service.connect()

    assert captured["statement_cache_size"] == 0
