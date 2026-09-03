"""Runtime invariants used to bound model work in routed extraction."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from neocortex.domains.memory_service import InMemoryDomainService
from neocortex.domains.models import ClassificationResult, DomainClassification, ProposedDomain
from neocortex.domains.router import DomainRouter
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
            [DomainClassification(domain_slug="technical_knowledge", confidence=0.9, reasoning="match")] * 100
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

    assert [result.domain_slug for result in results] == ["technical_knowledge"]


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
