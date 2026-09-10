#!/usr/bin/env python3
"""Read-only, allow-listed live evidence capture; never exports source/model text.

Run with uv run python <this-file> --run-id ID. Each invocation is immutable.
Live exports are NOT named-snapshot exports; their timestamps make this explicit.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import httpx

from neocortex.config import PostgresConfig
from neocortex.db.scoped import graph_scoped_connection
from neocortex.normalization import _TOOL_CALL_ARTIFACT, normalize_edge_type, normalize_node_type

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))
from corpus_loader import COMPACT_CORPUS, load_corpus  # noqa: E402  # ty: ignore[unresolved-import]


def digest(value):
    return "sha256:" + hashlib.sha256(value if isinstance(value, bytes) else str(value).encode()).hexdigest()


def data(value):
    return json.loads(value) if isinstance(value, str) else (value or {})


def correlation(value):
    return value if isinstance(value, str) and re.fullmatch(r"extract-[a-f0-9]{32}", value) else digest(value)


def safe_job(job):
    out = {key: job.get(key) for key in ("id", "attempts", "scheduled_at", "started_at", "created_at", "finished_at")}
    out["task_name"] = (
        job["task_name"] if job["task_name"] in ("route_episode", "extract_episode") else digest(job["task_name"])
    )
    out["status"] = (
        job["status"] if job["status"] in ("todo", "doing", "succeeded", "failed", "cancelled") else "UNKNOWN"
    )
    args = job.get("args", {})
    out["args"] = {
        key: val
        for key, val in args.items()
        if key in ("episode_id", "episode_ids")
        and (isinstance(val, int) or (isinstance(val, list) and all(type(v) is int for v in val)))
    }
    for key in ("target_schema", "source_schema", "domain_slug", "domain_hint"):
        if args.get(key) is not None:
            out["args"][key + "_hash"] = digest(args[key])
    if args.get("correlation_id"):
        out["args"]["correlation_id"] = correlation(args["correlation_id"])
    out["events"] = [
        {
            "type": (
                event["type"]
                if event["type"]
                in {
                    "deferred",
                    "started",
                    "succeeded",
                    "failed",
                    "cancelled",
                    "retried",
                    "scheduled",
                    "defer",
                    "retry_requested",
                }
                else digest(event["type"])
            ),
            "at": event["at"],
        }
        for event in job.get("events", [])
    ]
    return out


def type_info(row, kind, prohibited):
    name = row["name"]
    try:
        valid = (normalize_node_type if kind == "node" else normalize_edge_type)(name) == name
    except ValueError:
        valid = False
    safe = valid and not any(value and value in name for value in prohibited)
    return {
        "id": row["id"],
        "name": name if safe else None,
        "name_hash": digest(name),
        "valid_normalized_type": valid,
        "artifact_marker": bool(_TOOL_CALL_ARTIFACT.search(name)),
    }


async def capture(args):
    started = datetime.now(UTC)
    corpus = load_corpus(profile="compact")
    known = {digest(ep["text"]): f"E{ep['number']:02d}" for ep in corpus}
    output = {
        "run_id": args.run_id,
        "collector_sha256": digest(Path(__file__).read_bytes()),
        "capture_started_at": started.isoformat(),
        "provenance_kind": "live_read_only_capture_not_snapshot_export",
        "corpus_path": str(COMPACT_CORPUS.relative_to(ROOT)),
        "corpus_sha256": digest(COMPACT_CORPUS.read_bytes()),
        "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "episodes": [],
        "graphs": [],
        "jobs": [],
    }
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8001",
        headers={"Authorization": "Bearer " + os.environ.get("NEOCORTEX_ADMIN_TOKEN", "admin-token")},
        timeout=15,
    ) as client:
        response = await client.get("/admin/jobs/summary")
        response.raise_for_status()
        output["admin_jobs_summary"] = {
            key: val
            for key, val in response.json().items()
            if key in ("todo", "doing", "succeeded", "failed", "cancelled", "total") and type(val) is int
        }
        raw_jobs = []
        for offset in range(0, 10000, 1000):
            response = await client.get("/admin/jobs", params={"limit": 1000, "offset": offset})
            response.raise_for_status()
            page = response.json()
            raw_jobs.extend(page)
            if len(page) < 1000:
                break
        else:
            raise RuntimeError("job pagination bound exceeded")
        for job in raw_jobs:
            response = await client.get(f"/admin/jobs/{job['id']}")
            response.raise_for_status()
            output["jobs"].append(safe_job(response.json()))
    pool = await asyncpg.create_pool(PostgresConfig().dsn, min_size=1, max_size=1, command_timeout=20)
    try:
        async with pool.acquire() as conn:
            registry = await conn.fetch("SELECT schema_name, is_shared FROM public.graph_registry ORDER BY id")
            domains = await conn.fetch("SELECT to_jsonb(d) AS record FROM public.ontology_domains d")
        output["domains"] = []
        for row in domains:
            domain = data(row["record"])
            output["domains"].append(
                {
                    "id": domain["id"],
                    "slug_hash": digest(domain.get("slug")),
                    "schema_hash": digest(domain["schema_name"]) if domain.get("schema_name") else None,
                    "is_seed": bool(domain.get("seed")),
                    "parent_id": domain.get("parent_id") if type(domain.get("parent_id")) is int else None,
                }
            )
        prohibited = [r["schema_name"] for r in registry]
        for row in domains:
            prohibited.extend(
                v
                for k, v in data(row["record"]).items()
                if k in ("slug", "name", "description", "schema_name") and isinstance(v, str)
            )
        for reg in registry:
            shash = digest(reg["schema_name"])
            graph = {"schema_hash": shash, "is_shared": reg["is_shared"], "nodes": [], "edges": []}
            async with graph_scoped_connection(pool, reg["schema_name"], "admin") as conn:
                await conn.execute("SET TRANSACTION READ ONLY")
                episodes = await conn.fetch(
                    "SELECT id, content, metadata, consolidated, created_at FROM episode ORDER BY id"
                )
                nt = await conn.fetch("SELECT id, name FROM node_type ORDER BY id")
                et = await conn.fetch("SELECT id, name FROM edge_type ORDER BY id")
                nodes = await conn.fetch(
                    "SELECT id, type_id, name, content, properties, forgotten FROM node ORDER BY id"
                )
                edges = await conn.fetch("SELECT id, type_id, source_id, target_id, properties FROM edge ORDER BY id")
            graph["node_types"] = [type_info(row, "node", prohibited) for row in nt]
            graph["edge_types"] = [type_info(row, "edge", prohibited) for row in et]
            ntids, etids, nids = {r["id"] for r in nt}, {r["id"] for r in et}, {r["id"] for r in nodes}
            for ep in episodes:
                chash = digest(ep["content"].strip())
                key = known.get(chash)
                metadata_key = data(ep["metadata"]).get("corpus_episode")
                if key:
                    output["episodes"].append(
                        {
                            "schema_hash": shash,
                            "id": ep["id"],
                            "episode_key": key,
                            "content_hash": chash,
                            "metadata_episode_matches": metadata_key == int(key[1:]),
                            "consolidated": ep["consolidated"],
                            "created_at": ep["created_at"].isoformat(),
                        }
                    )
            for node in nodes:
                props = data(node["properties"])
                graph["nodes"].append(
                    {
                        "id": node["id"],
                        "type_id": node["type_id"],
                        "type_exists": node["type_id"] in ntids,
                        "name_hash": digest(node["name"]),
                        "name_nonempty": bool(node["name"].strip()),
                        "source_episode_id": (
                            props.get("_source_episode") if type(props.get("_source_episode")) is int else None
                        ),
                        "artifact_marker": bool(
                            _TOOL_CALL_ARTIFACT.search(
                                node["name"] + " " + (node["content"] or "") + " " + json.dumps(props)
                            )
                        ),
                        "forgotten": node["forgotten"],
                    }
                )
            for edge in edges:
                props = data(edge["properties"])
                graph["edges"].append(
                    {
                        "id": edge["id"],
                        "type_id": edge["type_id"],
                        "type_exists": edge["type_id"] in etids,
                        "source_id": edge["source_id"],
                        "target_id": edge["target_id"],
                        "references_valid": edge["source_id"] in nids and edge["target_id"] in nids,
                        "source_episode_id": (
                            props.get("_source_episode") if type(props.get("_source_episode")) is int else None
                        ),
                        "artifact_marker": bool(_TOOL_CALL_ARTIFACT.search(json.dumps(props))),
                        "name_field_status": "NOT_APPLICABLE_SCHEMA_HAS_NO_EDGE_NAME",
                    }
                )
            output["graphs"].append(graph)
    finally:
        await pool.close()
    # Preserve explicit source/job candidates without inventing uniqueness.
    for graph in output["graphs"]:
        for record in graph["nodes"] + graph["edges"]:
            episode_id = record["source_episode_id"]
            candidates = []
            for job in output["jobs"]:
                ja = job["args"]
                target = ja.get("target_schema_hash")
                if job["task_name"] != "extract_episode" or episode_id not in ja.get("episode_ids", []):
                    continue
                if target == graph["schema_hash"] or (target is None and not graph["is_shared"]):
                    candidates.append(job["id"])
            record["source_job_id_candidates"] = candidates
            record["source_episode_key_candidates"] = sorted(
                {ep["episode_key"] for ep in output["episodes"] if ep["id"] == episode_id}
            )
    output["audit"] = audit(args.run_id)
    output["capture_finished_at"] = datetime.now(UTC).isoformat()
    output["privacy"] = {
        "policy": "Allowlists; schema/domain/name values hashed; no source content or raw audit records copied",
        "dynamic_value_scan_passed": True,
    }
    serialized = json.dumps(output, indent=2, sort_keys=True)
    if any(value and len(value) > 3 and value in serialized for value in prohibited):
        raise RuntimeError("dynamic value detected in sanitized evidence; no output written")
    if re.search(r"ncx_[a-z0-9]+__[a-z0-9_]+", serialized):
        raise RuntimeError("schema value detected; no output written")
    dest = Path(__file__).parent / f"stage6-capture-{args.run_id}-{started.strftime('%Y%m%dT%H%M%S%fZ')}.json"
    dest.write_text(serialized + "\n")
    print(
        json.dumps(
            {
                "path": str(dest.relative_to(ROOT)),
                "episodes": len(output["episodes"]),
                "jobs": len(output["jobs"]),
                "nodes": sum(len(g["nodes"]) for g in output["graphs"]),
                "edges": sum(len(g["edges"]) for g in output["graphs"]),
                "summary": output["admin_jobs_summary"],
            }
        )
    )

    return output


async def watch_terminal(args):
    """Cheap one-second summary polling; capture once before DB replacement."""
    receipt_path = Path(__file__).parent / "stage6-active-run.json"
    receipt = json.loads(receipt_path.read_text())
    if receipt.get("run_id") != args.run_id:
        raise ValueError("active run receipt does not match requested run")
    run_start = datetime.fromisoformat(receipt["start_utc"])
    expected = {"E02", "E04", "E05", "E10", "E18", "E20", "E26", "E27"}
    deadline = time.monotonic() + args.watch_max_seconds
    print(
        json.dumps(
            {"watcher": "started", "run_id": args.run_id, "poll_seconds": 1, "max_seconds": args.watch_max_seconds}
        ),
        flush=True,
    )
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8001",
        headers={"Authorization": "Bearer " + os.environ.get("NEOCORTEX_ADMIN_TOKEN", "admin-token")},
        timeout=5,
    ) as client:
        while time.monotonic() < deadline:
            try:
                response = await client.get("/admin/jobs/summary")
                response.raise_for_status()
                summary = response.json()
            except httpx.HTTPError:
                await asyncio.sleep(1)
                continue
            if summary.get("total", 0) and summary.get("todo") == 0 and summary.get("doing") == 0:
                result = await capture(args)
                mapped = {e["episode_key"] for e in result["episodes"]} == expected
                mapped = mapped and all(
                    datetime.fromisoformat(e["created_at"]) >= run_start for e in result["episodes"]
                )
                terminal = (
                    result["admin_jobs_summary"].get("todo") == 0 and result["admin_jobs_summary"].get("doing") == 0
                )
                print(
                    json.dumps(
                        {
                            "watcher": (
                                "terminal_capture_complete" if mapped and terminal else "replacement_or_race_stopped"
                            ),
                            "run_id": args.run_id,
                            "verified_current_run_corpus": mapped,
                            "verified_terminal_summary": terminal,
                        }
                    ),
                    flush=True,
                )
                return
            await asyncio.sleep(1)
    print(json.dumps({"watcher": "deadline_reached", "run_id": args.run_id}), flush=True)


def audit(run_id):
    path = ROOT / "log/agent_actions.log"
    content = path.read_bytes()
    groups = {}
    numeric = {
        "requests",
        "tool_calls",
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "elapsed_s",
        "retry",
        "max_retries",
        "request_step",
        "entity_count",
        "relation_count",
        "proposed_node_types",
        "proposed_edge_types",
        "nodes_created",
        "nodes_updated",
        "nodes_archived",
        "edges_created",
        "edges_upserted",
        "created",
        "updated",
        "archived",
        "edges_removed",
        "actions_observed",
        "model_summary_actions",
        "matched_count",
        "accepted_match_count",
        "node_types",
        "edge_types",
        "entities",
        "relations",
    }
    # Only event literals compiled into repository sources may appear as labels.
    literals = set()
    for source in (ROOT / "src/neocortex").rglob("*.py"):
        literals.update(re.findall(r'["\']([a-z][a-z_]{2,80})["\']', source.read_text()))
    matched = malformed = 0
    for line in content.splitlines():
        try:
            rec = json.loads(line).get("record", {})
        except (ValueError, TypeError):
            malformed += 1
            continue
        extra = rec.get("extra", {})
        if extra.get("run_id") != run_id:
            continue
        matched += 1
        corr = correlation(extra.get("correlation_id"))
        agent = (
            extra.get("agent")
            if extra.get("agent") in {"ontology", "extractor", "librarian", "domain", "domain_classifier", "classifier"}
            else "unspecified"
        )
        key = (corr, agent)
        group = groups.setdefault(
            key,
            {
                "correlation_id": corr,
                "agent": agent,
                "episode_ids": set(),
                "events": Counter(),
                "numeric_by_event": {},
                "actions": Counter(),
                "error_types": Counter(),
                "tool_events": Counter(),
                "models": set(),
                "efforts": set(),
            },
        )
        if type(extra.get("episode_id")) is int:
            group["episode_ids"].add(extra["episode_id"])
        message = rec.get("message", "")
        event = message if message in literals else digest(message)
        group["events"][event] += 1
        vals = group["numeric_by_event"].setdefault(event, {})
        for k in numeric:
            value = extra.get(k)
            if type(value) in (int, float):
                stats = vals.setdefault(k, {"sum": 0, "count": 0, "min": value, "max": value})
                stats["sum"] += value
                stats["count"] += 1
                stats["min"], stats["max"] = min(stats["min"], value), max(stats["max"], value)
        if extra.get("error_type"):
            error_type = extra["error_type"]
            safe_errors = {
                "TimeoutError",
                "ReadTimeout",
                "ConnectTimeout",
                "ModelHTTPError",
                "UnexpectedModelBehavior",
                "UsageLimitExceeded",
                "ValidationError",
                "ModelRetry",
                "HTTPStatusError",
                "CancelledError",
            }
            group["error_types"][error_type if error_type in safe_errors else digest(error_type)] += 1
        if extra.get("tool") in literals:
            group["tool_events"][event + ":" + extra["tool"]] += 1
        if extra.get("action") in {"created", "updated", "archived", "upserted", "reinforced"}:
            group["actions"][extra["action"]] += 1
        if extra.get("model") in {"qwen3.8-flash-next", "local:qwen3.8-flash-next"}:
            group["models"].add(extra["model"])
        if extra.get("effort") in {"low", "medium", "high", "xhigh"}:
            group["efforts"].add(extra["effort"])
    for group in groups.values():
        for key in ("episode_ids", "models", "efforts"):
            group[key] = sorted(group[key])
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": digest(content),
        "byte_count": len(content),
        "exact_run_id_filter": run_id,
        "matched_record_count": matched,
        "malformed_line_count": malformed,
        "groups": list(groups.values()),
        "limitation": (
            "Records without exact run_id excluded; sums of retry counters are observations, "
            "not independent retry counts; audit file hash is of captured bytes at this timestamp."
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--watch-terminal", action="store_true")
    parser.add_argument("--watch-max-seconds", type=int, default=43200)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", args.run_id):
        parser.error("run id must contain only alphanumeric, dash or underscore")
    try:
        asyncio.run(watch_terminal(args) if args.watch_terminal else capture(args))
    except Exception as exc:
        print(json.dumps({"capture_failed": type(exc).__name__}), file=sys.stderr)
        raise SystemExit(1) from None
