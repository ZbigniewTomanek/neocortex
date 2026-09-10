import asyncpg
from loguru import logger

from neocortex.config import PostgresConfig


class PostgresService:
    """Manages PostgreSQL connections, health checks, and migrations."""

    def __init__(self, config: PostgresConfig | None = None):
        self._config = config or PostgresConfig()
        self._pool: asyncpg.Pool | None = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("PostgresService not started. Call connect() first.")
        return self._pool

    async def connect(self) -> None:
        """Create connection pool."""
        logger.info("Connecting to PostgreSQL at {}:{}", self._config.host, self._config.port)
        # statement_cache_size=0: scoped connections switch `search_path` per transaction on
        # pooled connections, so a plan cached under one graph schema would be invalid under another
        # ("cached plan must not change result type" — asyncpg cannot auto-retry inside a transaction).
        self._pool = await asyncpg.create_pool(
            dsn=self._config.dsn,
            min_size=self._config.min_pool_size,
            max_size=self._config.max_pool_size,
            statement_cache_size=0,
        )
        logger.info("Connection pool created (min={}, max={})", self._config.min_pool_size, self._config.max_pool_size)

    async def disconnect(self) -> None:
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("Connection pool closed")

    async def health_check(self) -> dict:
        """Check database connectivity and return status info."""
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT version() as version, current_database() as database, now() as server_time"
                )
                extensions = await conn.fetch(
                    "SELECT extname FROM pg_extension WHERE extname IN ('vector', 'pg_trgm') ORDER BY extname"
                )
                return {
                    "status": "healthy",
                    "version": row["version"],
                    "database": row["database"],
                    "server_time": str(row["server_time"]),
                    "extensions": [r["extname"] for r in extensions],
                    "pool_size": self.pool.get_size(),
                    "pool_free": self.pool.get_idle_size(),
                }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    async def execute(self, query: str, *args) -> str:
        """Execute a query (INSERT, UPDATE, DELETE). Returns status string."""
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def execute_in_schema(self, schema_name: str, query: str, *args) -> str:
        """Execute a write query against a specific graph schema."""
        from neocortex.db.scoped import schema_scoped_connection

        async with schema_scoped_connection(self.pool, schema_name) as conn:
            return await conn.execute(query, *args)

    async def fetch(self, query: str, *args) -> list[asyncpg.Record]:
        """Execute a query and return all rows."""
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args) -> asyncpg.Record | None:
        """Execute a query and return a single row."""
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args) -> object:
        """Execute a query and return a single value."""
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
