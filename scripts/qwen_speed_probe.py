#!/usr/bin/env python3
"""Per-stage speed probe for the extraction pipeline against a local model.

Runs the real ``run_extraction`` over compact-corpus episodes on an
``InMemoryRepository`` (no PostgreSQL, no services), aggregates the structured
``action_log`` events the pipeline already emits, and writes a privacy-safe JSON
summary.  Extraction results are cached under ``--cache-dir`` so later work can
iterate on the librarian stage alone (``--stage librarian``).

The summary holds stage names, durations, counts, privacy-safe classifier domain
keys, and normalized ontology edge type names.  Known classifier domains are
allowlisted code-owned slugs; proposed domains are represented only by hashes of
canonical names.  Ontology names are structural metadata: model-proposed names
reach ``edge_types_after`` only after ``InMemoryRepository.get_or_create_edge_type``
accepts the result of ``normalize_edge_type``.  Episode text, prompts, entity
names, and all other model output never reach the summary.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pydantic_ai
from loguru import logger
from openai import APITimeoutError
from pydantic_ai.settings import ThinkingLevel

from neocortex.db.mock import InMemoryRepository
from neocortex.domains.models import SEED_DOMAINS, ClassificationResult
from neocortex.extraction.agents import AgentInferenceConfig
from neocortex.extraction.pipeline import run_extraction
from neocortex.extraction.schemas import ExtractionResult
from neocortex.mcp_settings import MCPSettings
from neocortex.model_factory import LocalEndpoint
from neocortex.normalization import normalize_edge_type, normalize_node_type
from neocortex.schemas.memory import TypeInfo

try:  # Direct ``python scripts/qwen_speed_probe.py`` invocation.
    from corpus_loader import corpus_path, load_corpus  # ty: ignore[unresolved-import]
    from fact_retention import (  # ty: ignore[unresolved-import]
        Fixture,
        GraphView,
        count_temporal_edges,
        load_fixture,
        score_episode,
        score_supersession,
        snapshot_graph,
    )
except ModuleNotFoundError:  # Imported as ``scripts.qwen_speed_probe``.
    from scripts.corpus_loader import corpus_path, load_corpus  # ty: ignore[unresolved-import]
    from scripts.fact_retention import (  # ty: ignore[unresolved-import]
        Fixture,
        GraphView,
        count_temporal_edges,
        load_fixture,
        score_episode,
        score_supersession,
        snapshot_graph,
    )

ROOT = Path(__file__).resolve().parents[1]
AGENT_ID = "qwen_speed_probe"
DEFAULT_MODEL = "local:qwen3.8-flash-next"
DEFAULT_BASE_URL = "http://127.0.0.1:24000/v1"
DEFAULT_API_KEY_ENV = "LITELLM_API_KEY"
CACHE_DIR = ROOT / ".tmp/qwen-swift/cache"
VALIDATION_DIR = ROOT / ".tmp/qwen-swift/validation"
EPISODE_KEYS: dict[str, int] = {f"E{number:02d}": number for number in (2, 4, 5, 10, 18, 20, 26, 27)}
THINKING: dict[str, ThinkingLevel] = {
    "off": False,
    "minimal": "minimal",
    "low": "low",
    "medium": "medium",
    "high": "high",
}
PROFILES = ("hosted", "qwen_legacy", "qwen_finite", "qwen_bounded", "qwen_oneshot")
AGENTS = ("ontology", "extractor", "librarian")
# Agents whose thinking level the CLI can set independently.  The classifier is
# not a pipeline stage but runs under ``--classify`` from the same harness.
TUNABLE_AGENTS = (*AGENTS, "classifier")
CORPUS_CHOICES = ("episodes", "compact", "supersession", "both")
TRIPLET_IMPORTANCE = 0.5
# ``stage`` on pipeline events carries the ``_agent`` suffix; ``agent`` on agent
# lifecycle and usage events does not.  Both map to one probe stage name.
STAGE_NAMES = {name: name for name in AGENTS} | {f"{name}_agent": name for name in AGENTS}
STAGE_NAMES["domain_classifier"] = "classifier"
STAGE_ORDER = ("classifier", *AGENTS)
COUNT_FIELDS = ("requests", "tool_calls", "input_tokens", "output_tokens", "reasoning_tokens")
# Bounded-librarian diagnostics: counts and code-owned reason codes only.
TRAJECTORY_FIELDS = ("requests", "provider_tool_calls", "reads", "mutations_attempted", "mutations_succeeded",
                     "duplicates", "validation_rejections", "max_read_streak", "hard_reason")  # fmt: skip
_REASONING_MARKER = re.compile(r"</?think>", re.IGNORECASE)
_TIMEOUT_ERROR_TYPES = frozenset({"APITimeoutError", "CancelledError", "TimeoutError"})
_KNOWN_DOMAIN_SLUGS = frozenset(domain.slug for domain in SEED_DOMAINS)
_ONTOLOGY_PROPOSAL_FIELDS = (
    "accepted_node_proposals",
    "accepted_edge_proposals",
    "rejected_node_proposals",
    "rejected_edge_proposals",
    "proposal_rejection_reasons",
)
_ONTOLOGY_REJECTION_REASONS = frozenset({"normalization_rejected", "already_exists"})


class ActionLogCollector:
    """Loguru sink that keeps ``action_log=True`` records in memory."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def __call__(self, message: Any) -> None:
        record = message.record
        self.records.append({"event": record["message"], "fields": dict(record["extra"])})

    def reset(self) -> None:
        self.records.clear()


def install_collector() -> ActionLogCollector:
    """Replace loguru sinks with a quiet console sink plus the collector."""
    collector = ActionLogCollector()
    logger.remove()
    logger.add(
        sys.stderr,
        level=os.environ.get("NEOCORTEX_LOG_LEVEL", "WARNING").upper(),
        format="{time:HH:mm:ss} | {level: <7} | {message}",
    )
    logger.add(collector, level="DEBUG", filter=lambda record: bool(record["extra"].get("action_log")))
    return collector


def _blank_row(episode: str, stage: str, status: str) -> dict[str, Any]:
    result = {
        "episode": episode,
        "stage": stage,
        "seconds": None,
        **dict.fromkeys(COUNT_FIELDS, 0),
        "entities": None,
        "relations": None,
        "status": status,
    }
    if stage == "ontology":
        result.update(dict.fromkeys(_ONTOLOGY_PROPOSAL_FIELDS))
    elif stage == "classifier":
        result.update(
            {
                "matched_domains": None,
                "proposed_domains": None,
                "domain_keys": None,
                "valid_result": False,
            }
        )
    return result


def aggregate_stage_rows(episode: str, records: list[dict[str, Any]], *, outcome: str = "ok") -> list[dict[str, Any]]:
    """Fold collected action-log records into one row per pipeline stage.

    A stage that reported ``stage_timing`` completed; a stage that started and
    never reported one inherits ``outcome`` (``timeout`` or ``error:<Type>``).
    """
    rows: dict[str, dict[str, Any]] = {}

    def row(stage: str) -> dict[str, Any]:
        return rows.setdefault(stage, _blank_row(episode, stage, outcome))

    for record in records:
        fields = record["fields"]
        event = record["event"]
        if event == "ontology_proposal_rejected":
            # This privacy-safe validator event deliberately carries no stage or
            # source text.  ActionLogCollector is reset before each sequential
            # source-text run, which makes it attributable inside this probe.
            kind = fields.get("kind")
            if kind not in {"node", "edge"}:
                continue
            current = row("ontology")
            count_field = f"rejected_{kind}_proposals"
            current[count_field] = int(current[count_field] or 0) + 1
            reason = fields.get("reason_code")
            reason_key = str(reason) if reason in _ONTOLOGY_REJECTION_REASONS else "other"
            reasons = current["proposal_rejection_reasons"]
            if reasons is None:
                reasons = {}
                current["proposal_rejection_reasons"] = reasons
            bucket = f"{kind}:{reason_key}"
            reasons[bucket] = int(reasons.get(bucket) or 0) + 1
            continue
        stage = STAGE_NAMES.get(str(fields.get("stage") or fields.get("agent") or ""))
        if stage is None:
            continue
        if event == "agent_run_started":
            row(stage)
        elif event == "stage_timing":
            current = row(stage)
            current["seconds"] = float(fields.get("elapsed_s") or 0.0)
            current["status"] = "ok"
        elif event == "agent_usage":
            current = row(stage)
            for field in COUNT_FIELDS:
                current[field] += int(fields.get(field) or 0)
            if stage == "classifier":
                current["status"] = "ok"
        elif event == "extractor_cardinality":
            current = row("extractor")
            current["entities"] = int(fields.get("entity_count") or 0)
            current["relations"] = int(fields.get("relation_count") or 0)
        elif event == "ontology_agent_complete":
            current = row("ontology")
            current["accepted_node_proposals"] = (
                int(fields["proposed_node_types"]) if "proposed_node_types" in fields else None
            )
            current["accepted_edge_proposals"] = (
                int(fields["proposed_edge_types"]) if "proposed_edge_types" in fields else None
            )
            for kind in ("node", "edge"):
                count_field = f"rejected_{kind}_proposals"
                if current[count_field] is None:
                    current[count_field] = 0
            if current["proposal_rejection_reasons"] is None:
                current["proposal_rejection_reasons"] = {}
        elif event == "librarian_trajectory":
            row("librarian")["trajectory"] = {name: fields.get(name) for name in TRAJECTORY_FIELDS if name in fields}

    return [rows[stage] for stage in STAGE_ORDER if stage in rows]


def partial_stage_rows(episode: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only evidence observed before a wall-deadline cancellation.

    The normal aggregator's zero counters mean a completed audit emitted no
    usage.  During cancellation, absence of ``agent_usage`` is not such proof,
    so those counters remain null rather than becoming invented zeros.
    """
    rows = aggregate_stage_rows(episode, records, outcome="timeout")
    stages_with_usage = {
        STAGE_NAMES.get(str(record["fields"].get("stage") or record["fields"].get("agent") or ""))
        for record in records
        if record["event"] == "agent_usage"
    }
    for current in rows:
        if current["stage"] not in stages_with_usage:
            for field in COUNT_FIELDS:
                current[field] = None
    return rows


def cache_key(
    episode: str,
    model: str,
    thinking: ThinkingLevel,
    corpus_sha256: str,
    source_text: str,
    *,
    test_model: bool,
    fixture_revision: int | None = None,
    ontology_thinking: ThinkingLevel | None = None,
    extractor_thinking: ThinkingLevel | None = None,
) -> str:
    """Return the cache file stem for one episode under one inference setup.

    A cache entry holds an ``ExtractionResult`` plus the ontology snapshot it was
    produced against — artifacts the ontology and extractor agents produce and
    the librarian never influences.  Both of their levels therefore belong in the
    key: a librarian-only rerun must not silently reuse an extraction produced at
    another extractor level.

    The librarian and classifier levels are deliberately **out** of the key.  The
    thinking sweep's librarian pass reuses one extraction cached at a pinned
    extractor level across every librarian level; a single-valued
    ``--cache-thinking`` cannot express a per-agent key, so folding the librarian
    level in would miss the cache at every cell and re-run extraction each time.
    Excluding it still satisfies the requirement above, because the extractor
    level *is* in the key.

    ``source_text`` prevents a changed fixture triplet from reusing an earlier
    extraction.  ``fixture_revision`` additionally invalidates every triplet
    when the fixture contract changes.  Cache format version 2 intentionally
    makes pre-provenance cache files unreachable; there is no compatibility
    fallback.

    ``ontology_thinking`` and ``extractor_thinking`` default to ``thinking``.
    """
    ontology = thinking if ontology_thinking is None else ontology_thinking
    extractor = thinking if extractor_thinking is None else extractor_thinking
    source_sha256 = hashlib.sha256(source_text.encode()).hexdigest()
    preimage = json.dumps(
        {
            "version": 2,
            "model": model,
            "thinking": thinking,
            "ontology_thinking": ontology,
            "extractor_thinking": extractor,
            "corpus_sha256": corpus_sha256,
            "source_sha256": source_sha256,
            "fixture_revision": fixture_revision,
            "mode": "test" if test_model else "live",
        },
        sort_keys=True,
    )
    return f"{episode}-{hashlib.sha256(preimage.encode()).hexdigest()[:12]}"


def type_snapshot(types: list[TypeInfo]) -> list[dict[str, str]]:
    """Reduce repository type rows to the name/description pairs the cache needs."""
    return [{"name": info.name, "description": info.description or ""} for info in types]


def save_cached_extraction(
    cache_dir: Path,
    key: str,
    result: ExtractionResult,
    node_types: list[dict[str, str]],
    edge_types: list[dict[str, str]],
) -> Path:
    """Persist one extraction plus the ontology it was produced against."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{key}.json"
    payload = {
        "extraction": result.model_dump(mode="json"),
        "ontology": {"node_types": node_types, "edge_types": edge_types},
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_cached_extraction(cache_dir: Path, key: str) -> tuple[ExtractionResult, dict[str, list[dict[str, str]]]]:
    """Load a cached extraction and its ontology snapshot."""
    payload = json.loads((cache_dir / f"{key}.json").read_text(encoding="utf-8"))
    return ExtractionResult.model_validate(payload["extraction"]), payload["ontology"]


def resolve_local_endpoint(timeout_s: float) -> LocalEndpoint:
    """Build the local endpoint, defaulting base URL and key env for this probe.

    ``_env_file=None`` keeps the repository ``.env`` out of the probe: the model
    under test comes from the CLI, and a stale ``.env`` must not redirect it.
    """
    settings = MCPSettings(
        _env_file=None,  # ty: ignore[unknown-argument]
        local_model_base_url=os.environ.get("NEOCORTEX_LOCAL_MODEL_BASE_URL") or DEFAULT_BASE_URL,
        local_model_api_key_env=os.environ.get("NEOCORTEX_LOCAL_MODEL_API_KEY_ENV") or DEFAULT_API_KEY_ENV,
        local_model_timeout_s=timeout_s,
    )
    return LocalEndpoint.from_settings(settings)


@contextmanager
def _classifier_model_override(use_test_model: bool) -> Iterator[None]:
    """Replace only the classifier's provider factory during a test-model run."""
    if not use_test_model:
        yield
        return

    from unittest.mock import patch

    from pydantic_ai.models.test import TestModel

    from neocortex.domains import classifier as classifier_module

    # Keep AgentDomainClassifier configured with the requested Qwen identity so
    # it selects the Qwen prompt/settings branch. Only its final model factory
    # is replaced; no provider client can be constructed or called.
    with patch.object(classifier_module, "build_model", return_value=TestModel()):
        yield


def resolve_embeddings() -> tuple[Any, str]:
    """Construct the Gemini embedding service when a key is available."""
    if not os.environ.get("GOOGLE_API_KEY") and os.environ.get("GEMINI_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]
    if not os.environ.get("GOOGLE_API_KEY"):
        return None, "none"
    from neocortex.embedding_service import EmbeddingService

    return EmbeddingService(), "gemini"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Per-stage speed probe for the extraction pipeline.")
    parser.add_argument("--episodes", nargs="+", choices=tuple(EPISODE_KEYS), default=["E04", "E05"])
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--thinking", choices=tuple(THINKING), default="low")
    for agent in TUNABLE_AGENTS:
        parser.add_argument(
            f"--thinking-{agent}",
            choices=tuple(THINKING),
            default=None,
            help=f"thinking level for the {agent} agent; falls back to --thinking",
        )
    parser.add_argument(
        "--cache-thinking",
        choices=tuple(THINKING),
        default=None,
        help="read/write the extraction cache under this thinking level instead of --thinking, "
        "so a librarian-only run can reuse an extraction produced at another level",
    )
    parser.add_argument("--episode-timeout", type=float, default=900.0)
    parser.add_argument(
        "--per-call-timeout",
        type=float,
        default=300.0,
        help="bound on a single model call (reaches LocalEndpoint.timeout_s); --episode-timeout still "
        "bounds the whole episode",
    )
    parser.add_argument(
        "--max-wall-seconds",
        type=float,
        default=None,
        help="stop launching units once this much wall time has passed; unlaunched units are recorded as NOT MEASURED",
    )
    parser.add_argument("--corpus", choices=CORPUS_CHOICES, default="episodes")
    parser.add_argument("--fixture", type=Path, default=None, help="fact fixture for offline quality scoring")
    parser.add_argument("--repo", choices=("fresh", "shared"), default="fresh")
    parser.add_argument("--stage", choices=("all", "librarian"), default="all")
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--test-model", action="store_true")
    parser.add_argument("--profile", choices=PROFILES, default=None)
    parser.add_argument("--classify", action="store_true", help="also time the domain classifier")
    return parser


def git_head() -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return "NOT_MEASURED"
    return completed.stdout.strip() or "NOT_MEASURED"


def _write_classifier_capture(cache_dir: Path, episode: str, exc: BaseException, messages: list[Any]) -> Path:
    """Write a private failure capture: model messages live in the cache, never in validation."""
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"classifier-{episode}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    try:
        dumped = json.loads(ModelMessagesTypeAdapter.dump_json(messages))
    except Exception as dump_error:  # a capture failure must not mask the original error
        dumped = [{"capture_error": type(dump_error).__name__}]
    path.write_text(
        json.dumps({"error_type": type(exc).__name__, "error": str(exc), "messages": dumped}, indent=2),
        encoding="utf-8",
    )
    return path


async def _classify(
    text: str,
    episode: str,
    episode_id: int,
    config: AgentInferenceConfig,
    thinking: ThinkingLevel,
    timeout: float,
    cache_dir: Path,
) -> tuple[float, str, int, int, list[str] | None]:
    """Run the domain classifier once.

    Returns seconds, status, counts, and privacy-safe domain keys.  Only
    allowlisted known slugs and hashes of canonical proposed names reach the
    summary; all other model output remains private.
    """
    from pydantic_ai import capture_run_messages

    from neocortex.domains.classifier import AgentDomainClassifier

    classifier = AgentDomainClassifier(
        model_name=config.model_name, thinking_effort=thinking, local_endpoint=config.local_endpoint
    )
    status = "ok"
    matched = proposed = 0
    domain_keys: list[str] | None = None
    started = time.monotonic()
    with capture_run_messages() as messages:
        try:
            with _classifier_model_override(config.use_test_model):
                result = await asyncio.wait_for(
                    classifier.classify(text, list(SEED_DOMAINS), agent_id=AGENT_ID, episode_id=episode_id),
                    timeout=timeout,
                )
            matched = len(result.matched_domains)
            proposed = int(result.proposed_domain is not None)
            domain_keys = _classifier_domain_keys(result)
            if domain_keys is None:
                status = "error:InvalidClassifierDomainKeys"
        except (TimeoutError, APITimeoutError):
            status = "timeout"
        except Exception as exc:  # a classifier failure is a recorded measurement
            status = f"error:{type(exc).__name__}"
            print(f"classifier capture: {_write_classifier_capture(cache_dir, episode, exc, messages)}")
    return round(time.monotonic() - started, 2), status, matched, proposed, domain_keys


def _classifier_domain_keys(result: ClassificationResult) -> list[str] | None:
    """Return sorted privacy-safe keys, or null when a result is unusable.

    Proposal hashes are pseudonymous equality keys, not anonymous values.  They
    must not be interpreted beyond comparisons inside the same measurement run.
    """
    keys: set[str] = set()
    for match in result.matched_domains:
        if match.domain_slug not in _KNOWN_DOMAIN_SLUGS:
            return None
        keys.add(f"known:{match.domain_slug}")

    if result.proposed_domain is not None:
        canonical_name = " ".join(unicodedata.normalize("NFKC", result.proposed_domain.name).split()).casefold()
        if not canonical_name:
            return None
        digest = hashlib.sha256(canonical_name.encode("utf-8")).hexdigest()
        keys.add(f"proposed:sha256:{digest}")

    return sorted(keys)


@dataclass(frozen=True)
class Unit:
    """One measured run unit: a compact episode or a supersession triplet.

    A triplet is two texts on one shared repository that produce a single
    summary row, so the probe measures the same before/after defect the E2E
    children measure.
    """

    key: str
    kind: str  # "episode" | "triplet"
    texts: tuple[tuple[str, str], ...]  # (stage-row label, text)
    importance: float


@dataclass
class UnitProgress:
    """Mutable evidence retained if a wall deadline cancels ``run_unit``."""

    rows: list[dict[str, Any]]
    active_label: str | None = None


def resolve_thinking_levels(args: argparse.Namespace) -> dict[str, str]:
    """Return the resolved CLI level name per agent, falling back to ``--thinking``."""
    return {agent: (getattr(args, f"thinking_{agent}") or args.thinking) for agent in TUNABLE_AGENTS}


def build_configs(
    args: argparse.Namespace, levels: dict[str, str], endpoint: LocalEndpoint | None
) -> dict[str, AgentInferenceConfig]:
    """Build one :class:`AgentInferenceConfig` per tunable agent."""
    if args.test_model:
        return {
            agent: AgentInferenceConfig(
                model_name=args.model,
                use_test_model=True,
                thinking_effort=THINKING[levels[agent]],
                local_endpoint=endpoint,
            )
            for agent in TUNABLE_AGENTS
        }
    return {
        agent: AgentInferenceConfig(
            model_name=args.model, thinking_effort=THINKING[levels[agent]], local_endpoint=endpoint
        )
        for agent in TUNABLE_AGENTS
    }


def select_units(args: argparse.Namespace, corpus: dict[int, dict[str, object]], fixture: Fixture | None) -> list[Unit]:
    """Expand ``--corpus`` into the ordered run units."""
    keys: list[str] = []
    if args.corpus == "episodes":
        keys = list(args.episodes)
    elif args.corpus in ("compact", "both"):
        keys = list(EPISODE_KEYS)
    units = [
        Unit(
            key=key,
            kind="episode",
            texts=((key, str(corpus[EPISODE_KEYS[key]]["text"])),),
            importance=float(str(corpus[EPISODE_KEYS[key]]["importance"])),
        )
        for key in keys
    ]
    if args.corpus in ("supersession", "both") and fixture is not None:
        units.extend(
            Unit(
                key=triplet.id,
                kind="triplet",
                texts=((f"{triplet.id}-1", triplet.initial_text), (f"{triplet.id}-2", triplet.update_text)),
                importance=TRIPLET_IMPORTANCE,
            )
            for triplet in fixture.supersession
        )
    return units


def blank_summary(key: str, status: str, reason: str) -> dict[str, Any]:
    """A never-launched unit: nulls, never zeros that would read as measured."""
    return {
        "episode": key,
        "words": None,
        "seconds_total": None,
        "requests_total": None,
        "nodes_after": None,
        "edges_after": None,
        "edge_types_after": None,
        "fact_score": None,
        "supersession": None,
        "critical_defects": None,
        "status": status,
        "reason": reason,
    }


def _valid_type_name(name: str, normalizer: Callable[[str], str]) -> bool:
    """Return whether the repository normalizer accepts this stored spelling."""
    try:
        return normalizer(name) == name
    except ValueError:
        return False


def _node_signature(node: Any) -> tuple[Any, ...]:
    return node.type_id, node.name, node.content, json.dumps(node.properties, sort_keys=True, default=str)


def _edge_signature(edge: Any) -> tuple[Any, ...]:
    return (
        edge.source_id,
        edge.target_id,
        edge.type_id,
        edge.weight,
        json.dumps(edge.properties, sort_keys=True, default=str),
    )


def detect_critical_defects(
    before: GraphView,
    after: GraphView,
    records: list[dict[str, Any]],
    outcome: str,
) -> list[str]:
    """Return code-owned defect reasons observed while processing one text."""
    defects: set[str] = set()
    before_nodes = {node.id: _node_signature(node) for node in before.nodes}
    before_edges = {edge.id: _edge_signature(edge) for edge in before.edges}
    changed_nodes = [node for node in after.nodes if before_nodes.get(node.id) != _node_signature(node)]
    changed_edges = [edge for edge in after.edges if before_edges.get(edge.id) != _edge_signature(edge)]

    node_type_ids = {
        *(type_id for type_id, name in after.node_type_names.items() if before.node_type_names.get(type_id) != name),
        *(node.type_id for node in changed_nodes),
    }
    edge_type_ids = {
        *(type_id for type_id, name in after.edge_type_names.items() if before.edge_type_names.get(type_id) != name),
        *(edge.type_id for edge in changed_edges),
    }
    if any(
        not _valid_type_name(after.node_type_names[type_id], normalize_node_type)
        for type_id in node_type_ids
        if type_id in after.node_type_names
    ):
        defects.add("invalid_node_type")
    if any(
        not _valid_type_name(after.edge_type_names[type_id], normalize_edge_type)
        for type_id in edge_type_ids
        if type_id in after.edge_type_names
    ):
        defects.add("invalid_edge_type")

    stored_fields = [
        field
        for node in changed_nodes
        for field in (node.name, node.content or "", json.dumps(node.properties, sort_keys=True, default=str))
    ]
    stored_fields.extend(json.dumps(edge.properties, sort_keys=True, default=str) for edge in changed_edges)
    if any(_REASONING_MARKER.search(field) for field in stored_fields):
        defects.add("reasoning_marker")

    events = {str(record["event"]) for record in records}
    critical_failure_events = {
        str(record["event"])
        for record in records
        if not (outcome == "timeout" and record["fields"].get("error_type") in _TIMEOUT_ERROR_TYPES)
    }
    if "agent_run_failed" in critical_failure_events:
        defects.add("agent_run_failure")
    if "model_request_failed" in critical_failure_events:
        defects.add("model_request_failure")
    if "tool_call_failed" in critical_failure_events:
        defects.add("tool_call_failure")
    validation_rejected = any(
        record["event"] in {"tool_validation_rejected", "output_validation_retry"} for record in records
    )
    terminal_tool_rejection = any(
        int(record["fields"].get("retry") or 0) >= int(record["fields"].get("max_retries") or 0)
        for record in records
        if record["event"] == "tool_validation_rejected"
    )
    if validation_rejected and ("agent_run_failed" in critical_failure_events or terminal_tool_rejection):
        defects.add("validation_failure")
    # Successful structured-output tools are also redacted to ``unknown`` by
    # the shared audit hook. Only a failed executable tool is unambiguous here.
    if any(record["event"] == "tool_call_failed" and record["fields"].get("tool") == "unknown" for record in records):
        defects.add("unknown_tool")
    if outcome.startswith("error:") and not events.intersection(
        {"agent_run_failed", "model_request_failed", "tool_call_failed"}
    ):
        defects.add("unit_error")
    return sorted(defects)


def write_output(
    output: Path, run_meta: dict[str, Any], summaries: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> None:
    """Write the summary file.  Called after every unit so a kill leaves valid JSON."""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"run": run_meta, "episodes": summaries, "stages": rows}, indent=2), encoding="utf-8")


def chain_result(args: argparse.Namespace, fixture: Fixture | None, repo: InMemoryRepository) -> dict[str, Any]:
    """Evaluate the fixture's chain expectation, or say why it was not measured."""
    if args.corpus not in ("compact", "both"):
        return {"status": "NOT MEASURED", "reason": f"corpus={args.corpus}"}
    if fixture is None or fixture.chain is None:
        return {"status": "NOT MEASURED", "reason": "no_fixture"}
    if args.repo != "shared":
        return {"status": "NOT MEASURED", "reason": f"repo_mode={args.repo}"}
    measured = count_temporal_edges(snapshot_graph(repo))
    return {
        "episodes": list(fixture.chain.episodes),
        "min_temporal_edges": fixture.chain.min_temporal_edges,
        "temporal_edges": measured,
        "satisfied": measured >= fixture.chain.min_temporal_edges,
    }


async def run_text(
    label: str,
    text: str,
    importance: float,
    repo: InMemoryRepository,
    args: argparse.Namespace,
    collector: ActionLogCollector,
    configs: dict[str, AgentInferenceConfig],
    levels: dict[str, str],
    embeddings: Any,
    corpus_sha256: str,
    fixture_revision: int | None,
) -> tuple[float, str, list[dict[str, Any]], list[str]]:
    """Run one text and return seconds, outcome, stage rows, and defects."""
    collector.reset()
    episode_id = await repo.store_episode(
        AGENT_ID, text, importance=importance, metadata={"importance_hint": importance}
    )
    key = cache_key(
        label,
        args.model,
        THINKING[args.cache_thinking or args.thinking],
        corpus_sha256,
        text,
        test_model=args.test_model,
        fixture_revision=fixture_revision,
        ontology_thinking=THINKING[levels["ontology"]],
        extractor_thinking=THINKING[levels["extractor"]],
    )
    graph_before = snapshot_graph(repo)

    precomputed: dict[int, ExtractionResult] | None = None

    async def on_extracted(extracted_id: int, result: ExtractionResult) -> None:
        del extracted_id
        save_cached_extraction(
            args.cache_dir,
            key,
            result,
            type_snapshot(await repo.get_node_types(AGENT_ID)),
            type_snapshot(await repo.get_edge_types(AGENT_ID)),
        )

    started = time.monotonic()
    outcome = "ok"
    classifier_row: dict[str, Any] | None = None
    try:
        if args.stage == "librarian":
            cached, ontology = load_cached_extraction(args.cache_dir, key)
            for node_type in ontology["node_types"]:
                await repo.get_or_create_node_type(AGENT_ID, node_type["name"], node_type["description"])
            for edge_type in ontology["edge_types"]:
                await repo.get_or_create_edge_type(AGENT_ID, edge_type["name"], edge_type["description"])
            precomputed = {episode_id: cached}

        if args.classify:
            seconds, status, matched, proposed, domain_keys = await _classify(
                text,
                label,
                episode_id,
                configs["classifier"],
                THINKING[levels["classifier"]],
                args.episode_timeout,
                args.cache_dir,
            )
            classifier_row = _blank_row(label, "classifier", status)
            classifier_row["seconds"] = seconds
            classifier_row["matched_domains"] = matched
            classifier_row["proposed_domains"] = proposed
            classifier_row["domain_keys"] = domain_keys
            classifier_row["valid_result"] = status == "ok" and domain_keys is not None
            if status != "ok":
                outcome = status

        await asyncio.wait_for(
            run_extraction(
                repo=repo,
                embeddings=embeddings,
                agent_id=AGENT_ID,
                episode_ids=[episode_id],
                ontology_config=configs["ontology"],
                extractor_config=configs["extractor"],
                librarian_config=configs["librarian"],
                librarian_profile=args.profile,
                precomputed=precomputed,
                on_extracted=on_extracted,
            ),
            timeout=args.episode_timeout,
        )
    except (TimeoutError, APITimeoutError):
        if outcome == "ok":
            outcome = "timeout"
    except Exception as exc:  # a failure is a recorded measurement, not a crash
        if outcome == "ok":
            outcome = f"error:{type(exc).__name__}"
    seconds_total = round(time.monotonic() - started, 2)

    rows = aggregate_stage_rows(label, collector.records, outcome=outcome)
    if args.stage == "librarian" and outcome != "ok" and not any(row["stage"] == "librarian" for row in rows):
        # Cache preparation happens before the librarian emits lifecycle events.
        # Preserve that failure as a real stage row rather than an empty trace.
        rows.append(_blank_row(label, "librarian", outcome))
    if classifier_row is not None:
        # The classifier runs outside run_extraction, so the harness owns its timing.
        collected = next((row for row in rows if row["stage"] == "classifier"), None)
        if collected is None:
            rows.insert(0, classifier_row)
        else:
            collected["seconds"] = classifier_row["seconds"]
            collected["status"] = classifier_row["status"]
            collected["matched_domains"] = classifier_row["matched_domains"]
            collected["proposed_domains"] = classifier_row["proposed_domains"]
            collected["domain_keys"] = classifier_row["domain_keys"]
            collected["valid_result"] = classifier_row["valid_result"]

    defects = detect_critical_defects(graph_before, snapshot_graph(repo), collector.records, outcome)
    return seconds_total, outcome, rows, defects


async def run_unit(
    unit: Unit,
    repo: InMemoryRepository,
    args: argparse.Namespace,
    collector: ActionLogCollector,
    configs: dict[str, AgentInferenceConfig],
    levels: dict[str, str],
    embeddings: Any,
    corpus_sha256: str,
    fixture: Fixture | None,
    progress: UnitProgress,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run one unit's texts in order and return its summary plus stage rows.

    ``fact_score`` is ``None`` wherever nothing was measured — for a triplet, and
    for an episode the fixture says nothing about.  A zero-valued score there
    would read as a measured full-marks result.
    """
    seconds_total = 0.0
    rows = progress.rows
    critical_defects: set[str] = set()
    outcome = "ok"
    for label, text in unit.texts:
        progress.active_label = label
        seconds, text_outcome, text_rows, text_defects = await run_text(
            label,
            text,
            unit.importance,
            repo,
            args,
            collector,
            configs,
            levels,
            embeddings,
            corpus_sha256,
            fixture.revision if fixture is not None and unit.kind == "triplet" else None,
        )
        seconds_total += seconds
        rows.extend(text_rows)
        progress.active_label = None
        critical_defects.update(text_defects)
        if text_outcome != "ok" and outcome == "ok":
            outcome = text_outcome

    fact_score: dict[str, Any] | None = None
    supersession: dict[str, Any] | None = None
    if fixture is not None:
        graph = snapshot_graph(repo)
        if unit.kind == "episode":
            episode_fixture = fixture.episode(unit.key)
            if episode_fixture is not None:
                fact_score = asdict(score_episode(graph, episode_fixture))
        else:
            triplet = fixture.triplet(unit.key)
            if triplet is not None:
                supersession = asdict(score_supersession(graph, triplet))

    ontology_summary = await repo.get_ontology_summary(AGENT_ID)
    summary = {
        "episode": unit.key,
        "words": sum(len(text.split()) for _, text in unit.texts),
        "seconds_total": round(seconds_total, 2),
        "requests_total": sum(int(row["requests"]) for row in rows),
        "nodes_after": int(ontology_summary["total_nodes"]),
        "edges_after": int(ontology_summary["total_edges"]),
        "edge_types_after": {
            str(item["name"]): int(item["usage_count"])
            for item in ontology_summary["edge_types"]
            if int(item["usage_count"]) > 0
        },
        "fact_score": fact_score,
        "supersession": supersession,
        "critical_defects": sorted(critical_defects),
        "status": outcome,
    }
    return summary, rows


HEADER = ("ep", "stage", "seconds", "reqs", "tools", "in_tok", "out_tok", "think", "ents", "rels")
WIDTHS = (5, 11, 9, 5, 6, 9, 9, 9, 5, 5)
ROW_FIELDS = ("episode", "stage", "seconds", *COUNT_FIELDS, "entities", "relations")


def _line(values: tuple[Any, ...], status: str, suffix: str = "") -> str:
    cells = [
        f"{'-' if value is None else value!s:{'<' if index < 2 else '>'}{width}}"
        for index, (value, width) in enumerate(zip(values, WIDTHS, strict=True))
    ]
    return " ".join(cells) + f"  {status}{suffix}"


def print_rows(summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    for row in rows:
        print(_line(tuple(row[field] for field in ROW_FIELDS), row["status"]))
    totals = (
        summary["episode"],
        "TOTAL",
        summary["seconds_total"],
        summary["requests_total"],
        *([""] * 4),
        summary["nodes_after"],
        summary["edges_after"],
    )
    words = summary["words"]
    print(_line(totals, summary["status"], f"  words={'-' if words is None else words}"))


async def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.corpus in ("supersession", "both") and args.fixture is None:
        parser.error(f"--corpus {args.corpus} runs the supersession triplets, which live in --fixture; pass --fixture")
    levels = resolve_thinking_levels(args)
    corpus = {int(record["number"]): record for record in load_corpus(profile="compact")}
    corpus_sha256 = hashlib.sha256(corpus_path("compact").read_bytes()).hexdigest()
    fixture = load_fixture(args.fixture) if args.fixture is not None else None
    units = select_units(args, corpus, fixture)

    collector = install_collector()
    if args.test_model:
        # The endpoint object supplies Qwen-specific settings without creating
        # a provider; every TestModel config still bypasses network model setup.
        endpoint, embeddings, embeddings_mode = resolve_local_endpoint(args.per_call_timeout), None, "none"
    else:
        # The model comes from the CLI, never from MCPSettings, so .env cannot override it.
        endpoint = resolve_local_endpoint(args.per_call_timeout)
        embeddings, embeddings_mode = resolve_embeddings()
    configs = build_configs(args, levels, endpoint)

    output = args.output or (VALIDATION_DIR / f"speed-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json")
    run_meta: dict[str, Any] = {
        "model": "test-model" if args.test_model else args.model,
        "thinking": args.thinking,
        **{f"thinking_{agent}": levels[agent] for agent in TUNABLE_AGENTS},
        "cache_thinking": args.cache_thinking or args.thinking,
        "corpus_sha256": corpus_sha256,
        "corpus": args.corpus,
        "episodes": list(args.episodes),
        "units": [unit.key for unit in units],
        "fixture": str(args.fixture) if args.fixture is not None else None,
        "repo_mode": args.repo,
        "stage": args.stage,
        "profile": args.profile,
        "episode_timeout_s": args.episode_timeout,
        "per_call_timeout_s": args.per_call_timeout,
        "max_wall_seconds": args.max_wall_seconds,
        "wall_budget_exhausted": False,
        "chain": {"status": "NOT MEASURED", "reason": "run_incomplete"},
        "embeddings": embeddings_mode,
        "started_at": datetime.now(UTC).isoformat(),
        "git_head": git_head(),
        "pydantic_ai_version": pydantic_ai.__version__,
    }
    print(f"run: model={run_meta['model']} thinking={args.thinking} stage={args.stage} repo={args.repo}")
    print(_line(HEADER, "status"))

    shared_repo = InMemoryRepository()
    summaries: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    wall_started = time.monotonic()
    wall_deadline = wall_started + args.max_wall_seconds if args.max_wall_seconds is not None else None
    for index, unit in enumerate(units):
        remaining = wall_deadline - time.monotonic() if wall_deadline is not None else None
        if remaining is not None and remaining <= 0:
            # Stop launching, but record every unlaunched unit rather than dropping it.
            run_meta["wall_budget_exhausted"] = True
            for pending in units[index:]:
                summary = blank_summary(pending.key, "NOT MEASURED", "wall_budget")
                summaries.append(summary)
                print_rows(summary, [])
            write_output(output, run_meta, summaries, all_rows)
            break
        # A triplet always runs its two texts on one repository of its own, so
        # ``--repo`` cannot separate the update from the text it corrects.
        repo = InMemoryRepository() if unit.kind == "triplet" or args.repo == "fresh" else shared_repo
        progress = UnitProgress(rows=[])
        pending = run_unit(
            unit,
            repo,
            args,
            collector,
            configs,
            levels,
            embeddings,
            corpus_sha256,
            fixture,
            progress,
        )
        try:
            summary, rows = (
                await asyncio.wait_for(pending, timeout=remaining) if remaining is not None else await pending
            )
        except TimeoutError:
            run_meta["wall_budget_exhausted"] = True
            rows = list(progress.rows)
            if progress.active_label is not None:
                rows.extend(partial_stage_rows(progress.active_label, collector.records))
            summary = blank_summary(unit.key, "TIMEOUT", "wall_budget_during_unit")
            summaries.append(summary)
            all_rows.extend(rows)
            print_rows(summary, rows)
            for unlaunched in units[index + 1 :]:
                unmeasured = blank_summary(unlaunched.key, "NOT MEASURED", "wall_budget")
                summaries.append(unmeasured)
                print_rows(unmeasured, [])
            run_meta["chain"] = {"status": "NOT MEASURED", "reason": "wall_budget"}
            run_meta["wall_seconds"] = round(time.monotonic() - wall_started, 2)
            write_output(output, run_meta, summaries, all_rows)
            break
        summaries.append(summary)
        all_rows.extend(rows)
        print_rows(summary, rows)
        write_output(output, run_meta, summaries, all_rows)

    # A budget cut leaves the shared graph short of the chain's episodes, so the
    # count it would report is not the chain expectation.
    run_meta["chain"] = (
        {"status": "NOT MEASURED", "reason": "wall_budget"}
        if run_meta["wall_budget_exhausted"]
        else chain_result(args, fixture, shared_repo)
    )
    run_meta["wall_seconds"] = round(time.monotonic() - wall_started, 2)
    write_output(output, run_meta, summaries, all_rows)
    ok = sum(1 for summary in summaries if summary["status"] == "ok")
    print(f"run total: {run_meta['wall_seconds']}s, {ok}/{len(summaries)} episodes ok, summary written to {output}")
    return 0 if summaries and ok == len(summaries) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
