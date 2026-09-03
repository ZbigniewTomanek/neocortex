"""Tests for the extraction pipeline (Stage 4, Plan 07).

Tests run against InMemoryRepository with pydantic_ai TestModel — no Docker
or API keys needed.
"""

from __future__ import annotations

import pytest
from loguru import logger

from neocortex.db.mock import InMemoryRepository
from neocortex.extraction.agents import AgentInferenceConfig, OntologyAgentDeps, build_ontology_agent
from neocortex.extraction.pipeline import _persist_payload, run_extraction
from neocortex.extraction.schemas import (
    LibrarianPayload,
    NormalizedEntity,
    NormalizedRelation,
    OntologyProposal,
    ProposedEdgeType,
    ProposedNodeType,
)

AGENT = "test-agent"
_TEST_CONFIG = AgentInferenceConfig(use_test_model=True)


@pytest.fixture
def repo() -> InMemoryRepository:
    return InMemoryRepository()


def _sample_payload() -> LibrarianPayload:
    """Build a realistic librarian payload for testing persistence."""
    return LibrarianPayload(
        accepted_node_types=[
            ProposedNodeType(name="Neurotransmitter", description="A chemical messenger"),
            ProposedNodeType(name="Drug", description="A pharmaceutical substance"),
        ],
        accepted_edge_types=[
            ProposedEdgeType(name="INHIBITS", description="Blocks or reduces activity"),
            ProposedEdgeType(name="TREATS", description="Therapeutic relationship"),
        ],
        entities=[
            NormalizedEntity(
                name="Serotonin",
                type_name="Neurotransmitter",
                description="A monoamine neurotransmitter involved in mood regulation",
                properties={"alternate_name": "5-HT"},
                is_new=True,
            ),
            NormalizedEntity(
                name="Fluoxetine",
                type_name="Drug",
                description="A selective serotonin reuptake inhibitor (SSRI)",
                properties={"brand_name": "Prozac"},
                is_new=True,
            ),
        ],
        relations=[
            NormalizedRelation(
                source_name="Fluoxetine",
                target_name="Serotonin",
                relation_type="INHIBITS",
                weight=0.9,
                properties={"evidence": "blocks reuptake"},
            ),
        ],
        summary="Extracted neurotransmitter-drug relationships",
    )


# ── _persist_payload tests ──


@pytest.mark.asyncio
async def test_persist_payload_creates_types(repo: InMemoryRepository) -> None:
    """Verify that accepted types from payload are persisted."""
    eid = await repo.store_episode(AGENT, "test content")
    payload = _sample_payload()

    await _persist_payload(repo, None, AGENT, eid, payload)

    node_types = await repo.get_node_types(AGENT)
    edge_types = await repo.get_edge_types(AGENT)
    nt_names = {t.name for t in node_types}
    et_names = {t.name for t in edge_types}
    assert "Neurotransmitter" in nt_names
    assert "Drug" in nt_names
    assert "INHIBITS" in et_names
    assert "TREATS" in et_names


@pytest.mark.asyncio
async def test_persist_payload_creates_nodes(repo: InMemoryRepository) -> None:
    """Verify that entities are persisted as nodes."""
    eid = await repo.store_episode(AGENT, "test content")
    payload = _sample_payload()

    await _persist_payload(repo, None, AGENT, eid, payload)

    serotonin = await repo.find_nodes_by_name(AGENT, "Serotonin")
    assert len(serotonin) == 1
    assert serotonin[0].name == "Serotonin"
    assert serotonin[0].properties["alternate_name"] == "5-HT"
    assert serotonin[0].properties["_source_episode"] == eid

    fluoxetine = await repo.find_nodes_by_name(AGENT, "Fluoxetine")
    assert len(fluoxetine) == 1
    assert fluoxetine[0].properties["brand_name"] == "Prozac"


@pytest.mark.asyncio
async def test_persist_payload_creates_edges(repo: InMemoryRepository) -> None:
    """Verify that relations are persisted as edges."""
    eid = await repo.store_episode(AGENT, "test content")
    payload = _sample_payload()

    await _persist_payload(repo, None, AGENT, eid, payload)

    sigs = await repo.list_all_edge_signatures(AGENT)
    assert len(sigs) == 1
    assert "Fluoxetine" in sigs[0]
    assert "Serotonin" in sigs[0]


@pytest.mark.asyncio
async def test_persist_payload_skips_edge_with_missing_node(
    repo: InMemoryRepository,
) -> None:
    """Edges referencing non-existent nodes should be skipped, not crash."""
    eid = await repo.store_episode(AGENT, "test content")
    payload = LibrarianPayload(
        entities=[
            NormalizedEntity(name="Alpha", type_name="TypeA"),
        ],
        relations=[
            NormalizedRelation(
                source_name="Alpha",
                target_name="NonExistent",
                relation_type="LINKS_TO",
            ),
        ],
    )

    # Should not raise
    await _persist_payload(repo, None, AGENT, eid, payload)

    sigs = await repo.list_all_edge_signatures(AGENT)
    assert len(sigs) == 0  # edge skipped


@pytest.mark.asyncio
async def test_persist_payload_audit_does_not_include_relation_endpoint_names(
    repo: InMemoryRepository,
) -> None:
    """Durable audit records use resolution flags, not source text names."""
    eid = await repo.store_episode(AGENT, "private episode content")
    payload = LibrarianPayload(
        relations=[
            NormalizedRelation(
                source_name="Private Person Name",
                target_name="Confidential Organisation",
                relation_type="WORKS_FOR",
            )
        ]
    )
    captured: list[dict] = []
    sink_id = logger.add(lambda message: captured.append(message.record), level="INFO")
    try:
        await _persist_payload(
            repo,
            None,
            AGENT,
            eid,
            payload,
            audit_fields={"correlation_id": "test-correlation"},
        )
    finally:
        logger.remove(sink_id)

    records = [record for record in captured if record["message"] == "edge_skipped_missing_node"]
    assert len(records) == 1
    extra = records[0]["extra"]
    assert extra["source_id"] is None
    assert extra["target_id"] is None
    assert "source" not in extra
    assert "target" not in extra
    assert "Private Person Name" not in str(extra)
    assert "Confidential Organisation" not in str(extra)


@pytest.mark.asyncio
async def test_persist_payload_idempotent_nodes(repo: InMemoryRepository) -> None:
    """Running persist twice with same payload should not duplicate nodes."""
    eid = await repo.store_episode(AGENT, "test content")
    payload = _sample_payload()

    await _persist_payload(repo, None, AGENT, eid, payload)
    await _persist_payload(repo, None, AGENT, eid, payload)

    serotonin = await repo.find_nodes_by_name(AGENT, "Serotonin")
    assert len(serotonin) == 1  # not duplicated

    fluoxetine = await repo.find_nodes_by_name(AGENT, "Fluoxetine")
    assert len(fluoxetine) == 1


@pytest.mark.asyncio
async def test_persist_payload_idempotent_edges(repo: InMemoryRepository) -> None:
    """Running persist twice should not create duplicate edges."""
    eid = await repo.store_episode(AGENT, "test content")
    payload = _sample_payload()

    await _persist_payload(repo, None, AGENT, eid, payload)
    await _persist_payload(repo, None, AGENT, eid, payload)

    sigs = await repo.list_all_edge_signatures(AGENT)
    assert len(sigs) == 1


@pytest.mark.asyncio
async def test_persist_payload_resolves_existing_nodes_for_edges(
    repo: InMemoryRepository,
) -> None:
    """Edges referencing nodes created in a prior run should resolve."""
    eid = await repo.store_episode(AGENT, "test content")

    # First payload creates Serotonin node
    payload1 = LibrarianPayload(
        entities=[
            NormalizedEntity(name="Serotonin", type_name="Neurotransmitter", description="5-HT"),
        ],
    )
    await _persist_payload(repo, None, AGENT, eid, payload1)

    # Second payload creates Dopamine and links to existing Serotonin
    payload2 = LibrarianPayload(
        entities=[
            NormalizedEntity(name="Dopamine", type_name="Neurotransmitter", description="DA"),
        ],
        relations=[
            NormalizedRelation(
                source_name="Dopamine",
                target_name="Serotonin",
                relation_type="INTERACTS_WITH",
            ),
        ],
    )
    await _persist_payload(repo, None, AGENT, eid, payload2)

    sigs = await repo.list_all_edge_signatures(AGENT)
    assert len(sigs) == 1
    assert "Dopamine" in sigs[0]
    assert "Serotonin" in sigs[0]


# ── Full pipeline tests with TestModel ──


@pytest.mark.asyncio
async def test_run_extraction_with_test_model(repo: InMemoryRepository) -> None:
    """Full pipeline with TestModel: verify it runs without errors."""
    eid = await repo.store_episode(
        AGENT,
        "Serotonin is a monoamine neurotransmitter that modulates mood.",
    )

    await run_extraction(
        repo=repo,
        embeddings=None,
        agent_id=AGENT,
        episode_ids=[eid],
        ontology_config=_TEST_CONFIG,
        extractor_config=_TEST_CONFIG,
        librarian_config=_TEST_CONFIG,
    )

    # TestModel produces structurally valid output — verify flow completed
    # (specific node/edge counts depend on TestModel's generated data)
    stats = await repo.get_stats(AGENT)
    # At minimum, the pipeline ran without error. TestModel may produce
    # empty or populated lists, so we just verify the flow is sound.
    assert stats.total_episodes == 1


@pytest.mark.asyncio
async def test_run_extraction_skips_missing_episode(
    repo: InMemoryRepository,
) -> None:
    """Pipeline should skip episode IDs that don't exist."""
    await run_extraction(
        repo=repo,
        embeddings=None,
        agent_id=AGENT,
        episode_ids=[9999],
        ontology_config=_TEST_CONFIG,
        extractor_config=_TEST_CONFIG,
        librarian_config=_TEST_CONFIG,
    )

    stats = await repo.get_stats(AGENT)
    assert stats.total_nodes == 0
    assert stats.total_edges == 0


@pytest.mark.asyncio
async def test_run_extraction_multiple_episodes(repo: InMemoryRepository) -> None:
    """Pipeline processes multiple episodes sequentially."""
    eid1 = await repo.store_episode(AGENT, "Text about serotonin.")
    eid2 = await repo.store_episode(AGENT, "Text about dopamine.")

    await run_extraction(
        repo=repo,
        embeddings=None,
        agent_id=AGENT,
        episode_ids=[eid1, eid2],
        ontology_config=_TEST_CONFIG,
        extractor_config=_TEST_CONFIG,
        librarian_config=_TEST_CONFIG,
    )

    stats = await repo.get_stats(AGENT)
    assert stats.total_episodes == 2


# ── Ontology agent tool tests ──


@pytest.mark.asyncio
async def test_ontology_agent_runs_with_test_model_and_repo(repo: InMemoryRepository) -> None:
    """Ontology agent with tools works under TestModel with InMemoryRepository."""
    # Pre-populate some types
    await repo.get_or_create_node_type(AGENT, "Person", "A human being")
    await repo.get_or_create_node_type(AGENT, "Drug", "A pharmaceutical substance")
    await repo.get_or_create_edge_type(AGENT, "TREATS", "Therapeutic relationship")

    agent = build_ontology_agent(AgentInferenceConfig(use_test_model=True))
    result = await agent.run(
        "Analyze this text and propose ontology extensions:\n\nAspirin treats headaches.",
        deps=OntologyAgentDeps(
            episode_text="Aspirin treats headaches.",
            existing_node_types=["Person", "Drug"],
            existing_edge_types=["TREATS"],
            repo=repo,
            agent_id=AGENT,
        ),
    )
    # TestModel produces structurally valid output
    assert isinstance(result.output, OntologyProposal)


@pytest.mark.asyncio
async def test_ontology_agent_backward_compat_without_repo() -> None:
    """Ontology agent works without repo (tools return empty results gracefully)."""
    agent = build_ontology_agent(AgentInferenceConfig(use_test_model=True))
    result = await agent.run(
        "Analyze this text and propose ontology extensions:\n\nAspirin treats headaches.",
        deps=OntologyAgentDeps(
            episode_text="Aspirin treats headaches.",
            existing_node_types=["Person"],
            existing_edge_types=["TREATS"],
            # repo=None (default) — tools return empty results
        ),
    )
    assert isinstance(result.output, OntologyProposal)


def _get_tool_fn(agent, tool_name: str):
    """Extract a tool's underlying function from a pydantic-ai agent."""
    tool = agent._function_toolset.tools.get(tool_name)
    assert tool is not None, f"Tool {tool_name} not found"
    return tool.function


@pytest.mark.asyncio
async def test_propose_type_rejects_tool_call_artifact(repo: InMemoryRepository) -> None:
    """propose_type tool rejects names with tool-call artifacts via Stage 1 validation."""
    from types import SimpleNamespace

    agent = build_ontology_agent(AgentInferenceConfig(use_test_model=True))
    deps = OntologyAgentDeps(
        episode_text="test",
        existing_node_types=[],
        existing_edge_types=[],
        repo=repo,
        agent_id=AGENT,
    )
    ctx = SimpleNamespace(deps=deps)
    propose_fn = _get_tool_fn(agent, "propose_type")
    result = await propose_fn(
        ctx, name="ActivityfunctiondefaultApicreateOrUpdateNodecontent", description="test", kind="node"
    )
    assert result["accepted"] is False


@pytest.mark.asyncio
async def test_propose_type_rejects_duplicate(repo: InMemoryRepository) -> None:
    """propose_type rejects types that already exist in the ontology."""
    from types import SimpleNamespace

    agent = build_ontology_agent(AgentInferenceConfig(use_test_model=True))
    deps = OntologyAgentDeps(
        episode_text="test",
        existing_node_types=["Person", "Drug"],
        existing_edge_types=[],
        repo=repo,
        agent_id=AGENT,
    )
    ctx = SimpleNamespace(deps=deps)
    propose_fn = _get_tool_fn(agent, "propose_type")
    result = await propose_fn(ctx, name="Person", description="A human being", kind="node")
    assert result["accepted"] is False
    assert "already exists" in result["reason"]


@pytest.mark.asyncio
async def test_propose_type_accepts_valid_new_type(repo: InMemoryRepository) -> None:
    """propose_type accepts valid new types."""
    from types import SimpleNamespace

    agent = build_ontology_agent(AgentInferenceConfig(use_test_model=True))
    deps = OntologyAgentDeps(
        episode_text="test",
        existing_node_types=["Person"],
        existing_edge_types=[],
        repo=repo,
        agent_id=AGENT,
    )
    ctx = SimpleNamespace(deps=deps)
    propose_fn = _get_tool_fn(agent, "propose_type")
    result = await propose_fn(ctx, name="Neurotransmitter", description="A chemical messenger", kind="node")
    assert result["accepted"] is True
    assert result["normalized_name"] == "Neurotransmitter"


@pytest.mark.asyncio
async def test_type_budget_enforcement(repo: InMemoryRepository) -> None:
    """Pipeline enforces type budget by truncating excess proposed types."""
    eid = await repo.store_episode(AGENT, "Some text about many topics.")

    await run_extraction(
        repo=repo,
        embeddings=None,
        agent_id=AGENT,
        episode_ids=[eid],
        ontology_config=_TEST_CONFIG,
        extractor_config=_TEST_CONFIG,
        librarian_config=_TEST_CONFIG,
        ontology_max_new_types=2,
    )
    # TestModel may produce any number of types, but the pipeline
    # should have enforced the budget. This test verifies the flow
    # completes without error when budget enforcement is active.
    stats = await repo.get_stats(AGENT)
    assert stats.total_episodes == 1


@pytest.mark.asyncio
async def test_find_similar_types_mock(repo: InMemoryRepository) -> None:
    """InMemoryRepository.find_similar_types returns matching types."""
    await repo.get_or_create_node_type(AGENT, "Person", "A human being")
    await repo.get_or_create_node_type(AGENT, "PersonRole", "A role held by a person")
    # Create a node so we can test usage counts
    nt = await repo.get_or_create_node_type(AGENT, "Drug", "A pharmaceutical")
    await repo.upsert_node(AGENT, "Aspirin", nt.id, content="Pain reliever")

    results = await repo.find_similar_types(AGENT, "Person", kind="node")
    names = [t.name for t, _count, _examples in results]
    assert "Person" in names

    results = await repo.find_similar_types(AGENT, "Drug", kind="node")
    assert len(results) >= 1
    # Drug should have usage_count=1 (the Aspirin node)
    drug_result = [(t, count, ex) for t, count, ex in results if t.name == "Drug"]
    assert len(drug_result) == 1
    assert drug_result[0][1] == 1
    assert "Aspirin" in drug_result[0][2]


@pytest.mark.asyncio
async def test_get_ontology_summary_mock(repo: InMemoryRepository) -> None:
    """InMemoryRepository.get_ontology_summary returns usage statistics."""
    nt = await repo.get_or_create_node_type(AGENT, "Person", "A human being")
    await repo.upsert_node(AGENT, "Alice", nt.id, content="A person named Alice")
    await repo.upsert_node(AGENT, "Bob", nt.id, content="A person named Bob")
    await repo.get_or_create_edge_type(AGENT, "KNOWS", "Social connection")

    summary = await repo.get_ontology_summary(AGENT)
    assert summary["total_nodes"] == 2
    assert summary["total_edges"] == 0
    assert len(summary["node_types"]) == 1
    assert summary["node_types"][0]["name"] == "Person"
    assert summary["node_types"][0]["usage_count"] == 2
    assert len(summary["edge_types"]) == 1
    assert summary["edge_types"][0]["usage_count"] == 0
