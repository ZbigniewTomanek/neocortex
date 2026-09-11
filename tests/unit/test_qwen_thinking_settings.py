"""Thinking-off and output-ceiling settings for Qwen models.

Stage 2 measured reasoning tokens on runs configured with ``thinking=False``.
The cause is in PydanticAI 1.72.0: ``openai_model_profile`` reports
``supports_thinking=False`` for an unrecognised model name, so
``Model.prepare_request`` drops the unified thinking setting and
``OpenAIChatModel`` omits ``reasoning_effort`` from the request — leaving the
server on its thinking default.  The same drop applies to every effort value,
not only ``False``: before the relay was made explicit, ``low``, ``medium`` and
``high`` reached the server as identical requests, which is why Plan 33's four
effort probes are statistically indistinguishable.  These tests pin the fix at
the settings level and at the PydanticAI boundary where the leak happened, for
``none`` and for each positive level.
"""

from __future__ import annotations

import pytest
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.settings import ModelSettings, ThinkingLevel

from neocortex.mcp_settings import MCPSettings
from neocortex.model_factory import (
    QWEN_MAX_OUTPUT_TOKENS,
    LocalEndpoint,
    build_model,
    build_model_settings,
)

QWEN = "local:qwen3.8-flash-next"
HOSTED = "openai-responses:gpt-5.4-mini"


@pytest.fixture
def endpoint() -> LocalEndpoint:
    return LocalEndpoint(
        base_url="http://127.0.0.1:24000/v1",
        api_key_env="LITELLM_API_KEY",
        temperature=0.6,
        top_p=0.95,
        temperature_nothink=0.3,
        top_p_nothink=0.9,
        timeout_s=600.0,
    )


@pytest.mark.parametrize(
    "field",
    [
        "ontology_thinking_effort",
        "extractor_thinking_effort",
        "librarian_thinking_effort",
        "domain_classifier_thinking_effort",
    ],
)
def test_thinking_effort_env_false_parses_to_false(monkeypatch: pytest.MonkeyPatch, field: str) -> None:
    """``NEOCORTEX_<AGENT>_THINKING_EFFORT=false`` reaches the agents as ``False``."""
    monkeypatch.setenv(f"NEOCORTEX_{field.upper()}", "false")
    settings = MCPSettings(_env_file=None)  # ty: ignore[unknown-argument]
    assert getattr(settings, field) is False


def test_max_token_settings_default_to_the_qwen_table() -> None:
    settings = MCPSettings(_env_file=None)  # ty: ignore[unknown-argument]
    assert settings.ontology_max_tokens == QWEN_MAX_OUTPUT_TOKENS["ontology"]
    assert settings.extractor_max_tokens == QWEN_MAX_OUTPUT_TOKENS["extractor"]
    assert settings.librarian_max_tokens == QWEN_MAX_OUTPUT_TOKENS["librarian"]
    assert settings.domain_classifier_max_tokens == QWEN_MAX_OUTPUT_TOKENS["domain_classifier"]


def test_max_token_settings_are_env_tunable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEOCORTEX_EXTRACTOR_MAX_TOKENS", "1234")
    settings = MCPSettings(_env_file=None)  # ty: ignore[unknown-argument]
    assert settings.extractor_max_tokens == 1234


def test_qwen_nothink_settings_carry_the_reasoning_switches(endpoint: LocalEndpoint) -> None:
    settings = build_model_settings(False, QWEN, endpoint, max_output_tokens=2500)
    assert settings == {
        "thinking": False,
        "temperature": 0.3,
        "top_p": 0.9,
        "timeout": 600.0,
        "max_tokens": 2500,
        "openai_reasoning_effort": "none",
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }


def test_qwen_thinking_on_carries_the_effort_and_thinking_sampling(endpoint: LocalEndpoint) -> None:
    """A positive level needs the same explicit relay as ``none``.

    The profile drops ``thinking`` for every value, so without
    ``openai_reasoning_effort`` the request carries no effort at all and
    ``low``/``medium``/``high`` are indistinguishable on the wire.
    """
    settings = build_model_settings("low", QWEN, endpoint, max_output_tokens=2500)
    assert settings is not None
    assert settings == {
        "thinking": "low",
        "temperature": 0.6,
        "top_p": 0.95,
        "timeout": 600.0,
        "max_tokens": 2500,
        "openai_reasoning_effort": "low",
    }
    # The nothink chat-template kwarg stays off the thinking-on path.
    assert "extra_body" not in settings


@pytest.mark.parametrize(("level", "expected"), [("low", "low"), ("medium", "medium"), ("high", "high")])
def test_each_qwen_thinking_level_reaches_the_request(
    endpoint: LocalEndpoint, monkeypatch: pytest.MonkeyPatch, level: ThinkingLevel, expected: str
) -> None:
    """The regression guard for the sweep: levels must differ at the PydanticAI boundary."""
    monkeypatch.setenv("LITELLM_API_KEY", "test-key")
    model = build_model(QWEN, endpoint)
    assert isinstance(model, Model)
    settings = build_model_settings(level, QWEN, endpoint)
    resolved_settings, params = model.prepare_request(settings, ModelRequestParameters())
    assert model._get_reasoning_effort(resolved_settings or {}, params) == expected  # ty: ignore[unresolved-attribute]
    # Sampling parameters stay on the thinking pair, not the nothink pair.
    assert (resolved_settings or {}).get("temperature") == 0.6


def test_hosted_settings_ignore_the_qwen_ceiling(endpoint: LocalEndpoint) -> None:
    assert build_model_settings("low", HOSTED, endpoint, max_output_tokens=100) == ModelSettings(thinking="low")
    assert build_model_settings(False, HOSTED, endpoint, max_output_tokens=100) == ModelSettings(thinking=False)


def test_local_non_qwen_settings_ignore_the_qwen_switches(endpoint: LocalEndpoint) -> None:
    settings = build_model_settings(False, "local:llama-3.3-70b", endpoint, max_output_tokens=100)
    assert settings == ModelSettings(thinking=False, temperature=0.3, top_p=0.9, timeout=600.0)


def test_reasoning_effort_none_reaches_the_request(endpoint: LocalEndpoint, monkeypatch: pytest.MonkeyPatch) -> None:
    """The regression guard: PydanticAI must resolve ``none``, not omit the field."""
    monkeypatch.setenv("LITELLM_API_KEY", "test-key")
    model = build_model(QWEN, endpoint)
    assert isinstance(model, Model)
    settings = build_model_settings(False, QWEN, endpoint)
    resolved_settings, params = model.prepare_request(settings, ModelRequestParameters())
    assert model._get_reasoning_effort(resolved_settings or {}, params) == "none"  # ty: ignore[unresolved-attribute]
    # Sampling parameters survive: the local server needs the nothink pair.
    assert (resolved_settings or {}).get("temperature") == 0.3
