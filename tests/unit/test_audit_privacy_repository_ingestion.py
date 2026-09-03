"""Adversarial checks for durable action-log privacy at repository boundaries."""

from __future__ import annotations

import io
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request, UploadFile
from fastmcp import Context
from loguru import logger

from neocortex.db.adapter import GraphServiceAdapter
from neocortex.db.mock import InMemoryRepository
from neocortex.graph_service import GraphService
from neocortex.ingestion.episode_processor import EpisodeProcessor
from neocortex.ingestion.media_compressor_mock import MockMediaCompressor
from neocortex.ingestion.media_description import MediaDescriptionService
from neocortex.mcp_settings import MCPSettings


def _action_records(records: list[dict]) -> list[dict]:
    return [record for record in records if record["extra"].get("action_log")]


@pytest.mark.asyncio
async def test_mock_repository_dedup_audit_contains_no_model_or_source_values() -> None:
    repo = InMemoryRepository()
    agent_id = "test-agent"
    person_type = await repo.get_or_create_node_type(agent_id, "Person")
    organization_type = await repo.get_or_create_node_type(agent_id, "Organization")
    engineer_type = await repo.get_or_create_node_type(agent_id, "Engineer")
    assert person_type and organization_type and engineer_type

    alias_sentinel = "PRIVATE_ALIAS_SENTINEL"
    fuzzy_sentinel = "PRIVATE_FUZZY_TARGET_SENTINEL"
    drift_sentinel = "PRIVATE_DRIFT_SENTINEL"
    homonym_sentinel = "PRIVATE_HOMONYM_SENTINEL"
    records: list[dict] = []
    sink_id = logger.add(lambda message: records.append(message.record), level="INFO")
    try:
        await repo.upsert_node(agent_id, f"Private Canonical ({alias_sentinel})", person_type.id)
        await repo.upsert_node(agent_id, alias_sentinel, person_type.id)

        await repo.upsert_node(agent_id, f"{fuzzy_sentinel} Name", person_type.id)
        await repo.upsert_node(agent_id, f"{fuzzy_sentinel} Name Extra", person_type.id)

        await repo.upsert_node(agent_id, drift_sentinel, person_type.id)
        await repo.upsert_node(agent_id, drift_sentinel, engineer_type.id)

        await repo.upsert_node(agent_id, homonym_sentinel, person_type.id)
        await repo.upsert_node(agent_id, homonym_sentinel, organization_type.id)
    finally:
        logger.remove(sink_id)

    action_records = _action_records(records)
    assert action_records
    assert all(
        sentinel not in str(record["extra"])
        for sentinel in (alias_sentinel, fuzzy_sentinel, drift_sentinel, homonym_sentinel)
        for record in action_records
    )
    alias_record = next(record for record in action_records if record["message"] == "node_alias_resolved")
    assert alias_record["extra"]["candidate_node_ids"]
    fuzzy_record = next(record for record in action_records if record["message"] == "node_fuzzy_matched")
    assert isinstance(fuzzy_record["extra"]["matched_node_id"], int)
    drift_record = next(record for record in action_records if record["message"] == "node_type_drift_caught")
    assert isinstance(drift_record["extra"]["node_id"], int)
    homonym_record = next(record for record in action_records if record["message"] == "node_homonym_detected")
    assert homonym_record["extra"]["action"] == "created_separate"


@pytest.mark.asyncio
async def test_adapter_rejected_type_audit_contains_no_rejected_value_or_error() -> None:
    # Invalid normalization returns before the adapter needs a live database.
    adapter = GraphServiceAdapter(cast(GraphService, object()), settings=MCPSettings.model_construct())
    node_sentinel = "PRIVATE_INVALID_NODE_TYPE_SENTINEL"
    edge_sentinel = "PRIVATE_INVALID_EDGE_TYPE_SENTINEL"
    records: list[dict] = []
    sink_id = logger.add(lambda message: records.append(message.record), level="INFO")
    try:
        assert await adapter.get_or_create_node_type("agent", f"<think>{node_sentinel}</think>") is None
        assert await adapter.get_or_create_edge_type("agent", f"<tool_call>{edge_sentinel}</tool_call>") is None
    finally:
        logger.remove(sink_id)

    action_records = _action_records(records)
    assert {record["message"] for record in action_records} == {
        "invalid_node_type_rejected",
        "invalid_edge_type_rejected",
    }
    assert all(
        sentinel not in str(record["extra"]) for sentinel in (node_sentinel, edge_sentinel) for record in action_records
    )
    assert all("error" not in record["extra"] and "raw_name" not in record["extra"] for record in action_records)


class _Upload:
    def __init__(self, filename: str, content_type: str, payload: bytes = b"media") -> None:
        self.filename = filename
        self.content_type = content_type
        self._payload = io.BytesIO(payload)

    async def read(self, _size: int = -1) -> bytes:
        return self._payload.read(_size)


@pytest.mark.asyncio
async def test_ingestion_action_audit_contains_no_filename_path_or_schema() -> None:
    from neocortex.ingestion.routes import ingest_audio, ingest_video

    filename_sentinel = "PRIVATE_MEDIA_FILENAME_SENTINEL.wav"
    path_sentinel = "/private/source/PRIVATE_MEDIA_PATH_SENTINEL.wav"
    schema_sentinel = "ncx_shared__PRIVATE_MEDIA_SCHEMA_SENTINEL"
    job_app = MagicMock()
    job_app.configure_task.return_value.defer_async = AsyncMock(return_value=42)
    processor = EpisodeProcessor(
        repo=InMemoryRepository(),
        job_app=job_app,
        media_compressor=MockMediaCompressor(),
        media_describer=MediaDescriptionService(api_key=""),
    )
    processor._media_store = None
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(media_max_upload_bytes=1024 * 1024),
                processor=processor,
            )
        )
    )
    records: list[dict] = []
    sink_id = logger.add(lambda message: records.append(message.record), level="INFO")
    try:
        await processor._enqueue_extraction("agent", 1, target_schema=schema_sentinel)
        # The route calls the same processor path, including the media audit
        # event, while its request log covers the upload boundary.
        await ingest_audio(
            cast(UploadFile, _Upload(filename_sentinel, "audio/wav")),
            cast(Request, request),
            "agent",
            metadata=None,
            target_graph=None,
            session_id=None,
            force=False,
        )
        await ingest_video(
            cast(UploadFile, _Upload(filename_sentinel.replace(".wav", ".mp4"), "video/mp4")),
            cast(Request, request),
            "agent",
            metadata=None,
            target_graph=None,
            session_id=None,
            force=False,
        )
        await MediaDescriptionService(api_key="").describe_audio(path_sentinel, "audio/wav")
    finally:
        logger.remove(sink_id)

    action_records = _action_records(records)
    assert action_records
    assert all(
        sentinel not in str(record["extra"])
        for sentinel in (filename_sentinel, path_sentinel, schema_sentinel)
        for record in action_records
    )
    media_record = next(record for record in action_records if record["message"] == "media_ingested")
    assert media_record["extra"]["filename_present"] is True
    description_record = next(record for record in action_records if record["message"] == "media_description_generated")
    assert description_record["extra"]["file_path_present"] is True


@pytest.mark.asyncio
async def test_tool_action_audit_contains_no_graph_node_type_or_query_values() -> None:
    from neocortex.tools.discover import browse_nodes, discover_details, discover_ontology, inspect_node
    from neocortex.tools.remember import remember

    source_sentinel = "PRIVATE_TOOL_SOURCE_SENTINEL"
    graph_sentinel = "ncx_shared__PRIVATE_TOOL_GRAPH_SENTINEL"
    query_sentinel = "PRIVATE_QUERY_SENTINEL"
    repo = InMemoryRepository()
    settings = MCPSettings(mock_db=True, extraction_enabled=True, domain_routing_enabled=False)
    job_app = MagicMock()
    job_app.configure_task.return_value.defer_async = AsyncMock(return_value=11)
    router = SimpleNamespace(route_store_to=AsyncMock(return_value=graph_sentinel))
    ctx = SimpleNamespace(
        lifespan_context={"repo": repo, "settings": settings, "job_app": job_app, "router": router, "embeddings": None}
    )
    records: list[dict] = []
    sink_id = logger.add(lambda message: records.append(message.record), level="INFO")
    try:
        with patch("neocortex.tools.remember.get_agent_id_from_context", return_value="agent"):
            await remember(query_sentinel, target_graph=graph_sentinel, ctx=cast(Context, ctx))
        with patch("neocortex.tools.discover.get_agent_id_from_context", return_value="agent"):
            await discover_ontology(graph_sentinel, ctx=cast(Context, ctx))
            await discover_details(source_sentinel, graph_sentinel, ctx=cast(Context, ctx))
            await browse_nodes(graph_sentinel, type_name=source_sentinel, ctx=cast(Context, ctx))
            await inspect_node(source_sentinel, graph_sentinel, ctx=cast(Context, ctx))
    finally:
        logger.remove(sink_id)

    action_records = _action_records(records)
    assert action_records
    assert all(
        sentinel not in str(record["extra"])
        for sentinel in (source_sentinel, graph_sentinel, query_sentinel)
        for record in action_records
    )
