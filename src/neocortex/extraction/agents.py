"""Three-agent extraction pipeline: ontology, extractor, librarian.

Each agent is built via a factory function that accepts an inference config.
Agents are domain-agnostic — they work with any text, not just medical content.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from hashlib import sha256
from math import ceil
from time import monotonic
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger
from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import Hooks
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.models import Model
from pydantic_ai.models.test import TestModel
from pydantic_ai.settings import ModelSettings, ThinkingLevel

from neocortex.model_factory import (
    QWEN_MAX_OUTPUT_TOKENS,
    LocalEndpoint,
    build_model,
    build_model_settings,
    is_qwen_model,
)

if TYPE_CHECKING:
    from neocortex.db.protocol import MemoryRepository
    from neocortex.embedding_service import EmbeddingService

from neocortex.extraction.schemas import (
    CurationReport,
    CurationSummary,
    DecisionOutcomeBatch,
    EntityCandidate,
    EntityDecision,
    EntityDecisionKind,
    EntityDetail,
    EntityDetailBatch,
    EntityDetailRequest,
    EntityResolution,
    EntityResolutionBatch,
    ExtractedEntity,
    ExtractedRelation,
    ExtractionResult,
    LibrarianPayload,
    LibrarianTerminal,
    OneshotDecisions,
    OntologyProposal,
    RelationCheck,
    RelationCheckBatch,
    RelationDecision,
    RelationDecisionKind,
    TemporalPredecessorCandidate,
    ToolOutcome,
    ToolReason,
)

# Plan 33 introduces an opt-in local: model route; Stage 9 changes defaults after the gate.
DEFAULT_MODEL_NAME = "openai-responses:gpt-5.4-mini"
DEFAULT_THINKING_EFFORT = "low"
# Keep this in one place with the librarian Agent construction.  The pipeline
# uses the same value when deriving its operational request budget.
DEFAULT_LIBRARIAN_RETRIES = 1

# Qwen entity budget: the local endpoint decodes at ~34 tokens/s, so the size of
# the extractor's output is the dominant cost of an episode.  The cap scales with
# the episode instead of being a flat number, and is enforced twice: the prompt
# states it, and the host trims what comes back.
QWEN_ENTITY_CAP_MIN = 4
QWEN_ENTITY_CAP_MAX = 12
QWEN_ENTITY_CAP_WORDS_PER_ENTITY = 8
# Type names shown to the tool-free Qwen ontology agent, per kind.
QWEN_ONTOLOGY_TYPE_LIST_LIMIT = 40


def qwen_entity_cap(text: str) -> int:
    """Return the Qwen entity budget for one episode: min(12, max(4, ceil(words/8)))."""
    words = len(text.split())
    return min(QWEN_ENTITY_CAP_MAX, max(QWEN_ENTITY_CAP_MIN, ceil(words / QWEN_ENTITY_CAP_WORDS_PER_ENTITY)))


def cap_extraction_entities(result: ExtractionResult, cap: int) -> ExtractionResult:
    """Keep the ``cap`` most important entities and drop now-dangling relations.

    Selection is by descending ``importance``; ties keep the extractor's order.
    Survivors are returned in the extractor's original order, because the
    librarian addresses entities by index.  Returns the same object when the
    result already fits, so a compliant model pays nothing for the guard.
    """
    if len(result.entities) <= cap:
        return result
    ranked = sorted(enumerate(result.entities), key=lambda item: -item[1].importance)
    kept_indices = {index for index, _entity in ranked[:cap]}
    entities = [entity for index, entity in enumerate(result.entities) if index in kept_indices]
    names = {entity.name for entity in entities}
    relations = [r for r in result.relations if r.source_name in names and r.target_name in names]
    return ExtractionResult(entities=entities, relations=relations, rationale=result.rationale)


def _qwen_output_cap(config: AgentInferenceConfig, agent_kind: str) -> int | None:
    """Return the max output tokens for one Qwen agent, or None for other models.

    ``AgentInferenceConfig.max_output_tokens`` (fed by ``MCPSettings`` in the
    worker) wins; otherwise the code default applies, so every caller of the
    builders gets the ceiling without having to know about it.
    """
    if not is_qwen_model(config.model_name):
        return None
    return config.max_output_tokens if config.max_output_tokens is not None else QWEN_MAX_OUTPUT_TOKENS[agent_kind]


def _qwen_output_cap_settings(config: AgentInferenceConfig, agent_kind: str) -> ModelSettings | None:
    """Agent-level settings carrying only the Qwen output ceiling.

    Run-level ``model_settings`` are merged over these, so the ceiling survives
    without the call sites having to know about it.
    """
    cap = _qwen_output_cap(config, agent_kind)
    return None if cap is None else ModelSettings(max_tokens=cap)


# Tool names are code-owned identifiers.  Keep the allow-list here so an
# untrusted model-provided tool name cannot become a free-form action-log
# field.  The same hook is also used by the ontology and domain agents.
_AUDIT_TOOL_NAMES = frozenset(
    {
        "archive_node",
        "create_or_update_edge",
        "create_or_update_node",
        "find_node_by_name",
        "find_similar_nodes",
        "find_similar_types",
        "get_edges_between",
        "get_ontology_overview",
        "inspect_node_neighborhood",
        "propose_type",
        "remove_edge",
        "search_existing_nodes",
        "resolve_entities",
        "read_entity_details",
        "apply_entity_decisions",
        "check_relations",
        "apply_relation_decisions",
    }
)


def _safe_tool_name(tool_name: str) -> str:
    """Return a static tool identity suitable for the durable action log."""
    return tool_name if tool_name in _AUDIT_TOOL_NAMES else "unknown"


def _opaque_call_id(call_id: str | None) -> str | None:
    """Keep tool-call correlation without persisting model-controlled text."""
    if call_id is None:
        return None
    return sha256(call_id.encode("utf-8", errors="replace")).hexdigest()[:16]


@dataclass
class CurationActionTracker:
    """Counts successful graph mutations performed by one librarian run.

    The model's structured summary is not authoritative: it can be empty or
    stale after a long tool loop.  Mutation tools update this tracker only
    after the repository operation succeeds, and the pipeline uses these
    counters for its durable completion event.
    """

    entities_created: int = 0
    entities_updated: int = 0
    entities_archived: int = 0
    edges_created: int = 0
    edges_removed: int = 0

    def record_node(self, action: str) -> None:
        if action == "created":
            self.entities_created += 1
        elif action == "updated":
            self.entities_updated += 1

    def record_edge_upsert(self) -> None:
        # The repository API returns the resulting edge, not a created/updated
        # discriminator.  Count each successful upsert as an edge action.
        self.edges_created += 1

    def record_archive(self, archived: bool) -> None:
        if archived:
            self.entities_archived += 1

    def record_edge_removal(self, removed: bool) -> None:
        if removed:
            self.edges_removed += 1


@dataclass(frozen=True)
class LibrarianBudgetConfig:
    entity_read_limit: int = 2
    relation_read_limit: int = 1
    soft_read_streak: int = 6
    hard_read_streak: int = 10
    soft_no_progress_calls: int = 8
    hard_no_progress_calls: int = 14
    max_duplicate_calls: int = 2

    def __post_init__(self) -> None:
        if any(value < 1 for value in self.__dict__.values()):
            raise ValueError("librarian budget values must all be at least one")


class LibrarianTrajectoryLimitExceeded(RuntimeError):  # noqa: N818 - frozen public contract
    """A bounded librarian exceeded a host-enforced trajectory budget."""


class LibrarianIncompleteError(RuntimeError):
    """The model declared completion while indexed work remained pending."""


class LibrarianIdentityMismatch(RuntimeError):  # noqa: N818 - frozen public contract
    """An update did not preserve the resolver-bound repository identity."""


LibrarianProfile = Literal["hosted", "qwen_legacy", "qwen_finite", "qwen_bounded", "qwen_oneshot"]


@dataclass
class LibrarianTrajectoryTracker(CurationActionTracker):
    """Host authority for bounded librarian work, progress, and budgets."""

    entities: list[ExtractedEntity] = field(default_factory=list)
    relations: list[ExtractedRelation] = field(default_factory=list)
    budget: LibrarianBudgetConfig = field(default_factory=LibrarianBudgetConfig)
    entity_states: dict[int, str] = field(init=False)
    relation_states: dict[int, str] = field(init=False)
    entity_candidates: dict[int, dict[int, Any]] = field(default_factory=dict)
    selected_nodes: dict[int, int] = field(default_factory=dict)
    bound_node_ids: dict[int, int] = field(default_factory=dict)
    detailed_entities: set[int] = field(default_factory=set)
    truncated_entities: set[int] = field(default_factory=set)
    resolved_entities: set[int] = field(default_factory=set)
    entity_resolution_reason: dict[int, str] = field(default_factory=dict)
    temporal_predecessors: dict[int, int] = field(default_factory=dict)
    checked_edges: dict[int, set[int]] = field(default_factory=dict)
    entity_reads: dict[int, int] = field(default_factory=dict)
    relation_reads: dict[int, int] = field(default_factory=dict)
    provider_batch_calls: int = 0
    repository_item_reads: int = 0
    mutations_attempted: int = 0
    mutations_succeeded: int = 0
    duplicate_calls: int = 0
    validation_rejections: int = 0
    host_normalization_count: int = 0
    read_streak: int = 0
    max_read_streak: int = 0
    calls_since_progress: int = 0
    soft_reasons: set[str] = field(default_factory=set)
    hard_reason: str | None = None
    seen_item_calls: set[tuple[str, int]] = field(default_factory=set)
    successful_node_ids: set[int] = field(default_factory=set)
    successful_edge_ids: set[int] = field(default_factory=set)
    successful_edge_signatures: dict[int, tuple[int, int, int]] = field(default_factory=dict)
    removed_edge_ids: set[int] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.entity_states = {index: "pending" for index in range(len(self.entities))}
        self.relation_states = {index: "pending" for index in range(len(self.relations))}

    def normalize_indices(self, indices: list[int], count: int, limit: int) -> list[int]:
        if not indices or any(index < 0 for index in indices):
            raise ValueError("indices must be non-empty and non-negative")
        normalized = sorted(set(indices))
        if len(normalized) > limit:
            raise ValueError("unique index count exceeds the batch limit")
        if normalized[-1] >= count:
            raise ValueError("item index out of range")
        if normalized != indices:
            self.host_normalization_count += 1
        return normalized

    def _record_duplicate(self) -> None:
        self.duplicate_calls += 1
        if self.duplicate_calls > self.budget.max_duplicate_calls:
            self.hard_reason = "duplicate_calls"
            raise LibrarianTrajectoryLimitExceeded(self.hard_reason)

    def begin_call(self, tool: str, indices: list[int], *, read: bool) -> set[int]:
        if self.hard_reason:
            raise LibrarianTrajectoryLimitExceeded(self.hard_reason)
        if self.calls_since_progress >= self.budget.hard_no_progress_calls:
            self.hard_reason = "no_progress"
            raise LibrarianTrajectoryLimitExceeded(self.hard_reason)
        if read and self.read_streak >= self.budget.hard_read_streak:
            self.hard_reason = "read_streak"
            raise LibrarianTrajectoryLimitExceeded(self.hard_reason)
        pessimistic_minimum = (
            ceil(len(self.entities) / 16)
            + ceil(len(self.entities) / 8)
            + ceil(len(self.entities) / 8)
            + ceil(len(self.relations) / 16)
            + ceil(len(self.relations) / 8)
        )
        if self.provider_batch_calls >= pessimistic_minimum + self.budget.hard_no_progress_calls:
            self.hard_reason = "provider_call_limit"
            raise LibrarianTrajectoryLimitExceeded(self.hard_reason)
        self.provider_batch_calls += 1
        self.calls_since_progress += 1
        if read:
            self.read_streak += 1
            self.max_read_streak = max(self.max_read_streak, self.read_streak)
            if self.read_streak >= self.budget.soft_read_streak:
                self.soft_reasons.add("read_streak")
        else:
            self.read_streak = 0
        if self.calls_since_progress >= self.budget.soft_no_progress_calls:
            self.soft_reasons.add("no_progress")
        if self.provider_batch_calls >= pessimistic_minimum + 4:
            self.soft_reasons.add("provider_call_limit")
        duplicates: set[int] = set()
        for index in indices:
            key = (tool, index)
            if key in self.seen_item_calls:
                self._record_duplicate()
                duplicates.add(index)
            else:
                self.seen_item_calls.add(key)
        return duplicates

    def record_progress(self) -> None:
        self.calls_since_progress = 0

    def record_rejection(self, tool: str, index: int) -> None:
        """Leave recoverable work pending so a corrected decision can be retried."""
        self.validation_rejections += 1
        self.seen_item_calls.discard((tool, index))

    def consume_entity_read(self, index: int) -> None:
        count = self.entity_reads.get(index, 0)
        if count >= self.budget.entity_read_limit:
            self.hard_reason = "entity_read_limit"
            raise LibrarianTrajectoryLimitExceeded(self.hard_reason)
        self.entity_reads[index] = count + 1
        self.repository_item_reads += 1

    def consume_relation_read(self, index: int) -> None:
        count = self.relation_reads.get(index, 0)
        if count >= self.budget.relation_read_limit:
            self.hard_reason = "relation_read_limit"
            raise LibrarianTrajectoryLimitExceeded(self.hard_reason)
        self.relation_reads[index] = count + 1
        self.repository_item_reads += 1

    def build_report(self) -> CurationReport:
        pending_entities = sum(state == "pending" for state in self.entity_states.values())
        pending_relations = sum(state == "pending" for state in self.relation_states.values())
        if pending_entities or pending_relations:
            raise LibrarianIncompleteError(
                f"librarian finished with {pending_entities} entities and {pending_relations} relations pending"
            )
        entity_unresolved = sum(state == "unresolved" for state in self.entity_states.values())
        relation_unresolved = sum(state == "unresolved" for state in self.relation_states.values())
        status = "completed_with_unresolved" if entity_unresolved or relation_unresolved else "completed"
        return CurationReport(
            status=status,
            entities_created=sum(state == "created" for state in self.entity_states.values()),
            entities_updated=sum(state == "updated" for state in self.entity_states.values()),
            entities_unchanged=sum(state == "unchanged" for state in self.entity_states.values()),
            entities_unresolved=entity_unresolved,
            entities_archived=self.entities_archived,
            edges_created=sum(state == "created" for state in self.relation_states.values()),
            edges_unchanged=sum(state == "unchanged" for state in self.relation_states.values()),
            edges_unresolved=relation_unresolved,
            edges_removed=self.edges_removed,
            pending_entities=0,
            pending_relations=0,
        )

    @property
    def all_entities_terminal(self) -> bool:
        return all(state != "pending" for state in self.entity_states.values())


def build_librarian_relation_items(
    entities: list[ExtractedEntity], relations: list[ExtractedRelation]
) -> list[ExtractedRelation]:
    """Append missing explicit temporal relations in stable entity order."""
    result = list(relations)
    existing = {(r.source_name, r.target_name, r.relation_type) for r in result}
    for entity in entities:
        if not entity.supersedes or not entity.temporal_signal:
            continue
        key = (entity.name, entity.supersedes, entity.temporal_signal)
        if key not in existing:
            result.append(
                ExtractedRelation(
                    source_name=entity.name,
                    target_name=entity.supersedes,
                    relation_type=entity.temporal_signal,
                    properties={"synthetic_temporal": True},
                )
            )
            existing.add(key)
    return result


def _entity_allowed_decisions(
    tracker: LibrarianTrajectoryTracker, index: int, *, after_detail: bool
) -> list[EntityDecisionKind]:
    """Return the decisions accepted by the host for one entity at this phase."""
    selected = tracker.selected_nodes.get(index)
    reason = tracker.entity_resolution_reason.get(index)
    if selected is None:
        return ["unresolved"] if reason in {"ambiguous", "ambiguous_homonym"} else ["create"]
    if not after_detail or index not in tracker.detailed_entities:
        return []
    allowed: list[EntityDecisionKind] = ["unchanged"]
    if index in tracker.truncated_entities:
        allowed.append("unresolved")
    else:
        allowed.insert(0, "update")
    entity = tracker.entities[index]
    if entity.supersedes and entity.temporal_signal:
        allowed.append("archive_then_create")
    return allowed


@dataclass
class AgentInferenceConfig:
    """Per-agent inference configuration (model, thinking budget, etc.)."""

    model_name: str = DEFAULT_MODEL_NAME
    thinking_effort: ThinkingLevel | None = DEFAULT_THINKING_EFFORT
    use_test_model: bool = False
    local_endpoint: LocalEndpoint | None = None
    # Overrides the per-agent NEOCORTEX_*_MAX_TOKENS setting; Qwen models only.
    max_output_tokens: int | None = None

    @property
    def model_settings(self) -> ModelSettings | None:
        """Build pydantic-ai model_settings dict for agent.run()."""
        if self.thinking_effort is not None:
            return build_model_settings(
                self.thinking_effort,
                self.model_name,
                self.local_endpoint,
                max_output_tokens=self.max_output_tokens,
            )
        return None


def _endpoint_identity(config: AgentInferenceConfig) -> str:
    """Return a credential-free endpoint identity for audit events."""
    if config.local_endpoint is None or not config.local_endpoint.base_url:
        return "hosted"
    # The configured endpoint is an operator-controlled URL.  Keep only its
    # scheme, host, and path so a malformed URL cannot copy credentials or
    # query parameters into the durable action log.
    from urllib.parse import urlsplit, urlunsplit

    parsed = urlsplit(config.local_endpoint.base_url)
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path.rstrip("/"), "", ""))


def build_audit_fields(
    stage: str,
    config: AgentInferenceConfig,
    agent_id: str,
    correlation_id: str,
    episode_id: int | None = None,
) -> dict[str, object]:
    """Return common non-secret fields for a pipeline-stage audit event.

    Shared by ``extraction.pipeline`` and ``extraction.oneshot_librarian`` so
    every stage event carries the same credential-free dimensions.
    """
    return {
        "stage": stage,
        "agent": stage.removesuffix("_agent"),
        "agent_id": agent_id,
        "episode_id": episode_id,
        "correlation_id": correlation_id,
        "model": config.model_name.removeprefix("local:"),
        "endpoint": _endpoint_identity(config),
        "effort": config.thinking_effort,
        "run_id": os.environ.get("NEOCORTEX_BAKEOFF_RUN_ID") or "unavailable",
    }


def _audit_dimensions(ctx: RunContext[Any], agent_name: str, config: AgentInferenceConfig) -> dict[str, object]:
    """Build common, non-secret fields for model/tool audit records."""
    deps = ctx.deps
    return {
        "agent": agent_name,
        "agent_id": getattr(deps, "agent_id", None) or "unknown",
        "episode_id": getattr(deps, "episode_id", None),
        "correlation_id": getattr(deps, "correlation_id", None) or "unavailable",
        "model": config.model_name.removeprefix("local:"),
        "endpoint": _endpoint_identity(config),
        "effort": config.thinking_effort,
        "run_id": os.environ.get("NEOCORTEX_BAKEOFF_RUN_ID") or ctx.run_id,
    }


def build_audit_hooks(agent_name: str, config: AgentInferenceConfig) -> Hooks:
    """Create PydanticAI lifecycle hooks for the structured action log.

    The hooks deliberately record event metadata only.  Prompts, model output,
    tool arguments, and credentials do not belong in ``agent_actions.log``.
    PydanticAI retries output validation and tool execution through the model
    request loop; request records include the retry counter, and validation or
    tool errors identify the rejection cause.
    """
    started: dict[tuple[str, str], float] = {}

    def key(kind: str, identifier: str | None, ctx: RunContext[Any]) -> tuple[str, str]:
        return kind, identifier or f"step-{ctx.run_step}"

    async def before_run(ctx: RunContext[Any]) -> None:
        logger.bind(action_log=True).info(
            "agent_run_started",
            **_audit_dimensions(ctx, agent_name, config),
        )
        started[key("run", ctx.run_id, ctx)] = monotonic()

    async def after_run(ctx: RunContext[Any], *, result: Any) -> Any:
        run_key = key("run", ctx.run_id, ctx)
        logger.bind(action_log=True).info(
            "agent_run_completed",
            **_audit_dimensions(ctx, agent_name, config),
            elapsed_s=round(monotonic() - started.pop(run_key, monotonic()), 4),
            output_type=type(result.output).__name__,
        )
        return result

    async def on_run_error(ctx: RunContext[Any], *, error: BaseException) -> Any:
        logger.bind(action_log=True).warning(
            "agent_run_failed",
            **_audit_dimensions(ctx, agent_name, config),
            error_type=type(error).__name__,
            retry=ctx.retry,
            max_retries=ctx.max_retries,
        )
        raise error

    async def before_model_request(ctx: RunContext[Any], request_context: Any) -> Any:
        request_key = key("model", str(ctx.run_step), ctx)
        started[request_key] = monotonic()
        dimensions = _audit_dimensions(ctx, agent_name, config)
        logger.bind(action_log=True).info(
            "model_request_started",
            **dimensions,
            request_step=ctx.run_step,
            retry=ctx.retry,
            max_retries=ctx.max_retries,
        )
        if ctx.retry > 0:
            logger.bind(action_log=True).info(
                "output_validation_retry",
                **dimensions,
                request_step=ctx.run_step,
                retry=ctx.retry,
                max_retries=ctx.max_retries,
                cause="agent_retry_loop",
            )
        return request_context

    async def after_model_request(ctx: RunContext[Any], *, request_context: Any, response: Any) -> Any:
        request_key = key("model", str(ctx.run_step), ctx)
        logger.bind(action_log=True).info(
            "model_request_completed",
            **_audit_dimensions(ctx, agent_name, config),
            request_step=ctx.run_step,
            retry=ctx.retry,
            elapsed_s=round(monotonic() - started.pop(request_key, monotonic()), 4),
        )
        return response

    async def on_model_request_error(ctx: RunContext[Any], *, request_context: Any, error: Exception) -> Any:
        request_key = key("model", str(ctx.run_step), ctx)
        logger.bind(action_log=True).warning(
            "model_request_failed",
            **_audit_dimensions(ctx, agent_name, config),
            request_step=ctx.run_step,
            retry=ctx.retry,
            elapsed_s=round(monotonic() - started.pop(request_key, monotonic()), 4),
            error_type=type(error).__name__,
        )
        raise error

    async def before_tool_execute(ctx: RunContext[Any], *, call: ToolCallPart, tool_def: Any, args: Any) -> Any:
        del tool_def
        call_key = key("tool", call.tool_call_id, ctx)
        started[call_key] = monotonic()
        logger.bind(action_log=True).info(
            "tool_call_started",
            **_audit_dimensions(ctx, agent_name, config),
            tool=_safe_tool_name(call.tool_name),
            tool_call_id=_opaque_call_id(call.tool_call_id),
            retry=ctx.retry,
        )
        return args

    async def after_tool_execute(
        ctx: RunContext[Any], *, call: ToolCallPart, tool_def: Any, args: Any, result: Any
    ) -> Any:
        del tool_def, args
        call_key = key("tool", call.tool_call_id, ctx)
        logger.bind(action_log=True).info(
            "tool_call_completed",
            **_audit_dimensions(ctx, agent_name, config),
            tool=_safe_tool_name(call.tool_name),
            tool_call_id=_opaque_call_id(call.tool_call_id),
            retry=ctx.retry,
            elapsed_s=round(monotonic() - started.pop(call_key, monotonic()), 4),
            result_type=type(result).__name__,
        )
        return result

    async def on_tool_execute_error(
        ctx: RunContext[Any], *, call: ToolCallPart, tool_def: Any, args: Any, error: Exception
    ) -> Any:
        del tool_def, args
        call_key = key("tool", call.tool_call_id, ctx)
        logger.bind(action_log=True).warning(
            "tool_call_failed",
            **_audit_dimensions(ctx, agent_name, config),
            tool=_safe_tool_name(call.tool_name),
            tool_call_id=_opaque_call_id(call.tool_call_id),
            retry=ctx.retry,
            elapsed_s=round(monotonic() - started.pop(call_key, monotonic()), 4),
            error_type=type(error).__name__,
        )
        raise error

    async def on_tool_validate_error(
        ctx: RunContext[Any], *, call: ToolCallPart, tool_def: Any, args: Any, error: Any
    ) -> Any:
        del tool_def, args
        tracker = getattr(ctx.deps, "action_tracker", None)
        if isinstance(tracker, LibrarianTrajectoryTracker):
            tracker.validation_rejections += 1
            tracker.calls_since_progress += 1
        logger.bind(action_log=True).warning(
            "tool_validation_rejected",
            **_audit_dimensions(ctx, agent_name, config),
            tool=_safe_tool_name(call.tool_name),
            tool_call_id=_opaque_call_id(call.tool_call_id),
            retry=ctx.retry,
            max_retries=ctx.max_retries,
            error_type=type(error).__name__,
            retryable=isinstance(error, ModelRetry),
        )
        raise error

    return Hooks(
        before_run=before_run,
        after_run=after_run,
        run_error=on_run_error,
        before_model_request=before_model_request,
        after_model_request=after_model_request,
        model_request_error=on_model_request_error,
        before_tool_execute=before_tool_execute,
        after_tool_execute=after_tool_execute,
        tool_execute_error=on_tool_execute_error,
        tool_validate_error=on_tool_validate_error,
    )


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
    episode_id: int | None = None
    correlation_id: str | None = None


def _type_usage_line(entries: list[dict[str, Any]]) -> str:
    """Render ``name x usage`` for the used types, most used first."""
    used = [entry for entry in entries if int(entry["usage_count"]) > 0]
    used.sort(key=lambda entry: (-int(entry["usage_count"]), str(entry["name"])))
    return ", ".join(f"{entry['name']}x{entry['usage_count']}" for entry in used[:QWEN_ONTOLOGY_TYPE_LIST_LIMIT])


async def _ontology_overview_lines(deps: OntologyAgentDeps) -> list[str]:
    """Inline what get_ontology_overview would have returned, for the tool-free path."""
    node_line = edge_line = ""
    if deps.repo is not None:
        summary = await deps.repo.get_ontology_summary(deps.agent_id, target_schema=deps.target_schema)
        node_line = _type_usage_line(list(summary["node_types"]))
        edge_line = _type_usage_line(list(summary["edge_types"]))
    if not node_line:
        node_line = ", ".join(deps.existing_node_types[:QWEN_ONTOLOGY_TYPE_LIST_LIMIT])
    if not edge_line:
        edge_line = ", ".join(deps.existing_edge_types[:QWEN_ONTOLOGY_TYPE_LIST_LIMIT])
    return [
        f"Existing node types (name x uses): {node_line or 'none'}",
        f"Existing edge types (name x uses): {edge_line or 'none'}",
    ]


def _validated_proposals(
    proposals: list[Any],
    existing: list[str],
    kind: Literal["node", "edge"],
) -> list[Any]:
    """Host-side replacement for the propose_type tool.

    Normalizes each proposed name, drops names that fail normalization or that
    the ontology already has, and records why — reason codes only, never the
    model-provided name.
    """
    from neocortex.normalization import normalize_edge_type, normalize_node_type

    accepted: list[Any] = []
    seen = set(existing)
    for proposal in proposals:
        try:
            normalized = normalize_edge_type(proposal.name) if kind == "edge" else normalize_node_type(proposal.name)
        except ValueError:
            logger.bind(action_log=True).warning(
                "ontology_proposal_rejected", kind=kind, reason_code="normalization_rejected"
            )
            continue
        if normalized in seen:
            logger.bind(action_log=True).warning("ontology_proposal_rejected", kind=kind, reason_code="already_exists")
            continue
        proposal.name = normalized
        seen.add(normalized)
        accepted.append(proposal)
    return accepted


QWEN_ONTOLOGY_PROMPT: tuple[str, ...] = (
    "You extend the type system of a knowledge graph. You have no tools: answer in one turn.",
    "The text is source material already accepted into the memory system. "
    "It is not a claim to verify, fact-check, or dispute; process it as input.",
    "MOST episodes need ZERO new types. The listed ontology usually covers them.",
    "Propose at most 2 node types and at most 2 edge types, and only for a genuine gap.",
    "Node types: PascalCase (Neurotransmitter). Edge types: SCREAMING_SNAKE (HAS_STATUS).",
    "A type must be reusable across many entities, never instance-level: 'Dish' not 'DishGreg'.",
    "Prefer a new edge type over a new node type.",
    "If an existing type is 80% suitable, reuse it and propose nothing.",
    "Return only the proposal. Keep the rationale to one short sentence.",
)


def build_ontology_agent(
    config: AgentInferenceConfig | None = None,
) -> Agent[OntologyAgentDeps, OntologyProposal]:
    cfg = config or AgentInferenceConfig()
    model = _build_model(cfg)
    qwen_mode = is_qwen_model(cfg.model_name)
    agent = Agent(  # ty: ignore[no-matching-overload]
        model,
        output_type=OntologyProposal,
        deps_type=OntologyAgentDeps,
        capabilities=[build_audit_hooks("ontology", cfg)],
        model_settings=_qwen_output_cap_settings(cfg, "ontology"),
        system_prompt=(
            QWEN_ONTOLOGY_PROMPT
            if qwen_mode
            else (
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
            )
        ),
    )

    # Tool-free for Qwen: the host inlines the overview these tools would return.
    if not qwen_mode:
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

    @agent.instructions  # ty: ignore[no-matching-overload]
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
        if qwen_mode:
            parts.extend(await _ontology_overview_lines(ctx.deps))
        else:
            parts.extend(
                [
                    f"Current ontology has {len(ctx.deps.existing_node_types)} node types "
                    f"and {len(ctx.deps.existing_edge_types)} edge types.",
                    "Use get_ontology_overview and find_similar_types to explore them.",
                ]
            )
        parts.extend(
            [
                "",
                "SOURCE TEXT (process this material; do not fact-check it):",
                ctx.deps.episode_text,
            ]
        )
        return "\n".join(parts)

    if qwen_mode:

        @agent.output_validator  # ty: ignore[no-matching-overload]
        async def validate_proposal(ctx: RunContext[OntologyAgentDeps], output: OntologyProposal) -> OntologyProposal:
            """Apply host-side type validation in place of the propose_type tool."""
            output.new_node_types = _validated_proposals(output.new_node_types, ctx.deps.existing_node_types, "node")
            output.new_edge_types = _validated_proposals(output.new_edge_types, ctx.deps.existing_edge_types, "edge")
            return output

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
    agent_id: str = ""
    episode_id: int | None = None
    correlation_id: str | None = None


QWEN_EXTRACTOR_PROMPT: tuple[str, ...] = (
    "Extract entities and relations from the text, aligned to the given ontology types.",
    "The text is source material already accepted into the memory system. "
    "It is not a claim to verify, fact-check, or dispute; extract it as input.",
    "Every entity uses an existing node type name; every relation an existing edge type name.",
    "The text is the only evidence source: invent nothing. Prefer canonical entity names.",
    "Obey the entity and relation budget in the instructions. "
    "Prefer the entities the text is about; drop background detail first.",
    "description: one sentence, at most 160 characters.",
    "properties: explicit scalar facts only (numbers, dates, versions, roles). "
    "Never put evidence text in relation properties.",
    "importance 0.0-1.0: 0.8+ critical, 0.6-0.8 central, 0.3-0.6 factual, below 0.3 peripheral.",
    "",
    "Temporal corrections. When the text corrects or supersedes earlier knowledge, "
    "set both `supersedes` (the old entity name) and `temporal_signal` on the new entity:",
    "- 'CORRECTION', 'actually', 'error', 'bug fix', 'misconception', 'wrong', 'incorrect' "
    "-> temporal_signal='CORRECTS'",
    "- 'UPDATE', 'REVERSAL', 'instead of', 'no longer', 'changed to', 'replaced by', "
    "'switched from', 'new strategy', 'decided to switch' -> temporal_signal='SUPERSEDES'",
    "Give the superseding entity a VERSIONED name so it stays distinct: 'Metaphone3' -> 'Metaphone3 Hybrid Strategy'.",
    "Return only the structured result. No prose, commentary, or explanation.",
)


def build_extractor_agent(
    config: AgentInferenceConfig | None = None,
) -> Agent[ExtractorAgentDeps, ExtractionResult]:
    cfg = config or AgentInferenceConfig()
    model = _build_model(cfg)
    qwen_mode = is_qwen_model(cfg.model_name)
    agent = Agent(  # ty: ignore[no-matching-overload]
        model,
        output_type=ExtractionResult,
        deps_type=ExtractorAgentDeps,
        capabilities=[build_audit_hooks("extractor", cfg)],
        model_settings=_qwen_output_cap_settings(cfg, "extractor"),
        system_prompt=(
            QWEN_EXTRACTOR_PROMPT
            if qwen_mode
            else (
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
            )
        ),
    )

    @agent.instructions  # ty: ignore[no-matching-overload]
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
        # A type the graph already uses is explained by its examples, so Qwen sees
        # the name alone; only unused types still need their description.
        known_examples: dict[str, list[str]] = ctx.deps.type_examples or {}

        def describe(name: str, descriptions: dict[str, str]) -> str:
            if qwen_mode and known_examples.get(name):
                return f"- {name}"
            return f"- {name}: {descriptions[name]}" if descriptions.get(name) else f"- {name}"

        nt_list = "\n".join(describe(n, nt_descs) for n in ctx.deps.node_types) or "- none"
        et_list = "\n".join(describe(n, et_descs) for n in ctx.deps.edge_types) or "- none"
        if qwen_mode:
            cap = qwen_entity_cap(ctx.deps.episode_text)
            parts.extend(
                [
                    f"Budget: at most {cap} entities and at most {cap * 2} relations.",
                    "Extract only ontology-aligned entities and relations; omit a relation that cannot fit.",
                ]
            )
        else:
            parts.extend(
                [
                    "Rules:",
                    "- Extract only ontology-aligned entities and relations.",
                    "- If a relation cannot fit the ontology, omit it.",
                    "- Include evidence text in relation properties when possible.",
                ]
            )
        parts.extend(
            [
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
    correlation_id: str | None = None
    known_node_names: list[str] | None = None  # Fallback dedup context (non-tool mode)
    precomputed_embeddings: dict[str, list[float]] = field(default_factory=dict)
    action_tracker: CurationActionTracker | LibrarianTrajectoryTracker | None = None


def _trajectory_tracker(ctx: RunContext[LibrarianAgentDeps]) -> LibrarianTrajectoryTracker:
    tracker = ctx.deps.action_tracker
    if not isinstance(tracker, LibrarianTrajectoryTracker):
        raise RuntimeError("qwen_bounded requires LibrarianTrajectoryTracker dependencies")
    return tracker


def _node_candidate(node: Any, type_name: str, score: float | None = None) -> EntityCandidate:
    content = node.content or ""
    return EntityCandidate(
        node_id=node.id,
        name=node.name,
        type_name=type_name,
        score=score,
        content_digest=sha256(content.encode("utf-8")).hexdigest()[:16],
        content_preview=content[:240] or None,
    )


async def resolve_semantic_candidates(
    repo: MemoryRepository,
    agent_id: str,
    target_schema: str | None,
    name: str,
    expected_type: str,
    embedding: list[float] | None,
    *,
    type_names: dict[int, str],
) -> tuple[str, list[tuple[Any, float | None]]]:
    """Run only the embedding-backed step of entity resolution.

    Split out of ``resolve_entity_candidates`` so a caller that resolves many
    entities can spend one ``embed_batch`` on the names that actually reach
    this step instead of one ``embed`` per entity.
    """
    semantic_all = await repo.search_nodes(
        agent_id,
        name,
        limit=3,
        query_embedding=embedding,
        target_schema=target_schema,
        expected_type=expected_type,
    )
    semantic = [
        (node, float(score))
        for node, score in semantic_all
        if score > 0.5 and type_names.get(node.type_id, "").casefold() == expected_type.casefold()
    ]
    semantic.sort(key=lambda item: (-item[1], item[0].id))
    if semantic:
        if len(semantic) == 1 or semantic[0][1] - semantic[1][1] >= 0.10:
            return "semantic", semantic[:3]  # ty: ignore[invalid-return-type]
        return "ambiguous", semantic[:3]  # ty: ignore[invalid-return-type]
    return "none", []


async def resolve_entity_candidates(
    repo: MemoryRepository,
    embeddings: EmbeddingService | None,
    agent_id: str,
    target_schema: str | None,
    name: str,
    expected_type: str,
    *,
    type_names: dict[int, str] | None = None,
    semantic: bool = True,
) -> tuple[str, list[tuple[Any, float | None]]]:
    """Resolve one entity name to typed graph candidates, host-side.

    Tries exact name, then aliases, then trigram similarity, then (when
    ``semantic`` is set and an embedding service is available) vector search.
    Returns the match kind (``exact``/``alias``/``fuzzy``/``semantic``/
    ``ambiguous``/``ambiguous_homonym``/``none``) and up to three candidates
    with their score, if the step that produced them has one.

    ``type_names`` lets a caller reuse one node-type snapshot across entities.
    ``semantic=False`` stops before the embedding step, so a batching caller
    can collect the unmatched names and finish with
    ``resolve_semantic_candidates``.
    """
    types: dict[int, str] = type_names or {
        item.id: item.name for item in await repo.get_node_types(agent_id, target_schema=target_schema)
    }

    def filtered(nodes: list[Any]) -> list[tuple[Any, float | None]]:
        return [(node, None) for node in nodes if types.get(node.type_id, "").casefold() == expected_type.casefold()]

    by_name = await repo.find_nodes_by_name(agent_id, name, target_schema=target_schema)
    exact_all = [node for node in by_name if not node.forgotten]
    exact = filtered(exact_all)
    if exact_all:
        if len(exact) == 1:
            return "exact", exact
        return ("ambiguous" if exact else "ambiguous_homonym"), exact

    alias_all = [
        node for node in await repo.resolve_alias(agent_id, name, target_schema=target_schema) if not node.forgotten
    ]
    alias = filtered(alias_all)
    if alias_all:
        if len(alias) == 1:
            return "alias", alias
        return ("ambiguous" if alias else "ambiguous_homonym"), alias

    fuzzy_all = await repo.find_nodes_fuzzy(
        agent_id,
        name,
        threshold=0.3,
        limit=3,
        target_schema=target_schema,
        expected_type=expected_type,
    )
    fuzzy = [
        (node, float(score))
        for node, score in fuzzy_all
        if types.get(node.type_id, "").casefold() == expected_type.casefold()
    ]
    fuzzy.sort(key=lambda item: (-item[1], item[0].id))
    if fuzzy:
        if len(fuzzy) == 1 or fuzzy[0][1] - fuzzy[1][1] >= 0.10:
            return "fuzzy", fuzzy[:3]  # ty: ignore[invalid-return-type]
        return "ambiguous", fuzzy[:3]  # ty: ignore[invalid-return-type]

    if semantic and embeddings:
        return await resolve_semantic_candidates(
            repo,
            agent_id,
            target_schema,
            name,
            expected_type,
            await embeddings.embed(name),
            type_names=types,
        )
    return "none", []


def _register_bounded_librarian_tools(agent: Agent, cfg: AgentInferenceConfig) -> None:
    """Install the five non-overlapping Qwen batch tools."""

    async def typed_resolution(
        ctx: RunContext[LibrarianAgentDeps], name: str, expected_type: str
    ) -> tuple[str, list[tuple[Any, float | None]]]:
        return await resolve_entity_candidates(
            ctx.deps.repo,
            ctx.deps.embeddings,
            ctx.deps.agent_id,
            ctx.deps.target_schema,
            name,
            expected_type,
        )

    @agent.tool
    async def resolve_entities(ctx: RunContext[LibrarianAgentDeps], entity_indices: list[int]) -> EntityResolutionBatch:
        """Resolve up to 16 entity indices exactly once; the host sorts and deduplicates them."""
        tracker = _trajectory_tracker(ctx)
        entity_indices = tracker.normalize_indices(entity_indices, len(tracker.entities), 16)
        duplicates = tracker.begin_call("resolve_entities", entity_indices, read=True)
        items: list[EntityResolution] = []
        for index in entity_indices:
            if index in duplicates:
                items.append(
                    EntityResolution(
                        status="noop",
                        reason="duplicate_call",
                        item_kind="entity",
                        item_index=index,
                        match="none",
                        candidates=[],
                        detail_required=False,
                        allowed_decisions=[],
                    )
                )
                continue
            tracker.consume_entity_read(index)
            entity = tracker.entities[index]
            match, matches = await typed_resolution(ctx, entity.name, entity.type_name)
            candidates = [_node_candidate(node, entity.type_name, score) for node, score in matches]
            tracker.entity_candidates[index] = {node.id: node for node, _score in matches}
            tracker.resolved_entities.add(index)
            tracker.entity_resolution_reason[index] = match
            if len(matches) == 1 and match not in {"ambiguous", "ambiguous_homonym"}:
                tracker.selected_nodes[index] = matches[0][0].id
            temporal: list[TemporalPredecessorCandidate] = []
            if entity.supersedes:
                predecessor_match, predecessors = await typed_resolution(ctx, entity.supersedes, entity.type_name)
                if predecessor_match in {"exact", "alias"} and len(predecessors) == 1:
                    predecessor = predecessors[0][0]
                    tracker.temporal_predecessors[index] = predecessor.id
                    temporal.append(TemporalPredecessorCandidate(node_id=predecessor.id, name=predecessor.name))
            reason = (
                "no_match"
                if match == "none"
                else (
                    "ambiguous_homonym"
                    if match == "ambiguous_homonym"
                    else "ambiguous" if match == "ambiguous" else "resolved"
                )
            )
            items.append(
                EntityResolution(
                    status="ok",
                    reason=reason,
                    item_kind="entity",
                    item_index=index,
                    match=(
                        "ambiguous" if match in {"ambiguous", "ambiguous_homonym"} else match
                    ),  # ty: ignore[invalid-argument-type]
                    candidates=candidates,
                    detail_required=len(matches) == 1,
                    allowed_decisions=_entity_allowed_decisions(tracker, index, after_detail=False),
                    temporal_predecessor_candidates=temporal,
                )
            )
        if len(duplicates) < len(entity_indices):
            tracker.record_progress()
        return EntityResolutionBatch(items=items, budget_warning=bool(tracker.soft_reasons))

    @agent.tool
    async def read_entity_details(
        ctx: RunContext[LibrarianAgentDeps], requests: list[EntityDetailRequest]
    ) -> EntityDetailBatch:
        """Read details for up to eight entities; the host uses each resolver-selected node id."""
        tracker = _trajectory_tracker(ctx)
        indices = tracker.normalize_indices([item.entity_index for item in requests], len(tracker.entities), 8)
        request_by_index = {request.entity_index: request for request in reversed(requests)}
        requests = [request_by_index[index] for index in indices]
        if any(index not in tracker.resolved_entities for index in indices):
            raise ValueError("entity details are out of phase")
        duplicates = tracker.begin_call("read_entity_details", indices, read=True)
        items: list[EntityDetail] = []
        for request in requests:
            index = request.entity_index
            node_id = tracker.selected_nodes.get(index)
            if node_id is None:
                reason = tracker.entity_resolution_reason.get(index)
                items.append(
                    EntityDetail(
                        status="unresolved",
                        reason="ambiguous" if reason in {"ambiguous", "ambiguous_homonym"} else "not_found",
                        item_kind="entity",
                        item_index=index,
                        node_id=None,
                        content="",
                        truncated=False,
                        importance=0.0,
                        properties={},
                        properties_truncated=False,
                        allowed_decisions=_entity_allowed_decisions(tracker, index, after_detail=True),
                    )
                )
                continue
            if index in duplicates:
                items.append(
                    EntityDetail(
                        status="noop",
                        reason="duplicate_call",
                        item_kind="entity",
                        item_index=index,
                        node_id=node_id,
                        content="",
                        truncated=False,
                        importance=0.0,
                        properties={},
                        properties_truncated=False,
                        allowed_decisions=[],
                    )
                )
                continue
            if node_id not in tracker.entity_candidates.get(index, {}):
                raise ValueError("resolver-selected detail candidate is unavailable")
            tracker.consume_entity_read(index)
            node = tracker.entity_candidates[index][node_id]
            content = node.content or ""
            truncated = len(content) > 4000
            scalar_props: dict[str, str | int | float | bool | None] = {}
            omitted = False
            for key, value in sorted((node.properties or {}).items(), key=lambda pair: str(pair[0])):
                if key == "_source_episode" or isinstance(value, (dict, list, tuple, set)) or len(scalar_props) >= 16:
                    omitted = True
                    continue
                safe_key = str(key)[:64]
                safe_value = value[:256] if isinstance(value, str) else value
                omitted = omitted or safe_key != str(key) or safe_value != value
                scalar_props[safe_key] = safe_value
            tracker.detailed_entities.add(index)
            if truncated:
                tracker.truncated_entities.add(index)
            items.append(
                EntityDetail(
                    status="ok",
                    reason="resolved",
                    item_kind="entity",
                    item_index=index,
                    node_id=node_id,
                    content=content[:4000],
                    truncated=truncated,
                    importance=node.importance,
                    properties=scalar_props,
                    properties_truncated=omitted,
                    allowed_decisions=_entity_allowed_decisions(tracker, index, after_detail=True),
                )
            )
        if len(duplicates) < len(requests):
            tracker.record_progress()
        return EntityDetailBatch(items=items, budget_warning=bool(tracker.soft_reasons))

    @agent.tool
    async def apply_entity_decisions(
        ctx: RunContext[LibrarianAgentDeps], decisions: list[EntityDecision]
    ) -> DecisionOutcomeBatch:
        """Apply up to eight terminal entity decisions in ascending order."""
        from neocortex.normalization import canonicalize_name

        tracker = _trajectory_tracker(ctx)
        indices = tracker.normalize_indices([item.entity_index for item in decisions], len(tracker.entities), 8)
        decision_by_index = {decision.entity_index: decision for decision in reversed(decisions)}
        decisions = [decision_by_index[index] for index in indices]
        duplicates = tracker.begin_call("apply_entity_decisions", indices, read=False)
        outcomes: list[ToolOutcome] = []

        def reject(index: int, reason: ToolReason) -> None:
            tracker.record_rejection("apply_entity_decisions", index)
            outcomes.append(ToolOutcome(status="rejected", reason=reason, item_kind="entity", item_index=index))

        for decision in decisions:
            index = decision.entity_index
            if index in duplicates:
                outcomes.append(
                    ToolOutcome(status="noop", reason="duplicate_call", item_kind="entity", item_index=index)
                )
                continue
            entity = tracker.entities[index]
            selected = tracker.selected_nodes.get(index)
            if index not in tracker.resolved_entities:
                reject(index, "phase_violation")
                continue
            allowed = _entity_allowed_decisions(tracker, index, after_detail=True)
            if decision.decision not in allowed:
                if decision.decision == "create" and selected is not None:
                    reject(index, "selected_candidate_exists")
                elif decision.decision in {"update", "unchanged", "archive_then_create"} and selected is None:
                    reject(index, "selected_candidate_missing")
                elif selected is not None and index not in tracker.detailed_entities:
                    reject(index, "detail_required")
                elif decision.decision == "update" and index in tracker.truncated_entities:
                    reject(index, "truncated_detail")
                elif decision.decision == "unresolved":
                    reject(index, "unresolved_not_allowed")
                elif decision.decision == "archive_then_create":
                    reject(index, "temporal_evidence_missing")
                else:
                    reject(index, "decision_incompatible")
                continue
            if decision.decision in {"create", "update", "archive_then_create"} and not decision.content:
                reject(index, "content_missing")
                continue

            if decision.decision in {"unchanged", "unresolved"}:
                if decision.decision == "unchanged" and selected is not None:
                    tracker.bound_node_ids[index] = selected
                tracker.entity_states[index] = decision.decision
                outcomes.append(
                    ToolOutcome(
                        status="noop" if decision.decision == "unchanged" else "unresolved",
                        reason="unchanged" if decision.decision == "unchanged" else "ambiguous",
                        item_kind="entity",
                        item_index=index,
                    )
                )
                tracker.record_progress()
                continue

            node_type_id: int | None = None
            if decision.decision != "update":
                node_type = await ctx.deps.repo.get_or_create_node_type(
                    ctx.deps.agent_id, entity.type_name, target_schema=ctx.deps.target_schema
                )
                if node_type is None:
                    reject(index, "invalid_type")
                    continue
                node_type_id = node_type.id

            tracker.mutations_attempted += 1
            if decision.decision == "archive_then_create":
                assert selected is not None
                archived = await ctx.deps.repo.mark_forgotten(
                    ctx.deps.agent_id, [selected], target_schema=ctx.deps.target_schema
                )
                tracker.record_archive(archived > 0)

            canonical_name, aliases = canonicalize_name(entity.name)
            canonical_name = canonical_name or entity.name
            if decision.decision == "update":
                assert selected is not None
                candidate = tracker.entity_candidates[index][selected]
                canonical_name = candidate.name
                node_type_id = candidate.type_id
            assert node_type_id is not None
            props = dict(decision.properties or {})
            # Extractor facts are accepted source material. Model-authored curation
            # metadata may add keys, but it cannot silently remove or rewrite them.
            props.update(entity.properties)
            if ctx.deps.episode_id is not None:
                props["_source_episode"] = ctx.deps.episode_id
            assert decision.content is not None
            embedding = await ctx.deps.embeddings.embed(decision.content) if ctx.deps.embeddings else None
            node = await ctx.deps.repo.upsert_node(
                agent_id=ctx.deps.agent_id,
                name=canonical_name,
                type_id=node_type_id,
                content=decision.content,
                properties=props,
                embedding=embedding,
                target_schema=ctx.deps.target_schema,
                importance=decision.importance if decision.importance is not None else entity.importance,
            )
            if decision.decision == "update" and node.id != selected:
                raise LibrarianIdentityMismatch("repository returned a different node id for a bound update")
            for alias in aliases:
                await ctx.deps.repo.register_alias(
                    ctx.deps.agent_id, node.id, alias, source="librarian", target_schema=ctx.deps.target_schema
                )
            state = "updated" if decision.decision == "update" else "created"
            tracker.entity_states[index] = state
            tracker.bound_node_ids[index] = node.id
            tracker.successful_node_ids.add(node.id)
            tracker.record_node(state)
            tracker.mutations_succeeded += 1
            tracker.record_progress()
            outcomes.append(ToolOutcome(status="ok", reason=state, item_kind="entity", item_index=index))
        return DecisionOutcomeBatch(items=outcomes, budget_warning=bool(tracker.soft_reasons))

    def endpoint_id(tracker: LibrarianTrajectoryTracker, relation: ExtractedRelation, source: bool) -> int | None:
        wanted = relation.source_name if source else relation.target_name
        for index, entity in enumerate(tracker.entities):
            if entity.name.casefold() == wanted.casefold():
                return tracker.bound_node_ids.get(index)
            if (
                not source
                and entity.name.casefold() == relation.source_name.casefold()
                and entity.supersedes
                and entity.supersedes.casefold() == wanted.casefold()
            ):
                return tracker.temporal_predecessors.get(index)
        return None

    def relation_allowed_decisions(
        tracker: LibrarianTrajectoryTracker, index: int, source_id: int | None, target_id: int | None
    ) -> list[RelationDecisionKind]:
        if source_id is None or target_id is None:
            return ["unresolved"]
        if tracker.checked_edges.get(index):
            return ["existing_equivalent", "replace"]
        return ["create"]

    @agent.tool
    async def check_relations(ctx: RunContext[LibrarianAgentDeps], relation_indices: list[int]) -> RelationCheckBatch:
        """Check up to 16 relations; the host sorts and deduplicates their indices."""
        tracker = _trajectory_tracker(ctx)
        relation_indices = tracker.normalize_indices(relation_indices, len(tracker.relations), 16)
        if not tracker.all_entities_terminal:
            raise ValueError("relation checks are out of phase")
        duplicates = tracker.begin_call("check_relations", relation_indices, read=True)
        edge_types = await ctx.deps.repo.get_edge_types(ctx.deps.agent_id, target_schema=ctx.deps.target_schema)
        edge_type_names = {item.id: item.name for item in edge_types}
        cache: dict[int, list[dict]] = {}
        items: list[RelationCheck] = []
        for index in relation_indices:
            if index in duplicates:
                items.append(
                    RelationCheck(
                        status="noop",
                        reason="duplicate_call",
                        item_kind="relation",
                        item_index=index,
                        source_node_id=None,
                        target_node_id=None,
                        edges=[],
                        truncated=False,
                        allowed_decisions=[],
                    )
                )
                continue
            tracker.consume_relation_read(index)
            relation = tracker.relations[index]
            source_id, target_id = endpoint_id(tracker, relation, True), endpoint_id(tracker, relation, False)
            if source_id is None or target_id is None:
                tracker.checked_edges[index] = set()
                items.append(
                    RelationCheck(
                        status="unresolved",
                        reason="endpoint_missing",
                        item_kind="relation",
                        item_index=index,
                        source_node_id=source_id,
                        target_node_id=target_id,
                        edges=[],
                        truncated=False,
                        allowed_decisions=["unresolved"],
                    )
                )
                continue
            if source_id not in cache:
                cache[source_id] = await ctx.deps.repo.get_node_neighborhood(
                    ctx.deps.agent_id, source_id, depth=1, target_schema=ctx.deps.target_schema
                )
            edges = []
            for entry in cache[source_id]:
                for edge in entry["edges"]:
                    if {edge.source_id, edge.target_id} == {source_id, target_id}:
                        edges.append(
                            {
                                "edge_id": edge.id,
                                "type": edge_type_names.get(edge.type_id, "Unknown"),
                                "weight": edge.weight,
                            }
                        )
            edges.sort(key=lambda item: int(item["edge_id"]))
            tracker.checked_edges[index] = {int(item["edge_id"]) for item in edges}
            items.append(
                RelationCheck(
                    status="ok",
                    reason="resolved" if edges else "no_match",
                    item_kind="relation",
                    item_index=index,
                    source_node_id=source_id,
                    target_node_id=target_id,
                    edges=edges[:5],
                    truncated=len(edges) > 5,
                    allowed_decisions=relation_allowed_decisions(tracker, index, source_id, target_id),
                )
            )
        if len(duplicates) < len(relation_indices):
            tracker.record_progress()
        return RelationCheckBatch(items=items, budget_warning=bool(tracker.soft_reasons))

    @agent.tool
    async def apply_relation_decisions(
        ctx: RunContext[LibrarianAgentDeps], decisions: list[RelationDecision]
    ) -> DecisionOutcomeBatch:
        """Apply up to eight checked relation decisions in ascending order."""
        tracker = _trajectory_tracker(ctx)
        indices = tracker.normalize_indices([item.relation_index for item in decisions], len(tracker.relations), 8)
        decision_by_index = {decision.relation_index: decision for decision in reversed(decisions)}
        decisions = [decision_by_index[index] for index in indices]
        duplicates = tracker.begin_call("apply_relation_decisions", indices, read=False)
        outcomes: list[ToolOutcome] = []

        def reject(index: int, reason: ToolReason) -> None:
            tracker.record_rejection("apply_relation_decisions", index)
            outcomes.append(ToolOutcome(status="rejected", reason=reason, item_kind="relation", item_index=index))

        for decision in decisions:
            index = decision.relation_index
            if index in duplicates:
                outcomes.append(
                    ToolOutcome(status="noop", reason="duplicate_call", item_kind="relation", item_index=index)
                )
                continue
            if index not in tracker.checked_edges:
                reject(index, "edge_not_checked")
                continue
            relation = tracker.relations[index]
            source_id, target_id = endpoint_id(tracker, relation, True), endpoint_id(tracker, relation, False)
            checked = tracker.checked_edges[index]
            allowed = relation_allowed_decisions(tracker, index, source_id, target_id)
            if decision.decision not in allowed:
                if decision.decision == "unresolved":
                    reject(index, "unresolved_not_allowed")
                elif decision.decision == "replace":
                    reject(index, "replacement_edge_not_checked")
                elif decision.decision == "existing_equivalent":
                    reject(index, "edge_not_checked")
                else:
                    reject(index, "decision_incompatible")
                continue
            if decision.decision == "existing_equivalent" and not checked:
                reject(index, "edge_not_checked")
                continue
            if decision.decision == "replace" and decision.replace_edge_id not in checked:
                reject(index, "replacement_edge_not_checked")
                continue
            if decision.decision == "unresolved" and source_id is not None and target_id is not None:
                reject(index, "unresolved_not_allowed")
                continue
            if decision.decision in {"existing_equivalent", "unresolved"}:
                state = "unchanged" if decision.decision == "existing_equivalent" else "unresolved"
                tracker.relation_states[index] = state
                tracker.record_progress()
                outcomes.append(
                    ToolOutcome(
                        status="noop" if state == "unchanged" else "unresolved",
                        reason="existing_equivalent" if state == "unchanged" else "endpoint_missing",
                        item_kind="relation",
                        item_index=index,
                    )
                )
                continue
            if source_id is None or target_id is None:
                reject(index, "endpoint_missing")
                continue
            edge_type = await ctx.deps.repo.get_or_create_edge_type(
                ctx.deps.agent_id, relation.relation_type, target_schema=ctx.deps.target_schema
            )
            if edge_type is None:
                reject(index, "invalid_type")
                continue
            tracker.mutations_attempted += 1
            if decision.decision == "replace":
                assert decision.replace_edge_id is not None
                removed = await ctx.deps.repo.delete_edge(
                    ctx.deps.agent_id, decision.replace_edge_id, target_schema=ctx.deps.target_schema
                )
                tracker.record_edge_removal(removed)
                if removed:
                    tracker.removed_edge_ids.add(decision.replace_edge_id)
            props = dict(relation.properties)
            if ctx.deps.episode_id is not None:
                props["_source_episode"] = ctx.deps.episode_id
            edge = await ctx.deps.repo.upsert_edge(
                ctx.deps.agent_id,
                source_id,
                target_id,
                edge_type.id,
                weight=relation.weight,
                properties=props,
                target_schema=ctx.deps.target_schema,
            )
            if edge is None:
                raise RuntimeError("repository failed to upsert a relation")
            tracker.relation_states[index] = "created"
            tracker.successful_edge_ids.add(edge.id)
            tracker.successful_edge_signatures[edge.id] = (edge.source_id, edge.target_id, edge.type_id)
            tracker.record_edge_upsert()
            tracker.mutations_succeeded += 1
            tracker.record_progress()
            outcomes.append(ToolOutcome(status="ok", reason="created", item_kind="relation", item_index=index))
        return DecisionOutcomeBatch(items=outcomes, budget_warning=bool(tracker.soft_reasons))


def build_librarian_agent(
    config: AgentInferenceConfig | None = None,
    use_tools: bool = True,
    retries: int = DEFAULT_LIBRARIAN_RETRIES,
    *,
    profile: LibrarianProfile | None = None,
) -> Agent[LibrarianAgentDeps, Any]:
    """Build the librarian agent.

    When use_tools=True (default), the agent gets mutation tools and returns
    CurationSummary. When use_tools=False, it returns LibrarianPayload for
    backward-compatible _persist_payload flow.
    """
    cfg = config or AgentInferenceConfig()
    model = _build_model(cfg)
    selected_profile: LibrarianProfile = profile or ("qwen_oneshot" if is_qwen_model(cfg.model_name) else "hosted")
    if not use_tools:
        selected_profile = "hosted"

    output_type: Any
    if use_tools and selected_profile == "qwen_oneshot":
        output_type = OneshotDecisions
    elif use_tools and selected_profile == "qwen_bounded":
        output_type = LibrarianTerminal
    else:
        output_type = CurationSummary if use_tools else LibrarianPayload

    system_prompt: tuple[str, ...]
    if use_tools and selected_profile == "qwen_oneshot":
        # Every output token costs wall time on the local endpoint, so ask for
        # prose only where a merge actually needs it.
        system_prompt = (
            "Decide how new entities join a knowledge graph. Answer once; you have no tools.",
            "Each input line is: index | name | type | new description, then its graph candidates indented.",
            "Return exactly one decision per index:",
            "merge - a candidate is the same real-world thing: give its node_id and content.",
            "unchanged - a candidate already states every new fact: give its node_id, omit content.",
            "create - no candidate is the same thing: omit node_id and content.",
            "content is ONE combined description under 600 characters that keeps every existing fact and "
            "adds or corrects it with the new one; newer numbers, dates, and versions win.",
            "node_id must be a candidate id listed under that index.",
            'Example: {"decisions":[{"index":0,"decision":"merge","node_id":12,"content":"..."},'
            '{"index":1,"decision":"create"}]}',
        )
    elif use_tools and selected_profile in {"qwen_finite", "qwen_bounded"}:
        finish_rule = (
            'Return exactly {"status":"done"} only after every indexed item has a terminal decision.'
            if selected_profile == "qwen_bounded"
            else "Stop calling tools after all items are handled and return the CurationSummary."
        )
        workflow_rule = (
            "Process entity micro-batches of at most 8 indices end to end: resolve the next batch, read only "
            "details marked detail_required, then immediately decide every index using its allowed_decisions. "
            "Do not resolve the next entity batch until the current batch is terminal. After all entities are "
            "terminal, process relation micro-batches of at most 8 by checking and immediately deciding each batch."
            if selected_profile == "qwen_bounded"
            else "Process stable indices in ascending order across the three finite phases."
        )
        system_prompt = (
            f"You curate extracted knowledge in three finite phases. {workflow_rule}",
            "Entity phase: resolve each entity once; update only for added or corrected information, "
            "otherwise keep it unchanged; create missing entities. A superseding entity stays distinct "
            "and needs its temporal relation. Entity decisions supply only the entity index; the host "
            "derives any resolver-selected node identity.",
            "Relation phase starts only after every entity decision. Keep equivalent edges, replace "
            "only provably stale edges, and create missing edges. Use unresolved only when an endpoint is "
            "missing or ambiguous. Neighborhood exploration is unnecessary.",
            "Comprehensive merges, quantitative changes, contradictions, temporal edges, valid types, "
            "shared contributions, and deduplication remain mandatory.",
            "Only explicit supersedes, temporal_signal, or source correction language justifies temporal work.",
            (
                "The host sorts and deduplicates index batches. Batch resolver results are final for their indices. "
                "For detail reads, supply only entity_index; the host derives the resolver-selected node id. "
                "The allowed_decisions field is code-owned; choose only a listed category. "
                "A rejected decision stays pending: correct only those rejected indices in a later call. "
                "Never repeat an accepted index across calls or call a legacy read tool."
                if selected_profile == "qwen_bounded"
                else "Call find_similar_nodes and get_edges_between at most once for each input item."
            ),
            finish_rule,
        )
    elif use_tools:
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
            "You are a knowledge graph librarian. Your job is to normalize and deduplicate extracted knowledge.",
            "Normalize entity names to canonical forms.",
            "Preserve importance scores from extractor (max semantics if merging).",
            "ALWAYS provide a description for every entity.",
        )

    agent = Agent(  # ty: ignore[no-matching-overload]
        model,
        output_type=output_type,
        deps_type=LibrarianAgentDeps,
        retries=retries,
        capabilities=[build_audit_hooks("librarian", cfg)],
        model_settings=_qwen_output_cap_settings(cfg, "librarian"),
        system_prompt=system_prompt,
    )

    if use_tools and selected_profile == "qwen_oneshot":
        # Tool-free by design: the host resolves candidates and applies decisions.
        return agent  # ty: ignore[invalid-return-type]

    if use_tools and selected_profile == "qwen_bounded":
        _register_bounded_librarian_tools(agent, cfg)

        @agent.instructions  # ty: ignore[no-matching-overload]
        async def inject_bounded_context(ctx: RunContext[LibrarianAgentDeps]) -> str:
            tracker = _trajectory_tracker(ctx)
            entity_lines = [
                f"{index}: type={entity.type_name}; description={entity.description or ''}; "
                f"properties={entity.properties}; importance={entity.importance}; "
                f"supersedes={entity.supersedes or ''}; temporal_signal={entity.temporal_signal or ''}"
                for index, entity in enumerate(ctx.deps.extracted_entities)
            ]
            relation_lines = [
                f"{index}: source={relation.source_name}; target={relation.target_name}; "
                f"type={relation.relation_type}; weight={relation.weight}; properties={relation.properties}"
                for index, relation in enumerate(tracker.relations)
            ]
            return "\n".join(
                [
                    "ENTITIES",
                    *entity_lines,
                    "RELATIONS",
                    *relation_lines,
                    f"HOST STATUS entities_terminal=0/{len(entity_lines)} relations_terminal=0/{len(relation_lines)}",
                ]
            )

        return agent  # ty: ignore[invalid-return-type]

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
            target_schema=ctx.deps.target_schema,
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
                target_schema=ctx.deps.target_schema,
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
            target_schema=ctx.deps.target_schema,
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
            target_schema=ctx.deps.target_schema,
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
                **_audit_dimensions(ctx, "librarian", cfg),
                tool="create_or_update_node",
                node_id=node.id,
                action=action,
            )
            if ctx.deps.action_tracker is not None:
                ctx.deps.action_tracker.record_node(action)
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
                **_audit_dimensions(ctx, "librarian", cfg),
                tool="create_or_update_edge",
                edge_id=edge.id,
                source_id=edge.source_id,
                target_id=edge.target_id,
                edge_type_id=edge.type_id,
                action="upserted",
            )
            if ctx.deps.action_tracker is not None:
                ctx.deps.action_tracker.record_edge_upsert()
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
                **_audit_dimensions(ctx, "librarian", cfg),
                tool="archive_node",
                node_id=node_id,
                archived=count > 0,
                action="archived",
            )
            if ctx.deps.action_tracker is not None:
                ctx.deps.action_tracker.record_archive(count > 0)
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
                **_audit_dimensions(ctx, "librarian", cfg),
                tool="remove_edge",
                edge_id=edge_id,
                removed=deleted,
                action="removed",
            )
            if ctx.deps.action_tracker is not None:
                ctx.deps.action_tracker.record_edge_removal(deleted)
            return {
                "removed": deleted,
                "edge_id": edge_id,
                "reason": reason,
            }

    # ── Context injection ──

    @agent.instructions  # ty: ignore[no-matching-overload]
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
