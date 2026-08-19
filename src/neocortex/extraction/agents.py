"""Three-agent extraction pipeline: ontology, extractor, librarian.

Each agent is built via a factory function that accepts an inference config.
Agents are domain-agnostic — they work with any text, not just medical content.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from loguru import logger
from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model
from pydantic_ai.models.test import TestModel
from pydantic_ai.settings import ModelSettings, ThinkingLevel

from neocortex.model_factory import LocalEndpoint, build_model, build_model_settings

if TYPE_CHECKING:
    from neocortex.db.protocol import MemoryRepository
    from neocortex.embedding_service import EmbeddingService

from neocortex.extraction.schemas import (
    CurationSummary,
    ExtractedEntity,
    ExtractedRelation,
    ExtractionResult,
    LibrarianPayload,
    OntologyProposal,
)

# Plan 33 introduces an opt-in local: model route; Stage 9 changes defaults after the gate.
DEFAULT_MODEL_NAME = "openai-responses:gpt-5.4-mini"
DEFAULT_THINKING_EFFORT = "low"


@dataclass
class AgentInferenceConfig:
    """Per-agent inference configuration (model, thinking budget, etc.)."""

    model_name: str = DEFAULT_MODEL_NAME
    thinking_effort: ThinkingLevel | None = DEFAULT_THINKING_EFFORT
    use_test_model: bool = False
    local_endpoint: LocalEndpoint | None = None

    @property
    def model_settings(self) -> ModelSettings | None:
        """Build pydantic-ai model_settings dict for agent.run()."""
        if self.thinking_effort is not None:
            return build_model_settings(self.thinking_effort, self.model_name, self.local_endpoint)
        return None


def _build_model(config: AgentInferenceConfig) -> str | Model:
    """Build the LLM model from inference config."""
    if config.use_test_model:
        logger.debug("Using TestModel for extraction agents")
        return TestModel()
    logger.debug("Using model={}", config.model_name)
    return build_model(config.model_name, config.local_endpoint)


# ── Ontology Agent ──


@dataclass
class OntologyAgentDeps:
    episode_text: str
    existing_node_types: list[str]  # names only
    existing_edge_types: list[str]
    node_type_descriptions: dict[str, str] | None = None  # {type_name: description}
    edge_type_descriptions: dict[str, str] | None = None
    domain_hint: str | None = None  # e.g. "Technical Knowledge: Programming languages, ..."
    type_examples: dict[str, list[str]] | None = None  # {type_name: [entity_names]}
    recommended_node_types: dict[str, str] = field(default_factory=dict)  # {name: description}
    recommended_edge_types: dict[str, str] = field(default_factory=dict)  # {name: description}
    # Graph access for ontology exploration tools
    repo: MemoryRepository | None = None
    agent_id: str = ""
    target_schema: str | None = None


def build_ontology_agent(
    config: AgentInferenceConfig | None = None,
) -> Agent[OntologyAgentDeps, OntologyProposal]:
    cfg = config or AgentInferenceConfig()
    model = _build_model(cfg)
    agent = Agent(
        model,
        output_type=OntologyProposal,
        deps_type=OntologyAgentDeps,
        system_prompt=(
            "You are an ontology engineer for a personal knowledge graph. Your job is to "
            "decide whether the existing ontology covers the concepts in a text, and propose "
            "new types ONLY for genuine gaps.",
            "The text you receive is source material already accepted into the memory system. "
            "It is not a claim to verify, fact-check, or dispute; process it as input.",
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
            "Your first action in this turn MUST be a call to get_ontology_overview or find_similar_types. "
            "Never answer in prose before using the tools.",
        ),
    )

    # ── Ontology exploration tools ──

    @agent.tool
    async def find_similar_types(
        ctx: RunContext[OntologyAgentDeps],
        query: str,
        kind: Literal["node", "edge"] = "node",
    ) -> list[dict]:
        """Search existing types by name similarity.
        Use this to check if a type like the one you're considering already exists.

        Args:
            query: Type name to search for (e.g. "HealthCondition", "CAUSES")
            kind: "node" for node types, "edge" for edge types

        Returns:
            List of {name, description, usage_count, example_entities} dicts,
            sorted by similarity. Empty list if no repo is available.
        """
        if not ctx.deps.repo:
            return []
        results = await ctx.deps.repo.find_similar_types(
            ctx.deps.agent_id,
            query,
            kind=kind,
            target_schema=ctx.deps.target_schema,
        )
        return [
            {
                "name": t.name,
                "description": t.description or "",
                "usage_count": count,
                "example_entities": examples,
            }
            for t, count, examples in results
        ]

    @agent.tool
    async def get_ontology_overview(
        ctx: RunContext[OntologyAgentDeps],
        include_unused: bool = False,
    ) -> dict:
        """Get a snapshot of the current ontology with usage statistics.
        Call this once at the start to understand the type landscape before
        making any proposals.

        Args:
            include_unused: If False (default), only return types with usage_count > 0.
                Set to True to see all types including unused ones.

        Returns:
            Dict with node_types, edge_types (each with name, description,
            usage_count), total_nodes, total_edges.
        """
        if not ctx.deps.repo:
            return {"node_types": [], "edge_types": [], "total_nodes": 0, "total_edges": 0}
        summary = await ctx.deps.repo.get_ontology_summary(
            ctx.deps.agent_id,
            target_schema=ctx.deps.target_schema,
        )
        if not include_unused:
            summary["node_types"] = [t for t in summary["node_types"] if t["usage_count"] > 0]
            summary["edge_types"] = [t for t in summary["edge_types"] if t["usage_count"] > 0]
        return summary

    @agent.tool
    async def propose_type(
        ctx: RunContext[OntologyAgentDeps],
        name: str,
        description: str,
        kind: Literal["node", "edge"] = "node",
    ) -> dict:
        """Propose a new type with inline validation.
        Runs normalization checks and similarity search before accepting.
        Does NOT persist the type — just validates and returns feedback.

        Args:
            name: Proposed type name (PascalCase for node, SCREAMING_SNAKE for edge)
            description: What this type represents
            kind: "node" or "edge"

        Returns:
            {accepted: bool, normalized_name: str, reason: str, similar_existing: list}
            If rejected, reason explains why. If accepted but similar types exist,
            similar_existing lists them so you can reconsider.
        """
        from neocortex.normalization import normalize_edge_type, normalize_node_type

        # 1. Run Stage 1 normalization/validation
        try:
            normalized = normalize_edge_type(name) if kind == "edge" else normalize_node_type(name)
        except ValueError as e:
            return {"accepted": False, "normalized_name": name, "reason": str(e), "similar_existing": []}

        # 2. Check for similar existing types
        similar: list[str] = []
        if ctx.deps.repo:
            results = await ctx.deps.repo.find_similar_types(
                ctx.deps.agent_id,
                normalized,
                kind=kind,
                limit=3,
                target_schema=ctx.deps.target_schema,
            )
            similar = [t.name for t, _count, _ex in results]

        # 3. Check if type already exists (exact match)
        existing_types = ctx.deps.existing_node_types if kind == "node" else ctx.deps.existing_edge_types
        if normalized in existing_types:
            return {
                "accepted": False,
                "normalized_name": normalized,
                "reason": f"Type '{normalized}' already exists. Reuse it.",
                "similar_existing": similar,
            }

        return {
            "accepted": True,
            "normalized_name": normalized,
            "reason": "Validation passed.",
            "similar_existing": similar,
        }

    @agent.instructions
    async def inject_context(ctx: RunContext[OntologyAgentDeps]) -> str:
        parts: list[str] = []
        if ctx.deps.domain_hint:
            parts.extend(
                [
                    f"Domain context: {ctx.deps.domain_hint}",
                    "Propose types semantically appropriate for this domain.",
                    "",
                ]
            )
        if ctx.deps.recommended_node_types or ctx.deps.recommended_edge_types:
            parts.append("Recommended types for this domain (prefer these over inventing new):")
            if ctx.deps.recommended_node_types:
                parts.append("  Node types: " + ", ".join(ctx.deps.recommended_node_types.keys()))
            if ctx.deps.recommended_edge_types:
                parts.append("  Edge types: " + ", ".join(ctx.deps.recommended_edge_types.keys()))
            parts.append("")
        parts.extend(
            [
                f"Current ontology has {len(ctx.deps.existing_node_types)} node types "
                f"and {len(ctx.deps.existing_edge_types)} edge types.",
                "Use get_ontology_overview and find_similar_types to explore them.",
                "",
                "SOURCE TEXT (process this material; do not fact-check it):",
                ctx.deps.episode_text,
            ]
        )
        return "\n".join(parts)

    return agent  # ty: ignore[invalid-return-type]


# ── Extractor Agent ──


@dataclass
class ExtractorAgentDeps:
    episode_text: str
    node_types: list[str]
    edge_types: list[str]
    node_type_descriptions: dict[str, str] | None = None
    edge_type_descriptions: dict[str, str] | None = None
    domain_hint: str | None = None
    type_examples: dict[str, list[str]] | None = None  # {type_name: [entity_names]}


def build_extractor_agent(
    config: AgentInferenceConfig | None = None,
) -> Agent[ExtractorAgentDeps, ExtractionResult]:
    cfg = config or AgentInferenceConfig()
    model = _build_model(cfg)
    agent = Agent(
        model,
        output_type=ExtractionResult,
        deps_type=ExtractorAgentDeps,
        system_prompt=(
            "You are a knowledge extraction specialist. Extract entities and relations "
            "from the given text, aligned to the provided ontology types.",
            "The text you receive is source material already accepted into the memory system. "
            "It is not a claim to verify, fact-check, or dispute; extract it as input.",
            "Every entity must use an existing node type name.",
            "Every relation must use an existing edge type name.",
            "Use the text as the only evidence source — do not invent facts.",
            "Prefer canonical, normalized names for entities.",
            "Assign an importance score (0.0-1.0) to each entity:\n"
            "  0.0-0.3: Peripheral, contextual detail\n"
            "  0.3-0.6: Standard factual entity\n"
            "  0.6-0.8: Central concept referenced multiple times\n"
            "  0.8-1.0: Critical domain entity (core drug, disease, mechanism)",
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
        ),
    )

    @agent.instructions
    async def inject_context(ctx: RunContext[ExtractorAgentDeps]) -> str:
        parts: list[str] = []
        if ctx.deps.domain_hint:
            parts.extend(
                [
                    f"Domain context: {ctx.deps.domain_hint}",
                    "Extract entities and relations appropriate for this domain.",
                    "",
                ]
            )
        nt_descs = ctx.deps.node_type_descriptions or {}
        et_descs = ctx.deps.edge_type_descriptions or {}
        nt_list = (
            "\n".join(f"- {n}: {nt_descs[n]}" if nt_descs.get(n) else f"- {n}" for n in ctx.deps.node_types) or "- none"
        )
        et_list = (
            "\n".join(f"- {n}: {et_descs[n]}" if et_descs.get(n) else f"- {n}" for n in ctx.deps.edge_types) or "- none"
        )
        parts.extend(
            [
                "Rules:",
                "- Extract only ontology-aligned entities and relations.",
                "- If a relation cannot fit the ontology, omit it.",
                "- Include evidence text in relation properties when possible.",
                "",
                "Available node types:",
                nt_list,
                "",
                "Available edge types:",
                et_list,
            ]
        )
        if ctx.deps.type_examples:
            parts.extend(["", "Known entities and their assigned types:"])
            for type_name, examples in ctx.deps.type_examples.items():
                for entity_name in examples[:3]:
                    parts.append(f'- "{entity_name}" \u2192 {type_name}')
            parts.append("When extracting these entities, use their assigned types.")
        parts.extend(
            [
                "",
                "",
                "SOURCE TEXT (process this material; do not fact-check it):",
                ctx.deps.episode_text,
                "Return only the ExtractionResult structure; do not add prose.",
            ]
        )
        return "\n".join(parts)

    return agent  # ty: ignore[invalid-return-type]


# ── Librarian Agent ──


@dataclass
class LibrarianAgentDeps:
    episode_text: str
    node_types: list[str]
    edge_types: list[str]
    extracted_entities: list[ExtractedEntity]
    extracted_relations: list[ExtractedRelation]
    # Graph access for retrieval tools (replaces known_node_names)
    repo: MemoryRepository
    embeddings: EmbeddingService | None
    agent_id: str
    target_schema: str | None = None
    episode_id: int | None = None  # Source tracking in mutation tools
    known_node_names: list[str] | None = None  # Fallback dedup context (non-tool mode)
    precomputed_embeddings: dict[str, list[float]] = field(default_factory=dict)


def build_librarian_agent(
    config: AgentInferenceConfig | None = None,
    use_tools: bool = True,
) -> Agent[LibrarianAgentDeps, CurationSummary] | Agent[LibrarianAgentDeps, LibrarianPayload]:
    """Build the librarian agent.

    When use_tools=True (default), the agent gets mutation tools and returns
    CurationSummary. When use_tools=False, it returns LibrarianPayload for
    backward-compatible _persist_payload flow.
    """
    cfg = config or AgentInferenceConfig()
    model = _build_model(cfg)

    output_type = CurationSummary if use_tools else LibrarianPayload

    system_prompt: tuple[str, ...]
    if use_tools:
        system_prompt = (
            "You are a knowledge graph curator. You receive extracted entities and relations "
            "from a text, and your job is to integrate them into the existing knowledge graph "
            "using the tools available to you.",
            "The text and extracted data are source material already accepted into the memory system. "
            "Do not fact-check or dispute them; curate them according to the workflow below.",
            "",
            "## Workflow",
            "For each extracted entity:",
            "  1. Use find_similar_nodes to check if it already exists.",
            "     This checks exact name, aliases, fuzzy matches, and semantic similarity.",
            "  2. If a match is found (any match_type): compare the extracted description",
            "     with the existing content.",
            "     - If new info ADDS knowledge: use create_or_update_node with a",
            "       COMPREHENSIVE updated description merging old + new.",
            "     - If new info includes QUANTITATIVE UPDATES (numbers, percentages,",
            "       dates, versions): ALWAYS update the node content to reflect the",
            "       new values. Include both old and new values with context",
            "       (e.g., 'precision improved from 87% to 94.2%').",
            "     - If new info CONTRADICTS existing: update with correct info and",
            "       note the contradiction in properties.",
            "  3. If no match is found: use create_or_update_node to create it.",
            "  4. When creating a new node with a name that has known variants",
            "     (e.g., 'Apache Kafka' when 'Kafka' might be used later),",
            "     mention the variants in the node content.",
            "",
            "For each extracted relation:",
            "  1. Use get_edges_between to check for existing relationships",
            "  2. If an edge exists with a similar meaning (even different type name),",
            "     keep it — do NOT create a duplicate.",
            "  3. If an edge is now WRONG, use remove_edge and create the correct one.",
            "  4. If no relevant edge exists, use create_or_update_edge.",
            "",
            "## Quantitative Update Rules",
            "When an extracted entity contains updated numbers, percentages, dates,",
            "or version strings, you MUST update the node content to reflect the new",
            "values. This is non-negotiable. Examples:",
            "- 'precision: 87%' → 'precision: 94.2%' → node content MUST say '94.2%'",
            "- 'launch: June' → 'launch: August 1' → node content MUST say 'August 1'",
            "- 'v2.3' → 'v3.0' → node content MUST say 'v3.0'",
            "",
            "## Temporal Corrections (MANDATORY)",
            "When an extracted entity has `supersedes` set (non-null):",
            "",
            "  1. DO NOT merge this entity into the existing node with the superseded name.",
            "  2. Create a NEW node with the extracted name (versioned name).",
            "  3. Create an edge of the type specified in `temporal_signal`",
            "     (either 'CORRECTS' or 'SUPERSEDES') FROM the new node TO the old node.",
            "  4. Report both the new node creation and the temporal edge in your actions.",
            "",
            "This is non-negotiable. Temporal correction edges are critical for recall quality.",
            "If you merge a correction into an existing node, the temporal signal is lost.",
            "",
            "Even without explicit `supersedes` fields, watch for these signals in the",
            "episode text and create temporal edges when appropriate:",
            "  - 'CORRECTION', 'UPDATE', 'REVERSAL', 'actually', 'instead',",
            "    'no longer', 'changed to', 'replaced by', 'switched from'",
            "",
            "## Rules",
            "- ALWAYS provide comprehensive content when creating/updating nodes.",
            "- ALWAYS check for existing entities before creating new ones.",
            "- Prefer updating existing nodes over creating duplicates.",
            "- Normalize names to canonical form (proper casing, full names).",
            "- When in doubt about type assignment, match the existing node's type.",
            "",
            "## Shared Graph Context",
            "You may be curating a shared knowledge graph where multiple agents contribute.",
            "When you find an existing node via find_similar_nodes:",
            "- The node may have been created by a different agent.",
            "- You MUST still merge your new knowledge into it — do NOT skip updates",
            '  because the node "belongs" to someone else.',
            "- When merging, produce a COMPREHENSIVE description that combines the existing",
            "  content with the new information. Never discard existing facts.",
            '- Include both perspectives when they differ (e.g., "Backend team reports X.',
            '  ML team reports Y.").',
            "",
            "After all curation actions, return a CurationSummary describing what you did.",
            "Every entity must be resolved with find_similar_nodes before you create or update it. "
            "Finish by returning the structured CurationSummary.",
        )
    else:
        system_prompt = (
            "You are a knowledge graph librarian. " "Your job is to normalize and deduplicate extracted knowledge.",
            "Normalize entity names to canonical forms.",
            "Preserve importance scores from extractor (max semantics if merging).",
            "ALWAYS provide a description for every entity.",
        )

    agent = Agent(
        model,
        output_type=output_type,
        deps_type=LibrarianAgentDeps,
        system_prompt=system_prompt,
    )

    # ── Read-only retrieval tools ──

    @agent.tool
    async def search_existing_nodes(
        ctx: RunContext[LibrarianAgentDeps],
        query: str,
        limit: int = 5,
    ) -> list[dict]:
        """Search the knowledge graph for nodes matching a query.
        Use this to check if an entity already exists before deciding
        to create a new node or update an existing one.

        Args:
            query: Search text (entity name, description fragment, etc.)
            limit: Max results to return (default 5)

        Returns:
            List of {name, type_name, content, importance, node_id} dicts
        """
        embedding = None
        if ctx.deps.embeddings:
            embedding = await ctx.deps.embeddings.embed(query)
        results = await ctx.deps.repo.search_nodes(
            ctx.deps.agent_id,
            query,
            limit=limit,
            query_embedding=embedding,
        )
        types = await ctx.deps.repo.get_node_types(ctx.deps.agent_id, target_schema=ctx.deps.target_schema)
        type_names = {t.id: t.name for t in types}
        out = []
        for node, score in results:
            out.append(
                {
                    "node_id": node.id,
                    "name": node.name,
                    "type_name": type_names.get(node.type_id, "Unknown"),
                    "content": node.content,
                    "importance": node.importance,
                    "relevance_score": round(score, 3),
                }
            )
        return out

    @agent.tool
    async def find_node_by_name(
        ctx: RunContext[LibrarianAgentDeps],
        name: str,
    ) -> list[dict]:
        """Look up a specific node by exact name (case-insensitive).

        Args:
            name: Entity name to look up exactly, case-insensitively

        Returns:
            List of matching nodes (usually 0 or 1). Multiple means duplicates exist.
        """
        nodes = await ctx.deps.repo.find_nodes_by_name(
            ctx.deps.agent_id,
            name,
            target_schema=ctx.deps.target_schema,
        )
        types = await ctx.deps.repo.get_node_types(ctx.deps.agent_id, target_schema=ctx.deps.target_schema)
        type_map = {t.id: t.name for t in types}
        return [
            {
                "node_id": n.id,
                "name": n.name,
                "type_name": type_map.get(n.type_id, "Unknown"),
                "content": n.content,
                "importance": n.importance,
                "properties": n.properties,
            }
            for n in nodes
            if not n.forgotten
        ]

    @agent.tool
    async def find_similar_nodes(
        ctx: RunContext[LibrarianAgentDeps],
        name: str,
        limit: int = 5,
    ) -> list[dict]:
        """Find nodes with names similar to the given name.
        Uses exact match first, then alias resolution, then fuzzy matching.
        ALWAYS use this instead of find_node_by_name when checking for existing entities.

        Args:
            name: Entity name to search for (or a variant/alias)
            limit: Max results to return (default 5)

        Returns:
            List of {name, type_name, content, importance, node_id, match_type} dicts
            where match_type is 'exact', 'alias', or 'fuzzy'
        """
        results: list[dict] = []
        types = await ctx.deps.repo.get_node_types(ctx.deps.agent_id, target_schema=ctx.deps.target_schema)
        type_names = {t.id: t.name for t in types}

        # 1. Exact match
        exact = await ctx.deps.repo.find_nodes_by_name(ctx.deps.agent_id, name, target_schema=ctx.deps.target_schema)
        for node in exact:
            results.append(
                {
                    "node_id": node.id,
                    "name": node.name,
                    "type_name": type_names.get(node.type_id, "Unknown"),
                    "content": node.content,
                    "importance": node.importance,
                    "match_type": "exact",
                }
            )

        if results:
            return results

        # 2. Alias resolution
        alias_nodes = await ctx.deps.repo.resolve_alias(ctx.deps.agent_id, name, target_schema=ctx.deps.target_schema)
        for node in alias_nodes:
            results.append(
                {
                    "node_id": node.id,
                    "name": node.name,
                    "type_name": type_names.get(node.type_id, "Unknown"),
                    "content": node.content,
                    "importance": node.importance,
                    "match_type": "alias",
                }
            )
        if results:
            return results

        # 3. Fuzzy matching (trigram similarity in PG, word overlap in mock)
        fuzzy = await ctx.deps.repo.find_nodes_fuzzy(
            ctx.deps.agent_id,
            name,
            threshold=0.3,
            limit=limit,
            target_schema=ctx.deps.target_schema,
        )
        for node, score in fuzzy:
            results.append(
                {
                    "node_id": node.id,
                    "name": node.name,
                    "type_name": type_names.get(node.type_id, "Unknown"),
                    "content": node.content,
                    "importance": node.importance,
                    "match_type": "fuzzy",
                    "similarity": round(score, 3),
                }
            )

        # 4. Semantic search fallback
        if not results and ctx.deps.embeddings:
            embedding = await ctx.deps.embeddings.embed(name)
            semantic = await ctx.deps.repo.search_nodes(
                ctx.deps.agent_id,
                name,
                limit=limit,
                query_embedding=embedding,
            )
            for node, score in semantic:
                if score > 0.5:
                    results.append(
                        {
                            "node_id": node.id,
                            "name": node.name,
                            "type_name": type_names.get(node.type_id, "Unknown"),
                            "content": node.content,
                            "importance": node.importance,
                            "match_type": "semantic",
                            "similarity": round(score, 3),
                        }
                    )

        return results

    @agent.tool
    async def inspect_node_neighborhood(
        ctx: RunContext[LibrarianAgentDeps],
        node_id: int,
        depth: int = 1,
    ) -> dict:
        """Inspect a node and its immediate neighborhood (connected nodes and edges).
        Use this after finding a node to understand its relationships before
        deciding how to update the graph.

        Args:
            node_id: The node ID (from search or find results)
            depth: How many hops to traverse (1 = immediate neighbors, 2 = 2-hop)

        Returns:
            Dict with center node info and list of connected edges and neighbors.
        """
        neighborhood = await ctx.deps.repo.get_node_neighborhood(
            agent_id=ctx.deps.agent_id,
            node_id=node_id,
            depth=min(depth, 2),
        )
        types = await ctx.deps.repo.get_node_types(ctx.deps.agent_id, target_schema=ctx.deps.target_schema)
        edge_types = await ctx.deps.repo.get_edge_types(ctx.deps.agent_id, target_schema=ctx.deps.target_schema)
        nt_map = {t.id: t.name for t in types}
        et_map = {t.id: t.name for t in edge_types}

        edges_out = []
        neighbors_out = []
        for entry in neighborhood:
            node = entry["node"]
            neighbors_out.append(
                {
                    "node_id": node.id,
                    "name": node.name,
                    "type": nt_map.get(node.type_id, "Unknown"),
                    "content": node.content[:100] if node.content else None,
                }
            )
            for edge in entry["edges"]:
                edges_out.append(
                    {
                        "edge_id": edge.id,
                        "source_id": edge.source_id,
                        "target_id": edge.target_id,
                        "type": et_map.get(edge.type_id, "Unknown"),
                        "weight": edge.weight,
                    }
                )
        return {"neighbors": neighbors_out, "edges": edges_out}

    @agent.tool
    async def get_edges_between(
        ctx: RunContext[LibrarianAgentDeps],
        source_name: str,
        target_name: str,
    ) -> list[dict]:
        """Find all edges between two named nodes.
        Use this before creating an edge to check if a relationship already exists.

        Args:
            source_name: Name of the source node
            target_name: Name of the target node

        Returns:
            List of existing edges between these nodes, with type and weight.
        """
        src_nodes = await ctx.deps.repo.find_nodes_by_name(
            ctx.deps.agent_id,
            source_name,
            target_schema=ctx.deps.target_schema,
        )
        tgt_nodes = await ctx.deps.repo.find_nodes_by_name(
            ctx.deps.agent_id,
            target_name,
            target_schema=ctx.deps.target_schema,
        )
        if not src_nodes or not tgt_nodes:
            return []

        edge_types = await ctx.deps.repo.get_edge_types(ctx.deps.agent_id, target_schema=ctx.deps.target_schema)
        et_map = {t.id: t.name for t in edge_types}

        # Get neighborhood and filter for edges to target
        src = src_nodes[0]
        tgt_ids = {n.id for n in tgt_nodes}
        neighborhood = await ctx.deps.repo.get_node_neighborhood(
            agent_id=ctx.deps.agent_id,
            node_id=src.id,
            depth=1,
        )
        result = []
        for entry in neighborhood:
            for edge in entry["edges"]:
                if edge.target_id in tgt_ids or edge.source_id in tgt_ids:
                    result.append(
                        {
                            "edge_id": edge.id,
                            "source_id": edge.source_id,
                            "target_id": edge.target_id,
                            "type": et_map.get(edge.type_id, "Unknown"),
                            "weight": edge.weight,
                            "properties": edge.properties,
                        }
                    )
        return result

    # ── Mutation tools (Stage 3) ──

    if use_tools:

        @agent.tool
        async def create_or_update_node(
            ctx: RunContext[LibrarianAgentDeps],
            name: str,
            type_name: str,
            content: str,
            properties: dict | None = None,
            importance: float = 0.5,
        ) -> dict:
            """Create a new node or update an existing one.
            Searches by name first — if a node with this name exists,
            updates its content and merges properties. If not, creates new.

            ALWAYS provide a content description, even for existing nodes.
            The content should be a comprehensive, up-to-date summary.

            Args:
                name: Canonical entity name
                type_name: Node type (must be from available types)
                content: Description of the entity (REQUIRED — always provide this)
                properties: Optional key-value properties
                importance: 0.0-1.0 importance score

            Returns:
                Dict with node_id, name, type_name, is_new, action taken
            """
            from neocortex.normalization import canonicalize_name

            canonical, aliases = canonicalize_name(name)
            if canonical:
                name = canonical

            node_type = await ctx.deps.repo.get_or_create_node_type(
                ctx.deps.agent_id,
                type_name,
                target_schema=ctx.deps.target_schema,
            )
            if node_type is None:
                return {"error": f"Invalid type name '{type_name}' — rejected by validation"}
            embedding = None
            if ctx.deps.embeddings and content:
                embedding = ctx.deps.precomputed_embeddings.get(content)
                if embedding is None:
                    embedding = await ctx.deps.embeddings.embed(content)

            episode_id = ctx.deps.episode_id
            props = {**(properties or {})}
            if episode_id:
                props["_source_episode"] = episode_id

            node = await ctx.deps.repo.upsert_node(
                agent_id=ctx.deps.agent_id,
                name=name,
                type_id=node_type.id,
                content=content,
                properties=props,
                embedding=embedding,
                target_schema=ctx.deps.target_schema,
                importance=importance,
            )

            # Register aliases from canonicalization (covers both new and updated nodes)
            for alias in aliases:
                await ctx.deps.repo.register_alias(
                    ctx.deps.agent_id,
                    node.id,
                    alias,
                    source="librarian",
                    target_schema=ctx.deps.target_schema,
                )

            is_new = node.created_at == node.updated_at
            action = "created" if is_new else "updated"
            logger.bind(action_log=True).info(
                "librarian_tool_call",
                tool="create_or_update_node",
                node_name=name,
                action=action,
                agent_id=ctx.deps.agent_id,
            )
            return {
                "node_id": node.id,
                "name": node.name,
                "type_name": type_name,
                "is_new": is_new,
                "action": action,
            }

        @agent.tool
        async def create_or_update_edge(
            ctx: RunContext[LibrarianAgentDeps],
            source_name: str,
            target_name: str,
            edge_type: str,
            weight: float = 1.0,
            properties: dict | None = None,
        ) -> dict:
            """Create a new edge or update an existing one between two nodes.
            Both nodes must already exist (create them first with create_or_update_node).

            Before calling this, use get_edges_between to check for existing relationships.
            If an edge already exists with a suitable type, prefer updating it over creating
            a new one with a different type.

            Args:
                source_name: Name of the source node (must exist)
                target_name: Name of the target node (must exist)
                edge_type: Relationship type (e.g., MEMBER_OF, WORKS_ON)
                weight: Edge weight 0.0-1.0 (default 1.0)
                properties: Optional properties (evidence text, etc.)

            Returns:
                Dict with edge_id, source, target, type, action
            """
            src_nodes = await ctx.deps.repo.find_nodes_by_name(
                ctx.deps.agent_id,
                source_name,
                target_schema=ctx.deps.target_schema,
            )
            tgt_nodes = await ctx.deps.repo.find_nodes_by_name(
                ctx.deps.agent_id,
                target_name,
                target_schema=ctx.deps.target_schema,
            )
            if not src_nodes:
                return {"error": f"Source node '{source_name}' not found. Create it first."}
            if not tgt_nodes:
                return {"error": f"Target node '{target_name}' not found. Create it first."}

            et = await ctx.deps.repo.get_or_create_edge_type(
                ctx.deps.agent_id,
                edge_type,
                target_schema=ctx.deps.target_schema,
            )
            if et is None:
                return {"error": f"Invalid edge type '{edge_type}' — rejected by validation"}

            episode_id = ctx.deps.episode_id
            props = {**(properties or {})}
            if episode_id:
                props["_source_episode"] = episode_id

            edge = await ctx.deps.repo.upsert_edge(
                agent_id=ctx.deps.agent_id,
                source_id=src_nodes[0].id,
                target_id=tgt_nodes[0].id,
                type_id=et.id,
                weight=weight,
                properties=props,
                target_schema=ctx.deps.target_schema,
            )
            if edge is None:
                return {"error": f"Failed to upsert edge '{source_name}' -> '{target_name}' ({edge_type})"}
            logger.bind(action_log=True).info(
                "librarian_tool_call",
                tool="create_or_update_edge",
                source=source_name,
                target=target_name,
                edge_type=edge_type,
                agent_id=ctx.deps.agent_id,
            )
            return {
                "edge_id": edge.id,
                "source": source_name,
                "target": target_name,
                "type": edge_type,
                "action": "upserted",
            }

        @agent.tool
        async def archive_node(
            ctx: RunContext[LibrarianAgentDeps],
            node_id: int,
            reason: str,
        ) -> dict:
            """Soft-delete a node that is no longer current.
            Use this when new information supersedes or contradicts an existing node.
            The node is not hard-deleted — it's marked as forgotten and excluded from future recall.

            Args:
                node_id: ID of the node to archive (from find_node_by_name results)
                reason: Why this node is being archived

            Returns:
                Dict confirming the archival
            """
            count = await ctx.deps.repo.mark_forgotten(
                ctx.deps.agent_id,
                [node_id],
                target_schema=ctx.deps.target_schema,
            )
            logger.bind(action_log=True).info(
                "librarian_tool_call",
                tool="archive_node",
                node_id=node_id,
                reason=reason,
                agent_id=ctx.deps.agent_id,
            )
            return {
                "archived": count > 0,
                "node_id": node_id,
                "reason": reason,
            }

        @agent.tool
        async def remove_edge(
            ctx: RunContext[LibrarianAgentDeps],
            edge_id: int,
            reason: str,
        ) -> dict:
            """Remove a stale or incorrect edge from the graph.
            Use this when a relationship is no longer valid (e.g., Alice is no longer
            on the billing team, so the MEMBER_OF→Billing edge should be removed).

            Args:
                edge_id: ID of the edge to remove (from get_edges_between or inspect results)
                reason: Why this edge is being removed

            Returns:
                Dict confirming the removal
            """
            deleted = await ctx.deps.repo.delete_edge(
                ctx.deps.agent_id,
                edge_id,
                target_schema=ctx.deps.target_schema,
            )
            logger.bind(action_log=True).info(
                "librarian_tool_call",
                tool="remove_edge",
                edge_id=edge_id,
                reason=reason,
                agent_id=ctx.deps.agent_id,
            )
            return {
                "removed": deleted,
                "edge_id": edge_id,
                "reason": reason,
            }

    # ── Context injection ──

    @agent.instructions
    async def inject_context(ctx: RunContext[LibrarianAgentDeps]) -> str:
        def _format_entity(e: ExtractedEntity) -> str:
            base = f"- {e.name} [{e.type_name}]: {e.description or 'no description'}"
            if e.supersedes:
                base += f" [SUPERSEDES={e.supersedes}, signal={e.temporal_signal}]"
            return base

        entities_str = "\n".join(_format_entity(e) for e in ctx.deps.extracted_entities) or "- none"
        relations_str = (
            "\n".join(
                f"- {r.source_name} --[{r.relation_type}]--> {r.target_name}" for r in ctx.deps.extracted_relations
            )
            or "- none"
        )
        parts = [
            "SOURCE MATERIAL (already accepted; do not fact-check it):",
            ctx.deps.episode_text,
            "",
            "Available node types:",
            "\n".join(f"- {n}" for n in ctx.deps.node_types) or "- none",
            "",
            "Available edge types:",
            "\n".join(f"- {n}" for n in ctx.deps.edge_types) or "- none",
            "",
            "Extracted entities (from extractor — your job is to curate these):",
            entities_str,
            "",
            "Extracted relations:",
            relations_str,
        ]
        if use_tools:
            parts.extend(
                [
                    "",
                    "IMPORTANT: Use your tools to check the existing graph before making decisions.",
                    "Do NOT assume entities are new — always verify with find_similar_nodes first.",
                    "- ALWAYS provide a description for every entity when using create_or_update_node.",
                    "- For existing entities, write an UPDATED description that "
                    "incorporates new information from the text.",
                    "- The description becomes the entity's canonical summary — make it comprehensive and current.",
                ]
            )
        else:
            # Fallback: inject known names for dedup context
            if ctx.deps.known_node_names:
                parts.extend(
                    [
                        "",
                        "Known entities in the graph (check for duplicates):",
                        "\n".join(f"- {n}" for n in ctx.deps.known_node_names[:500]),
                    ]
                )
            parts.extend(
                [
                    "",
                    "ALWAYS provide a description for every entity, even if is_new=False.",
                    "For existing entities, write an UPDATED description that incorporates new information "
                    "from the text.",
                    "",
                    "Every entity must be checked against known names before persistence.",
                    "Return only the structured LibrarianPayload; do not add prose.",
                ]
            )
        if use_tools:
            parts.extend(
                [
                    "",
                    "Every entity must be resolved with find_similar_nodes before you create or update it.",
                    "Finish by returning the structured CurationSummary.",
                ]
            )
        return "\n".join(parts)

    return agent  # ty: ignore[invalid-return-type]
