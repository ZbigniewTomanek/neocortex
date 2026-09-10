"""Model construction for hosted and per-agent local OpenAI-compatible models."""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import cast

from openai.types import chat
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings, ThinkingLevel

LOCAL_PREFIX = "local:"


@dataclass(frozen=True)
class LocalEndpoint:
    """Resolved local endpoint configuration, shared by all agent builders."""

    base_url: str | None
    api_key_env: str
    temperature: float
    top_p: float
    temperature_nothink: float
    top_p_nothink: float
    timeout_s: float

    @classmethod
    def from_settings(cls, settings) -> LocalEndpoint:
        return cls(
            base_url=settings.local_model_base_url,
            api_key_env=settings.local_model_api_key_env,
            temperature=settings.local_model_temperature,
            top_p=settings.local_model_top_p,
            temperature_nothink=settings.local_model_temperature_nothink,
            top_p_nothink=settings.local_model_top_p_nothink,
            timeout_s=settings.local_model_timeout_s,
        )


def is_local_model(model_name: str) -> bool:
    return model_name.startswith(LOCAL_PREFIX)


def is_qwen_model(model_name: str) -> bool:
    """Return whether the provider-stripped identifier names the Qwen family."""
    identifier = model_name.split(":", 1)[-1].lower()
    return identifier.startswith("qwen") or "/qwen" in identifier


class LocalOpenAIChatModel(OpenAIChatModel):
    """OpenAI chat model adapter for strict local OpenAI-compatible servers.

    PydanticAI 1.72.0 maps each static or dynamic instruction to a separate
    system message. Some local servers accept only one system message at the
    start of a chat request. This override uses PydanticAI's private
    ``_map_messages`` hook, so the pinned dependency must be rechecked before
    upgrading: a signature or mapping-contract change can invalidate this
    compatibility adapter.
    """

    async def _map_messages(
        self, messages: Sequence[ModelMessage], model_request_parameters: ModelRequestParameters
    ) -> list[chat.ChatCompletionMessageParam]:
        """Coalesce mapped system messages while preserving all other messages."""
        mapped = await super()._map_messages(messages, model_request_parameters)
        system_content: list[str] = []
        non_system: list[chat.ChatCompletionMessageParam] = []

        for message in mapped:
            if message.get("role") != "system":
                non_system.append(message)
                continue

            content = cast(str | Iterable[chat.ChatCompletionContentPartTextParam], message["content"])
            if isinstance(content, str):
                system_content.append(content)
            else:
                system_content.extend(part["text"] for part in content)

        if not system_content:
            return non_system

        system_message = chat.ChatCompletionSystemMessageParam(
            role="system",
            content="\n\n".join(system_content),
        )
        return [system_message, *non_system]


def build_model(model_name: str, endpoint: LocalEndpoint | None) -> str | Model:
    """Build a model object for local names and preserve hosted string routing."""
    if not is_local_model(model_name):
        return model_name
    if endpoint is None or not endpoint.base_url:
        raise ValueError(f"{model_name!r} requires NEOCORTEX_LOCAL_MODEL_BASE_URL to be set")
    api_key = os.environ.get(endpoint.api_key_env, "") if endpoint.api_key_env else ""
    if endpoint.api_key_env and not api_key:
        raise ValueError(f"{model_name!r} requires {endpoint.api_key_env} to be set for the local endpoint")
    return LocalOpenAIChatModel(
        model_name.removeprefix(LOCAL_PREFIX),
        provider=OpenAIProvider(
            base_url=endpoint.base_url,
            api_key=api_key,
        ),
    )


def build_model_settings(
    thinking_effort: ThinkingLevel | None,
    model_name: str,
    endpoint: LocalEndpoint | None,
) -> ModelSettings | None:
    """Build common pydantic-ai settings, adding sampling controls for local models."""
    if thinking_effort is None:
        return None
    if not is_local_model(model_name):
        return ModelSettings(thinking=thinking_effort)
    if endpoint is None:
        raise ValueError(f"{model_name!r} requires NEOCORTEX_LOCAL_MODEL_BASE_URL to be set")
    thinking_on = thinking_effort is not False
    return ModelSettings(
        thinking=thinking_effort,
        temperature=endpoint.temperature if thinking_on else endpoint.temperature_nothink,
        top_p=endpoint.top_p if thinking_on else endpoint.top_p_nothink,
        timeout=endpoint.timeout_s,
    )
