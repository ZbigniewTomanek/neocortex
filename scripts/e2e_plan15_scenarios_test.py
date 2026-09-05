"""E2E replay of Plan 15's 14 scenarios against the tool-equipped librarian pipeline.

Validates Plan 16 Stage 3.5: the tool-driven extraction pipeline produces correct
graph state for the real-world scenarios that exposed quality issues in Plan 15.

Pass criteria: >= 11/14 scenarios PASS (79%); PARTIAL is informational only.

Each scenario:
  1. Ingests 1-2 episodes with known content
  2. Waits for extraction to complete
  3. Queries graph state via DB + recall
  4. Records PASS / PARTIAL / FAIL

Prerequisites:
  docker compose up -d postgres
  GOOGLE_API_KEY=... NEOCORTEX_AUTH_MODE=dev_token \
    NEOCORTEX_DEV_TOKENS_FILE=dev_tokens.json \
    NEOCORTEX_MOCK_DB=false uv run python -m neocortex &
  GOOGLE_API_KEY=... NEOCORTEX_AUTH_MODE=dev_token \
    NEOCORTEX_DEV_TOKENS_FILE=dev_tokens.json \
    NEOCORTEX_MOCK_DB=false uv run python -m neocortex.ingestion &

Usage:
  GOOGLE_API_KEY=... uv run python scripts/e2e_plan15_scenarios_test.py

Via unified runner:
  GOOGLE_API_KEY=... ./scripts/run_e2e.sh scripts/e2e_plan15_scenarios_test.py
"""

from __future__ import annotations

import asyncio
import itertools
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import cast

import asyncpg
import httpx
from fastmcp import Client

from neocortex.config import PostgresConfig

try:
    from scripts.e2e_result import write_configured_result  # ty: ignore[unresolved-import]
except ModuleNotFoundError:  # Direct ``python scripts/e2e_plan15_scenarios_test.py`` execution.
    from e2e_result import write_configured_result  # ty: ignore[unresolved-import]

BASE_URL = os.environ.get("NEOCORTEX_BASE_URL", "http://127.0.0.1:8000")
INGESTION_URL = os.environ.get("NEOCORTEX_INGESTION_BASE_URL", "http://127.0.0.1:8001")
MCP_URL = os.environ.get("NEOCORTEX_MCP_URL", f"{BASE_URL}/mcp")
TOKEN = os.environ.get("NEOCORTEX_ALICE_TOKEN", "alice-token")
AGENT_SCHEMA = "ncx_alice__personal"

JOB_WAIT_TIMEOUT = 600  # seconds (10 min for Gemini API rate limits)
JOB_POLL_INTERVAL = 3  # seconds


# ── Scenario verdict ──


class Verdict(Enum):
    PASS = "PASS"
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"


@dataclass
class ScenarioResult:
    name: str
    verdict: Verdict = Verdict.FAIL
    notes: list[str] = field(default_factory=list)


def build_result_payload(results: list[ScenarioResult], child_run_id: str) -> dict[str, object]:
    """Build the safe result while keeping PARTIAL informational only."""
    pass_count = sum(1 for result in results if result.verdict == Verdict.PASS)
    partial_count = sum(1 for result in results if result.verdict == Verdict.PARTIAL)
    fail_count = sum(1 for result in results if result.verdict == Verdict.FAIL)
    acceptable = pass_count + partial_count
    gate_passed = pass_count >= 11
    return {
        "schema_version": 1,
        "kind": "neocortex-e2e-scenario-result",
        "script": "e2e_plan15_scenarios_test.py",
        "child_run_id": child_run_id,
        "status": "PASS" if gate_passed else "FAIL",
        "exit_code": 0 if gate_passed else 1,
        "counts": {
            "total": len(results),
            "pass": pass_count,
            "partial": partial_count,
            "acceptable": acceptable,
            "fail": fail_count,
        },
        "gate": {"basis": "PASS", "threshold": 11, "passed": gate_passed},
        "scenarios": [{"index": index, "verdict": result.verdict.value} for index, result in enumerate(results, 1)],
    }


# ── Seed texts ──

# S1: Basic recall
S1_TEXT = (
    "Phoenix Framework is a web framework written in Elixir. "
    "It uses channels for real-time communication and LiveView "
    "for server-rendered interactive user interfaces."
)

# S2: Fact update (person's team changes)
S2_INITIAL = (
    "Diana Rivera works on the billing team as a senior engineer. "
    "She specializes in payment processing and invoice generation. "
    "Diana has been with the billing team for three years."
)
S2_UPDATE = (
    "Diana Rivera transferred to the auth team as tech lead. "
    "She now leads the authentication and authorization platform, "
    "focusing on OAuth2 integration and session management. "
    "Diana moved from billing to auth last month."
)

# S3: Entity dedup (same entity across episodes)
S3_EPISODE_A = (
    "Kubernetes is a container orchestration platform originally "
    "developed by Google. It manages containerized applications "
    "across clusters of machines."
)
S3_EPISODE_B = (
    "Kubernetes supports auto-scaling and load balancing. "
    "It uses pods as the smallest deployable units and services "
    "for network abstraction."
)

# S4: Edge accumulation (Diana's team edges — tested via S2 data)
# Uses S2_INITIAL + S2_UPDATE; verification checks edge state.

# S5: Deadline contradiction
S5_INITIAL = "The Project Zenith deadline is April 15, 2026. The team is targeting a beta release by that date."
S5_UPDATE = (
    "The Project Zenith deadline has been pushed back from "
    "April 15 to May 1, 2026 due to the merge freeze. "
    "The April 15 deadline is no longer valid."
)

# S6: Explicit correction
S6_INITIAL = "Marcus Chen is a backend developer who primarily uses Java for microservices development at the company."
S6_CORRECTION = (
    "CORRECTION: Marcus Chen actually uses Rust, not Java. "
    "He switched to Rust six months ago for memory safety "
    "guarantees in the payment service."
)

# S7: Preference reversal
S7_INITIAL = "The infrastructure team decided to use Redis as the primary cache layer for the API gateway."
S7_REVERSAL = (
    "The infrastructure team reversed the Redis decision and "
    "will use Memcached instead, because of simpler operational "
    "model and lower memory overhead for their use case."
)

# S8: Property accumulation
S8_EPISODE_A = "The BERT NLP model achieved 92.4 percent accuracy on the entity matching task in the Plan 42 benchmark."
S8_EPISODE_B = (
    "The BERT NLP model has 15ms average inference latency on a V100 GPU, making it suitable for real-time scoring."
)

# S9: Property conflict
S9_INITIAL = "The data ingestion pipeline has 4 stages: extraction, cleaning, validation, and loading."
S9_UPDATE = (
    "The data ingestion pipeline has been extended to 6 stages: "
    "extraction, cleaning, normalization, dedup, validation, "
    "and loading. The old 4-stage design is replaced."
)

# S10: Complex domain queries
S10_TEXT = (
    "Entity Resolution is the process of determining whether "
    "different data records refer to the same real-world entity. "
    "Our ER engine uses a multi-stage pipeline: normalization, "
    "feature extraction, blocking, pruning, scoring, evaluation. "
    "Blocking is the most critical stage for scalability — it "
    "generates candidate pairs using Metaphone3 phonetic encoding "
    "for name matching. The key metric is pairs-per-entity."
)

# S11: Fact supersession
S11_INITIAL = "The Plan 42 benchmark showed a scaling exponent of b=0.57, fitted from 1M and 5M data points."
S11_UPDATE = (
    "UPDATE: After running the 10M benchmark, the Plan 42 "
    "scaling exponent was refined to b=0.62. The previous "
    "b=0.57 value is outdated and should not be used."
)

# S12: Importance effect
S12_HIGH = (
    "CRITICAL: Production API keys for the Zenith service must "
    "be rotated before April 5, 2026. This is a P0 security "
    "requirement with compliance implications."
)
S12_LOW = "The office printer on floor 3 needs new toner cartridges."

# S13: Recency effect — tested via S5 (newer deadline should rank higher)

# S14: Activation (access count) — tested via repeated recalls


# ── Helpers ──


async def mcp_call(tool_name: str, arguments: dict[str, object]) -> dict:
    async with Client(MCP_URL, auth=TOKEN) as client:
        result = await client.call_tool(tool_name, arguments)
    if not isinstance(result.structured_content, dict):
        raise AssertionError(f"{tool_name} did not return structured content: {result}")
    return result.structured_content


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


async def _assert_health() -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{BASE_URL}/health")
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != "ok":
        raise AssertionError(f"Unexpected health payload: {payload}")


async def _get_max_job_id() -> int:
    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        val = await conn.fetchval("SELECT coalesce(max(id), 0) FROM procrastinate_jobs WHERE queue_name = 'extraction'")
        return int(val)
    finally:
        await conn.close()


async def _wait_for_extraction(baseline_job_id: int, label: str) -> None:
    """Poll until all extraction jobs created after baseline complete."""
    print(f"\n  Waiting for extraction jobs ({label}, timeout {JOB_WAIT_TIMEOUT}s)...")
    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        start = time.monotonic()
        while time.monotonic() - start < JOB_WAIT_TIMEOUT:
            row = await conn.fetchrow(
                """SELECT
                    count(*) FILTER (WHERE status = 'todo') AS pending,
                    count(*) FILTER (WHERE status = 'doing') AS running,
                    count(*) FILTER (WHERE status = 'succeeded') AS completed,
                    count(*) FILTER (WHERE status = 'failed') AS failed
                FROM procrastinate_jobs
                WHERE queue_name = 'extraction' AND id > $1""",
                baseline_job_id,
            )
            pending = int(row["pending"])
            running = int(row["running"])
            completed = int(row["completed"])
            failed = int(row["failed"])

            # Also check routing jobs
            route_row = await conn.fetchrow(
                """SELECT
                    count(*) FILTER (WHERE status IN ('todo', 'doing')) AS active
                FROM procrastinate_jobs
                WHERE task_name IN ('route_episode', 'extract_episode')
                  AND id > $1
                  AND status IN ('todo', 'doing')""",
                baseline_job_id,
            )
            route_active = int(route_row["active"])

            elapsed = int(time.monotonic() - start)
            print(
                f"    [{elapsed:3d}s] pending={pending} running={running} "
                f"completed={completed} failed={failed} routing={route_active}"
            )
            if pending == 0 and running == 0 and route_active == 0:
                if completed > 0:
                    print(f"    [OK] Extraction done ({completed} completed, {failed} failed)")
                    return
                if completed == 0 and failed == 0:
                    await asyncio.sleep(JOB_POLL_INTERVAL)
                    continue
                if failed > 0 and completed == 0:
                    print(f"    [WARN] All {failed} jobs failed")
                    return
            await asyncio.sleep(JOB_POLL_INTERVAL)

        raise AssertionError(f"Extraction jobs did not complete within {JOB_WAIT_TIMEOUT}s")
    finally:
        await conn.close()


async def _find_nodes_by_name(name_pattern: str) -> list[dict]:
    """Query DB for nodes matching a case-insensitive pattern."""
    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        schema = _quote(AGENT_SCHEMA)
        rows = await conn.fetch(
            f"""SELECT n.name, n.content, nt.name AS type_name,
                       n.importance, n.forgotten, n.id
                FROM {schema}.node n
                JOIN {schema}.node_type nt ON nt.id = n.type_id
                WHERE lower(n.name) LIKE $1
                  AND n.forgotten = false
                ORDER BY n.name""",
            f"%{name_pattern.lower()}%",
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def _find_edges_for_node(node_name_pattern: str) -> list[dict]:
    """Query DB for edges involving a node matching the pattern."""
    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        schema = _quote(AGENT_SCHEMA)
        rows = await conn.fetch(
            f"""SELECT src.name AS source, tgt.name AS target,
                       et.name AS edge_type, e.weight
                FROM {schema}.edge e
                JOIN {schema}.node src ON e.source_id = src.id
                JOIN {schema}.node tgt ON e.target_id = tgt.id
                JOIN {schema}.edge_type et ON e.type_id = et.id
                WHERE lower(src.name) LIKE $1
                   OR lower(tgt.name) LIKE $1
                ORDER BY e.weight DESC""",
            f"%{node_name_pattern.lower()}%",
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def _get_duplicate_nodes() -> list[dict]:
    """Q3: Find duplicate node names."""
    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        schema = _quote(AGENT_SCHEMA)
        rows = await conn.fetch(f"""SELECT lower(n.name) AS name, COUNT(*) AS count,
                       array_agg(nt.name ORDER BY n.id) AS types
                FROM {schema}.node n
                JOIN {schema}.node_type nt ON n.type_id = nt.id
                WHERE n.forgotten = false
                GROUP BY lower(n.name)
                HAVING COUNT(*) > 1
                ORDER BY count DESC""")
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def _recall(query: str, limit: int = 10) -> list[dict]:
    """Call MCP recall and return results list."""
    result = await mcp_call("recall", {"query": query, "limit": limit})
    return result.get("results", [])


# ── Scenario Implementations ──


async def scenario_01_basic_recall() -> ScenarioResult:
    """S1: Basic recall — store and retrieve a fact."""
    r = ScenarioResult("S01: Basic recall")

    results = await _recall("Phoenix Framework Elixir web")
    found = any(
        "phoenix" in str(x.get("content", "")).lower() or "phoenix" in str(x.get("name", "")).lower() for x in results
    )
    if found:
        r.verdict = Verdict.PASS
        r.notes.append("Phoenix Framework found in recall results")
    else:
        # Check if it's in the graph at all
        nodes = await _find_nodes_by_name("phoenix")
        if nodes:
            r.verdict = Verdict.PARTIAL
            r.notes.append(f"Phoenix node exists in DB ({len(nodes)}) but not in recall top-10")
        else:
            r.verdict = Verdict.FAIL
            r.notes.append("Phoenix Framework not found in recall or DB")
    return r


async def scenario_02_fact_update() -> ScenarioResult:
    """S2: Fact update — Diana's team changes from billing to auth."""
    r = ScenarioResult("S02: Fact update (content)")

    nodes = await _find_nodes_by_name("diana")
    if not nodes:
        r.verdict = Verdict.FAIL
        r.notes.append("No Diana node found in DB")
        return r

    # Check content reflects auth team
    auth_found = False
    billing_only = False
    for node in nodes:
        content = str(node.get("content", "")).lower()
        r.notes.append(f"  node='{node['name']}' content='{content[:120]}'")
        if "auth" in content or "oauth" in content or "authentication" in content:
            auth_found = True
        if "billing" in content and "auth" not in content:
            billing_only = True

    if auth_found:
        r.verdict = Verdict.PASS
        r.notes.append("Content updated: auth team reflected")
    elif billing_only:
        r.verdict = Verdict.FAIL
        r.notes.append("Content still says billing only — content update failed")
    else:
        # Content might be generic; check recall
        results = await _recall("Diana Rivera team")
        auth_in_recall = any("auth" in str(x.get("content", "")).lower() for x in results)
        r.verdict = Verdict.PARTIAL if auth_in_recall else Verdict.FAIL
        r.notes.append(f"Auth in recall: {auth_in_recall}")
    return r


async def scenario_03_entity_dedup() -> ScenarioResult:
    """S3: Entity dedup — Kubernetes mentioned in 2 episodes → 1 node."""
    r = ScenarioResult("S03: Entity dedup")

    nodes = await _find_nodes_by_name("kubernetes")
    exact = [n for n in nodes if n["name"].lower().strip() == "kubernetes"]
    r.notes.append(f"Kubernetes nodes: {len(exact)} exact, {len(nodes)} total")

    if len(exact) == 1:
        r.verdict = Verdict.PASS
        r.notes.append("Single Kubernetes node — dedup works")
    elif len(exact) == 0:
        # LLM might have used a different name
        if nodes:
            r.verdict = Verdict.PARTIAL
            r.notes.append(f"No exact 'Kubernetes' but found related: {[n['name'] for n in nodes]}")
        else:
            r.verdict = Verdict.FAIL
            r.notes.append("No Kubernetes-related nodes found")
    else:
        types = [n["type_name"] for n in exact]
        r.verdict = Verdict.FAIL
        r.notes.append(f"Duplicate Kubernetes nodes with types: {types}")
    return r


async def scenario_04_edge_accumulation() -> ScenarioResult:
    """S4: Edge accumulation — Diana's team edges should reflect current state."""
    r = ScenarioResult("S04: Edge accumulation")

    edges = await _find_edges_for_node("diana")
    if not edges:
        r.verdict = Verdict.FAIL
        r.notes.append("No edges found for Diana")
        return r

    # Look for team-related edges
    auth_edges = []
    billing_edges = []
    for e in edges:
        edge_str = f"{e['source']} --{e['edge_type']}--> {e['target']}"
        target_lower = str(e.get("target", "")).lower()
        source_lower = str(e.get("source", "")).lower()
        combined = f"{target_lower} {source_lower} {str(e.get('edge_type', '')).lower()}"
        if "auth" in combined:
            auth_edges.append(edge_str)
        if "billing" in combined:
            billing_edges.append(edge_str)

    r.notes.append(f"Auth edges: {auth_edges}")
    r.notes.append(f"Billing edges: {billing_edges}")
    r.notes.append(f"Total Diana edges: {len(edges)}")

    if auth_edges and not billing_edges:
        r.verdict = Verdict.PASS
        r.notes.append("Only auth edges — old billing edges cleaned up")
    elif auth_edges and billing_edges:
        r.verdict = Verdict.PARTIAL
        r.notes.append("Both auth and billing edges coexist")
    elif billing_edges and not auth_edges:
        r.verdict = Verdict.FAIL
        r.notes.append("Only billing edges — update not reflected in edges")
    else:
        # Edges exist but don't mention auth/billing explicitly
        r.verdict = Verdict.PARTIAL
        r.notes.append("Edges exist but team membership not explicit in edge targets")
    return r


async def scenario_05_deadline_contradiction() -> ScenarioResult:
    """S5: Deadline contradiction — Zenith deadline April 15 → May 1."""
    r = ScenarioResult("S05: Deadline contradiction")

    nodes = await _find_nodes_by_name("zenith")
    if not nodes:
        # Try recall
        results = await _recall("Project Zenith deadline")
        may_found = any("may" in str(x.get("content", "")).lower() for x in results)
        if may_found:
            r.verdict = Verdict.PARTIAL
            r.notes.append("Zenith not a node but May deadline in recall")
        else:
            r.verdict = Verdict.FAIL
            r.notes.append("No Zenith node and no May deadline in recall")
        return r

    content_all = " ".join(str(n.get("content", "")).lower() for n in nodes)
    r.notes.append(f"Zenith node content: '{content_all[:200]}'")

    if "may" in content_all:
        if "april" in content_all:
            r.verdict = Verdict.PARTIAL
            r.notes.append("Both April and May mentioned — partial update")
        else:
            r.verdict = Verdict.PASS
            r.notes.append("May 1 reflected, April replaced")
    else:
        r.verdict = Verdict.FAIL
        r.notes.append("May deadline not found in node content")
    return r


async def scenario_06_explicit_correction() -> ScenarioResult:
    """S6: Explicit correction — Marcus uses Rust, not Java."""
    r = ScenarioResult("S06: Explicit correction")

    nodes = await _find_nodes_by_name("marcus")
    if not nodes:
        results = await _recall("Marcus Chen programming language")
        rust_found = any("rust" in str(x.get("content", "")).lower() for x in results)
        if rust_found:
            r.verdict = Verdict.PARTIAL
            r.notes.append("Marcus not a node but Rust in recall")
        else:
            r.verdict = Verdict.FAIL
            r.notes.append("No Marcus node and no Rust in recall")
        return r

    content_all = " ".join(str(n.get("content", "")).lower() for n in nodes)
    r.notes.append(f"Marcus node content: '{content_all[:200]}'")

    if "rust" in content_all:
        if "java" in content_all and "not java" not in content_all:
            r.verdict = Verdict.PARTIAL
            r.notes.append("Both Rust and Java in content")
        else:
            r.verdict = Verdict.PASS
            r.notes.append("Rust reflected, Java corrected")
    else:
        r.verdict = Verdict.FAIL
        r.notes.append("Rust not found in Marcus node content")
    return r


async def scenario_07_preference_reversal() -> ScenarioResult:
    """S7: Preference reversal — Redis → Memcached."""
    r = ScenarioResult("S07: Preference reversal")

    # Check recall ranking: Memcached should rank above Redis for cache query
    results = await _recall("cache layer API gateway decision")

    memcached_rank = None
    redis_rank = None
    for i, res in enumerate(results):
        content = str(res.get("content", "")).lower()
        name = str(res.get("name", "")).lower()
        combined = f"{name} {content}"
        if "memcached" in combined and memcached_rank is None:
            memcached_rank = i
        if "redis" in combined and "memcached" not in combined and redis_rank is None:
            redis_rank = i

    r.notes.append(f"Memcached rank: {memcached_rank}, Redis rank: {redis_rank}")

    if memcached_rank is not None and (redis_rank is None or memcached_rank < redis_rank):
        r.verdict = Verdict.PASS
        r.notes.append("Memcached ranks above Redis — reversal reflected")
    elif memcached_rank is not None and redis_rank is not None:
        r.verdict = Verdict.PARTIAL
        r.notes.append("Both found but Memcached doesn't rank higher")
    elif memcached_rank is None and redis_rank is not None:
        r.verdict = Verdict.FAIL
        r.notes.append("Only Redis found — reversal not reflected")
    else:
        # Neither found — check nodes
        nodes_mc = await _find_nodes_by_name("memcached")
        nodes_re = await _find_nodes_by_name("redis")
        r.notes.append(f"Memcached nodes: {len(nodes_mc)}, Redis nodes: {len(nodes_re)}")
        r.verdict = Verdict.PARTIAL if nodes_mc else Verdict.FAIL
    return r


async def scenario_08_property_accumulation() -> ScenarioResult:
    """S8: Property accumulation — BERT has both accuracy and latency info."""
    r = ScenarioResult("S08: Property accumulation")

    results = await _recall("BERT NLP model performance")
    all_content = " ".join(str(x.get("content", "")).lower() + " " + str(x.get("name", "")).lower() for x in results)

    has_accuracy = "92" in all_content or "accuracy" in all_content
    has_latency = "15ms" in all_content or "15 ms" in all_content or "latency" in all_content

    r.notes.append(f"Accuracy info: {has_accuracy}, Latency info: {has_latency}")

    if has_accuracy and has_latency:
        r.verdict = Verdict.PASS
        r.notes.append("Both accuracy and latency accessible via recall")
    elif has_accuracy or has_latency:
        r.verdict = Verdict.PARTIAL
        r.notes.append("Only one property found")
    else:
        # Check DB directly
        nodes = await _find_nodes_by_name("bert")
        if nodes:
            node_content = " ".join(str(n.get("content", "")).lower() for n in nodes)
            r.notes.append(f"BERT node content: '{node_content[:200]}'")
            r.verdict = Verdict.PARTIAL
            r.notes.append("BERT node exists but properties not in recall top-10")
        else:
            r.verdict = Verdict.FAIL
            r.notes.append("No BERT-related nodes or recall results")
    return r


async def scenario_09_property_conflict() -> ScenarioResult:
    """S9: Property conflict — pipeline stages 4 → 6."""
    r = ScenarioResult("S09: Property conflict")

    # Check for pipeline node content
    nodes = await _find_nodes_by_name("pipeline")
    if not nodes:
        nodes = await _find_nodes_by_name("ingestion")
    if not nodes:
        results = await _recall("data ingestion pipeline stages")
        six_found = any("6" in str(x.get("content", "")) for x in results)
        r.verdict = Verdict.PARTIAL if six_found else Verdict.FAIL
        r.notes.append(f"No pipeline node; 6-stage in recall: {six_found}")
        return r

    content_all = " ".join(str(n.get("content", "")).lower() for n in nodes)
    r.notes.append(f"Pipeline node content: '{content_all[:200]}'")

    # The updated pipeline has 6 stages including normalization and dedup
    has_six = "6" in content_all or "normalization" in content_all or "dedup" in content_all
    has_four_only = "4" in content_all and not has_six

    if has_six:
        r.verdict = Verdict.PASS
        r.notes.append("6-stage pipeline reflected in content")
    elif has_four_only:
        r.verdict = Verdict.FAIL
        r.notes.append("Still shows 4-stage pipeline — conflict not resolved")
    else:
        r.verdict = Verdict.PARTIAL
        r.notes.append("Pipeline node exists but stage count unclear")
    return r


async def scenario_10_complex_domain() -> ScenarioResult:
    """S10: Complex domain queries — ER blocking with graph context."""
    r = ScenarioResult("S10: Complex domain query")

    results = await _recall("entity resolution blocking candidate pairs")

    # Should get rich results with multiple related concepts
    er_content = []
    for res in results:
        content = str(res.get("content", "")).lower()
        name = str(res.get("name", "")).lower()
        if any(
            kw in content or kw in name for kw in ["blocking", "entity resolution", "metaphone", "pairs", "candidate"]
        ):
            er_content.append(res.get("name", "unknown"))

    r.notes.append(f"ER-related results: {er_content}")

    # Check for graph context (neighbors) in results
    has_graph_context = any(res.get("graph_context") for res in results)
    r.notes.append(f"Graph context present: {has_graph_context}")

    if len(er_content) >= 2:
        r.verdict = Verdict.PASS
        r.notes.append(f"Rich ER recall: {len(er_content)} relevant results")
    elif len(er_content) == 1:
        r.verdict = Verdict.PARTIAL
        r.notes.append("Only 1 ER-related result")
    else:
        r.verdict = Verdict.FAIL
        r.notes.append("No ER-related results in recall")
    return r


async def scenario_11_fact_supersession() -> ScenarioResult:
    """S11: Fact supersession — scaling exponent b=0.57 → b=0.62."""
    r = ScenarioResult("S11: Fact supersession")

    results = await _recall("Plan 42 scaling exponent benchmark")

    all_content = " ".join(str(x.get("content", "")) for x in results)

    has_062 = "0.62" in all_content
    has_057 = "0.57" in all_content

    r.notes.append(f"b=0.62 found: {has_062}, b=0.57 found: {has_057}")

    if has_062:
        # Find ranking of each
        rank_062 = None
        rank_057 = None
        for i, res in enumerate(results):
            c = str(res.get("content", ""))
            if "0.62" in c and rank_062 is None:
                rank_062 = i
            if "0.57" in c and "0.62" not in c and rank_057 is None:
                rank_057 = i

        if rank_057 is None or (rank_062 is not None and rank_062 <= rank_057):
            r.verdict = Verdict.PASS
            r.notes.append("Updated exponent 0.62 ranks at or above 0.57")
        else:
            r.verdict = Verdict.PARTIAL
            r.notes.append(f"0.62 at rank {rank_062}, 0.57 at rank {rank_057}")
    else:
        r.verdict = Verdict.FAIL
        r.notes.append("Updated exponent 0.62 not found in recall")
    return r


async def scenario_12_importance_effect() -> ScenarioResult:
    """S12: Importance effect — critical alert (high importance) ranks above trivial fact."""
    r = ScenarioResult("S12: Importance effect")

    results = await _recall("production security keys rotation")

    critical_rank = None
    for i, res in enumerate(results):
        content = str(res.get("content", "")).lower()
        name = str(res.get("name", "")).lower()
        if "api key" in content or "rotate" in content or "zenith" in (content + name):
            critical_rank = i
            break

    r.notes.append(f"Critical alert rank: {critical_rank}")

    if critical_rank is not None and critical_rank < 3:
        r.verdict = Verdict.PASS
        r.notes.append(f"Critical alert found at rank {critical_rank}")
    elif critical_rank is not None:
        r.verdict = Verdict.PARTIAL
        r.notes.append(f"Critical alert found but at rank {critical_rank}")
    else:
        # Check if the node exists with high importance
        nodes = await _find_nodes_by_name("zenith")
        high_imp = [n for n in nodes if n.get("importance", 0) > 0.7]
        if high_imp:
            r.verdict = Verdict.PARTIAL
            r.notes.append("High importance Zenith node exists but not in recall top-10")
        else:
            r.verdict = Verdict.FAIL
            r.notes.append("Critical alert not found")
    return r


async def scenario_13_recency_effect() -> ScenarioResult:
    """S13: Recency effect — newer update episodes rank above older initial episodes."""
    r = ScenarioResult("S13: Recency effect")

    # Use Zenith deadline as test case: update (May) should rank >= initial (April)
    results = await _recall("Project Zenith deadline date")

    may_rank = None
    april_rank = None
    for i, res in enumerate(results):
        content = str(res.get("content", "")).lower()
        if "may" in content and may_rank is None:
            may_rank = i
        if "april" in content and "may" not in content and april_rank is None:
            april_rank = i

    r.notes.append(f"May (newer) rank: {may_rank}, April (older) rank: {april_rank}")

    if may_rank is not None and (april_rank is None or may_rank <= april_rank):
        r.verdict = Verdict.PASS
        r.notes.append("Newer deadline info ranks at or above older")
    elif may_rank is not None and april_rank is not None:
        r.verdict = Verdict.PARTIAL
        r.notes.append("Both found but newer doesn't rank higher")
    else:
        r.verdict = Verdict.PARTIAL
        r.notes.append("Cannot determine recency ranking from available data")
    return r


async def scenario_14_activation() -> ScenarioResult:
    """S14: Activation (access count) — repeated recalls increase score."""
    r = ScenarioResult("S14: Activation (access)")

    # Recall BERT multiple times and track scores
    scores: list[float] = []
    for _i in range(5):
        results = await _recall("BERT NLP model entity matching")
        for res in results:
            name = str(res.get("name", "")).lower()
            content = str(res.get("content", "")).lower()
            if "bert" in name or "bert" in content:
                scores.append(float(res.get("score", 0)))
                break
        else:
            scores.append(0.0)

    r.notes.append(f"Scores over 5 recalls: {[f'{s:.4f}' for s in scores]}")

    non_zero = [s for s in scores if s > 0]
    if len(non_zero) >= 3:
        # Check if scores trend upward
        increases = sum(1 for a, b in itertools.pairwise(non_zero) if b >= a)
        r.notes.append(f"Score increases: {increases}/{len(non_zero) - 1}")
        if increases >= len(non_zero) - 2:  # Allow 1 decrease
            r.verdict = Verdict.PASS
            r.notes.append("Scores trend upward — activation works")
        else:
            r.verdict = Verdict.PARTIAL
            r.notes.append("Scores don't consistently increase")
    elif non_zero:
        r.verdict = Verdict.PARTIAL
        r.notes.append(f"Only {len(non_zero)} non-zero scores out of 5 recalls")
    else:
        r.verdict = Verdict.FAIL
        r.notes.append("BERT not found in any recall")
    return r


# ── Main Test Flow ──


async def main() -> int:
    print("=" * 70)
    print("Plan 15 Scenario Replay (Plan 16 Stage 3.5)")
    print(f"MCP:       {MCP_URL}")
    print(f"Ingestion: {INGESTION_URL}")
    print("Token:     configured")
    print(f"Schema:    {AGENT_SCHEMA}")
    print("=" * 70)

    await _assert_health()

    # ── Phase A: Ingest all initial episodes ──
    print("\n" + "=" * 70)
    print("PHASE A: Ingesting initial episodes")
    print("=" * 70)

    baseline_a = await _get_max_job_id()

    initial_episodes = [
        ("S01-basic", S1_TEXT),
        ("S02-diana-initial", S2_INITIAL),
        ("S03-k8s-a", S3_EPISODE_A),
        ("S03-k8s-b", S3_EPISODE_B),
        ("S05-deadline-initial", S5_INITIAL),
        ("S06-marcus-initial", S6_INITIAL),
        ("S07-cache-initial", S7_INITIAL),
        ("S08-bert-accuracy", S8_EPISODE_A),
        ("S08-bert-latency", S8_EPISODE_B),
        ("S09-pipeline-initial", S9_INITIAL),
        ("S10-er-domain", S10_TEXT),
        ("S11-exponent-initial", S11_INITIAL),
        ("S12-critical", S12_HIGH),
        ("S12-trivial", S12_LOW),
    ]

    for label, text in initial_episodes:
        result = await mcp_call(
            "remember",
            {
                "text": text,
                "context": f"e2e_plan15_{label}",
            },
        )
        eid = result.get("episode_id", "?")
        print(f"  [{label}] episode {eid}: {text[:60]}...")

    # ── Phase B: Wait for initial extraction ──
    print("\n" + "=" * 70)
    print("PHASE B: Waiting for initial extraction to complete")
    print("=" * 70)
    await _wait_for_extraction(baseline_a, "phase-A initial")

    # ── Phase C: Ingest update episodes ──
    print("\n" + "=" * 70)
    print("PHASE C: Ingesting update/correction episodes")
    print("=" * 70)

    baseline_c = await _get_max_job_id()

    update_episodes = [
        ("S02-diana-update", S2_UPDATE),
        ("S05-deadline-update", S5_UPDATE),
        ("S06-marcus-correction", S6_CORRECTION),
        ("S07-cache-reversal", S7_REVERSAL),
        ("S09-pipeline-update", S9_UPDATE),
        ("S11-exponent-update", S11_UPDATE),
    ]

    for label, text in update_episodes:
        result = await mcp_call(
            "remember",
            {
                "text": text,
                "context": f"e2e_plan15_{label}",
            },
        )
        eid = result.get("episode_id", "?")
        print(f"  [{label}] episode {eid}: {text[:60]}...")

    # ── Phase D: Wait for update extraction ──
    print("\n" + "=" * 70)
    print("PHASE D: Waiting for update extraction to complete")
    print("=" * 70)
    await _wait_for_extraction(baseline_c, "phase-C updates")

    # ── Phase E: Run all scenario verifications ──
    print("\n" + "=" * 70)
    print("PHASE E: Verifying all 14 scenarios")
    print("=" * 70)

    scenarios = [
        scenario_01_basic_recall,
        scenario_02_fact_update,
        scenario_03_entity_dedup,
        scenario_04_edge_accumulation,
        scenario_05_deadline_contradiction,
        scenario_06_explicit_correction,
        scenario_07_preference_reversal,
        scenario_08_property_accumulation,
        scenario_09_property_conflict,
        scenario_10_complex_domain,
        scenario_11_fact_supersession,
        scenario_12_importance_effect,
        scenario_13_recency_effect,
        scenario_14_activation,
    ]

    results: list[ScenarioResult] = []
    for scenario_fn in scenarios:
        print(f"\n--- {scenario_fn.__doc__} ---")
        try:
            result = await scenario_fn()
        except Exception as e:
            result = ScenarioResult(name=scenario_fn.__name__, verdict=Verdict.FAIL)
            result.notes.append(f"Exception: {e}")
        results.append(result)
        print(f"  [{result.verdict.value}] {result.name}")
        for note in result.notes:
            print(f"    {note}")

    # ── Summary ──
    print("\n" + "=" * 70)
    print("SCENARIO RESULTS SUMMARY")
    print("=" * 70)

    result_payload = build_result_payload(results, os.environ.get("NEOCORTEX_E2E_RUN_ID", "NOT_MEASURED"))
    result_counts = cast(dict[str, int], result_payload["counts"])
    result_gate = cast(dict[str, object], result_payload["gate"])
    pass_count = int(result_counts["pass"])
    partial_count = int(result_counts["partial"])
    fail_count = int(result_counts["fail"])
    # Keep the broad PASS + PARTIAL total as informational only.  The Plan 15
    # gate is deliberately strict: PARTIAL never contributes to gate passage.
    acceptable = int(result_counts["acceptable"])

    print(f"\n{'#':<4} {'Scenario':<35} {'Verdict':<10}")
    print("-" * 52)
    for i, r in enumerate(results, 1):
        marker = {Verdict.PASS: "+", Verdict.PARTIAL: "~", Verdict.FAIL: "x"}[r.verdict]
        print(f"[{marker}] {i:<2}  {r.name:<35} {r.verdict.value}")

    print(f"\nPASS: {pass_count}  PARTIAL: {partial_count}  FAIL: {fail_count}")
    print(f"Acceptable (PASS only): {pass_count}/14")
    print(f"Acceptable (PASS + PARTIAL): {acceptable}/14")

    gate = 11  # >= 79%
    gate_passed = bool(result_gate["passed"])
    if gate_passed:
        print(f"\n[GATE PASSED] {pass_count}/14 >= {gate}/14 (strict)")
    else:
        print(f"\n[GATE FAILED] {pass_count}/14 < {gate}/14 (strict PASS only)")

    write_configured_result(result_payload)

    # ── Duplicate node report ──
    print("\n--- Duplicate Node Report ---")
    dupes = await _get_duplicate_nodes()
    if dupes:
        for d in dupes:
            print(f"  {d['name']}: {d['count']}x types={d['types']}")
    else:
        print("  No duplicate nodes detected")

    print("\n" + "=" * 70)
    print("PLAN 15 SCENARIO REPLAY COMPLETED")
    print("=" * 70)
    return 0 if gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
