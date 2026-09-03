"""Runtime invariants used to bound model work in routed extraction."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from loguru import logger

from neocortex.domains.memory_service import InMemoryDomainService
from neocortex.domains.models import (
    SEED_DOMAINS,
    ClassificationResult,
    DomainClassification,
    ProposedDomain,
)
from neocortex.domains.router import MAX_UNIQUE_ROUTED_DOMAINS, DomainRouter
from neocortex.permissions.memory_service import InMemoryPermissionService


@pytest.mark.asyncio
async def test_untrusted_duplicate_and_unknown_matches_enqueue_one_job_per_known_domain() -> None:
    domain_service = InMemoryDomainService()
    await domain_service.seed_defaults()
    permissions = InMemoryPermissionService(bootstrap_admin_id="admin")
    await permissions.grant("agent", "ncx_shared__technical_knowledge", True, True, "test")
    classifier = AsyncMock()
    classifier.classify.return_value = ClassificationResult(
        matched_domains=(
            [DomainClassification(domain_slug="technical_knowledge", confidence=0.4, reasoning="weak")]
            + [DomainClassification(domain_slug="technical_knowledge", confidence=0.9, reasoning="strong")] * 100
            + [DomainClassification(domain_slug="not_a_real_domain", confidence=0.9, reasoning="match")] * 100
        )
    )

    router = DomainRouter(
        domain_service=domain_service,
        classifier=classifier,
        schema_mgr=None,
        permissions=permissions,
    )

    results = await router.route_and_extract("agent", 1, "technical text")

    assert [(result.domain_slug, result.confidence) for result in results] == [("technical_knowledge", 0.9)]


@pytest.mark.asyncio
async def test_action_log_excludes_unknown_classifier_slug() -> None:
    domain_service = InMemoryDomainService()
    await domain_service.seed_defaults()
    permissions = InMemoryPermissionService(bootstrap_admin_id="admin")
    await permissions.grant("agent", "ncx_shared__technical_knowledge", True, True, "test")
    source_sentinel = "private-classification-source-secret"
    classifier = AsyncMock()
    classifier.classify.return_value = ClassificationResult(
        matched_domains=[
            DomainClassification(domain_slug=source_sentinel, confidence=0.99, reasoning="untrusted"),
            DomainClassification(domain_slug="technical_knowledge", confidence=0.9, reasoning="match"),
        ]
    )
    router = DomainRouter(
        domain_service=domain_service,
        classifier=classifier,
        schema_mgr=None,
        permissions=permissions,
    )
    records: list[dict] = []
    sink_id = logger.add(lambda message: records.append(message.record), level="INFO")
    try:
        results = await router.route_and_extract("agent", 1, "technical text")
    finally:
        logger.remove(sink_id)

    action_records = [record for record in records if record["extra"].get("action_log")]
    assert [result.domain_slug for result in results] == ["technical_knowledge"]
    assert action_records
    assert all(source_sentinel not in str(record["extra"]) for record in action_records)
    classification_record = next(
        record for record in action_records if record["message"] == "domain_classification_result"
    )
    assert classification_record["extra"]["accepted_domain_slugs"] == ["technical_knowledge"]


@pytest.mark.asyncio
async def test_invalid_proposal_slug_is_discarded_without_blocking_known_matches() -> None:
    domain_service = InMemoryDomainService()
    await domain_service.seed_defaults()
    permissions = InMemoryPermissionService(bootstrap_admin_id="admin")
    await permissions.grant("agent", "ncx_shared__technical_knowledge", True, True, "test")
    classifier = AsyncMock()
    classifier.classify.return_value = ClassificationResult(
        matched_domains=[DomainClassification(domain_slug="technical_knowledge", confidence=0.9, reasoning="match")],
        proposed_domain=ProposedDomain(
            slug="!!!",
            name="Invalid proposal",
            description="The slug sanitizes to an empty value",
            reasoning="adversarial input",
        ),
    )
    schema_mgr = AsyncMock()
    schema_mgr.get_graph.return_value = {"schema_name": "existing"}

    router = DomainRouter(
        domain_service=domain_service,
        classifier=classifier,
        schema_mgr=schema_mgr,
        permissions=permissions,
    )

    results = await router.route_and_extract("agent", 1, "technical text")

    assert [result.domain_slug for result in results] == ["technical_knowledge"]
    schema_mgr.create_graph.assert_not_awaited()


@pytest.mark.asyncio
async def test_route_cap_is_five_and_reserves_one_slot_for_a_proposal() -> None:
    domain_service = InMemoryDomainService()
    await domain_service.seed_defaults()
    for index in range(6):
        await domain_service.create_domain(
            slug=f"existing_{index}",
            name=f"Existing {index}",
            description="An existing dynamic domain",
            created_by="agent",
        )
    permissions = InMemoryPermissionService(bootstrap_admin_id="admin")
    classifier = AsyncMock()
    classifier.classify.return_value = ClassificationResult(
        matched_domains=[
            DomainClassification(domain_slug=slug, confidence=confidence, reasoning="match")
            for slug, confidence in (
                ("user_profile", 0.9),
                ("technical_knowledge", 0.8),
                ("work_context", 0.7),
                ("domain_knowledge", 0.6),
            )
        ]
        * 10
        + [
            DomainClassification(domain_slug=f"existing_{index}", confidence=0.55, reasoning="dynamic match")
            for index in range(6)
        ],
        proposed_domain=ProposedDomain(
            slug="novel_domain",
            name="Novel domain",
            description="A proposed domain",
            reasoning="test",
        ),
    )
    schema_mgr = AsyncMock()
    schema_mgr.get_graph.return_value = {"schema_name": "existing"}
    schema_mgr.create_graph.side_effect = lambda agent_id, purpose, is_shared=False: f"ncx_shared__{purpose}"
    seed_generator = AsyncMock()

    router = DomainRouter(
        domain_service=domain_service,
        classifier=classifier,
        schema_mgr=schema_mgr,
        permissions=permissions,
        seed_generator=seed_generator,
    )

    results = await router.route_and_extract("agent", 1, "novel text")

    assert MAX_UNIQUE_ROUTED_DOMAINS == len(SEED_DOMAINS) + 1 == 5
    assert len(results) == MAX_UNIQUE_ROUTED_DOMAINS
    assert [result.domain_slug for result in results] == [
        "user_profile",
        "technical_knowledge",
        "work_context",
        "domain_knowledge",
        "novel_domain",
    ]
    seed_generator.resolve_seed.assert_awaited_once_with("novel_domain")


@pytest.mark.parametrize("parent_exists", [False, True])
@pytest.mark.asyncio
async def test_action_log_excludes_untrusted_missing_or_dynamic_parent_slug(parent_exists: bool) -> None:
    domain_service = InMemoryDomainService()
    await domain_service.seed_defaults()
    source_sentinel = "private-parent-source-secret"
    if parent_exists:
        await domain_service.create_domain(
            slug=source_sentinel,
            name="Dynamic parent",
            description="A dynamic parent",
            created_by="agent",
        )
    permissions = InMemoryPermissionService(bootstrap_admin_id="admin")
    classifier = AsyncMock()
    classifier.classify.return_value = ClassificationResult(
        proposed_domain=ProposedDomain(
            slug="safe_child",
            name="Safe child",
            description="A safe child domain",
            reasoning="test",
            parent_slug=source_sentinel,
        )
    )
    schema_mgr = AsyncMock()
    schema_mgr.create_graph.side_effect = lambda agent_id, purpose, is_shared=False: f"ncx_shared__{purpose}"
    router = DomainRouter(
        domain_service=domain_service,
        classifier=classifier,
        schema_mgr=schema_mgr,
        permissions=permissions,
    )
    records: list[dict] = []
    sink_id = logger.add(lambda message: records.append(message.record), level="INFO")
    try:
        results = await router.route_and_extract("agent", 1, "child text")
    finally:
        logger.remove(sink_id)

    action_records = [record for record in records if record["extra"].get("action_log")]
    assert [result.domain_slug for result in results] == ["safe_child"]
    assert action_records
    assert all(source_sentinel not in str(record["extra"]) for record in action_records)
    assert any(
        record["message"] == "domain_schema_permission_granted" and not record["extra"].get("action_log")
        for record in records
    )
    provisioned_record = next(record for record in action_records if record["message"] == "domain_provisioned")
    assert provisioned_record["extra"]["slug"] == "safe_child"
    if not parent_exists:
        parent_record = next(
            record for record in action_records if record["message"] == "domain_provision_parent_not_found"
        )
        assert parent_record["extra"]["reason"] == "parent_not_found_treating_as_root"


@pytest.mark.asyncio
async def test_dynamic_parent_is_preserved_for_existing_hierarchy_semantics() -> None:
    domain_service = InMemoryDomainService()
    await domain_service.seed_defaults()
    dynamic_parent = await domain_service.create_domain(
        slug="dynamic_parent",
        name="Dynamic parent",
        description="A model-created parent",
        created_by="agent",
    )
    permissions = InMemoryPermissionService(bootstrap_admin_id="admin")
    classifier = AsyncMock()
    classifier.classify.return_value = ClassificationResult(
        proposed_domain=ProposedDomain(
            slug="dynamic_child",
            name="Dynamic child",
            description="A model-created child",
            reasoning="test",
            parent_slug=dynamic_parent.slug,
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

    results = await router.route_and_extract("agent", 1, "novel text")
    child = await domain_service.get_domain("dynamic_child")

    assert len(results) == 1
    assert child is not None
    assert child.parent_id == dynamic_parent.id
    seed_generator.resolve_seed.assert_awaited_once_with("dynamic_child")
