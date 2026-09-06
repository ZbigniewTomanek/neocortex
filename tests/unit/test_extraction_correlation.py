"""Collision and privacy contracts for extraction-job correlation ids."""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neocortex.db.mock import InMemoryRepository
from neocortex.domains.memory_service import InMemoryDomainService
from neocortex.domains.models import ClassificationResult, DomainClassification
from neocortex.domains.router import DomainRouter
from neocortex.ingestion.episode_processor import EpisodeProcessor
from neocortex.jobs.correlation import new_extraction_correlation_id, normalize_extraction_correlation_id
from neocortex.permissions.memory_service import InMemoryPermissionService

_CORRELATION_ID = re.compile(r"^extract-[0-9a-f]{32}$")


def _job_app() -> MagicMock:
    job_app = MagicMock()
    task = MagicMock()
    task.defer_async = AsyncMock(return_value=1)
    job_app.configure_task.return_value = task
    return job_app


def test_correlation_ids_are_opaque_and_collision_free_for_sample() -> None:
    ids = {new_extraction_correlation_id() for _ in range(1000)}

    assert len(ids) == 1000
    assert all(_CORRELATION_ID.fullmatch(value) for value in ids)
    assert all("agent" not in value and "episode" not in value for value in ids)


@pytest.mark.parametrize("legacy_id", [None, "job:alice:1", "extract-original-id", 42, {"legacy": True}])
def test_correlation_normalization_replaces_non_opaque_values(legacy_id: object) -> None:
    normalized = normalize_extraction_correlation_id(legacy_id)

    assert _CORRELATION_ID.fullmatch(normalized)
    if legacy_id is not None:
        assert normalized != legacy_id


def test_correlation_normalization_preserves_valid_value_byte_for_byte() -> None:
    valid_id = "extract-0123456789abcdef0123456789abcdef"

    assert normalize_extraction_correlation_id(valid_id) == valid_id


@pytest.mark.asyncio
async def test_personal_mcp_and_ingestion_enqueue_distinct_ids() -> None:
    from neocortex.mcp_settings import MCPSettings
    from neocortex.tools.remember import remember

    repo = InMemoryRepository()
    job_app = _job_app()
    context = MagicMock()
    context.lifespan_context = {
        "repo": repo,
        "settings": MCPSettings(mock_db=True, extraction_enabled=True, domain_routing_enabled=False),
        "embeddings": None,
        "job_app": job_app,
    }

    with patch("neocortex.tools.remember.get_agent_id_from_context", return_value="agent"):
        await remember("first", ctx=context)
        await remember("second", ctx=context)

    processor = EpisodeProcessor(repo=repo, job_app=job_app, extraction_enabled=True, domain_routing_enabled=False)
    await processor.process_text("agent", "third", {})

    calls = job_app.configure_task.return_value.defer_async.call_args_list
    ids = [call.kwargs["correlation_id"] for call in calls]
    assert len(ids) == 3
    assert len(set(ids)) == 3
    assert all(_CORRELATION_ID.fullmatch(value) for value in ids)


@pytest.mark.asyncio
async def test_routed_extraction_enqueue_gets_distinct_opaque_ids() -> None:
    service = InMemoryDomainService()
    await service.seed_defaults()
    permissions = InMemoryPermissionService(bootstrap_admin_id="admin")
    await permissions.grant("agent", "ncx_shared__technical_knowledge", True, True, "test")
    classifier = AsyncMock(
        classify=AsyncMock(
            return_value=ClassificationResult(
                matched_domains=[
                    DomainClassification(domain_slug="technical_knowledge", confidence=0.9, reasoning="test")
                ]
            )
        )
    )
    job_app = _job_app()
    router = DomainRouter(service, classifier, None, permissions, job_app=job_app)

    await router.route_and_extract("agent", 4, "technical text")
    await router.route_and_extract("agent", 5, "technical text")

    calls = job_app.configure_task.return_value.defer_async.call_args_list
    ids = [call.kwargs["correlation_id"] for call in calls]
    assert len(ids) == 2
    assert len(set(ids)) == 2
    assert all(_CORRELATION_ID.fullmatch(value) for value in ids)
    assert all("technical_knowledge" not in value for value in ids)
