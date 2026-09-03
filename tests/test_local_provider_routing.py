"""Unit coverage for per-agent local OpenAI-compatible model routing."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from openai.types import chat
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.output import OutputObjectDefinition
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import ToolDefinition

from neocortex.mcp_settings import MCPSettings
from neocortex.model_factory import LocalEndpoint, LocalOpenAIChatModel, build_model, build_model_settings


@pytest.fixture
def endpoint() -> LocalEndpoint:
    # Keep routing tests independent of a developer's local .env file. The
    # live preflight supplies explicit environment overrides instead.
    return LocalEndpoint.from_settings(
        MCPSettings(
            local_model_base_url="http://local.example/v1",
            local_model_api_key_env="",
            _env_file=None,  # ty: ignore[unknown-argument]
        )
    )


def test_local_model_uses_configured_endpoint(endpoint: LocalEndpoint) -> None:
    model = build_model("local:qwen3.8-flash-next", endpoint)
    assert isinstance(model, LocalOpenAIChatModel)
    assert model.model_name == "qwen3.8-flash-next"
    assert str(model._provider.base_url).rstrip("/") == "http://local.example/v1"
    assert model._provider.client.api_key == ""


@pytest.mark.asyncio
async def test_local_model_coalesces_static_and_dynamic_instructions(endpoint: LocalEndpoint) -> None:
    model = build_model("local:qwen3.8-flash-next", endpoint)
    assert isinstance(model, OpenAIChatModel)
    messages = [
        ModelRequest(
            parts=[SystemPromptPart("static one"), SystemPromptPart("static two"), UserPromptPart("source")],
            instructions="dynamic context",
        )
    ]

    mapped = await model._map_messages(messages, ModelRequestParameters())

    assert [message["role"] for message in mapped] == ["system", "user"]
    assert mapped[0] == {"role": "system", "content": "static one\n\nstatic two\n\ndynamic context"}
    assert mapped[1] == {"role": "user", "content": "source"}


@pytest.mark.asyncio
async def test_local_model_preserves_tool_call_return_order_and_ids(endpoint: LocalEndpoint) -> None:
    model = build_model("local:qwen3.8-flash-next", endpoint)
    assert isinstance(model, OpenAIChatModel)
    messages = [
        ModelRequest(parts=[SystemPromptPart("instructions"), UserPromptPart("source")]),
        ModelResponse(parts=[ToolCallPart("lookup", '{"query":"source"}', tool_call_id="call-1")]),
        ModelRequest(parts=[ToolReturnPart("lookup", "result", tool_call_id="call-1")]),
    ]

    mapped = await model._map_messages(messages, ModelRequestParameters())

    assert [message["role"] for message in mapped] == ["system", "user", "assistant", "tool"]
    assistant = cast(chat.ChatCompletionAssistantMessageParam, mapped[2])
    tool = cast(chat.ChatCompletionToolMessageParam, mapped[3])
    assert next(iter(assistant["tool_calls"]))["id"] == "call-1"
    assert tool["tool_call_id"] == "call-1"
    assert tool["content"] == "result"


class _EmptyStream:
    async def __aenter__(self) -> _EmptyStream:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def __aiter__(self) -> AsyncIterator[object]:
        return self

    async def __anext__(self) -> object:
        raise StopAsyncIteration


@pytest.mark.asyncio
async def test_local_model_keeps_tools_and_structured_output_request_shape(
    endpoint: LocalEndpoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = build_model("local:qwen3.8-flash-next", endpoint)
    assert isinstance(model, OpenAIChatModel)
    captured: dict[str, object] = {}

    async def create(**kwargs: object) -> _EmptyStream:
        captured.update(kwargs)
        return _EmptyStream()

    monkeypatch.setattr(model.client.chat.completions, "create", create)
    hosted_model = OpenAIChatModel(
        "qwen3.8-flash-next",
        provider=OpenAIProvider(base_url=endpoint.base_url, api_key=""),
    )
    hosted_captured: dict[str, object] = {}

    async def hosted_create(**kwargs: object) -> _EmptyStream:
        hosted_captured.update(kwargs)
        return _EmptyStream()

    monkeypatch.setattr(hosted_model.client.chat.completions, "create", hosted_create)
    params = ModelRequestParameters(
        function_tools=[
            ToolDefinition(
                name="lookup",
                description="Look up source material.",
                parameters_json_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            )
        ],
        output_mode="native",
        output_object=OutputObjectDefinition(
            name="Answer",
            json_schema={"type": "object", "properties": {"answer": {"type": "string"}}},
        ),
    )
    messages = [
        ModelRequest(parts=[SystemPromptPart("static"), UserPromptPart("source")], instructions="dynamic"),
    ]

    stream = await cast(Any, model)._completions_create(messages, True, {}, params)
    await cast(Any, hosted_model)._completions_create(messages, True, {}, params)

    assert isinstance(stream, _EmptyStream)
    assert captured["stream"] is True
    assert captured["messages"] != hosted_captured["messages"]
    for key in ("stream", "tool_choice", "tools", "response_format"):
        assert captured[key] == hosted_captured[key]
    assert captured["messages"] == [
        {"role": "system", "content": "static\n\ndynamic"},
        {"role": "user", "content": "source"},
    ]
    hosted_messages = cast(list[chat.ChatCompletionMessageParam], hosted_captured["messages"])
    assert [message["role"] for message in hosted_messages] == ["system", "system", "user"]


def test_hosted_model_keeps_string_routing(endpoint: LocalEndpoint) -> None:
    model = build_model("openai-responses:gpt-5.4-mini", endpoint)
    assert model == "openai-responses:gpt-5.4-mini"


def test_local_model_requires_base_url() -> None:
    with pytest.raises(ValueError, match="NEOCORTEX_LOCAL_MODEL_BASE_URL"):
        build_model(
            "local:qwen3.8-flash-next",
            LocalEndpoint.from_settings(MCPSettings(_env_file=None)),  # ty: ignore[unknown-argument]
        )


def test_model_settings_preserve_hosted_and_none_behaviour(endpoint: LocalEndpoint) -> None:
    assert build_model_settings(None, "local:qwen", endpoint) is None
    hosted = build_model_settings("medium", "openai-responses:gpt-5.4-mini", endpoint)
    assert hosted == ModelSettings(thinking="medium")


def test_local_model_settings_include_sampling_and_timeout(endpoint: LocalEndpoint) -> None:
    settings = build_model_settings("xhigh", "local:qwen3.8-flash-next", endpoint)
    assert settings == ModelSettings(thinking="xhigh", temperature=0.6, top_p=0.95, timeout=600.0)

    nothink_endpoint = LocalEndpoint(
        base_url=endpoint.base_url,
        api_key_env=endpoint.api_key_env,
        temperature=endpoint.temperature,
        top_p=endpoint.top_p,
        temperature_nothink=0.3,
        top_p_nothink=0.9,
        timeout_s=42.0,
    )
    settings = build_model_settings(False, "local:qwen3.8-flash-next", nothink_endpoint)
    assert settings == ModelSettings(thinking=False, temperature=0.3, top_p=0.9, timeout=42.0)


def test_two_agents_can_use_different_providers(endpoint: LocalEndpoint) -> None:
    local = build_model("local:qwen3.8-flash-next", endpoint)
    hosted = build_model("openai-responses:gpt-5.4-mini", endpoint)
    assert isinstance(local, OpenAIChatModel)
    assert hosted == "openai-responses:gpt-5.4-mini"


def test_local_model_reads_authentication_only_from_configured_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_VLLM_API_KEY", "test-only-key")
    settings = MCPSettings(
        local_model_base_url="http://local.example/v1",
        local_model_api_key_env="TEST_VLLM_API_KEY",
        _env_file=None,  # ty: ignore[unknown-argument]
    )

    model = build_model("local:qwen3.8-flash-next", LocalEndpoint.from_settings(settings))

    assert isinstance(model, OpenAIChatModel)
    assert model._provider.client.api_key == "test-only-key"


def test_local_model_requires_configured_authentication_when_environment_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TEST_VLLM_API_KEY", raising=False)
    settings = MCPSettings(
        local_model_base_url="http://local.example/v1",
        local_model_api_key_env="TEST_VLLM_API_KEY",
        _env_file=None,  # ty: ignore[unknown-argument]
    )

    with pytest.raises(ValueError, match="TEST_VLLM_API_KEY"):
        build_model("local:qwen3.8-flash-next", LocalEndpoint.from_settings(settings))


def test_local_sampling_and_timeout_settings_are_environment_driven(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        "NEOCORTEX_LOCAL_MODEL_BASE_URL": "http://local.example/v1",
        "NEOCORTEX_LOCAL_MODEL_API_KEY_ENV": "TEST_VLLM_API_KEY",
        "NEOCORTEX_LOCAL_MODEL_TEMPERATURE": "0.4",
        "NEOCORTEX_LOCAL_MODEL_TOP_P": "0.8",
        "NEOCORTEX_LOCAL_MODEL_TEMPERATURE_NOTHINK": "0.2",
        "NEOCORTEX_LOCAL_MODEL_TOP_P_NOTHINK": "0.7",
        "NEOCORTEX_LOCAL_MODEL_TIMEOUT_S": "123",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    settings = MCPSettings(_env_file=None)  # ty: ignore[unknown-argument]
    endpoint = LocalEndpoint.from_settings(settings)

    assert endpoint.base_url == "http://local.example/v1"
    assert endpoint.api_key_env == "TEST_VLLM_API_KEY"
    assert endpoint.temperature == 0.4
    assert endpoint.top_p == 0.8
    assert endpoint.temperature_nothink == 0.2
    assert endpoint.top_p_nothink == 0.7
    assert endpoint.timeout_s == 123.0
