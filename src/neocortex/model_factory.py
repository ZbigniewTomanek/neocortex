"""Model construction for hosted and per-agent local OpenAI-compatible models."""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import cast

from openai.types import chat
from openai.types.shared import ReasoningEffort
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.profiles.openai import OPENAI_REASONING_EFFORT_MAP
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


def qwen_nothink_extra_body() -> dict[str, object]:
    """Return the chat-template switch that turns Qwen thinking off server-side.

    The unified ``thinking=False`` setting alone is not enough: PydanticAI
    1.72.0 resolves ``ModelSettings.thinking`` against the model profile, and
    ``openai_model_profile`` reports ``supports_thinking=False`` for every model
    name it does not recognise (Qwen included).  ``Model.prepare_request`` then
    drops the setting silently, ``ModelRequestParameters.thinking`` stays
    ``None``, and ``OpenAIChatModel._get_reasoning_effort`` omits
    ``reasoning_effort`` from the request — so the server keeps thinking on.
    ``openai_reasoning_effort`` is read before the profile is consulted, so
    setting it explicitly restores the intent; this chat-template kwarg covers
    servers that ignore the OpenAI field.  A fresh dict per call: the value
    travels into request bodies that must not share mutable state.
    """
    return {"chat_template_kwargs": {"enable_thinking": False}}


# Per-agent output ceilings for Qwen models, in tokens.  The local endpoint
# decodes at ~34 tokens/s, so an unbounded response is an unbounded stage.
# ``MCPSettings.<agent>_max_tokens`` defaults to these and can override them.
QWEN_MAX_OUTPUT_TOKENS: dict[str, int] = {
    "ontology": 600,
    "extractor": 2500,
    "librarian": 1500,
    "domain_classifier": 400,
}


def build_model_settings(
    thinking_effort: ThinkingLevel | None,
    model_name: str,
    endpoint: LocalEndpoint | None,
    *,
    max_output_tokens: int | None = None,
) -> ModelSettings | None:
    """Build common pydantic-ai settings, adding sampling controls for local models.

    ``max_output_tokens`` bounds the response of Qwen models only; hosted and
    other local models keep the provider default.
    """
    if thinking_effort is None:
        return None
    if not is_local_model(model_name):
        return ModelSettings(thinking=thinking_effort)
    if endpoint is None:
        raise ValueError(f"{model_name!r} requires NEOCORTEX_LOCAL_MODEL_BASE_URL to be set")
    thinking_on = thinking_effort is not False
    # The OpenAI-flavoured settings mapping: a superset of ModelSettings that
    # also carries ``openai_reasoning_effort``.
    settings = OpenAIChatModelSettings(
        thinking=thinking_effort,
        temperature=endpoint.temperature if thinking_on else endpoint.temperature_nothink,
        top_p=endpoint.top_p if thinking_on else endpoint.top_p_nothink,
        timeout=endpoint.timeout_s,
    )
    if not is_qwen_model(model_name):
        return settings
    if max_output_tokens is not None:
        settings["max_tokens"] = max_output_tokens
    # ``supports_thinking=False`` drops ``thinking`` for every effort value, not
    # only ``False`` (see ``qwen_nothink_extra_body``), so every level has to be
    # restated through ``openai_reasoning_effort`` or the request carries no
    # effort at all and ``low``/``medium``/``high`` reach the server identical.
    # The map is PydanticAI's own, so the wire value matches what the profile
    # would have produced had it recognised the model.
    settings["openai_reasoning_effort"] = cast(ReasoningEffort, OPENAI_REASONING_EFFORT_MAP[thinking_effort])
    if not thinking_on:
        settings["extra_body"] = qwen_nothink_extra_body()
    return settings
