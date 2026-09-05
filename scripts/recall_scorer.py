#!/usr/bin/env python3
"""Run the nine Plan 18.5 recall queries and emit M1-M4 as JSON."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, cast

from fastmcp import Client

try:
    from scripts.e2e_manifest import atomic_write_json  # ty: ignore[unresolved-import]
except ModuleNotFoundError:  # Direct ``python scripts/recall_scorer.py`` execution.
    from e2e_manifest import atomic_write_json  # ty: ignore[unresolved-import]

QUERIES = [
    ("Q1", "What is blocking in entity resolution and how does the system implement it?", ("blocking", "stop-list")),
    ("Q2", "Describe the overall system architecture and Vertica design patterns", ("architecture", "vertica")),
    (
        "Q3",
        "SQL injection vulnerability in normalization service",
        ("sql injection", "identifierlinknormalizationservice"),
    ),
    ("Q4", "fingerprint hash collision birthday paradox 32-bit to 64-bit", ("birthday paradox", "64-bit")),
    ("Q5", "Korean character crash UDX bug in name parsing", ("korean", "parsehumanname")),
    ("Q6", "Who is on the DataWalk ER team and what are their roles?", ("team", "tomek", "jonas")),
    ("Q7", "What is Jonas Weber's current role and team assignment?", ("security", "jonas")),
    ("Q8", "What is the current Metaphone3 encoding strategy and code length?", ("correction", "metaphone3", "8-char")),
    ("Q9", "How has the Metaphone3 decision evolved over time? What changed?", ("correction", "metaphone3")),
]


def _recall_token(*, require_bakeoff_mcp: bool = False) -> str:
    """Use the explicitly configured MCP credential for bake-off recall.

    The full local arm authenticates the MCP endpoint with
    ``NEOCORTEX_MCP_TOKEN``.  Keep the Alice-token fallback for standalone
    Plan 18.5 runs that use the test-token map.
    """
    mcp_token = os.environ.get("NEOCORTEX_MCP_TOKEN")
    if require_bakeoff_mcp and not mcp_token:
        raise RuntimeError("NEOCORTEX_MCP_TOKEN is required for bake-off recall")
    return (
        os.environ.get("NEOCORTEX_RECALL_TOKEN")
        or mcp_token
        or os.environ.get("NEOCORTEX_ALICE_TOKEN")
        or "alice-token"
    )


def _opaque_hash(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _valid_identifier(value: object) -> int | str | None:
    """Normalize only identifiers allowed by the RecallItem/DB contract."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value if value > 0 else None
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None


def _item_identifier(item: object) -> int | str | None:
    """Return an opaque-item source identifier, without treating missing as a value."""
    if not isinstance(item, dict):
        return None
    item_data = cast(dict[str, Any], item)
    item_id = _valid_identifier(item_data.get("item_id"))
    if item_id is not None:
        return item_id
    return _valid_identifier(item_data.get("id"))


def _safe_recall_evidence(rows: list[dict[str, Any]], *, run_id: str) -> dict[str, Any]:
    query_results: list[dict[str, Any]] = []
    all_item_hashes: set[str] = set()
    known_top1_ids = 0
    missing_top1_ids = 0
    for index, row in enumerate(rows, 1):
        items = row["results"]
        item_hashes = set()
        for item in items:
            item_id = _item_identifier(item)
            if item_id is not None:
                item_hashes.add(_opaque_hash(item_id))
        all_item_hashes.update(item_hashes)
        top_id = _item_identifier(items[0]) if items else None
        if top_id is not None:
            known_top1_ids += 1
            top_item_hash = _opaque_hash(top_id)
        else:
            missing_top1_ids += 1
            top_item_hash = None
        query_results.append(
            {
                "index": index,
                "result_count": len(items),
                "top_item_hash": top_item_hash,
                "keyword_match_count": sum(contains(row, item) for item in items[:5]),
            }
        )
    activations = [
        float(item.get("activation_score", 0)) for row in rows for item in row["results"] if isinstance(item, dict)
    ]
    top_ids = []
    for row in rows:
        item_id = _item_identifier(row["results"][0]) if row["results"] else None
        if item_id is not None:
            top_ids.append(_opaque_hash(item_id))
    specific = [rows[i] for i in (2, 3, 4)]
    temporal = [rows[i] for i in (6, 7, 8)]
    return {
        "schema_version": 1,
        "kind": "neocortex-recall-evidence",
        "status": "MEASURED",
        "run_id": run_id,
        "query_count": len(rows),
        "query_results": query_results,
        "top1_id_availability": {"known": known_top1_ids, "missing": missing_top1_ids},
        "metrics": {
            "M1_max_activation": max(activations, default=0),
            "M2_max_top1_count": max(Counter(top_ids).values(), default=0),
            "M3_specific_event_pass": sum(any(contains(row, item) for item in row["results"][:5]) for row in specific),
            "M4_temporal_pass": sum(any(contains(row, item) for item in row["results"][:5]) for row in temporal),
        },
        "opaque_item_hashes": sorted(all_item_hashes),
    }


def contains(row: dict[str, Any], item: object) -> bool:
    if not isinstance(item, dict):
        return False
    return any(k.lower() in json.dumps(item, ensure_ascii=False).lower() for k in row["keywords"])


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=str, default="docs/plans/33-local-qwen-migration/resources/recall-results.json"
    )
    args = parser.parse_args()
    url = os.environ.get("NEOCORTEX_MCP_URL", "http://127.0.0.1:8000/mcp")
    bakeoff_run_id = os.environ.get("NEOCORTEX_BAKEOFF_RUN_ID")
    token = _recall_token(require_bakeoff_mcp=bool(bakeoff_run_id))
    rows = []
    async with Client(url, auth=token) as client:
        for name, query, keywords in QUERIES:
            result = await client.call_tool("recall", {"query": query, "limit": 10})
            data = result.structured_content or {}
            items = data.get("results", data.get("items", [])) if isinstance(data, dict) else []
            rows.append({"query": name, "text": query, "results": items, "keywords": keywords})
    output = _safe_recall_evidence(rows, run_id=bakeoff_run_id or "standalone")
    destination = Path(os.path.abspath(args.output))
    atomic_write_json(destination, output)
    print(
        json.dumps(
            {"status": output["status"], "query_count": output["query_count"], "metrics": output["metrics"]}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
