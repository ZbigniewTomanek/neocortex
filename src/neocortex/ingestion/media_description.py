from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from loguru import logger


@dataclass
class MediaDescription:
    text: str  # Full generated description (stored as episode content)
    model: str  # Model used
    token_count: int  # Tokens consumed (for audit logging)


_AUDIO_PROMPT = """Provide a detailed description of this audio. Include:
- Full transcription if speech is present
- Speaker identification where possible
- Description of non-speech audio (music, sounds, silence)
- Language(s) detected
- Overall summary"""

_VIDEO_PROMPT = """Provide a detailed description of this video. Include:
- Scene-by-scene description with timestamps
- Full transcription of any speech
- Description of visual elements, actions, and text on screen
- Key objects, people, locations identified
- Overall summary"""

_POLL_INTERVAL_SECONDS = 5
_POLL_TIMEOUT_SECONDS = 300  # 5 minutes


class MediaDescriptionService:
    """Generates text descriptions of audio/video using Gemini multimodal inference.

    Uses the Gemini Files API for upload (handles files up to 2GB) and
    generate_content for multimodal inference. Files are deleted from
    Gemini after description is generated (they auto-expire after 48h
    regardless).
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3-flash-preview",
        max_output_tokens: int = 8192,
    ) -> None:
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._client = None

        if api_key:
            from google import genai

            self._client = genai.Client(api_key=api_key)
            logger.info("MediaDescriptionService initialized with model={}", self._model)
        else:
            logger.warning("No API key provided — MediaDescriptionService will return placeholder descriptions")

    async def describe_audio(self, file_path: str, mime_type: str, context: str = "") -> MediaDescription:
        """Generate a text description of an audio file via Gemini."""
        prompt = _AUDIO_PROMPT
        if context:
            prompt += f"\n\nContext from the user: {context}"

        result = await self._describe(file_path, mime_type, prompt, "audio")

        logger.bind(action_log=True).info(
            "media_description_generated",
            media_type="audio",
            model=self._model,
            file_path_present=bool(file_path),
            token_count=result.token_count,
            description_length=len(result.text),
        )

        return result

    async def describe_video(self, file_path: str, mime_type: str, context: str = "") -> MediaDescription:
        """Generate a text description of a video file via Gemini."""
        prompt = _VIDEO_PROMPT
        if context:
            prompt += f"\n\nContext from the user: {context}"

        result = await self._describe(file_path, mime_type, prompt, "video")

        logger.bind(action_log=True).info(
            "media_description_generated",
            media_type="video",
            model=self._model,
            file_path_present=bool(file_path),
            token_count=result.token_count,
            description_length=len(result.text),
        )

        return result

    async def _describe(self, file_path: str, mime_type: str, prompt: str, media_type: str) -> MediaDescription:
        """Upload file to Gemini, generate description, and clean up."""
        if self._client is None:
            return MediaDescription(
                text=f"[No API key — placeholder description for {os.path.basename(file_path)}]",
                model="none",
                token_count=0,
            )

        uploaded_file = None
        try:
            uploaded_file = await self._upload_and_wait(file_path, mime_type)

            from google.genai import types

            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=[uploaded_file, prompt],
                config=types.GenerateContentConfig(
                    max_output_tokens=self._max_output_tokens,
                ),
            )

            text = response.text or ""
            token_count = 0
            if response.usage_metadata and response.usage_metadata.total_token_count:
                token_count = response.usage_metadata.total_token_count

            return MediaDescription(text=text, model=self._model, token_count=token_count)

        except Exception:
            logger.opt(exception=True).warning("Gemini {} description failed for {}", media_type, file_path)
            return MediaDescription(
                text=f"[Description generation failed for {os.path.basename(file_path)}]",
                model=self._model,
                token_count=0,
            )
        finally:
            if uploaded_file and uploaded_file.name:
                await self._cleanup_file(uploaded_file.name)

    async def _upload_and_wait(self, file_path: str, mime_type: str) -> object:
        """Upload a file to Gemini Files API and poll until ACTIVE."""
        from google.genai import types

        assert self._client is not None  # Caller guards on _client
        logger.debug("Uploading {} to Gemini Files API", file_path)

        uploaded = await self._client.aio.files.upload(
            file=file_path,
            config=types.UploadFileConfig(mime_type=mime_type),
        )

        elapsed = 0.0
        while uploaded.state and uploaded.state.value == "PROCESSING":
            if elapsed >= _POLL_TIMEOUT_SECONDS:
                raise TimeoutError(f"Gemini file processing timed out after {_POLL_TIMEOUT_SECONDS}s")
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            elapsed += _POLL_INTERVAL_SECONDS
            assert uploaded.name is not None
            uploaded = await self._client.aio.files.get(name=uploaded.name)
            logger.debug("Polling file state: {} ({}s elapsed)", uploaded.state, elapsed)

        if uploaded.state and uploaded.state.value == "FAILED":
            raise RuntimeError(f"Gemini file processing failed: {uploaded.error}")

        return uploaded

    async def _cleanup_file(self, file_name: str) -> None:
        """Best-effort delete of uploaded file from Gemini."""
        assert self._client is not None  # Caller guards on _client
        try:
            await self._client.aio.files.delete(name=file_name)
            logger.debug("Deleted Gemini file {}", file_name)
        except Exception:
            logger.opt(exception=True).warning("Failed to delete Gemini file {}", file_name)
