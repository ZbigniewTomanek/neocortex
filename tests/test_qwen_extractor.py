"""Qwen extractor: entity budget, terse instructions, unchanged hosted prompt.

The local endpoint decodes at ~34 tokens/s, so the extractor's output size is
the dominant cost of an episode.  The budget is stated in the prompt and
enforced by the host; the hosted agent must not notice any of it.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from neocortex.extraction.agents import (
    AgentInferenceConfig,
    ExtractorAgentDeps,
    build_extractor_agent,
    cap_extraction_entities,
    count_capped_relations,
    qwen_entity_cap,
)
from neocortex.extraction.schemas import ExtractedEntity, ExtractedRelation, ExtractionResult
from neocortex.model_factory import QWEN_MAX_OUTPUT_TOKENS, LocalEndpoint

HOSTED_EXTRACTOR_SYSTEM_PROMPT: tuple[str, ...] = (
    "You are a knowledge extraction specialist. Extract entities and relations from the given text, aligned "
    "to the provided ontology types.",
    "The text you receive is source material already accepted into the memory system. It is not a claim to "
    "verify, fact-check, or dispute; extract it as input.",
    "Every entity must use an existing node type name.",
    "Every relation must use an existing edge type name.",
    "Use the text as the only evidence source — do not invent facts.",
    "Prefer canonical, normalized names for entities.",
    "Assign an importance score (0.0-1.0) to each entity:\n  0.0-0.3: Peripheral, contextual detail\n  "
    "0.3-0.6: Standard factual entity\n  0.6-0.8: Central concept referenced multiple times\n  0.8-1.0: "
    "Critical domain entity (core drug, disease, mechanism)",
    "",
    "## Temporal Corrections",
    "When the text contains signals that new information CORRECTS or SUPERSEDES",
    "previous knowledge, you MUST populate the `supersedes` and `temporal_signal`",
    "fields on the relevant entity:",
    "",
    "- CORRECTION signals: 'CORRECTION', 'actually', 'error', 'bug fix',",
    "  'misconception', 'wrong', 'incorrect'",
    "  → Set temporal_signal='CORRECTS', supersedes='<old entity name>'",
    "",
    "- SUPERSESSION signals: 'UPDATE', 'REVERSAL', 'instead of', 'no longer',",
    "  'changed to', 'replaced by', 'switched from', 'new strategy',",
    "  'decided to switch', 'moving from X to Y'",
    "  → Set temporal_signal='SUPERSEDES', supersedes='<old entity name>'",
    "",
    "When a correction is detected, use a VERSIONED name for the new entity:",
    "  - Old: 'Metaphone3' → New: 'Metaphone3 Hybrid Strategy'",
    "  - Old: 'Jonas Weber' role → New entity: 'Jonas Weber Security Role'",
    "This prevents the librarian from merging the new entity into the old one.",
    "Return only the structured result. Never write prose, commentary, or explanation outside the schema.",
)

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
HOSTED_CONFIG = AgentInferenceConfig(model_name="openai-responses:gpt-5.4-mini", use_test_model=True)


# ── Cap formula ──


@pytest.mark.parametrize(("words", "expected"), [(10, 4), (40, 5), (93, 12), (200, 12), (500, 12)])
def test_entity_cap_formula(words: int, expected: int) -> None:
    assert qwen_entity_cap(" ".join(["word"] * words)) == expected


def test_entity_cap_handles_empty_text() -> None:
    assert qwen_entity_cap("") == 4


# ── Host enforcement ──


def _entity(name: str, importance: float) -> ExtractedEntity:
    return ExtractedEntity(name=name, type_name="Thing", description=name, importance=importance)


def _result() -> ExtractionResult:
    return ExtractionResult(
        entities=[_entity("A", 0.9), _entity("B", 0.2), _entity("C", 0.5), _entity("D", 0.5)],
        relations=[
            ExtractedRelation(source_name="A", target_name="C", relation_type="LINKS"),
            ExtractedRelation(source_name="A", target_name="B", relation_type="LINKS"),
            ExtractedRelation(source_name="B", target_name="D", relation_type="LINKS"),
        ],
    )


def test_cap_keeps_top_entities_by_importance_in_document_order() -> None:
    capped = cap_extraction_entities(_result(), 3)
    # B (0.2) is the only entity outside the top three; ties keep extractor order.
    assert [entity.name for entity in capped.entities] == ["A", "C", "D"]


def test_cap_drops_relations_with_a_dropped_endpoint() -> None:
    capped = cap_extraction_entities(_result(), 3)
    assert [(r.source_name, r.target_name) for r in capped.relations] == [("A", "C")]


def test_cap_is_a_no_op_below_the_budget() -> None:
    result = _result()
    assert cap_extraction_entities(result, 4) is result
    assert cap_extraction_entities(result, 12) is result


def test_count_capped_relations_reports_the_drop_and_its_endpoints() -> None:
    before = _result()
    after = cap_extraction_entities(before, 3)
    dropped, pairs = count_capped_relations(before, after)
    # A->B and B->D lose B; only A->C survives.
    assert dropped == 2
    assert pairs == [("A", "B"), ("B", "D")]


def test_count_capped_relations_is_zero_when_nothing_was_dropped() -> None:
    result = _result()
    assert count_capped_relations(result, result) == (0, [])


def test_count_capped_relations_counts_duplicates_once_each() -> None:
    entities = [_entity("A", 0.9), _entity("B", 0.1)]
    duplicated = ExtractionResult(
        entities=entities,
        relations=[
            ExtractedRelation(source_name="A", target_name="B", relation_type="LINKS"),
            ExtractedRelation(source_name="A", target_name="B", relation_type="LINKS"),
        ],
    )
    after = ExtractionResult(entities=[entities[0]], relations=[])
    assert count_capped_relations(duplicated, after) == (2, [("A", "B"), ("A", "B")])


# ── Prompts ──


def test_hosted_extractor_prompt_is_unchanged() -> None:
    """Hosted behaviour is out of scope for the Qwen work: pin its prompt."""
    agent = build_extractor_agent(HOSTED_CONFIG)
    assert agent._system_prompts == HOSTED_EXTRACTOR_SYSTEM_PROMPT


def test_qwen_extractor_prompt_is_short_and_keeps_the_temporal_rules() -> None:
    agent = build_extractor_agent(QWEN_CONFIG)
    prompts = agent._system_prompts
    assert prompts != HOSTED_EXTRACTOR_SYSTEM_PROMPT
    joined = "\n".join(prompts)
    assert len(joined.splitlines()) <= 25
    assert "temporal_signal='CORRECTS'" in joined
    assert "temporal_signal='SUPERSEDES'" in joined
    assert "supersedes" in joined
    assert "VERSIONED name" in joined
    assert "160 characters" in joined
    assert "every explicit number, date, percentage, version, and code ID" in joined
    assert "also copy those explicit scalar facts" in joined


def test_qwen_extractor_carries_the_output_ceiling_and_hosted_does_not() -> None:
    assert build_extractor_agent(QWEN_CONFIG).model_settings == {"max_tokens": QWEN_MAX_OUTPUT_TOKENS["extractor"]}
    assert build_extractor_agent(HOSTED_CONFIG).model_settings is None


def test_config_overrides_the_output_ceiling() -> None:
    from dataclasses import replace

    agent = build_extractor_agent(replace(QWEN_CONFIG, max_output_tokens=999))
    assert agent.model_settings == {"max_tokens": 999}


# ── Retries ──


def test_qwen_extractor_allows_an_extra_output_retry_and_hosted_keeps_the_default() -> None:
    """Qwen exhausted the single default output-validation retry and raised UnexpectedModelBehavior.

    One extra retry recovers the attempt in-process; the hosted agent keeps pydantic-ai's default.
    """
    assert build_extractor_agent(QWEN_CONFIG)._max_result_retries == 2
    assert build_extractor_agent(QWEN_CONFIG)._max_tool_retries == 2
    assert build_extractor_agent(HOSTED_CONFIG)._max_result_retries == 1
    assert build_extractor_agent(HOSTED_CONFIG)._max_tool_retries == 1


# ── Instructions ──


def _capture_instructions(config: AgentInferenceConfig, deps: ExtractorAgentDeps) -> str:
    """Run the extractor once against a stub model and return the request instructions."""
    seen: list[str] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(str(getattr(messages[-1], "instructions", "") or ""))
        tool = info.output_tools[0]
        return ModelResponse(parts=[ToolCallPart(tool.name, {"entities": [], "relations": []}, tool_call_id="x")])

    agent = build_extractor_agent(config)

    async def run() -> None:
        with agent.override(model=FunctionModel(respond)):
            await agent.run("Extract entities and relations from the source text.", deps=deps)

    import asyncio

    asyncio.run(run())
    return seen[-1]


def _deps(text: str, **kwargs: Any) -> ExtractorAgentDeps:
    return ExtractorAgentDeps(
        episode_text=text,
        node_types=["Person", "Project"],
        edge_types=["WORKS_ON"],
        node_type_descriptions={"Person": "A human being", "Project": "A unit of work"},
        edge_type_descriptions={"WORKS_ON": "Assignment"},
        **kwargs,
    )


def test_qwen_instructions_state_the_budget() -> None:
    text = " ".join(["word"] * 40)  # cap 5
    instructions = _capture_instructions(QWEN_CONFIG, _deps(text))
    assert "at most 5 entities and at most 10 relations" in instructions


def test_qwen_instructions_drop_descriptions_for_types_the_graph_already_uses() -> None:
    deps = _deps("short text", type_examples={"Person": ["Ada Lovelace"]})
    instructions = _capture_instructions(QWEN_CONFIG, deps)
    assert "- Person\n" in instructions
    assert "- Person: A human being" not in instructions
    # An unused type still needs its description to be usable.
    assert "- Project: A unit of work" in instructions


def test_hosted_instructions_keep_descriptions_and_evidence_rule() -> None:
    deps = _deps("short text", type_examples={"Person": ["Ada Lovelace"]})
    instructions = _capture_instructions(HOSTED_CONFIG, deps)
    assert "- Person: A human being" in instructions
    assert "Include evidence text in relation properties when possible." in instructions
    assert "at most" not in instructions


# ── Pipeline enforcement ──


@pytest.mark.asyncio
async def test_pipeline_caps_an_over_producing_qwen_extractor(monkeypatch: pytest.MonkeyPatch) -> None:
    """The host trims the extraction and says so, with counts only."""
    from loguru import logger

    from neocortex.db.mock import InMemoryRepository
    from neocortex.extraction.pipeline import run_extraction

    entities = [
        {
            "name": f"Entity {index}",
            "type_name": "Thing",
            "description": "A thing",
            "importance": round(0.05 * index, 2),
        }
        for index in range(1, 15)
    ]

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages
        tool = info.output_tools[0]
        if "new_node_types" in tool.parameters_json_schema.get("properties", {}):
            payload: dict[str, Any] = {"new_node_types": [], "new_edge_types": [], "rationale": ""}
        else:
            payload = {"entities": entities, "relations": [], "rationale": ""}
        return ModelResponse(parts=[ToolCallPart(tool.name, payload, tool_call_id="call")])

    monkeypatch.setattr("neocortex.extraction.agents._build_model", lambda config: FunctionModel(respond))

    repo = InMemoryRepository()
    await repo.get_or_create_node_type("capped-agent", "Thing", "A thing")
    text = " ".join(["word"] * 40)  # cap 5
    episode_id = await repo.store_episode("capped-agent", text, importance=0.5)
    config = AgentInferenceConfig(
        model_name="local:qwen3.8-flash-next", thinking_effort=False, local_endpoint=LOCAL_ENDPOINT
    )

    records: list[tuple[str, dict[str, Any]]] = []
    handler = logger.add(
        lambda message: records.append((message.record["message"], dict(message.record["extra"]))),
        level="DEBUG",
        filter=lambda record: bool(record["extra"].get("action_log")),
    )
    try:
        await run_extraction(
            repo=repo,
            embeddings=None,
            agent_id="capped-agent",
            episode_ids=[episode_id],
            ontology_config=config,
            extractor_config=config,
            librarian_config=config,
        )
    finally:
        logger.remove(handler)

    capped = [fields for event, fields in records if event == "extractor_cardinality_capped"]
    assert len(capped) == 1
    assert (capped[0]["before"], capped[0]["after"], capped[0]["cap"]) == (14, 5, 5)
    cardinality = [fields for event, fields in records if event == "extractor_cardinality"]
    assert cardinality[0]["entity_count"] == 5
    # Only the five most important entities were written.
    summary = await repo.get_ontology_summary("capped-agent")
    assert int(summary["total_nodes"]) == 5


@pytest.mark.asyncio
async def test_pipeline_does_not_cap_a_hosted_extractor(monkeypatch: pytest.MonkeyPatch) -> None:
    from loguru import logger

    from neocortex.db.mock import InMemoryRepository
    from neocortex.extraction.pipeline import run_extraction

    entities = [
        {"name": f"Entity {index}", "type_name": "Thing", "description": "A thing", "importance": 0.5}
        for index in range(1, 15)
    ]

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages
        tool = info.output_tools[0]
        if "new_node_types" in tool.parameters_json_schema.get("properties", {}):
            payload: dict[str, Any] = {"new_node_types": [], "new_edge_types": [], "rationale": ""}
        elif "entities" in tool.parameters_json_schema.get("properties", {}):
            payload = {"entities": entities, "relations": [], "rationale": ""}
        else:  # the hosted librarian's curation summary
            payload = {}
        return ModelResponse(parts=[ToolCallPart(tool.name, payload, tool_call_id="call")])

    monkeypatch.setattr("neocortex.extraction.agents._build_model", lambda config: FunctionModel(respond))

    repo = InMemoryRepository()
    await repo.get_or_create_node_type("hosted-agent", "Thing", "A thing")
    episode_id = await repo.store_episode("hosted-agent", " ".join(["word"] * 40), importance=0.5)
    records: list[str] = []
    handler = logger.add(
        lambda message: records.append(message.record["message"]),
        level="DEBUG",
        filter=lambda record: bool(record["extra"].get("action_log")),
    )
    try:
        await run_extraction(
            repo=repo,
            embeddings=None,
            agent_id="hosted-agent",
            episode_ids=[episode_id],
            ontology_config=HOSTED_CONFIG,
            extractor_config=HOSTED_CONFIG,
            librarian_config=HOSTED_CONFIG,
            librarian_use_tools=False,
        )
    finally:
        logger.remove(handler)

    assert "extractor_cardinality_capped" not in records


@pytest.mark.asyncio
async def test_pipeline_logs_relations_dropped_by_cap_without_any_entity_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cap's collateral edge loss is counted, and only counted (D-13)."""
    from loguru import logger

    from neocortex.db.mock import InMemoryRepository
    from neocortex.extraction.pipeline import run_extraction

    # 40 words gives a cap of 5.  Five important entities survive; the sixth,
    # "Peripheral Detail", is dropped and takes exactly one relation with it.
    entities = [
        {"name": f"Entity {index}", "type_name": "Thing", "description": "A thing", "importance": 0.9}
        for index in range(1, 6)
    ]
    entities.append({"name": "Peripheral Detail", "type_name": "Thing", "description": "A thing", "importance": 0.01})
    relations = [
        {"source_name": "Entity 1", "target_name": "Entity 2", "relation_type": "LINKS"},
        {"source_name": "Entity 1", "target_name": "Peripheral Detail", "relation_type": "LINKS"},
    ]

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages
        tool = info.output_tools[0]
        if "new_node_types" in tool.parameters_json_schema.get("properties", {}):
            payload: dict[str, Any] = {"new_node_types": [], "new_edge_types": [], "rationale": ""}
        else:
            payload = {"entities": entities, "relations": relations, "rationale": ""}
        return ModelResponse(parts=[ToolCallPart(tool.name, payload, tool_call_id="call")])

    monkeypatch.setattr("neocortex.extraction.agents._build_model", lambda config: FunctionModel(respond))

    repo = InMemoryRepository()
    await repo.get_or_create_node_type("dropped-relation-agent", "Thing", "A thing")
    await repo.get_or_create_edge_type("dropped-relation-agent", "LINKS", "A link")
    episode_id = await repo.store_episode("dropped-relation-agent", " ".join(["word"] * 40), importance=0.5)
    config = AgentInferenceConfig(
        model_name="local:qwen3.8-flash-next", thinking_effort=False, local_endpoint=LOCAL_ENDPOINT
    )

    records: list[tuple[str, dict[str, Any]]] = []
    handler = logger.add(
        lambda message: records.append((message.record["message"], dict(message.record["extra"]))),
        level="DEBUG",
        filter=lambda record: bool(record["extra"].get("action_log")),
    )
    try:
        await run_extraction(
            repo=repo,
            embeddings=None,
            agent_id="dropped-relation-agent",
            episode_ids=[episode_id],
            ontology_config=config,
            extractor_config=config,
            librarian_config=config,
        )
    finally:
        logger.remove(handler)

    capped = [fields for event, fields in records if event == "extractor_cardinality_capped"]
    assert len(capped) == 1
    assert capped[0]["relations_dropped_by_cap"] == 1
    assert capped[0]["relations_before"] == 2
    assert capped[0]["relations_after"] == 1
    # The dropped endpoints are entity names; the audit log is privacy-scanned,
    # so not one of them may appear in any field of any record.
    for _event, fields in records:
        assert "Peripheral Detail" not in str(fields)
