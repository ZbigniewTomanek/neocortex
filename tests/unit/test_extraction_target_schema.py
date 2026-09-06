"""Tests for extraction pipeline target_schema awareness."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from neocortex.db.mock import InMemoryRepository
from neocortex.ingestion.episode_processor import EpisodeProcessor

SHARED_SCHEMA = "ncx_shared__research"


@pytest.fixture
def repo() -> InMemoryRepository:
    return InMemoryRepository()


@pytest.mark.asyncio
async def test_store_episode_routes_to_target_schema(repo: InMemoryRepository) -> None:
    """EpisodeProcessor stores episodes in the target schema when specified."""
    processor = EpisodeProcessor(repo=repo, extraction_enabled=False)
    result = await processor.process_text("alice", "Shared fact", {}, target_schema=SHARED_SCHEMA)

    assert result.status == "stored"
    assert SHARED_SCHEMA in repo._schema_episodes
    assert len(repo._schema_episodes[SHARED_SCHEMA]) == 1
    assert repo._schema_episodes[SHARED_SCHEMA][0]["content"] == "Shared fact"


@pytest.mark.asyncio
async def test_store_episode_personal_when_no_target(repo: InMemoryRepository) -> None:
    """EpisodeProcessor stores in personal graph when no target_schema."""
    processor = EpisodeProcessor(repo=repo, extraction_enabled=False)
    result = await processor.process_text("alice", "Personal fact", {})

    assert result.status == "stored"
    assert len(repo._schema_episodes) == 0
    assert len(repo._episodes) == 1


@pytest.mark.asyncio
async def test_enqueue_extraction_passes_target_schema() -> None:
    """_enqueue_extraction passes target_schema to the job."""
    mock_job_app = MagicMock()
    mock_task = MagicMock()
    mock_task.defer_async = AsyncMock(return_value=42)
    mock_job_app.configure_task.return_value = mock_task

    repo = InMemoryRepository()
    processor = EpisodeProcessor(repo=repo, job_app=mock_job_app, extraction_enabled=True)

    # Store an episode in the target schema
    episode_id = await repo.store_episode_to("alice", SHARED_SCHEMA, "Shared research content")
    await processor._enqueue_extraction("alice", episode_id, target_schema=SHARED_SCHEMA)

    mock_job_app.configure_task.assert_called_once_with("extract_episode")
    call = mock_task.defer_async.call_args
    assert call is not None
    assert call.kwargs == {
        "agent_id": "alice",
        "episode_ids": [episode_id],
        "target_schema": SHARED_SCHEMA,
        "correlation_id": call.kwargs["correlation_id"],
    }
    assert call.kwargs["correlation_id"].startswith("extract-")


@pytest.mark.asyncio
async def test_enqueue_extraction_none_target_schema() -> None:
    """_enqueue_extraction passes None target_schema for personal graph."""
    mock_job_app = MagicMock()
    mock_task = MagicMock()
    mock_task.defer_async = AsyncMock(return_value=42)
    mock_job_app.configure_task.return_value = mock_task

    repo = InMemoryRepository()
    processor = EpisodeProcessor(repo=repo, job_app=mock_job_app, extraction_enabled=True)

    episode_id = await repo.store_episode("alice", "Personal content")
    await processor._enqueue_extraction("alice", episode_id, target_schema=None)

    call = mock_task.defer_async.call_args
    assert call is not None
    assert call.kwargs["agent_id"] == "alice"
    assert call.kwargs["episode_ids"] == [episode_id]
    assert call.kwargs["target_schema"] is None
    assert call.kwargs["correlation_id"].startswith("extract-")


@pytest.mark.asyncio
async def test_process_text_with_target_enqueues_correctly() -> None:
    """process_text with target_schema passes it through to enqueue."""
    mock_job_app = MagicMock()
    mock_task = MagicMock()
    mock_task.defer_async = AsyncMock(return_value=42)
    mock_job_app.configure_task.return_value = mock_task

    repo = InMemoryRepository()
    processor = EpisodeProcessor(repo=repo, job_app=mock_job_app, extraction_enabled=True)

    result = await processor.process_text("alice", "Shared fact", {}, target_schema=SHARED_SCHEMA)

    assert result.status == "stored"
    # Verify the extraction job was enqueued with target_schema
    mock_task.defer_async.assert_called_once()
    call_kwargs = mock_task.defer_async.call_args
    assert call_kwargs.kwargs.get("target_schema") == SHARED_SCHEMA or (
        len(call_kwargs.args) == 0 and call_kwargs[1].get("target_schema") == SHARED_SCHEMA
    )


@pytest.mark.asyncio
async def test_process_document_with_target_schema(repo: InMemoryRepository) -> None:
    """process_document routes to target schema."""
    processor = EpisodeProcessor(repo=repo, extraction_enabled=False)
    result = await processor.process_document(
        "alice", "doc.txt", b"shared doc content", "text/plain", {}, target_schema=SHARED_SCHEMA
    )

    assert result.status == "stored"
    assert SHARED_SCHEMA in repo._schema_episodes


@pytest.mark.asyncio
async def test_process_events_with_target_schema(repo: InMemoryRepository) -> None:
    """process_events routes to target schema."""
    processor = EpisodeProcessor(repo=repo, extraction_enabled=False)
    result = await processor.process_events("alice", [{"type": "test"}], {}, target_schema=SHARED_SCHEMA)

    assert result.status == "stored"
    assert SHARED_SCHEMA in repo._schema_episodes
