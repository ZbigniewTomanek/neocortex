"""Ensure dynamic routing identifiers do not enter durable action logs."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from loguru import logger

from neocortex.db.mock import InMemoryRepository
from neocortex.domains.memory_service import InMemoryDomainService
from neocortex.domains.models import ClassificationResult, ProposedDomain, RoutingResult
from neocortex.domains.ontology_seeds import DomainOntologySeed
from neocortex.domains.router import DomainRouter
from neocortex.domains.seed_generator import SeedGenerator
from neocortex.extraction.agents import AgentInferenceConfig
from neocortex.extraction.pipeline import run_extraction
from neocortex.permissions.memory_service import InMemoryPermissionService


def _action_records(records: list[dict]) -> list[dict]:
    return [record for record in records if record["extra"].get("action_log")]


@pytest.mark.asyncio
async def test_valid_dynamic_slug_is_opaque_in_router_action_logs() -> None:
    domain_service = InMemoryDomainService()
    await domain_service.seed_defaults()
    permissions = InMemoryPermissionService(bootstrap_admin_id="admin")
    source_sentinel = "valid_private_dynamic_domain"
    classifier = AsyncMock()
    classifier.classify.return_value = ClassificationResult(
        proposed_domain=ProposedDomain(
            slug=source_sentinel,
            name="Private dynamic domain",
            description="A model-created domain",
            reasoning="test",
        )
    )
    schema_mgr = AsyncMock()
    schema_mgr.create_graph.side_effect = lambda agent_id, purpose, is_shared=False: f"ncx_shared__{purpose}"
    seed_generator = AsyncMock()
    router = DomainRouter(
        domain_service=domain_service,
        classifier=classifier,
        schema_mgr=schema_mgr,
        permissions=permissions,
        seed_generator=seed_generator,
    )
    records: list[dict] = []
    sink_id = logger.add(lambda message: records.append(message.record), level="INFO")
    try:
        results = await router.route_and_extract("agent", 1, "safe episode")
    finally:
        logger.remove(sink_id)

    dynamic_domain = await domain_service.get_domain(source_sentinel)
    assert dynamic_domain is not None
    action_records = _action_records(records)
    assert results and results[0].domain_slug == source_sentinel
    assert action_records
    assert all(source_sentinel not in str(record["extra"]) for record in action_records)
    classification_record = next(
        record for record in action_records if record["message"] == "domain_classification_result"
    )
    assert classification_record["extra"]["accepted_domain_ids"] == [dynamic_domain.id]
    provisioned_record = next(record for record in action_records if record["message"] == "domain_provisioned")
    assert provisioned_record["extra"]["domain_id"] == dynamic_domain.id
    completed_record = next(record for record in action_records if record["message"] == "domain_routing_completed")
    assert completed_record["extra"]["routed_domain_ids"] == [dynamic_domain.id]


@pytest.mark.asyncio
async def test_seed_generation_uses_domain_id_in_action_log(monkeypatch: pytest.MonkeyPatch) -> None:
    domain_service = InMemoryDomainService()
    source_sentinel = "valid_private_seed_domain"
    dynamic_domain = await domain_service.create_domain(
        slug=source_sentinel,
        name="Private dynamic domain",
        description="A model-created domain",
        created_by="agent",
    )
    seed_generator = SeedGenerator(domain_service)
    monkeypatch.setattr(seed_generator, "_generate_seed", AsyncMock(return_value=DomainOntologySeed()))
    records: list[dict] = []
    sink_id = logger.add(lambda message: records.append(message.record), level="INFO")
    try:
        await seed_generator.resolve_seed(source_sentinel)
    finally:
        logger.remove(sink_id)

    action_records = _action_records(records)
    assert action_records
    assert all(source_sentinel not in str(record["extra"]) for record in action_records)
    seed_record = next(record for record in action_records if record["message"] == "seed_generated")
    assert seed_record["extra"]["domain_id"] == dynamic_domain.id
    assert seed_record["extra"]["static_domain"] is False


@pytest.mark.asyncio
async def test_route_job_logs_counts_instead_of_dynamic_result_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import neocortex.jobs.context as context
    from neocortex.jobs.tasks import route_episode

    source_sentinel = "valid_private_route_domain"
    domain_router = AsyncMock()
    domain_router.route_and_extract.return_value = [
        RoutingResult(domain_slug=source_sentinel, schema_name=f"ncx_shared__{source_sentinel}", confidence=0.8)
    ]
    monkeypatch.setattr(context, "_services", {"domain_router": domain_router})
    records: list[dict] = []
    sink_id = logger.add(lambda message: records.append(message.record), level="INFO")
    try:
        await route_episode("agent", 1, "safe episode")
    finally:
        logger.remove(sink_id)

    action_records = _action_records(records)
    assert action_records
    assert all(source_sentinel not in str(record["extra"]) for record in action_records)
    completed_record = next(record for record in action_records if record["message"] == "route_episode_completed")
    assert completed_record["extra"]["routed_count"] == 1
    assert "routed_to" not in completed_record["extra"]


@pytest.mark.asyncio
async def test_extract_job_logs_presence_flags_instead_of_dynamic_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import neocortex.jobs.context as context
    from neocortex.jobs.tasks import extract_episode

    source_sentinel = "valid_private_extract_domain"
    settings = SimpleNamespace(
        ontology_model="test-model",
        ontology_thinking_effort="low",
        extractor_model="test-model",
        extractor_thinking_effort="low",
        librarian_model="test-model",
        librarian_thinking_effort="low",
        librarian_use_tools=True,
        extraction_tool_calls_limit=150,
        ontology_tool_calls_limit=30,
        ontology_max_new_types=3,
        ontology_max_tokens=600,
        extractor_max_tokens=2500,
        librarian_max_tokens=1500,
    )
    monkeypatch.setattr(
        context,
        "_services",
        {"repo": AsyncMock(), "embeddings": None, "settings": settings, "seed_generator": None},
    )
    mock_run = AsyncMock()
    monkeypatch.setattr("neocortex.extraction.pipeline.run_extraction", mock_run)
    records: list[dict] = []
    sink_id = logger.add(lambda message: records.append(message.record), level="INFO")
    try:
        await extract_episode(
            agent_id="agent",
            episode_ids=[1],
            target_schema=f"ncx_shared__{source_sentinel}",
            source_schema="__personal__",
            domain_hint=f"private hint {source_sentinel}",
            domain_slug=source_sentinel,
        )
    finally:
        logger.remove(sink_id)

    action_records = _action_records(records)
    assert action_records
    assert all(source_sentinel not in str(record["extra"]) for record in action_records)
    started_record = next(record for record in action_records if record["message"] == "extract_episode_started")
    assert started_record["extra"]["routed_extraction"] is True
    assert "target_schema" not in started_record["extra"]
    assert "domain_slug" not in started_record["extra"]


@pytest.mark.asyncio
async def test_pipeline_action_logs_exclude_dynamic_target_schema() -> None:
    source_sentinel = "valid_private_pipeline_domain"
    target_schema = f"ncx_shared__{source_sentinel}"
    repo = InMemoryRepository()
    await repo.store_episode("agent", "safe episode")
    records: list[dict] = []
    sink_id = logger.add(lambda message: records.append(message.record), level="INFO")
    try:
        await run_extraction(
            repo=repo,
            embeddings=None,
            agent_id="agent",
            episode_ids=[1],
            target_schema=target_schema,
            source_schema=None,
            ontology_config=AgentInferenceConfig(use_test_model=True),
            extractor_config=AgentInferenceConfig(use_test_model=True),
            librarian_config=AgentInferenceConfig(use_test_model=True),
            domain_slug=source_sentinel,
            librarian_use_tools=False,
            archive_interval=0,
        )
    finally:
        logger.remove(sink_id)

    action_records = _action_records(records)
    assert action_records
    assert all(source_sentinel not in str(record["extra"]) for record in action_records)
    complete_record = next(record for record in action_records if record["message"] == "extraction_complete")
    assert complete_record["extra"]["target_schema_present"] is True
    assert complete_record["extra"]["routed_extraction"] is True
    assert "target_schema" not in complete_record["extra"]
