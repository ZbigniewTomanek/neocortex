"""Unit coverage for per-agent local OpenAI-compatible model routing."""

import pytest
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.settings import ModelSettings

from neocortex.mcp_settings import MCPSettings
from neocortex.model_factory import LocalEndpoint, build_model, build_model_settings


@pytest.fixture
def endpoint() -> LocalEndpoint:
    return LocalEndpoint.from_settings(MCPSettings(local_model_base_url="http://local.example/v1"))


def test_local_model_uses_configured_endpoint(endpoint: LocalEndpoint) -> None:
    model = build_model("local:qwen3.8-27b", endpoint)
    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == "qwen3.8-27b"
    assert str(model._provider.base_url).rstrip("/") == "http://local.example/v1"


def test_hosted_model_keeps_string_routing(endpoint: LocalEndpoint) -> None:
    model = build_model("openai-responses:gpt-5.4-mini", endpoint)
    assert model == "openai-responses:gpt-5.4-mini"


def test_local_model_requires_base_url() -> None:
    with pytest.raises(ValueError, match="NEOCORTEX_LOCAL_MODEL_BASE_URL"):
        build_model("local:qwen3.8-27b", LocalEndpoint.from_settings(MCPSettings()))


def test_model_settings_preserve_hosted_and_none_behaviour(endpoint: LocalEndpoint) -> None:
    assert build_model_settings(None, "local:qwen", endpoint) is None
    hosted = build_model_settings("medium", "openai-responses:gpt-5.4-mini", endpoint)
    assert hosted == ModelSettings(thinking="medium")


def test_local_model_settings_include_sampling_and_timeout(endpoint: LocalEndpoint) -> None:
    settings = build_model_settings("xhigh", "local:qwen", endpoint)
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
    settings = build_model_settings(False, "local:qwen", nothink_endpoint)
    assert settings == ModelSettings(thinking=False, temperature=0.3, top_p=0.9, timeout=42.0)


def test_two_agents_can_use_different_providers(endpoint: LocalEndpoint) -> None:
    local = build_model("local:qwen", endpoint)
    hosted = build_model("openai-responses:gpt-5.4-mini", endpoint)
    assert isinstance(local, OpenAIChatModel)
    assert hosted == "openai-responses:gpt-5.4-mini"
