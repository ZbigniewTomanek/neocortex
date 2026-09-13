"""E2E validation for Plan 17: Entity Normalization & Deduplication.

Replays 8 episodes from Plan 17 resources/scenarios.md against a fresh graph,
then scores 14 scenarios to validate normalization improvements.

Target: >=13/14 Acceptable, 0 Fails, no regressions.

Prerequisites:
  docker compose up -d postgres
  GOOGLE_API_KEY=... NEOCORTEX_AUTH_MODE=dev_token \
    NEOCORTEX_DEV_TOKENS_FILE=dev_tokens.json \
    NEOCORTEX_MOCK_DB=false uv run python -m neocortex &
  GOOGLE_API_KEY=... NEOCORTEX_AUTH_MODE=dev_token \
    NEOCORTEX_DEV_TOKENS_FILE=dev_tokens.json \
    NEOCORTEX_MOCK_DB=false uv run python -m neocortex.ingestion &

Usage:
  GOOGLE_API_KEY=... uv run python scripts/e2e_plan17_validation.py
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from enum import Enum

import asyncpg
import httpx
from fastmcp import Client

from neocortex.config import PostgresConfig

try:
    from scripts.e2e_common import JobWaitError, wait_for_jobs, wait_for_ready  # ty: ignore[unresolved-import]
    from scripts.e2e_result import write_configured_result  # ty: ignore[unresolved-import]
except ModuleNotFoundError:  # Direct ``python scripts/e2e_plan17_validation.py`` execution.
    from e2e_common import JobWaitError, wait_for_jobs, wait_for_ready  # ty: ignore[unresolved-import]
    from e2e_result import write_configured_result  # ty: ignore[unresolved-import]

BASE_URL = os.environ.get("NEOCORTEX_BASE_URL", "http://127.0.0.1:8000")
INGESTION_URL = os.environ.get("NEOCORTEX_INGESTION_BASE_URL", "http://127.0.0.1:8001")
MCP_URL = os.environ.get("NEOCORTEX_MCP_URL", f"{BASE_URL}/mcp")
# Use "eve" for a fresh schema to avoid polluting existing data
TOKEN = os.environ.get("NEOCORTEX_EVE_TOKEN", "eve-token")
AGENT_SCHEMA = "ncx_eve__personal"

# ── Verdict ──


class Verdict(Enum):
    ACCEPTABLE = "Acceptable"
    PARTIAL = "Partial"
    FAIL = "FAIL"


@dataclass
class ScenarioResult:
    name: str
    verdict: Verdict = Verdict.FAIL
    notes: list[str] = field(default_factory=list)


# ── Episodes from resources/scenarios.md ──

EP1_TEAM = (
    "Team Atlas is working on Project Nexus, a next-generation data processing platform. "
    "The team consists of Maya Chen (Tech Lead), Jonas Weber (Backend Engineer), "
    "and Sarah Kim (Data Pipeline Specialist). They use DataForge as their primary "
    "data transformation tool. The project launch is targeted for June 2025."
)

EP2_ROLE_CHANGE = (
    "Maya Chen has been promoted from Tech Lead to Engineering Director, effective "
    "immediately. She will continue overseeing Project Nexus but with expanded "
    "responsibilities across the engineering organization."
)

EP3_MIGRATION = (
    "DataForge has completed its migration from Apache Kafka to Apache Pulsar for "
    "event streaming. The migration was driven by Pulsar's superior partition "
    "ordering guarantees and multi-tenancy support."
)

EP4_DEADLINE = (
    "The Project Nexus launch date has been moved from June 2025 to August 1, 2025. "
    "The delay is due to new compliance requirements that must be addressed before "
    "the public release."
)

EP5_REVERSION = (
    "After evaluation, the Pulsar migration has been cancelled. DataForge is reverting "
    "to Apache Kafka for event streaming. The team found that Kafka's ecosystem "
    "maturity outweighed Pulsar's technical advantages."
)

EP6_TEAM_CHANGE = (
    "Jonas Weber has transitioned to the Security team effective this week. "
    "Sarah Kim is replacing him as the primary backend engineer on Project Nexus."
)

EP7_PRECISION = (
    "The NLP model precision for DataForge was previously reported as 87%. "
    "After re-evaluation with the updated test suite, the actual measured "
    "precision is 94.2%, a significant improvement over the initial estimate."
)

EP8_ARCHITECTURE = (
    "DataForge now uses a microservices architecture consisting of: "
    "API Gateway for request routing and rate limiting, "
    "Service Mesh (Istio) for inter-service communication, "
    "Event Bus (Kafka) for async message processing, "
    "Data Lake for long-term storage and analytics."
)


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
    print(f"\n  Waiting for extraction jobs ({label})...")
    try:
        counts = await wait_for_jobs(
            baseline_job_id=baseline_job_id,
            label=label,
            require_routing_idle=True,
        )
    except JobWaitError as exc:
        counts = exc.counts
        if (
            counts.pending == 0
            and counts.running == 0
            and counts.completed == 0
            and counts.failed > 0
            and counts.route_active == 0
        ):
            print(f"    [WARN] All {counts.failed} jobs failed")
            return
        raise
    print(f"    [OK] Extraction done ({counts.completed} completed, {counts.failed} failed)")


async def _schema_exists() -> bool:
    """Check if the agent schema exists."""
    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        val = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name = $1)",
            AGENT_SCHEMA,
        )
        return bool(val)
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


async def _get_all_nodes() -> list[dict]:
    """Get all non-forgotten nodes."""
    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        schema = _quote(AGENT_SCHEMA)
        rows = await conn.fetch(
            f"""SELECT n.name, n.content, nt.name AS type_name,
                       n.importance, n.id
                FROM {schema}.node n
                JOIN {schema}.node_type nt ON nt.id = n.type_id
                WHERE n.forgotten = false
                ORDER BY n.name""",
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def _get_all_edge_types() -> list[dict]:
    """Get all edge types with usage counts."""
    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        schema = _quote(AGENT_SCHEMA)
        rows = await conn.fetch(
            f"""SELECT et.name, COUNT(e.id) AS edge_count
                FROM {schema}.edge_type et
                LEFT JOIN {schema}.edge e ON e.type_id = et.id
                GROUP BY et.id, et.name
                ORDER BY edge_count DESC""",
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def _get_all_node_types() -> list[dict]:
    """Get all node types with usage counts."""
    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        schema = _quote(AGENT_SCHEMA)
        rows = await conn.fetch(
            f"""SELECT nt.name, COUNT(n.id) AS node_count
                FROM {schema}.node_type nt
                LEFT JOIN {schema}.node n ON n.type_id = nt.id AND n.forgotten = false
                GROUP BY nt.id, nt.name
                ORDER BY node_count DESC""",
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def _get_aliases() -> list[dict]:
    """Get all aliases."""
    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        schema = _quote(AGENT_SCHEMA)
        rows = await conn.fetch(
            f"""SELECT a.alias, n.name AS canonical_name, nt.name AS type_name, a.source
                FROM {schema}.node_alias a
                JOIN {schema}.node n ON a.node_id = n.id
                JOIN {schema}.node_type nt ON n.type_id = nt.id
                ORDER BY n.name, a.alias""",
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def _get_graph_health() -> dict:
    """Get overall graph health metrics."""
    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        schema = _quote(AGENT_SCHEMA)
        row = await conn.fetchrow(
            f"""SELECT
                (SELECT count(*) FROM {schema}.node WHERE forgotten = false) AS active_nodes,
                (SELECT count(*) FROM {schema}.node WHERE forgotten = true) AS forgotten_nodes,
                (SELECT count(*) FROM {schema}.edge) AS edges,
                (SELECT count(*) FROM {schema}.episode) AS episodes,
                (SELECT count(*) FROM {schema}.node_type) AS node_types,
                (SELECT count(*) FROM {schema}.edge_type) AS edge_types,
                (SELECT count(*) FROM {schema}.node_alias) AS aliases""",
        )
        return dict(row)
    finally:
        await conn.close()


async def _get_edge_weight_stats() -> dict:
    """Get edge weight distribution."""
    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        schema = _quote(AGENT_SCHEMA)
        row = await conn.fetchrow(
            f"""SELECT
                min(weight) AS min_weight,
                avg(weight) AS avg_weight,
                max(weight) AS max_weight,
                percentile_cont(0.5) WITHIN GROUP (ORDER BY weight) AS median_weight,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY weight) AS p95_weight
            FROM {schema}.edge""",
        )
        return dict(row) if row else {}
    finally:
        await conn.close()


async def _get_duplicate_nodes() -> list[dict]:
    """Find duplicate node names."""
    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        schema = _quote(AGENT_SCHEMA)
        rows = await conn.fetch(
            f"""SELECT lower(n.name) AS name, COUNT(*) AS count,
                       array_agg(nt.name ORDER BY n.id) AS types
                FROM {schema}.node n
                JOIN {schema}.node_type nt ON n.type_id = nt.id
                WHERE n.forgotten = false
                GROUP BY lower(n.name)
                HAVING COUNT(*) > 1
                ORDER BY count DESC""",
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def _recall(query: str, limit: int = 10) -> list[dict]:
    """Call MCP recall and return results list."""
    result = await mcp_call("recall", {"query": query, "limit": limit})
    return result.get("results", [])


SCREAMING_SNAKE_RE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$")


# ── Scenario Implementations ──


async def scenario_01_basic_fact_recall() -> ScenarioResult:
    """S01: Basic fact recall — Team Atlas and Project Nexus are retrievable."""
    r = ScenarioResult("S01: Basic fact recall")

    results = await _recall("Team Atlas Project Nexus")
    found_atlas = any(
        "atlas" in str(x.get("content", "")).lower() or "atlas" in str(x.get("name", "")).lower() for x in results
    )
    found_nexus = any(
        "nexus" in str(x.get("content", "")).lower() or "nexus" in str(x.get("name", "")).lower() for x in results
    )

    r.notes.append(f"Team Atlas in recall: {found_atlas}, Project Nexus in recall: {found_nexus}")

    if found_atlas and found_nexus:
        r.verdict = Verdict.ACCEPTABLE
        r.notes.append("Both Team Atlas and Project Nexus found")
    elif found_atlas or found_nexus:
        r.verdict = Verdict.PARTIAL
        r.notes.append("Only one found in recall")
    else:
        nodes_atlas = await _find_nodes_by_name("atlas")
        nodes_nexus = await _find_nodes_by_name("nexus")
        if nodes_atlas or nodes_nexus:
            r.verdict = Verdict.PARTIAL
            r.notes.append("Nodes exist but not in recall top-10")
        else:
            r.verdict = Verdict.FAIL
            r.notes.append("Neither found")
    return r


async def scenario_02_multi_entity_recall() -> ScenarioResult:
    """S02: Multi-entity recall — Maya, Jonas, Sarah all exist as separate entities."""
    r = ScenarioResult("S02: Multi-entity recall")

    people = ["maya", "jonas", "sarah"]
    found_count = 0
    for name in people:
        nodes = await _find_nodes_by_name(name)
        if nodes:
            found_count += 1
            r.notes.append(f"  {name}: {len(nodes)} node(s) — {[n['name'] for n in nodes]}")
        else:
            r.notes.append(f"  {name}: NOT FOUND")

    if found_count == 3:
        r.verdict = Verdict.ACCEPTABLE
        r.notes.append("All 3 people found as nodes")
    elif found_count >= 2:
        r.verdict = Verdict.PARTIAL
        r.notes.append(f"Only {found_count}/3 people found")
    else:
        r.verdict = Verdict.FAIL
        r.notes.append(f"Only {found_count}/3 people found")
    return r


async def scenario_03_content_updates_person() -> ScenarioResult:
    """S03: Content updates (person) — Maya's role change reflected."""
    r = ScenarioResult("S03: Content updates (person)")

    nodes = await _find_nodes_by_name("maya")
    if not nodes:
        r.verdict = Verdict.FAIL
        r.notes.append("No Maya node found")
        return r

    content_all = " ".join(str(n.get("content", "")).lower() for n in nodes)
    r.notes.append(f"Maya content: '{content_all[:200]}'")

    has_director = "director" in content_all or "engineering director" in content_all
    has_tech_lead_only = "tech lead" in content_all and not has_director

    if has_director:
        r.verdict = Verdict.ACCEPTABLE
        r.notes.append("Engineering Director reflected in content")
    elif has_tech_lead_only:
        r.verdict = Verdict.FAIL
        r.notes.append("Still shows Tech Lead only")
    else:
        # Check recall
        results = await _recall("Maya Chen role")
        director_in_recall = any("director" in str(x.get("content", "")).lower() for x in results)
        r.verdict = Verdict.PARTIAL if director_in_recall else Verdict.FAIL
        r.notes.append(f"Director in recall: {director_in_recall}")
    return r


async def scenario_04_content_updates_tech() -> ScenarioResult:
    """S04: Content updates (tech) — DataForge migration tracked."""
    r = ScenarioResult("S04: Content updates (tech)")

    nodes = await _find_nodes_by_name("dataforge")
    if not nodes:
        r.verdict = Verdict.FAIL
        r.notes.append("No DataForge node found")
        return r

    content_all = " ".join(str(n.get("content", "")).lower() for n in nodes)
    r.notes.append(f"DataForge content: '{content_all[:200]}'")

    # After reversion (EP5), DataForge should reference Kafka
    has_kafka = "kafka" in content_all
    # Pulsar might still be mentioned as historical context, that's ok

    if has_kafka:
        r.verdict = Verdict.ACCEPTABLE
        r.notes.append("Kafka reflected in DataForge content")
    else:
        r.verdict = Verdict.PARTIAL
        r.notes.append("Kafka not found in DataForge content")
    return r


async def scenario_05_deadline_updates() -> ScenarioResult:
    """S05: Deadline updates — Project Nexus deadline reflects August."""
    r = ScenarioResult("S05: Deadline updates")

    nodes = await _find_nodes_by_name("nexus")
    if not nodes:
        results = await _recall("Project Nexus deadline launch date")
        august_found = any("august" in str(x.get("content", "")).lower() for x in results)
        r.verdict = Verdict.PARTIAL if august_found else Verdict.FAIL
        r.notes.append(f"No Nexus node; August in recall: {august_found}")
        return r

    content_all = " ".join(str(n.get("content", "")).lower() for n in nodes)
    r.notes.append(f"Nexus content: '{content_all[:200]}'")

    if "august" in content_all:
        if "june" in content_all:
            r.verdict = Verdict.PARTIAL
            r.notes.append("Both June and August mentioned")
        else:
            r.verdict = Verdict.ACCEPTABLE
            r.notes.append("August reflected, June replaced")
    else:
        # Check recall
        results = await _recall("Project Nexus launch date")
        august_in_recall = any("august" in str(x.get("content", "")).lower() for x in results)
        r.verdict = Verdict.PARTIAL if august_in_recall else Verdict.FAIL
        r.notes.append(f"August in recall: {august_in_recall}")
    return r


async def scenario_06_contradiction_handling() -> ScenarioResult:
    """S06: Contradiction handling — Kafka reversion after Pulsar migration."""
    r = ScenarioResult("S06: Contradiction handling")

    # After EP3 (migrate to Pulsar) and EP5 (revert to Kafka),
    # DataForge node content should reflect Kafka (current state).
    # Both Kafka and Pulsar may appear in recall (historical context is fine).

    # Primary check: DataForge node content reflects Kafka reversion
    nodes = await _find_nodes_by_name("dataforge")
    dataforge_exact = [n for n in nodes if n["name"].lower().strip() == "dataforge"]

    if dataforge_exact:
        content = str(dataforge_exact[0].get("content", "")).lower()
        r.notes.append(f"DataForge content: '{content[:200]}'")
        kafka_in_content = "kafka" in content
        reversion_in_content = "revert" in content or "cancel" in content
        r.notes.append(f"Kafka in content: {kafka_in_content}, Reversion in content: {reversion_in_content}")

        if kafka_in_content:
            r.verdict = Verdict.ACCEPTABLE
            r.notes.append("DataForge content reflects Kafka (reversion processed)")
        else:
            r.verdict = Verdict.PARTIAL
            r.notes.append("DataForge exists but Kafka not in content")
    else:
        # Fallback: check recall
        results = await _recall("DataForge event streaming technology")
        kafka_found = any(
            "kafka" in str(x.get("content", "")).lower() or "kafka" in str(x.get("name", "")).lower() for x in results
        )
        if kafka_found:
            r.verdict = Verdict.PARTIAL
            r.notes.append("Kafka found in recall but DataForge node missing")
        else:
            r.verdict = Verdict.FAIL
            r.notes.append("Neither DataForge node nor Kafka in recall")
    return r


async def scenario_07_correction_framing() -> ScenarioResult:
    """S07: Correction framing — NLP precision 87% → 94.2% in node content."""
    r = ScenarioResult("S07: Correction framing")

    # Check DataForge or NLP model node for precision update
    nodes_df = await _find_nodes_by_name("dataforge")
    nodes_nlp = await _find_nodes_by_name("nlp")
    nodes_precision = await _find_nodes_by_name("precision")
    all_nodes = nodes_df + nodes_nlp + nodes_precision

    content_all = " ".join(str(n.get("content", "")).lower() for n in all_nodes)
    r.notes.append(f"Combined content ({len(all_nodes)} nodes): '{content_all[:300]}'")

    has_942 = "94.2" in content_all

    if has_942:
        r.verdict = Verdict.ACCEPTABLE
        r.notes.append("94.2% precision found in node content")
    else:
        # Check recall
        results = await _recall("NLP model precision DataForge accuracy")
        recall_content = " ".join(str(x.get("content", "")).lower() for x in results)
        if "94.2" in recall_content:
            r.verdict = Verdict.PARTIAL
            r.notes.append("94.2% found in recall but not in node content")
        elif "87" in recall_content:
            r.verdict = Verdict.PARTIAL
            r.notes.append("Only old 87% found — correction not propagated")
        else:
            r.verdict = Verdict.FAIL
            r.notes.append("No precision info found anywhere")
    return r


async def scenario_08_property_evolution() -> ScenarioResult:
    """S08: Property evolution — DataForge microservices architecture reflected."""
    r = ScenarioResult("S08: Property evolution")

    nodes = await _find_nodes_by_name("dataforge")
    if not nodes:
        r.verdict = Verdict.FAIL
        r.notes.append("No DataForge node found")
        return r

    # Check DataForge content AND connected nodes/recall for architecture info
    content_all = " ".join(str(n.get("content", "")).lower() for n in nodes)
    r.notes.append(f"DataForge content: '{content_all[:300]}'")

    # Architecture components may be in DataForge content OR as separate connected nodes
    components = ["microservices", "api gateway", "istio", "service mesh", "data lake"]
    found_in_content = [c for c in components if c in content_all]

    # Also check if components exist as separate nodes (proper graph modeling)
    all_nodes = await _get_all_nodes()
    all_node_names = " ".join(n["name"].lower() for n in all_nodes)
    found_as_nodes = [c for c in components if c in all_node_names]

    # Check recall for full picture
    results = await _recall("DataForge architecture microservices components")
    recall_names = " ".join(str(x.get("name", "")).lower() for x in results)
    recall_content = " ".join(str(x.get("content", "")).lower() for x in results)
    recall_combined = f"{recall_names} {recall_content}"
    found_in_recall = [c for c in components if c in recall_combined]

    all_found = set(found_in_content + found_as_nodes + found_in_recall)
    r.notes.append(f"In content: {found_in_content}, as nodes: {found_as_nodes}, in recall: {found_in_recall}")

    if len(all_found) >= 3:
        r.verdict = Verdict.ACCEPTABLE
        r.notes.append(f"Architecture components accessible: {all_found}")
    elif len(all_found) >= 1:
        r.verdict = Verdict.PARTIAL
        r.notes.append(f"Some components found: {all_found}")
    else:
        r.verdict = Verdict.FAIL
        r.notes.append("No architecture info found")
    return r


async def scenario_09_domain_knowledge() -> ScenarioResult:
    """S09: Domain knowledge query — DataForge tech stack query returns rich context."""
    r = ScenarioResult("S09: Domain knowledge query")

    results = await _recall("DataForge technology stack data processing")
    relevant = []
    for res in results:
        content = str(res.get("content", "")).lower()
        name = str(res.get("name", "")).lower()
        if any(kw in content or kw in name for kw in ["dataforge", "kafka", "nexus", "atlas"]):
            relevant.append(res.get("name", "unknown"))

    r.notes.append(f"Relevant results: {relevant}")

    has_graph_context = any(res.get("graph_context") for res in results)
    r.notes.append(f"Graph context present: {has_graph_context}")

    if len(relevant) >= 2:
        r.verdict = Verdict.ACCEPTABLE
        r.notes.append(f"Rich recall: {len(relevant)} relevant results")
    elif len(relevant) == 1:
        r.verdict = Verdict.PARTIAL
        r.notes.append("Only 1 relevant result")
    else:
        r.verdict = Verdict.FAIL
        r.notes.append("No relevant results in recall")
    return r


async def scenario_10_update_buried_by_activation() -> ScenarioResult:
    """S10: Update buried by activation — after stress test, recent updates still accessible."""
    r = ScenarioResult("S10: Update not buried by activation")

    # After 10 stress recalls of "Team Atlas", check that Jonas's team change is still findable
    results = await _recall("Jonas Weber Security team")
    jonas_found = any(
        "jonas" in str(x.get("content", "")).lower() or "jonas" in str(x.get("name", "")).lower() for x in results
    )
    security_found = any("security" in str(x.get("content", "")).lower() for x in results)

    r.notes.append(f"Jonas in recall: {jonas_found}, Security in recall: {security_found}")

    if jonas_found and security_found:
        r.verdict = Verdict.ACCEPTABLE
        r.notes.append("Jonas's security team move still accessible")
    elif jonas_found:
        r.verdict = Verdict.PARTIAL
        r.notes.append("Jonas found but security team not in content")
    else:
        r.verdict = Verdict.FAIL
        r.notes.append("Jonas not found after stress test")
    return r


async def scenario_11_edge_type_stability() -> ScenarioResult:
    """S11: Edge type stability — all edge types are SCREAMING_SNAKE_CASE."""
    r = ScenarioResult("S11: Edge type stability")

    edge_types = await _get_all_edge_types()
    if not edge_types:
        r.verdict = Verdict.FAIL
        r.notes.append("No edge types found")
        return r

    total = len(edge_types)
    valid = [et for et in edge_types if SCREAMING_SNAKE_RE.match(et["name"])]
    invalid = [et for et in edge_types if not SCREAMING_SNAKE_RE.match(et["name"])]

    r.notes.append(f"Total edge types: {total}, Valid SCREAMING_SNAKE: {len(valid)}, Invalid: {len(invalid)}")
    if invalid:
        r.notes.append(f"Invalid edge types: {[et['name'] for et in invalid]}")

    if len(invalid) == 0:
        r.verdict = Verdict.ACCEPTABLE
        r.notes.append("All edge types are SCREAMING_SNAKE_CASE")
    elif len(invalid) <= 2:
        r.verdict = Verdict.PARTIAL
        r.notes.append(f"{len(invalid)} non-conforming edge types")
    else:
        r.verdict = Verdict.FAIL
        r.notes.append(f"{len(invalid)} non-conforming edge types — normalization not working")
    return r


async def scenario_12_node_dedup() -> ScenarioResult:
    """S12: Node dedup — DataForge exists as exactly 1 node (not 2 with different types)."""
    r = ScenarioResult("S12: Node dedup")

    # The original Plan 17 gap was: "DataForge exists as 2 nodes (Tool + Project)"
    # With type hierarchy, Tool and Project are in the same merge group → should merge.
    # Note: nodes like "DataForge NLP Precision 94.2%" are distinct entities, not duplicates.
    nodes = await _find_nodes_by_name("dataforge")
    r.notes.append(f"DataForge-matching nodes: {len(nodes)}")
    for n in nodes:
        r.notes.append(f"  name='{n['name']}' type='{n['type_name']}' importance={n.get('importance')}")

    # The key check: exactly 1 node named "DataForge" (exact match, not substring)
    dataforge_exact = [n for n in nodes if n["name"].lower().strip() == "dataforge"]
    r.notes.append(f"Exact 'DataForge' nodes: {len(dataforge_exact)}")
    for n in dataforge_exact:
        r.notes.append(f"  exact: name='{n['name']}' type='{n['type_name']}'")

    # Also check for Kafka/Apache Kafka aliasing
    kafka_nodes = await _find_nodes_by_name("kafka")
    r.notes.append(f"Kafka-related nodes: {len(kafka_nodes)}")
    for n in kafka_nodes:
        r.notes.append(f"  name='{n['name']}' type='{n['type_name']}'")

    # Check aliases
    aliases = await _get_aliases()
    kafka_aliases = [
        a for a in aliases if "kafka" in a.get("alias", "").lower() or "kafka" in a.get("canonical_name", "").lower()
    ]
    r.notes.append(f"Kafka-related aliases: {kafka_aliases}")

    # Check for real duplicates (same name, different types)
    dupes = await _get_duplicate_nodes()
    r.notes.append(f"Duplicate nodes: {dupes}")

    if len(dataforge_exact) == 1:
        if len(dupes) == 0:
            r.verdict = Verdict.ACCEPTABLE
            r.notes.append("Single DataForge node, no name duplicates")
        else:
            r.verdict = Verdict.PARTIAL
            r.notes.append("Single DataForge but other name duplicates exist")
    elif len(dataforge_exact) == 0:
        r.verdict = Verdict.PARTIAL
        r.notes.append("No exact 'DataForge' node (may be named differently)")
    else:
        r.verdict = Verdict.FAIL
        r.notes.append(f"{len(dataforge_exact)} exact 'DataForge' nodes — dedup failed")
    return r


async def scenario_13_edge_weight_creep() -> ScenarioResult:
    """S13: Edge weight creep — max edge weight stays <= 1.5 after stress test."""
    r = ScenarioResult("S13: Edge weight creep")

    stats = await _get_edge_weight_stats()
    if not stats or stats.get("max_weight") is None:
        r.verdict = Verdict.FAIL
        r.notes.append("No edge weight data")
        return r

    max_weight = float(stats["max_weight"])
    avg_weight = float(stats["avg_weight"])
    r.notes.append(f"max={max_weight:.3f} avg={avg_weight:.3f} median={float(stats.get('median_weight', 0)):.3f}")

    if max_weight <= 1.5:
        r.verdict = Verdict.ACCEPTABLE
        r.notes.append(f"Max weight {max_weight:.3f} within bounds")
    elif max_weight <= 2.0:
        r.verdict = Verdict.PARTIAL
        r.notes.append(f"Max weight {max_weight:.3f} slightly above 1.5")
    else:
        r.verdict = Verdict.FAIL
        r.notes.append(f"Max weight {max_weight:.3f} — weight creep detected")
    return r


async def scenario_14_importance_vs_activation() -> ScenarioResult:
    """S14: Importance vs activation — importance ordering stable after repeated recall."""
    r = ScenarioResult("S14: Importance vs activation")

    # Check that high-importance nodes don't get displaced by frequently-accessed trivial nodes
    results = await _recall("Project Nexus data processing platform")

    # Project Nexus should still be highly ranked
    nexus_rank = None
    for i, res in enumerate(results):
        name = str(res.get("name", "")).lower()
        content = str(res.get("content", "")).lower()
        if "nexus" in name or "nexus" in content:
            nexus_rank = i
            break

    r.notes.append(f"Project Nexus rank in recall: {nexus_rank}")

    if nexus_rank is not None and nexus_rank < 5:
        r.verdict = Verdict.ACCEPTABLE
        r.notes.append(f"Nexus at rank {nexus_rank} — importance preserved")
    elif nexus_rank is not None:
        r.verdict = Verdict.PARTIAL
        r.notes.append(f"Nexus at rank {nexus_rank} — slightly displaced")
    else:
        r.verdict = Verdict.FAIL
        r.notes.append("Nexus not found in recall top-10")
    return r


# ── Main Test Flow ──


async def main() -> int:
    print("=" * 70)
    print("Plan 17: Entity Normalization Validation")
    print(f"MCP:       {MCP_URL}")
    print(f"Ingestion: {INGESTION_URL}")
    print("Token:     configured")
    print(f"Schema:    {AGENT_SCHEMA}")
    print("=" * 70)

    await wait_for_ready(INGESTION_URL, TOKEN)
    await _assert_health()

    # ── Phase A: Ingest initial episodes (EP1, EP3, EP7) ──
    print("\n" + "=" * 70)
    print("PHASE A: Ingesting initial episodes")
    print("=" * 70)

    baseline_a = await _get_max_job_id()

    initial_episodes = [
        ("EP1-team", EP1_TEAM),
        ("EP3-migration", EP3_MIGRATION),
        ("EP7-precision", EP7_PRECISION),
        ("EP8-architecture", EP8_ARCHITECTURE),
    ]

    for label, text in initial_episodes:
        result = await mcp_call(
            "remember",
            {"text": text, "context": f"e2e_plan17_{label}"},
        )
        eid = result.get("episode_id", "?")
        print(f"  [{label}] episode {eid}: {text[:60]}...")

    print("\n  Waiting for initial extraction...")
    await _wait_for_extraction(baseline_a, "phase-A initial")

    # ── Phase B: Ingest update episodes ──
    print("\n" + "=" * 70)
    print("PHASE B: Ingesting update/correction episodes")
    print("=" * 70)

    baseline_b = await _get_max_job_id()

    update_episodes = [
        ("EP2-role-change", EP2_ROLE_CHANGE),
        ("EP4-deadline", EP4_DEADLINE),
        ("EP5-reversion", EP5_REVERSION),
        ("EP6-team-change", EP6_TEAM_CHANGE),
    ]

    for label, text in update_episodes:
        result = await mcp_call(
            "remember",
            {"text": text, "context": f"e2e_plan17_{label}"},
        )
        eid = result.get("episode_id", "?")
        print(f"  [{label}] episode {eid}: {text[:60]}...")

    print("\n  Waiting for update extraction...")
    await _wait_for_extraction(baseline_b, "phase-B updates")

    # ── Phase C: Recall stress test (10 recalls) ──
    print("\n" + "=" * 70)
    print("PHASE C: Recall stress test (10 x 'Team Atlas members')")
    print("=" * 70)

    for i in range(10):
        results = await _recall("Team Atlas members")
        top_names = [r.get("name", "?") for r in results[:3]]
        print(f"  Recall {i + 1}/10: top={top_names}")
        await asyncio.sleep(1)

    # ── Phase D: Score all 14 scenarios ──
    print("\n" + "=" * 70)
    print("PHASE D: Scoring all 14 scenarios")
    print("=" * 70)

    scenarios = [
        scenario_01_basic_fact_recall,
        scenario_02_multi_entity_recall,
        scenario_03_content_updates_person,
        scenario_04_content_updates_tech,
        scenario_05_deadline_updates,
        scenario_06_contradiction_handling,
        scenario_07_correction_framing,
        scenario_08_property_evolution,
        scenario_09_domain_knowledge,
        scenario_10_update_buried_by_activation,
        scenario_11_edge_type_stability,
        scenario_12_node_dedup,
        scenario_13_edge_weight_creep,
        scenario_14_importance_vs_activation,
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

    # ── Phase E: Graph health audit ──
    print("\n" + "=" * 70)
    print("PHASE E: Graph Health Audit")
    print("=" * 70)

    health = await _get_graph_health()
    print(f"  Active nodes:   {health.get('active_nodes', '?')}")
    print(f"  Forgotten nodes: {health.get('forgotten_nodes', '?')}")
    print(f"  Edges:          {health.get('edges', '?')}")
    print(f"  Episodes:       {health.get('episodes', '?')}")
    print(f"  Node types:     {health.get('node_types', '?')}")
    print(f"  Edge types:     {health.get('edge_types', '?')}")
    print(f"  Aliases:        {health.get('aliases', '?')}")

    weight_stats = await _get_edge_weight_stats()
    if weight_stats:
        print("\n  Edge weight stats:")
        for k, v in weight_stats.items():
            print(f"    {k}: {float(v):.4f}" if v is not None else f"    {k}: null")

    print("\n  --- All nodes ---")
    all_nodes = await _get_all_nodes()
    for n in all_nodes:
        print(f"    {n['name']} [{n['type_name']}] imp={n.get('importance', '?')}")

    print("\n  --- All edge types ---")
    all_ets = await _get_all_edge_types()
    for et in all_ets:
        marker = "OK" if SCREAMING_SNAKE_RE.match(et["name"]) else "BAD"
        print(f"    [{marker}] {et['name']} ({et['edge_count']} edges)")

    print("\n  --- All node types ---")
    all_nts = await _get_all_node_types()
    for nt in all_nts:
        print(f"    {nt['name']} ({nt['node_count']} nodes)")

    print("\n  --- Aliases ---")
    aliases = await _get_aliases()
    for a in aliases:
        print(f"    '{a['alias']}' -> '{a['canonical_name']}' [{a['type_name']}] (source: {a.get('source', '?')})")

    print("\n  --- Duplicate nodes ---")
    dupes = await _get_duplicate_nodes()
    if dupes:
        for d in dupes:
            print(f"    {d['name']}: {d['count']}x types={d['types']}")
    else:
        print("    No duplicate nodes detected")

    # ── Summary ──
    print("\n" + "=" * 70)
    print("SCENARIO RESULTS SUMMARY")
    print("=" * 70)

    acceptable_count = sum(1 for r in results if r.verdict == Verdict.ACCEPTABLE)
    partial_count = sum(1 for r in results if r.verdict == Verdict.PARTIAL)
    fail_count = sum(1 for r in results if r.verdict == Verdict.FAIL)

    plan165_baseline = {
        1: "Acceptable",
        2: "Acceptable",
        3: "Acceptable",
        4: "Acceptable",
        5: "Acceptable",
        6: "Acceptable",
        7: "Partial",
        8: "Partial",
        9: "Acceptable",
        10: "Acceptable",
        11: "Acceptable",
        12: "Partial",
        13: "Acceptable",
        14: "Acceptable",
    }

    print(f"\n{'#':<4} {'Scenario':<40} {'Plan 16.5':<12} {'Plan 17':<12} {'Delta'}")
    print("-" * 80)
    for i, r in enumerate(results, 1):
        baseline = plan165_baseline.get(i, "?")
        marker = {"Acceptable": "+", "Partial": "~", "FAIL": "x"}[r.verdict.value]
        delta = ""
        if baseline == "Partial" and r.verdict == Verdict.ACCEPTABLE:
            delta = "IMPROVED"
        elif baseline == "Acceptable" and r.verdict != Verdict.ACCEPTABLE:
            delta = "REGRESSION"
        print(f"[{marker}] {i:<2}  {r.name:<40} {baseline:<12} {r.verdict.value:<12} {delta}")

    print(f"\nAcceptable: {acceptable_count}/14  Partial: {partial_count}/14  Fail: {fail_count}/14")
    print("\nPlan 16.5: 11 Acceptable / 3 Partial / 0 Fail  (79%)")
    pct = acceptable_count * 100 // 14
    print(f"Plan 17:   {acceptable_count} Acceptable / {partial_count} Partial / {fail_count} Fail  ({pct}%)")
    print("Target:    >=13 Acceptable (93%)")

    regressions = []
    for i, r in enumerate(results, 1):
        baseline = plan165_baseline.get(i, "?")
        if baseline == "Acceptable" and r.verdict != Verdict.ACCEPTABLE:
            regressions.append(f"S{i:02d}: {r.name}")

    if regressions:
        print(f"\nREGRESSIONS: {regressions}")
    else:
        print("\nNo regressions from Plan 16.5 baseline")

    gate_passed = acceptable_count >= 13 and fail_count == 0
    if gate_passed:
        print("\n[TARGET MET] >= 13/14 Acceptable, 0 Fails")
    elif fail_count == 0:
        print(f"\n[TARGET NOT MET] {acceptable_count}/14 Acceptable (need 13), but 0 Fails")
    else:
        print(f"\n[HARD FAILURE] {fail_count} Fails detected")

    write_configured_result(
        {
            "schema_version": 1,
            "kind": "neocortex-e2e-scenario-result",
            "script": "e2e_plan17_validation.py",
            "child_run_id": os.environ.get("NEOCORTEX_E2E_RUN_ID", "NOT_MEASURED"),
            "status": "PASS" if gate_passed else "FAIL",
            "exit_code": 0 if gate_passed else 1,
            "counts": {
                "total": len(results),
                "pass": 0,
                "partial": partial_count,
                "acceptable": acceptable_count,
                "fail": fail_count,
            },
            "gate": {"basis": "ACCEPTABLE", "threshold": 13, "passed": gate_passed},
            "scenarios": [
                {"index": index, "verdict": result.verdict.value.upper()} for index, result in enumerate(results, 1)
            ],
        }
    )

    print("\n" + "=" * 70)
    print("PLAN 17 VALIDATION COMPLETED")
    print("=" * 70)
    return 0 if gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
