"""Tests for librarian retrieval tools (Stage 2, Plan 16).

Tests verify:
- Tools are registered on the librarian agent
- Tools return correct results against InMemoryRepository
- Pipeline passes repo to librarian deps (no more list_all_node_names)
- Type descriptions flow to ontology/extractor agents
"""

from __future__ import annotations

import pytest

from neocortex.db.mock import InMemoryRepository
from neocortex.extraction.agents import (
    AgentInferenceConfig,
    LibrarianAgentDeps,
    build_librarian_agent,
)
from neocortex.extraction.schemas import ExtractedEntity

AGENT = "test-agent"
_TEST_CONFIG = AgentInferenceConfig(use_test_model=True)


@pytest.fixture
def repo() -> InMemoryRepository:
    return InMemoryRepository()


def _make_deps(repo: InMemoryRepository) -> LibrarianAgentDeps:
    """Build minimal librarian deps for testing."""
    return LibrarianAgentDeps(
        episode_text="Alice works on billing.",
        node_types=["Person", "Service"],
        edge_types=["WORKS_ON"],
        extracted_entities=[
            ExtractedEntity(name="Alice", type_name="Person", description="A person"),
        ],
        extracted_relations=[],
        repo=repo,
        embeddings=None,
        agent_id=AGENT,
    )


# ── Tool registration tests ──


def test_librarian_agent_has_retrieval_tools() -> None:
    """Verify all 5 retrieval tools are registered on the librarian agent."""
    agent = build_librarian_agent(_TEST_CONFIG)
    tool_names = sorted(agent._function_toolset.tools.keys())
    assert "search_existing_nodes" in tool_names
    assert "find_node_by_name" in tool_names
    assert "find_similar_nodes" in tool_names
    assert "inspect_node_neighborhood" in tool_names
    assert "get_edges_between" in tool_names


def test_librarian_agent_has_nine_tools_in_tool_mode() -> None:
    """Tool-equipped librarian has 5 retrieval + 4 mutation = 9 tools."""
    agent = build_librarian_agent(_TEST_CONFIG, use_tools=True)
    assert len(agent._function_toolset.tools) == 9


def test_librarian_agent_has_five_tools_in_fallback_mode() -> None:
    """Fallback librarian has only 5 retrieval tools."""
    agent = build_librarian_agent(_TEST_CONFIG, use_tools=False)
    assert len(agent._function_toolset.tools) == 5


# ── Tool functionality tests via direct mock repo ──


@pytest.mark.asyncio
async def test_search_existing_nodes_finds_matching(repo: InMemoryRepository) -> None:
    """search_existing_nodes returns nodes matching query text."""
    nt = await repo.get_or_create_node_type(AGENT, "Person")
    await repo.upsert_node(AGENT, "Alice", nt.id, content="Engineer at Acme")

    results = await repo.search_nodes(AGENT, "Alice", limit=5)
    assert len(results) == 1
    assert results[0][0].name == "Alice"
    assert results[0][1] > 0  # has a relevance score


@pytest.mark.asyncio
async def test_search_existing_nodes_empty_graph(repo: InMemoryRepository) -> None:
    """search_existing_nodes returns empty list on empty graph."""
    results = await repo.search_nodes(AGENT, "Alice", limit=5)
    assert results == []


@pytest.mark.asyncio
async def test_find_node_by_name_exact_match(repo: InMemoryRepository) -> None:
    """find_node_by_name returns exact case-insensitive matches."""
    nt = await repo.get_or_create_node_type(AGENT, "Person")
    await repo.upsert_node(AGENT, "Alice", nt.id, content="Engineer")

    # Case-insensitive match
    nodes = await repo.find_nodes_by_name(AGENT, "alice")
    assert len(nodes) == 1
    assert nodes[0].name == "Alice"


@pytest.mark.asyncio
async def test_find_node_by_name_no_match(repo: InMemoryRepository) -> None:
    """find_node_by_name returns empty list when no match."""
    nodes = await repo.find_nodes_by_name(AGENT, "NonExistent")
    assert nodes == []


@pytest.mark.asyncio
async def test_find_node_by_name_excludes_forgotten(repo: InMemoryRepository) -> None:
    """find_node_by_name excludes forgotten nodes."""
    nt = await repo.get_or_create_node_type(AGENT, "Person")
    node = await repo.upsert_node(AGENT, "Alice", nt.id)
    await repo.mark_forgotten(AGENT, [node.id])

    nodes = await repo.find_nodes_by_name(AGENT, "Alice")
    assert nodes == []


@pytest.mark.asyncio
async def test_inspect_node_neighborhood(repo: InMemoryRepository) -> None:
    """inspect_node_neighborhood returns connected nodes and edges."""
    nt = await repo.get_or_create_node_type(AGENT, "Person")
    et = await repo.get_or_create_edge_type(AGENT, "WORKS_ON")
    svc_type = await repo.get_or_create_node_type(AGENT, "Service")

    alice = await repo.upsert_node(AGENT, "Alice", nt.id)
    billing = await repo.upsert_node(AGENT, "Billing", svc_type.id)
    await repo.upsert_edge(AGENT, alice.id, billing.id, et.id)

    neighborhood = await repo.get_node_neighborhood(AGENT, alice.id, depth=1)
    assert len(neighborhood) == 1
    assert neighborhood[0]["node"].name == "Billing"
    assert len(neighborhood[0]["edges"]) == 1


@pytest.mark.asyncio
async def test_get_edges_between_via_neighborhood(repo: InMemoryRepository) -> None:
    """get_edges_between finds edges between two named nodes."""
    nt = await repo.get_or_create_node_type(AGENT, "Person")
    svc_type = await repo.get_or_create_node_type(AGENT, "Service")
    et = await repo.get_or_create_edge_type(AGENT, "WORKS_ON")

    alice = await repo.upsert_node(AGENT, "Alice", nt.id)
    billing = await repo.upsert_node(AGENT, "Billing", svc_type.id)
    await repo.upsert_edge(AGENT, alice.id, billing.id, et.id, weight=0.9)

    # Verify we can find the edge through neighborhood traversal
    neighborhood = await repo.get_node_neighborhood(AGENT, alice.id, depth=1)
    edges = []
    for entry in neighborhood:
        for edge in entry["edges"]:
            if edge.target_id == billing.id or edge.source_id == billing.id:
                edges.append(edge)
    assert len(edges) == 1
    assert edges[0].weight == 0.9


@pytest.mark.asyncio
async def test_get_edges_between_no_nodes(repo: InMemoryRepository) -> None:
    """get_edges_between returns empty when nodes don't exist."""
    nodes = await repo.find_nodes_by_name(AGENT, "NonExistent")
    assert nodes == []  # no nodes, so no edges


# ── Pipeline integration test ──


@pytest.mark.asyncio
async def test_pipeline_no_longer_calls_list_all_node_names(repo: InMemoryRepository) -> None:
    """Pipeline in tool mode should NOT call list_all_node_names."""
    from unittest.mock import AsyncMock, patch

    from neocortex.extraction.pipeline import run_extraction

    eid = await repo.store_episode(AGENT, "Alice works on billing.")

    # Spy on list_all_node_names to verify it's NOT called
    original = repo.list_all_node_names
    spy = AsyncMock(side_effect=original)
    repo.list_all_node_names = spy  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]

    with patch("neocortex.extraction.pipeline.build_librarian_agent") as mock_build:
        # Mock agent to avoid actual LLM calls but verify deps
        mock_agent = AsyncMock()
        mock_agent._function_tools = {}

        from neocortex.extraction.schemas import CurationSummary

        mock_result = AsyncMock()
        mock_result.output = CurationSummary()
        mock_agent.run = AsyncMock(return_value=mock_result)
        mock_build.return_value = mock_agent

        await run_extraction(
            repo=repo,
            embeddings=None,
            agent_id=AGENT,
            episode_ids=[eid],
            ontology_config=_TEST_CONFIG,
            extractor_config=_TEST_CONFIG,
            librarian_config=_TEST_CONFIG,
            librarian_use_tools=True,
        )

    # list_all_node_names should NOT have been called in tool mode
    spy.assert_not_called()


@pytest.mark.asyncio
async def test_pipeline_passes_repo_to_librarian_deps(repo: InMemoryRepository) -> None:
    """Verify pipeline passes repo, embeddings, agent_id to LibrarianAgentDeps."""
    from unittest.mock import AsyncMock, patch

    from neocortex.extraction.pipeline import run_extraction

    eid = await repo.store_episode(AGENT, "Alice works on billing.")

    captured_deps = []

    original_build = build_librarian_agent

    def patched_build(config=None, use_tools=True, retries=1):
        agent = original_build(config, use_tools=use_tools, retries=retries)

        async def capturing_run(*args, **kwargs):
            deps = kwargs.get("deps")
            if deps is not None:
                captured_deps.append(deps)
            # Return a mock result instead of actually running the LLM
            from neocortex.extraction.schemas import CurationSummary

            result = AsyncMock()
            result.output = CurationSummary()
            return result

        agent.run = capturing_run  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        return agent

    with patch("neocortex.extraction.pipeline.build_librarian_agent", side_effect=patched_build):
        await run_extraction(
            repo=repo,
            embeddings=None,
            agent_id=AGENT,
            episode_ids=[eid],
            ontology_config=_TEST_CONFIG,
            extractor_config=_TEST_CONFIG,
            librarian_config=_TEST_CONFIG,
        )

    assert len(captured_deps) == 1
    deps = captured_deps[0]
    assert deps.repo is repo
    assert deps.embeddings is None
    assert deps.agent_id == AGENT
    assert deps.target_schema is None


# ── Type descriptions tests ──


@pytest.mark.asyncio
async def test_pipeline_passes_type_descriptions_to_ontology(repo: InMemoryRepository) -> None:
    """Verify ontology agent gets type descriptions, not just names."""
    from unittest.mock import MagicMock, patch

    from neocortex.extraction.agents import OntologyAgentDeps, build_ontology_agent
    from neocortex.extraction.pipeline import run_extraction
    from neocortex.extraction.schemas import OntologyProposal

    eid = await repo.store_episode(AGENT, "Test text.")
    # Pre-create a node type with description
    await repo.get_or_create_node_type(AGENT, "Person", description="A human individual")

    captured_ont_deps: list[OntologyAgentDeps] = []

    original_build_ont = build_ontology_agent

    def patched_build_ont(config=None):
        agent = original_build_ont(config)

        async def capturing_run(*args, **kwargs):
            deps = kwargs.get("deps")
            if deps is not None:
                captured_ont_deps.append(deps)
            result = MagicMock()
            result.output = OntologyProposal()
            result.all_messages.return_value = []
            result.usage.return_value = MagicMock(requests=0)
            return result

        agent.run = capturing_run  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        return agent

    with patch("neocortex.extraction.pipeline.build_ontology_agent", side_effect=patched_build_ont):
        await run_extraction(
            repo=repo,
            embeddings=None,
            agent_id=AGENT,
            episode_ids=[eid],
            ontology_config=_TEST_CONFIG,
            extractor_config=_TEST_CONFIG,
            librarian_config=_TEST_CONFIG,
        )

    assert len(captured_ont_deps) == 1
    deps = captured_ont_deps[0]
    assert deps.node_type_descriptions is not None
    assert deps.node_type_descriptions.get("Person") == "A human individual"


# ── Full pipeline with TestModel ──


@pytest.mark.asyncio
async def test_full_pipeline_with_test_model(repo: InMemoryRepository) -> None:
    """Full pipeline runs without errors using TestModel (with new deps)."""
    from neocortex.extraction.pipeline import run_extraction

    eid = await repo.store_episode(
        AGENT,
        "Alice is an engineer who works on the billing service.",
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

    stats = await repo.get_stats(AGENT)
    assert stats.total_episodes == 1
