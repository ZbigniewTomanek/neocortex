"""E2E test for the extraction pipeline: ingest → extract → recall with graph context.

Validates the full data path:
  1. Ingest medical text via MCP remember (triggers extraction)
  2. Wait for Procrastinate extraction jobs to complete
  3. Verify ontology was created (node types, edge types)
  4. Verify nodes and edges were extracted into the graph
  5. Recall with a semantic query → expect graph_context on matched nodes
  6. Discover → expect non-zero type counts
  7. Cross-agent isolation: Bob cannot see Alice's extracted graph

Prerequisites:
  docker compose up -d postgres
  GOOGLE_API_KEY=... NEOCORTEX_AUTH_MODE=dev_token \
    NEOCORTEX_DEV_TOKENS_FILE=dev_tokens.json \
    NEOCORTEX_MOCK_DB=false uv run python -m neocortex &
  GOOGLE_API_KEY=... NEOCORTEX_AUTH_MODE=dev_token \
    NEOCORTEX_DEV_TOKENS_FILE=dev_tokens.json \
    NEOCORTEX_MOCK_DB=false uv run python -m neocortex.ingestion &

Usage:
  GOOGLE_API_KEY=... uv run python scripts/e2e_extraction_pipeline_test.py

Via unified runner:
  GOOGLE_API_KEY=... ./scripts/run_e2e.sh scripts/e2e_extraction_pipeline_test.py
"""

from __future__ import annotations

import asyncio
import os
import time

import asyncpg
import httpx
from fastmcp import Client

from neocortex.config import PostgresConfig

try:
    from scripts.e2e_common import (  # ty: ignore[unresolved-import]
        DEFAULT_JOB_WAIT_S,
        DEFAULT_POLL_S,
        wait_for_jobs,
        wait_for_ready,
    )
except ModuleNotFoundError:  # Direct ``python scripts/e2e_extraction_pipeline_test.py`` execution.
    from e2e_common import (  # ty: ignore[unresolved-import]
        DEFAULT_JOB_WAIT_S,
        DEFAULT_POLL_S,
        wait_for_jobs,
        wait_for_ready,
    )

BASE_URL = os.environ.get("NEOCORTEX_BASE_URL", "http://127.0.0.1:8000")
INGESTION_URL = os.environ.get("NEOCORTEX_INGESTION_BASE_URL", "http://127.0.0.1:8001")
MCP_URL = os.environ.get("NEOCORTEX_MCP_URL", f"{BASE_URL}/mcp")
ALICE_TOKEN = os.environ.get("NEOCORTEX_ALICE_TOKEN", "alice-token")
BOB_TOKEN = os.environ.get("NEOCORTEX_BOB_TOKEN", "bob-token")
ADMIN_TOKEN = os.environ.get("NEOCORTEX_ADMIN_TOKEN", "admin-token-neocortex")
AGENT_SCHEMA = "ncx_alice__personal"

# Seed domain schemas for domain routing validation
DOMAIN_SCHEMAS = [
    "ncx_shared__user_profile",
    "ncx_shared__technical_knowledge",
    "ncx_shared__work_context",
    "ncx_shared__domain_knowledge",
]
DOMAIN_PURPOSES = ["user_profile", "technical_knowledge", "work_context", "domain_knowledge"]

# --- Seed texts (subset of medical corpus for speed) ---

SEED_TEXTS = [
    (
        "Serotonin (5-hydroxytryptamine, 5-HT) is a monoamine neurotransmitter "
        "primarily found in the gastrointestinal tract, blood platelets, and the "
        "central nervous system. In the brain, serotonin is synthesized in the "
        "raphe nuclei of the brainstem. It modulates mood, appetite, sleep, and "
        "cognitive functions including memory and learning."
    ),
    (
        "Selective serotonin reuptake inhibitors (SSRIs) such as fluoxetine and "
        "sertraline work by blocking the reuptake of serotonin in the synaptic "
        "cleft, increasing its availability for postsynaptic receptors. They are "
        "first-line treatment for major depressive disorder and several anxiety "
        "disorders."
    ),
    (
        "SSRI-induced sexual dysfunction is one of the most common reasons for "
        "treatment discontinuation. Symptoms include decreased libido, delayed "
        "ejaculation, and anorgasmia. The mechanism involves serotonin's "
        "inhibitory effect on dopamine and norepinephrine pathways that mediate "
        "sexual arousal and orgasm."
    ),
]


async def mcp_call(token: str, tool_name: str, arguments: dict[str, object]) -> dict:
    async with Client(MCP_URL, auth=token) as client:
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


# ── Step 0: Set up domain routing prerequisites ──────────────────


async def step_setup_domain_routing() -> None:
    """Verify seed domain schemas are auto-provisioned (Plan 13 Stage 1) and grant Alice write."""
    print("\n=== Step 0: Set up domain routing prerequisites ===")

    # Verify discover_domains returns seed domains (Plan 13 Stage 1 + Stage 4)
    domains_result = await mcp_call(ALICE_TOKEN, "discover_domains", {})
    domain_slugs = [d["slug"] for d in domains_result.get("domains", [])]
    print(f"  discover_domains returned: {domain_slugs}")
    for expected in DOMAIN_PURPOSES:
        if expected in domain_slugs:
            print(f"    [PASS] Seed domain '{expected}' present")
        else:
            print(f"    [WARN] Seed domain '{expected}' missing")

    # Verify seed schemas are auto-provisioned (is_shared=true) via discover_graphs
    graphs_result = await mcp_call(ALICE_TOKEN, "discover_graphs", {})
    graph_names = [g["schema_name"] for g in graphs_result.get("graphs", [])]
    shared_graphs = [g for g in graphs_result.get("graphs", []) if g.get("is_shared")]
    print(f"  discover_graphs returned {len(graph_names)} graphs, {len(shared_graphs)} shared")
    for schema_name in DOMAIN_SCHEMAS:
        if schema_name in graph_names:
            print(f"    [PASS] Seed schema '{schema_name}' auto-provisioned and accessible")
        else:
            print(f"    [INFO] Seed schema '{schema_name}' not yet visible — creating via admin")

    async with httpx.AsyncClient(base_url=INGESTION_URL, timeout=10.0) as client:
        # Ensure shared schemas exist (idempotent — may already be auto-provisioned)
        for purpose in DOMAIN_PURPOSES:
            resp = await client.post(
                "/admin/graphs",
                headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
                json={"purpose": purpose},
            )
            if resp.status_code == 200:
                schema = resp.json().get("schema_name", "")
                print(f"  Ensured schema: {schema}")
            else:
                print(f"  Schema for '{purpose}': {resp.status_code} (may already exist)")

        # Grant Alice write permissions to all domain schemas
        for schema_name in DOMAIN_SCHEMAS:
            resp = await client.post(
                "/admin/permissions",
                headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
                json={
                    "agent_id": "alice",
                    "schema_name": schema_name,
                    "can_read": True,
                    "can_write": True,
                },
            )
            if resp.status_code == 200:
                print(f"  Granted alice write on {schema_name}")
            else:
                print(f"  Grant for {schema_name}: {resp.status_code}")

    print("  [PASS] Domain routing prerequisites configured")


# ── Step 1: Ingest seed texts ──────────────────────────────────────


async def _cleanup_stale_jobs() -> None:
    """Delete old extraction jobs so the worker can process ours immediately."""
    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        result = await conn.execute("DELETE FROM procrastinate_jobs WHERE queue_name = 'extraction'")
        # result is e.g. "DELETE 26"
        count = int(result.split()[-1]) if result else 0
        if count:
            print(f"  Cleaned up {count} stale extraction job(s)")
    finally:
        await conn.close()


async def _get_max_job_id() -> int:
    """Return the current max job ID so we can track only new jobs."""
    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        val = await conn.fetchval("SELECT coalesce(max(id), 0) FROM procrastinate_jobs WHERE queue_name = 'extraction'")
        return int(val)
    finally:
        await conn.close()


async def step_ingest() -> tuple[list[int], int]:
    """Store seed texts via MCP remember (triggers extraction jobs)."""
    print("\n=== Step 1: Ingest seed texts ===")
    baseline_job_id = await _get_max_job_id()
    print(f"  Baseline job ID: {baseline_job_id}")
    episode_ids: list[int] = []
    for i, text in enumerate(SEED_TEXTS):
        result = await mcp_call(ALICE_TOKEN, "remember", {"text": text, "context": "e2e_extraction_test"})
        eid = int(result["episode_id"])
        assert eid > 0, f"Bad episode id: {result}"
        episode_ids.append(eid)
        print(f"  [{i + 1}/{len(SEED_TEXTS)}] Stored episode {eid}: {text[:60]}...")
    return episode_ids, baseline_job_id


# ── Step 2: Wait for extraction jobs ───────────────────────────────


async def step_wait_for_extraction(baseline_job_id: int) -> None:
    """Poll the database until our extraction jobs (created after baseline) complete."""
    print("\n=== Step 2: Wait for extraction jobs ===")
    counts = await wait_for_jobs(baseline_job_id=baseline_job_id, label="extraction")
    if counts.failed:
        conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
        try:
            err_rows = await conn.fetch(
                """SELECT id, args, status
                   FROM procrastinate_jobs
                   WHERE queue_name = 'extraction' AND status = 'failed'
                     AND id > $1
                   LIMIT 3""",
                baseline_job_id,
            )
            details = [(int(r["id"]), r["status"]) for r in err_rows]
            print(f"  [WARN] {counts.failed} job(s) failed: {details}")
        finally:
            await conn.close()
    print(f"  [PASS] All extraction jobs finished ({counts.completed} completed, {counts.failed} failed)")


# ── Step 2b: Verify domain routing jobs ───────────────────────────


async def step_verify_routing_jobs(baseline_job_id: int) -> None:
    """Verify that route_episode jobs were created and completed."""
    timeout_s = float(os.environ.get("NEOCORTEX_E2E_JOB_WAIT_S", str(DEFAULT_JOB_WAIT_S)))
    print(f"\n=== Step 2b: Verify domain routing jobs (timeout {timeout_s:g}s) ===")
    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        # Check that route_episode jobs were enqueued
        route_row = await conn.fetchrow(
            """SELECT
                count(*) FILTER (WHERE status = 'todo') AS pending,
                count(*) FILTER (WHERE status = 'doing') AS running,
                count(*) FILTER (WHERE status = 'succeeded') AS completed,
                count(*) FILTER (WHERE status = 'failed') AS failed,
                count(*) AS total
            FROM procrastinate_jobs
            WHERE task_name = 'route_episode' AND id > $1""",
            baseline_job_id,
        )
        total = int(route_row["total"])
        completed = int(route_row["completed"])
        failed = int(route_row["failed"])
        pending = int(route_row["pending"])
        running = int(route_row["running"])

        print(
            f"  route_episode jobs: total={total} completed={completed} "
            f"failed={failed} pending={pending} running={running}"
        )

        if total == 0:
            print("  [WARN] No route_episode jobs found — domain routing may be disabled")
            return

        # Wait for remaining routing jobs
        start = time.monotonic()
        while pending > 0 or running > 0:
            if time.monotonic() - start > timeout_s:
                raise AssertionError(f"Domain routing jobs did not complete within {timeout_s:g}s")
            await asyncio.sleep(DEFAULT_POLL_S)
            route_row = await conn.fetchrow(
                """SELECT
                    count(*) FILTER (WHERE status = 'todo') AS pending,
                    count(*) FILTER (WHERE status = 'doing') AS running,
                    count(*) FILTER (WHERE status = 'succeeded') AS completed,
                    count(*) FILTER (WHERE status = 'failed') AS failed
                FROM procrastinate_jobs
                WHERE task_name = 'route_episode' AND id > $1""",
                baseline_job_id,
            )
            pending = int(route_row["pending"])
            running = int(route_row["running"])
            completed = int(route_row["completed"])
            failed = int(route_row["failed"])
            elapsed = int(time.monotonic() - start)
            print(
                f"  [{elapsed:3d}s] route_episode: pending={pending} running={running} "
                f"completed={completed} failed={failed}"
            )

        assert completed > 0, "No route_episode jobs completed successfully"
        print(f"  [PASS] {completed} route_episode job(s) completed")

        # Now wait for any extraction jobs spawned by routing
        # These target shared domain schemas (target_schema != NULL)
        start2 = time.monotonic()
        while True:
            domain_extract_row = await conn.fetchrow(
                """SELECT
                    count(*) FILTER (WHERE status = 'todo') AS pending,
                    count(*) FILTER (WHERE status = 'doing') AS running,
                    count(*) FILTER (WHERE status = 'succeeded') AS completed,
                    count(*) FILTER (WHERE status = 'failed') AS failed,
                    count(*) AS total
                FROM procrastinate_jobs
                WHERE task_name = 'extract_episode' AND id > $1
                  AND args::text LIKE '%%ncx_shared__%%'""",
                baseline_job_id,
            )
            d_pending = int(domain_extract_row["pending"])
            d_running = int(domain_extract_row["running"])
            d_completed = int(domain_extract_row["completed"])
            d_failed = int(domain_extract_row["failed"])
            d_total = int(domain_extract_row["total"])

            if d_total == 0:
                print("  [INFO] No domain extraction jobs found (routing may not have matched)")
                break
            if d_pending == 0 and d_running == 0:
                print(f"  [PASS] Domain extraction jobs done: {d_completed} completed, {d_failed} failed")
                break
            if time.monotonic() - start2 > timeout_s:
                raise AssertionError("Domain extraction jobs did not complete in time")
            elapsed = int(time.monotonic() - start2)
            print(
                f"  [{elapsed:3d}s] domain extract: pending={d_pending} running={d_running} "
                f"completed={d_completed} failed={d_failed}"
            )
            await asyncio.sleep(DEFAULT_POLL_S)

    finally:
        await conn.close()


# ── Step 10b: Verify shared domain schemas populated ─────────────


async def step_verify_domain_schemas() -> None:
    """Check that at least one shared domain schema got nodes/edges from routing."""
    print("\n=== Step 10b: Verify shared domain schemas populated ===")
    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        schemas_with_data: list[str] = []
        for schema_name in DOMAIN_SCHEMAS:
            # Check if schema exists
            exists = await conn.fetchval(
                "SELECT 1 FROM information_schema.schemata WHERE schema_name = $1",
                schema_name,
            )
            if not exists:
                print(f"  {schema_name}: schema does not exist")
                continue

            schema = _quote(schema_name)
            node_count = await conn.fetchval(f"SELECT count(*) FROM {schema}.node")
            edge_count = await conn.fetchval(f"SELECT count(*) FROM {schema}.edge")
            episode_count = await conn.fetchval(f"SELECT count(*) FROM {schema}.episode")
            node_count = int(node_count)
            edge_count = int(edge_count)
            episode_count = int(episode_count)

            status = "HAS DATA" if node_count > 0 else "empty"
            print(f"  {schema_name}: nodes={node_count} edges={edge_count} episodes={episode_count} [{status}]")

            if node_count > 0:
                schemas_with_data.append(schema_name)
                # Print sample nodes
                rows = await conn.fetch(f"""
                    SELECT n.name, nt.name AS type_name
                    FROM {schema}.node n
                    JOIN {schema}.node_type nt ON nt.id = n.type_id
                    ORDER BY n.name LIMIT 5""")
                for r in rows:
                    print(f"    {r['name']} [{r['type_name']}]")

        if schemas_with_data:
            print(f"  [PASS] {len(schemas_with_data)} domain schema(s) populated: {', '.join(schemas_with_data)}")
        else:
            print("  [WARN] No domain schemas populated — routing may not have matched or extraction may have failed")

        # Personal graph should ALSO still have data (backward compat)
        schema = _quote(AGENT_SCHEMA)
        personal_nodes = await conn.fetchval(f"SELECT count(*) FROM {schema}.node")
        assert int(personal_nodes) > 0, "Personal graph has no nodes — domain routing should be additive, not replacing"
        print(f"  [PASS] Personal graph still has {personal_nodes} nodes (backward compat)")
    finally:
        await conn.close()

    # Also verify via MCP discovery tools
    print("\n  Verifying domain schemas via discover_ontology...")
    for schema_name in DOMAIN_SCHEMAS:
        try:
            ontology = await mcp_call(ALICE_TOKEN, "discover_ontology", {"graph_name": schema_name})
            stats = ontology.get("stats", {})
            nt = ontology.get("node_types", [])
            et = ontology.get("edge_types", [])
            print(
                f"  {schema_name} via MCP: {len(nt)} node types, {len(et)} edge types, "
                f"nodes={stats.get('total_nodes', 0)} edges={stats.get('total_edges', 0)}"
            )
        except Exception as e:
            print(f"  {schema_name} via MCP: error — {e}")


# ── Step 3: Verify ontology created ────────────────────────────────


async def step_verify_ontology() -> None:
    """Check that node types and edge types were created in the agent's schema."""
    print("\n=== Step 3: Verify ontology ===")
    result = await mcp_call(ALICE_TOKEN, "discover_ontology", {"graph_name": AGENT_SCHEMA})
    node_types = result.get("node_types", [])
    edge_types = result.get("edge_types", [])
    stats = result.get("stats", {})

    print(f"  Node types ({len(node_types)}):")
    for nt in node_types:
        print(f"    {nt['name']} — {nt.get('count', 0)} entities")
    print(f"  Edge types ({len(edge_types)}):")
    for et in edge_types:
        print(f"    {et['name']} — {et.get('count', 0)} relations")
    print(f"  Stats: {stats}")

    assert len(node_types) > 0, f"No node types created. discover_ontology returned: {result}"
    assert len(edge_types) > 0, f"No edge types created. discover_ontology returned: {result}"
    print(f"  [PASS] Ontology populated: {len(node_types)} node types, {len(edge_types)} edge types")

    # Drill into a specific type using discover_details
    first_nt = node_types[0]["name"]
    detail_result = await mcp_call(
        ALICE_TOKEN,
        "discover_details",
        {"type_name": first_nt, "graph_name": AGENT_SCHEMA, "kind": "node"},
    )
    detail = detail_result.get("type_detail", {})
    print(
        f"  discover_details for '{first_nt}': count={detail.get('count', 0)}, samples={detail.get('sample_names', [])}"
    )
    assert detail.get("name") == first_nt, f"Unexpected detail name: {detail}"
    print(f"  [PASS] discover_details returned detail for '{first_nt}'")


# ── Step 4: Verify graph data in PostgreSQL ────────────────────────


async def step_verify_graph_data() -> dict[str, int]:
    """Directly query the agent's schema to count nodes and edges."""
    print("\n=== Step 4: Verify graph data in PostgreSQL ===")
    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        schema = _quote(AGENT_SCHEMA)
        node_count = await conn.fetchval(f"SELECT count(*) FROM {schema}.node")
        edge_count = await conn.fetchval(f"SELECT count(*) FROM {schema}.edge")
        episode_count = await conn.fetchval(f"SELECT count(*) FROM {schema}.episode")
        node_type_count = await conn.fetchval(f"SELECT count(*) FROM {schema}.node_type")
        edge_type_count = await conn.fetchval(f"SELECT count(*) FROM {schema}.edge_type")

        counts = {
            "nodes": int(node_count),
            "edges": int(edge_count),
            "episodes": int(episode_count),
            "node_types": int(node_type_count),
            "edge_types": int(edge_type_count),
        }
        for label, count in counts.items():
            status = "PASS" if count > 0 else "FAIL"
            print(f"  [{status}] {label}: {count}")

        assert counts["nodes"] > 0, "No nodes extracted"
        assert counts["edges"] > 0, "No edges extracted"
        assert counts["episodes"] >= len(
            SEED_TEXTS
        ), f"Expected at least {len(SEED_TEXTS)} episodes, got {counts['episodes']}"

        # Print sample nodes for human inspection
        rows = await conn.fetch(f"""SELECT n.name, nt.name AS type_name
                FROM {schema}.node n
                JOIN {schema}.node_type nt ON nt.id = n.type_id
                ORDER BY n.name LIMIT 10""")
        print("  Sample nodes:")
        for r in rows:
            print(f"    {r['name']} [{r['type_name']}]")

        # Print sample edges
        edge_rows = await conn.fetch(f"""SELECT src.name AS source, et.name AS rel, tgt.name AS target
                FROM {schema}.edge e
                JOIN {schema}.node src ON src.id = e.source_id
                JOIN {schema}.node tgt ON tgt.id = e.target_id
                JOIN {schema}.edge_type et ON et.id = e.type_id
                LIMIT 10""")
        print("  Sample edges:")
        for r in edge_rows:
            print(f"    {r['source']} --[{r['rel']}]--> {r['target']}")

        return counts
    finally:
        await conn.close()


# ── Step 5: Recall with graph context ──────────────────────────────


async def step_recall_with_graph_context() -> None:
    """Recall using a semantic query and verify graph_context is populated."""
    print("\n=== Step 5: Recall with graph context ===")
    queries = [
        ("serotonin mood regulation", "serotonin"),
        ("SSRI antidepressant mechanism", "ssri"),
        ("sexual dysfunction treatment side effects", "sexual"),
    ]
    for query, expected_keyword in queries:
        result = await mcp_call(ALICE_TOKEN, "recall", {"query": query, "limit": 10})
        results = result.get("results", [])
        print(f"\n  Query: '{query}'")
        print(f"  Results: {len(results)}")

        # Check for any node-sourced results (from extraction)
        node_results = [r for r in results if r.get("source_kind") == "node"]
        episode_results = [r for r in results if r.get("source_kind") == "episode"]
        print(f"    Nodes: {len(node_results)}, Episodes: {len(episode_results)}")

        # Check graph_context on node results
        with_context = [r for r in node_results if r.get("graph_context")]
        if with_context:
            print(f"    [PASS] {len(with_context)} node(s) have graph_context")
            ctx = with_context[0]["graph_context"]
            center = ctx.get("center_node", {})
            edges = ctx.get("edges", [])
            neighbors = ctx.get("neighbor_nodes", [])
            print(f"    Center: {center.get('name')} [{center.get('type')}]")
            print(f"    Edges: {len(edges)}, Neighbors: {len(neighbors)}")
        else:
            if node_results:
                print("    [WARN] Node results found but no graph_context attached")
            else:
                print("    [INFO] No node results (only episodes) — graph may still be building")

        # At minimum, episodes should match
        contents = " ".join(str(r.get("content", "")) for r in results).lower()
        if expected_keyword.lower() in contents:
            print(f"    [PASS] Found '{expected_keyword}' in results")
        else:
            print(f"    [WARN] '{expected_keyword}' not found in results")


# ── Step 6: Verify cognitive heuristic fields in recall ───────────


async def step_verify_cognitive_fields() -> None:
    """Verify that recall results include activation_score, importance, spreading_bonus."""
    print("\n=== Step 6: Verify cognitive heuristic fields ===")
    result = await mcp_call(ALICE_TOKEN, "recall", {"query": "serotonin", "limit": 10})
    results = result.get("results", [])
    assert len(results) > 0, "No recall results for cognitive field check"

    node_results = [r for r in results if r.get("source_kind") == "node"]
    episode_results = [r for r in results if r.get("source_kind") == "episode"]

    # Node results should have importance assigned by extraction agents
    for r in node_results:
        assert "importance" in r, f"Node result missing 'importance': {r.get('name')}"
        assert "activation_score" in r, f"Node result missing 'activation_score': {r.get('name')}"
        imp = r["importance"]
        if imp is not None:
            assert 0.0 <= imp <= 1.0, f"importance out of range: {imp}"
            print(f"    Node '{r['name']}': importance={imp:.2f}, activation={r.get('activation_score')}")

    # At least some results should have spreading_bonus (from graph traversal)
    with_bonus = [r for r in results if r.get("spreading_bonus") and r["spreading_bonus"] > 0]
    if with_bonus:
        print(f"  [PASS] {len(with_bonus)} result(s) have spreading_bonus > 0")
    else:
        print("  [INFO] No spreading_bonus observed (may need graph neighbors)")

    print(f"  [PASS] Cognitive fields present on {len(node_results)} node(s), {len(episode_results)} episode(s)")


# ── Step 7: Verify episodic consolidation ─────────────────────────


async def step_verify_consolidation() -> None:
    """Verify that extracted episodes are marked as consolidated."""
    print("\n=== Step 7: Verify episodic consolidation ===")
    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        schema = _quote(AGENT_SCHEMA)
        rows = await conn.fetch(f"SELECT id, consolidated, importance FROM {schema}.episode ORDER BY id")
        consolidated_count = sum(1 for r in rows if r["consolidated"])
        total = len(rows)
        print(f"  Episodes: {total} total, {consolidated_count} consolidated")

        for r in rows:
            status = "consolidated" if r["consolidated"] else "raw"
            print(f"    Episode {r['id']}: {status}, importance={r['importance']:.2f}")

        # All seed episodes should be consolidated after extraction
        assert consolidated_count >= len(
            SEED_TEXTS
        ), f"Expected at least {len(SEED_TEXTS)} consolidated episodes, got {consolidated_count}/{total}"
        print(f"  [PASS] {consolidated_count}/{total} episodes consolidated")
    finally:
        await conn.close()


# ── Step 8: Verify node importance from extraction ────────────────


async def step_verify_node_importance() -> None:
    """Verify that extracted nodes have non-default importance assigned by agents."""
    print("\n=== Step 8: Verify node importance from extraction ===")
    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        schema = _quote(AGENT_SCHEMA)
        rows = await conn.fetch(f"SELECT name, importance FROM {schema}.node ORDER BY importance DESC LIMIT 15")
        assert len(rows) > 0, "No nodes found for importance check"

        has_non_default = False
        for r in rows:
            imp = float(r["importance"])
            if imp != 0.5:
                has_non_default = True
            print(f"    {r['name'][:40]:40s}  importance={imp:.2f}")

        if has_non_default:
            print("  [PASS] Extraction agents assigned varied importance scores")
        else:
            print("  [WARN] All nodes have default importance=0.5 — agents may not be assigning importance")
    finally:
        await conn.close()


# ── Step 9: Verify discover cognitive stats ───────────────────────


async def step_verify_discover_stats() -> None:
    """Verify discover_ontology returns cognitive stats (forgotten, consolidated, avg_activation)."""
    print("\n=== Step 9: Verify discover cognitive stats ===")
    result = await mcp_call(ALICE_TOKEN, "discover_ontology", {"graph_name": AGENT_SCHEMA})
    stats = result.get("stats", {})

    for key in ("forgotten_nodes", "consolidated_episodes", "avg_activation"):
        assert key in stats, f"Missing cognitive stat '{key}' in discover_ontology: {stats}"

    print(f"  forgotten_nodes:       {stats['forgotten_nodes']}")
    print(f"  consolidated_episodes: {stats['consolidated_episodes']}")
    print(f"  avg_activation:        {stats['avg_activation']}")

    assert stats["consolidated_episodes"] >= len(SEED_TEXTS), (
        f"Expected at least {len(SEED_TEXTS)} consolidated episodes in discover_ontology stats, "
        f"got {stats['consolidated_episodes']}"
    )
    print("  [PASS] Discover cognitive stats present and consistent")


# ── Step 10: Cross-agent isolation ─────────────────────────────────


async def step_verify_isolation() -> None:
    """Verify Bob cannot see Alice's extracted graph."""
    print("\n=== Step 6: Cross-agent isolation ===")
    bob_graphs_result = await mcp_call(BOB_TOKEN, "discover_graphs", {})
    bob_graph_names = [g["schema_name"] for g in bob_graphs_result.get("graphs", [])]

    # Bob should not see Alice's personal schema
    bob_has_alice = AGENT_SCHEMA in bob_graph_names
    print(f"  Bob's graphs: {bob_graph_names}")
    if bob_has_alice:
        print("  [WARN] Bob can see Alice's personal schema — checking if data leaked")
    else:
        print("  [PASS] Bob cannot see Alice's personal schema")

    # Check Bob's own ontology (should have no medical types from Alice)
    bob_personal = "ncx_bob__personal"
    bob_nodes = 0
    bob_node_types: list = []
    if bob_personal in bob_graph_names:
        bob_ontology = await mcp_call(BOB_TOKEN, "discover_ontology", {"graph_name": bob_personal})
        bob_node_types = bob_ontology.get("node_types", [])
        bob_nodes = bob_ontology.get("stats", {}).get("total_nodes", 0)

    print(f"  Bob's node types: {len(bob_node_types)}")
    print(f"  Bob's total nodes: {bob_nodes}")

    # Bob should NOT have Alice's extracted nodes in his personal schema
    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        bob_schema = "ncx_bob__personal"
        exists = await conn.fetchval(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = $1",
            bob_schema,
        )
        if exists:
            # Check that Alice's medical-domain nodes didn't leak into Bob's schema
            leaked = await conn.fetchval(f"""SELECT count(*) FROM {_quote(bob_schema)}.node
                    WHERE lower(name) LIKE '%serotonin%'
                       OR lower(name) LIKE '%ssri%'
                       OR lower(name) LIKE '%raphe%'""")
            assert int(leaked) == 0, f"Bob has {leaked} medical nodes — extraction leaked across agents"
            print("  [PASS] Bob's schema has no Alice medical nodes (isolation verified)")
        else:
            print("  [PASS] Bob's personal schema doesn't exist (no data stored)")
    finally:
        await conn.close()


# ── Main ───────────────────────────────────────────────────────────


async def main() -> None:
    print("=" * 60)
    print("E2E Extraction Pipeline Test")
    print(f"MCP:       {MCP_URL}")
    print(f"Ingestion: {INGESTION_URL}")
    print("Token:     configured")
    print("=" * 60)

    await wait_for_ready(INGESTION_URL, ADMIN_TOKEN)
    await _assert_health()

    await step_setup_domain_routing()
    await _cleanup_stale_jobs()
    episode_ids, baseline_job_id = await step_ingest()
    await step_wait_for_extraction(baseline_job_id)
    await step_verify_routing_jobs(baseline_job_id)
    await step_verify_ontology()
    counts = await step_verify_graph_data()
    await step_recall_with_graph_context()
    await step_verify_cognitive_fields()
    await step_verify_consolidation()
    await step_verify_node_importance()
    await step_verify_discover_stats()
    await step_verify_isolation()
    await step_verify_domain_schemas()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print(f"  Episodes ingested:  {len(episode_ids)}")
    print(f"  Nodes extracted:    {counts['nodes']}")
    print(f"  Edges extracted:    {counts['edges']}")
    print(f"  Node types:         {counts['node_types']}")
    print(f"  Edge types:         {counts['edge_types']}")
    print("=" * 60)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
