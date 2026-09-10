"""Host-resolved one-shot librarian for local Qwen models.

The tool-driven librarian profiles pay one model request per batch of reads and
one per batch of decisions.  On a local endpoint that decodes at tens of tokens
per second, that trajectory dominates the pipeline's wall time.  This module
inverts the loop: the host resolves every extracted entity against the graph,
asks the model at most one structured question about the entities that actually
have a candidate, and then applies the decisions deterministically.

Design invariants:

* zero model requests when no entity resolved to a candidate;
* at most one model request otherwise (the agent is tool-free);
* every decision is validated against host-owned candidates, and an invalid or
  missing decision falls back to a host default instead of another request;
* an entity carrying ``supersedes`` is always created as a distinct node.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic_ai.usage import UsageLimits

from neocortex.extraction.agents import (
    AgentInferenceConfig,
    CurationActionTracker,
    LibrarianAgentDeps,
    build_audit_fields,
    resolve_entity_candidates,
    resolve_semantic_candidates,
)
from neocortex.extraction.schemas import (
    CurationReport,
    ExtractedEntity,
    ExtractionResult,
    OneshotCandidate,
    OneshotDecision,
    OneshotDecisions,
    OneshotItem,
)
from neocortex.normalization import canonicalize_name

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from neocortex.db.protocol import MemoryRepository
    from neocortex.embedding_service import EmbeddingService

# The model is asked for at most one answer; the extra budget covers the single
# output-validation retry the agent is constructed with.
ONESHOT_REQUEST_LIMIT = 3
MAX_CANDIDATES = 3
CANDIDATE_CONTENT_CHARS = 400
CANDIDATE_PROPERTY_LIMIT = 8
MERGE_CONTENT_CHARS = 1200
TEMPORAL_SIGNALS = ("CORRECTS", "SUPERSEDES")
DEFAULT_TEMPORAL_SIGNAL = "SUPERSEDES"


@dataclass
class EntityResolutionOutcome:
    """What the host learned about one extracted entity before asking the model."""

    index: int
    match: str
    candidates: list[Any] = field(default_factory=list)
    predecessor: Any | None = None

    @property
    def single_strong_match(self) -> bool:
        """A lone exact or alias hit: safe to merge without the model."""
        return self.match in {"exact", "alias"} and len(self.candidates) == 1


@dataclass
class _NodePlan:
    """The deterministic write the host derived for one entity."""

    index: int
    action: str  # create | merge | unchanged
    name: str
    type_id: int | None
    content: str | None
    properties: dict[str, Any]
    importance: float
    new_fact: str | None = None
    node_id: int | None = None
    aliases: list[str] = field(default_factory=list)


def _scalar_properties(properties: dict[str, Any] | None) -> dict[str, str | int | float | bool | None]:
    """Reduce node properties to the bounded scalar view the model may see."""
    scalars: dict[str, str | int | float | bool | None] = {}
    for key, value in sorted((properties or {}).items(), key=lambda pair: str(pair[0])):
        if key == "_source_episode" or isinstance(value, (dict, list, tuple, set)):
            continue
        if len(scalars) >= CANDIDATE_PROPERTY_LIMIT:
            break
        scalars[str(key)[:64]] = value[:256] if isinstance(value, str) else value
    return scalars


def _merge_content(existing: str | None, description: str | None) -> str:
    """Host default merge: keep the old text, append the new fact once."""
    old = (existing or "").strip()
    new = (description or "").strip()
    if not old:
        return new[:MERGE_CONTENT_CHARS]
    if not new or new.casefold() in old.casefold():
        return old[:MERGE_CONTENT_CHARS]
    return f"{old} {new}"[:MERGE_CONTENT_CHARS]


def _temporal_signal(entity: ExtractedEntity) -> str:
    signal = (entity.temporal_signal or "").strip().upper()
    return signal if signal in TEMPORAL_SIGNALS else DEFAULT_TEMPORAL_SIGNAL


async def resolve_extraction_entities(
    repo: MemoryRepository,
    embeddings: EmbeddingService | None,
    agent_id: str,
    target_schema: str | None,
    entities: list[ExtractedEntity],
) -> list[EntityResolutionOutcome]:
    """Resolve every extracted entity (and any predecessor) with no model calls.

    Deterministic lookups run first for all entities.  The names that reach the
    embedding step are then embedded in one batch, so a 30-entity episode costs
    one embedding request rather than 30.
    """
    type_names = {item.id: item.name for item in await repo.get_node_types(agent_id, target_schema=target_schema)}
    outcomes: list[EntityResolutionOutcome] = []
    for index, entity in enumerate(entities):
        match, matches = await resolve_entity_candidates(
            repo,
            embeddings,
            agent_id,
            target_schema,
            entity.name,
            entity.type_name,
            type_names=type_names,
            semantic=False,
        )
        outcomes.append(
            EntityResolutionOutcome(index=index, match=match, candidates=[node for node, _score in matches])
        )

    pending = [outcome for outcome in outcomes if outcome.match == "none"]
    if pending and embeddings:
        vectors = await embeddings.embed_batch([entities[outcome.index].name for outcome in pending])
        for outcome, vector in zip(pending, vectors, strict=True):
            entity = entities[outcome.index]
            match, matches = await resolve_semantic_candidates(
                repo,
                agent_id,
                target_schema,
                entity.name,
                entity.type_name,
                vector,
                type_names=type_names,
            )
            outcome.match = match
            outcome.candidates = [node for node, _score in matches]

    for outcome in outcomes:
        entity = entities[outcome.index]
        if not entity.supersedes:
            continue
        match, matches = await resolve_entity_candidates(
            repo,
            embeddings,
            agent_id,
            target_schema,
            entity.supersedes,
            entity.type_name,
            type_names=type_names,
            semantic=False,
        )
        if match in {"exact", "alias"} and len(matches) == 1:
            outcome.predecessor = matches[0][0]
    return outcomes


def build_oneshot_items(entities: list[ExtractedEntity], outcomes: list[EntityResolutionOutcome]) -> list[OneshotItem]:
    """Build the model's work list: entities with candidates and no supersedes.

    An entity carrying ``supersedes`` is always a distinct create, so asking the
    model about it would only spend tokens on an answer the host overrides.
    """
    items: list[OneshotItem] = []
    for outcome in outcomes:
        entity = entities[outcome.index]
        if entity.supersedes or not outcome.candidates:
            continue
        items.append(
            OneshotItem(
                index=outcome.index,
                name=entity.name,
                type_name=entity.type_name,
                description=entity.description,
                properties=entity.properties,
                candidates=[
                    OneshotCandidate(
                        node_id=node.id,
                        name=node.name,
                        content=(node.content or "")[:CANDIDATE_CONTENT_CHARS],
                        properties=_scalar_properties(node.properties),
                    )
                    for node in outcome.candidates[:MAX_CANDIDATES]
                ],
            )
        )
    return items


def render_oneshot_items(items: list[OneshotItem]) -> str:
    """Render the work list as compact lines: one per entity, candidates indented."""
    lines: list[str] = []
    for item in items:
        lines.append(f"{item.index} | {item.name} | {item.type_name} | {item.description or ''}")
        for candidate in item.candidates:
            lines.append(f"  node_id={candidate.node_id} | {candidate.name} | {candidate.content}")
    return "\n".join(lines)


def _colliding_candidate(entity: ExtractedEntity, outcome: EntityResolutionOutcome) -> Any | None:
    """The offered candidate a ``create`` for this entity would overwrite.

    ``upsert_node`` dedups by name, so creating an entity whose canonical name
    equals a candidate's name does not add a node: it rewrites that candidate's
    content.  Such a create is therefore applied as a merge instead.
    """
    canonical, _aliases = canonicalize_name(entity.name)
    wanted = (canonical or entity.name).casefold()
    for node in outcome.candidates[:MAX_CANDIDATES]:
        if node.name.casefold() == wanted:
            return node
    if outcome.single_strong_match:
        return outcome.candidates[0]
    return None


def _decision_for(
    entity: ExtractedEntity,
    outcome: EntityResolutionOutcome,
    decision: OneshotDecision | None,
) -> tuple[str, Any, str | None]:
    """Return (action, node, content) after validating the model's decision.

    An unusable decision is not retried with the model: the host default wins.
    A ``create`` that would collide with an offered candidate is one such
    unusable decision, because the collision destroys the candidate's content.
    """
    candidates = {node.id: node for node in outcome.candidates[:MAX_CANDIDATES]}
    if decision is not None and not entity.supersedes and decision.decision != "create":
        node = candidates.get(decision.node_id) if decision.node_id is not None else None
        if node is not None and decision.decision == "unchanged":
            return "unchanged", node, None
        if node is not None and decision.decision == "merge" and decision.content:
            return "merge", node, decision.content[:MERGE_CONTENT_CHARS]

    if not entity.supersedes:
        collision = _colliding_candidate(entity, outcome)
        if collision is not None:
            return "merge", collision, _merge_content(collision.content, entity.description)
    return "create", None, None


def _chain_repeated_targets(plans: list[_NodePlan]) -> None:
    """Make a second write to one node build on the first write, not the snapshot.

    Two extracted entities can resolve to the same node (a name and one of its
    aliases).  Both merges were decided against the content read at resolution
    time, so applying them in order would drop the earlier one's fact.  Rebuild
    the later plan's content from what the run already decided to write.
    """
    decided: dict[int, str | None] = {}
    for plan in plans:
        if plan.node_id is None or plan.action == "unchanged":
            continue
        previous = decided.get(plan.node_id)
        if previous is not None:
            plan.content = _merge_content(previous, plan.new_fact)
        decided[plan.node_id] = plan.content


async def run_oneshot_librarian(
    *,
    repo: MemoryRepository,
    embeddings: EmbeddingService | None,
    agent_id: str,
    target_schema: str | None,
    episode_id: int | None,
    correlation_id: str | None,
    extraction: ExtractionResult,
    agent: Agent[Any, Any],
    cfg: AgentInferenceConfig,
    tracker: CurationActionTracker,
) -> CurationReport:
    """Resolve host-side, decide in at most one request, then apply.

    Returns the report the pipeline logs.  Emits the ``agent_usage`` and
    ``librarian_trajectory`` audit events for this profile; the pipeline still
    owns ``librarian_progress``, ``stage_timing``, and ``curation_complete``.
    """
    entities = extraction.entities
    audit = build_audit_fields("librarian_agent", cfg, agent_id, correlation_id or "unavailable", episode_id)

    outcomes = await resolve_extraction_entities(repo, embeddings, agent_id, target_schema, entities)
    items = build_oneshot_items(entities, outcomes)

    decisions: dict[int, OneshotDecision] = {}
    requests = 0
    if items:
        result = await agent.run(
            render_oneshot_items(items),
            deps=_deps(repo, embeddings, agent_id, target_schema, episode_id, correlation_id, extraction, tracker),
            model_settings=cfg.model_settings,
            usage_limits=UsageLimits(request_limit=ONESHOT_REQUEST_LIMIT),
        )
        usage = result.usage()
        requests = int(getattr(usage, "requests", 0))
        _log_usage(audit, usage)
        output = result.output
        if isinstance(output, OneshotDecisions):
            wanted = {item.index for item in items}
            # Later duplicates for one index lose to the first, and an index the
            # host never asked about is ignored.
            for decision in output.decisions:
                if decision.index in wanted and decision.index not in decisions:
                    decisions[decision.index] = decision

    report = await _apply(
        repo=repo,
        embeddings=embeddings,
        agent_id=agent_id,
        target_schema=target_schema,
        episode_id=episode_id,
        audit=audit,
        entities=entities,
        relations=extraction.relations,
        outcomes=outcomes,
        decisions=decisions,
        tracker=tracker,
    )
    logger.bind(action_log=True).info(
        "librarian_trajectory",
        **audit,
        profile="qwen_oneshot",
        expected_entities=len(entities),
        expected_relations=len(extraction.relations),
        terminal_counts=report.model_dump(exclude={"result_source", "status"}),
        requests=requests,
        provider_tool_calls=0,
        model_items=len(items),
        model_decisions=len(decisions),
        result_source="host_tracker",
    )
    return report


def _deps(
    repo: MemoryRepository,
    embeddings: EmbeddingService | None,
    agent_id: str,
    target_schema: str | None,
    episode_id: int | None,
    correlation_id: str | None,
    extraction: ExtractionResult,
    tracker: CurationActionTracker,
) -> Any:
    """Build the librarian deps the audit hooks read (no tools consume them)."""
    return LibrarianAgentDeps(
        episode_text="",
        node_types=[],
        edge_types=[],
        extracted_entities=extraction.entities,
        extracted_relations=extraction.relations,
        repo=repo,
        embeddings=embeddings,
        agent_id=agent_id,
        target_schema=target_schema,
        episode_id=episode_id,
        correlation_id=correlation_id,
        action_tracker=tracker,
    )


def _log_usage(audit: dict[str, object], usage: Any) -> None:
    """Write the provider-neutral numeric usage fields for the decision call."""
    details = getattr(usage, "details", {}) or {}
    logger.bind(action_log=True).info(
        "agent_usage",
        **audit,
        requests=int(getattr(usage, "requests", 0)),
        tool_calls=int(getattr(usage, "tool_calls", 0)),
        input_tokens=int(getattr(usage, "input_tokens", 0)),
        output_tokens=int(getattr(usage, "output_tokens", 0)),
        reasoning_tokens=details.get("reasoning_tokens"),
    )


async def _apply(
    *,
    repo: MemoryRepository,
    embeddings: EmbeddingService | None,
    agent_id: str,
    target_schema: str | None,
    episode_id: int | None,
    audit: dict[str, object],
    entities: list[ExtractedEntity],
    relations: list[Any],
    outcomes: list[EntityResolutionOutcome],
    decisions: dict[int, OneshotDecision],
    tracker: CurationActionTracker,
) -> CurationReport:
    """Apply entity decisions, temporal edges, and relations deterministically."""
    plans: list[_NodePlan] = []
    unresolved_entities = 0
    for outcome in outcomes:
        entity = entities[outcome.index]
        action, node, content = _decision_for(entity, outcome, decisions.get(outcome.index))
        properties: dict[str, Any] = {}
        if action == "create":
            node_type = await repo.get_or_create_node_type(agent_id, entity.type_name, target_schema=target_schema)
            if node_type is None:
                logger.bind(action_log=True, **audit).warning(
                    "skipping_entity_invalid_type",
                    entity_index=outcome.index,
                    accepted=False,
                    reason_code="normalization_rejected",
                )
                unresolved_entities += 1
                continue
            canonical, aliases = canonicalize_name(entity.name)
            properties.update(entity.properties)
            if episode_id is not None:
                properties["_source_episode"] = episode_id
            plans.append(
                _NodePlan(
                    index=outcome.index,
                    action="create",
                    name=canonical or entity.name,
                    type_id=node_type.id,
                    content=entity.description,
                    properties=properties,
                    importance=entity.importance,
                    new_fact=entity.description,
                    aliases=aliases,
                )
            )
            continue

        assert node is not None
        properties.update(node.properties or {})
        properties.update(entity.properties)
        if episode_id is not None:
            properties["_source_episode"] = episode_id
        plans.append(
            _NodePlan(
                index=outcome.index,
                action=action,
                name=node.name,
                type_id=node.type_id,
                content=content,
                properties=properties,
                importance=max(node.importance, entity.importance),
                new_fact=entity.description,
                node_id=node.id,
            )
        )

    _chain_repeated_targets(plans)

    # One embedding batch for everything that gets written.
    embedded: dict[int, list[float] | None] = {}
    if embeddings:
        writable = [plan for plan in plans if plan.action != "unchanged" and plan.content]
        if writable:
            vectors = await embeddings.embed_batch([str(plan.content) for plan in writable])
            for plan, vector in zip(writable, vectors, strict=True):
                embedded[plan.index] = vector

    bound: dict[int, int] = {}
    created = updated = unchanged = 0
    for plan in plans:
        if plan.action == "unchanged":
            assert plan.node_id is not None
            bound[plan.index] = plan.node_id
            unchanged += 1
            continue
        assert plan.type_id is not None
        node = await repo.upsert_node(
            agent_id=agent_id,
            name=plan.name,
            type_id=plan.type_id,
            content=plan.content,
            properties=plan.properties,
            embedding=embedded.get(plan.index),
            target_schema=target_schema,
            importance=plan.importance,
        )
        bound[plan.index] = node.id
        for alias in plan.aliases:
            await repo.register_alias(agent_id, node.id, alias, source="librarian", target_schema=target_schema)
        if plan.action == "create":
            created += 1
            tracker.record_node("created")
        else:
            updated += 1
            tracker.record_node("updated")

    # The host-mandated temporal edges are resolved here but written last.
    # ``upsert_edge`` rewrites the type of a lone edge between an ordered pair
    # ("type drift"), so an extractor relation over the same pair would silently
    # overwrite SUPERSEDES/CORRECTS if the temporal edge were written first.
    temporal_plans: list[tuple[int, int, int, dict[str, Any]]] = []
    for outcome in outcomes:
        entity = entities[outcome.index]
        if not entity.supersedes or outcome.predecessor is None or outcome.index not in bound:
            continue
        edge_type = await repo.get_or_create_edge_type(agent_id, _temporal_signal(entity), target_schema=target_schema)
        if edge_type is None:
            continue
        temporal_properties: dict[str, Any] = {"synthetic_temporal": True}
        if episode_id is not None:
            temporal_properties["_source_episode"] = episode_id
        temporal_plans.append((bound[outcome.index], outcome.predecessor.id, edge_type.id, temporal_properties))
    temporal_pairs = {(source_id, target_id) for source_id, target_id, _, _ in temporal_plans}

    edges_created = 0
    edges_unchanged = 0
    edges_unresolved = 0

    for relation in relations:
        source_id = _endpoint_id(entities, outcomes, bound, relation, source=True)
        target_id = _endpoint_id(entities, outcomes, bound, relation, source=False)
        if source_id is None or target_id is None:
            edges_unresolved += 1
            logger.bind(action_log=True, **audit).warning(
                "edge_skipped_missing_node",
                source_id=source_id,
                target_id=target_id,
                source_present=source_id is not None,
                target_present=target_id is not None,
                reason_code="missing_node",
            )
            continue
        if (source_id, target_id) in temporal_pairs:
            edges_unchanged += 1
            logger.bind(action_log=True, **audit).warning(
                "edge_skipped_temporal_pair",
                source_id=source_id,
                target_id=target_id,
                reason_code="temporal_pair",
            )
            continue
        edge_type = await repo.get_or_create_edge_type(agent_id, relation.relation_type, target_schema=target_schema)
        if edge_type is None:
            edges_unresolved += 1
            logger.bind(action_log=True, **audit).warning(
                "edge_skipped_invalid_type",
                accepted=False,
                reason_code="normalization_rejected",
            )
            continue
        edge_properties = dict(relation.properties)
        if episode_id is not None:
            edge_properties["_source_episode"] = episode_id
        edge = await repo.upsert_edge(
            agent_id,
            source_id,
            target_id,
            edge_type.id,
            weight=relation.weight,
            properties=edge_properties,
            target_schema=target_schema,
        )
        if edge is None:
            edges_unresolved += 1
            logger.bind(action_log=True, **audit).warning(
                "edge_skipped_upsert_failed",
                source_id=source_id,
                target_id=target_id,
                reason_code="upsert_failed",
            )
            continue
        edges_created += 1
        tracker.record_edge_upsert()

    for source_id, target_id, temporal_type_id, temporal_properties in temporal_plans:
        edge = await repo.upsert_edge(
            agent_id,
            source_id,
            target_id,
            temporal_type_id,
            weight=1.0,
            properties=temporal_properties,
            target_schema=target_schema,
        )
        if edge is None:
            edges_unresolved += 1
            logger.bind(action_log=True, **audit).warning(
                "edge_skipped_upsert_failed",
                source_id=source_id,
                target_id=target_id,
                reason_code="upsert_failed",
            )
            continue
        edges_created += 1
        tracker.record_edge_upsert()

    return CurationReport(
        status="completed_with_unresolved" if unresolved_entities or edges_unresolved else "completed",
        entities_created=created,
        entities_updated=updated,
        entities_unchanged=unchanged,
        entities_unresolved=unresolved_entities,
        entities_archived=0,
        edges_created=edges_created,
        edges_unchanged=edges_unchanged,
        edges_unresolved=edges_unresolved,
        edges_removed=0,
        pending_entities=0,
        pending_relations=0,
    )


def _endpoint_id(
    entities: list[ExtractedEntity],
    outcomes: list[EntityResolutionOutcome],
    bound: dict[int, int],
    relation: Any,
    *,
    source: bool,
) -> int | None:
    """Resolve one relation endpoint by case-insensitive extracted-entity name.

    Same rule as the bounded profile: a target naming the predecessor of a
    superseding source binds to that predecessor node.
    """
    wanted = relation.source_name if source else relation.target_name
    for index, entity in enumerate(entities):
        if entity.name.casefold() == wanted.casefold():
            return bound.get(index)
        if (
            not source
            and entity.name.casefold() == relation.source_name.casefold()
            and entity.supersedes
            and entity.supersedes.casefold() == wanted.casefold()
        ):
            predecessor = outcomes[index].predecessor
            return predecessor.id if predecessor is not None else None
    return None
