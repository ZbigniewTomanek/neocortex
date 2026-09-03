from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
import uuid
from typing import TYPE_CHECKING

import procrastinate
from loguru import logger

from neocortex.db.protocol import MemoryRepository
from neocortex.ingestion.media_models import MediaIngestionResult, MediaRef
from neocortex.ingestion.models import IngestionResult

if TYPE_CHECKING:
    from neocortex.embedding_service import EmbeddingService
    from neocortex.ingestion.media_compressor import CompressedMedia, MediaCompressor
    from neocortex.ingestion.media_compressor_mock import MockMediaCompressor
    from neocortex.ingestion.media_description import MediaDescription, MediaDescriptionService
    from neocortex.ingestion.media_description_mock import MockMediaDescriptionService
    from neocortex.ingestion.media_store import MediaFileStore


class EpisodeProcessor:
    """Ingestion processor that stores episodes and enqueues extraction jobs.

    After each episode is stored and embedded, an async extraction job is
    deferred via Procrastinate (if a job_app is provided and extraction is
    enabled). The extraction worker in the MCP server process picks up these
    jobs.
    """

    def __init__(
        self,
        repo: MemoryRepository,
        embeddings: EmbeddingService | None = None,
        job_app: procrastinate.App | None = None,
        extraction_enabled: bool = True,
        # Media services
        media_store: MediaFileStore | None = None,
        media_compressor: MediaCompressor | MockMediaCompressor | None = None,
        media_describer: MockMediaDescriptionService | MediaDescriptionService | None = None,
        domain_routing_enabled: bool = True,
    ) -> None:
        self._repo = repo
        self._embeddings = embeddings
        self._job_app = job_app
        self._extraction_enabled = extraction_enabled
        self._media_store = media_store
        self._media_compressor = media_compressor
        self._media_describer = media_describer
        self._domain_routing_enabled = domain_routing_enabled

    async def _embed_episode(self, episode_id: int, text: str, agent_id: str, target_schema: str | None = None) -> None:
        if self._embeddings is None:
            return
        vector = await self._embeddings.embed(text)
        if vector:
            await self._repo.update_episode_embedding(episode_id, vector, agent_id, target_schema=target_schema)

    async def _enqueue_extraction(self, agent_id: str, episode_id: int, target_schema: str | None = None) -> int | None:
        if not self._job_app or not self._extraction_enabled:
            return None
        job_id = await self._job_app.configure_task("extract_episode").defer_async(
            agent_id=agent_id, episode_ids=[episode_id], target_schema=target_schema
        )
        logger.bind(action_log=True).info(
            "extraction_enqueued",
            job_id=job_id,
            episode_id=episode_id,
            agent_id=agent_id,
            target_schema_present=target_schema is not None,
            source="ingestion",
        )
        return job_id

    async def _enqueue_routing(
        self,
        agent_id: str,
        episode_id: int,
        text: str,
        target_schema: str | None = None,
    ) -> None:
        """Enqueue domain routing job if enabled and no explicit target.

        Requires self._job_app (which implies extraction_enabled) and
        self._domain_routing_enabled. Skipped when target_schema is set
        (explicit targeting takes precedence over automatic routing).
        """
        if not self._job_app or not self._domain_routing_enabled or target_schema is not None:
            return
        await self._job_app.configure_task("route_episode").defer_async(
            agent_id=agent_id,
            episode_id=episode_id,
            episode_text=text,
        )
        logger.bind(action_log=True).info(
            "domain_routing_enqueued",
            episode_id=episode_id,
            agent_id=agent_id,
            source="ingestion",
        )

    @staticmethod
    def _compute_hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _compute_hash_bytes(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    async def _store_episode(
        self,
        agent_id: str,
        text: str,
        source_type: str,
        target_schema: str | None = None,
        content_hash: str | None = None,
        metadata: dict | None = None,
        session_id: str | None = None,
    ) -> int:
        if target_schema:
            return await self._repo.store_episode_to(
                agent_id,
                target_schema,
                text,
                source_type=source_type,
                content_hash=content_hash,
                metadata=metadata,
                session_id=session_id,
            )
        return await self._repo.store_episode(
            agent_id,
            text,
            source_type=source_type,
            content_hash=content_hash,
            metadata=metadata,
            session_id=session_id,
        )

    async def process_text(
        self,
        agent_id: str,
        text: str,
        metadata: dict,
        target_schema: str | None = None,
        force: bool = False,
        session_id: str | None = None,
    ) -> IngestionResult:
        request_session_id = session_id or str(uuid.uuid4())
        content_hash = self._compute_hash(text)
        if not force:
            # Note: concurrent requests with identical content may both pass this
            # check before either stores. This is acceptable for the primary use case
            # (sequential re-ingestion of daily notes by a single agent).
            existing = await self._repo.check_episode_hashes(agent_id, [content_hash], target_schema=target_schema)
            if existing:
                return IngestionResult(
                    status="skipped",
                    episodes_created=0,
                    message="Content already ingested",
                    content_hash=content_hash,
                    existing_episode_id=next(iter(existing.values())),
                )
        episode_id = await self._store_episode(
            agent_id,
            text,
            "ingestion_text",
            target_schema,
            content_hash=content_hash,
            metadata=metadata,
            session_id=request_session_id,
        )
        await self._embed_episode(episode_id, text, agent_id, target_schema)
        await self._enqueue_extraction(agent_id, episode_id, target_schema)
        await self._enqueue_routing(agent_id, episode_id, text, target_schema)
        return IngestionResult(
            status="stored",
            episodes_created=1,
            message="Text stored as episode",
            content_hash=content_hash,
        )

    async def process_document(
        self,
        agent_id: str,
        filename: str,
        content: bytes,
        content_type: str,
        metadata: dict,
        target_schema: str | None = None,
        force: bool = False,
        session_id: str | None = None,
    ) -> IngestionResult:
        request_session_id = session_id or str(uuid.uuid4())
        content_hash = self._compute_hash_bytes(content)
        if not force:
            existing = await self._repo.check_episode_hashes(agent_id, [content_hash], target_schema=target_schema)
            if existing:
                return IngestionResult(
                    status="skipped",
                    episodes_created=0,
                    message=f"Document '{filename}' already ingested",
                    content_hash=content_hash,
                    existing_episode_id=next(iter(existing.values())),
                )
        text = content.decode("utf-8", errors="replace")
        episode_id = await self._store_episode(
            agent_id,
            text,
            "ingestion_document",
            target_schema,
            content_hash=content_hash,
            metadata=metadata,
            session_id=request_session_id,
        )
        await self._embed_episode(episode_id, text, agent_id, target_schema)
        await self._enqueue_extraction(agent_id, episode_id, target_schema)
        await self._enqueue_routing(agent_id, episode_id, text, target_schema)
        return IngestionResult(
            status="stored",
            episodes_created=1,
            message=f"Document '{filename}' stored as episode",
            content_hash=content_hash,
        )

    async def process_events(
        self,
        agent_id: str,
        events: list[dict],
        metadata: dict,
        target_schema: str | None = None,
        force: bool = False,
        session_id: str | None = None,
    ) -> IngestionResult:
        request_session_id = session_id or str(uuid.uuid4())
        # Pre-compute hashes for all events
        event_texts = [json.dumps(event, sort_keys=True) for event in events]
        event_hashes = [self._compute_hash(text) for text in event_texts]

        # Batch check existing hashes (unless force)
        existing_hashes: dict[str, int] = {}
        if not force:
            existing_hashes = await self._repo.check_episode_hashes(agent_id, event_hashes, target_schema=target_schema)

        stored = 0
        skipped = 0
        seen_hashes: set[str] = set()
        for event_text, content_hash in zip(event_texts, event_hashes, strict=True):
            # Skip duplicates: already in DB or seen earlier in this batch
            if not force and (content_hash in existing_hashes or content_hash in seen_hashes):
                skipped += 1
                seen_hashes.add(content_hash)
                continue
            seen_hashes.add(content_hash)
            try:
                episode_id = await self._store_episode(
                    agent_id,
                    event_text,
                    "ingestion_event",
                    target_schema,
                    content_hash=content_hash,
                    metadata=metadata,
                    session_id=request_session_id,
                )
                await self._embed_episode(episode_id, event_text, agent_id, target_schema)
                await self._enqueue_extraction(agent_id, episode_id, target_schema)
                await self._enqueue_routing(agent_id, episode_id, event_text, target_schema)
                stored += 1
            except Exception:
                logger.exception("Event ingestion failed after %d/%d events", stored, len(events))
                return IngestionResult(
                    status="partial",
                    episodes_created=stored,
                    message=f"Failed after {stored}/{len(events)} events ({skipped} skipped as duplicates)",
                )

        if skipped == len(events):
            return IngestionResult(
                status="skipped",
                episodes_created=0,
                message=f"All {skipped} events already ingested",
            )
        if skipped > 0:
            return IngestionResult(
                status="partial",
                episodes_created=stored,
                message=f"{stored} events stored, {skipped} skipped as duplicates",
            )
        return IngestionResult(
            status="stored",
            episodes_created=stored,
            message=f"All {stored} events stored",
        )

    async def process_audio(
        self,
        agent_id: str,
        filename: str,
        raw_path: str,
        content_type: str,
        metadata: dict,
        target_schema: str | None = None,
        force: bool = False,
        session_id: str | None = None,
    ) -> MediaIngestionResult:
        """Compress audio -> describe via Gemini -> store file -> store episode."""
        return await self._process_media(
            media_type="audio",
            agent_id=agent_id,
            filename=filename,
            raw_path=raw_path,
            content_type=content_type,
            metadata=metadata,
            target_schema=target_schema,
            compressed_ext="ogg",
            force=force,
            session_id=session_id,
        )

    async def process_video(
        self,
        agent_id: str,
        filename: str,
        raw_path: str,
        content_type: str,
        metadata: dict,
        target_schema: str | None = None,
        force: bool = False,
        session_id: str | None = None,
    ) -> MediaIngestionResult:
        """Compress video -> describe via Gemini -> store file -> store episode."""
        return await self._process_media(
            media_type="video",
            agent_id=agent_id,
            filename=filename,
            raw_path=raw_path,
            content_type=content_type,
            metadata=metadata,
            target_schema=target_schema,
            compressed_ext="mp4",
            force=force,
            session_id=session_id,
        )

    async def _process_media(
        self,
        media_type: str,
        agent_id: str,
        filename: str,
        raw_path: str,
        content_type: str,
        metadata: dict,
        target_schema: str | None,
        compressed_ext: str,
        force: bool = False,
        session_id: str | None = None,
    ) -> MediaIngestionResult:
        """Shared pipeline: compress -> describe -> store file -> store episode.

        Caller is responsible for writing the upload to raw_path; this method
        cleans up raw_path after processing.
        """
        request_session_id = session_id or str(uuid.uuid4())
        # Early dedup check on raw file bytes — before the expensive pipeline
        with open(raw_path, "rb") as f:
            raw_bytes = f.read()
        content_hash = self._compute_hash_bytes(raw_bytes)
        del raw_bytes  # free memory

        if not force:
            existing = await self._repo.check_episode_hashes(agent_id, [content_hash], target_schema=target_schema)
            if existing:
                # Clean up the raw file since we're skipping
                with contextlib.suppress(OSError):
                    os.unlink(raw_path)
                return MediaIngestionResult(
                    status="skipped",
                    episodes_created=0,
                    message=f"{media_type.capitalize()} '{filename}' already ingested",
                    content_hash=content_hash,
                    existing_episode_id=next(iter(existing.values())),
                )

        if self._media_compressor is None:
            return MediaIngestionResult(status="failed", episodes_created=0, message="ffmpeg not available")

        describer = self._media_describer
        if describer is None:
            from neocortex.ingestion.media_description_mock import MockMediaDescriptionService

            describer = MockMediaDescriptionService()

        compressed_path: str | None = None
        try:
            # 1. Compress
            fd_c, compressed_path = tempfile.mkstemp(suffix=f".{compressed_ext}")
            os.close(fd_c)
            compress_fn = getattr(self._media_compressor, f"compress_{media_type}")
            compressed: CompressedMedia = await compress_fn(raw_path, compressed_path)
            # Compressor may change the path (e.g. appending extension)
            compressed_path = compressed.path

            # 3. Describe
            context = metadata.get("context", "")
            describe_fn = getattr(describer, f"describe_{media_type}")
            description: MediaDescription = await describe_fn(compressed.path, compressed.mime_type, context=context)

            # 4. Save to media store (moves compressed file into the store)
            media_ref = None
            if self._media_store is not None:
                media_ref = await self._media_store.save(
                    agent_id=agent_id,
                    source_path=compressed.path,
                    extension=compressed_ext,
                    original_filename=filename,
                    content_type=content_type,
                    duration_seconds=compressed.duration_seconds,
                )
                # File was moved into the store, no longer at compressed_path
                compressed_path = None

            # 5. Build episode text with embedded metadata
            episode_text = self._build_episode_text(
                media_type=media_type,
                filename=filename,
                description=description,
                media_ref=media_ref,
                compressed=compressed,
            )

            # 6-8. Store, embed, enqueue
            source_type = f"ingestion_{media_type}"
            episode_id = await self._store_episode(
                agent_id,
                episode_text,
                source_type,
                target_schema,
                content_hash=content_hash,
                metadata=metadata,
                session_id=request_session_id,
            )
            await self._embed_episode(episode_id, episode_text, agent_id, target_schema)
            await self._enqueue_extraction(agent_id, episode_id, target_schema)
            await self._enqueue_routing(agent_id, episode_id, episode_text, target_schema)

            logger.bind(action_log=True).info(
                "media_ingested",
                media_type=media_type,
                agent_id=agent_id,
                filename_present=bool(filename),
                episode_id=episode_id,
                media_ref_present=media_ref is not None,
            )

            label = media_type.capitalize()
            return MediaIngestionResult(
                status="stored",
                episodes_created=1,
                message=f"{label} '{filename}' processed and stored as episode",
                media_ref=media_ref,
                content_hash=content_hash,
            )
        except Exception:
            label = media_type.capitalize()
            logger.opt(exception=True).error("{} ingestion failed for {}", label, filename)
            return MediaIngestionResult(
                status="failed",
                episodes_created=0,
                message=f"{label} ingestion failed for '{filename}'",
            )
        finally:
            for p in (raw_path, compressed_path):
                if p is not None:
                    with contextlib.suppress(OSError):
                        os.unlink(p)

    @staticmethod
    def _build_episode_text(
        media_type: str,
        filename: str,
        description: MediaDescription,
        media_ref: MediaRef | None,
        compressed: CompressedMedia,
    ) -> str:
        """Build episode text with embedded structured metadata."""
        label = "Audio" if media_type == "audio" else "Video"
        lines = [
            f"[{label}: {filename}]",
            "",
            description.text,
            "",
            "---",
            "Media metadata:",
        ]

        if media_ref is not None:
            lines.append(f"- media_ref: {media_ref.relative_path}")
            lines.append(f"- original_filename: {media_ref.original_filename}")
            lines.append(f"- content_type: {media_ref.content_type}")
            lines.append(f"- compressed_size: {media_ref.compressed_size}")

        lines.append(f"- media_type: {media_type}")
        lines.append(f"- duration_seconds: {compressed.duration_seconds}")
        lines.append(f"- description_model: {description.model}")
        lines.append(f"- description_tokens: {description.token_count}")

        return "\n".join(lines) + "\n"


# Backward-compatible alias
StubProcessor = EpisodeProcessor
