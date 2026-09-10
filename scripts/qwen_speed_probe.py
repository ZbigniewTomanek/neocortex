#!/usr/bin/env python3
"""Per-stage speed probe for the extraction pipeline against a local model.

Runs the real ``run_extraction`` over compact-corpus episodes on an
``InMemoryRepository`` (no PostgreSQL, no services), aggregates the structured
``action_log`` events the pipeline already emits, and writes a counts-only JSON
summary.  Extraction results are cached under ``--cache-dir`` so later work can
iterate on the librarian stage alone (``--stage librarian``).

The summary holds stage names, durations, and counts only.  Episode text,
prompts, entity names, and model output never reach it.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pydantic_ai
from loguru import logger
from pydantic_ai.settings import ThinkingLevel

from neocortex.db.mock import InMemoryRepository
from neocortex.domains.models import SEED_DOMAINS
from neocortex.extraction.agents import AgentInferenceConfig
from neocortex.extraction.pipeline import run_extraction
from neocortex.extraction.schemas import ExtractionResult
from neocortex.mcp_settings import MCPSettings
from neocortex.model_factory import LocalEndpoint
from neocortex.schemas.memory import TypeInfo

try:  # Direct ``python scripts/qwen_speed_probe.py`` invocation.
    from corpus_loader import corpus_path, load_corpus  # ty: ignore[unresolved-import]
except ModuleNotFoundError:  # Imported as ``scripts.qwen_speed_probe``.
    from scripts.corpus_loader import corpus_path, load_corpus  # ty: ignore[unresolved-import]

ROOT = Path(__file__).resolve().parents[1]
AGENT_ID = "qwen_speed_probe"
DEFAULT_MODEL = "local:qwen3.8-flash-next"
DEFAULT_BASE_URL = "http://127.0.0.1:24000/v1"
DEFAULT_API_KEY_ENV = "LITELLM_API_KEY"
CACHE_DIR = ROOT / ".tmp/qwen-swift/cache"
VALIDATION_DIR = ROOT / ".tmp/qwen-swift/validation"
EPISODE_KEYS: dict[str, int] = {f"E{number:02d}": number for number in (2, 4, 5, 10, 18, 20, 26, 27)}
THINKING: dict[str, ThinkingLevel] = {"off": False, "minimal": "minimal", "low": "low", "medium": "medium"}
PROFILES = ("hosted", "qwen_legacy", "qwen_finite", "qwen_bounded")
AGENTS = ("ontology", "extractor", "librarian")
# ``stage`` on pipeline events carries the ``_agent`` suffix; ``agent`` on agent
# lifecycle and usage events does not.  Both map to one probe stage name.
STAGE_NAMES = {name: name for name in AGENTS} | {f"{name}_agent": name for name in AGENTS}
STAGE_NAMES["domain_classifier"] = "classifier"
STAGE_ORDER = ("classifier", *AGENTS)
COUNT_FIELDS = ("requests", "tool_calls", "input_tokens", "output_tokens", "reasoning_tokens")
# Bounded-librarian diagnostics: counts and code-owned reason codes only.
TRAJECTORY_FIELDS = ("requests", "provider_tool_calls", "reads", "mutations_attempted", "mutations_succeeded",
                     "duplicates", "validation_rejections", "max_read_streak", "hard_reason")  # fmt: skip


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
    return {
        "episode": episode,
        "stage": stage,
        "seconds": None,
        **dict.fromkeys(COUNT_FIELDS, 0),
        "entities": None,
        "relations": None,
        "status": status,
    }


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
        stage = STAGE_NAMES.get(str(fields.get("stage") or fields.get("agent") or ""))
        if stage is None:
            continue
        event = record["event"]
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
        elif event == "librarian_trajectory":
            row("librarian")["trajectory"] = {name: fields.get(name) for name in TRAJECTORY_FIELDS if name in fields}

    return [rows[stage] for stage in STAGE_ORDER if stage in rows]


def cache_key(episode: str, model: str, thinking: ThinkingLevel, corpus_sha256: str, *, test_model: bool) -> str:
    """Return the cache file stem for one episode under one inference setup."""
    preimage = f"{model}|{thinking}|{corpus_sha256}|{'test' if test_model else 'live'}"
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
    parser.add_argument("--episode-timeout", type=float, default=900.0)
    parser.add_argument("--repo", choices=("fresh", "shared"), default="fresh")
    parser.add_argument("--stage", choices=("all", "librarian"), default="all")
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--test-model", action="store_true")
    parser.add_argument("--profile", choices=PROFILES, default=None)
    parser.add_argument("--classify", action="store_true", help="also time the domain classifier (needs a live model)")
    return parser


def git_head() -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return "NOT_MEASURED"
    return completed.stdout.strip() or "NOT_MEASURED"


async def _classify(
    text: str, episode_id: int, config: AgentInferenceConfig, thinking: ThinkingLevel, timeout: float
) -> tuple[float, str]:
    """Run the domain classifier once and return (seconds, status)."""
    from neocortex.domains.classifier import AgentDomainClassifier

    classifier = AgentDomainClassifier(
        model_name=config.model_name, thinking_effort=thinking, local_endpoint=config.local_endpoint
    )
    status = "ok"
    started = time.monotonic()
    try:
        await asyncio.wait_for(
            classifier.classify(text, list(SEED_DOMAINS), agent_id=AGENT_ID, episode_id=episode_id), timeout=timeout
        )
    except TimeoutError:
        status = "timeout"
    except Exception as exc:  # a classifier failure is a recorded measurement
        status = f"error:{type(exc).__name__}"
    return round(time.monotonic() - started, 2), status


async def run_episode(
    episode: str,
    repo: InMemoryRepository,
    corpus: dict[int, dict[str, object]],
    args: argparse.Namespace,
    collector: ActionLogCollector,
    config: AgentInferenceConfig,
    embeddings: Any,
    corpus_sha256: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run one episode end to end and return its summary plus stage rows."""
    record = corpus[EPISODE_KEYS[episode]]
    text = str(record["text"])
    episode_id = await repo.store_episode(
        AGENT_ID, text, importance=float(str(record["importance"])), metadata={"importance_hint": record["importance"]}
    )
    key = cache_key(episode, args.model, THINKING[args.thinking], corpus_sha256, test_model=args.test_model)
    collector.reset()

    precomputed: dict[int, ExtractionResult] | None = None
    if args.stage == "librarian":
        cached, ontology = load_cached_extraction(args.cache_dir, key)
        for node_type in ontology["node_types"]:
            await repo.get_or_create_node_type(AGENT_ID, node_type["name"], node_type["description"])
        for edge_type in ontology["edge_types"]:
            await repo.get_or_create_edge_type(AGENT_ID, edge_type["name"], edge_type["description"])
        precomputed = {episode_id: cached}

    async def on_extracted(extracted_id: int, result: ExtractionResult) -> None:
        del extracted_id
        save_cached_extraction(
            args.cache_dir,
            key,
            result,
            type_snapshot(await repo.get_node_types(AGENT_ID)),
            type_snapshot(await repo.get_edge_types(AGENT_ID)),
        )

    classifier_row: dict[str, Any] | None = None
    if args.classify:
        seconds, status = await _classify(text, episode_id, config, THINKING[args.thinking], args.episode_timeout)
        classifier_row = _blank_row(episode, "classifier", status)
        classifier_row["seconds"] = seconds

    started = time.monotonic()
    outcome = "ok"
    try:
        await asyncio.wait_for(
            run_extraction(
                repo=repo,
                embeddings=embeddings,
                agent_id=AGENT_ID,
                episode_ids=[episode_id],
                ontology_config=config,
                extractor_config=config,
                librarian_config=config,
                librarian_profile=args.profile,
                precomputed=precomputed,
                on_extracted=on_extracted,
            ),
            timeout=args.episode_timeout,
        )
    except TimeoutError:
        outcome = "timeout"
    except Exception as exc:  # a failure is a recorded measurement, not a crash
        outcome = f"error:{type(exc).__name__}"
    seconds_total = round(time.monotonic() - started, 2)

    rows = aggregate_stage_rows(episode, collector.records, outcome=outcome)
    if classifier_row is not None:
        # The classifier runs outside run_extraction, so the harness owns its timing.
        collected = next((row for row in rows if row["stage"] == "classifier"), None)
        if collected is None:
            rows.insert(0, classifier_row)
        else:
            collected["seconds"] = classifier_row["seconds"]
            collected["status"] = classifier_row["status"]

    ontology_summary = await repo.get_ontology_summary(AGENT_ID)
    summary = {
        "episode": episode,
        "words": len(text.split()),
        "seconds_total": seconds_total,
        "requests_total": sum(int(row["requests"]) for row in rows),
        "nodes_after": int(ontology_summary["total_nodes"]),
        "edges_after": int(ontology_summary["total_edges"]),
        "edge_types_after": {
            str(item["name"]): int(item["usage_count"])
            for item in ontology_summary["edge_types"]
            if int(item["usage_count"]) > 0
        },
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
    print(_line(totals, summary["status"], f"  words={summary['words']}"))


async def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    thinking = THINKING[args.thinking]
    corpus = {int(record["number"]): record for record in load_corpus(profile="compact")}
    corpus_sha256 = hashlib.sha256(corpus_path("compact").read_bytes()).hexdigest()

    collector = install_collector()
    if args.test_model:
        # The hosted default model name keeps TestModel free of endpoint requirements.
        config = AgentInferenceConfig(use_test_model=True, thinking_effort=thinking)
        embeddings, embeddings_mode = None, "none"
    else:
        # The model comes from the CLI, never from MCPSettings, so .env cannot override it.
        endpoint = resolve_local_endpoint(args.episode_timeout)
        config = AgentInferenceConfig(model_name=args.model, thinking_effort=thinking, local_endpoint=endpoint)
        embeddings, embeddings_mode = resolve_embeddings()

    output = args.output or (VALIDATION_DIR / f"speed-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json")
    run_meta: dict[str, Any] = {
        "model": "test-model" if args.test_model else args.model,
        "thinking": args.thinking,
        "corpus_sha256": corpus_sha256,
        "episodes": list(args.episodes),
        "repo_mode": args.repo,
        "stage": args.stage,
        "profile": args.profile,
        "episode_timeout_s": args.episode_timeout,
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
    for episode in args.episodes:
        repo = shared_repo if args.repo == "shared" else InMemoryRepository()
        summary, rows = await run_episode(episode, repo, corpus, args, collector, config, embeddings, corpus_sha256)
        summaries.append(summary)
        all_rows.extend(rows)
        print_rows(summary, rows)

    run_meta["wall_seconds"] = round(time.monotonic() - wall_started, 2)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"run": run_meta, "episodes": summaries, "stages": all_rows}, indent=2), encoding="utf-8"
    )
    ok = sum(1 for summary in summaries if summary["status"] == "ok")
    print(f"run total: {run_meta['wall_seconds']}s, {ok}/{len(summaries)} episodes ok, summary written to {output}")
    return 0 if ok == len(summaries) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
