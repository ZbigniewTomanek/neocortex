#!/usr/bin/env python3
"""Run the nine Plan 18.5 recall queries and emit M1-M4 as JSON."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import Counter

from fastmcp import Client

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


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=str, default="docs/plans/33-local-qwen-migration/resources/recall-results.json"
    )
    args = parser.parse_args()
    url = os.environ.get("NEOCORTEX_MCP_URL", "http://127.0.0.1:8000/mcp")
    token = os.environ.get("NEOCORTEX_ALICE_TOKEN", "alice-token")
    rows = []
    async with Client(url, auth=token) as client:
        for name, query, keywords in QUERIES:
            result = await client.call_tool("recall", {"query": query, "limit": 10})
            data = result.structured_content or {}
            items = data.get("results", data.get("items", [])) if isinstance(data, dict) else []
            rows.append({"query": name, "text": query, "results": items, "keywords": keywords})
    activations = [
        float(item.get("activation_score", 0)) for row in rows for item in row["results"] if isinstance(item, dict)
    ]
    top_ids = [str(row["results"][0].get("item_id", row["results"][0].get("id", ""))) for row in rows if row["results"]]
    specific = [rows[i] for i in (2, 3, 4)]
    temporal = [rows[i] for i in (6, 7, 8)]

    def contains(row: dict) -> bool:
        return any(
            any(k.lower() in json.dumps(item, ensure_ascii=False).lower() for k in row["keywords"])
            for item in row["results"][:5]
        )

    output = {
        "queries": rows,
        "M1_max_activation": max(activations, default=0),
        "M2_max_top1_count": max(Counter(top_ids).values(), default=0),
        "M3_specific_event_pass": sum(contains(row) for row in specific),
        "M4_temporal_pass": sum(contains(row) for row in temporal),
    }
    destination = os.path.abspath(args.output)
    with open(destination, "w") as handle:
        json.dump(output, handle, indent=2, default=str)
    print(json.dumps({k: v for k, v in output.items() if k != "queries"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
