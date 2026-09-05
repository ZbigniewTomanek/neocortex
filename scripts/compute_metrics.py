#!/usr/bin/env python3
"""Emit machine-readable bake-off metrics from the current graph and logs."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import cast

import asyncpg
import httpx

from neocortex.config import PostgresConfig
from neocortex.normalization import _TOOL_CALL_ARTIFACT

ROOT = Path(__file__).resolve().parents[1]
PLAN_RESOURCES = ROOT / "docs/plans/33-local-qwen-migration/resources"
CORPUS = ROOT / "docs/plans/18.5-e2e-revalidation/resources/episodes.md"
_IDENTIFIER = re.compile(r"^[A-Z][a-zA-Z0-9]*$")
_SCREAMING_SNAKE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")
_SEGMENTS = re.compile(r"[A-Z][a-z]+|[A-Z]+(?=[A-Z]|$)|[0-9]+")


class NonTerminalJobsError(RuntimeError):
    """Raised before a quality metrics artifact can be written."""

    def __init__(self, summary: dict[str, object]):
        self.summary = summary
        super().__init__(f"jobs are not terminal: {summary}")


class InvalidJobSummaryError(RuntimeError):
    """Raised when the admin job counts cannot support a truthful metric."""

    def __init__(self, summary: object, reason: str):
        self.summary = summary
        self.reason = reason
        super().__init__(f"invalid job summary ({reason})")


# A run-scoped audit record must prove that the model pipeline actually ran.
# Generic loguru records (for example, ``extraction_enqueued``) are not enough
# to support model quality metrics.  Keep this gate explicit so adding a new
# event cannot accidentally make an empty run look measured.
EXPECTED_RUN_SCOPED_EVENTS = frozenset(
    {
        "model_request_started",
        "model_request_completed",
        "model_request_failed",
        "agent_usage",
    }
)


def validate_job_summary(summary: object) -> dict[str, int]:
    """Validate terminal status counts and the ten-percent failure ceiling."""
    if not isinstance(summary, dict):
        raise InvalidJobSummaryError(summary, "not_an_object")
    summary_dict = cast(dict[str, object], summary)
    required = ("todo", "doing", "succeeded", "failed", "cancelled", "total")
    if any(key not in summary for key in required):
        raise InvalidJobSummaryError(summary, "missing_count")
    counts: dict[str, int] = {}
    for key in required:
        value = summary_dict[key]
        if type(value) is not int or value < 0:
            raise InvalidJobSummaryError(summary, "invalid_count")
        counts[key] = value
    if counts["total"] == 0:
        raise InvalidJobSummaryError(summary, "zero_total")
    if sum(counts[key] for key in ("todo", "doing", "succeeded", "failed", "cancelled")) != counts["total"]:
        raise InvalidJobSummaryError(summary, "inconsistent_total")
    if counts["todo"] or counts["doing"]:
        raise NonTerminalJobsError(summary_dict)
    if (counts["failed"] + counts["cancelled"]) / counts["total"] > 0.10:
        raise InvalidJobSummaryError(summary, "failure_rate_exceeded")
    return counts


def ensure_terminal_jobs(summary: object) -> None:
    """Refuse a quality artifact without terminal, internally consistent jobs."""
    validate_job_summary(summary)


def resolve_run_id(run_id: str | None = None) -> str:
    """Resolve the one run identifier used by all evidence collectors."""
    return run_id or os.environ.get("NEOCORTEX_BAKEOFF_RUN_ID") or uuid.uuid4().hex


def _atomic_write_json(destination: Path, payload: dict[str, object]) -> None:
    """Write JSON beside the destination, then publish it with one rename."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(payload, temporary, indent=2, default=str)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, destination)
        temporary_name = None
    finally:
        if temporary_name is not None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary_name)


def _invalidate_canonical_metrics(destination: Path) -> Path | None:
    """Move a stale quality artifact out of its canonical name atomically.

    The old artifact remains recoverable under a clearly marked ``.stale``
    name.  A unique suffix avoids overwriting an earlier diagnostic artifact.
    """
    if not destination.exists():
        return None
    stale = destination.with_name(destination.name + ".stale")
    if stale.exists():
        stale = destination.with_name(destination.name + f".stale-{uuid.uuid4().hex}")
    os.replace(destination, stale)
    return stale


def _write_not_measured(
    destination: Path,
    *,
    reason: str,
    run_id: str,
    ingestion_url: str,
    job_summary: dict[str, object] | None = None,
    audit: dict[str, object] | None = None,
) -> Path:
    """Invalidate canonical quality metrics and publish a truthful sidecar."""
    stale = _invalidate_canonical_metrics(destination)
    input_paths: dict[str, str] = {
        "admin_jobs_api": _endpoint_identity(ingestion_url) + "/admin/jobs/summary",
        "audit_log": _relative_path(ROOT / "log/agent_actions.log"),
    }
    marker: dict[str, object] = {
        "schema_version": 3,
        "status": "NOT_MEASURED",
        "reason": reason,
        "run_id": run_id,
        "input_paths": input_paths,
    }
    if job_summary is not None:
        marker["job_summary"] = job_summary
    if audit is not None:
        marker["audit"] = audit
    if stale is not None:
        marker["invalidated_canonical"] = _relative_path(destination)
        marker["recoverable_stale_artifact"] = _relative_path(stale)
    sidecar = destination.with_name(destination.stem + ".not-measured" + destination.suffix)
    _atomic_write_json(sidecar, marker)
    return sidecar


def _relative_path(path: Path) -> str:
    """Return a repository-relative path for reproducible evidence."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def invalid_type_names(node_names: Iterable[str], edge_names: Iterable[str]) -> dict[str, list[str]]:
    """Validate node and edge naming conventions independently."""
    invalid_nodes = [
        name
        for name in node_names
        if len(name) > 60 or len(_SEGMENTS.findall(name)) > 5 or _IDENTIFIER.fullmatch(name) is None
    ]
    invalid_edges = [
        name
        for name in edge_names
        if len(name) > 60 or len(_SEGMENTS.findall(name)) > 5 or _SCREAMING_SNAKE.fullmatch(name) is None
    ]
    return {
        "invalid_node_type_names": invalid_nodes,
        "invalid_edge_type_names": invalid_edges,
        "invalid_type_names": invalid_nodes + invalid_edges,
    }


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


def _audit_log_paths() -> list[Path]:
    """Return the active and rotated action-log files in this repository.

    The action sink rotates at 10 MB.  Reading only ``agent_actions.log`` can
    silently discard the beginning of a long bake-off run, which would make
    its measured event counts and provenance incomplete.
    """
    directory = ROOT / "log"
    paths = list(directory.glob("agent_actions*.log"))
    return sorted(paths, key=lambda path: (path.name != "agent_actions.log", path.name))


def _read_audit_logs() -> tuple[list[Path], list[str], bool]:
    """Read the active and rotated action logs without losing provenance."""
    paths = _audit_log_paths()
    lines: list[str] = []
    read_error = False
    for path in paths:
        try:
            lines.extend(path.read_text(encoding="utf-8").splitlines())
        except (OSError, UnicodeError):
            read_error = True
    return paths, lines, read_error


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
    snapshot_sha256: str | None = None,
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
        snapshot_digest = None
        if snapshot_path is not None:
            snapshot_digest = _sha256_file(snapshot_path)
            if snapshot_sha256 is not None and snapshot_sha256 != snapshot_digest:
                raise ValueError("graph snapshot digest does not match the supplied value")
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
            node_names = await conn.fetch(f"SELECT name FROM {s}.node_type")
            edge_names = await conn.fetch(f"SELECT name FROM {s}.edge_type")
            names = [*node_names, *edge_names]
            name_set = {str(x["name"]) for x in names}
            candidates = [
                name
                for name in name_set
                if len(_SEGMENTS.findall(name)) > 1
                and any(name.startswith(prefix) and prefix in name_set for prefix in _SEGMENTS.findall(name)[:-1])
            ]
            type_validation = invalid_type_names(
                (str(x["name"]) for x in node_names),
                (str(x["name"]) for x in edge_names),
            )
            leaks = await conn.fetch(
                f"SELECT name FROM {s}.node WHERE name ~* $1 OR content::text ~* $1", _TOOL_CALL_ARTIFACT.pattern
            )
            per_schema[schema] = {
                **dict(row),
                "instance_type_candidates": candidates,
                **type_validation,
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
            "graph_snapshot_sha256": snapshot_digest or "NOT_MEASURED",
            "audit_log": _relative_path(ROOT / "log/agent_actions.log"),
            "admin_jobs_api": _endpoint_identity(ingestion_url) + "/admin/jobs/summary",
            "corpus": _relative_path(CORPUS),
        }
        run_metadata = {
            "run_id": resolve_run_id(run_id),
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
            "snapshot_sha256": snapshot_digest or "NOT_MEASURED",
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
    """Collect run-scoped audit metrics, or report why they are not measured.

    A quality artifact is valid only when at least one explicitly expected
    event is present for the selected run.  The no-signal paths intentionally
    return ``NOT_MEASURED`` instead of inventing zeroes from an absent log.
    """
    path = ROOT / "log/agent_actions.log"
    audit_paths, lines, read_error = _read_audit_logs()
    counts: dict[str, int] = {}
    attempts = rejected = 0
    missing_dimensions = 0
    stage_timings: list[dict] = []
    usage: list[dict] = []
    malformed_lines = 0
    valid_records = 0
    matched_records = 0
    for line in lines:
        try:
            record = json.loads(line)
            log_record = record.get("record") if isinstance(record, dict) else None
            extra = log_record.get("extra") if isinstance(log_record, dict) else None
            if not isinstance(log_record, dict) or not isinstance(extra, dict):
                malformed_lines += 1
                continue
            valid_records += 1
            message = log_record.get("message", "")
            if not isinstance(message, str):
                message = str(message)
            if run_id and extra.get("run_id") != run_id:
                continue
            if correlation_id and extra.get("correlation_id") != correlation_id:
                continue
            matched_records += 1
            event_value = extra.get("event") or message.split(" ", 1)[0]
            event = str(event_value) if event_value else ""
            if not event:
                continue
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
        except (ValueError, TypeError, AttributeError):
            malformed_lines += 1
    attempts = counts.get("entity_attempt", 0) + counts.get("extraction_entity_attempt", 0)
    result: dict[str, object] = {
        "status": "MEASURED",
        "invalid_type_rejections": rejected,
        "entity_attempts": attempts,
        "invalid_type_rejection_rate": rejected / attempts if attempts else None,
        "audit_event_counts": counts,
        "stage_timings": stage_timings,
        "usage": usage,
        "source_path": _relative_path(path),
        "source_paths": [_relative_path(item) for item in audit_paths],
        "run_id": run_id or "ALL_LOG_ENTRIES",
        "correlation_id": correlation_id or "ALL_CORRELATIONS",
        "missing_required_dimensions": missing_dimensions,
        "expected_run_scoped_events": sorted(EXPECTED_RUN_SCOPED_EVENTS),
        "matched_expected_run_events": sorted(set(counts) & EXPECTED_RUN_SCOPED_EVENTS),
        "valid_records": valid_records,
        "matched_records": matched_records,
        "malformed_lines": malformed_lines,
    }
    if not audit_paths:
        return {**result, "status": "NOT_MEASURED", "reason": "missing_audit_log"}
    if read_error:
        # A rotated member is part of the run's evidence set.  Partial reads
        # cannot prove complete event counts, even when another member has a
        # matching event, so never publish a measured artifact in this case.
        return {**result, "status": "NOT_MEASURED", "reason": "unreadable_audit_log"}
    if not lines or not any(line.strip() for line in lines):
        return {**result, "status": "NOT_MEASURED", "reason": "empty_audit_log"}
    if valid_records == 0:
        return {**result, "status": "NOT_MEASURED", "reason": "malformed_audit_log"}
    if matched_records == 0:
        return {**result, "status": "NOT_MEASURED", "reason": "audit_log_fully_filtered"}
    if not (set(counts) & EXPECTED_RUN_SCOPED_EVENTS):
        return {**result, "status": "NOT_MEASURED", "reason": "missing_expected_run_event"}
    return result


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", required=True)
    parser.add_argument("--phase", default="corpus", choices=("corpus", "e2e"))
    parser.add_argument("--merge", action="store_true")
    parser.add_argument("--snapshot-path", type=Path)
    parser.add_argument("--snapshot-sha256")
    parser.add_argument(
        "--ingestion-url", default=os.environ.get("NEOCORTEX_INGESTION_BASE_URL", "http://127.0.0.1:8001")
    )
    parser.add_argument("--run-id", default=os.environ.get("NEOCORTEX_BAKEOFF_RUN_ID"))
    args = parser.parse_args()
    effective_run_id = resolve_run_id(args.run_id)
    destination = PLAN_RESOURCES / f"metrics-{args.arm}.json"
    try:
        output = await collect(
            args.arm,
            args.phase,
            snapshot_path=args.snapshot_path,
            ingestion_url=args.ingestion_url,
            run_id=effective_run_id,
            snapshot_sha256=args.snapshot_sha256,
        )
    except (NonTerminalJobsError, InvalidJobSummaryError) as exc:
        reason = "non_terminal_jobs" if isinstance(exc, NonTerminalJobsError) else exc.reason
        summary = cast(dict[str, object], exc.summary) if isinstance(exc.summary, dict) else None
        destination = _write_not_measured(
            destination,
            reason=reason,
            run_id=effective_run_id,
            ingestion_url=args.ingestion_url,
            job_summary=summary,
        )
        print(f"job evidence is not measured ({reason}); quality metrics not written ({destination})", file=sys.stderr)
        return 2
    audit = audit_metrics(run_id=effective_run_id)
    if audit.get("status") != "MEASURED":
        destination = _write_not_measured(
            destination,
            reason=str(audit.get("reason", "audit_evidence_unavailable")),
            run_id=effective_run_id,
            ingestion_url=args.ingestion_url,
            job_summary=output.get("job_summary") if isinstance(output.get("job_summary"), dict) else None,
            audit=audit,
        )
        print(f"audit evidence is not measured; quality metrics not written ({destination})", file=sys.stderr)
        return 2
    output["audit"] = audit
    if args.merge and destination.exists():
        old = json.loads(destination.read_text())
        old.setdefault("phases", {})[args.phase] = output
        output = old
    ensure_terminal_jobs(output.get("job_summary", {}))
    _atomic_write_json(destination, output)
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
