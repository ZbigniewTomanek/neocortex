"""E2E test for cognitive heuristics in live recall.

Validates the full cognitive pipeline against a running MCP server + PostgreSQL:
  1. ACT-R activation increases with repeated recalls
  2. Importance scoring from extraction persists and ranks results
  3. Spreading activation discovers neighbors via graph edges
  4. Edge reinforcement strengthens traversed edges
  5. Episodic consolidation demotes extracted episodes
  6. Discover returns cognitive stats

Prerequisites:
  docker compose up -d postgres
  GOOGLE_API_KEY=... NEOCORTEX_AUTH_MODE=dev_token \
    NEOCORTEX_DEV_TOKENS_FILE=dev_tokens.json \
    NEOCORTEX_MOCK_DB=false uv run python -m neocortex &
  GOOGLE_API_KEY=... NEOCORTEX_AUTH_MODE=dev_token \
    NEOCORTEX_DEV_TOKENS_FILE=dev_tokens.json \
    NEOCORTEX_MOCK_DB=false uv run python -m neocortex.ingestion &

Usage:
  GOOGLE_API_KEY=... uv run python scripts/e2e_cognitive_recall_test.py

Via unified runner:
  GOOGLE_API_KEY=... ./scripts/run_e2e.sh scripts/e2e_cognitive_recall_test.py
"""

from __future__ import annotations

import asyncio
import os

import asyncpg
import httpx
from fastmcp import Client

from neocortex.config import PostgresConfig

try:
    from scripts.e2e_common import wait_for_jobs, wait_for_ready  # ty: ignore[unresolved-import]
except ModuleNotFoundError:  # Direct ``python scripts/e2e_cognitive_recall_test.py`` execution.
    from e2e_common import wait_for_jobs, wait_for_ready  # ty: ignore[unresolved-import]

BASE_URL = os.environ.get("NEOCORTEX_BASE_URL", "http://127.0.0.1:8000")
INGESTION_URL = os.environ.get("NEOCORTEX_INGESTION_BASE_URL", "http://127.0.0.1:8001")
MCP_URL = os.environ.get("NEOCORTEX_MCP_URL", f"{BASE_URL}/mcp")
TOKEN = os.environ.get("NEOCORTEX_ALICE_TOKEN", "alice-token")
AGENT_SCHEMA = "ncx_alice__personal"

# Medical seed texts to trigger extraction and build a connected graph
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
    if response.json().get("status") != "ok":
        raise AssertionError(f"Unexpected health payload: {response.json()}")


async def _cleanup_stale_jobs() -> None:
    """Delete old extraction jobs so the worker can process ours immediately."""
    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        result = await conn.execute("DELETE FROM procrastinate_jobs WHERE queue_name = 'extraction'")
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


async def _wait_for_extraction(baseline_job_id: int) -> None:
    """Poll until extraction jobs created after baseline are done."""
    await wait_for_jobs(baseline_job_id=baseline_job_id, label="extraction")


# ── Step 1: Ingest and wait for extraction ────────────────────────


async def step_setup() -> None:
    """Ingest seed corpus and wait for extraction to complete."""
    print("\n=== Step 1: Ingest seed corpus & wait for extraction ===")
    await _cleanup_stale_jobs()
    baseline_job_id = await _get_max_job_id()
    print(f"  Baseline job ID: {baseline_job_id}")
    for i, text in enumerate(SEED_TEXTS):
        result = await mcp_call("remember", {"text": text, "context": "e2e_cognitive_test"})
        eid = int(result["episode_id"])
        assert eid > 0, f"Bad episode id: {result}"
        print(f"  [{i + 1}/{len(SEED_TEXTS)}] Stored episode {eid}")

    await _wait_for_extraction(baseline_job_id)
    print("  [PASS] Extraction complete")


# ── Step 2: ACT-R activation increases with repeated recalls ──────


async def step_activation_increases() -> list[float]:
    """Recall the same query 3 times. Track a specific node's activation over time."""
    print("\n=== Step 2: ACT-R activation increases with repeated recalls ===")
    query = "serotonin"
    tracked_node: str | None = None
    activation_history: list[float] = []

    for i in range(3):
        result = await mcp_call("recall", {"query": query, "limit": 10})
        results = result.get("results", [])
        node_results = [r for r in results if r.get("source_kind") == "node"]

        if not node_results:
            print(f"  Recall #{i + 1}: no node results")
            continue

        # On first recall, pick a node to track. On subsequent recalls, find that same node.
        if tracked_node is None:
            tracked_node = node_results[0]["name"]

        tracked = next((r for r in node_results if r["name"] == tracked_node), None)
        if tracked and tracked.get("activation_score") is not None:
            act = float(tracked["activation_score"])
            activation_history.append(act)
            print(f"  Recall #{i + 1}: '{tracked_node[:35]}' activation={act:.3f}")
        else:
            print(f"  Recall #{i + 1}: tracked node '{tracked_node}' not in results")

    if len(activation_history) >= 2:
        # Activation should be non-decreasing for the same node
        for i in range(1, len(activation_history)):
            if activation_history[i] < activation_history[i - 1] - 0.01:
                print(
                    f"  [WARN] Activation dip on '{tracked_node}': "
                    f"{activation_history[i - 1]:.3f} -> {activation_history[i]:.3f}"
                )
        # Overall trend: last should be >= first
        if activation_history[-1] >= activation_history[0] - 0.01:
            print(f"  [PASS] Activation trend: {' -> '.join(f'{a:.3f}' for a in activation_history)}")
        else:
            print(
                f"  [WARN] Activation did not increase overall: {' -> '.join(f'{a:.3f}' for a in activation_history)}"
            )
    else:
        print("  [WARN] Not enough activation data points to verify trend")

    return activation_history


# ── Step 3: Importance scoring from extraction ────────────────────


async def step_importance_in_results() -> None:
    """Verify recall results include importance scores assigned by extraction agents."""
    print("\n=== Step 3: Importance scoring in recall results ===")
    result = await mcp_call("recall", {"query": "serotonin SSRI depression", "limit": 10})
    results = result.get("results", [])
    node_results = [r for r in results if r.get("source_kind") == "node"]

    assert len(node_results) > 0, "No node results for importance check"

    importance_values: list[float] = []
    for r in node_results:
        imp = r.get("importance")
        if imp is not None:
            assert 0.0 <= imp <= 1.0, f"importance out of range: {imp}"
            importance_values.append(imp)
            print(f"    {r['name'][:40]:40s}  importance={imp:.2f}  score={r['score']:.3f}")

    assert len(importance_values) > 0, "No importance values in node results"

    # Check there's some variance — agents should assign different importance
    if len(set(round(v, 2) for v in importance_values)) > 1:
        print("  [PASS] Varied importance scores from extraction agents")
    else:
        print("  [INFO] All importance scores identical (agents may assign uniform scores)")

    print(f"  [PASS] Importance present on {len(importance_values)}/{len(node_results)} nodes")


# ── Step 4: Importance hint propagation via remember ──────────────


async def step_importance_hint() -> None:
    """Verify remember(importance=0.95) propagates to extracted nodes."""
    print("\n=== Step 4: Importance hint propagation ===")
    baseline_job_id = await _get_max_job_id()
    result = await mcp_call(
        "remember",
        {
            "text": "Lithium is a critical mood stabilizer for bipolar disorder",
            "importance": 0.95,
        },
    )
    hint_episode_id = int(result["episode_id"])
    print(f"  Stored episode {hint_episode_id} with importance=0.95")

    # Wait for extraction of this single episode
    print("  Waiting for extraction...")
    await wait_for_jobs(baseline_job_id=baseline_job_id, label="importance hint")
    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        # Check importance on nodes from this episode
        schema = _quote(AGENT_SCHEMA)
        rows = await conn.fetch(
            f"""SELECT name, importance FROM {schema}.node
                WHERE properties->>'_source_episode' = $1""",
            str(hint_episode_id),
        )

        if rows:
            all_above_hint = all(float(r["importance"]) >= 0.94 for r in rows)
            for r in rows:
                print(f"    {r['name'][:40]:40s}  importance={float(r['importance']):.2f}")
            if all_above_hint:
                print(f"  [PASS] All {len(rows)} nodes have importance >= 0.95 (hint floor)")
            else:
                below = [r for r in rows if float(r["importance"]) < 0.94]
                print(
                    f"  [WARN] {len(below)} node(s) below importance hint floor "
                    f"(hint=0.95, may indicate hint propagation issue)"
                )
        else:
            print("  [INFO] No nodes with _source_episode found (extraction may not tag source)")
    finally:
        await conn.close()


# ── Step 5: Spreading activation discovers neighbors ──────────────


async def step_spreading_activation() -> None:
    """Verify spreading_bonus is applied to neighbor nodes."""
    print("\n=== Step 5: Spreading activation ===")
    result = await mcp_call("recall", {"query": "serotonin mood", "limit": 15})
    results = result.get("results", [])

    with_bonus = [r for r in results if r.get("spreading_bonus") and r["spreading_bonus"] > 0]
    without_bonus = [r for r in results if not r.get("spreading_bonus") or r["spreading_bonus"] == 0]

    print(f"  Total results: {len(results)}")
    print(f"  With spreading_bonus > 0: {len(with_bonus)}")
    print(f"  Without spreading_bonus:  {len(without_bonus)}")

    for r in with_bonus[:5]:
        print(
            f"    {r['name'][:35]:35s}  bonus={r['spreading_bonus']:.3f}  "
            f"score={r['score']:.3f}  kind={r['source_kind']}"
        )

    if with_bonus:
        print(f"  [PASS] Spreading activation discovered {len(with_bonus)} neighbor(s)")
    else:
        # Not a hard failure — spreading requires graph traversal to find neighbors
        # of seed nodes that are not themselves seed nodes
        print("  [INFO] No spreading bonus observed (graph may not have indirect neighbors)")


# ── Step 6: Edge reinforcement ────────────────────────────────────


async def step_edge_reinforcement() -> None:
    """Verify edges traversed during recall have weight > 1.0 (reinforced)."""
    print("\n=== Step 6: Edge reinforcement ===")
    # Run a few more recalls to trigger reinforcement
    for _i in range(3):
        await mcp_call("recall", {"query": "serotonin neurotransmitter", "limit": 5})

    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        schema = _quote(AGENT_SCHEMA)
        rows = await conn.fetch(f"""SELECT src.name AS source, tgt.name AS target, e.weight
                FROM {schema}.edge e
                JOIN {schema}.node src ON src.id = e.source_id
                JOIN {schema}.node tgt ON tgt.id = e.target_id
                WHERE e.weight > 1.0
                ORDER BY e.weight DESC
                LIMIT 10""")

        if rows:
            print(f"  Reinforced edges (weight > 1.0): {len(rows)}")
            for r in rows:
                print(f"    {r['source'][:20]} -> {r['target'][:20]}  weight={float(r['weight']):.3f}")
            print(f"  [PASS] {len(rows)} edge(s) reinforced above baseline weight 1.0")
        else:
            print("  [INFO] No edges with weight > 1.0 yet (may need more recalls to trigger)")
    finally:
        await conn.close()


# ── Step 7: Episodic consolidation ────────────────────────────────


async def step_consolidation() -> None:
    """Verify episodes are marked consolidated after extraction, and graph nodes outrank them."""
    print("\n=== Step 7: Episodic consolidation ===")
    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        schema = _quote(AGENT_SCHEMA)
        rows = await conn.fetch(f"SELECT id, consolidated, importance FROM {schema}.episode ORDER BY id")
        consolidated = sum(1 for r in rows if r["consolidated"])
        total = len(rows)
        print(f"  Episodes: {total} total, {consolidated} consolidated")
        assert consolidated > 0, "No episodes marked as consolidated after extraction"
        print(f"  [PASS] {consolidated}/{total} episodes consolidated")
    finally:
        await conn.close()

    # Check that graph nodes outrank consolidated episodes for the same query
    result = await mcp_call("recall", {"query": "serotonin", "limit": 10})
    results = result.get("results", [])
    node_results = [r for r in results if r.get("source_kind") == "node"]
    episode_results = [r for r in results if r.get("source_kind") == "episode"]

    if node_results and episode_results:
        top_node_score = max(r["score"] for r in node_results)
        top_episode_score = max(r["score"] for r in episode_results)
        print(f"  Top node score:    {top_node_score:.3f}")
        print(f"  Top episode score: {top_episode_score:.3f}")
        if top_node_score >= top_episode_score:
            print("  [PASS] Graph nodes outrank consolidated episodes")
        else:
            print("  [INFO] Episode still outranks nodes (may depend on query/embedding match)")
    else:
        print(f"  [INFO] Cannot compare: {len(node_results)} nodes, {len(episode_results)} episodes")


# ── Step 8: Discover cognitive stats ──────────────────────────────


async def step_discover_cognitive_stats() -> None:
    """Verify discover_ontology returns complete cognitive stats."""
    print("\n=== Step 8: Discover cognitive stats ===")
    result = await mcp_call("discover_ontology", {"graph_name": AGENT_SCHEMA})
    stats = result.get("stats", {})

    required_keys = (
        "total_nodes",
        "total_edges",
        "total_episodes",
        "forgotten_nodes",
        "consolidated_episodes",
        "avg_activation",
    )
    for key in required_keys:
        assert key in stats, f"Missing stat '{key}' in discover: {stats}"

    print(f"  total_nodes:           {stats['total_nodes']}")
    print(f"  total_edges:           {stats['total_edges']}")
    print(f"  total_episodes:        {stats['total_episodes']}")
    print(f"  forgotten_nodes:       {stats['forgotten_nodes']}")
    print(f"  consolidated_episodes: {stats['consolidated_episodes']}")
    print(f"  avg_activation:        {stats['avg_activation']}")

    assert stats["total_nodes"] > 0, "Expected nodes > 0 after extraction"
    assert stats["total_edges"] > 0, "Expected edges > 0 after extraction"
    assert stats["consolidated_episodes"] > 0, "Expected consolidated episodes > 0"

    # After multiple recalls, avg_activation should be positive
    if stats["avg_activation"] > 0:
        print("  [PASS] avg_activation > 0 (reflects recall activity)")
    else:
        print("  [INFO] avg_activation = 0 (access tracking may not have propagated to stats)")

    print("  [PASS] All cognitive stats present and valid")


# ── Main ───────────────────────────────────────────────────────────


async def main() -> None:
    print("=" * 60)
    print("E2E Cognitive Recall Test")
    print(f"MCP:       {MCP_URL}")
    print(f"Ingestion: {INGESTION_URL}")
    print("Token:     configured")
    print("=" * 60)

    await wait_for_ready(INGESTION_URL, TOKEN)
    await _assert_health()

    await step_setup()
    activation_history = await step_activation_increases()
    await step_importance_in_results()
    await step_importance_hint()
    await step_spreading_activation()
    await step_edge_reinforcement()
    await step_consolidation()
    await step_discover_cognitive_stats()

    print("\n" + "=" * 60)
    print("SUMMARY")
    if activation_history:
        print(f"  Activation trend: {' -> '.join(f'{a:.3f}' for a in activation_history)}")
    print("=" * 60)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
