"""Shared readiness and extraction-job waits for NeoCortex E2E children."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast

import asyncpg
import httpx

from neocortex.config import PostgresConfig

DEFAULT_JOB_WAIT_S = 900.0
DEFAULT_POLL_S = 3.0
DEFAULT_STALL_S = 300.0

_EXTRACTION_COUNTS_SQL = """SELECT count(*) FILTER (WHERE status = 'todo')      AS pending,
       count(*) FILTER (WHERE status = 'doing')     AS running,
       count(*) FILTER (WHERE status = 'succeeded') AS completed,
       count(*) FILTER (WHERE status = 'failed')    AS failed
FROM procrastinate_jobs
WHERE queue_name = 'extraction' AND id > $1"""

_ROUTING_ACTIVE_SQL = """SELECT
    count(*) FILTER (WHERE status IN ('todo', 'doing')) AS active
FROM procrastinate_jobs
WHERE task_name IN ('route_episode', 'extract_episode')
  AND id > $1
  AND status IN ('todo', 'doing')"""


class _Connection(Protocol):
    async def fetchrow(self, query: str, *args: object) -> Mapping[str, object]: ...

    async def close(self) -> None: ...


@dataclass(frozen=True)
class JobCounts:
    """Last observed extraction and routing job counts."""

    pending: int
    running: int
    completed: int
    failed: int
    route_active: int = 0


class JobWaitError(AssertionError):
    """A bounded job wait ended without reaching its terminal condition."""

    def __init__(self, message: str, counts: JobCounts) -> None:
        super().__init__(message)
        self.counts = counts


def _count(row: Mapping[str, object], key: str) -> int:
    return int(cast(Any, row[key]))


def _counts_text(counts: JobCounts) -> str:
    return (
        f"pending={counts.pending} running={counts.running} "
        f"completed={counts.completed} failed={counts.failed} "
        f"routing={counts.route_active}"
    )


async def wait_for_ready(base_url: str, token: str | None = None, timeout_s: float = 60.0) -> None:
    """Wait until the jobs summary endpoint responds successfully.

    This is only a service-liveness check.  The endpoint reports lifetime
    totals and has no run baseline, so its body must never be used to decide
    whether the current child's jobs have completed.
    """
    started = time.monotonic()
    backoff_s = 0.1
    last_error = "no response"
    headers = {"Authorization": f"Bearer {token}"} if token else None
    async with httpx.AsyncClient() as client:
        while True:
            remaining = timeout_s - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError(f"service did not become ready within {timeout_s:g}s; last error: {last_error}")
            try:
                response = await client.get(
                    f"{base_url.rstrip('/')}/admin/jobs/summary",
                    headers=headers,
                    timeout=min(5.0, remaining),
                )
                if response.status_code == 200:
                    return
                last_error = f"HTTP {response.status_code}"
            except (httpx.RequestError, OSError) as exc:
                last_error = type(exc).__name__

            remaining = timeout_s - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError(f"service did not become ready within {timeout_s:g}s; last error: {last_error}")
            await asyncio.sleep(min(backoff_s, remaining))
            backoff_s = min(backoff_s * 2, 2.0)


async def wait_for_jobs(
    *,
    baseline_job_id: int,
    min_completed: int = 1,
    timeout_s: float | None = None,
    stall_s: float = DEFAULT_STALL_S,
    poll_s: float = DEFAULT_POLL_S,
    label: str = "",
    require_routing_idle: bool = False,
    conn: _Connection | None = None,
) -> JobCounts:
    """Wait for this child's extraction jobs to complete, or fail boundedly."""
    resolved_timeout = (
        float(os.environ.get("NEOCORTEX_E2E_JOB_WAIT_S", str(DEFAULT_JOB_WAIT_S))) if timeout_s is None else timeout_s
    )
    owns_connection = conn is None
    connection = conn
    if connection is None:
        connection = cast(_Connection, await asyncpg.connect(dsn=PostgresConfig().dsn))

    started = time.monotonic()
    last_change = started
    previous: JobCounts | None = None
    current = JobCounts(0, 0, 0, 0)
    try:
        while True:
            row = await connection.fetchrow(_EXTRACTION_COUNTS_SQL, baseline_job_id)
            route_active = 0
            if require_routing_idle:
                route_row = await connection.fetchrow(_ROUTING_ACTIVE_SQL, baseline_job_id)
                route_active = _count(route_row, "active")
            current = JobCounts(
                pending=_count(row, "pending"),
                running=_count(row, "running"),
                completed=_count(row, "completed"),
                failed=_count(row, "failed"),
                route_active=route_active,
            )
            now = time.monotonic()
            elapsed = int(now - started)
            label_text = f" {label}" if label else ""
            print(f"  [{elapsed:3d}s]{label_text} {_counts_text(current)}")

            if (
                current.pending == 0
                and current.running == 0
                and current.completed >= min_completed
                and (not require_routing_idle or current.route_active == 0)
            ):
                return current

            if current != previous:
                previous = current
                last_change = now
            elif now - last_change >= stall_s:
                raise JobWaitError(
                    f"job counts stalled for {stall_s:g}s; last counts: {_counts_text(current)}",
                    current,
                )

            if now - started >= resolved_timeout:
                raise JobWaitError(
                    f"jobs did not complete within {resolved_timeout:g}s; last counts: {_counts_text(current)}",
                    current,
                )

            await asyncio.sleep(
                min(
                    poll_s,
                    max(0.0, resolved_timeout - (now - started)),
                    max(0.0, stall_s - (now - last_change)),
                )
            )
    finally:
        if owns_connection:
            await connection.close()
