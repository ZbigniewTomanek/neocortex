from __future__ import annotations

import json
import os
import tempfile
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from loguru import logger

from neocortex.ingestion.auth import get_agent_id
from neocortex.ingestion.media_models import MediaIngestionResult
from neocortex.ingestion.models import (
    EventsIngestionRequest,
    HashCheckRequest,
    HashCheckResult,
    IngestionResult,
    TextIngestionRequest,
)

router = APIRouter(prefix="/ingest", tags=["ingestion"])

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
_ACCEPTED_CONTENT_TYPES = {
    "text/plain",
    "application/json",
    "text/markdown",
    "text/csv",
}

_ACCEPTED_AUDIO_TYPES = {
    "audio/mpeg",  # .mp3
    "audio/wav",  # .wav
    "audio/x-wav",  # .wav (alternative)
    "audio/ogg",  # .ogg
    "audio/flac",  # .flac
    "audio/aac",  # .aac
    "audio/mp4",  # .m4a
    "audio/webm",  # .weba
}

_ACCEPTED_VIDEO_TYPES = {
    "video/mp4",  # .mp4
    "video/mpeg",  # .mpeg
    "video/webm",  # .webm
    "video/quicktime",  # .mov
    "video/x-msvideo",  # .avi
    "video/x-matroska",  # .mkv
    "video/3gpp",  # .3gp
}


async def _check_write_permission(request: Request, agent_id: str, target_graph: str) -> None:
    """Raise 403 if the agent lacks write access to the target shared graph."""
    permissions = request.app.state.permissions
    if not await permissions.can_write_schema(agent_id, target_graph):
        raise HTTPException(
            status_code=403,
            detail=f"Agent '{agent_id}' does not have write access to '{target_graph}'",
        )


@router.post("/text", response_model=IngestionResult)
async def ingest_text(
    body: TextIngestionRequest,
    request: Request,
    agent_id: Annotated[str, Depends(get_agent_id)],
) -> IngestionResult:
    if body.target_graph:
        await _check_write_permission(request, agent_id, body.target_graph)
    processor = request.app.state.processor
    return await processor.process_text(
        agent_id,
        body.text,
        body.metadata,
        target_schema=body.target_graph,
        force=body.force,
        session_id=body.session_id,
    )


@router.post("/document", response_model=IngestionResult)
async def ingest_document(
    file: UploadFile,
    request: Request,
    agent_id: Annotated[str, Depends(get_agent_id)],
    metadata: str | None = Form(default=None),
    target_graph: str | None = Form(default=None),
    session_id: str | None = Form(default=None),
    force: bool = Form(default=False),
) -> IngestionResult:
    if target_graph:
        await _check_write_permission(request, agent_id, target_graph)

    # Validate content type
    content_type = file.content_type or "application/octet-stream"
    if content_type not in _ACCEPTED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported content type '{content_type}'. Accepted: {', '.join(sorted(_ACCEPTED_CONTENT_TYPES))}",
        )

    # Read up to the limit + 1 byte so we can detect oversized uploads
    # without buffering the entire file into memory.
    content_bytes = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(content_bytes) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum upload size of {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
        )

    parsed_metadata: dict = {}
    if metadata:
        try:
            parsed_metadata = json.loads(metadata)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid metadata JSON: {exc}") from exc

    processor = request.app.state.processor
    return await processor.process_document(
        agent_id,
        file.filename or "unknown",
        content_bytes,
        content_type,
        parsed_metadata,
        target_schema=target_graph,
        force=force,
        session_id=session_id,
    )


@router.post("/events", response_model=IngestionResult)
async def ingest_events(
    body: EventsIngestionRequest,
    request: Request,
    agent_id: Annotated[str, Depends(get_agent_id)],
) -> IngestionResult:
    if body.target_graph:
        await _check_write_permission(request, agent_id, body.target_graph)
    processor = request.app.state.processor
    return await processor.process_events(
        agent_id,
        body.events,
        body.metadata,
        target_schema=body.target_graph,
        force=body.force,
        session_id=body.session_id,
    )


async def _stream_upload_to_temp(
    file: UploadFile,
    max_bytes: int,
    suffix: str,
) -> str:
    """Stream an UploadFile to a temp file, enforcing a size limit.

    Returns the temp file path. Raises HTTPException(413) if the file exceeds
    max_bytes. Caller is responsible for deleting the temp file.
    """
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    try:
        total = 0
        chunk_size = 256 * 1024  # 256 KB
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                os.close(fd)
                os.unlink(tmp_path)
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds maximum upload size of {max_bytes // (1024 * 1024)} MB",
                )
            os.write(fd, chunk)
        os.close(fd)
    except HTTPException:
        raise
    except Exception:
        os.close(fd)
        os.unlink(tmp_path)
        raise
    return tmp_path


@router.post("/audio", response_model=MediaIngestionResult)
async def ingest_audio(
    file: UploadFile,
    request: Request,
    agent_id: Annotated[str, Depends(get_agent_id)],
    metadata: str | None = Form(default=None),
    target_graph: str | None = Form(default=None),
    session_id: str | None = Form(default=None),
    force: bool = Form(default=False),
) -> MediaIngestionResult:
    if target_graph:
        await _check_write_permission(request, agent_id, target_graph)

    content_type = file.content_type or "application/octet-stream"
    if content_type not in _ACCEPTED_AUDIO_TYPES:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported audio content type '{content_type}'. "
                f"Accepted: {', '.join(sorted(_ACCEPTED_AUDIO_TYPES))}"
            ),
        )

    settings = request.app.state.settings
    suffix = os.path.splitext(file.filename or "upload")[1] or ".bin"
    raw_path = await _stream_upload_to_temp(file, settings.media_max_upload_bytes, suffix)

    parsed_metadata: dict = {}
    if metadata:
        try:
            parsed_metadata = json.loads(metadata)
        except json.JSONDecodeError as exc:
            os.unlink(raw_path)
            raise HTTPException(status_code=422, detail=f"Invalid metadata JSON: {exc}") from exc

    processor = request.app.state.processor
    result = await processor.process_audio(
        agent_id,
        file.filename or "unknown",
        raw_path,
        content_type,
        parsed_metadata,
        target_schema=target_graph,
        force=force,
        session_id=session_id,
    )

    logger.bind(action_log=True).info(
        "ingest_audio",
        agent_id=agent_id,
        filename_present=bool(file.filename),
        content_type=content_type,
        status=result.status,
    )

    return result


@router.post("/video", response_model=MediaIngestionResult)
async def ingest_video(
    file: UploadFile,
    request: Request,
    agent_id: Annotated[str, Depends(get_agent_id)],
    metadata: str | None = Form(default=None),
    target_graph: str | None = Form(default=None),
    session_id: str | None = Form(default=None),
    force: bool = Form(default=False),
) -> MediaIngestionResult:
    if target_graph:
        await _check_write_permission(request, agent_id, target_graph)

    content_type = file.content_type or "application/octet-stream"
    if content_type not in _ACCEPTED_VIDEO_TYPES:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported video content type '{content_type}'. "
                f"Accepted: {', '.join(sorted(_ACCEPTED_VIDEO_TYPES))}"
            ),
        )

    settings = request.app.state.settings
    suffix = os.path.splitext(file.filename or "upload")[1] or ".bin"
    raw_path = await _stream_upload_to_temp(file, settings.media_max_upload_bytes, suffix)

    parsed_metadata: dict = {}
    if metadata:
        try:
            parsed_metadata = json.loads(metadata)
        except json.JSONDecodeError as exc:
            os.unlink(raw_path)
            raise HTTPException(status_code=422, detail=f"Invalid metadata JSON: {exc}") from exc

    processor = request.app.state.processor
    result = await processor.process_video(
        agent_id,
        file.filename or "unknown",
        raw_path,
        content_type,
        parsed_metadata,
        target_schema=target_graph,
        force=force,
        session_id=session_id,
    )

    logger.bind(action_log=True).info(
        "ingest_video",
        agent_id=agent_id,
        filename_present=bool(file.filename),
        content_type=content_type,
        status=result.status,
    )

    return result


@router.post("/check", response_model=HashCheckResult)
async def check_hashes(
    body: HashCheckRequest,
    request: Request,
    agent_id: Annotated[str, Depends(get_agent_id)],
) -> HashCheckResult:
    repo = request.app.state.services_ctx["repo"]
    existing = await repo.check_episode_hashes(agent_id, body.hashes, target_schema=body.target_graph)
    missing = [h for h in body.hashes if h not in existing]

    logger.bind(action_log=True).info(
        "hash_check",
        agent_id=agent_id,
        hashes_checked=len(body.hashes),
        hashes_found=len(existing),
    )

    return HashCheckResult(existing=existing, missing=missing)
