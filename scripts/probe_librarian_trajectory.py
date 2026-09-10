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
import re
import subprocess
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pydantic_ai
from pydantic_ai import capture_run_messages
from pydantic_ai.messages import RetryPromptPart, ToolCallPart
from pydantic_ai.usage import RunUsage

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
from neocortex.extraction.schemas import ExtractionResult
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
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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


def select_probe_episodes(keys: set[str] | None = None) -> list[dict[str, object]]:
    if sha256_file(COMPACT_CORPUS) != EXPECTED_CORPUS_SHA256:
        raise ValueError("compact corpus digest changed")
    selected = [row for row in load_corpus(profile="compact") if row["number"] in {4, 5}]
    if [row["number"] for row in selected] != [4, 5]:
        raise ValueError("fixed probe episode selection failed")
    if keys is None:
        return selected
    return [row for row in selected if f"E{int(str(row['number'])):02d}" in keys]


def _selected_profiles(arms: set[str] | None = None) -> list[tuple[str, LibrarianProfile]]:
    return [(arm, profile) for arm, profile in PROFILES if arms is None or arm in arms]


def _is_complete_matrix(arms: list[tuple[str, LibrarianProfile]], episodes: list[dict[str, object]]) -> bool:
    return {arm for arm, _profile in arms} == {"A0", "A1", "A2"} and {
        f"E{int(str(row['number'])):02d}" for row in episodes
    } == {"E04", "E05"}


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
    paired = {(row["arm"], row["episode_key"], row["repeat"]): row for row in rows}
    baselines = [row for key, row in paired.items() if key[0] == "A0"]
    candidates = [row for key, row in paired.items() if key[0] == "A2"]
    if len(baselines) != len(candidates) or not baselines:
        return {"status": "NOT_MEASURED", "reason": "incomplete paired matrix"}
    if (
        any(row.get("status") not in {"completed", "timeout"} for row in baselines)
        or any(row.get("status") != "completed" for row in candidates)
        or any(not isinstance(row.get(metric), int) for row in relevant for metric in required_numeric)
    ):
        return {"status": "NOT_MEASURED", "reason": "paired arm failed or lacks eligible numeric usage"}
    censored_baselines = sum(row["status"] == "timeout" for row in baselines)
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
            and row.get("idempotence_status") == "completed"
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
        "a0_timeout_lower_bounds": censored_baselines,
    }


def _apply_gate_eligibility(
    gate: dict[str, Any], rows: list[dict[str, Any]], controls: dict[str, Any], complete_matrix: bool
) -> dict[str, Any]:
    if not complete_matrix:
        return {"status": "NOT_MEASURED", "reason": "diagnostic subset cannot satisfy production gate"}
    if any(row["fixture_assertion_status"] == "NOT_MEASURED" for row in rows):
        return {"status": "NOT_MEASURED", "reason": "frozen extractor output cannot represent checked fixture"}
    unavailable = [
        name
        for name in ("embedding_revision", "vector_dimension", "normalization", "target_schema_isolation")
        if controls[name] in {"NOT_MEASURED", False}
    ]
    if unavailable:
        return {"status": "NOT_MEASURED", "reason": "required controls unavailable", "controls": unavailable}
    if any(row["unknown_tool_calls"] for row in rows):
        return {"status": "FAIL", "reason": "unknown provider tool identity"}
    return gate


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


def _configure_embedding_api_key(env_name: str) -> str:
    if not ENV_NAME.fullmatch(env_name):
        raise ValueError("embedding API key environment name is invalid")
    value = os.environ.get(env_name)
    if not value:
        raise ValueError("configured embedding API key environment is absent or empty")
    os.environ["GOOGLE_API_KEY"] = value
    return env_name


async def _create_probe_graph(
    schema_mgr: Any,
    permissions: Any,
    probe_agent: str,
    purpose: str,
    granted_by: str,
    created_schemas: list[str],
) -> str:
    schema = await schema_mgr.create_graph(probe_agent, purpose, is_shared=True)
    created_schemas.append(schema)
    await permissions.grant(
        probe_agent,
        schema,
        can_read=True,
        can_write=True,
        granted_by=granted_by,
    )
    return schema


def _usage(result: Any) -> dict[str, int | None]:
    return _usage_snapshot(result.usage())


def _usage_snapshot(usage: RunUsage) -> dict[str, int | None]:
    details = getattr(usage, "details", {}) or {}
    return {
        "requests": usage.requests,
        "provider_tool_calls": usage.tool_calls,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "reasoning_tokens": details.get("reasoning_tokens"),
    }


async def _seed_types(
    repo: GraphServiceAdapter,
    agent_id: str,
    target_schema: str,
    node_types: list[tuple[str, str | None]],
    edge_types: list[tuple[str, str | None]],
) -> None:
    for name, description in node_types:
        await repo.get_or_create_node_type(agent_id, name, description, target_schema=target_schema)
    for name, description in edge_types:
        await repo.get_or_create_edge_type(agent_id, name, description, target_schema=target_schema)


async def _extract_once(
    text: str,
    config: AgentInferenceConfig,
    repo: GraphServiceAdapter,
    agent_id: str,
    target_schema: str,
    timeout: float,
) -> tuple[Any, list[tuple[str, str | None]], list[tuple[str, str | None]]]:
    base_nodes = [
        (name, None) for name in ("SoftwareComponent", "Database", "Table", "Feature", "Person", "Organization")
    ]
    base_edges = [(name, None) for name in ("USES", "CONTAINS", "HAS_FEATURE", "CORRECTS", "SUPERSEDES")]
    await _seed_types(repo, agent_id, target_schema, base_nodes, base_edges)
    node_types = await repo.get_node_types(agent_id, target_schema=target_schema)
    edge_types = await repo.get_edge_types(agent_id, target_schema=target_schema)
    ontology = build_ontology_agent(config)
    ontology_result = await asyncio.wait_for(
        ontology.run(
            "Analyze the fixed source.",
            deps=OntologyAgentDeps(
                episode_text=text,
                existing_node_types=[x.name for x in node_types],
                existing_edge_types=[x.name for x in edge_types],
                repo=repo,
                agent_id=agent_id,
                target_schema=target_schema,
            ),
            model_settings=config.model_settings,
        ),
        timeout=timeout,
    )
    for item in ontology_result.output.new_node_types:
        await repo.get_or_create_node_type(agent_id, item.name, item.description, target_schema=target_schema)
    for item in ontology_result.output.new_edge_types:
        await repo.get_or_create_edge_type(agent_id, item.name, item.description, target_schema=target_schema)
    node_types = await repo.get_node_types(agent_id, target_schema=target_schema)
    edge_types = await repo.get_edge_types(agent_id, target_schema=target_schema)
    extractor = build_extractor_agent(config)
    extracted = await asyncio.wait_for(
        extractor.run(
            "Extract the fixed source.",
            deps=ExtractorAgentDeps(
                episode_text=text,
                node_types=[x.name for x in node_types],
                edge_types=[x.name for x in edge_types],
            ),
            model_settings=config.model_settings,
        ),
        timeout=timeout,
    )
    return (
        extracted.output,
        [(x.name, x.description) for x in node_types],
        [(x.name, x.description) for x in edge_types],
    )


def _cache_provenance(
    *, model: str, effort: str, temperature: float, top_p: float, episode_keys: list[str]
) -> dict[str, Any]:
    return {
        "compact_corpus_sha256": EXPECTED_CORPUS_SHA256,
        "model": model,
        "effort": effort,
        "temperature": temperature,
        "top_p": top_p,
        "episode_keys": episode_keys,
    }


def _read_frozen_cache(
    path: Path, expected_provenance: dict[str, Any]
) -> tuple[dict[str, tuple[Any, list[tuple[str, str | None]], list[tuple[str, str | None]]]], dict[str, Any]]:
    cache = json.loads(path.read_text(encoding="utf-8"))
    if cache.get("schema_version") != 1 or cache.get("kind") != "neocortex-qwen-frozen-extraction":
        raise ValueError("frozen extraction cache identity is invalid")
    provenance = cache.get("provenance")
    if not isinstance(provenance, dict) or any(
        provenance.get(key) != value for key, value in expected_provenance.items()
    ):
        raise ValueError("frozen extraction cache provenance does not match the requested controls")
    cached_episodes = cache.get("episodes")
    if not isinstance(cached_episodes, dict) or set(cached_episodes) != set(expected_provenance["episode_keys"]):
        raise ValueError("frozen extraction cache episode set is invalid")
    frozen: dict[str, tuple[Any, list[tuple[str, str | None]], list[tuple[str, str | None]]]] = {}
    for key in expected_provenance["episode_keys"]:
        item = cached_episodes[key]
        extracted = ExtractionResult.model_validate(item.get("extracted"))
        node_types = item.get("node_types")
        edge_types = item.get("edge_types")
        if not isinstance(node_types, list) or not isinstance(edge_types, list):
            raise ValueError("frozen extraction cache ontology shape is invalid")
        typed_groups: list[list[tuple[str, str | None]]] = []
        for group in (node_types, edge_types):
            typed: list[tuple[str, str | None]] = []
            for value in group:
                if (
                    not isinstance(value, list)
                    or len(value) != 2
                    or not isinstance(value[0], str)
                    or (value[1] is not None and not isinstance(value[1], str))
                ):
                    raise ValueError("frozen extraction cache ontology entry is invalid")
                typed.append((value[0], value[1]))
            typed_groups.append(typed)
        frozen[key] = (extracted, typed_groups[0], typed_groups[1])
    return frozen, provenance


def _write_frozen_cache(
    path: Path,
    frozen: dict[str, tuple[Any, list[tuple[str, str | None]], list[tuple[str, str | None]]]],
    provenance: dict[str, Any],
) -> None:
    payload = {
        "schema_version": 1,
        "kind": "neocortex-qwen-frozen-extraction",
        "provenance": {**provenance, "origin": "live_extraction"},
        "episodes": {
            key: {
                "extracted": extracted.model_dump(mode="json"),
                "node_types": node_types,
                "edge_types": edge_types,
            }
            for key, (extracted, node_types, edge_types) in frozen.items()
        },
    }
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def _safe_cache_summary(
    path: Path, provenance: dict[str, Any], frozen: dict[str, tuple[Any, Any, Any]]
) -> dict[str, Any]:
    return {
        "sha256": sha256_file(path),
        "provenance": provenance,
        "cardinalities": {
            key: {
                "entities": len(extracted.entities),
                "relations": len(build_librarian_relation_items(extracted.entities, extracted.relations)),
                "node_types": len(node_types),
                "edge_types": len(edge_types),
            }
            for key, (extracted, node_types, edge_types) in frozen.items()
        },
    }


async def _observe_graph(pool: Any, target_schema: str) -> dict[str, list[dict[str, Any]]]:
    async with schema_scoped_connection(pool, target_schema) as conn:
        nodes = [
            _normalize_graph_properties(dict(row))
            for row in await conn.fetch(
                "SELECT id, type_id, name, content, properties, forgotten FROM node ORDER BY id"
            )
        ]
        edges = [
            _normalize_graph_properties(dict(row))
            for row in await conn.fetch("SELECT id, source_id, target_id, type_id, properties FROM edge ORDER BY id")
        ]
        node_types = [dict(row) for row in await conn.fetch("SELECT id, name FROM node_type ORDER BY id")]
        edge_types = [dict(row) for row in await conn.fetch("SELECT id, name FROM edge_type ORDER BY id")]
    return {"nodes": nodes, "edges": edges, "node_types": node_types, "edge_types": edge_types}


def _normalize_graph_properties(row: dict[str, Any]) -> dict[str, Any]:
    properties = row.get("properties")
    if isinstance(properties, str):
        try:
            properties = json.loads(properties)
        except json.JSONDecodeError:
            raise ValueError("graph properties are not valid JSON") from None
    if not isinstance(properties, dict):
        raise ValueError("graph properties must be a JSON object")
    row["properties"] = properties
    return row


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


def _message_counters(messages: list[Any], output_tool_name: str | None) -> dict[str, Any]:
    executable: list[str] = []
    terminal_output_calls = 0
    retries = 0
    for message in messages:
        for part in getattr(message, "parts", []):
            if isinstance(part, RetryPromptPart):
                retries += 1
            elif isinstance(part, ToolCallPart):
                if output_tool_name is not None and part.tool_name == output_tool_name:
                    terminal_output_calls += 1
                else:
                    executable.append(part.tool_name)
    return {
        "tool_names": executable,
        "terminal_output_calls": terminal_output_calls,
        "validation_rejections": retries,
    }


def _failure_reason(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return "timeout"
    if type(exc).__name__ == "LibrarianIncompleteError":
        return "incomplete_terminalization"
    if isinstance(exc, ValueError):
        known = {
            "indices must be non-empty, unique, ascending, and within the batch limit": "invalid_index_batch",
            "indices must be non-empty and non-negative": "invalid_index_batch",
            "unique index count exceeds the batch limit": "unique_batch_limit",
            "item index out of range": "item_index_out_of_range",
            "entity details are out of phase": "entity_detail_phase_violation",
            "detail node was not the resolver-selected candidate": "entity_detail_identity_mismatch",
            "entity detail requires a resolver-selected candidate": "entity_detail_candidate_missing",
            "resolver-selected detail candidate is unavailable": "entity_detail_candidate_unavailable",
            "decision identity differs from the selected resolver candidate": "entity_decision_identity_mismatch",
            "existing candidates must be inspected before a decision": "entity_detail_required",
            "create and update decisions require content": "entity_content_missing",
            "truncated details cannot be updated": "entity_detail_truncated",
            "unresolved requires ambiguity or truncated details": "invalid_unresolved_entity",
            "archive_then_create requires explicit temporal evidence": "invalid_temporal_entity",
            "invalid extracted entity type": "invalid_entity_type",
            "relation checks are out of phase": "relation_phase_violation",
            "relation decisions require a prior check": "relation_check_missing",
            "existing_equivalent requires a checked edge": "equivalent_edge_not_checked",
            "replace edge was not returned for this relation": "replacement_edge_not_checked",
            "unresolved requires a missing endpoint or ambiguity": "invalid_unresolved_relation",
            "relation mutation endpoints are missing": "relation_endpoint_missing",
            "invalid extracted relation type": "invalid_relation_type",
        }
        return known.get(str(exc), "value_error_unclassified")
    return {
        "LibrarianTrajectoryLimitExceeded": "trajectory_limit",
        "LibrarianIdentityMismatch": "identity_mismatch",
        "UnexpectedModelBehavior": "model_protocol_failure",
    }.get(type(exc).__name__, "unclassified_exception")


def _mutation_counts(tracker: CurationActionTracker) -> tuple[int, int]:
    if isinstance(tracker, LibrarianTrajectoryTracker):
        return tracker.mutations_attempted, tracker.mutations_succeeded
    successful = sum(
        (
            tracker.entities_created,
            tracker.entities_updated,
            tracker.entities_archived,
            tracker.edges_created,
            tracker.edges_removed,
        )
    )
    return successful, successful


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


def _extractable_fact_hashes(episode_key: str, extracted: Any) -> set[str]:
    preimages: list[dict[str, str]] = []
    for entity in extracted.entities:
        for key, value in sorted(entity.properties.items()):
            if isinstance(value, (dict, list, tuple)):
                continue
            object_value = str(value).lower() if isinstance(value, bool) else str(value)
            for kind in ("node_fact", "quantitative_update"):
                preimages.append(
                    {
                        "episode_key": episode_key,
                        "kind": kind,
                        "subject": entity.name,
                        "predicate": str(key),
                        "object": object_value,
                    }
                )
    for relation in build_librarian_relation_items(extracted.entities, extracted.relations):
        for kind in ("edge_signature", "temporal_edge"):
            preimages.append(
                {
                    "episode_key": episode_key,
                    "kind": kind,
                    "subject": relation.source_name,
                    "predicate": relation.relation_type,
                    "object": relation.target_name,
                }
            )
    return {hashlib.sha256(canonical_expectation(preimage)).hexdigest() for preimage in preimages}


def _fixture_trace_categories(
    episode_key: str,
    expectations: list[dict[str, Any]],
    extracted: Any,
    tracker: Any,
    graph: dict[str, list[dict[str, Any]]],
) -> dict[str, int]:
    categories: dict[str, int] = {}

    def record(category: str) -> None:
        categories[category] = categories.get(category, 0) + 1

    observed = _observed_fact_hashes(episode_key, graph)
    lineage_preserved = _lineage_preserved_fixture_hashes(episode_key, expectations, extracted, tracker, graph)
    nodes = {row["id"]: row for row in graph["nodes"]}
    for expectation in expectations:
        digest = expectation["sha256"]
        preimage = expectation["preimage"]
        if digest in observed or digest in lineage_preserved:
            record("preserved" if digest in observed else "preserved_via_bound_identity")
            continue
        if preimage["kind"] in {"node_fact", "quantitative_update"}:
            owners: list[int] = []
            for index, entity in enumerate(extracted.entities):
                value = entity.properties.get(preimage["predicate"])
                object_value = str(value).lower() if isinstance(value, bool) else str(value)
                candidate = {**preimage, "subject": entity.name, "object": object_value}
                if (
                    preimage["predicate"] in entity.properties
                    and hashlib.sha256(canonical_expectation(candidate)).hexdigest() == digest
                ):
                    owners.append(index)
            if not owners:
                record("not_representable")
                continue
            if not isinstance(tracker, LibrarianTrajectoryTracker):
                record("not_traceable_for_profile")
                continue
            index = owners[0]
            state = tracker.entity_states.get(index)
            if state in {"pending", "unresolved"}:
                record(f"entity_{state}")
                continue
            bound_id = tracker.bound_node_ids.get(index)
            if bound_id is None:
                record("terminal_entity_without_bound_node")
                continue
            node = nodes.get(bound_id)
            if node is None:
                record("bound_node_missing")
                continue
            if node["name"] != preimage["subject"]:
                record("canonical_subject_changed")
            elif preimage["predicate"] not in node["properties"]:
                record("mutation_property_omitted")
            else:
                value = node["properties"][preimage["predicate"]]
                object_value = str(value).lower() if isinstance(value, bool) else str(value)
                record(
                    "mutation_property_changed" if object_value != preimage["object"] else "post_graph_hash_mismatch"
                )
        elif digest in _extractable_fact_hashes(episode_key, extracted):
            record("relation_post_graph_missing")
        else:
            record("not_representable")
    return dict(sorted(categories.items()))


def _lineage_preserved_fixture_hashes(
    episode_key: str,
    expectations: list[dict[str, Any]],
    extracted: Any,
    tracker: Any,
    graph: dict[str, list[dict[str, Any]]],
) -> set[str]:
    if not isinstance(tracker, LibrarianTrajectoryTracker):
        return set()
    nodes = {row["id"]: row for row in graph["nodes"]}
    edge_types = {row["id"]: row["name"] for row in graph["edge_types"]}
    relations = build_librarian_relation_items(extracted.entities, extracted.relations)
    preserved: set[str] = set()

    def endpoint_id(name: str) -> int | None:
        for index, entity in enumerate(extracted.entities):
            if entity.name.casefold() == name.casefold():
                return tracker.bound_node_ids.get(index)
        return None

    for expectation in expectations:
        preimage = expectation["preimage"]
        digest = expectation["sha256"]
        if preimage["kind"] in {"node_fact", "quantitative_update"}:
            for index, entity in enumerate(extracted.entities):
                value = entity.properties.get(preimage["predicate"])
                object_value = str(value).lower() if isinstance(value, bool) else str(value)
                candidate = {**preimage, "subject": entity.name, "object": object_value}
                if (
                    preimage["predicate"] in entity.properties
                    and hashlib.sha256(canonical_expectation(candidate)).hexdigest() == digest
                ):
                    node = nodes.get(tracker.bound_node_ids.get(index))
                    if node is not None and preimage["predicate"] in node["properties"]:
                        observed_value = node["properties"][preimage["predicate"]]
                        normalized = (
                            str(observed_value).lower() if isinstance(observed_value, bool) else str(observed_value)
                        )
                        if normalized == preimage["object"]:
                            preserved.add(digest)
        else:
            for relation in relations:
                candidate = {
                    "episode_key": episode_key,
                    "kind": preimage["kind"],
                    "subject": relation.source_name,
                    "predicate": relation.relation_type,
                    "object": relation.target_name,
                }
                if hashlib.sha256(canonical_expectation(candidate)).hexdigest() != digest:
                    continue
                source_id, target_id = endpoint_id(relation.source_name), endpoint_id(relation.target_name)
                if source_id is None or target_id is None:
                    continue
                if any(
                    edge["source_id"] == source_id
                    and edge["target_id"] == target_id
                    and edge_types.get(edge["type_id"]) == relation.relation_type
                    for edge in graph["edges"]
                ):
                    preserved.add(digest)
    return preserved


def _bounded_prompt(entity_count: int, relation_count: int, *, idempotence: bool = False) -> str:
    verb = "Reconcile" if idempotence else "Curate"
    return (
        f"{verb} all fixed indexed inputs: {entity_count} entities and {relation_count} relations. "
        "Use only the registered phase tools. Process entity indices in ascending micro-batches of at most 8: resolve "
        "one batch, request details only where detail_required=true, then immediately decide every index using only "
        "its code-owned allowed_decisions before resolving the next batch. Once every entity is terminal, process "
        "relation "
        "indices in ascending micro-batches of at most 8: check one batch and immediately decide it using only its "
        "allowed_decisions. Return the structured terminal status only after every index is terminal."
    )


async def _run_arm(
    arm: str,
    profile: LibrarianProfile,
    episode_key: str,
    repeat: int,
    text: str,
    repo: GraphServiceAdapter,
    agent_id: str,
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
    primary_usage = RunUsage()
    usage = _usage_snapshot(primary_usage)
    tool_names: list[str] = []
    retries = 0
    terminal_output_calls = 0
    failure_stage: str | None = None
    failure_reason: str | None = None
    result: Any = None
    primary_messages: list[Any] = []
    try:
        failure_stage = "agent_run"
        agent = build_librarian_agent(config, use_tools=True, profile=profile)
        with capture_run_messages() as primary_messages:
            result = await asyncio.wait_for(
                agent.run(
                    (
                        _bounded_prompt(len(extracted.entities), len(relation_items))
                        if arm == "A2"
                        else "Curate all fixed indexed inputs."
                    ),
                    deps=LibrarianAgentDeps(
                        episode_text=text,
                        node_types=[x.name for x in await repo.get_node_types(agent_id, target_schema=target_schema)],
                        edge_types=[x.name for x in await repo.get_edge_types(agent_id, target_schema=target_schema)],
                        extracted_entities=extracted.entities,
                        extracted_relations=relation_items,
                        repo=repo,
                        embeddings=embeddings,
                        agent_id=agent_id,
                        target_schema=target_schema,
                        episode_id=repeat,
                        action_tracker=tracker,
                    ),
                    model_settings=config.model_settings,
                    usage=primary_usage,
                ),
                timeout=timeout,
            )
        usage = _usage_snapshot(primary_usage)
        counters = _message_counters(primary_messages, getattr(result, "_output_tool_name", None))
        tool_names = counters["tool_names"]
        retries = counters["validation_rejections"]
        terminal_output_calls = counters["terminal_output_calls"]
        failure_stage = "tracker_report"
        report = tracker.build_report() if isinstance(tracker, LibrarianTrajectoryTracker) else None
        status = report.status if report else "completed"
        completed = True
        failure_stage = None
        private["messages"] = [str(message) for message in result.all_messages()]
    except Exception as exc:
        usage = _usage_snapshot(primary_usage)
        counters = _message_counters(primary_messages, getattr(result, "_output_tool_name", None))
        tool_names = counters["tool_names"]
        retries = counters["validation_rejections"]
        terminal_output_calls = counters["terminal_output_calls"]
        status = "timeout" if isinstance(exc, TimeoutError) else "failed"
        failure_reason = _failure_reason(exc)
        private["error_type"] = type(exc).__name__
        private["messages"] = [str(message) for message in primary_messages]

    idempotence_status: str = "NOT_RUN"
    idempotence_failure_reason: str | None = None
    idempotence_usage = RunUsage()
    idempotence_messages: list[Any] = []
    if arm == "A2" and completed:
        rerun_tracker = LibrarianTrajectoryTracker(entities=extracted.entities, relations=relation_items, budget=budget)
        try:
            with capture_run_messages() as idempotence_messages:
                rerun_result = await asyncio.wait_for(
                    build_librarian_agent(config, use_tools=True, profile="qwen_bounded").run(
                        _bounded_prompt(len(extracted.entities), len(relation_items), idempotence=True),
                        deps=LibrarianAgentDeps(
                            episode_text=text,
                            node_types=[
                                x.name for x in await repo.get_node_types(agent_id, target_schema=target_schema)
                            ],
                            edge_types=[
                                x.name for x in await repo.get_edge_types(agent_id, target_schema=target_schema)
                            ],
                            extracted_entities=extracted.entities,
                            extracted_relations=relation_items,
                            repo=repo,
                            embeddings=embeddings,
                            agent_id=agent_id,
                            target_schema=target_schema,
                            episode_id=repeat,
                            action_tracker=rerun_tracker,
                        ),
                        model_settings=config.model_settings,
                        usage=idempotence_usage,
                    ),
                    timeout=timeout,
                )
            rerun_tracker.build_report()
            idempotence_status = "completed"
            private["idempotence_messages"] = [str(message) for message in rerun_result.all_messages()]
        except Exception as exc:
            idempotence_status = "timeout" if isinstance(exc, TimeoutError) else "failed"
            idempotence_failure_reason = _failure_reason(exc)
            private["idempotence_error_type"] = type(exc).__name__
            private["idempotence_messages"] = [str(message) for message in idempotence_messages]

    graph = await _observe_graph(pool, target_schema)
    nodes = {row["id"]: row for row in graph["nodes"]}
    edges = {row["id"]: row for row in graph["edges"]}
    node_type_ids = {row["id"] for row in graph["node_types"]}
    edge_type_ids = {row["id"] for row in graph["edge_types"]}
    assertion_failures = {
        "dangling_edge": sum(
            edge["source_id"] not in nodes or edge["target_id"] not in nodes for edge in edges.values()
        ),
        "invalid_node_type": sum(node["type_id"] not in node_type_ids for node in nodes.values()),
        "invalid_edge_type": sum(edge["type_id"] not in edge_type_ids for edge in edges.values()),
        "missing_node_source_episode": sum(
            (node.get("properties") or {}).get("_source_episode") != repeat for node in nodes.values()
        ),
        "missing_edge_source_episode": sum(
            (edge.get("properties") or {}).get("_source_episode") != repeat for edge in edges.values()
        ),
    }
    canonical_nodes = {(node["name"].casefold(), node["type_id"]) for node in nodes.values()}
    canonical_edges = {(edge["source_id"], edge["target_id"], edge["type_id"]) for edge in edges.values()}
    idempotence_duplicate_count += len(nodes) - len(canonical_nodes) + len(edges) - len(canonical_edges)
    if isinstance(tracker, LibrarianTrajectoryTracker):
        assertion_failures["missing_successful_node"] = sum(
            node_id not in nodes for node_id in tracker.successful_node_ids
        )
        successful_edge_mismatch = 0
        for edge_id, signature in tracker.successful_edge_signatures.items():
            edge = edges.get(edge_id)
            if edge is None or (edge["source_id"], edge["target_id"], edge["type_id"]) != signature:
                successful_edge_mismatch += 1
        assertion_failures["successful_edge_mismatch"] = successful_edge_mismatch
        assertion_failures["removed_edge_retained"] = sum(edge_id in edges for edge_id in tracker.removed_edge_ids)
        assertion_failures["idempotence_incomplete"] = int(idempotence_status != "completed")

    fixture_episode = next(row for row in validate_fixture()["episodes"] if row["episode_key"] == episode_key)
    expected_hashes = {row["sha256"] for row in fixture_episode["expectations"]}
    extractable_hashes = _extractable_fact_hashes(episode_key, extracted)
    representable_hashes = expected_hashes & extractable_hashes
    unrepresentable_hashes = expected_hashes - representable_hashes
    observed_hashes = _observed_fact_hashes(episode_key, graph)
    lineage_hashes = _lineage_preserved_fixture_hashes(
        episode_key, fixture_episode["expectations"], extracted, tracker, graph
    )
    matched_hashes = representable_hashes & (observed_hashes | lineage_hashes)
    assertion_failures["missing_representable_fixture"] = len(representable_hashes - matched_hashes)
    unknown_tools = sum(name not in SAFE_TOOL_NAMES for name in tool_names)
    assertion_failures["unknown_executable_tool"] = unknown_tools
    failures = sum(assertion_failures.values())
    graph_hash = _graph_digest(graph)
    mutation_attempts, mutation_successes = _mutation_counts(tracker)
    row = {
        "run_id": uuid.uuid4().hex,
        "arm": arm,
        "episode_key": episode_key,
        "repeat": repeat,
        "status": status,
        "failure_stage": failure_stage,
        "failure_reason": failure_reason,
        "elapsed_seconds": round(time.monotonic() - started, 4),
        **usage,
        "tool_counts": _safe_tool_counts(tool_names),
        "terminal_output_calls": terminal_output_calls,
        "read_count": getattr(tracker, "repository_item_reads", "NOT_MEASURED"),
        "mutation_attempts": mutation_attempts,
        "mutation_successes": mutation_successes,
        "duplicate_calls": getattr(tracker, "duplicate_calls", 0),
        "max_read_streak": getattr(tracker, "max_read_streak", 0),
        "validation_rejections": getattr(tracker, "validation_rejections", retries),
        "host_normalization_count": getattr(tracker, "host_normalization_count", "NOT_MEASURED"),
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
        "assertion_failure_counts": dict(sorted(assertion_failures.items())),
        "outcome_assertions_failed": failures,
        "unknown_tool_calls": unknown_tools,
        "idempotence_duplicate_count": idempotence_duplicate_count,
        "idempotence_status": idempotence_status if arm == "A2" else "NOT_MEASURED",
        "idempotence_failure_reason": idempotence_failure_reason,
        "idempotence_usage": _usage_snapshot(idempotence_usage),
        "idempotence_host_normalization_count": getattr(
            rerun_tracker if arm == "A2" and completed else None, "host_normalization_count", "NOT_MEASURED"
        ),
        "fixture_assertion_status": "NOT_MEASURED" if unrepresentable_hashes else "MEASURED",
        "fixture_expectation_count": len(expected_hashes),
        "fixture_representable_count": len(representable_hashes),
        "fixture_unrepresentable_hashes": sorted(unrepresentable_hashes),
        "fixture_trace_categories": _fixture_trace_categories(
            episode_key, fixture_episode["expectations"], extracted, tracker, graph
        ),
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
    parser.add_argument("--extraction-timeout", type=float)
    parser.add_argument("--embedding-model", required=True)
    parser.add_argument("--embedding-endpoint-id", required=True)
    parser.add_argument("--embedding-revision", default=os.environ.get("NEOCORTEX_EMBEDDING_REVISION"))
    parser.add_argument(
        "--embedding-api-key-env",
        default=os.environ.get("NEOCORTEX_EMBEDDING_API_KEY_ENV", "GOOGLE_API_KEY"),
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--safe-summary", required=True, type=Path)
    parser.add_argument("--frozen-cache", type=Path)
    parser.add_argument("--repeats", type=int, choices=(1, 3), default=1)
    parser.add_argument("--arms", nargs="+", choices=[arm for arm, _profile in PROFILES])
    parser.add_argument("--episodes", nargs="+", choices=("E04", "E05"))
    args = parser.parse_args()
    if args.output.resolve() == ROOT or ROOT in args.output.resolve().parents:
        parser.error("private --output must be outside the repository")
    if args.frozen_cache and (args.frozen_cache.resolve() == ROOT or ROOT in args.frozen_cache.resolve().parents):
        parser.error("private --frozen-cache must be outside the repository")
    validate_fixture()
    selected_profiles = _selected_profiles(set(args.arms) if args.arms else None)
    episodes = select_probe_episodes(set(args.episodes) if args.episodes else None)
    complete_matrix = _is_complete_matrix(selected_profiles, episodes)
    selected_episode_keys = [f"E{int(str(row['number'])):02d}" for row in episodes]
    extraction_timeout = args.extraction_timeout or args.timeout
    if extraction_timeout <= 0:
        parser.error("--extraction-timeout must be positive")
    cache_expected = _cache_provenance(
        model=args.model,
        effort=args.effort,
        temperature=args.temperature,
        top_p=args.top_p,
        episode_keys=selected_episode_keys,
    )
    endpoint = os.environ.get("NEOCORTEX_LOCAL_MODEL_BASE_URL")
    api_key_env = os.environ.get("NEOCORTEX_LOCAL_MODEL_API_KEY_ENV", "VLLM_API_KEY")
    if not endpoint or not os.environ.get(api_key_env):
        parser.error("configured local endpoint and its API key environment are required")
    try:
        embedding_api_key_env = _configure_embedding_api_key(args.embedding_api_key_env)
    except ValueError as exc:
        parser.error(str(exc))
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
    permissions = services["permissions"]
    if (
        not isinstance(repo, GraphServiceAdapter)
        or pg is None
        or schema_mgr is None
        or embeddings is None
        or permissions is None
    ):
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
    cache_provenance: dict[str, Any] | None = None
    cache_status = "disabled"
    pre_state_hashes: dict[str, list[str]] = {}
    clean_pre_states = True
    probe_agent = f"probe{uuid.uuid4().hex[:12]}"
    try:
        if args.frozen_cache and args.frozen_cache.exists():
            frozen, cache_provenance = _read_frozen_cache(args.frozen_cache, cache_expected)
            cache_status = "reused"
        else:
            for episode in episodes:
                key = f"E{int(str(episode['number'])):02d}"
                schema = await _create_probe_graph(
                    schema_mgr,
                    permissions,
                    probe_agent,
                    f"extract{key.lower()}",
                    settings.bootstrap_admin_id,
                    created_schemas,
                )
                frozen[key] = await _extract_once(
                    str(episode["text"]), config, repo, probe_agent, schema, extraction_timeout
                )
            if args.frozen_cache:
                _write_frozen_cache(args.frozen_cache, frozen, cache_expected)
                frozen, cache_provenance = _read_frozen_cache(args.frozen_cache, cache_expected)
                cache_status = "created"
        for repeat in range(1, args.repeats + 1):
            for arm, profile in selected_profiles:
                for episode in episodes:
                    key = f"E{int(str(episode['number'])):02d}"
                    extracted, node_types, edge_types = frozen[key]
                    schema = await _create_probe_graph(
                        schema_mgr,
                        permissions,
                        probe_agent,
                        f"{arm.lower()}{key.lower()}r{repeat}",
                        settings.bootstrap_admin_id,
                        created_schemas,
                    )
                    await _seed_types(repo, probe_agent, schema, node_types, edge_types)
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
                        probe_agent,
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
    expected_prestate_groups = len(selected_profiles) * args.repeats
    graph_isolation = (
        len(created_schemas) == len(set(created_schemas))
        and clean_pre_states
        and set(pre_state_hashes) == set(selected_episode_keys)
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
        "extraction_timeout": extraction_timeout,
        "embedding_model": args.embedding_model,
        "embedding_endpoint_id": _endpoint_identity(args.embedding_endpoint_id),
        "embedding_revision": args.embedding_revision or "NOT_MEASURED",
        "embedding_api_key_env": embedding_api_key_env,
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
        "episode_keys": selected_episode_keys,
        "profiles": [profile for _arm, profile in selected_profiles],
        "arms": [arm for arm, _profile in selected_profiles],
        "matrix_complete": complete_matrix,
        "parallel_tool_calls": False,
        "budget": vars(budget),
        "pydantic_ai_version": pydantic_ai.__version__,
        "frozen_extraction_cache": (
            {"status": cache_status, **_safe_cache_summary(args.frozen_cache, cache_provenance, frozen)}
            if args.frozen_cache and cache_provenance is not None
            else {"status": "disabled"}
        ),
    }
    gate = evaluate_material_improvement(rows)
    gate = _apply_gate_eligibility(gate, rows, controls, complete_matrix)
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
