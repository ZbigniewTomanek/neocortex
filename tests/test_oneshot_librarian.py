"""Tests for the host-resolved one-shot librarian (profile ``qwen_oneshot``).

The profile's contract is that the host does the resolving and the applying,
and the model is asked at most one question:

- no candidates in the graph → no model call at all;
- a merge decision updates the resolved node instead of duplicating it;
- a decision naming a node outside the host's candidate set is discarded;
- a `create` that would overwrite an offered candidate is applied as a merge;
- two entities resolving to one node keep both of their facts;
- an edge upsert that returns None is counted unresolved and audited;
- an entity with ``supersedes`` stays distinct and gets its temporal edge;
- replaying the same extraction adds no nodes and no edges;
- a relation whose endpoint never bound is skipped and audited.
"""

from __future__ import annotations

from typing import Any

import pytest
from loguru import logger
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.settings import ModelSettings

from neocortex.db.mock import InMemoryRepository
from neocortex.extraction.agents import (
    AgentInferenceConfig,
    CurationActionTracker,
    build_librarian_agent,
)
from neocortex.extraction.oneshot_librarian import (
    build_oneshot_items,
    render_oneshot_items,
    resolve_extraction_entities,
    run_oneshot_librarian,
)
from neocortex.extraction.schemas import (
    ExtractedEntity,
    ExtractedRelation,
    ExtractionResult,
    OneshotDecisions,
)
from neocortex.model_factory import LocalEndpoint

AGENT = "test-agent"
LOCAL_ENDPOINT = LocalEndpoint(
    base_url="http://127.0.0.1:24000/v1",
    api_key_env="LITELLM_API_KEY",
    temperature=0.6,
    top_p=0.95,
    temperature_nothink=0.3,
    top_p_nothink=0.9,
    timeout_s=600.0,
)
QWEN_CONFIG = AgentInferenceConfig(
    model_name="local:qwen3.8-flash-next",
    thinking_effort=False,
    use_test_model=True,
    local_endpoint=LOCAL_ENDPOINT,
)


@pytest.fixture
def repo() -> InMemoryRepository:
    return InMemoryRepository()


class _CollectingSink:
    """Capture the structured action-log records one run emits."""

    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, message: Any) -> None:
        record = message.record
        self.records.append((record["message"], dict(record["extra"])))

    def events(self, name: str) -> list[dict[str, Any]]:
        return [fields for event, fields in self.records if event == name]


class _NoModelCall(TestModel):
    """Fail loudly if the librarian reaches the model."""

    def _request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        raise AssertionError("the one-shot librarian must not call the model without candidates")


def _decisions_model(payload: dict[str, Any]) -> FunctionModel:
    """A model that answers the single decision request with ``payload``."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages
        assert not info.function_tools, "the one-shot librarian agent must be tool-free"
        tool = info.output_tools[0] if info.output_tools else None
        if tool is None:
            return ModelResponse(parts=[TextPart(OneshotDecisions.model_validate(payload).model_dump_json())])
        return ModelResponse(parts=[ToolCallPart(tool.name, payload, tool_call_id="oneshot")])

    return FunctionModel(respond)


async def _run(
    repo: InMemoryRepository,
    extraction: ExtractionResult,
    *,
    model: Any,
    episode_id: int | None = 1,
) -> tuple[Any, _CollectingSink]:
    agent = build_librarian_agent(QWEN_CONFIG, profile="qwen_oneshot")
    sink = _CollectingSink()
    handler = logger.add(sink, level="DEBUG", filter=lambda record: bool(record["extra"].get("action_log")))
    try:
        with agent.override(model=model):
            report = await run_oneshot_librarian(
                repo=repo,
                embeddings=None,
                agent_id=AGENT,
                target_schema=None,
                episode_id=episode_id,
                correlation_id=None,
                extraction=extraction,
                agent=agent,
                cfg=QWEN_CONFIG,
                tracker=CurationActionTracker(),
            )
    finally:
        logger.remove(handler)
    return report, sink


def _node(repo: InMemoryRepository, node_id: int) -> Any:
    """Read one stored node straight out of the mock repository."""
    return repo._nodes[node_id]


def _edge_types_between(repo: InMemoryRepository, source_id: int, target_id: int) -> list[str]:
    """Edge type names stored for one ordered pair — the drift unit in the mock."""
    names = {edge_type.id: name for name, edge_type in repo._edge_types.items()}
    return sorted(
        names[edge.type_id]
        for edge in repo._edges.values()
        if edge.source_id == source_id and edge.target_id == target_id
    )


async def _counts(repo: InMemoryRepository) -> tuple[int, int]:
    summary = await repo.get_ontology_summary(AGENT)
    return int(summary["total_nodes"]), int(summary["total_edges"])


def _extraction() -> ExtractionResult:
    return ExtractionResult(
        entities=[
            ExtractedEntity(name="Apache Kafka", type_name="Technology", description="Event streaming platform."),
            ExtractedEntity(name="Payments Team", type_name="Team", description="Owns the payments service."),
        ],
        relations=[
            ExtractedRelation(source_name="Payments Team", target_name="Apache Kafka", relation_type="USES"),
        ],
    )


# ── No candidates: zero model requests ──


@pytest.mark.asyncio
async def test_empty_graph_needs_no_model_call(repo: InMemoryRepository) -> None:
    """With nothing to compare against, the host creates everything on its own."""
    report, sink = await _run(repo, _extraction(), model=_NoModelCall())

    assert sink.events("agent_run_started") == []
    assert sink.events("agent_usage") == []
    assert report.entities_created == 2
    assert report.edges_created == 1
    assert await _counts(repo) == (2, 1)
    trajectory = sink.events("librarian_trajectory")
    assert len(trajectory) == 1
    assert trajectory[0]["profile"] == "qwen_oneshot"
    assert trajectory[0]["requests"] == 0
    assert trajectory[0]["model_items"] == 0


# ── Merge ──


@pytest.mark.asyncio
async def test_merge_decision_updates_the_resolved_node(repo: InMemoryRepository) -> None:
    """A merge rewrites the existing node's content and lifts its importance."""
    node_type = await repo.get_or_create_node_type(AGENT, "Technology")
    assert node_type is not None
    existing = await repo.upsert_node(
        agent_id=AGENT,
        name="Apache Kafka",
        type_id=node_type.id,
        content="Message broker.",
        importance=0.2,
    )

    extraction = ExtractionResult(
        entities=[
            ExtractedEntity(
                name="Apache Kafka",
                type_name="Technology",
                description="Event streaming platform, version 4.0.",
                importance=0.8,
            )
        ]
    )
    payload = {
        "decisions": [
            {
                "index": 0,
                "decision": "merge",
                "node_id": existing.id,
                "content": "Message broker and event streaming platform, version 4.0.",
            }
        ]
    }
    report, sink = await _run(repo, extraction, model=_decisions_model(payload))

    merged = _node(repo, existing.id)
    assert merged.content == "Message broker and event streaming platform, version 4.0."
    assert merged.importance == pytest.approx(0.8)
    assert report.entities_updated == 1
    assert report.entities_created == 0
    assert await _counts(repo) == (1, 0)
    assert sink.events("agent_usage")[0]["requests"] == 1
    assert sink.events("librarian_trajectory")[0]["requests"] == 1


@pytest.mark.asyncio
async def test_unchanged_decision_creates_nothing(repo: InMemoryRepository) -> None:
    """An `unchanged` decision binds the node without writing to it."""
    node_type = await repo.get_or_create_node_type(AGENT, "Technology")
    assert node_type is not None
    existing = await repo.upsert_node(
        agent_id=AGENT, name="Apache Kafka", type_id=node_type.id, content="Event streaming platform."
    )
    extraction = ExtractionResult(
        entities=[ExtractedEntity(name="Apache Kafka", type_name="Technology", description="Event streaming platform.")]
    )
    payload = {"decisions": [{"index": 0, "decision": "unchanged", "node_id": existing.id}]}

    report, _ = await _run(repo, extraction, model=_decisions_model(payload))

    assert report.entities_unchanged == 1
    assert report.entities_created == 0
    assert report.entities_updated == 0
    node = _node(repo, existing.id)
    assert node.content == "Event streaming platform."
    assert await _counts(repo) == (1, 0)


# ── Validation of model-supplied identity ──


@pytest.mark.asyncio
async def test_node_id_outside_candidate_set_falls_back_to_host_default(repo: InMemoryRepository) -> None:
    """An unknown node_id is discarded; the single exact match still merges."""
    node_type = await repo.get_or_create_node_type(AGENT, "Technology")
    assert node_type is not None
    existing = await repo.upsert_node(
        agent_id=AGENT, name="Apache Kafka", type_id=node_type.id, content="Message broker."
    )
    other_type = await repo.get_or_create_node_type(AGENT, "Team")
    assert other_type is not None
    outsider = await repo.upsert_node(agent_id=AGENT, name="Payments Team", type_id=other_type.id, content="Team.")

    extraction = ExtractionResult(
        entities=[ExtractedEntity(name="Apache Kafka", type_name="Technology", description="Event streaming platform.")]
    )
    payload = {"decisions": [{"index": 0, "decision": "merge", "node_id": outsider.id, "content": "hijacked content"}]}

    report, _ = await _run(repo, extraction, model=_decisions_model(payload))

    hijacked = _node(repo, outsider.id)
    assert hijacked.content == "Team."
    merged = _node(repo, existing.id)
    # Host default merge: keep the old fact, append the new one.
    assert merged.content == "Message broker. Event streaming platform."
    assert report.entities_updated == 1
    assert await _counts(repo) == (2, 0)


@pytest.mark.asyncio
async def test_merge_without_content_falls_back_to_host_default(repo: InMemoryRepository) -> None:
    """A merge that omits content is not retried with the model."""
    node_type = await repo.get_or_create_node_type(AGENT, "Technology")
    assert node_type is not None
    existing = await repo.upsert_node(
        agent_id=AGENT, name="Apache Kafka", type_id=node_type.id, content="Message broker."
    )
    extraction = ExtractionResult(
        entities=[ExtractedEntity(name="Apache Kafka", type_name="Technology", description="Version 4.0 released.")]
    )
    payload = {"decisions": [{"index": 0, "decision": "merge", "node_id": existing.id}]}

    report, sink = await _run(repo, extraction, model=_decisions_model(payload))

    merged = _node(repo, existing.id)
    assert merged.content == "Message broker. Version 4.0 released."
    assert report.entities_updated == 1
    assert sink.events("agent_usage")[0]["requests"] == 1


@pytest.mark.asyncio
async def test_missing_decision_falls_back_to_host_default(repo: InMemoryRepository) -> None:
    """An index the model never answered still gets a deterministic outcome."""
    node_type = await repo.get_or_create_node_type(AGENT, "Technology")
    assert node_type is not None
    existing = await repo.upsert_node(
        agent_id=AGENT, name="Apache Kafka", type_id=node_type.id, content="Message broker."
    )
    extraction = ExtractionResult(
        entities=[ExtractedEntity(name="Apache Kafka", type_name="Technology", description="Version 4.0 released.")]
    )

    report, _ = await _run(repo, extraction, model=_decisions_model({"decisions": []}))

    merged = _node(repo, existing.id)
    assert merged.content == "Message broker. Version 4.0 released."
    assert report.entities_updated == 1
    assert await _counts(repo) == (1, 0)


@pytest.mark.asyncio
async def test_create_decision_colliding_with_a_candidate_merges_instead(repo: InMemoryRepository) -> None:
    """`create` on a name the graph already holds would erase it, so it merges.

    ``upsert_node`` dedups by name: honoring this decision verbatim replaces the
    existing node's content with the one-line description instead of adding a node.
    """
    node_type = await repo.get_or_create_node_type(AGENT, "Technology")
    assert node_type is not None
    existing = await repo.upsert_node(
        agent_id=AGENT,
        name="Apache Kafka",
        type_id=node_type.id,
        content="Message broker written in Scala. Used by 200 teams.",
    )
    extraction = ExtractionResult(
        entities=[ExtractedEntity(name="Apache Kafka", type_name="Technology", description="Streaming.")]
    )
    payload = {"decisions": [{"index": 0, "decision": "create"}]}

    report, _ = await _run(repo, extraction, model=_decisions_model(payload))

    kept = _node(repo, existing.id)
    assert "Message broker written in Scala" in kept.content
    assert "Streaming." in kept.content
    assert report.entities_updated == 1
    assert report.entities_created == 0
    assert await _counts(repo) == (1, 0)


@pytest.mark.asyncio
async def test_two_entities_on_one_node_keep_both_facts(repo: InMemoryRepository) -> None:
    """A name and one of its aliases both merge; the second write chains on the first."""
    node_type = await repo.get_or_create_node_type(AGENT, "Technology")
    assert node_type is not None
    existing = await repo.upsert_node(
        agent_id=AGENT, name="Kubernetes", type_id=node_type.id, content="Container orchestrator."
    )
    await repo.register_alias(AGENT, existing.id, "K8s", source="test")

    extraction = ExtractionResult(
        entities=[
            ExtractedEntity(name="Kubernetes", type_name="Technology", description="Now at version 1.33."),
            ExtractedEntity(name="K8s", type_name="Technology", description="Runs the payments cluster."),
        ]
    )

    report, _ = await _run(repo, extraction, model=_decisions_model({"decisions": []}))

    merged = _node(repo, existing.id)
    assert "Container orchestrator." in merged.content
    assert "Now at version 1.33." in merged.content
    assert "Runs the payments cluster." in merged.content
    assert report.entities_updated == 2
    assert report.entities_created == 0
    assert await _counts(repo) == (1, 0)


# ── Temporal corrections ──


@pytest.mark.asyncio
async def test_supersedes_entity_creates_a_distinct_node_and_temporal_edge(repo: InMemoryRepository) -> None:
    """A superseding entity is never merged into its predecessor."""
    node_type = await repo.get_or_create_node_type(AGENT, "Strategy")
    assert node_type is not None
    predecessor = await repo.upsert_node(
        agent_id=AGENT, name="Metaphone3", type_id=node_type.id, content="Phonetic matching strategy."
    )

    extraction = ExtractionResult(
        entities=[
            ExtractedEntity(
                name="Metaphone3 Hybrid Strategy",
                type_name="Strategy",
                description="Hybrid phonetic strategy replacing Metaphone3.",
                supersedes="Metaphone3",
                temporal_signal="SUPERSEDES",
            )
        ]
    )

    report, _ = await _run(repo, extraction, model=_NoModelCall())

    assert report.entities_created == 1
    assert report.edges_created == 1
    nodes, edges = await _counts(repo)
    assert (nodes, edges) == (2, 1)
    summary = await repo.get_ontology_summary(AGENT)
    used = {row["name"]: row["usage_count"] for row in summary["edge_types"] if row["usage_count"] > 0}
    assert used == {"SUPERSEDES": 1}
    still_there = _node(repo, predecessor.id)
    assert still_there.content == "Phonetic matching strategy."


@pytest.mark.asyncio
async def test_unknown_temporal_signal_defaults_to_supersedes(repo: InMemoryRepository) -> None:
    """An off-contract temporal signal becomes SUPERSEDES, never a new type."""
    node_type = await repo.get_or_create_node_type(AGENT, "Strategy")
    assert node_type is not None
    await repo.upsert_node(agent_id=AGENT, name="Metaphone3", type_id=node_type.id, content="Old strategy.")
    extraction = ExtractionResult(
        entities=[
            ExtractedEntity(
                name="Metaphone3 Hybrid Strategy",
                type_name="Strategy",
                description="New strategy.",
                supersedes="Metaphone3",
                temporal_signal="replaced-by",
            )
        ]
    )

    await _run(repo, extraction, model=_NoModelCall())

    summary = await repo.get_ontology_summary(AGENT)
    used = {row["name"]: row["usage_count"] for row in summary["edge_types"] if row["usage_count"] > 0}
    assert used == {"SUPERSEDES": 1}


@pytest.mark.asyncio
async def test_supersedes_entity_is_never_offered_to_the_model(repo: InMemoryRepository) -> None:
    """The work list skips superseding entities: the host already decided."""
    node_type = await repo.get_or_create_node_type(AGENT, "Strategy")
    assert node_type is not None
    await repo.upsert_node(agent_id=AGENT, name="Metaphone3 Hybrid Strategy", type_id=node_type.id, content="Old.")
    entities = [
        ExtractedEntity(
            name="Metaphone3 Hybrid Strategy",
            type_name="Strategy",
            description="New.",
            supersedes="Metaphone3",
            temporal_signal="CORRECTS",
        )
    ]
    outcomes = await resolve_extraction_entities(repo, None, AGENT, None, entities)

    assert outcomes[0].match == "exact"
    assert build_oneshot_items(entities, outcomes) == []


# ── Idempotence ──


@pytest.mark.asyncio
async def test_replaying_the_same_extraction_adds_nothing(repo: InMemoryRepository) -> None:
    """Second pass over one extraction: 0 new nodes, 0 new edges."""
    extraction = _extraction()
    await _run(repo, extraction, model=_NoModelCall())
    first = await _counts(repo)

    payload = {"decisions": []}  # every entity falls back to the host default
    report, _ = await _run(repo, extraction, model=_decisions_model(payload))

    assert await _counts(repo) == first
    assert report.entities_created == 0
    assert report.entities_updated == 2


# ── Relations ──


@pytest.mark.asyncio
async def test_relation_with_an_unbound_endpoint_is_skipped_and_audited(repo: InMemoryRepository) -> None:
    """A relation naming an entity nobody extracted is dropped, not guessed."""
    extraction = ExtractionResult(
        entities=[ExtractedEntity(name="Payments Team", type_name="Team", description="Owns payments.")],
        relations=[
            ExtractedRelation(source_name="Payments Team", target_name="Apache Kafka", relation_type="USES"),
            ExtractedRelation(source_name="Payments Team", target_name="Payments Team", relation_type="OWNS"),
        ],
    )

    report, sink = await _run(repo, extraction, model=_NoModelCall())

    assert report.edges_created == 1
    assert report.edges_unresolved == 1
    assert report.status == "completed_with_unresolved"
    skipped = sink.events("edge_skipped_missing_node")
    assert len(skipped) == 1
    assert skipped[0]["target_present"] is False
    assert skipped[0]["reason_code"] == "missing_node"


@pytest.mark.asyncio
async def test_relation_to_a_predecessor_binds_to_the_resolved_node(repo: InMemoryRepository) -> None:
    """A temporal relation whose target is the predecessor still lands."""
    node_type = await repo.get_or_create_node_type(AGENT, "Strategy")
    assert node_type is not None
    predecessor = await repo.upsert_node(agent_id=AGENT, name="Metaphone3", type_id=node_type.id, content="Old.")
    extraction = ExtractionResult(
        entities=[
            ExtractedEntity(
                name="Metaphone3 Hybrid Strategy",
                type_name="Strategy",
                description="New.",
                supersedes="Metaphone3",
                temporal_signal="CORRECTS",
            )
        ],
        relations=[
            ExtractedRelation(
                source_name="Metaphone3 Hybrid Strategy", target_name="Metaphone3", relation_type="CORRECTS"
            )
        ],
    )

    report, sink = await _run(repo, extraction, model=_NoModelCall())

    assert sink.events("edge_skipped_missing_node") == []
    # Both endpoints bind, but the relation lands on the temporal pair, so the
    # host steps around it and only the temporal edge is written.
    assert report.edges_created == 1
    assert report.edges_unchanged == 1
    skipped = sink.events("edge_skipped_temporal_pair")
    assert [fields["reason_code"] for fields in skipped] == ["temporal_pair"]
    nodes, edges = await _counts(repo)
    assert (nodes, edges) == (2, 1)
    assert predecessor.id in {node.id for node in await repo.find_nodes_by_name(AGENT, "Metaphone3")}


@pytest.mark.asyncio
async def test_temporal_edge_survives_a_relation_over_the_same_pair(repo: InMemoryRepository) -> None:
    """Regression: edge-type drift must not overwrite SUPERSEDES with a relation type.

    ``upsert_edge`` rewrites the type of a lone edge between an ordered pair, so a
    relation such as (B, REPLACED, A) written after the temporal edge would erase it.
    """
    await _run(
        repo,
        ExtractionResult(
            entities=[
                ExtractedEntity(name="Metaphone3", type_name="Strategy", description="Phonetic matching strategy.")
            ]
        ),
        model=_NoModelCall(),
        episode_id=1,
    )
    predecessors = await repo.find_nodes_by_name(AGENT, "Metaphone3")
    assert len(predecessors) == 1
    predecessor_id = predecessors[0].id

    report, sink = await _run(
        repo,
        ExtractionResult(
            entities=[
                ExtractedEntity(
                    name="Metaphone3 8-Character Codes",
                    type_name="Strategy",
                    description="Longer phonetic codes replacing Metaphone3.",
                    supersedes="Metaphone3",
                    temporal_signal="SUPERSEDES",
                )
            ],
            relations=[
                ExtractedRelation(
                    source_name="Metaphone3 8-Character Codes",
                    target_name="Metaphone3",
                    relation_type="REPLACED",
                )
            ],
        ),
        model=_NoModelCall(),
        episode_id=2,
    )

    successors = await repo.find_nodes_by_name(AGENT, "Metaphone3 8-Character Codes")
    assert len(successors) == 1
    assert _edge_types_between(repo, successors[0].id, predecessor_id) == ["SUPERSEDES"]
    assert report.edges_created == 1
    assert report.edges_unchanged == 1
    assert [fields["reason_code"] for fields in sink.events("edge_skipped_temporal_pair")] == ["temporal_pair"]


@pytest.mark.asyncio
async def test_a_relation_on_the_reverse_pair_keeps_both_edges(repo: InMemoryRepository) -> None:
    """Drift is keyed on the ordered pair, so the mirror relation is left alone."""
    await _run(
        repo,
        ExtractionResult(
            entities=[
                ExtractedEntity(name="Metaphone3", type_name="Strategy", description="Phonetic matching strategy.")
            ]
        ),
        model=_NoModelCall(),
        episode_id=1,
    )
    predecessors = await repo.find_nodes_by_name(AGENT, "Metaphone3")
    assert len(predecessors) == 1
    predecessor_id = predecessors[0].id

    report, sink = await _run(
        repo,
        ExtractionResult(
            entities=[
                ExtractedEntity(
                    name="Metaphone3 8-Character Codes",
                    type_name="Strategy",
                    description="Longer phonetic codes replacing Metaphone3.",
                    supersedes="Metaphone3",
                    temporal_signal="SUPERSEDES",
                ),
                ExtractedEntity(name="Metaphone3", type_name="Strategy", description="Phonetic matching strategy."),
            ],
            relations=[
                ExtractedRelation(
                    source_name="Metaphone3",
                    target_name="Metaphone3 8-Character Codes",
                    relation_type="MEASURED_BY",
                )
            ],
        ),
        model=_decisions_model({"decisions": [{"index": 1, "decision": "unchanged", "node_id": predecessor_id}]}),
        episode_id=2,
    )

    successors = await repo.find_nodes_by_name(AGENT, "Metaphone3 8-Character Codes")
    assert len(successors) == 1
    successor_id = successors[0].id
    assert _edge_types_between(repo, successor_id, predecessor_id) == ["SUPERSEDES"]
    assert _edge_types_between(repo, predecessor_id, successor_id) == ["MEASURED_BY"]
    assert report.edges_created == 2
    assert report.edges_unchanged == 0
    assert sink.events("edge_skipped_temporal_pair") == []


@pytest.mark.asyncio
async def test_edge_upsert_returning_none_is_counted_and_audited(repo: InMemoryRepository) -> None:
    """Both edge loops treat a None upsert as unresolved and say so with ids only."""

    class _RefusingRepo(InMemoryRepository):
        async def upsert_edge(self, *args: Any, **kwargs: Any) -> None:
            del args, kwargs
            return None

    refusing = _RefusingRepo()
    node_type = await refusing.get_or_create_node_type(AGENT, "Strategy")
    assert node_type is not None
    await refusing.upsert_node(agent_id=AGENT, name="Metaphone3", type_id=node_type.id, content="Old strategy.")
    extraction = ExtractionResult(
        entities=[
            ExtractedEntity(
                name="Metaphone3 Hybrid Strategy",
                type_name="Strategy",
                description="New strategy.",
                supersedes="Metaphone3",
                temporal_signal="SUPERSEDES",
            ),
            ExtractedEntity(name="Search Team", type_name="Team", description="Owns the matcher."),
        ],
        relations=[
            ExtractedRelation(source_name="Search Team", target_name="Metaphone3 Hybrid Strategy", relation_type="OWNS")
        ],
    )

    report, sink = await _run(refusing, extraction, model=_NoModelCall())

    assert report.edges_created == 0
    # One temporal edge and one relation, both refused by the repository.
    assert report.edges_unresolved == 2
    assert report.status == "completed_with_unresolved"
    failed = sink.events("edge_skipped_upsert_failed")
    assert len(failed) == 2
    assert {fields["reason_code"] for fields in failed} == {"upsert_failed"}
    for fields in failed:
        assert isinstance(fields["source_id"], int)
        assert isinstance(fields["target_id"], int)
    assert sink.events("edge_skipped_missing_node") == []


# ── Work list and prompt shape ──


@pytest.mark.asyncio
async def test_work_list_holds_only_entities_with_candidates(repo: InMemoryRepository) -> None:
    """Entities the graph knows nothing about never reach the model."""
    node_type = await repo.get_or_create_node_type(AGENT, "Technology")
    assert node_type is not None
    await repo.upsert_node(
        agent_id=AGENT,
        name="Apache Kafka",
        type_id=node_type.id,
        content="Message broker.",
        properties={"_source_episode": 7, "vendor": "Apache", "nested": {"skip": True}},
    )
    entities = _extraction().entities
    outcomes = await resolve_extraction_entities(repo, None, AGENT, None, entities)
    items = build_oneshot_items(entities, outcomes)

    assert [item.index for item in items] == [0]
    assert [candidate.name for candidate in items[0].candidates] == ["Apache Kafka"]
    assert items[0].candidates[0].properties == {"vendor": "Apache"}
    rendered = render_oneshot_items(items)
    assert rendered.splitlines()[0].startswith("0 | Apache Kafka | Technology |")
    assert "node_id=" in rendered.splitlines()[1]


def test_oneshot_prompt_is_short_and_shows_the_expected_json() -> None:
    """The decision prompt stays terse: local decode time is the budget."""
    agent = build_librarian_agent(QWEN_CONFIG, profile="qwen_oneshot")
    prompt = "\n".join(agent._system_prompts)

    assert len(agent._system_prompts) <= 15
    assert '"decisions"' in prompt
    assert "under 600 characters" in prompt
    assert "you have no tools" in prompt
    assert "node_id must be a candidate id listed under that index" in prompt


# ── Profile selection ──


def test_qwen_models_select_oneshot_and_hosted_keeps_its_tools() -> None:
    """Default selection follows is_qwen_model; hosted behavior is untouched."""
    from neocortex.extraction.schemas import CurationSummary

    qwen = build_librarian_agent(QWEN_CONFIG)
    hosted = build_librarian_agent(
        AgentInferenceConfig(model_name="openai-responses:gpt-5.4-mini", use_test_model=True)
    )

    assert qwen.output_type is OneshotDecisions
    assert qwen._function_toolset.tools == {}
    assert hosted.output_type is CurationSummary
    assert len(hosted._function_toolset.tools) == 9


@pytest.mark.asyncio
async def test_pipeline_selects_the_oneshot_profile_for_qwen(repo: InMemoryRepository) -> None:
    """run_extraction routes a Qwen librarian through the one-shot module."""
    from neocortex.extraction.pipeline import run_extraction

    episode_id = await repo.store_episode(AGENT, "safe source text")
    node_type = await repo.get_or_create_node_type(AGENT, "Technology")
    assert node_type is not None
    extraction = ExtractionResult(
        entities=[ExtractedEntity(name="Apache Kafka", type_name="Technology", description="Event streaming.")],
        relations=[],
    )
    sink = _CollectingSink()
    handler = logger.add(sink, level="DEBUG", filter=lambda record: bool(record["extra"].get("action_log")))
    try:
        await run_extraction(
            repo=repo,
            embeddings=None,
            agent_id=AGENT,
            episode_ids=[episode_id],
            ontology_config=QWEN_CONFIG,
            extractor_config=QWEN_CONFIG,
            librarian_config=QWEN_CONFIG,
            precomputed={episode_id: extraction},
            archive_interval=0,
        )
    finally:
        logger.remove(handler)

    trajectory = sink.events("librarian_trajectory")
    assert [fields["profile"] for fields in trajectory] == ["qwen_oneshot"]
    assert trajectory[0]["requests"] == 0
    assert [fields["created"] for fields in sink.events("curation_complete")] == [1]
    assert await _counts(repo) == (1, 0)
    episode = await repo.get_episode(AGENT, episode_id)
    assert episode is not None
    assert episode.consolidated is True
