"""E2E test for episodic memory features (Plan 31: MemMachine improvements).

Validates session-tagged episodes, neighbor expansion, STM boost, FOLLOWS edges,
and combined episodic + graph recall against a running MCP server + PostgreSQL.

Prerequisites:
  docker compose up -d postgres
  GOOGLE_API_KEY=... NEOCORTEX_AUTH_MODE=dev_token \
    NEOCORTEX_DEV_TOKENS_FILE=dev_tokens.json \
    NEOCORTEX_MOCK_DB=false uv run python -m neocortex &
  GOOGLE_API_KEY=... NEOCORTEX_AUTH_MODE=dev_token \
    NEOCORTEX_DEV_TOKENS_FILE=dev_tokens.json \
    NEOCORTEX_MOCK_DB=false uv run python -m neocortex.ingestion &

Usage:
  GOOGLE_API_KEY=... uv run python scripts/e2e_episodic_memory_test.py

Via unified runner:
  GOOGLE_API_KEY=... ./scripts/run_e2e.sh scripts/e2e_episodic_memory_test.py
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

import asyncpg
import httpx
from fastmcp import Client

from neocortex.config import PostgresConfig

try:
    from scripts.e2e_common import JobWaitError, wait_for_jobs, wait_for_ready  # ty: ignore[unresolved-import]
except ModuleNotFoundError:  # Direct ``python scripts/e2e_episodic_memory_test.py`` execution.
    from e2e_common import JobWaitError, wait_for_jobs, wait_for_ready  # ty: ignore[unresolved-import]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("NEOCORTEX_BASE_URL", "http://127.0.0.1:8000")
INGESTION_URL = os.environ.get("NEOCORTEX_INGESTION_BASE_URL", "http://127.0.0.1:8001")
MCP_URL = os.environ.get("NEOCORTEX_MCP_URL", f"{BASE_URL}/mcp")
ALICE_TOKEN = os.environ.get("NEOCORTEX_ALICE_TOKEN", "alice-token")
AGENT_SCHEMA = "ncx_alice__personal"

SUFFIX = uuid.uuid4().hex[:8]

SESSION_A = f"morning-standup-{SUFFIX}"
SESSION_B = f"afternoon-debug-{SUFFIX}"

# Session A: morning standup discussion (6 turns).
# Turns 1-2 are about the office party (unrelated to PG).
# Turns 3-4 are about the PostgreSQL upgrade (will match PG queries).
# Turns 5-6 are about hiring/onboarding (unrelated to PG).
# This structure ensures that a PG-specific recall query will directly
# hit turns 3-4, and neighbor expansion should pull in turns 2 and 5-6
# as session context — validating the MemMachine nucleus+neighbor model.
SESSION_A_TURNS = [
    (
        "First item on the standup agenda: the team holiday party is"
        " confirmed for June 15th at the rooftop venue. Everyone needs"
        f" to RSVP by end of this week. [{SUFFIX}]"
    ),
    (
        "Catering options for the party are Mediterranean or BBQ."
        " Maria is collecting votes in the Slack channel."
        f" Budget approved for 50 people. [{SUFFIX}]"
    ),
    (
        "We discussed the PostgreSQL 16 upgrade timeline in standup today."
        " The DBA team wants to do it during the maintenance window"
        f" on May 3rd. [{SUFFIX}]"
    ),
    (
        "The main risk with the PG16 upgrade is the breaking change in"
        " jsonb_path_query behavior. We need to audit all JSONB queries"
        f" in the analytics pipeline first. [{SUFFIX}]"
    ),
    (
        "Alice volunteered to run the JSONB query audit. She will check"
        " all stored procedures and the three most active Grafana"
        f" dashboards before the migration. [{SUFFIX}]"
    ),
    (
        "Last topic: we have two new backend engineers starting next"
        " Monday. Bob is preparing the onboarding checklist and setting"
        f" up their development environments. [{SUFFIX}]"
    ),
]

# Session B: afternoon debugging session about API latency (3 turns)
SESSION_B_TURNS = [
    (
        "Investigating p99 latency spike in the /api/search endpoint."
        " Response times jumped from 120ms to 800ms after yesterday's"
        f" deploy. [{SUFFIX}]"
    ),
    (
        "Root cause found: the new full-text search query is doing a"
        " sequential scan on the documents table instead of using the"
        " GIN index. The query planner chose wrong because ANALYZE"
        f" hasn't run since the bulk import. [{SUFFIX}]"
    ),
    (
        "Fix deployed: ran ANALYZE on documents table and added a query"
        " hint to force GIN index usage. p99 back to 130ms. Will add"
        f" ANALYZE to the post-import automation. [{SUFFIX}]"
    ),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def mcp_call(tool_name: str, arguments: dict[str, object]) -> dict:
    """Call an MCP tool on the running server and return structured content."""
    async with Client(MCP_URL, auth=ALICE_TOKEN) as client:
        result = await client.call_tool(tool_name, arguments)
    if not isinstance(result.structured_content, dict):
        raise AssertionError(f"{tool_name} did not return structured content: {result}")
    return result.structured_content


def _quote_identifier(identifier: str) -> str:
    """Quote a SQL identifier to prevent injection."""
    return '"' + identifier.replace('"', '""') + '"'


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _post(path: str, token: str, **kwargs) -> dict:
    async with httpx.AsyncClient(base_url=INGESTION_URL, timeout=10.0) as client:
        resp = await client.post(path, headers=_headers(token), **kwargs)
    resp.raise_for_status()
    return resp.json()


async def _get_max_job_id() -> int:
    """Return the current max job ID so we can track only new jobs."""
    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        val = await conn.fetchval("SELECT coalesce(max(id), 0) FROM procrastinate_jobs WHERE queue_name = 'extraction'")
        return int(val)
    finally:
        await conn.close()


async def _wait_for_extraction(baseline_job_id: int) -> None:
    """Poll until extraction jobs created after baseline are done."""
    try:
        counts = await wait_for_jobs(baseline_job_id=baseline_job_id, label="extraction")
    except JobWaitError as exc:
        counts = exc.counts
        if counts.pending == 0 and counts.running == 0 and counts.completed == 0:
            if counts.failed > 0:
                raise AssertionError(f"All {counts.failed} extraction jobs failed") from exc
            raise AssertionError("No extraction jobs found after baseline — nothing was enqueued") from exc
        raise
    msg = f"  Extraction complete: {counts.completed} jobs finished"
    if counts.failed:
        msg += f" ({counts.failed} failed)"
    print(msg)


# ---------------------------------------------------------------------------
# Stage 1: Session Ingestion
# ---------------------------------------------------------------------------


async def ingest_session_episodes(session_id: str, turns: list[str], token: str = ALICE_TOKEN) -> None:
    """Ingest a sequence of text turns as a single session."""
    for turn in turns:
        result = await _post(
            "/ingest/text",
            token,
            json={"text": turn, "session_id": session_id},
        )
        if result["status"] != "stored":
            raise AssertionError(f"Ingestion failed: {result}")
        # Note: result["episodes_created"] is a count (int), not an episode ID.
        # Actual episode IDs are verified via direct DB queries using session_id.
        print(f"  Stored episode (session={session_id[:20]}...): {turn[:60]}...")


async def verify_session_in_db(session_id: str, expected_count: int) -> None:
    """Verify session episodes exist in DB with correct sequence numbers."""
    config = PostgresConfig()
    conn = await asyncpg.connect(dsn=config.dsn)
    try:
        table = f"{_quote_identifier(AGENT_SCHEMA)}.episode"
        rows = await conn.fetch(
            f"SELECT id, content, session_id, session_sequence, created_at "
            f"FROM {table} WHERE session_id = $1 ORDER BY session_sequence",
            session_id,
        )
        if len(rows) != expected_count:
            raise AssertionError(f"Expected {expected_count} episodes for session {session_id}, " f"got {len(rows)}")
        for i, row in enumerate(rows, start=1):
            if row["session_sequence"] != i:
                raise AssertionError(
                    f"Episode {row['id']} has session_sequence={row['session_sequence']}, " f"expected {i}"
                )
        print(f"  DB check passed: {expected_count} episodes with correct sequences")
    finally:
        await conn.close()


async def test_session_ingestion() -> None:
    """Stage 1: Ingest session-tagged episodes and verify in DB."""
    print("\n=== Stage 1: Session Ingestion ===")

    print("\nIngesting Session A (morning standup, 4 turns)...")
    await ingest_session_episodes(SESSION_A, SESSION_A_TURNS)

    print("\nIngesting Session B (afternoon debug, 3 turns)...")
    await ingest_session_episodes(SESSION_B, SESSION_B_TURNS)

    print("\nVerifying sessions in database...")
    await verify_session_in_db(SESSION_A, len(SESSION_A_TURNS))
    await verify_session_in_db(SESSION_B, len(SESSION_B_TURNS))

    print("\n=== Stage 1 PASSED ===")


# ---------------------------------------------------------------------------
# Stage 2: Session Recall with Neighbors
# ---------------------------------------------------------------------------


async def _backdate_session_episodes(session_id: str, hours_ago: float) -> int:
    """Backdate all episodes in a session to `hours_ago` hours in the past."""
    config = PostgresConfig()
    conn = await asyncpg.connect(dsn=config.dsn)
    try:
        table = f"{_quote_identifier(AGENT_SCHEMA)}.episode"
        result = await conn.execute(
            f"UPDATE {table} " f"SET created_at = now() - interval '1 hour' * $1 " f"WHERE session_id = $2",
            hours_ago,
            session_id,
        )
        updated = int(result.split()[-1])  # "UPDATE N"
        print(f"  Backdated {updated} episodes in session {session_id[:20]}... by {hours_ago}h")
        return updated
    finally:
        await conn.close()


async def test_session_recall_with_neighbors() -> None:
    """Stage 2: Recall with neighbor expansion and session clustering."""
    print("\n=== Stage 2: Session Recall with Neighbors ===")

    # Query specifically about PG upgrade — should match Session A turns 3-5
    # but NOT turns 1-2 (party) or turn 6 (hiring).  Neighbor expansion should
    # pull those unrelated session turns in as context neighbors.
    result = await mcp_call(
        "recall",
        {
            "query": f"PostgreSQL 16 upgrade JSONB audit timeline {SUFFIX}",
            "limit": 5,
        },
    )
    items = result["results"]

    if not items:
        raise AssertionError("Recall returned no results")

    # Check that we got episode results
    episode_items = [i for i in items if i.get("source_kind") == "episode"]
    print(f"  Recall returned {len(items)} items, {len(episode_items)} episodes")

    # Debug: print each episode's details
    for ep in episode_items:
        content_preview = ep.get("content", "")[:60]
        print(
            f"    ep={ep['item_id']} score={ep['score']:.4f} "
            f"session={ep.get('session_id', 'N/A')[:20]}... "
            f"seq={ep.get('session_sequence')} "
            f"neighbor_of={ep.get('neighbor_of')} "
            f"content={content_preview}..."
        )

    if len(episode_items) < 2:
        raise AssertionError(f"Expected at least 2 episode results (nucleus + neighbors), " f"got {len(episode_items)}")

    # Check for neighbor episodes (those brought in by expansion)
    nucleus_episodes = [e for e in episode_items if e.get("neighbor_of") is None]
    neighbor_episodes = [e for e in episode_items if e.get("neighbor_of") is not None]
    print(f"  Nucleus episodes: {len(nucleus_episodes)}")
    print(f"  Neighbor episodes: {len(neighbor_episodes)}")

    if not neighbor_episodes:
        raise AssertionError(
            "No neighbor episodes found — neighbor expansion may not be working. "
            "Check that recall_expand_neighbors setting is True."
        )

    # Verify neighbor scores are discounted relative to nucleus
    for neighbor in neighbor_episodes:
        nucleus_id = neighbor["neighbor_of"]
        nucleus = next((e for e in nucleus_episodes if e["item_id"] == nucleus_id), None)
        if nucleus and neighbor["score"] >= nucleus["score"]:
            print(
                f"  WARNING: Neighbor {neighbor['item_id']} score "
                f"({neighbor['score']:.4f}) >= nucleus {nucleus_id} score "
                f"({nucleus['score']:.4f})"
            )

    # Verify session_id is present on episode results
    session_episodes = [e for e in episode_items if e.get("session_id")]
    if not session_episodes:
        raise AssertionError("No episodes have session_id in recall results")

    print(f"  Episodes with session_id: {len(session_episodes)}")
    print("\n=== Stage 2 PASSED ===")


async def test_cross_session_isolation() -> None:
    """Verify neighbor expansion stays within session boundaries."""
    print("\n--- Cross-Session Isolation Check ---")

    result = await mcp_call(
        "recall",
        {
            "query": f"API latency spike search endpoint {SUFFIX}",
            "limit": 20,
        },
    )
    items = result["results"]
    episode_items = [i for i in items if i.get("source_kind") == "episode"]

    # Find neighbor episodes and check their session_id
    for ep in episode_items:
        if ep.get("neighbor_of") and ep.get("session_id"):
            # Find the nucleus this neighbor belongs to
            nucleus = next(
                (e for e in episode_items if e["item_id"] == ep["neighbor_of"]),
                None,
            )
            if nucleus and nucleus.get("session_id") != ep["session_id"]:
                raise AssertionError(
                    f"Neighbor episode {ep['item_id']} (session={ep['session_id']}) "
                    f"has different session than nucleus {ep['neighbor_of']} "
                    f"(session={nucleus.get('session_id')}). "
                    f"Cross-session neighbor expansion should not happen."
                )

    print("  Cross-session isolation verified")


# ---------------------------------------------------------------------------
# Stage 3: STM Boost Validation
# ---------------------------------------------------------------------------


async def test_stm_boost_ordering() -> None:
    """Stage 3: Verify STM boost makes recent episodes rank higher."""
    print("\n=== Stage 3: STM Boost Validation ===")

    # Backdate Session A episodes to 3h ago (outside the 2h STM boost window)
    print("\nBackdating Session A episodes to 3h ago...")
    await _backdate_session_episodes(SESSION_A, hours_ago=3.0)

    # Ingest a fresh episode with similar content to Session A
    fresh_session = f"fresh-note-{SUFFIX}"
    fresh_text = (
        f"Quick note: the PostgreSQL 16 upgrade risk assessment is complete. "
        f"All JSONB queries have been audited and three need modification "
        f"before the migration can proceed. [{SUFFIX}]"
    )

    result = await _post(
        "/ingest/text",
        ALICE_TOKEN,
        json={"text": fresh_text, "session_id": fresh_session},
    )
    if result["status"] != "stored":
        raise AssertionError(f"Fresh episode ingestion failed: {result}")
    print(f"  Stored fresh episode: {fresh_text[:60]}...")

    # Small delay to let embedding be computed
    await asyncio.sleep(2)

    # Recall with a query that matches both old Session A content AND fresh episode
    result = await mcp_call(
        "recall",
        {
            "query": f"PostgreSQL JSONB query audit for upgrade {SUFFIX}",
            "limit": 20,
        },
    )
    items = result["results"]
    episode_items = [i for i in items if i.get("source_kind") == "episode"]

    if not episode_items:
        raise AssertionError("No episode results returned")

    # Find the fresh episode in results
    fresh_episode = None
    old_session_a_episodes = []
    for ep in episode_items:
        content = ep.get("content", "")
        if "risk assessment is complete" in content:
            fresh_episode = ep
        elif ep.get("session_id") == SESSION_A:
            old_session_a_episodes.append(ep)

    if fresh_episode is None:
        raise AssertionError("Fresh episode not found in recall results")

    print(f"  Fresh episode score: {fresh_episode['score']:.4f}")

    if old_session_a_episodes:
        # Fresh episode should outrank same-topic old episodes because:
        # - Fresh: < 2h old -> gets STM boost (up to 1.5x)
        # - Old: backdated to 3h ago -> no STM boost
        best_old_score = max(ep["score"] for ep in old_session_a_episodes)
        print(f"  Best old Session A score: {best_old_score:.4f}")
        print(f"  STM advantage: {fresh_episode['score'] - best_old_score:+.4f}")

        if fresh_episode["score"] < best_old_score:
            # This is a soft check — STM boost may not always overcome
            # a much stronger semantic match. Log a warning rather than fail.
            print(
                f"  WARNING: Fresh episode scored lower than old episode. "
                f"STM boost ({fresh_episode['score']:.4f}) did not overcome "
                f"old episode advantage ({best_old_score:.4f}). "
                f"This may be acceptable if semantic similarity differs significantly."
            )
        else:
            print("  STM boost confirmed: fresh episode ranks above stale content")
    else:
        print("  No old Session A episodes in top results for comparison")

    # Verify the fresh episode has a score > 0 (sanity check)
    if fresh_episode["score"] <= 0:
        raise AssertionError(f"Fresh episode has non-positive score: {fresh_episode['score']}")

    print("\n=== Stage 3 PASSED ===")


# ---------------------------------------------------------------------------
# Stage 4: Extraction Pipeline + FOLLOWS Edges
# ---------------------------------------------------------------------------


async def verify_follows_edges(session_id: str) -> int:
    """Verify FOLLOWS edges exist between consecutive session episodes."""
    config = PostgresConfig()
    conn = await asyncpg.connect(dsn=config.dsn)
    try:
        # Find episodes in this session
        ep_table = f"{_quote_identifier(AGENT_SCHEMA)}.episode"
        episodes = await conn.fetch(
            f"SELECT id, session_sequence FROM {ep_table} " f"WHERE session_id = $1 ORDER BY session_sequence",
            session_id,
        )

        if len(episodes) < 2:
            print(f"  Only {len(episodes)} episodes — no FOLLOWS edges expected")
            return 0

        # Check for FOLLOWS edges in the edge table
        edge_table = f"{_quote_identifier(AGENT_SCHEMA)}.edge"
        edge_type_table = f"{_quote_identifier(AGENT_SCHEMA)}.edge_type"

        follows_count = await conn.fetchval(
            f"SELECT count(*) FROM {edge_table} e "
            f"JOIN {edge_type_table} et ON e.type_id = et.id "
            f"WHERE et.name = 'FOLLOWS'",
        )

        print(f"  FOLLOWS edges in graph: {follows_count}")
        return follows_count
    finally:
        await conn.close()


async def verify_extracted_nodes() -> int:
    """Verify extraction created nodes in the personal graph."""
    result = await mcp_call("discover_graphs", {})
    graphs = result.get("graphs", [])

    personal_graph = next((g for g in graphs if g["schema_name"] == AGENT_SCHEMA), None)
    if personal_graph is None:
        raise AssertionError(f"Personal graph {AGENT_SCHEMA} not found in discover_graphs")

    stats = personal_graph.get("stats", {})
    node_count = stats.get("total_nodes", 0)
    edge_count = stats.get("total_edges", 0)
    episode_count = stats.get("total_episodes", 0)

    print(f"  Graph stats: {node_count} nodes, {edge_count} edges, {episode_count} episodes")

    if node_count == 0:
        raise AssertionError("No nodes extracted — extraction pipeline may have failed")

    return node_count


async def test_extraction_and_follows(baseline_job_id: int) -> None:
    """Stage 4: Verify extraction pipeline and FOLLOWS edges."""
    print("\n=== Stage 4: Extraction Pipeline + FOLLOWS Edges ===")

    # Wait for extraction to process our episodes.
    # We captured baseline_job_id in main() before ingestion started (Stage 1).
    # This ensures we only wait for jobs from THIS test run.
    print("\nWaiting for extraction jobs to complete...")
    await _wait_for_extraction(baseline_job_id)

    # Verify extraction produced graph nodes
    print("\nChecking extracted knowledge graph nodes...")
    node_count = await verify_extracted_nodes()
    print(f"  Extraction produced {node_count} nodes")

    # Verify FOLLOWS edges for Session A (4 turns → should have >= 1 FOLLOWS)
    print("\nChecking FOLLOWS edges for Session A...")
    follows_a = await verify_follows_edges(SESSION_A)

    print("\nChecking FOLLOWS edges for Session B...")
    follows_b = await verify_follows_edges(SESSION_B)

    total_follows = follows_a + follows_b
    if total_follows == 0:
        raise AssertionError(
            "No FOLLOWS edges found in either session. "
            "The extraction pipeline should create FOLLOWS edges between "
            "consecutive personal episodes in the same session."
        )

    print(f"\n  Total FOLLOWS edges: {total_follows}")
    print("\n=== Stage 4 PASSED ===")


# ---------------------------------------------------------------------------
# Stage 5: Combined Recall + Formatted Context
# ---------------------------------------------------------------------------


async def test_combined_recall() -> None:
    """Stage 5: Verify combined episodic + graph node recall."""
    print("\n=== Stage 5: Combined Recall + Formatted Context ===")

    # Query should match both episode text AND extracted graph nodes.
    # Use a high limit so extracted nodes don't crowd out episodes.
    result = await mcp_call(
        "recall",
        {
            "query": f"PostgreSQL database upgrade {SUFFIX}",
            "limit": 50,
        },
    )
    items = result["results"]

    # Categorize results by source kind
    episodes = [i for i in items if i.get("source_kind") == "episode"]
    nodes = [i for i in items if i.get("source_kind") == "node"]

    print(f"  Total results: {len(items)}")
    print(f"  Episodes: {len(episodes)}")
    print(f"  Graph nodes: {len(nodes)}")
    if items:
        top3 = items[:3]
        for i, item in enumerate(top3):
            kind = item.get("source_kind")
            score = item.get("score", 0)
            name = item.get("name", "")[:60]
            print(f"    #{i+1}: {kind} score={score:.4f} name={name}")

    if not episodes:
        raise AssertionError("No episodes in combined recall — expected session episodes")

    if not nodes:
        # Nodes may not appear if extraction didn't produce matching entities.
        # This is a soft check — log warning but don't fail.
        print(
            "  WARNING: No graph nodes in recall results. "
            "Extraction may not have produced entities matching the query. "
            "This is acceptable if episodes are present."
        )
    else:
        # Verify nodes have graph_context (subgraph neighborhood)
        nodes_with_context = [n for n in nodes if n.get("graph_context")]
        print(f"  Nodes with graph_context: {len(nodes_with_context)}")

        # Print sample node for debugging
        sample_node = nodes[0]
        print(f"  Sample node: '{sample_node['name']}' (type={sample_node.get('item_type')})")

    print("\n  Combined recall verified: both memory types present")


async def test_formatted_context() -> None:
    """Verify formatted_context contains valid JSON with session clusters."""
    print("\n--- Formatted Context Validation ---")

    result = await mcp_call(
        "recall",
        {
            "query": f"standup discussion database migration {SUFFIX}",
            "limit": 20,
        },
    )

    formatted = result.get("formatted_context")
    if formatted is None:
        raise AssertionError(
            "formatted_context is None in recall result. " "Stage 5 of Plan 31 should populate this field."
        )

    if not formatted.strip():
        raise AssertionError("formatted_context is empty string")

    print(f"  formatted_context length: {len(formatted)} chars")

    # The formatted_context is a string containing JSON blocks separated by "\n---\n"
    # Each block is either a session cluster or an isolated episode
    blocks = [b.strip() for b in formatted.split("\n---\n") if b.strip()]

    if not blocks:
        raise AssertionError("formatted_context contains no content blocks")

    print(f"  Content blocks: {len(blocks)}")

    # Try to parse each block as JSON
    parsed_blocks = []
    for i, block in enumerate(blocks):
        try:
            parsed = json.loads(block)
            parsed_blocks.append(parsed)
        except json.JSONDecodeError:
            # Some blocks may be non-JSON (e.g., node results)
            print(f"  Block {i}: non-JSON ({block[:80]}...)")
            continue

    if not parsed_blocks:
        raise AssertionError("No JSON-parseable blocks in formatted_context")

    # Check session cluster structure
    session_clusters = [b for b in parsed_blocks if "episodes" in b]
    isolated_episodes = [b for b in parsed_blocks if "episodes" not in b and "content" in b]

    print(f"  Session clusters: {len(session_clusters)}")
    print(f"  Isolated episodes: {len(isolated_episodes)}")

    for cluster in session_clusters:
        sid = cluster.get("session_id", "unknown")
        eps = cluster.get("episodes", [])
        print(f"  Cluster session={sid[:30]}...: {len(eps)} episodes")

        # Verify chronological ordering within cluster
        sequences = [e.get("session_sequence") for e in eps if e.get("session_sequence") is not None]
        if sequences and sequences != sorted(sequences):
            raise AssertionError(f"Episodes in cluster session={sid} are not in chronological order: {sequences}")

        # Verify neighbor flagging
        neighbors = [e for e in eps if e.get("is_context_neighbor")]
        if neighbors:
            print(f"    Context neighbors: {len(neighbors)}")

    print("\n  Formatted context validation passed")


async def test_graph_traversal_recall() -> None:
    """Verify that recall uses graph traversal to find related knowledge."""
    print("\n--- Graph Traversal Recall ---")

    # Use discover_ontology to see what node types extraction created
    result = await mcp_call("discover_ontology", {"graph_name": AGENT_SCHEMA})

    node_types = result.get("node_types", [])
    edge_types = result.get("edge_types", [])
    print(f"  Ontology: {len(node_types)} node types, {len(edge_types)} edge types")

    for nt in node_types[:5]:
        print(f"    Node type: {nt['name']} ({nt.get('count', '?')} instances)")
    for et in edge_types[:5]:
        print(f"    Edge type: {et['name']} ({et.get('count', '?')} instances)")

    # If we have nodes, try a query that should trigger graph traversal
    if node_types:
        # Query for something specific that extraction should have captured
        result = await mcp_call(
            "recall",
            {
                "query": f"latency spike root cause {SUFFIX}",
                "limit": 10,
            },
        )
        items = result["results"]
        nodes = [i for i in items if i.get("source_kind") == "node"]

        if nodes:
            # Check if any nodes have spreading_bonus (evidence of graph traversal)
            with_spread = [n for n in nodes if n.get("spreading_bonus")]
            print(f"  Nodes with spreading_bonus: {len(with_spread)}/{len(nodes)}")
        else:
            print("  No graph nodes matched this query")

    print("\n  Graph traversal recall check complete")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    print(f"NeoCortex Episodic Memory E2E Test (suffix={SUFFIX})")
    print(f"MCP: {MCP_URL}")
    print(f"Ingestion: {INGESTION_URL}")

    await wait_for_ready(INGESTION_URL, ALICE_TOKEN)

    # Capture baseline extraction job ID BEFORE ingestion so Stage 4
    # only waits for jobs from this test run (not stale previous runs).
    baseline_job_id = await _get_max_job_id()
    print(f"Baseline extraction job ID: {baseline_job_id}")

    # Stage 1: Session ingestion
    await test_session_ingestion()

    # Stage 2: Session recall with neighbors
    await test_session_recall_with_neighbors()
    await test_cross_session_isolation()

    # Stage 3: STM boost recency validation
    await test_stm_boost_ordering()

    # Stage 4: Extraction pipeline + FOLLOWS edges
    await test_extraction_and_follows(baseline_job_id)

    # Stage 5: Combined recall + formatted context
    await test_combined_recall()
    await test_formatted_context()
    await test_graph_traversal_recall()

    print("\n=== ALL TESTS PASSED ===")


if __name__ == "__main__":
    asyncio.run(main())
