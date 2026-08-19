"""Model construction for hosted and per-agent local OpenAI-compatible models."""

from __future__ import annotations

import os
from dataclasses import dataclass

from pydantic_ai.models import Model
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


def build_model(model_name: str, endpoint: LocalEndpoint | None) -> str | Model:
    """Build a model object for local names and preserve hosted string routing."""
    if not is_local_model(model_name):
        return model_name
    if endpoint is None or not endpoint.base_url:
        raise ValueError(f"{model_name!r} requires NEOCORTEX_LOCAL_MODEL_BASE_URL to be set")
    return OpenAIChatModel(
        model_name.removeprefix(LOCAL_PREFIX),
        provider=OpenAIProvider(
            base_url=endpoint.base_url,
            api_key=os.environ.get(endpoint.api_key_env, ""),
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
