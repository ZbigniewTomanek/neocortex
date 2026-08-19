#!/usr/bin/env python3
"""Emit machine-readable bake-off metrics from the current graph and logs."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import datetime
from pathlib import Path

import asyncpg

from neocortex.config import PostgresConfig
from neocortex.normalization import _TOOL_CALL_ARTIFACT

ROOT = Path(__file__).resolve().parents[1]
_IDENTIFIER = re.compile(r"^[A-Z][a-zA-Z0-9]*$")
_SEGMENTS = re.compile(r"[A-Z][a-z]+|[A-Z]+(?=[A-Z]|$)|[0-9]+")


def quote(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9_]+", value):
        raise ValueError(f"unsafe schema name: {value}")
    return '"' + value + '"'


async def collect(arm: str, phase: str) -> dict:
    config = PostgresConfig()
    conn = await asyncpg.connect(config.dsn)
    try:
        schemas = await conn.fetch("SELECT schema_name FROM graph_registry ORDER BY schema_name")
        per_schema = {}
        for record in schemas:
            schema = str(record["schema_name"])
            s = quote(schema)
            metric_sql = f"""
                WITH ant AS (
                    SELECT COUNT(DISTINCT nt.id) cnt FROM {s}.node_type nt
                    JOIN {s}.node n ON n.type_id = nt.id
                ), aet AS (
                    SELECT COUNT(DISTINCT et.id) cnt FROM {s}.edge_type et
                    JOIN {s}.edge e ON e.type_id = et.id
                ), all_et AS (SELECT COUNT(*) cnt FROM {s}.edge_type), unused AS (
                    SELECT COUNT(*) cnt FROM {s}.edge_type et
                    LEFT JOIN {s}.edge e ON e.type_id = et.id WHERE e.id IS NULL
                ), garbage AS (
                    SELECT (SELECT COUNT(*) FROM {s}.node_type WHERE name ~* $1)
                         + (SELECT COUNT(*) FROM {s}.edge_type WHERE name ~* $1) cnt
                ), nodes AS (SELECT COUNT(*) cnt FROM {s}.node)
                SELECT (SELECT cnt FROM ant) active_node_types,
                       (SELECT cnt FROM aet) active_edge_types,
                       ROUND((SELECT cnt FROM unused)::numeric /
                             NULLIF((SELECT cnt FROM all_et), 0) * 100, 1)
                             unused_edge_type_pct,
                       (SELECT cnt FROM garbage) garbage_types,
                       ROUND((SELECT cnt FROM nodes)::numeric /
                             NULLIF((SELECT cnt FROM ant), 0), 1) type_reuse_ratio
            """
            row = await conn.fetchrow(
                metric_sql,
                _TOOL_CALL_ARTIFACT.pattern,
            )
            names = await conn.fetch(f"SELECT name FROM {s}.node_type UNION ALL SELECT name FROM {s}.edge_type")
            name_set = {str(x["name"]) for x in names}
            candidates = [
                name
                for name in name_set
                if len(_SEGMENTS.findall(name)) > 1
                and any(name.startswith(prefix) and prefix in name_set for prefix in _SEGMENTS.findall(name)[:-1])
            ]
            invalid = [
                str(x["name"])
                for x in names
                if len(str(x["name"])) > 60
                or len(_SEGMENTS.findall(str(x["name"]))) > 5
                or _IDENTIFIER.fullmatch(str(x["name"])) is None
            ]
            leaks = await conn.fetch(
                f"SELECT name FROM {s}.node WHERE name ~* $1 OR content::text ~* $1", _TOOL_CALL_ARTIFACT.pattern
            )
            per_schema[schema] = {
                **dict(row),
                "instance_type_candidates": candidates,
                "invalid_type_names": invalid,
                "stored_leaks": [str(x["name"]) for x in leaks],
            }
        return {
            "arm": arm,
            "phase": phase,
            "generated_at": datetime.now().astimezone().isoformat(),
            "artifact_regex": _TOOL_CALL_ARTIFACT.pattern,
            "schemas": per_schema,
        }
    finally:
        await conn.close()


def audit_metrics() -> dict:
    path = ROOT / "log/agent_actions.log"
    counts: dict[str, int] = {}
    attempts = rejected = 0
    stage_timings: list[dict] = []
    usage: list[dict] = []
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                record = json.loads(line)
                message = record.get("record", {}).get("message", "")
                extra = record.get("record", {}).get("extra", {})
                event = extra.get("event") or message.split(" ", 1)[0]
                counts[event] = counts.get(event, 0) + 1
                if event in {
                    "skipping_entity_invalid_type",
                    "skipping_invalid_node_type",
                    "skipping_invalid_edge_type",
                    "invalid_node_type_rejected",
                    "invalid_edge_type_rejected",
                }:
                    rejected += 1
                if event == "agent_usage":
                    usage.append(extra)
                if event == "stage_timing":
                    stage_timings.append(extra)
            except (ValueError, TypeError):
                continue
    attempts = counts.get("entity_attempt", 0) + counts.get("extraction_entity_attempt", 0)
    return {
        "invalid_type_rejections": rejected,
        "entity_attempts": attempts,
        "invalid_type_rejection_rate": rejected / attempts if attempts else None,
        "audit_event_counts": counts,
        "stage_timings": stage_timings,
        "usage": usage,
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", required=True)
    parser.add_argument("--phase", default="corpus", choices=("corpus", "e2e"))
    parser.add_argument("--merge", action="store_true")
    args = parser.parse_args()
    output = await collect(args.arm, args.phase)
    output["audit"] = audit_metrics()
    destination = ROOT / f"docs/plans/33-local-qwen-migration/resources/metrics-{args.arm}.json"
    if args.merge and destination.exists():
        old = json.loads(destination.read_text())
        old.setdefault("phases", {})[args.phase] = output
        output = old
    destination.write_text(json.dumps(output, indent=2, default=str) + "\n")
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
