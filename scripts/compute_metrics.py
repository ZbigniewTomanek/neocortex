#!/usr/bin/env python3
"""Emit machine-readable bake-off metrics from the current graph and logs."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

import asyncpg
import httpx

from neocortex.config import PostgresConfig
from neocortex.normalization import _TOOL_CALL_ARTIFACT

ROOT = Path(__file__).resolve().parents[1]
PLAN_RESOURCES = ROOT / "docs/plans/33-local-qwen-migration/resources"
CORPUS = ROOT / "docs/plans/18.5-e2e-revalidation/resources/episodes.md"
_IDENTIFIER = re.compile(r"^[A-Z][a-zA-Z0-9]*$")
_SEGMENTS = re.compile(r"[A-Z][a-z]+|[A-Z]+(?=[A-Z]|$)|[0-9]+")


class NonTerminalJobsError(RuntimeError):
    """Raised before a quality metrics artifact can be written."""

    def __init__(self, summary: dict[str, object]):
        self.summary = summary
        super().__init__(f"jobs are not terminal: {summary}")


def ensure_terminal_jobs(summary: dict[str, object]) -> None:
    """Refuse a quality artifact while any queued or running job remains."""

    def count(value: object) -> int:
        return int(value) if isinstance(value, (int, float, str)) else 0

    todo = count(summary.get("todo", 0))
    doing = count(summary.get("doing", 0))
    if todo + doing:
        raise NonTerminalJobsError(summary)


def _relative_path(path: Path) -> str:
    """Return a repository-relative path for reproducible evidence."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _git_metadata() -> dict[str, object]:
    """Capture source revision without including environment credentials."""
    try:
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
        clean = subprocess.run(["git", "diff", "--quiet"], cwd=ROOT, check=False).returncode == 0
    except (OSError, subprocess.CalledProcessError):
        return {"source_revision": "NOT_MEASURED", "source_worktree_clean": "NOT_MEASURED"}
    return {"source_revision": revision, "source_worktree_clean": clean}


def _endpoint_identity(url: str) -> str:
    """Redact user info and query/fragment from an endpoint URL."""
    from urllib.parse import urlsplit, urlunsplit

    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path.rstrip("/"), "", ""))


async def fetch_job_summary(ingestion_url: str, admin_token: str) -> dict[str, object]:
    """Read job completion from the authenticated admin API."""
    url = ingestion_url.rstrip("/") + "/admin/jobs/summary"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            url,
            params={"all_agents": "true"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("admin jobs summary must be a JSON object")
    return {str(k): v for k, v in payload.items()}


def quote(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9_]+", value):
        raise ValueError(f"unsafe schema name: {value}")
    return '"' + value + '"'


async def collect(
    arm: str,
    phase: str,
    *,
    snapshot_path: Path | None = None,
    ingestion_url: str | None = None,
    admin_token: str | None = None,
    run_id: str | None = None,
) -> dict:
    config = PostgresConfig()
    if snapshot_path is not None and not snapshot_path.exists():
        raise FileNotFoundError(f"graph snapshot input does not exist: {snapshot_path}")
    conn = await asyncpg.connect(config.dsn)
    try:
        corpus = re.findall(r"^### Episode (\d+) -- ", CORPUS.read_text(encoding="utf-8"), re.MULTILINE)
        if len(corpus) != 28 or [int(number) for number in corpus] != list(range(1, 29)):
            raise ValueError(f"fixed corpus must contain episodes 1..28, parsed {len(corpus)}")
        corpus_sha256 = hashlib.sha256(CORPUS.read_bytes()).hexdigest()
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
        ingestion_url = ingestion_url or os.environ.get("NEOCORTEX_INGESTION_BASE_URL", "http://127.0.0.1:8001")
        admin_token = admin_token or os.environ.get("NEOCORTEX_ADMIN_TOKEN")
        if not admin_token:
            raise RuntimeError("NEOCORTEX_ADMIN_TOKEN is required for job metrics")
        jobs = await fetch_job_summary(ingestion_url, admin_token)
        ensure_terminal_jobs(jobs)

        source_paths = {
            "metrics_script": _relative_path(Path(__file__)),
            "graph_source": "live PostgreSQL graph",
            "graph_snapshot": _relative_path(snapshot_path) if snapshot_path else "NOT_MEASURED",
            "audit_log": _relative_path(ROOT / "log/agent_actions.log"),
            "admin_jobs_api": _endpoint_identity(ingestion_url) + "/admin/jobs/summary",
            "corpus": _relative_path(CORPUS),
        }
        run_metadata = {
            "run_id": run_id or os.environ.get("NEOCORTEX_BAKEOFF_RUN_ID") or uuid.uuid4().hex,
            "generated_at_utc": datetime.now().astimezone().isoformat(),
            "arm": arm,
            "phase": phase,
            "source_paths": source_paths,
            "endpoint": (
                _endpoint_identity(os.environ.get("NEOCORTEX_LOCAL_MODEL_BASE_URL", ""))
                if os.environ.get("NEOCORTEX_LOCAL_MODEL_BASE_URL")
                else "NOT_MEASURED"
            ),
            "model_ids": {
                name.removeprefix("NEOCORTEX_").removesuffix("_MODEL").lower(): value
                for name in (
                    "NEOCORTEX_ONTOLOGY_MODEL",
                    "NEOCORTEX_EXTRACTOR_MODEL",
                    "NEOCORTEX_LIBRARIAN_MODEL",
                    "NEOCORTEX_DOMAIN_CLASSIFIER_MODEL",
                )
                if (value := os.environ.get(name))
            },
            "efforts": {
                name.removeprefix("NEOCORTEX_").removesuffix("_THINKING_EFFORT").lower(): value
                for name in (
                    "NEOCORTEX_ONTOLOGY_THINKING_EFFORT",
                    "NEOCORTEX_EXTRACTOR_THINKING_EFFORT",
                    "NEOCORTEX_LIBRARIAN_THINKING_EFFORT",
                    "NEOCORTEX_DOMAIN_CLASSIFIER_THINKING_EFFORT",
                )
                if (value := os.environ.get(name))
            },
            "worker_concurrency": os.environ.get("NEOCORTEX_WORKER_CONCURRENCY", "NOT_MEASURED"),
            "per_call_timeout_s": os.environ.get("NEOCORTEX_LOCAL_MODEL_TIMEOUT_S", "NOT_MEASURED"),
            "corpus_size": len(corpus),
            "corpus_sha256": corpus_sha256,
            **_git_metadata(),
        }
        return {
            "schema_version": 3,
            "arm": arm,
            "phase": phase,
            "generated_at": run_metadata["generated_at_utc"],
            "run_metadata": run_metadata,
            "input_paths": source_paths,
            "job_summary": jobs,
            "artifact_regex": _TOOL_CALL_ARTIFACT.pattern,
            "schemas": per_schema,
        }
    finally:
        await conn.close()


def audit_metrics(*, run_id: str | None = None, correlation_id: str | None = None) -> dict:
    path = ROOT / "log/agent_actions.log"
    counts: dict[str, int] = {}
    attempts = rejected = 0
    missing_dimensions = 0
    stage_timings: list[dict] = []
    usage: list[dict] = []
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                record = json.loads(line)
                message = record.get("record", {}).get("message", "")
                extra = record.get("record", {}).get("extra", {})
                if run_id and extra.get("run_id") != run_id:
                    continue
                if correlation_id and extra.get("correlation_id") != correlation_id:
                    continue
                event = extra.get("event") or message.split(" ", 1)[0]
                counts[event] = counts.get(event, 0) + 1
                if event in {
                    "model_request_started",
                    "model_request_completed",
                    "model_request_failed",
                    "tool_call_started",
                    "tool_call_completed",
                    "tool_call_failed",
                    "tool_validation_rejected",
                    "output_validation_retry",
                    "stage_timing",
                    "agent_usage",
                }:
                    required = ("model", "endpoint", "agent", "effort", "correlation_id")
                    missing_dimensions += sum(extra.get(name) in (None, "", "unavailable") for name in required)
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
        "source_path": _relative_path(path),
        "run_id": run_id or "ALL_LOG_ENTRIES",
        "correlation_id": correlation_id or "ALL_CORRELATIONS",
        "missing_required_dimensions": missing_dimensions,
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", required=True)
    parser.add_argument("--phase", default="corpus", choices=("corpus", "e2e"))
    parser.add_argument("--merge", action="store_true")
    parser.add_argument("--snapshot-path", type=Path)
    parser.add_argument(
        "--ingestion-url", default=os.environ.get("NEOCORTEX_INGESTION_BASE_URL", "http://127.0.0.1:8001")
    )
    parser.add_argument("--run-id", default=os.environ.get("NEOCORTEX_BAKEOFF_RUN_ID"))
    args = parser.parse_args()
    try:
        output = await collect(
            args.arm,
            args.phase,
            snapshot_path=args.snapshot_path,
            ingestion_url=args.ingestion_url,
            run_id=args.run_id,
        )
    except NonTerminalJobsError as exc:
        destination = PLAN_RESOURCES / f"metrics-{args.arm}.not-measured.json"
        destination.write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "status": "NOT_MEASURED",
                    "reason": "non_terminal_jobs",
                    "job_summary": exc.summary,
                    "input_paths": {"admin_jobs_api": _endpoint_identity(args.ingestion_url) + "/admin/jobs/summary"},
                },
                indent=2,
            )
            + "\n"
        )
        print(f"jobs are non-terminal; quality metrics not written ({destination})", file=sys.stderr)
        return 2
    output["audit"] = audit_metrics(run_id=args.run_id)
    destination = PLAN_RESOURCES / f"metrics-{args.arm}.json"
    if args.merge and destination.exists():
        old = json.loads(destination.read_text())
        old.setdefault("phases", {})[args.phase] = output
        output = old
    ensure_terminal_jobs(output.get("job_summary", {}))
    destination.write_text(json.dumps(output, indent=2, default=str) + "\n")
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
