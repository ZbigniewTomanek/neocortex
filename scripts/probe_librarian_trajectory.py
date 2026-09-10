#!/usr/bin/env python3
"""Run the fixed E04/E05 A0/A1/A2 librarian trajectory matrix."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import math
import os
import subprocess
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pydantic_ai
from pydantic_ai.messages import RetryPromptPart, ToolCallPart

from neocortex.db.adapter import GraphServiceAdapter
from neocortex.db.scoped import schema_scoped_connection
from neocortex.extraction.agents import (
    AgentInferenceConfig,
    CurationActionTracker,
    ExtractorAgentDeps,
    LibrarianAgentDeps,
    LibrarianBudgetConfig,
    LibrarianProfile,
    LibrarianTrajectoryTracker,
    OntologyAgentDeps,
    build_extractor_agent,
    build_librarian_agent,
    build_librarian_relation_items,
    build_ontology_agent,
)
from neocortex.mcp_settings import MCPSettings
from neocortex.model_factory import LocalEndpoint
from neocortex.services import create_services, shutdown_services

try:
    from corpus_loader import COMPACT_CORPUS, load_corpus  # ty: ignore[unresolved-import]
except ModuleNotFoundError:  # Imported as a module by deterministic tests.
    from scripts.corpus_loader import COMPACT_CORPUS, load_corpus  # ty: ignore[unresolved-import]

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/qwen_librarian_e04_e05.json"
EXPECTED_CORPUS_SHA256 = "2394bcacfc4fcff6d8ee1f280f8642f8eaf864797cfcd4b333d57b4b9da296d3"
PROFILES: tuple[tuple[str, LibrarianProfile], ...] = (
    ("A0", "qwen_legacy"),
    ("A1", "qwen_finite"),
    ("A2", "qwen_bounded"),
)
PREIMAGE_KEYS = {"episode_key", "kind", "subject", "predicate", "object"}
KINDS = {"node_fact", "edge_signature", "quantitative_update", "temporal_edge"}
SAFE_TOOL_NAMES = {
    "archive_node",
    "apply_entity_decisions",
    "apply_relation_decisions",
    "check_relations",
    "create_or_update_edge",
    "create_or_update_node",
    "find_node_by_name",
    "find_similar_nodes",
    "get_edges_between",
    "inspect_node_neighborhood",
    "read_entity_details",
    "remove_edge",
    "resolve_entities",
    "search_existing_nodes",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_expectation(preimage: dict[str, str]) -> bytes:
    normalized = {key: unicodedata.normalize("NFC", value) for key, value in preimage.items()}
    return json.dumps(
        {"domain": "neocortex-qwen-probe-v1", **normalized},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def validate_fixture(path: Path = FIXTURE) -> dict[str, Any]:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    source = fixture.get("source", {})
    if source.get("path") != COMPACT_CORPUS.relative_to(ROOT).as_posix():
        raise ValueError("fixture source path is not the immutable compact corpus")
    if source.get("sha256") != EXPECTED_CORPUS_SHA256 or sha256_file(COMPACT_CORPUS) != EXPECTED_CORPUS_SHA256:
        raise ValueError("compact corpus digest changed")
    lines = COMPACT_CORPUS.read_text(encoding="utf-8").splitlines()
    seen: set[bytes] = set()
    episodes = fixture.get("episodes")
    if not isinstance(episodes, list) or {row.get("episode_key") for row in episodes} != {"E04", "E05"}:
        raise ValueError("fixture must contain exactly E04 and E05")
    for row in episodes:
        start, end = row.get("source_block_lines", (0, 0))
        if not (1 <= start <= end <= len(lines)) or not any(row["heading"] in line for line in lines[:start]):
            raise ValueError("fixture line span does not exist under its named heading")
        expectations = row.get("expectations")
        if not expectations:
            raise ValueError("fixture expectation sets cannot be empty")
        for expectation in expectations:
            if set(expectation) != {"preimage", "sha256"}:
                raise ValueError("hash-only or generated fixture expectation")
            preimage = expectation["preimage"]
            if set(preimage) != PREIMAGE_KEYS or preimage["kind"] not in KINDS:
                raise ValueError("fixture preimage shape is invalid")
            canonical = canonical_expectation(preimage)
            if canonical in seen:
                raise ValueError("duplicate fixture preimage")
            seen.add(canonical)
            if hashlib.sha256(canonical).hexdigest() != expectation["sha256"]:
                raise ValueError("fixture expectation digest is invalid")
    return fixture


def select_probe_episodes() -> list[dict[str, object]]:
    if sha256_file(COMPACT_CORPUS) != EXPECTED_CORPUS_SHA256:
        raise ValueError("compact corpus digest changed")
    selected = [row for row in load_corpus(profile="compact") if row["number"] in {4, 5}]
    if [row["number"] for row in selected] != [4, 5]:
        raise ValueError("fixed probe episode selection failed")
    return selected


def provider_call_minimum(entities: int, details: int, relations: int) -> int:
    return (
        math.ceil(entities / 16)
        + math.ceil(details / 8)
        + math.ceil(entities / 8)
        + math.ceil(relations / 16)
        + math.ceil(relations / 8)
    )


def evaluate_material_improvement(rows: list[dict[str, Any]]) -> dict[str, Any]:
    required_numeric = ("provider_tool_calls", "requests", "validation_rejections")
    relevant = [row for row in rows if row.get("arm") in {"A0", "A2"}]
    if any(row.get("status") != "completed" for row in relevant) or any(
        not isinstance(row.get(metric), int) for row in relevant for metric in required_numeric
    ):
        return {"status": "NOT_MEASURED", "reason": "paired arm failed, timed out, or lacks numeric usage"}
    paired = {(row["arm"], row["episode_key"], row["repeat"]): row for row in rows}
    baselines = [row for key, row in paired.items() if key[0] == "A0"]
    candidates = [row for key, row in paired.items() if key[0] == "A2"]
    if len(baselines) != len(candidates) or not baselines:
        return {"status": "NOT_MEASURED", "reason": "incomplete paired matrix"}
    minimum = sum(row["provider_call_minimum"] for row in candidates)
    baseline_tools = sum(row["provider_tool_calls"] for row in baselines)
    baseline_requests = sum(row["requests"] for row in baselines)
    tool_ceiling = math.floor(0.70 * baseline_tools)
    request_ceiling = math.floor(0.70 * baseline_requests)
    if tool_ceiling < minimum or request_ceiling < minimum + len(candidates):
        return {"status": "NOT_MEASURED", "reason": "fresh baseline ceiling is below computed minimum"}
    passed = (
        sum(row["provider_tool_calls"] for row in candidates) <= tool_ceiling
        and sum(row["requests"] for row in candidates) <= request_ceiling
        and all(row["status"] == "completed" for row in candidates)
        and all(row["max_read_streak"] <= 10 and row["duplicate_calls"] == 0 for row in candidates)
        and all(
            row["hard_budget_events"] == 0
            and row["outcome_assertions_failed"] == 0
            and row["idempotence_duplicate_count"] == 0
            for row in candidates
        )
        and all(
            paired[("A2", row["episode_key"], row["repeat"])][metric] <= math.ceil(1.10 * row[metric])
            for row in baselines
            for metric in ("provider_tool_calls", "requests")
        )
        and all(
            paired[("A2", row["episode_key"], row["repeat"])]["validation_rejections"] <= row["validation_rejections"]
            for row in baselines
        )
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "minimum": minimum,
        "tool_ceiling": tool_ceiling,
        "request_ceiling": request_ceiling,
    }


def _source_identity() -> tuple[str, str, list[dict[str, str]]]:
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True).stdout.strip()
    tracked = subprocess.run(
        ["git", "ls-files", "--", "src", "scripts", "tests"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.splitlines()
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "--", "src", "scripts", "tests"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.splitlines()
    manifest = [
        {"path": name, "sha256": sha256_file(ROOT / name)}
        for name in sorted(set(tracked + untracked))
        if (ROOT / name).is_file()
    ]
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return revision or "NOT_MEASURED", hashlib.sha256(encoded).hexdigest(), manifest


def _endpoint_identity(value: str) -> str:
    parsed = urlsplit(value if "://" in value else f"https://{value}")
    return urlunsplit((parsed.scheme, parsed.hostname or "", parsed.path, "", ""))


def _usage(result: Any) -> dict[str, int | None]:
    usage = result.usage()
    details = getattr(usage, "details", {}) or {}
    return {
        "requests": int(getattr(usage, "requests", 0)),
        "provider_tool_calls": int(getattr(usage, "tool_calls", 0)),
        "input_tokens": int(getattr(usage, "input_tokens", 0)),
        "output_tokens": int(getattr(usage, "output_tokens", 0)),
        "reasoning_tokens": details.get("reasoning_tokens"),
    }


async def _seed_types(
    repo: GraphServiceAdapter,
    target_schema: str,
    node_types: list[tuple[str, str | None]],
    edge_types: list[tuple[str, str | None]],
) -> None:
    for name, description in node_types:
        await repo.get_or_create_node_type("probe", name, description, target_schema=target_schema)
    for name, description in edge_types:
        await repo.get_or_create_edge_type("probe", name, description, target_schema=target_schema)


async def _extract_once(
    text: str,
    config: AgentInferenceConfig,
    repo: GraphServiceAdapter,
    target_schema: str,
) -> tuple[Any, list[tuple[str, str | None]], list[tuple[str, str | None]]]:
    base_nodes = [
        (name, None) for name in ("SoftwareComponent", "Database", "Table", "Feature", "Person", "Organization")
    ]
    base_edges = [(name, None) for name in ("USES", "CONTAINS", "HAS_FEATURE", "CORRECTS", "SUPERSEDES")]
    await _seed_types(repo, target_schema, base_nodes, base_edges)
    node_types = await repo.get_node_types("probe", target_schema=target_schema)
    edge_types = await repo.get_edge_types("probe", target_schema=target_schema)
    ontology = build_ontology_agent(config)
    ontology_result = await ontology.run(
        "Analyze the fixed source.",
        deps=OntologyAgentDeps(
            episode_text=text,
            existing_node_types=[x.name for x in node_types],
            existing_edge_types=[x.name for x in edge_types],
            repo=repo,
            agent_id="probe",
            target_schema=target_schema,
        ),
        model_settings=config.model_settings,
    )
    for item in ontology_result.output.new_node_types:
        await repo.get_or_create_node_type("probe", item.name, item.description, target_schema=target_schema)
    for item in ontology_result.output.new_edge_types:
        await repo.get_or_create_edge_type("probe", item.name, item.description, target_schema=target_schema)
    node_types = await repo.get_node_types("probe", target_schema=target_schema)
    edge_types = await repo.get_edge_types("probe", target_schema=target_schema)
    extractor = build_extractor_agent(config)
    extracted = await extractor.run(
        "Extract the fixed source.",
        deps=ExtractorAgentDeps(
            episode_text=text,
            node_types=[x.name for x in node_types],
            edge_types=[x.name for x in edge_types],
        ),
        model_settings=config.model_settings,
    )
    return (
        extracted.output,
        [(x.name, x.description) for x in node_types],
        [(x.name, x.description) for x in edge_types],
    )


async def _observe_graph(pool: Any, target_schema: str) -> dict[str, list[dict[str, Any]]]:
    async with schema_scoped_connection(pool, target_schema) as conn:
        nodes = [
            dict(row)
            for row in await conn.fetch(
                "SELECT id, type_id, name, content, properties, forgotten FROM node ORDER BY id"
            )
        ]
        edges = [
            dict(row)
            for row in await conn.fetch("SELECT id, source_id, target_id, type_id, properties FROM edge ORDER BY id")
        ]
        node_types = [dict(row) for row in await conn.fetch("SELECT id, name FROM node_type ORDER BY id")]
        edge_types = [dict(row) for row in await conn.fetch("SELECT id, name FROM edge_type ORDER BY id")]
    return {"nodes": nodes, "edges": edges, "node_types": node_types, "edge_types": edge_types}


async def _reset_graph_state(pool: Any, target_schema: str) -> None:
    """Reset mutable graph state before an arm while retaining its frozen ontology."""
    async with schema_scoped_connection(pool, target_schema) as conn:
        await conn.execute("TRUNCATE TABLE edge, node_alias, node RESTART IDENTITY")


def _graph_digest(graph: dict[str, list[dict[str, Any]]]) -> str:
    node_types = {row["id"]: row["name"] for row in graph["node_types"]}
    edge_types = {row["id"]: row["name"] for row in graph["edge_types"]}
    payload = {
        "nodes": sorted(
            (node_types.get(n["type_id"]), n["name"], n["content"], n["properties"]) for n in graph["nodes"]
        ),
        "edges": sorted(
            (e["source_id"], e["target_id"], edge_types.get(e["type_id"]), e["properties"]) for e in graph["edges"]
        ),
        "node_types": sorted(node_types.values()),
        "edge_types": sorted(edge_types.values()),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _safe_tool_counts(tool_names: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for raw_name in tool_names:
        name = raw_name if raw_name in SAFE_TOOL_NAMES else "unknown"
        counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items()))


def _observed_fact_hashes(episode_key: str, graph: dict[str, list[dict[str, Any]]]) -> set[str]:
    node_names = {row["id"]: row["name"] for row in graph["nodes"]}
    edge_types = {row["id"]: row["name"] for row in graph["edge_types"]}
    preimages: list[dict[str, str]] = []
    for node in graph["nodes"]:
        for key, value in sorted((node.get("properties") or {}).items()):
            if key == "_source_episode" or isinstance(value, (dict, list, tuple)):
                continue
            object_value = str(value).lower() if isinstance(value, bool) else str(value)
            for kind in ("node_fact", "quantitative_update"):
                preimages.append(
                    {
                        "episode_key": episode_key,
                        "kind": kind,
                        "subject": node["name"],
                        "predicate": str(key),
                        "object": object_value,
                    }
                )
    for edge in graph["edges"]:
        source, target, predicate = (
            node_names.get(edge["source_id"]),
            node_names.get(edge["target_id"]),
            edge_types.get(edge["type_id"]),
        )
        if source is None or target is None or predicate is None:
            continue
        for kind in ("edge_signature", "temporal_edge"):
            preimages.append(
                {"episode_key": episode_key, "kind": kind, "subject": source, "predicate": predicate, "object": target}
            )
    return {hashlib.sha256(canonical_expectation(preimage)).hexdigest() for preimage in preimages}


async def _run_arm(
    arm: str,
    profile: LibrarianProfile,
    episode_key: str,
    repeat: int,
    text: str,
    repo: GraphServiceAdapter,
    target_schema: str,
    extracted: Any,
    config: AgentInferenceConfig,
    embeddings: Any,
    budget: LibrarianBudgetConfig,
    timeout: float,
    pool: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    relation_items = build_librarian_relation_items(extracted.entities, extracted.relations)
    tracker: Any = (
        LibrarianTrajectoryTracker(entities=extracted.entities, relations=relation_items, budget=budget)
        if arm == "A2"
        else CurationActionTracker()
    )
    started = time.monotonic()
    private: dict[str, Any] = {"arm": arm, "episode_key": episode_key, "repeat": repeat}
    completed = False
    idempotence_duplicate_count = 0
    usage: dict[str, int | None] = {
        "requests": 0,
        "provider_tool_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": None,
    }
    tool_names: list[str] = []
    retries = 0
    try:
        agent = build_librarian_agent(config, use_tools=True, profile=profile)
        result = await asyncio.wait_for(
            agent.run(
                "Curate all fixed indexed inputs.",
                deps=LibrarianAgentDeps(
                    episode_text=text,
                    node_types=[x.name for x in await repo.get_node_types("probe", target_schema=target_schema)],
                    edge_types=[x.name for x in await repo.get_edge_types("probe", target_schema=target_schema)],
                    extracted_entities=extracted.entities,
                    extracted_relations=relation_items,
                    repo=repo,
                    embeddings=embeddings,
                    agent_id="probe",
                    target_schema=target_schema,
                    episode_id=repeat,
                    action_tracker=tracker,
                ),
                model_settings=config.model_settings,
            ),
            timeout=timeout,
        )
        usage = _usage(result)
        tool_names = [
            part.tool_name
            for msg in result.all_messages()
            for part in getattr(msg, "parts", [])
            if isinstance(part, ToolCallPart)
        ]
        retries = sum(
            isinstance(part, RetryPromptPart) for msg in result.all_messages() for part in getattr(msg, "parts", [])
        )
        report = tracker.build_report() if isinstance(tracker, LibrarianTrajectoryTracker) else None
        status = report.status if report else "completed"
        completed = True
        private["messages"] = [str(message) for message in result.all_messages()]
    except TimeoutError:
        status = "timeout"
    except Exception as exc:
        status = "failed"
        private["error_type"] = type(exc).__name__

    if arm == "A2" and completed:
        rerun_tracker = LibrarianTrajectoryTracker(entities=extracted.entities, relations=relation_items, budget=budget)
        try:
            rerun_result = await asyncio.wait_for(
                build_librarian_agent(config, use_tools=True, profile="qwen_bounded").run(
                    "Reconcile the same fixed indexed inputs on the post-state.",
                    deps=LibrarianAgentDeps(
                        episode_text=text,
                        node_types=[x.name for x in await repo.get_node_types("probe", target_schema=target_schema)],
                        edge_types=[x.name for x in await repo.get_edge_types("probe", target_schema=target_schema)],
                        extracted_entities=extracted.entities,
                        extracted_relations=relation_items,
                        repo=repo,
                        embeddings=embeddings,
                        agent_id="probe",
                        target_schema=target_schema,
                        episode_id=repeat,
                        action_tracker=rerun_tracker,
                    ),
                    model_settings=config.model_settings,
                ),
                timeout=timeout,
            )
            rerun_tracker.build_report()
            private["idempotence_messages"] = [str(message) for message in rerun_result.all_messages()]
        except Exception as exc:
            private["idempotence_error_type"] = type(exc).__name__
            idempotence_duplicate_count += 1

    graph = await _observe_graph(pool, target_schema)
    nodes = {row["id"]: row for row in graph["nodes"]}
    edges = {row["id"]: row for row in graph["edges"]}
    node_type_ids = {row["id"] for row in graph["node_types"]}
    edge_type_ids = {row["id"] for row in graph["edge_types"]}
    failures = sum(edge["source_id"] not in nodes or edge["target_id"] not in nodes for edge in edges.values())
    failures += sum(node["type_id"] not in node_type_ids for node in nodes.values())
    failures += sum(edge["type_id"] not in edge_type_ids for edge in edges.values())
    failures += sum((node.get("properties") or {}).get("_source_episode") != repeat for node in nodes.values())
    failures += sum((edge.get("properties") or {}).get("_source_episode") != repeat for edge in edges.values())
    canonical_nodes = {(node["name"].casefold(), node["type_id"]) for node in nodes.values()}
    canonical_edges = {(edge["source_id"], edge["target_id"], edge["type_id"]) for edge in edges.values()}
    idempotence_duplicate_count += len(nodes) - len(canonical_nodes) + len(edges) - len(canonical_edges)
    if isinstance(tracker, LibrarianTrajectoryTracker):
        failures += sum(node_id not in nodes for node_id in tracker.successful_node_ids)
        for edge_id, signature in tracker.successful_edge_signatures.items():
            edge = edges.get(edge_id)
            if edge is None or (edge["source_id"], edge["target_id"], edge["type_id"]) != signature:
                failures += 1
        failures += sum(edge_id in edges for edge_id in tracker.removed_edge_ids)

    fixture_episode = next(row for row in validate_fixture()["episodes"] if row["episode_key"] == episode_key)
    expected_hashes = {row["sha256"] for row in fixture_episode["expectations"]}
    observed_hashes = _observed_fact_hashes(episode_key, graph)
    matched_hashes = expected_hashes & observed_hashes
    failures += len(expected_hashes - matched_hashes)
    unknown_tools = sum(name not in SAFE_TOOL_NAMES for name in tool_names)
    failures += unknown_tools
    graph_hash = _graph_digest(graph)
    row = {
        "run_id": uuid.uuid4().hex,
        "arm": arm,
        "episode_key": episode_key,
        "repeat": repeat,
        "status": status,
        "elapsed_seconds": round(time.monotonic() - started, 4),
        **usage,
        "tool_counts": _safe_tool_counts(tool_names),
        "read_count": getattr(tracker, "repository_item_reads", "NOT_MEASURED"),
        "mutation_attempts": getattr(tracker, "mutations_attempted", sum(vars(tracker).values())),
        "mutation_successes": getattr(tracker, "mutations_succeeded", sum(vars(tracker).values())),
        "duplicate_calls": getattr(tracker, "duplicate_calls", 0),
        "max_read_streak": getattr(tracker, "max_read_streak", 0),
        "validation_rejections": getattr(tracker, "validation_rejections", retries),
        "soft_budget_events": len(getattr(tracker, "soft_reasons", [])),
        "hard_budget_events": int(bool(getattr(tracker, "hard_reason", None))),
        "tracker_dispositions": (
            {
                "availability": "MEASURED",
                "entities": dict(tracker.entity_states),
                "relations": dict(tracker.relation_states),
            }
            if isinstance(tracker, LibrarianTrajectoryTracker)
            else {"availability": "NOT_MEASURED"}
        ),
        "graph_node_count": len(nodes),
        "graph_edge_count": len(edges),
        "graph_outcome_hashes": sorted([graph_hash, *matched_hashes]),
        "outcome_assertions_failed": failures,
        "unknown_tool_calls": unknown_tools,
        "idempotence_duplicate_count": idempotence_duplicate_count,
        "provider_call_minimum": provider_call_minimum(
            len(extracted.entities),
            len(tracker.detailed_entities) if isinstance(tracker, LibrarianTrajectoryTracker) else 0,
            len(relation_items),
        ),
    }
    return row, private


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", required=True)
    parser.add_argument("--temperature", required=True, type=float)
    parser.add_argument("--top-p", required=True, type=float)
    parser.add_argument("--timeout", required=True, type=float)
    parser.add_argument("--embedding-model", required=True)
    parser.add_argument("--embedding-endpoint-id", required=True)
    parser.add_argument("--embedding-revision", default=os.environ.get("NEOCORTEX_EMBEDDING_REVISION"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--safe-summary", required=True, type=Path)
    parser.add_argument("--repeats", type=int, choices=(1, 3), default=1)
    args = parser.parse_args()
    if args.output.resolve() == ROOT or ROOT in args.output.resolve().parents:
        parser.error("private --output must be outside the repository")
    validate_fixture()
    episodes = select_probe_episodes()
    endpoint = os.environ.get("NEOCORTEX_LOCAL_MODEL_BASE_URL")
    api_key_env = os.environ.get("NEOCORTEX_LOCAL_MODEL_API_KEY_ENV", "VLLM_API_KEY")
    if not endpoint or not os.environ.get(api_key_env):
        parser.error("configured local endpoint and its API key environment are required")
    local_endpoint = LocalEndpoint(
        endpoint, api_key_env, args.temperature, args.top_p, args.temperature, args.top_p, args.timeout
    )
    config = AgentInferenceConfig(model_name=args.model, thinking_effort=args.effort, local_endpoint=local_endpoint)
    budget = LibrarianBudgetConfig()
    settings = MCPSettings(
        mock_db=False,
        extraction_enabled=False,
        domain_routing_enabled=False,
        embedding_model=args.embedding_model,
        local_model_base_url=endpoint,
        local_model_api_key_env=api_key_env,
        local_model_timeout_s=args.timeout,
    )
    services = await create_services(settings)
    repo = services["repo"]
    pg, schema_mgr, embeddings = services["pg"], services["schema_mgr"], services["embeddings"]
    if not isinstance(repo, GraphServiceAdapter) or pg is None or schema_mgr is None or embeddings is None:
        await shutdown_services(services)
        raise RuntimeError("probe requires the PostgreSQL repository and configured embedding service")
    vector = await embeddings.embed("neocortex fixed librarian trajectory probe")
    vector_dimension: int | str = len(vector) if vector is not None else "NOT_MEASURED"
    normalization: bool | str = (
        abs(math.sqrt(sum(value * value for value in vector)) - 1.0) <= 1e-6 if vector is not None else "NOT_MEASURED"
    )
    rows: list[dict[str, Any]] = []
    private_rows: list[dict[str, Any]] = []
    created_schemas: list[str] = []
    frozen: dict[str, tuple[Any, list[tuple[str, str | None]], list[tuple[str, str | None]]]] = {}
    pre_state_hashes: dict[str, list[str]] = {}
    clean_pre_states = True
    probe_agent = f"probe{uuid.uuid4().hex[:12]}"
    try:
        for episode in episodes:
            key = f"E{int(str(episode['number'])):02d}"
            schema = await schema_mgr.create_graph(probe_agent, f"extract{key.lower()}")
            created_schemas.append(schema)
            frozen[key] = await _extract_once(str(episode["text"]), config, repo, schema)
        for repeat in range(1, args.repeats + 1):
            for arm, profile in PROFILES:
                for episode in episodes:
                    key = f"E{int(str(episode['number'])):02d}"
                    extracted, node_types, edge_types = frozen[key]
                    schema = await schema_mgr.create_graph(probe_agent, f"{arm.lower()}{key.lower()}r{repeat}")
                    created_schemas.append(schema)
                    await _seed_types(repo, schema, node_types, edge_types)
                    await _reset_graph_state(pg.pool, schema)
                    pre_graph = await _observe_graph(pg.pool, schema)
                    clean_pre_states = clean_pre_states and not pre_graph["nodes"] and not pre_graph["edges"]
                    pre_state_hashes.setdefault(key, []).append(_graph_digest(pre_graph))
                    row, private = await _run_arm(
                        arm,
                        profile,
                        key,
                        repeat,
                        str(episode["text"]),
                        repo,
                        schema,
                        extracted,
                        config,
                        embeddings,
                        budget,
                        args.timeout,
                        pg.pool,
                    )
                    rows.append(row)
                    private_rows.append(private)
    finally:
        for schema in reversed(created_schemas):
            with contextlib.suppress(Exception):
                await schema_mgr.drop_graph(schema)
        await shutdown_services(services)

    revision, source_hash, source_manifest = _source_identity()
    expected_prestate_groups = len(PROFILES) * args.repeats
    graph_isolation = (
        len(created_schemas) == len(set(created_schemas))
        and clean_pre_states
        and set(pre_state_hashes) == {"E04", "E05"}
        and all(
            len(hashes) == expected_prestate_groups and len(set(hashes)) == 1 for hashes in pre_state_hashes.values()
        )
    )
    controls = {
        "model": args.model,
        "effort": args.effort,
        "temperature": args.temperature,
        "top_p": args.top_p,
        "timeout": args.timeout,
        "embedding_model": args.embedding_model,
        "embedding_endpoint_id": _endpoint_identity(args.embedding_endpoint_id),
        "embedding_revision": args.embedding_revision or "NOT_MEASURED",
        "vector_dimension": vector_dimension,
        "normalization": normalization,
        "graph_backend": "postgresql",
        "target_schema_isolation": graph_isolation,
        "source_revision": revision,
        "source_diff_sha256": source_hash,
        "source_manifest_sha256": source_hash,
        "source_files": source_manifest,
        "compact_corpus_path": COMPACT_CORPUS.relative_to(ROOT).as_posix(),
        "compact_corpus_sha256": EXPECTED_CORPUS_SHA256,
        "episode_keys": ["E04", "E05"],
        "profiles": [profile for _arm, profile in PROFILES],
        "parallel_tool_calls": False,
        "budget": vars(budget),
        "pydantic_ai_version": pydantic_ai.__version__,
    }
    gate = evaluate_material_improvement(rows)
    unmeasured_controls = [
        name
        for name in ("embedding_revision", "vector_dimension", "normalization", "target_schema_isolation")
        if controls[name] in {"NOT_MEASURED", False}
    ]
    if unmeasured_controls:
        gate = {"status": "NOT_MEASURED", "reason": "required controls unavailable", "controls": unmeasured_controls}
    elif any(row["unknown_tool_calls"] for row in rows):
        gate = {"status": "FAIL", "reason": "unknown provider tool identity"}
    safe = {
        "schema_version": 1,
        "kind": "neocortex-qwen-librarian-probe-summary",
        "controls": controls,
        "rows": rows,
        "gate": gate,
    }
    private = {**safe, "private_rows": private_rows}
    args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    args.output.write_text(json.dumps(private, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(args.output, 0o600)
    args.safe_summary.parent.mkdir(parents=True, exist_ok=True)
    args.safe_summary.write_text(json.dumps(safe, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if gate["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
