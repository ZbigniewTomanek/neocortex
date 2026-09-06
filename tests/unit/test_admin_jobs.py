"""Tests for the Admin Job Monitoring REST API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from neocortex.mcp_settings import MCPSettings
from neocortex.permissions.memory_service import InMemoryPermissionService

BOOTSTRAP_ADMIN = "admin"


@pytest.fixture
def settings() -> MCPSettings:
    return MCPSettings(mock_db=True, extraction_enabled=False, auth_mode="dev_token")


@pytest.fixture
def permissions() -> InMemoryPermissionService:
    svc = InMemoryPermissionService(bootstrap_admin_id=BOOTSTRAP_ADMIN)
    return svc


def _make_job_row(
    job_id: int = 1,
    task_name: str = "extract_episode",
    status: str = "succeeded",
    queue_name: str = "extraction",
    agent_id: str = "alice",
    attempts: int = 1,
) -> dict:
    """Create a dict mimicking an asyncpg Record for a procrastinate_jobs row."""
    now = datetime.now(UTC)
    return {
        "id": job_id,
        "task_name": task_name,
        "status": status,
        "queue_name": queue_name,
        "args": {"agent_id": agent_id, "episode_id": "ep-1"},
        "attempts": attempts,
        "scheduled_at": now,
        "started_at": now,
        "created_at": now,
        "finished_at": now,
    }


def _make_summary_row(
    todo: int = 0,
    doing: int = 0,
    succeeded: int = 2,
    failed: int = 1,
    cancelled: int = 0,
) -> dict:
    return {
        "todo": todo,
        "doing": doing,
        "succeeded": succeeded,
        "failed": failed,
        "cancelled": cancelled,
        "total": todo + doing + succeeded + failed + cancelled,
    }


class FakeRecord(dict):
    """Dict subclass that supports both key and attribute access like asyncpg.Record."""

    def __getitem__(self, key):
        return super().__getitem__(key)


def _record(d: dict) -> FakeRecord:
    return FakeRecord(d)


class _FakeTransaction:
    """Mimics asyncpg transaction context manager."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _FakeConnection:
    """Mimics an asyncpg connection with transaction support."""

    def __init__(self):
        self.fetchrow = AsyncMock(return_value=None)
        self.execute = AsyncMock()

    def transaction(self):
        return _FakeTransaction()


class _FakeAcquire:
    """Mimics pool.acquire() async context manager."""

    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        return False


@pytest.fixture
def mock_pool():
    pool = AsyncMock()
    pool.fetch = AsyncMock(return_value=[])
    pool.fetchrow = AsyncMock(return_value=None)
    pool.execute = AsyncMock()
    # Support pool.acquire() for transactional cancel — use MagicMock
    # so it returns the context manager directly (not wrapped in a coroutine)
    conn = _FakeConnection()
    pool.acquire = MagicMock(return_value=_FakeAcquire(conn))
    pool._mock_conn = conn  # expose for test assertions
    return pool


@pytest.fixture
def app(settings: MCPSettings, permissions: InMemoryPermissionService, mock_pool):
    from fastapi import FastAPI

    from neocortex.admin.routes import router as admin_router
    from neocortex.ingestion.routes import router as ingest_router

    app = FastAPI()
    app.state.settings = settings
    app.state.permissions = permissions
    app.state.schema_mgr = None
    app.state.pool = mock_pool
    app.state.services_ctx = {}
    app.state.token_map = {
        "admin-token": BOOTSTRAP_ADMIN,
        "alice-token": "alice",
        "bob-token": "bob",
    }

    app.include_router(ingest_router)
    app.include_router(admin_router)
    return app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


ADMIN_HEADERS = {"Authorization": "Bearer admin-token"}
ALICE_HEADERS = {"Authorization": "Bearer alice-token"}
BOB_HEADERS = {"Authorization": "Bearer bob-token"}


# ---------------------------------------------------------------------------
# Job list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_jobs_returns_empty(client: AsyncClient, mock_pool) -> None:
    mock_pool.fetch.return_value = []
    resp = await client.get("/admin/jobs", headers=ALICE_HEADERS)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_jobs_returns_records(client: AsyncClient, mock_pool) -> None:
    mock_pool.fetch.return_value = [_record(_make_job_row(job_id=1)), _record(_make_job_row(job_id=2))]
    resp = await client.get("/admin/jobs", headers=ALICE_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["id"] == 1
    assert data[0]["task_name"] == "extract_episode"


@pytest.mark.asyncio
async def test_list_jobs_filters_by_status(client: AsyncClient, mock_pool) -> None:
    mock_pool.fetch.return_value = [_record(_make_job_row(status="failed"))]
    resp = await client.get("/admin/jobs", params={"status": "failed"}, headers=ALICE_HEADERS)
    assert resp.status_code == 200
    # Verify the SQL was called with the status filter
    call_args = mock_pool.fetch.call_args
    assert call_args[0][1] == "alice"  # effective_agent_id
    assert call_args[0][2] == "failed"  # status


@pytest.mark.asyncio
async def test_list_jobs_non_admin_cannot_use_all_agents(client: AsyncClient, mock_pool) -> None:
    resp = await client.get("/admin/jobs", params={"all_agents": "true"}, headers=ALICE_HEADERS)
    assert resp.status_code == 403
    assert "Admin required" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_list_jobs_admin_can_use_all_agents(
    client: AsyncClient, permissions: InMemoryPermissionService, mock_pool
) -> None:
    await permissions.ensure_admin(BOOTSTRAP_ADMIN)
    mock_pool.fetch.return_value = []
    resp = await client.get("/admin/jobs", params={"all_agents": "true"}, headers=ADMIN_HEADERS)
    assert resp.status_code == 200
    # effective_agent_id should be None (no agent filter)
    call_args = mock_pool.fetch.call_args
    assert call_args[0][1] is None


# ---------------------------------------------------------------------------
# Job summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_job_summary(client: AsyncClient, mock_pool) -> None:
    mock_pool.fetchrow.return_value = _record(_make_summary_row(todo=1, doing=2, succeeded=5, failed=1))
    resp = await client.get("/admin/jobs/summary", headers=ALICE_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["todo"] == 1
    assert data["doing"] == 2
    assert data["succeeded"] == 5
    assert data["failed"] == 1
    assert data["total"] == 9


# ---------------------------------------------------------------------------
# Job detail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_job_detail_found(client: AsyncClient, mock_pool) -> None:
    mock_pool.fetchrow.return_value = _record(_make_job_row(job_id=42, agent_id="alice"))
    mock_pool.fetch.return_value = [
        _record({"type": "deferred", "at": datetime.now(UTC)}),
        _record({"type": "started", "at": datetime.now(UTC)}),
    ]
    resp = await client.get("/admin/jobs/42", headers=ALICE_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == 42
    assert len(data["events"]) == 2
    assert data["events"][0]["type"] == "deferred"


@pytest.mark.asyncio
async def test_job_detail_other_agents_job_requires_admin(client: AsyncClient, mock_pool) -> None:
    mock_pool.fetchrow.return_value = _record(_make_job_row(job_id=42, agent_id="bob"))
    resp = await client.get("/admin/jobs/42", headers=ALICE_HEADERS)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_job_detail_admin_can_view_any(
    client: AsyncClient, permissions: InMemoryPermissionService, mock_pool
) -> None:
    await permissions.ensure_admin(BOOTSTRAP_ADMIN)
    mock_pool.fetchrow.return_value = _record(_make_job_row(job_id=42, agent_id="alice"))
    mock_pool.fetch.return_value = []
    resp = await client.get("/admin/jobs/42", headers=ADMIN_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["id"] == 42


@pytest.mark.asyncio
async def test_job_detail_not_found(client: AsyncClient, mock_pool) -> None:
    mock_pool.fetchrow.return_value = None
    resp = await client.get("/admin/jobs/999", headers=ALICE_HEADERS)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Cancel job
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_own_job(client: AsyncClient, mock_pool) -> None:
    # Ownership check via pool.fetchrow, cancel via conn.fetchrow (transactional)
    mock_pool.fetchrow.return_value = _record({"owner": "alice"})
    mock_pool._mock_conn.fetchrow.return_value = _record({"id": 10})
    resp = await client.delete("/admin/jobs/10", headers=ALICE_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_fails_if_not_todo(client: AsyncClient, mock_pool) -> None:
    mock_pool.fetchrow.return_value = _record({"owner": "alice"})
    mock_pool._mock_conn.fetchrow.return_value = None  # cancel returns nothing
    resp = await client.delete("/admin/jobs/10", headers=ALICE_HEADERS)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_cancel_other_agents_job_requires_admin(client: AsyncClient, mock_pool) -> None:
    mock_pool.fetchrow.return_value = _record({"owner": "bob"})
    resp = await client.delete("/admin/jobs/10", headers=ALICE_HEADERS)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cancel_other_agents_job_as_admin(
    client: AsyncClient, permissions: InMemoryPermissionService, mock_pool
) -> None:
    await permissions.ensure_admin(BOOTSTRAP_ADMIN)
    mock_pool.fetchrow.return_value = _record({"owner": "alice"})
    mock_pool._mock_conn.fetchrow.return_value = _record({"id": 10})
    resp = await client.delete("/admin/jobs/10", headers=ADMIN_HEADERS)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_cancel_nonexistent_job(client: AsyncClient, mock_pool) -> None:
    mock_pool.fetchrow.return_value = None
    resp = await client.delete("/admin/jobs/999", headers=ALICE_HEADERS)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Retry job
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_failed_job(app, client: AsyncClient, mock_pool) -> None:
    original_args = {"agent_id": "alice", "episode_id": "ep-1"}
    mock_pool.fetchrow.return_value = _record(
        {
            "task_name": "extract_episode",
            "args": original_args,
            "status": "failed",
        }
    )
    mock_job_app = MagicMock()
    mock_task = MagicMock()
    mock_task.defer_async = AsyncMock(return_value=99)
    mock_job_app.configure_task.return_value = mock_task
    app.state.services_ctx["job_app"] = mock_job_app

    resp = await client.post("/admin/jobs/5/retry", headers=ALICE_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "retried"
    assert data["new_job_id"] == 99
    mock_job_app.configure_task.assert_called_once_with("extract_episode")


@pytest.mark.asyncio
async def test_retry_extract_job_preserves_existing_correlation_id(app, client: AsyncClient, mock_pool) -> None:
    original_args = {
        "agent_id": "alice",
        "episode_ids": [1],
        "correlation_id": "extract-0123456789abcdef0123456789abcdef",
    }
    mock_pool.fetchrow.return_value = _record(
        {"task_name": "extract_episode", "args": original_args, "status": "failed"}
    )
    mock_job_app = MagicMock()
    mock_task = MagicMock()
    mock_task.defer_async = AsyncMock(return_value=99)
    mock_job_app.configure_task.return_value = mock_task
    app.state.services_ctx["job_app"] = mock_job_app

    resp = await client.post("/admin/jobs/5/retry", headers=ALICE_HEADERS)

    assert resp.status_code == 200
    assert mock_task.defer_async.call_args.kwargs == original_args


@pytest.mark.asyncio
async def test_retry_legacy_extract_job_gets_opaque_correlation_id(app, client: AsyncClient, mock_pool) -> None:
    original_args = {"agent_id": "alice", "episode_ids": [1]}
    mock_pool.fetchrow.return_value = _record(
        {"task_name": "extract_episode", "args": original_args, "status": "failed"}
    )
    mock_job_app = MagicMock()
    mock_task = MagicMock()
    mock_task.defer_async = AsyncMock(return_value=99)
    mock_job_app.configure_task.return_value = mock_task
    app.state.services_ctx["job_app"] = mock_job_app

    resp = await client.post("/admin/jobs/5/retry", headers=ALICE_HEADERS)

    assert resp.status_code == 200
    retry_args = mock_task.defer_async.call_args.kwargs
    assert retry_args["agent_id"] == "alice"
    assert retry_args["episode_ids"] == [1]
    assert retry_args["correlation_id"].startswith("extract-")
    assert original_args == {"agent_id": "alice", "episode_ids": [1]}


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_id", ["job:alice:1", "extract-original-id", 42, {"legacy": True}])
async def test_retry_non_opaque_extract_id_is_replaced(app, client: AsyncClient, mock_pool, legacy_id: object) -> None:
    original_args = {"agent_id": "alice", "episode_ids": [1], "correlation_id": legacy_id}
    mock_pool.fetchrow.return_value = _record(
        {"task_name": "extract_episode", "args": original_args, "status": "failed"}
    )
    mock_job_app = MagicMock()
    mock_task = MagicMock()
    mock_task.defer_async = AsyncMock(return_value=99)
    mock_job_app.configure_task.return_value = mock_task
    app.state.services_ctx["job_app"] = mock_job_app

    resp = await client.post("/admin/jobs/5/retry", headers=ALICE_HEADERS)

    assert resp.status_code == 200
    retry_args = mock_task.defer_async.call_args.kwargs
    assert retry_args["correlation_id"].startswith("extract-")
    assert retry_args["correlation_id"] != legacy_id


@pytest.mark.asyncio
async def test_retry_non_failed_job_returns_409(client: AsyncClient, mock_pool) -> None:
    mock_pool.fetchrow.return_value = _record(
        {
            "task_name": "extract_episode",
            "args": {"agent_id": "alice"},
            "status": "succeeded",
        }
    )
    resp = await client.post("/admin/jobs/5/retry", headers=ALICE_HEADERS)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_retry_without_job_app_returns_501(app, client: AsyncClient, mock_pool) -> None:
    mock_pool.fetchrow.return_value = _record(
        {
            "task_name": "extract_episode",
            "args": {"agent_id": "alice"},
            "status": "failed",
        }
    )
    # Ensure no job_app in services_ctx
    app.state.services_ctx = {}
    resp = await client.post("/admin/jobs/5/retry", headers=ALICE_HEADERS)
    assert resp.status_code == 501


@pytest.mark.asyncio
async def test_retry_other_agents_job_requires_admin(client: AsyncClient, mock_pool) -> None:
    mock_pool.fetchrow.return_value = _record(
        {
            "task_name": "extract_episode",
            "args": {"agent_id": "bob"},
            "status": "failed",
        }
    )
    resp = await client.post("/admin/jobs/5/retry", headers=ALICE_HEADERS)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Mock DB mode (pool=None)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jobs_501_when_no_pool(settings: MCPSettings, permissions: InMemoryPermissionService) -> None:
    """All job endpoints return 501 when pool is None (mock DB mode)."""
    from fastapi import FastAPI

    from neocortex.admin.routes import router as admin_router
    from neocortex.ingestion.routes import router as ingest_router

    app = FastAPI()
    app.state.settings = settings
    app.state.permissions = permissions
    app.state.schema_mgr = None
    app.state.pool = None
    app.state.services_ctx = {}
    app.state.token_map = {"alice-token": "alice"}

    app.include_router(ingest_router)
    app.include_router(admin_router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for path in ["/admin/jobs", "/admin/jobs/summary", "/admin/jobs/1"]:
            resp = await client.get(path, headers={"Authorization": "Bearer alice-token"})
            assert resp.status_code == 501, f"Expected 501 for {path}"

        resp = await client.delete("/admin/jobs/1", headers={"Authorization": "Bearer alice-token"})
        assert resp.status_code == 501

        resp = await client.post("/admin/jobs/1/retry", headers={"Authorization": "Bearer alice-token"})
        assert resp.status_code == 501
