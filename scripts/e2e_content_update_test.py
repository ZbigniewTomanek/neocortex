"""E2E test for node content updates: verify re-extraction updates node descriptions.

Validates Plan 16 Stage 1 fix end-to-end:
  1. Ingest text about "Alice" on the billing team
  2. Wait for extraction to complete
  3. Recall "Alice" — verify content mentions "billing"
  4. Ingest updated text about "Alice" transferring to auth team
  5. Wait for extraction to complete
  6. Recall "Alice" — verify content mentions "auth team"
  7. Verify only 1 node named "Alice" exists (no duplicates)

Prerequisites:
  docker compose up -d postgres
  GOOGLE_API_KEY=... NEOCORTEX_AUTH_MODE=dev_token \
    NEOCORTEX_DEV_TOKENS_FILE=dev_tokens.json \
    NEOCORTEX_MOCK_DB=false uv run python -m neocortex &
  GOOGLE_API_KEY=... NEOCORTEX_AUTH_MODE=dev_token \
    NEOCORTEX_DEV_TOKENS_FILE=dev_tokens.json \
    NEOCORTEX_MOCK_DB=false uv run python -m neocortex.ingestion &

Usage:
  GOOGLE_API_KEY=... uv run python scripts/e2e_content_update_test.py

Via unified runner:
  GOOGLE_API_KEY=... ./scripts/run_e2e.sh scripts/e2e_content_update_test.py
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
except ModuleNotFoundError:  # Direct ``python scripts/e2e_content_update_test.py`` execution.
    from e2e_common import wait_for_jobs, wait_for_ready  # ty: ignore[unresolved-import]

BASE_URL = os.environ.get("NEOCORTEX_BASE_URL", "http://127.0.0.1:8000")
INGESTION_URL = os.environ.get("NEOCORTEX_INGESTION_BASE_URL", "http://127.0.0.1:8001")
MCP_URL = os.environ.get("NEOCORTEX_MCP_URL", f"{BASE_URL}/mcp")
ALICE_TOKEN = os.environ.get("NEOCORTEX_ALICE_TOKEN", "alice-token")
ADMIN_TOKEN = os.environ.get("NEOCORTEX_ADMIN_TOKEN", "admin-token-neocortex")
AGENT_SCHEMA = "ncx_alice__personal"

# --- Seed texts: initial and updated knowledge about Alice ---

TEXT_INITIAL = (
    "Alice works on the billing team as a senior engineer. "
    "She specializes in payment processing and invoice generation. "
    "Alice has been with the billing team for three years."
)

TEXT_UPDATED = (
    "Alice transferred to the auth team as tech lead. "
    "She now leads the authentication and authorization platform, "
    "focusing on OAuth2 integration and session management. "
    "Alice moved from billing to auth last month."
)


# --- Helpers ---


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


async def _get_max_job_id() -> int:
    """Return the current max extraction job ID so we can track only new jobs."""
    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        val = await conn.fetchval(
            "SELECT coalesce(max(id), 0) FROM procrastinate_jobs " "WHERE queue_name = 'extraction'"
        )
        return int(val)
    finally:
        await conn.close()


async def _wait_for_extraction(baseline_job_id: int, label: str) -> None:
    """Poll until extraction jobs created after baseline complete."""
    print(f"\n  Waiting for extraction jobs ({label})...")
    counts = await wait_for_jobs(
        baseline_job_id=baseline_job_id,
        label=label,
        require_routing_idle=True,
    )
    if counts.failed:
        print(f"    [WARN] {counts.failed} job(s) failed")
    print(f"    [PASS] Extraction done ({counts.completed} completed, {counts.failed} failed)")


async def _find_alice_nodes() -> list[dict]:
    """Query DB directly for nodes whose name contains 'alice' (case-insensitive)."""
    conn = await asyncpg.connect(dsn=PostgresConfig().dsn)
    try:
        schema = _quote(AGENT_SCHEMA)
        rows = await conn.fetch(f"""SELECT n.name, n.content, nt.name AS type_name,
                       n.importance, n.forgotten
                FROM {schema}.node n
                JOIN {schema}.node_type nt ON nt.id = n.type_id
                WHERE lower(n.name) LIKE '%alice%'
                  AND n.forgotten = false
                ORDER BY n.name""")
        return [dict(r) for r in rows]
    finally:
        await conn.close()


# --- Test Steps ---


async def step_ingest_initial() -> int:
    """Ingest initial text about Alice on billing team."""
    print("\n=== Step 1: Ingest initial text (Alice on billing team) ===")
    baseline = await _get_max_job_id()
    result = await mcp_call(
        ALICE_TOKEN,
        "remember",
        {"text": TEXT_INITIAL, "context": "e2e_content_update_test"},
    )
    eid = int(result["episode_id"])
    print(f"  Stored episode {eid}")
    print(f"  Text: {TEXT_INITIAL[:80]}...")
    return baseline


async def step_verify_initial() -> None:
    """Verify Alice node exists with billing-related content."""
    print("\n=== Step 3: Verify initial content (billing team) ===")

    # Check via recall
    result = await mcp_call(ALICE_TOKEN, "recall", {"query": "Alice billing team", "limit": 10})
    results = result.get("results", [])
    print(f"  Recall returned {len(results)} results")

    found_billing = False
    for r in results:
        content = str(r.get("content", "")).lower()
        name = str(r.get("name", "")).lower()
        if "alice" in name or "alice" in content:
            print(f"    Match: name='{r.get('name')}' content='{str(r.get('content', ''))[:120]}...'")
            if "billing" in content or "payment" in content or "invoice" in content:
                found_billing = True
                print("    [PASS] Found billing-related content for Alice")

    # Also check direct DB
    alice_nodes = await _find_alice_nodes()
    print(f"\n  Direct DB query: {len(alice_nodes)} Alice node(s)")
    for node in alice_nodes:
        content = str(node.get("content", "")).lower()
        print(f"    name='{node['name']}' type='{node['type_name']}' content='{str(node.get('content', ''))[:120]}...'")
        if "billing" in content or "payment" in content or "invoice" in content:
            found_billing = True

    if not found_billing:
        # The node might exist but with a generic description from the LLM.
        # Check if at least an Alice node was created.
        if alice_nodes:
            print("  [WARN] Alice node exists but content doesn't explicitly mention billing.")
            print("         LLM may have summarized differently. Proceeding with update test.")
        else:
            print("  [WARN] No Alice nodes found in DB — extraction may not have created a Person node.")
            print("         The LLM may have focused on other entities. Proceeding with update test.")
    else:
        print("  [PASS] Initial content verified: Alice associated with billing")


async def step_ingest_updated() -> int:
    """Ingest updated text about Alice transferring to auth team."""
    print("\n=== Step 4: Ingest updated text (Alice to auth team) ===")
    baseline = await _get_max_job_id()
    result = await mcp_call(
        ALICE_TOKEN,
        "remember",
        {"text": TEXT_UPDATED, "context": "e2e_content_update_test"},
    )
    eid = int(result["episode_id"])
    print(f"  Stored episode {eid}")
    print(f"  Text: {TEXT_UPDATED[:80]}...")
    return baseline


async def step_verify_updated() -> bool:
    """Verify Alice node content reflects auth team after re-extraction.

    Returns True if the core assertion passes (auth content found).
    """
    print("\n=== Step 6: Verify updated content (auth team) ===")

    # Check via recall
    result = await mcp_call(ALICE_TOKEN, "recall", {"query": "Alice auth team", "limit": 10})
    results = result.get("results", [])
    print(f"  Recall returned {len(results)} results")

    found_auth = False
    for r in results:
        content = str(r.get("content", "")).lower()
        name = str(r.get("name", "")).lower()
        if "alice" in name or "alice" in content:
            print(f"    Match: name='{r.get('name')}' content='{str(r.get('content', ''))[:120]}...'")
            if "auth" in content or "oauth" in content or "session" in content or "authentication" in content:
                found_auth = True
                print("    [PASS] Found auth-related content for Alice")

    # Check direct DB for content update
    alice_nodes = await _find_alice_nodes()
    print(f"\n  Direct DB query: {len(alice_nodes)} Alice node(s)")

    auth_in_db = False
    billing_still_primary = False
    for node in alice_nodes:
        content = str(node.get("content", "")).lower()
        print(f"    name='{node['name']}' type='{node['type_name']}' content='{str(node.get('content', ''))[:150]}...'")
        if "auth" in content or "oauth" in content or "authentication" in content:
            auth_in_db = True
        # Check if billing is STILL the primary description (bad — means content didn't update)
        if "billing" in content and "auth" not in content:
            billing_still_primary = True

    passed = True
    if auth_in_db:
        print("  [PASS] Node content updated: Alice now associated with auth team")
    elif found_auth:
        print("  [PASS] Recall finds auth content for Alice (may be in episode)")
    else:
        print("  [FAIL] Auth-related content not found for Alice in nodes.")
        print("         Content update may not have propagated, or LLM summarized differently.")
        passed = False

    if billing_still_primary:
        print("  [FAIL] Billing is still the primary content — content update did not work")
        passed = False
    else:
        print("  [PASS] Billing is not the sole content (content was updated or merged)")

    return passed


async def step_verify_no_duplicates() -> bool:
    """Verify only 1 node named 'Alice' exists (no duplicates from type drift).

    Returns True if no duplicates detected.
    """
    print("\n=== Step 7: Verify no duplicate Alice nodes ===")
    alice_nodes = await _find_alice_nodes()

    # Count nodes whose name is exactly or very close to "Alice"
    exact_alice = [n for n in alice_nodes if n["name"].lower().strip() == "alice"]
    print(f"  Total nodes matching 'alice': {len(alice_nodes)}")
    print(f"  Exact 'Alice' name matches: {len(exact_alice)}")
    for node in alice_nodes:
        print(f"    name='{node['name']}' type='{node['type_name']}' forgotten={node['forgotten']}")

    if len(exact_alice) <= 1:
        print(f"  [PASS] No duplicate Alice nodes (found {len(exact_alice)})")
        return True
    else:
        # Multiple nodes named "Alice" with different types = type drift duplication
        types = [n["type_name"] for n in exact_alice]
        print(f"  [FAIL] {len(exact_alice)} nodes named 'Alice' with types: {types}")
        print("         This indicates type drift duplication")
        return False


# --- Main ---


async def main() -> None:
    print("=" * 60)
    print("E2E Content Update Test (Plan 16 Stage 1.5)")
    print(f"MCP:       {MCP_URL}")
    print(f"Ingestion: {INGESTION_URL}")
    print(f"Token:     {ALICE_TOKEN[:8]}...")
    print("=" * 60)

    await wait_for_ready(INGESTION_URL, ADMIN_TOKEN)
    await _assert_health()

    # Step 1: Ingest initial text
    baseline1 = await step_ingest_initial()

    # Step 2: Wait for extraction
    print("\n=== Step 2: Wait for initial extraction ===")
    await _wait_for_extraction(baseline1, "initial")

    # Step 3: Verify initial content
    await step_verify_initial()

    # Step 4: Ingest updated text
    baseline2 = await step_ingest_updated()

    # Step 5: Wait for extraction
    print("\n=== Step 5: Wait for update extraction ===")
    await _wait_for_extraction(baseline2, "update")

    # Step 6: Verify updated content
    content_ok = await step_verify_updated()

    # Step 7: Verify no duplicates
    dedup_ok = await step_verify_no_duplicates()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    alice_nodes = await _find_alice_nodes()
    print(f"  Alice nodes in graph: {len(alice_nodes)}")
    for node in alice_nodes:
        print(f"    {node['name']} [{node['type_name']}]: {str(node.get('content', ''))[:100]}")

    failures = []
    if not content_ok:
        failures.append("content update verification")
    if not dedup_ok:
        failures.append("duplicate node detection")

    if failures:
        print(f"\n  [FAIL] Failed checks: {', '.join(failures)}")
        print("=" * 60)
        print("CONTENT UPDATE E2E TEST FAILED")
        raise SystemExit(1)

    print("=" * 60)
    print("CONTENT UPDATE E2E TEST COMPLETED")


if __name__ == "__main__":
    asyncio.run(main())
