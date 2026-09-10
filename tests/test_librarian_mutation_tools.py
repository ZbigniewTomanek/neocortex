"""Tests for librarian mutation tools and tool-driven curation (Stage 3, Plan 16).

Tests verify:
- 4 mutation tools are registered on the tool-equipped librarian agent
- Mutation tools work against InMemoryRepository
- CurationSummary validator computes counts from actions
- cleanup_partial_curation removes tagged nodes/edges
- Pipeline uses tool-driven curation by default
- Pipeline falls back to _persist_payload when librarian_use_tools=False
- delete_edge works in mock repo
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from loguru import logger
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.test import TestModel
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits

from neocortex.db.mock import InMemoryRepository
from neocortex.extraction.agents import (
    DEFAULT_LIBRARIAN_RETRIES,
    AgentInferenceConfig,
    CurationActionTracker,
    LibrarianAgentDeps,
    LibrarianBudgetConfig,
    LibrarianTrajectoryLimitExceeded,
    LibrarianTrajectoryTracker,
    build_librarian_agent,
    build_librarian_relation_items,
)
from neocortex.extraction.schemas import (
    CurationAction,
    CurationSummary,
    EntityDecision,
    EntityDetailRequest,
    ExtractedEntity,
    ExtractedRelation,
    LibrarianPayload,
    RelationDecision,
)
from neocortex.model_factory import LocalEndpoint

AGENT = "test-agent"
_TEST_CONFIG = AgentInferenceConfig(use_test_model=True)


def test_local_librarian_settings_disable_parallel_calls_without_changing_hosted() -> None:
    """Only a local librarian receives the serial tool-call mitigation."""
    from neocortex.extraction.pipeline import _librarian_model_settings

    endpoint = LocalEndpoint(
        base_url="http://127.0.0.1:24000/v1",
        api_key_env="LITELLM_API_KEY",
        temperature=0.6,
        top_p=0.95,
        temperature_nothink=0.3,
        top_p_nothink=0.9,
        timeout_s=600.0,
    )
    local = AgentInferenceConfig(
        model_name="local:qwen3.8-flash-next",
        thinking_effort="low",
        local_endpoint=endpoint,
    )
    hosted = AgentInferenceConfig(model_name="openai-responses:gpt-5.4-mini", thinking_effort="low")

    local_settings = _librarian_model_settings(local)
    assert local_settings is not None
    assert local_settings["parallel_tool_calls"] is False
    assert _librarian_model_settings(hosted) == hosted.model_settings


def test_bounded_prompt_states_host_identity_and_recoverable_decision_contracts() -> None:
    agent = build_librarian_agent(_TEST_CONFIG, profile="qwen_bounded")
    prompt = "\n".join(agent._system_prompts)

    assert "host derives any resolver-selected node identity" in prompt
    assert "Use unresolved only when an endpoint is missing or ambiguous" in prompt
    assert "Process entity micro-batches of at most 8 indices end to end" in prompt
    assert "allowed_decisions field is code-owned" in prompt
    assert "A rejected decision stays pending" in prompt


def test_bounded_entity_decision_schema_has_no_model_supplied_identity() -> None:
    assert "selected_node_id" not in EntityDecision.model_json_schema()["properties"]
    with pytest.raises(ValueError):
        EntityDecision.model_validate({"entity_index": 0, "decision": "unchanged", "selected_node_id": 7})


@pytest.fixture
def repo() -> InMemoryRepository:
    return InMemoryRepository()


class _ToolBudgetThenValidationRetryModel(TestModel):
    """Emit one retrieval call, then an invalid and valid curation result."""

    def __init__(self) -> None:
        super().__init__(call_tools=[])
        self.requests = 0

    def _request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        del messages, model_settings
        self.requests += 1
        if self.requests == 1:
            search_tool = next(
                tool for tool in model_request_parameters.function_tools if tool.name == "search_existing_nodes"
            )
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        search_tool.name,
                        {"query": "Alice", "limit": 1},
                        tool_call_id="search-call",
                    )
                ],
                model_name="scripted-retry-model",
            )

        output_tool = model_request_parameters.output_tools[0]
        # Force PydanticAI to spend its configured output-validation retry.
        output_args: dict[str, Any] = (
            {"actions": "not-a-list", "summary": ""} if self.requests == 2 else {"actions": [], "summary": ""}
        )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    output_tool.name,
                    output_args,
                    tool_call_id=f"output-call-{self.requests}",
                )
            ],
            model_name="scripted-retry-model",
        )


class _TwoCallBatchModel(TestModel):
    """Return two retrieval calls in one response to test pre-execution limits."""

    def __init__(self) -> None:
        super().__init__(call_tools=[])
        self.requests = 0

    def _request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        del messages, model_settings
        self.requests += 1
        search_tool = next(
            tool for tool in model_request_parameters.function_tools if tool.name == "search_existing_nodes"
        )
        return ModelResponse(
            parts=[
                ToolCallPart(search_tool.name, {"query": "one", "limit": 1}, tool_call_id="search-one"),
                ToolCallPart(search_tool.name, {"query": "two", "limit": 1}, tool_call_id="search-two"),
            ],
            model_name="scripted-two-call-model",
        )


def _make_deps(
    repo: InMemoryRepository,
    episode_id: int | None = None,
) -> LibrarianAgentDeps:
    """Build minimal librarian deps for testing."""
    return LibrarianAgentDeps(
        episode_text="Alice works on billing.",
        node_types=["Person", "Service"],
        edge_types=["WORKS_ON"],
        extracted_entities=[
            ExtractedEntity(name="Alice", type_name="Person", description="A person"),
        ],
        extracted_relations=[
            ExtractedRelation(
                source_name="Alice",
                target_name="Billing",
                relation_type="WORKS_ON",
            ),
        ],
        repo=repo,
        embeddings=None,
        agent_id=AGENT,
        episode_id=episode_id,
    )


# ── Tool registration tests ──


def test_tool_equipped_librarian_has_8_tools() -> None:
    """Tool-equipped librarian has 4 retrieval + 4 mutation = 8 tools."""
    agent = build_librarian_agent(_TEST_CONFIG, use_tools=True)
    tool_names = sorted(agent._function_toolset.tools.keys())
    assert "create_or_update_node" in tool_names
    assert "create_or_update_edge" in tool_names
    assert "archive_node" in tool_names
    assert "remove_edge" in tool_names
    assert "search_existing_nodes" in tool_names
    assert "find_node_by_name" in tool_names
    assert "inspect_node_neighborhood" in tool_names
    assert "get_edges_between" in tool_names
    assert "find_similar_nodes" in tool_names
    assert len(tool_names) == 9


def test_fallback_librarian_has_5_tools() -> None:
    """Non-tool librarian has only 5 retrieval tools, no mutation tools."""
    agent = build_librarian_agent(_TEST_CONFIG, use_tools=False)
    tool_names = sorted(agent._function_toolset.tools.keys())
    assert "create_or_update_node" not in tool_names
    assert "create_or_update_edge" not in tool_names
    assert "archive_node" not in tool_names
    assert "remove_edge" not in tool_names
    assert len(tool_names) == 5


# ── CurationSummary tests ──


def test_curation_summary_computes_counts_from_actions() -> None:
    """CurationSummary validator derives counts from actions list."""
    summary = CurationSummary(
        actions=[
            CurationAction(action="created_node", entity_name="Alice"),
            CurationAction(action="created_node", entity_name="Bob"),
            CurationAction(action="updated_node", entity_name="Charlie"),
            CurationAction(action="archived_node", entity_name="Dave"),
            CurationAction(action="created_edge", edge_source="Alice", edge_target="Bob"),
            CurationAction(action="removed_edge", edge_source="Charlie", edge_target="Dave"),
            CurationAction(action="removed_edge", edge_source="Eve", edge_target="Frank"),
        ],
        summary="Test summary",
    )
    assert summary.entities_created == 2
    assert summary.entities_updated == 1
    assert summary.entities_archived == 1
    assert summary.edges_created == 1
    assert summary.edges_removed == 2


def test_curation_summary_empty_actions() -> None:
    """CurationSummary with no actions has all zero counts."""
    summary = CurationSummary(summary="Nothing done")
    assert summary.entities_created == 0
    assert summary.entities_updated == 0
    assert summary.entities_archived == 0
    assert summary.edges_created == 0
    assert summary.edges_removed == 0


def test_curation_summary_overrides_manual_counts() -> None:
    """Validator recomputes counts even if LLM provides them explicitly."""
    summary = CurationSummary(
        actions=[
            CurationAction(action="created_node", entity_name="Alice"),
        ],
        entities_created=99,  # LLM got it wrong
    )
    assert summary.entities_created == 1  # validator corrected it


# ── delete_edge tests ──


@pytest.mark.asyncio
async def test_delete_edge_removes_edge(repo: InMemoryRepository) -> None:
    """delete_edge removes an existing edge and returns True."""
    nt = await repo.get_or_create_node_type(AGENT, "Person")
    et = await repo.get_or_create_edge_type(AGENT, "KNOWS")
    alice = await repo.upsert_node(AGENT, "Alice", nt.id)
    bob = await repo.upsert_node(AGENT, "Bob", nt.id)
    edge = await repo.upsert_edge(AGENT, alice.id, bob.id, et.id)
    assert edge is not None

    result = await repo.delete_edge(AGENT, edge.id)
    assert result is True

    # Edge should be gone
    sigs = await repo.list_all_edge_signatures(AGENT)
    assert len(sigs) == 0


@pytest.mark.asyncio
async def test_delete_edge_nonexistent_returns_false(repo: InMemoryRepository) -> None:
    """delete_edge returns False for non-existent edge."""
    result = await repo.delete_edge(AGENT, 9999)
    assert result is False


# ── cleanup_partial_curation tests ──


@pytest.mark.asyncio
async def test_cleanup_partial_curation_removes_tagged_items(repo: InMemoryRepository) -> None:
    """cleanup_partial_curation deletes nodes/edges tagged with episode_id."""
    nt = await repo.get_or_create_node_type(AGENT, "Person")
    et = await repo.get_or_create_edge_type(AGENT, "KNOWS")

    # Create items tagged with episode 42
    alice = await repo.upsert_node(
        AGENT,
        "Alice",
        nt.id,
        properties={"_source_episode": 42},
    )
    bob = await repo.upsert_node(
        AGENT,
        "Bob",
        nt.id,
        properties={"_source_episode": 42},
    )
    await repo.upsert_edge(
        AGENT,
        alice.id,
        bob.id,
        et.id,
        properties={"_source_episode": 42},
    )

    # Create an unrelated item (episode 99) that should NOT be deleted
    await repo.upsert_node(
        AGENT,
        "Charlie",
        nt.id,
        properties={"_source_episode": 99},
    )

    deleted = await repo.cleanup_partial_curation(AGENT, 42)
    assert deleted == 3  # 2 nodes + 1 edge

    # Charlie should still exist
    charlie = await repo.find_nodes_by_name(AGENT, "Charlie")
    assert len(charlie) == 1

    # Alice and Bob should be gone
    alice_nodes = await repo.find_nodes_by_name(AGENT, "Alice")
    assert len(alice_nodes) == 0


@pytest.mark.asyncio
async def test_cleanup_partial_curation_no_matches(repo: InMemoryRepository) -> None:
    """cleanup_partial_curation returns 0 when nothing matches."""
    deleted = await repo.cleanup_partial_curation(AGENT, 999)
    assert deleted == 0


@pytest.mark.asyncio
async def test_retry_after_partial_failure(repo: InMemoryRepository) -> None:
    """Simulates partial curation failure and successful retry."""
    nt = await repo.get_or_create_node_type(AGENT, "Person")

    # Simulate partial curation: one node was created before failure
    await repo.upsert_node(
        AGENT,
        "Alice",
        nt.id,
        content="Partial",
        properties={"_source_episode": 10},
    )

    # Cleanup before retry
    deleted = await repo.cleanup_partial_curation(AGENT, 10)
    assert deleted == 1

    # Retry: create again cleanly
    await repo.upsert_node(
        AGENT,
        "Alice",
        nt.id,
        content="Complete",
        properties={"_source_episode": 10},
    )

    alice = await repo.find_nodes_by_name(AGENT, "Alice")
    assert len(alice) == 1
    assert alice[0].content == "Complete"


@pytest.mark.asyncio
async def test_librarian_mutation_audit_is_opaque_and_tracker_counts_actions(
    repo: InMemoryRepository,
) -> None:
    """Mutation audit records contain IDs and actions, never source strings."""
    entity_one = "PRIVATE_ENTITY_SENTINEL_ONE"
    entity_two = "PRIVATE_ENTITY_SENTINEL_TWO"
    node_type = "PRIVATE_NODE_TYPE_SENTINEL"
    edge_type = "PRIVATE_EDGE_TYPE_SENTINEL"
    private_content = "PRIVATE_CONTENT_SENTINEL"
    private_reason = "PRIVATE_REASON_SENTINEL"
    tracker = CurationActionTracker()
    deps = _make_deps(repo, episode_id=42)
    deps.node_types = [node_type]
    deps.edge_types = [edge_type]
    deps.action_tracker = tracker
    ctx = SimpleNamespace(deps=deps, run_id="opaque-run", retry=0)
    agent = build_librarian_agent(_TEST_CONFIG, use_tools=True)
    tools = agent._function_toolset.tools
    records: list[dict] = []
    sink_id = logger.add(lambda message: records.append(message.record), level="INFO")

    try:
        await tools["create_or_update_node"].function(
            ctx,
            name=entity_one,
            type_name=node_type,
            content=private_content,
        )
        second = await tools["create_or_update_node"].function(
            ctx,
            name=entity_two,
            type_name=node_type,
            content=private_content,
        )
        edge = await tools["create_or_update_edge"].function(
            ctx,
            source_name=entity_one,
            target_name=entity_two,
            edge_type=edge_type,
        )
        await tools["archive_node"].function(ctx, node_id=second["node_id"], reason=private_reason)
        await tools["remove_edge"].function(ctx, edge_id=edge["edge_id"], reason=private_reason)
    finally:
        logger.remove(sink_id)

    action_records = [record for record in records if record["extra"].get("action_log")]
    assert action_records
    assert all(
        sentinel not in str(record["extra"])
        for sentinel in (entity_one, entity_two, node_type, edge_type, private_content, private_reason)
        for record in action_records
    )
    node_record = next(record for record in action_records if record["message"] == "librarian_tool_call")
    assert node_record["extra"]["tool"] in {
        "create_or_update_node",
        "create_or_update_edge",
        "archive_node",
        "remove_edge",
    }
    assert isinstance(node_record["extra"].get("node_id"), int)
    assert tracker.entities_created == 2
    assert tracker.edges_created == 1
    assert tracker.entities_archived == 1
    assert tracker.edges_removed == 1


@pytest.mark.asyncio
async def test_bounded_batches_terminalize_from_repository_results(repo: InMemoryRepository) -> None:
    entities = [
        ExtractedEntity(
            name="Alpha",
            type_name="Concept",
            description="Alpha content",
            properties={"reviewed_count": 15},
        ),
        ExtractedEntity(name="Beta", type_name="Concept", description="Beta content"),
    ]
    relations = build_librarian_relation_items(
        entities, [ExtractedRelation(source_name="Alpha", target_name="Beta", relation_type="RELATED_TO")]
    )
    await repo.get_or_create_node_type(AGENT, "Concept")
    await repo.get_or_create_edge_type(AGENT, "RELATED_TO")
    tracker = LibrarianTrajectoryTracker(entities=entities, relations=relations)
    deps = LibrarianAgentDeps(
        episode_text="private source",
        node_types=["Concept"],
        edge_types=["RELATED_TO"],
        extracted_entities=entities,
        extracted_relations=relations,
        repo=repo,
        embeddings=None,
        agent_id=AGENT,
        episode_id=7,
        action_tracker=tracker,
    )
    ctx = SimpleNamespace(deps=deps, run_id="bounded", retry=0)
    tools = build_librarian_agent(_TEST_CONFIG, profile="qwen_bounded")._function_toolset.tools
    resolved = await tools["resolve_entities"].function(ctx, entity_indices=[0, 1])
    assert [item.reason for item in resolved.items] == ["no_match", "no_match"]
    outcomes = await tools["apply_entity_decisions"].function(
        ctx,
        decisions=[
            EntityDecision(
                entity_index=0,
                decision="create",
                content="Alpha content",
                properties={"reviewed_count": 999, "model_note": "kept"},
            ),
            EntityDecision(entity_index=1, decision="create", content="Beta content"),
        ],
    )
    assert [item.reason for item in outcomes.items] == ["created", "created"]
    checked = await tools["check_relations"].function(ctx, relation_indices=[0])
    assert checked.items[0].reason == "no_match"
    await tools["apply_relation_decisions"].function(
        ctx, decisions=[RelationDecision(relation_index=0, decision="create")]
    )
    report = tracker.build_report()
    assert report.status == "completed"
    assert (report.entities_created, report.edges_created, report.result_source) == (2, 1, "host_tracker")
    assert tracker.successful_node_ids == set(tracker.bound_node_ids.values())
    assert tracker.successful_edge_ids == set(tracker.successful_edge_signatures)
    assert all(node.properties["_source_episode"] == 7 for node in repo._nodes.values())
    alpha = next(node for node in repo._nodes.values() if node.name == "Alpha")
    assert alpha.properties["reviewed_count"] == 15
    assert alpha.properties["model_note"] == "kept"


def test_duplicate_budget_is_enforced_per_tool_item_across_mixed_batches() -> None:
    entities = [ExtractedEntity(name=str(index), type_name="Concept", description="x") for index in range(3)]
    tracker = LibrarianTrajectoryTracker(
        entities=entities, relations=[], budget=LibrarianBudgetConfig(max_duplicate_calls=2)
    )
    assert tracker.begin_call("resolve_entities", [0, 1], read=True) == set()
    tracker.record_progress()
    assert tracker.begin_call("resolve_entities", [0, 2], read=True) == {0}
    tracker.record_progress()
    with pytest.raises(LibrarianTrajectoryLimitExceeded, match="duplicate_calls"):
        tracker.begin_call("resolve_entities", [1, 2], read=True)
    assert tracker.duplicate_calls == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "kwargs"),
    [
        ("resolve_entities", {"entity_indices": [-1]}),
        (
            "read_entity_details",
            {"requests": [EntityDetailRequest.model_construct(entity_index=-1)]},
        ),
        (
            "apply_entity_decisions",
            {"decisions": [EntityDecision.model_construct(entity_index=-1, decision="create", content="x")]},
        ),
        ("check_relations", {"relation_indices": [-1]}),
        (
            "apply_relation_decisions",
            {"decisions": [RelationDecision.model_construct(relation_index=-1, decision="create")]},
        ),
    ],
)
async def test_bounded_tools_reject_negative_indices_before_repository_access(
    repo: InMemoryRepository, tool_name: str, kwargs: dict[str, Any]
) -> None:
    entities = [ExtractedEntity(name="Alpha", type_name="Concept", description="x")]
    relations = [ExtractedRelation(source_name="Alpha", target_name="Alpha", relation_type="RELATED_TO")]
    tracker = LibrarianTrajectoryTracker(entities=entities, relations=relations)
    deps = LibrarianAgentDeps(
        episode_text="private",
        node_types=["Concept"],
        edge_types=["RELATED_TO"],
        extracted_entities=entities,
        extracted_relations=relations,
        repo=repo,
        embeddings=None,
        agent_id=AGENT,
        action_tracker=tracker,
    )
    ctx = SimpleNamespace(deps=deps, run_id="negative", retry=0)
    tool = build_librarian_agent(_TEST_CONFIG, profile="qwen_bounded")._function_toolset.tools[tool_name]
    with pytest.raises(ValueError, match="indices"):
        await tool.function(ctx, **kwargs)
    assert tracker.provider_batch_calls == 0
    assert tracker.repository_item_reads == 0
    assert not repo._nodes and not repo._edges


def test_bounded_tracker_normalizes_order_and_duplicates_but_rejects_invalid_unique_batches() -> None:
    tracker = LibrarianTrajectoryTracker(
        entities=[ExtractedEntity(name=str(index), type_name="Concept") for index in range(17)]
    )
    assert tracker.normalize_indices([2, 0, 2, 1], 17, 16) == [0, 1, 2]
    assert tracker.host_normalization_count == 1
    assert tracker.normalize_indices([0, 1], 17, 16) == [0, 1]
    assert tracker.host_normalization_count == 1
    with pytest.raises(ValueError, match="non-negative"):
        tracker.normalize_indices([-1, 0], 17, 16)
    with pytest.raises(ValueError, match="out of range"):
        tracker.normalize_indices([17], 17, 16)
    with pytest.raises(ValueError, match="batch limit"):
        tracker.normalize_indices(list(range(17)), 17, 16)
    with pytest.raises(ValueError, match="non-empty"):
        tracker.normalize_indices([], 17, 16)
    assert tracker.host_normalization_count == 1


@pytest.mark.asyncio
async def test_bounded_detail_read_derives_resolver_selected_node_id(repo: InMemoryRepository) -> None:
    node_type = await repo.get_or_create_node_type(AGENT, "Concept")
    assert node_type is not None
    node = await repo.upsert_node(agent_id=AGENT, name="Alpha", type_id=node_type.id, content="existing")
    entity = ExtractedEntity(name="Alpha", type_name="Concept", description="new")
    tracker = LibrarianTrajectoryTracker(entities=[entity])
    deps = LibrarianAgentDeps(
        episode_text="private",
        node_types=["Concept"],
        edge_types=[],
        extracted_entities=[entity],
        extracted_relations=[],
        repo=repo,
        embeddings=None,
        agent_id=AGENT,
        action_tracker=tracker,
    )
    ctx = SimpleNamespace(deps=deps, run_id="host-bound-detail", retry=0)
    tools = build_librarian_agent(_TEST_CONFIG, profile="qwen_bounded")._function_toolset.tools
    await tools["resolve_entities"].function(ctx, entity_indices=[0])
    detail = await tools["read_entity_details"].function(ctx, requests=[EntityDetailRequest(entity_index=0)])
    assert detail.items[0].node_id == node.id
    assert detail.items[0].allowed_decisions == ["update", "unchanged"]
    assert EntityDetailRequest.model_json_schema()["properties"] == {
        "entity_index": {"minimum": 0, "title": "Entity Index", "type": "integer"}
    }


@pytest.mark.asyncio
async def test_bounded_detail_read_safely_rejects_index_without_selected_candidate(
    repo: InMemoryRepository,
) -> None:
    entity = ExtractedEntity(name="Missing", type_name="Concept")
    tracker = LibrarianTrajectoryTracker(entities=[entity])
    tracker.resolved_entities.add(0)
    tracker.entity_resolution_reason[0] = "none"
    deps = LibrarianAgentDeps(
        episode_text="private",
        node_types=["Concept"],
        edge_types=[],
        extracted_entities=[entity],
        extracted_relations=[],
        repo=repo,
        embeddings=None,
        agent_id=AGENT,
        action_tracker=tracker,
    )
    ctx = SimpleNamespace(deps=deps, run_id="missing-detail", retry=0)
    tool = build_librarian_agent(_TEST_CONFIG, profile="qwen_bounded")._function_toolset.tools["read_entity_details"]
    result = await tool.function(ctx, requests=[EntityDetailRequest(entity_index=0)])
    assert result.items[0].reason == "not_found"
    assert result.items[0].node_id is None
    assert result.items[0].allowed_decisions == ["create"]
    assert tracker.repository_item_reads == 0


@pytest.mark.asyncio
async def test_bounded_tools_normalize_model_batches_before_repository_work(repo: InMemoryRepository) -> None:
    entities = [ExtractedEntity(name=name, type_name="Concept") for name in ("Alpha", "Beta", "Gamma")]
    await repo.get_or_create_node_type(AGENT, "Concept")
    tracker = LibrarianTrajectoryTracker(entities=entities)
    deps = LibrarianAgentDeps(
        episode_text="private",
        node_types=["Concept"],
        edge_types=[],
        extracted_entities=entities,
        extracted_relations=[],
        repo=repo,
        embeddings=None,
        agent_id=AGENT,
        action_tracker=tracker,
    )
    ctx = SimpleNamespace(deps=deps, run_id="normalized-batch", retry=0)
    tools = build_librarian_agent(_TEST_CONFIG, profile="qwen_bounded")._function_toolset.tools
    resolved = await tools["resolve_entities"].function(ctx, entity_indices=[2, 0, 2, 1])
    assert [item.item_index for item in resolved.items] == [0, 1, 2]
    assert all(item.allowed_decisions == ["create"] for item in resolved.items)
    assert tracker.repository_item_reads == 3
    assert tracker.host_normalization_count == 1


@pytest.mark.asyncio
async def test_bounded_entity_micro_batches_can_resolve_and_decide_end_to_end(
    repo: InMemoryRepository,
) -> None:
    entities = [ExtractedEntity(name=name, type_name="Concept") for name in ("Alpha", "Beta")]
    await repo.get_or_create_node_type(AGENT, "Concept")
    tracker = LibrarianTrajectoryTracker(entities=entities)
    deps = LibrarianAgentDeps(
        episode_text="private",
        node_types=["Concept"],
        edge_types=[],
        extracted_entities=entities,
        extracted_relations=[],
        repo=repo,
        embeddings=None,
        agent_id=AGENT,
        action_tracker=tracker,
    )
    ctx = SimpleNamespace(deps=deps, run_id="entity-micro-batch", retry=0)
    tools = build_librarian_agent(_TEST_CONFIG, profile="qwen_bounded")._function_toolset.tools

    first = await tools["resolve_entities"].function(ctx, entity_indices=[0])
    assert first.items[0].allowed_decisions == ["create"]
    applied = await tools["apply_entity_decisions"].function(
        ctx, decisions=[EntityDecision(entity_index=0, decision="create", content="Alpha")]
    )
    assert applied.items[0].status == "ok"
    assert tracker.entity_states == {0: "created", 1: "pending"}

    await tools["resolve_entities"].function(ctx, entity_indices=[1])
    await tools["apply_entity_decisions"].function(
        ctx, decisions=[EntityDecision(entity_index=1, decision="create", content="Beta")]
    )
    assert tracker.build_report().status == "completed"


@pytest.mark.asyncio
async def test_bounded_entity_batch_applies_valid_items_and_allows_rejected_retry(
    repo: InMemoryRepository,
) -> None:
    node_type = await repo.get_or_create_node_type(AGENT, "Concept")
    assert node_type is not None
    existing = await repo.upsert_node(agent_id=AGENT, name="Alpha", type_id=node_type.id, content="existing")
    entities = [
        ExtractedEntity(name="Alpha", type_name="Concept", description="existing"),
        ExtractedEntity(name="Beta", type_name="Concept", description="new"),
    ]
    tracker = LibrarianTrajectoryTracker(entities=entities)
    deps = LibrarianAgentDeps(
        episode_text="private",
        node_types=["Concept"],
        edge_types=[],
        extracted_entities=entities,
        extracted_relations=[],
        repo=repo,
        embeddings=None,
        agent_id=AGENT,
        action_tracker=tracker,
    )
    ctx = SimpleNamespace(deps=deps, run_id="entity-retry", retry=0)
    tools = build_librarian_agent(_TEST_CONFIG, profile="qwen_bounded")._function_toolset.tools
    await tools["resolve_entities"].function(ctx, entity_indices=[0, 1])
    await tools["read_entity_details"].function(ctx, requests=[EntityDetailRequest(entity_index=0)])

    mixed = await tools["apply_entity_decisions"].function(
        ctx,
        decisions=[
            EntityDecision(entity_index=0, decision="create", content="wrong action"),
            EntityDecision(entity_index=1, decision="create", content="new"),
        ],
    )
    assert [(item.status, item.reason) for item in mixed.items] == [
        ("rejected", "selected_candidate_exists"),
        ("ok", "created"),
    ]
    assert tracker.entity_states == {0: "pending", 1: "created"}
    assert tracker.validation_rejections == 1

    corrected = await tools["apply_entity_decisions"].function(
        ctx, decisions=[EntityDecision(entity_index=0, decision="unchanged")]
    )
    assert [(item.status, item.reason) for item in corrected.items] == [("noop", "unchanged")]
    assert tracker.bound_node_ids[0] == existing.id
    assert tracker.duplicate_calls == 0
    assert tracker.build_report().status == "completed"


@pytest.mark.asyncio
async def test_bounded_wrong_phase_decision_is_rejected_then_retriable(repo: InMemoryRepository) -> None:
    entity = ExtractedEntity(name="Alpha", type_name="Concept")
    tracker = LibrarianTrajectoryTracker(entities=[entity])
    deps = LibrarianAgentDeps(
        episode_text="private",
        node_types=["Concept"],
        edge_types=[],
        extracted_entities=[entity],
        extracted_relations=[],
        repo=repo,
        embeddings=None,
        agent_id=AGENT,
        action_tracker=tracker,
    )
    ctx = SimpleNamespace(deps=deps, run_id="phase-retry", retry=0)
    tools = build_librarian_agent(_TEST_CONFIG, profile="qwen_bounded")._function_toolset.tools

    rejected = await tools["apply_entity_decisions"].function(
        ctx, decisions=[EntityDecision(entity_index=0, decision="create", content="new")]
    )
    assert [(item.status, item.reason) for item in rejected.items] == [("rejected", "phase_violation")]
    assert not repo._nodes
    assert tracker.entity_states[0] == "pending"

    await tools["resolve_entities"].function(ctx, entity_indices=[0])
    corrected = await tools["apply_entity_decisions"].function(
        ctx, decisions=[EntityDecision(entity_index=0, decision="create", content="new")]
    )
    assert [(item.status, item.reason) for item in corrected.items] == [("ok", "created")]
    assert tracker.validation_rejections == 1
    assert tracker.duplicate_calls == 0


@pytest.mark.asyncio
async def test_bounded_relation_batch_applies_valid_items_and_allows_rejected_retry(
    repo: InMemoryRepository,
) -> None:
    entities = [
        ExtractedEntity(name="Alpha", type_name="Concept"),
        ExtractedEntity(name="Beta", type_name="Concept"),
    ]
    relations = [
        ExtractedRelation(source_name="Alpha", target_name="Beta", relation_type="FIRST"),
        ExtractedRelation(source_name="Beta", target_name="Alpha", relation_type="SECOND"),
    ]
    node_type = await repo.get_or_create_node_type(AGENT, "Concept")
    assert node_type is not None
    alpha = await repo.upsert_node(agent_id=AGENT, name="Alpha", type_id=node_type.id)
    beta = await repo.upsert_node(agent_id=AGENT, name="Beta", type_id=node_type.id)
    await repo.get_or_create_edge_type(AGENT, "FIRST")
    await repo.get_or_create_edge_type(AGENT, "SECOND")
    tracker = LibrarianTrajectoryTracker(entities=entities, relations=relations)
    tracker.entity_states.update({0: "unchanged", 1: "unchanged"})
    tracker.bound_node_ids.update({0: alpha.id, 1: beta.id})
    deps = LibrarianAgentDeps(
        episode_text="private",
        node_types=["Concept"],
        edge_types=["FIRST", "SECOND"],
        extracted_entities=entities,
        extracted_relations=relations,
        repo=repo,
        embeddings=None,
        agent_id=AGENT,
        action_tracker=tracker,
    )
    ctx = SimpleNamespace(deps=deps, run_id="relation-retry", retry=0)
    tools = build_librarian_agent(_TEST_CONFIG, profile="qwen_bounded")._function_toolset.tools
    checked = await tools["check_relations"].function(ctx, relation_indices=[0, 1])
    assert all(item.allowed_decisions == ["create"] for item in checked.items)

    mixed = await tools["apply_relation_decisions"].function(
        ctx,
        decisions=[
            RelationDecision(relation_index=0, decision="create"),
            RelationDecision(relation_index=1, decision="unresolved"),
        ],
    )
    assert [(item.status, item.reason) for item in mixed.items] == [
        ("ok", "created"),
        ("rejected", "unresolved_not_allowed"),
    ]
    assert tracker.relation_states == {0: "created", 1: "pending"}
    assert tracker.validation_rejections == 1

    corrected = await tools["apply_relation_decisions"].function(
        ctx, decisions=[RelationDecision(relation_index=1, decision="create")]
    )
    assert [(item.status, item.reason) for item in corrected.items] == [("ok", "created")]
    assert tracker.duplicate_calls == 0
    assert tracker.build_report().status == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("use_tools", [True, False])
async def test_librarian_request_limit_tracks_tool_budget(
    repo: InMemoryRepository,
    use_tools: bool,
) -> None:
    """Both librarian modes receive a request budget above the tool budget."""
    from neocortex.extraction.pipeline import run_extraction

    eid = await repo.store_episode(AGENT, "safe source")
    captured_limits = []

    def fake_build(_config=None, *, use_tools=True, retries=DEFAULT_LIBRARIAN_RETRIES):
        agent = SimpleNamespace()
        agent._max_result_retries = retries

        async def run(*_args, **kwargs):
            captured_limits.append(kwargs["usage_limits"])
            output = CurationSummary() if use_tools else LibrarianPayload()
            result = SimpleNamespace(
                output=output,
                usage=lambda: SimpleNamespace(
                    requests=1,
                    tool_calls=0,
                    input_tokens=0,
                    output_tokens=0,
                    details={},
                ),
            )
            return result

        agent.run = run
        return agent

    with patch("neocortex.extraction.pipeline.build_librarian_agent", side_effect=fake_build):
        await run_extraction(
            repo=repo,
            embeddings=None,
            agent_id=AGENT,
            episode_ids=[eid],
            ontology_config=_TEST_CONFIG,
            extractor_config=_TEST_CONFIG,
            librarian_config=_TEST_CONFIG,
            librarian_use_tools=use_tools,
            tool_calls_limit=17,
            archive_interval=0,
        )

    assert len(captured_limits) == 1
    assert captured_limits[0].request_limit == 19
    assert captured_limits[0].tool_calls_limit == 17


@pytest.mark.asyncio
async def test_librarian_request_budget_allows_full_tool_budget_and_retry(
    repo: InMemoryRepository,
) -> None:
    """A full tool budget plus one output retry completes under the derived limit."""
    from neocortex.extraction.pipeline import _librarian_request_limit

    agent = build_librarian_agent(_TEST_CONFIG, use_tools=True)
    model = _ToolBudgetThenValidationRetryModel()
    deps = _make_deps(repo)
    tool_calls_limit = 1
    request_limit = _librarian_request_limit(tool_calls_limit, DEFAULT_LIBRARIAN_RETRIES)

    assert agent._max_result_retries == DEFAULT_LIBRARIAN_RETRIES
    assert request_limit == tool_calls_limit + 1 + DEFAULT_LIBRARIAN_RETRIES
    with agent.override(model=model):
        result = await agent.run(
            "Integrate the extracted entities and relations into the knowledge graph.",
            deps=deps,
            usage_limits=UsageLimits(
                request_limit=request_limit,
                tool_calls_limit=tool_calls_limit,
            ),
        )

    assert result.output == CurationSummary()
    assert model.requests == request_limit
    assert result.usage().requests == request_limit


@pytest.mark.asyncio
async def test_pydantic_ai_checks_a_whole_tool_batch_before_execution(repo: InMemoryRepository) -> None:
    """A two-call response is rejected before either tool runs at limit one.

    The request limit is deliberately much larger than the one request made by
    this fixture.  This isolates the installed PydanticAI tool-batch check from
    request-limit accounting.
    """
    agent = build_librarian_agent(_TEST_CONFIG, use_tools=True)
    model = _TwoCallBatchModel()
    search_nodes = AsyncMock(return_value=[])
    deps = _make_deps(repo)

    with (
        patch.object(repo, "search_nodes", search_nodes),
        agent.override(model=model),
        pytest.raises(UsageLimitExceeded, match="tool_calls_limit"),
    ):
        await agent.run(
            "Integrate the extracted entities and relations into the knowledge graph.",
            deps=deps,
            usage_limits=UsageLimits(request_limit=10, tool_calls_limit=1),
        )

    assert model.requests == 1
    search_nodes.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provided_correlation_id", "expected_correlation_id"),
    [
        ("job:test-agent:1", None),
        ("extract-0123456789abcdef0123456789abcdef", "extract-0123456789abcdef0123456789abcdef"),
    ],
)
async def test_librarian_failure_audit_reports_unproven_mutation_risk(
    repo: InMemoryRepository,
    provided_correlation_id: str,
    expected_correlation_id: str | None,
) -> None:
    """A failed tool attempt is observable without exposing source material."""
    from neocortex.extraction.pipeline import run_extraction

    eid = await repo.store_episode(AGENT, "safe source")
    records: list[dict] = []

    def fake_build(_config=None, *, use_tools=True, retries=DEFAULT_LIBRARIAN_RETRIES):
        del use_tools, retries
        agent = SimpleNamespace()

        async def run(*_args, **_kwargs):
            raise UsageLimitExceeded("tool budget exhausted")

        agent.run = run
        return agent

    sink_id = logger.add(lambda message: records.append(message.record), level="INFO")
    try:
        with (
            patch("neocortex.extraction.pipeline.build_librarian_agent", side_effect=fake_build),
            pytest.raises(UsageLimitExceeded),
        ):
            await run_extraction(
                repo=repo,
                embeddings=None,
                agent_id=AGENT,
                episode_ids=[eid],
                ontology_config=_TEST_CONFIG,
                extractor_config=_TEST_CONFIG,
                librarian_config=_TEST_CONFIG,
                librarian_use_tools=True,
                archive_interval=0,
                correlation_id=provided_correlation_id,
            )
    finally:
        logger.remove(sink_id)

    failure = next(record for record in records if record["message"] == "librarian_failed")
    assert failure["extra"]["error_type"] == "UsageLimitExceeded"
    assert failure["extra"]["graph_cleanliness"] == "NOT_MEASURED"
    assert failure["extra"]["mutation_count"] == 0
    assert failure["extra"]["entity_count"] >= 0
    assert failure["extra"]["relation_count"] >= 0
    assert failure["extra"]["correlation_id"].startswith("extract-")
    assert len(failure["extra"]["correlation_id"]) == len("extract-") + 32
    if expected_correlation_id is not None:
        assert failure["extra"]["correlation_id"] == expected_correlation_id
    else:
        assert failure["extra"]["correlation_id"] != provided_correlation_id
        assert all(provided_correlation_id not in str(record["extra"]) for record in records)


@pytest.mark.asyncio
async def test_curation_complete_uses_observed_actions_not_model_summary(
    repo: InMemoryRepository,
) -> None:
    """Completion counts remain accurate when the model returns an empty action list."""
    from neocortex.extraction.pipeline import run_extraction

    summary_sentinel = "PRIVATE_MODEL_SUMMARY_SENTINEL"
    eid = await repo.store_episode(AGENT, "safe source")
    records: list[dict] = []

    def fake_build(_config=None, *, use_tools=True, retries=DEFAULT_LIBRARIAN_RETRIES):
        agent = SimpleNamespace()

        async def run(*_args, **kwargs):
            tracker = kwargs["deps"].action_tracker
            assert tracker is not None
            tracker.record_node("created")
            tracker.record_edge_upsert()
            return SimpleNamespace(
                output=CurationSummary(summary=summary_sentinel),
                usage=lambda: SimpleNamespace(
                    requests=1,
                    tool_calls=2,
                    input_tokens=0,
                    output_tokens=0,
                    details={},
                ),
            )

        agent.run = run
        return agent

    sink_id = logger.add(lambda message: records.append(message.record), level="INFO")
    try:
        with patch("neocortex.extraction.pipeline.build_librarian_agent", side_effect=fake_build):
            await run_extraction(
                repo=repo,
                embeddings=None,
                agent_id=AGENT,
                episode_ids=[eid],
                ontology_config=_TEST_CONFIG,
                extractor_config=_TEST_CONFIG,
                librarian_config=_TEST_CONFIG,
                librarian_use_tools=True,
                archive_interval=0,
            )
    finally:
        logger.remove(sink_id)

    complete = next(record for record in records if record["message"] == "curation_complete")
    extra = complete["extra"]
    assert extra["created"] == 1
    assert extra["edges_created"] == 1
    assert extra["actions_observed"] == 2
    assert extra["model_summary_actions"] == 0
    assert "summary" not in extra
    assert summary_sentinel not in str(extra)
    cardinality = next(record for record in records if record["message"] == "extractor_cardinality")
    assert isinstance(cardinality["extra"]["entity_count"], int)
    assert isinstance(cardinality["extra"]["relation_count"], int)
    progress = next(record for record in records if record["message"] == "librarian_progress")
    assert progress["extra"]["phase"] == "started"
    assert progress["extra"]["mutation_count"] == 0
    assert progress["extra"]["tool_calls_limit"] == 150


# ── Pipeline integration tests ──


@pytest.mark.asyncio
async def test_pipeline_tool_mode_does_not_call_persist_payload(repo: InMemoryRepository) -> None:
    """In tool mode, pipeline should NOT call _persist_payload."""
    from unittest.mock import AsyncMock, patch

    from neocortex.extraction.pipeline import _persist_payload, run_extraction

    eid = await repo.store_episode(AGENT, "Alice works on billing.")

    persist_spy = AsyncMock(side_effect=_persist_payload)

    with patch("neocortex.extraction.pipeline._persist_payload", persist_spy):
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

    persist_spy.assert_not_called()


@pytest.mark.asyncio
async def test_pipeline_fallback_mode_calls_persist_payload(repo: InMemoryRepository) -> None:
    """When librarian_use_tools=False, pipeline uses _persist_payload."""
    from unittest.mock import AsyncMock, patch

    from neocortex.extraction.pipeline import _persist_payload, run_extraction

    eid = await repo.store_episode(AGENT, "Alice works on billing.")

    persist_spy = AsyncMock(side_effect=_persist_payload)

    with patch("neocortex.extraction.pipeline._persist_payload", persist_spy):
        await run_extraction(
            repo=repo,
            embeddings=None,
            agent_id=AGENT,
            episode_ids=[eid],
            ontology_config=_TEST_CONFIG,
            extractor_config=_TEST_CONFIG,
            librarian_config=_TEST_CONFIG,
            librarian_use_tools=False,
        )

    persist_spy.assert_called_once()


@pytest.mark.asyncio
async def test_pipeline_skips_cleanup_before_curation(repo: InMemoryRepository) -> None:
    """Pipeline does NOT call cleanup_partial_curation — upsert semantics make it unnecessary."""
    from unittest.mock import AsyncMock

    from neocortex.extraction.pipeline import run_extraction

    eid = await repo.store_episode(AGENT, "Alice works on billing.")

    cleanup_spy = AsyncMock(return_value=0)
    repo.cleanup_partial_curation = cleanup_spy  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]

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

    cleanup_spy.assert_not_called()


@pytest.mark.asyncio
async def test_full_pipeline_tool_mode_with_test_model(repo: InMemoryRepository) -> None:
    """Full pipeline in tool mode runs without errors using TestModel."""
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
        librarian_use_tools=True,
    )

    stats = await repo.get_stats(AGENT)
    assert stats.total_episodes == 1


@pytest.mark.asyncio
async def test_full_pipeline_fallback_mode_with_test_model(repo: InMemoryRepository) -> None:
    """Full pipeline in fallback mode runs without errors using TestModel."""
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
        librarian_use_tools=False,
    )

    stats = await repo.get_stats(AGENT)
    assert stats.total_episodes == 1


# ── list_all_node_names limit tests ──


@pytest.mark.asyncio
async def test_list_all_node_names_with_limit(repo: InMemoryRepository) -> None:
    """list_all_node_names respects the limit parameter."""
    nt = await repo.get_or_create_node_type(AGENT, "Person")
    for name in ["Alice", "Bob", "Charlie", "Dave", "Eve"]:
        await repo.upsert_node(AGENT, name, nt.id)

    all_names = await repo.list_all_node_names(AGENT)
    assert len(all_names) == 5

    limited = await repo.list_all_node_names(AGENT, limit=3)
    assert len(limited) == 3
