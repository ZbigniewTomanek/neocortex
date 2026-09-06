from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel, field_validator

from neocortex.admin.auth import require_admin
from neocortex.ingestion.auth import get_agent_id
from neocortex.jobs.correlation import normalize_extraction_correlation_id
from neocortex.schemas.permissions import PermissionGrant, PermissionInfo

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Permission management
# ---------------------------------------------------------------------------


@router.post("/permissions", response_model=PermissionInfo)
async def grant_permission(
    body: PermissionGrant,
    request: Request,
    admin_id: Annotated[str, Depends(require_admin)],
) -> PermissionInfo:
    permissions = request.app.state.permissions
    return await permissions.grant(
        agent_id=body.agent_id,
        schema_name=body.schema_name,
        can_read=body.can_read,
        can_write=body.can_write,
        granted_by=admin_id,
    )


@router.delete("/permissions/{agent_id}/{schema_name}")
async def revoke_permission(
    agent_id: str,
    schema_name: str,
    request: Request,
    admin_id: Annotated[str, Depends(require_admin)],
):
    permissions = request.app.state.permissions
    removed = await permissions.revoke(agent_id, schema_name)
    if not removed:
        raise HTTPException(status_code=404, detail="Permission not found")
    return {"status": "revoked", "agent_id": agent_id, "schema_name": schema_name}


@router.get("/permissions", response_model=list[PermissionInfo])
async def list_permissions(
    request: Request,
    admin_id: Annotated[str, Depends(require_admin)],
    agent_id: str | None = None,
    schema_name: str | None = None,
) -> list[PermissionInfo]:
    permissions = request.app.state.permissions
    if agent_id:
        return await permissions.list_for_agent(agent_id)
    if schema_name:
        return await permissions.list_for_schema(schema_name)
    return await permissions.list_all_permissions()


@router.get("/permissions/{agent_id}", response_model=list[PermissionInfo])
async def list_permissions_for_agent(
    agent_id: str,
    request: Request,
    admin_id: Annotated[str, Depends(require_admin)],
) -> list[PermissionInfo]:
    permissions = request.app.state.permissions
    return await permissions.list_for_agent(agent_id)


# ---------------------------------------------------------------------------
# Agent management
# ---------------------------------------------------------------------------


class AdminStatusRequest(BaseModel):
    is_admin: bool


@router.get("/agents")
async def list_agents(
    request: Request,
    admin_id: Annotated[str, Depends(require_admin)],
):
    permissions = request.app.state.permissions
    return await permissions.list_agents()


@router.put("/agents/{agent_id}/admin")
async def promote_agent(
    agent_id: str,
    body: AdminStatusRequest,
    request: Request,
    admin_id: Annotated[str, Depends(require_admin)],
):
    permissions = request.app.state.permissions
    try:
        await permissions.set_admin(agent_id, is_admin=body.is_admin)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    status = "promoted" if body.is_admin else "demoted"
    return {"status": status, "agent_id": agent_id}


@router.delete("/agents/{agent_id}/admin")
async def demote_agent(
    agent_id: str,
    request: Request,
    admin_id: Annotated[str, Depends(require_admin)],
):
    permissions = request.app.state.permissions
    try:
        await permissions.set_admin(agent_id, is_admin=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "demoted", "agent_id": agent_id}


# ---------------------------------------------------------------------------
# Graph management
# ---------------------------------------------------------------------------


class CreateGraphRequest(BaseModel):
    purpose: str


@router.post("/graphs")
async def create_graph(
    body: CreateGraphRequest,
    request: Request,
    admin_id: Annotated[str, Depends(require_admin)],
):
    schema_mgr = getattr(request.app.state, "schema_mgr", None)
    if schema_mgr is None:
        raise HTTPException(status_code=501, detail="Graph management requires a real database")
    schema_name = await schema_mgr.create_graph("shared", body.purpose, is_shared=True)
    return {"schema_name": schema_name, "purpose": body.purpose}


@router.get("/graphs")
async def list_graphs(
    request: Request,
    admin_id: Annotated[str, Depends(require_admin)],
):
    schema_mgr = getattr(request.app.state, "schema_mgr", None)
    if schema_mgr is None:
        raise HTTPException(status_code=501, detail="Graph management requires a real database")
    graphs = await schema_mgr.list_graphs()
    return graphs


@router.delete("/graphs/{schema_name}")
async def drop_graph(
    schema_name: str,
    request: Request,
    admin_id: Annotated[str, Depends(require_admin)],
):
    schema_mgr = getattr(request.app.state, "schema_mgr", None)
    if schema_mgr is None:
        raise HTTPException(status_code=501, detail="Graph management requires a real database")
    deleted = await schema_mgr.drop_graph(schema_name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Graph '{schema_name}' not found")
    return {"status": "dropped", "schema_name": schema_name}


# ---------------------------------------------------------------------------
# Type consolidation
# ---------------------------------------------------------------------------


class MergeActionResponse(BaseModel):
    source_type_name: str
    source_type_id: int
    target_type_name: str
    target_type_id: int
    nodes_moved: int


class ArchiveActionResponse(BaseModel):
    type_name: str
    type_id: int
    kind: str


class ConsolidationResponse(BaseModel):
    merges: list[MergeActionResponse]
    archives: list[ArchiveActionResponse]


def _require_repo(request: Request):
    repo = getattr(request.app.state, "repo", None)
    if repo is None:
        raise HTTPException(501, "Type consolidation requires a repository")
    return repo


@router.post("/consolidate/preview", response_model=ConsolidationResponse)
async def consolidate_preview(
    request: Request,
    admin_id: Annotated[str, Depends(require_admin)],
    schema_name: str | None = None,
):
    from neocortex.extraction.type_consolidation import (
        archive_unused_types,
        merge_similar_types,
    )

    repo = _require_repo(request)
    merges = await merge_similar_types(repo, admin_id, schema=schema_name, dry_run=True)
    archives = await archive_unused_types(repo, admin_id, schema=schema_name, dry_run=True)

    return ConsolidationResponse(
        merges=[MergeActionResponse(**m.__dict__) for m in merges],
        archives=[ArchiveActionResponse(**a.__dict__) for a in archives],
    )


@router.post("/consolidate/apply", response_model=ConsolidationResponse)
async def consolidate_apply(
    request: Request,
    admin_id: Annotated[str, Depends(require_admin)],
    schema_name: str | None = None,
):
    from neocortex.extraction.type_consolidation import (
        archive_unused_types,
        merge_similar_types,
    )

    repo = _require_repo(request)
    merges = await merge_similar_types(repo, admin_id, schema=schema_name, dry_run=False)
    archives = await archive_unused_types(repo, admin_id, schema=schema_name, dry_run=False)

    logger.bind(action_log=True).info(
        "consolidation_applied",
        admin_id=admin_id,
        schema_name_present=schema_name is not None,
        merges=len(merges),
        archives=len(archives),
    )

    return ConsolidationResponse(
        merges=[MergeActionResponse(**m.__dict__) for m in merges],
        archives=[ArchiveActionResponse(**a.__dict__) for a in archives],
    )


# ---------------------------------------------------------------------------
# Job monitoring
# ---------------------------------------------------------------------------


class JobSummary(BaseModel):
    """Aggregate counts by status."""

    todo: int = 0
    doing: int = 0
    succeeded: int = 0
    failed: int = 0
    cancelled: int = 0
    total: int = 0


class JobInfo(BaseModel):
    """Single job record."""

    id: int
    task_name: str
    status: str
    queue_name: str
    args: dict
    attempts: int

    @field_validator("args", mode="before")
    @classmethod
    def _parse_args(cls, v: object) -> object:
        if isinstance(v, str):
            return json.loads(v)
        return v

    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    created_at: datetime | None = None
    finished_at: datetime | None = None


class JobEvent(BaseModel):
    type: str
    at: datetime


class JobDetail(JobInfo):
    events: list[JobEvent] = []


def _require_pool(request: Request):
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        raise HTTPException(501, "Job monitoring requires a real database")
    return pool


_LIST_JOBS_SQL = """\
SELECT j.id, j.task_name, j.status::text, j.queue_name,
       j.args, j.attempts, j.scheduled_at,
       (SELECT at FROM procrastinate_events e
        WHERE e.job_id = j.id AND e.type = 'started'
        ORDER BY at DESC LIMIT 1) AS started_at,
       (SELECT MIN(at) FROM procrastinate_events e
        WHERE e.job_id = j.id AND e.type = 'deferred') AS created_at,
       (SELECT MAX(at) FROM procrastinate_events e
        WHERE e.job_id = j.id
          AND e.type IN ('succeeded', 'failed', 'cancelled')
       ) AS finished_at
FROM procrastinate_jobs j
WHERE j.queue_name = 'extraction'
  AND ($1::text IS NULL OR j.args->>'agent_id' = $1)
  AND ($2::text IS NULL OR j.status::text = $2)
  AND ($3::text IS NULL OR j.task_name = $3)
ORDER BY j.id DESC
LIMIT $4 OFFSET $5
"""

_SUMMARY_SQL = """\
SELECT
    count(*) FILTER (WHERE status = 'todo') AS todo,
    count(*) FILTER (WHERE status = 'doing') AS doing,
    count(*) FILTER (WHERE status = 'succeeded') AS succeeded,
    count(*) FILTER (WHERE status = 'failed') AS failed,
    count(*) FILTER (WHERE status = 'cancelled') AS cancelled,
    count(*) AS total
FROM procrastinate_jobs
WHERE queue_name = 'extraction'
  AND ($1::text IS NULL OR args->>'agent_id' = $1)
"""

_DETAIL_SQL = """\
SELECT j.id, j.task_name, j.status::text, j.queue_name,
       j.args, j.attempts, j.scheduled_at,
       (SELECT at FROM procrastinate_events e
        WHERE e.job_id = j.id AND e.type = 'started'
        ORDER BY at DESC LIMIT 1) AS started_at,
       (SELECT MIN(at) FROM procrastinate_events e
        WHERE e.job_id = j.id AND e.type = 'deferred') AS created_at,
       (SELECT MAX(at) FROM procrastinate_events e
        WHERE e.job_id = j.id
          AND e.type IN ('succeeded', 'failed', 'cancelled')
       ) AS finished_at
FROM procrastinate_jobs j
WHERE j.id = $1 AND j.queue_name = 'extraction'
"""

_EVENTS_SQL = """\
SELECT type, at FROM procrastinate_events WHERE job_id = $1 ORDER BY at
"""

_CANCEL_SQL = """\
UPDATE procrastinate_jobs SET status = 'cancelled' WHERE id = $1 AND status = 'todo' RETURNING id
"""

_INSERT_CANCEL_EVENT_SQL = """\
INSERT INTO procrastinate_events (job_id, type, at) VALUES ($1, 'cancelled', NOW())
"""


async def _resolve_effective_agent_id(
    request: Request,
    agent_id: str,
    all_agents: bool,
) -> str | None:
    """Return None (no filter) if admin requests all_agents, else the caller's ID."""
    if all_agents:
        permissions = request.app.state.permissions
        if not await permissions.is_admin(agent_id):
            raise HTTPException(403, "Admin required for all_agents view")
        return None
    return agent_id


_JobStatus = Literal["todo", "doing", "succeeded", "failed", "cancelled"]


@router.get("/jobs", response_model=list[JobInfo])
async def list_jobs(
    request: Request,
    agent_id: Annotated[str, Depends(get_agent_id)],
    status: _JobStatus | None = None,
    task_name: str | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    all_agents: bool = False,
):
    pool = _require_pool(request)
    effective_agent_id = await _resolve_effective_agent_id(request, agent_id, all_agents)
    rows = await pool.fetch(
        _LIST_JOBS_SQL,
        effective_agent_id,
        status,
        task_name,
        limit,
        offset,
    )
    return [JobInfo(**dict(r)) for r in rows]


@router.get("/jobs/summary", response_model=JobSummary)
async def job_summary(
    request: Request,
    agent_id: Annotated[str, Depends(get_agent_id)],
    all_agents: bool = False,
):
    pool = _require_pool(request)
    effective_agent_id = await _resolve_effective_agent_id(request, agent_id, all_agents)
    row = await pool.fetchrow(_SUMMARY_SQL, effective_agent_id)
    return JobSummary(**dict(row))


@router.get("/jobs/{job_id}", response_model=JobDetail)
async def job_detail(
    job_id: int,
    request: Request,
    agent_id: Annotated[str, Depends(get_agent_id)],
):
    pool = _require_pool(request)
    row = await pool.fetchrow(_DETAIL_SQL, job_id)
    if row is None:
        raise HTTPException(404, "Job not found")
    # Verify ownership or admin
    args = row["args"]
    if isinstance(args, str):
        args = json.loads(args)
    owner = args.get("agent_id") if isinstance(args, dict) else None
    if owner != agent_id:
        permissions = request.app.state.permissions
        if not await permissions.is_admin(agent_id):
            raise HTTPException(403, "Not authorized to view this job")
    events = await pool.fetch(_EVENTS_SQL, job_id)
    return JobDetail(
        **dict(row),
        events=[JobEvent(**dict(e)) for e in events],
    )


@router.delete("/jobs/{job_id}")
async def cancel_job(
    job_id: int,
    request: Request,
    agent_id: Annotated[str, Depends(get_agent_id)],
):
    pool = _require_pool(request)
    # Verify the caller owns the job or is admin
    job_row = await pool.fetchrow(
        "SELECT args->>'agent_id' AS owner FROM procrastinate_jobs WHERE id = $1",
        job_id,
    )
    if job_row is None:
        raise HTTPException(404, "Job not found")
    owner = job_row["owner"]
    if owner != agent_id:
        permissions = request.app.state.permissions
        if not await permissions.is_admin(agent_id):
            raise HTTPException(403, "Not authorized to cancel this job")
    async with pool.acquire() as conn, conn.transaction():
        result = await conn.fetchrow(_CANCEL_SQL, job_id)
        if result is None:
            raise HTTPException(409, "Job cannot be cancelled (not in 'todo' status)")
        await conn.execute(_INSERT_CANCEL_EVENT_SQL, job_id)
    logger.bind(action_log=True).info("job_cancel", job_id=job_id, agent_id=agent_id)
    return {"status": "cancelled", "job_id": job_id}


@router.post("/jobs/{job_id}/retry")
async def retry_job(
    job_id: int,
    request: Request,
    agent_id: Annotated[str, Depends(get_agent_id)],
):
    pool = _require_pool(request)
    row = await pool.fetchrow(
        "SELECT task_name, args, status::text AS status FROM procrastinate_jobs WHERE id = $1",
        job_id,
    )
    if row is None:
        raise HTTPException(404, "Job not found")
    if row["status"] not in ("failed", "cancelled"):
        raise HTTPException(409, "Only failed or cancelled jobs can be retried")
    # Verify ownership or admin
    original_args = json.loads(row["args"]) if isinstance(row["args"], str) else dict(row["args"])
    owner = original_args.get("agent_id")
    if owner != agent_id:
        permissions = request.app.state.permissions
        if not await permissions.is_admin(agent_id):
            raise HTTPException(403, "Not authorized to retry this job")
    job_app = request.app.state.services_ctx.get("job_app")
    if not job_app:
        raise HTTPException(501, "Job retry requires extraction to be enabled")
    # A legacy extract job may predate opaque correlation ids.  Normalize only
    # this copied retry payload; an existing code-owned id remains byte-for-
    # byte unchanged so a manual retry preserves the original audit lineage.
    retry_correlation_id = None
    if row["task_name"] == "extract_episode":
        original_correlation_id = original_args.get("correlation_id")
        normalized_correlation_id = normalize_extraction_correlation_id(original_correlation_id)
        retry_correlation_id = (
            normalized_correlation_id if normalized_correlation_id != original_correlation_id else None
        )
        original_args["correlation_id"] = normalized_correlation_id
    new_job_id = await job_app.configure_task(row["task_name"]).defer_async(**original_args)
    logger.bind(action_log=True).info(
        "job_retry",
        job_id=job_id,
        new_job_id=new_job_id,
        agent_id=agent_id,
        correlation_id=original_args.get("correlation_id") if row["task_name"] == "extract_episode" else None,
        correlation_generated=retry_correlation_id is not None,
    )
    return {"status": "retried", "original_job_id": job_id, "new_job_id": new_job_id}
