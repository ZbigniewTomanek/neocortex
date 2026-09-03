"""Unit coverage for per-agent local OpenAI-compatible model routing."""

import pytest
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.settings import ModelSettings

from neocortex.mcp_settings import MCPSettings
from neocortex.model_factory import LocalEndpoint, build_model, build_model_settings


@pytest.fixture
def endpoint() -> LocalEndpoint:
    # Keep routing tests independent of a developer's local .env file. The
    # live preflight supplies explicit environment overrides instead.
    return LocalEndpoint.from_settings(
        MCPSettings(local_model_base_url="http://local.example/v1", _env_file=None)  # ty: ignore[unknown-argument]
    )


def test_local_model_uses_configured_endpoint(endpoint: LocalEndpoint) -> None:
    model = build_model("local:qwen3.8-flash-next", endpoint)
    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == "qwen3.8-flash-next"
    assert str(model._provider.base_url).rstrip("/") == "http://local.example/v1"


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


def test_local_model_uses_empty_key_when_configured_environment_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TEST_VLLM_API_KEY", raising=False)
    settings = MCPSettings(
        local_model_base_url="http://local.example/v1",
        local_model_api_key_env="TEST_VLLM_API_KEY",
        _env_file=None,  # ty: ignore[unknown-argument]
    )

    model = build_model("local:qwen3.8-flash-next", LocalEndpoint.from_settings(settings))

    assert isinstance(model, OpenAIChatModel)
    assert model._provider.client.api_key == ""


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
