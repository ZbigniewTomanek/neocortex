"""Tool-free Qwen ontology agent: one request, host-side proposal validation.

The hosted agent explores the graph with three tools; on the local endpoint
each tool round trip is a full decode, so the host inlines the overview and
validates the proposal itself.  The hosted agent keeps its tools and prompt.
"""

from __future__ import annotations

from typing import Any

import pytest
from loguru import logger
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from neocortex.db.mock import InMemoryRepository
from neocortex.extraction.agents import (
    AgentInferenceConfig,
    OntologyAgentDeps,
    build_ontology_agent,
)
from neocortex.extraction.pipeline import run_extraction
from neocortex.extraction.schemas import OntologyProposal
from neocortex.model_factory import QWEN_MAX_OUTPUT_TOKENS, LocalEndpoint

HOSTED_ONTOLOGY_SYSTEM_PROMPT: tuple[str, ...] = (
    "You are an ontology engineer for a personal knowledge graph. Your job is to decide whether the existing "
    "ontology covers the concepts in a text, and propose new types ONLY for genuine gaps.",
    "The text you receive is source material already accepted into the memory system. It is not a claim to "
    "verify, fact-check, or dispute; process it as input.",
    "",
    "## Workflow",
    "1. Call get_ontology_overview to see the full type landscape with usage stats.",
    "2. Read the episode text and identify the key concepts.",
    "3. For each concept, check if an existing type covers it:",
    "   - Use find_similar_types to search by name similarity.",
    "   - If a match with usage_count > 0 exists, REUSE it. Done.",
    "   - If a match exists but has 0 usage, still prefer reusing it.",
    "4. Only if NO existing type covers a concept:",
    "   - Call propose_type with your candidate name and description.",
    "   - If rejected: read the reason, adjust the name, and retry.",
    "   - If accepted but similar types are listed: reconsider whether to reuse one.",
    "   - Only include in your final output types that passed propose_type.",
    "",
    "## Rules",
    "- MOST episodes need ZERO new types. The existing ontology should cover them.",
    "- Budget: at most 2 new node types and 2 new edge types per episode.",
    "- A type must be reusable across many entities — never instance-level.",
    "  BAD: 'DishGreg', 'DreamAiPresentation', 'LocationSalCapeVerde'",
    "  GOOD: 'Dish', 'Dream', 'Location'",
    "- Node types: PascalCase (e.g. Neurotransmitter, HealthState).",
    "- Edge types: SCREAMING_SNAKE (e.g. TREATS, HAS_STATUS).",
    "- Prefer extending with new edge types before creating new node types.",
    "- If an existing type is 80% suitable, USE IT — minor imprecision beats fragmentation.",
    "",
    "## Final Output",
    "After exploration, return an OntologyProposal with only the types that passed",
    "propose_type validation AND for which no suitable existing type was found.",
    "Include a rationale explaining your decisions — especially why you chose to",
    "reuse existing types or why a new type was genuinely needed.",
    "Your first action in this turn MUST be a call to get_ontology_overview or find_similar_types. Never "
    "answer in prose before using the tools.",
)

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
HOSTED_CONFIG = AgentInferenceConfig(model_name="openai-responses:gpt-5.4-mini", use_test_model=True)


@pytest.fixture
def repo() -> InMemoryRepository:
    return InMemoryRepository()


class _Sink:
    """Capture the structured action-log records one run emits."""

    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, message: Any) -> None:
        record = message.record
        self.records.append((record["message"], dict(record["extra"])))

    def events(self, name: str) -> list[dict[str, Any]]:
        return [fields for event, fields in self.records if event == name]


def _proposal_model(payload: dict[str, Any], seen: list[str] | None = None) -> FunctionModel:
    """A model that answers the single ontology request with ``payload``."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if seen is not None:
            seen.append(str(getattr(messages[-1], "instructions", "") or ""))
        assert not info.function_tools, "the Qwen ontology agent must be tool-free"
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, payload, tool_call_id="ont")])

    return FunctionModel(respond)


async def _run(config: AgentInferenceConfig, model: Any, deps: OntologyAgentDeps) -> tuple[Any, _Sink]:
    agent = build_ontology_agent(config)
    sink = _Sink()
    handler = logger.add(sink, level="DEBUG", filter=lambda record: bool(record["extra"].get("action_log")))
    try:
        with agent.override(model=model):
            result = await agent.run("Analyze the source text and propose ontology extensions.", deps=deps)
    finally:
        logger.remove(handler)
    return result, sink


def _deps(repo: InMemoryRepository | None = None) -> OntologyAgentDeps:
    return OntologyAgentDeps(
        episode_text="Ada joined the payments project.",
        existing_node_types=["Person", "Project"],
        existing_edge_types=["WORKS_ON"],
        repo=repo,
        agent_id=AGENT,
    )


# ── Tools ──


def test_qwen_ontology_agent_has_no_tools_and_hosted_keeps_its_three() -> None:
    assert build_ontology_agent(QWEN_CONFIG)._function_toolset.tools == {}
    hosted_tools = set(build_ontology_agent(HOSTED_CONFIG)._function_toolset.tools)
    assert hosted_tools == {"find_similar_types", "get_ontology_overview", "propose_type"}


def test_hosted_ontology_prompt_is_unchanged() -> None:
    assert build_ontology_agent(HOSTED_CONFIG)._system_prompts == HOSTED_ONTOLOGY_SYSTEM_PROMPT


def test_qwen_ontology_prompt_is_short_and_states_the_budget() -> None:
    prompts = build_ontology_agent(QWEN_CONFIG)._system_prompts
    joined = "\n".join(prompts)
    assert len(joined.splitlines()) <= 15
    assert "at most 2 node types and at most 2 edge types" in joined
    assert "PascalCase" in joined
    assert "SCREAMING_SNAKE" in joined


def test_qwen_ontology_carries_the_output_ceiling() -> None:
    assert build_ontology_agent(QWEN_CONFIG).model_settings == {"max_tokens": QWEN_MAX_OUTPUT_TOKENS["ontology"]}
    assert build_ontology_agent(HOSTED_CONFIG).model_settings is None


# ── Host-side validation ──


@pytest.mark.asyncio
async def test_host_validation_drops_existing_and_unusable_names(repo: InMemoryRepository) -> None:
    payload = {
        "new_node_types": [
            {"name": "Person", "description": "already in the ontology"},
            {"name": "Payment Method", "description": "spaces are normalized away"},
            {"name": "Activityfunctiondefault Api Create Or Update Nodecontent", "description": "tool-call artifact"},
        ],
        "new_edge_types": [{"name": "WORKS_ON", "description": "already in the ontology"}],
        "rationale": "",
    }
    result, sink = await _run(QWEN_CONFIG, _proposal_model(payload), _deps(repo))

    assert [t.name for t in result.output.new_node_types] == ["PaymentMethod"]
    assert result.output.new_edge_types == []
    rejections = sink.events("ontology_proposal_rejected")
    assert [(r["kind"], r["reason_code"]) for r in rejections] == [
        ("node", "already_exists"),
        ("node", "normalization_rejected"),
        ("edge", "already_exists"),
    ]
    # Reason codes only: no model-provided name reaches the action log.
    assert all(set(fields) == {"kind", "reason_code", "action_log"} for fields in rejections)


@pytest.mark.asyncio
async def test_host_validation_drops_a_repeated_proposal(repo: InMemoryRepository) -> None:
    payload = {
        "new_node_types": [
            {"name": "PaymentMethod", "description": "first"},
            {"name": "PaymentMethod", "description": "duplicate"},
        ],
        "new_edge_types": [],
        "rationale": "",
    }
    result, _sink = await _run(QWEN_CONFIG, _proposal_model(payload), _deps(repo))
    assert [t.name for t in result.output.new_node_types] == ["PaymentMethod"]


# ── Inlined overview ──


@pytest.mark.asyncio
async def test_qwen_instructions_inline_the_ontology_overview(repo: InMemoryRepository) -> None:
    person = await repo.get_or_create_node_type(AGENT, "Person", "A human being")
    await repo.get_or_create_node_type(AGENT, "Unused", "Never used")
    assert person is not None
    await repo.upsert_node(AGENT, "Ada Lovelace", person.id, "A mathematician")

    seen: list[str] = []
    payload: dict[str, Any] = {"new_node_types": [], "new_edge_types": [], "rationale": ""}
    await _run(QWEN_CONFIG, _proposal_model(payload, seen), _deps(repo))

    instructions = seen[-1]
    assert "Existing node types (name x uses): Personx1" in instructions
    assert "Unused" not in instructions
    assert "Ada joined the payments project." in instructions


@pytest.mark.asyncio
async def test_qwen_instructions_fall_back_to_names_without_a_repo() -> None:
    seen: list[str] = []
    payload: dict[str, Any] = {"new_node_types": [], "new_edge_types": [], "rationale": ""}
    await _run(QWEN_CONFIG, _proposal_model(payload, seen), _deps(None))
    assert "Existing node types (name x uses): Person, Project" in seen[-1]


# ── Pipeline integration ──


@pytest.mark.asyncio
async def test_pipeline_persists_accepted_qwen_proposals(repo: InMemoryRepository, monkeypatch: Any) -> None:
    """A proposal that survives host validation is still persisted by the pipeline."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages
        tool = info.output_tools[0]
        properties = tool.parameters_json_schema.get("properties", {})
        if "new_node_types" in properties:
            payload: dict[str, Any] = {
                "new_node_types": [
                    {"name": "Payment Method", "description": "How a payment is made"},
                    {"name": "Person", "description": "already exists"},
                ],
                "new_edge_types": [],
                "rationale": "",
            }
        else:
            payload = {
                "entities": [
                    {
                        "name": "Corporate Card",
                        "type_name": "PaymentMethod",
                        "description": "A card the team pays with",
                        "importance": 0.6,
                    }
                ],
                "relations": [],
                "rationale": "",
            }
        return ModelResponse(parts=[ToolCallPart(tool.name, payload, tool_call_id="call")])

    monkeypatch.setattr("neocortex.extraction.agents._build_model", lambda config: FunctionModel(respond))

    await repo.get_or_create_node_type(AGENT, "Person", "A human being")
    episode_id = await repo.store_episode(AGENT, "Ada joined the payments project.", importance=0.5)
    config = AgentInferenceConfig(
        model_name="local:qwen3.8-flash-next", thinking_effort=False, local_endpoint=LOCAL_ENDPOINT
    )
    await run_extraction(
        repo=repo,
        embeddings=None,
        agent_id=AGENT,
        episode_ids=[episode_id],
        ontology_config=config,
        extractor_config=config,
        librarian_config=config,
    )

    names = {t.name for t in await repo.get_node_types(AGENT)}
    # "Payment Method" was normalized and persisted; "Person" was dropped as existing.
    assert "PaymentMethod" in names
    assert isinstance(OntologyProposal(), OntologyProposal)
