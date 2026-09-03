"""Runtime invariants used to bound model work in routed extraction."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

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


@pytest.mark.asyncio
async def test_dynamic_parent_is_flattened_so_seed_resolution_cannot_recurse() -> None:
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
    assert child.parent_id is None
    seed_generator.resolve_seed.assert_awaited_once_with("dynamic_child")
