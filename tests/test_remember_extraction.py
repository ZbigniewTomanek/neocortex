"""Tests for extraction job wiring in remember tool and ingestion processor."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neocortex.db.mock import InMemoryRepository
from neocortex.ingestion.episode_processor import EpisodeProcessor
from neocortex.mcp_settings import MCPSettings
from neocortex.schemas.memory import RememberResult

# ── Fixtures ──


@pytest.fixture
def repo() -> InMemoryRepository:
    return InMemoryRepository()


@pytest.fixture
def settings() -> MCPSettings:
    return MCPSettings(mock_db=True, extraction_enabled=True)


def _make_mock_job_app(return_value: int = 42) -> MagicMock:
    """Create a mock job_app whose configure_task(...).defer_async(...) returns return_value."""
    mock_job_app = MagicMock()
    mock_deferrer = MagicMock()
    mock_deferrer.defer_async = AsyncMock(return_value=return_value)
    mock_job_app.configure_task.return_value = mock_deferrer
    return mock_job_app


# ── Remember tool tests ──


@pytest.mark.asyncio
async def test_remember_skips_extraction_when_no_job_app(repo: InMemoryRepository, settings: MCPSettings):
    """Without job_app, remember stores episode but doesn't enqueue extraction."""
    ctx = MagicMock()
    ctx.lifespan_context = {
        "repo": repo,
        "settings": settings,
        "embeddings": None,
        "job_app": None,
    }

    with patch("neocortex.tools.remember.get_agent_id_from_context", return_value="test-agent"):
        from neocortex.tools.remember import remember

        result = await remember("Test memory", ctx=ctx)

    assert isinstance(result, RememberResult)
    assert result.status == "stored"
    assert result.episode_id > 0
    assert result.extraction_job_id is None


@pytest.mark.asyncio
async def test_remember_skips_extraction_when_disabled(repo: InMemoryRepository):
    """With extraction_enabled=False, no job is enqueued even with job_app."""
    settings = MCPSettings(mock_db=True, extraction_enabled=False, domain_routing_enabled=False)
    ctx = MagicMock()
    ctx.lifespan_context = {
        "repo": repo,
        "settings": settings,
        "embeddings": None,
        "job_app": MagicMock(),  # job_app present but extraction disabled
    }

    with patch("neocortex.tools.remember.get_agent_id_from_context", return_value="test-agent"):
        from neocortex.tools.remember import remember

        result = await remember("Test memory", ctx=ctx)

    assert result.extraction_job_id is None


@pytest.mark.asyncio
async def test_remember_enqueues_extraction_job(repo: InMemoryRepository):
    """With job_app and extraction enabled, remember defers an extraction job."""
    settings = MCPSettings(mock_db=True, extraction_enabled=True, domain_routing_enabled=False)
    mock_job_app = _make_mock_job_app(return_value=42)

    ctx = MagicMock()
    ctx.lifespan_context = {
        "repo": repo,
        "settings": settings,
        "embeddings": None,
        "job_app": mock_job_app,
    }

    with patch("neocortex.tools.remember.get_agent_id_from_context", return_value="test-agent"):
        from neocortex.tools.remember import remember

        result = await remember("Test memory about serotonin", ctx=ctx)

    assert result.status == "stored"
    assert result.episode_id > 0
    assert result.extraction_job_id == 42

    # Verify configure_task was called correctly
    mock_job_app.configure_task.assert_called_once_with("extract_episode")
    extraction_call = mock_job_app.configure_task.return_value.defer_async.call_args
    assert extraction_call is not None
    assert extraction_call.kwargs["agent_id"] == "test-agent"
    assert extraction_call.kwargs["episode_ids"] == [result.episode_id]
    assert extraction_call.kwargs["target_schema"] is None
    assert extraction_call.kwargs["correlation_id"].startswith("extract-")


# ── EpisodeProcessor tests ──


@pytest.mark.asyncio
async def test_processor_skips_extraction_when_no_job_app(repo: InMemoryRepository):
    """EpisodeProcessor without job_app stores but doesn't enqueue."""
    processor = EpisodeProcessor(repo=repo, job_app=None)
    result = await processor.process_text("agent-a", "hello world", {})

    assert result.status == "stored"
    assert result.episodes_created == 1


@pytest.mark.asyncio
async def test_processor_skips_extraction_when_disabled(repo: InMemoryRepository):
    """EpisodeProcessor with extraction_enabled=False doesn't enqueue."""
    mock_job_app = MagicMock()
    processor = EpisodeProcessor(
        repo=repo, job_app=mock_job_app, extraction_enabled=False, domain_routing_enabled=False
    )
    result = await processor.process_text("agent-a", "hello world", {})

    assert result.status == "stored"
    assert result.episodes_created == 1


@pytest.mark.asyncio
async def test_processor_enqueues_extraction_on_text(repo: InMemoryRepository):
    """EpisodeProcessor with job_app defers extraction after storing text."""
    mock_job_app = _make_mock_job_app(return_value=99)

    processor = EpisodeProcessor(repo=repo, job_app=mock_job_app, extraction_enabled=True, domain_routing_enabled=False)
    result = await processor.process_text("agent-a", "serotonin modulates mood", {})

    assert result.status == "stored"
    assert result.episodes_created == 1
    mock_job_app.configure_task.assert_called_with("extract_episode")
    mock_job_app.configure_task.return_value.defer_async.assert_called_once()
    call_kwargs = mock_job_app.configure_task.return_value.defer_async.call_args[1]
    assert call_kwargs["agent_id"] == "agent-a"
    assert len(call_kwargs["episode_ids"]) == 1


@pytest.mark.asyncio
async def test_processor_enqueues_extraction_on_document(repo: InMemoryRepository):
    """EpisodeProcessor defers extraction after storing a document."""
    mock_job_app = _make_mock_job_app(return_value=101)

    processor = EpisodeProcessor(repo=repo, job_app=mock_job_app, extraction_enabled=True, domain_routing_enabled=False)
    result = await processor.process_document("agent-a", "doc.txt", b"Medical text about SSRIs", "text/plain", {})

    assert result.status == "stored"
    mock_job_app.configure_task.return_value.defer_async.assert_called_once()


@pytest.mark.asyncio
async def test_processor_enqueues_extraction_on_events(repo: InMemoryRepository):
    """EpisodeProcessor defers extraction for each event in a batch."""
    mock_job_app = _make_mock_job_app(return_value=200)

    processor = EpisodeProcessor(repo=repo, job_app=mock_job_app, extraction_enabled=True, domain_routing_enabled=False)
    events = [{"type": "note", "text": "fact 1"}, {"type": "note", "text": "fact 2"}]
    result = await processor.process_events("agent-a", events, {})

    assert result.status == "stored"
    assert result.episodes_created == 2
    assert mock_job_app.configure_task.return_value.defer_async.call_count == 2


@pytest.mark.asyncio
async def test_processor_backward_compat_stub_import():
    """StubProcessor import from old module still works."""
    from neocortex.ingestion.stub_processor import StubProcessor

    assert StubProcessor is EpisodeProcessor
