"""Offline checks for the isolated Qwen reasoning-effort probe."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import APITimeoutError
from pydantic_ai.messages import ModelResponse, TextPart
from scripts import effort_level_probe as probe  # ty: ignore[unresolved-import]

from neocortex.extraction.agents import AgentInferenceConfig, build_extractor_agent


def _row(
    level: str,
    repeat: int,
    reasoning_tokens: int | None,
    *,
    output_tokens: int | None = 10,
    status: str = "OK",
    valid_output: bool | None = True,
    marker: bool | None = False,
) -> dict[str, Any]:
    return {
        "level": level,
        "repeat": repeat,
        "status": status,
        "reasoning_tokens": reasoning_tokens,
        "output_tokens": output_tokens,
        "valid_output": valid_output,
        "timeout": status == "TIMEOUT",
        "reasoning_marker_detected": marker,
    }


def _args(output: Path, **overrides: Any) -> argparse.Namespace:
    values = {
        "model": probe.DEFAULT_MODEL,
        "levels": "off,low,medium,high",
        "repeats": 3,
        "per_call_timeout": 300.0,
        "max_wall_seconds": 1200.0,
        "output": output,
        "test_model": True,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_identical_distributions_are_aliases() -> None:
    assert probe.are_aliases([100, 120, 140], [100, 120, 140]) is True


def test_zero_and_eight_hundred_are_distinct() -> None:
    assert probe.are_aliases([0, 0, 0], [800, 800, 800]) is False


def test_non_transitive_aliases_reduce_in_ascending_order() -> None:
    # low~medium and medium~high, while low and high are distinct.  Ascending
    # greedy reduction therefore keeps low and high.
    samples = {
        "off": [0, 0, 0],
        "low": [90, 100, 110],
        "medium": [105, 115, 125],
        "high": [120, 130, 140],
    }
    matrix = probe.pairwise_alias_matrix(samples, probe.LEVEL_ORDER)
    assert matrix["low"]["medium"] is True
    assert matrix["medium"]["high"] is True
    assert matrix["low"]["high"] is False
    assert probe.distinct_levels(samples) == ["off", "low", "high"]


def test_cancellation_fires_only_from_complete_valid_measurements() -> None:
    samples = {
        "off": [8, 9, 10],
        "low": [7, 8, 9],
        "medium": [8, 9, 10],
        "high": [6, 7, 8],
    }
    assert probe.cancellation_decision(samples, probe.LEVEL_ORDER, 3) == (
        True,
        "no_positive_median_exceeds_off_maximum",
    )


def test_missing_usage_cannot_prove_alias_or_cancellation() -> None:
    rows = [_row(level, repeat, 0 if level == "off" else 1) for level in probe.LEVEL_ORDER for repeat in range(1, 4)]
    rows[-1] = _row("high", 3, None, status="NOT MEASURED")
    analysis = probe.analyze_rows(rows, probe.LEVEL_ORDER, 3)
    assert analysis["cancellation_fired"] is None
    assert analysis["cancellation_reason"] == "missing_measured_valid_rows"
    assert analysis["pairwise_alias"]["medium"]["high"] is None
    assert "high" in analysis["distinct_levels"]


def test_empty_output_and_reasoning_marker_cannot_trigger_cancellation() -> None:
    rows = [_row(level, repeat, 0) for level in probe.LEVEL_ORDER for repeat in range(1, 4)]
    rows[0] = _row("off", 1, 0, output_tokens=0)
    rows[4] = _row("low", 2, 0, marker=True)
    analysis = probe.analyze_rows(rows, probe.LEVEL_ORDER, 3)
    assert analysis["cancellation_fired"] is None
    assert analysis["levels"]["off"]["measured_valid_rows"] == 2
    assert analysis["levels"]["low"]["measured_valid_rows"] == 2


@pytest.mark.parametrize(
    ("level", "thinking", "expected_effort", "expected_template"),
    [
        ("off", False, "none", False),
        ("low", "low", "low", None),
        ("medium", "medium", "medium", None),
        ("high", "high", "high", None),
    ],
)
def test_every_effort_resolves_at_the_real_pydanticai_boundary(
    level: str,
    thinking: Any,
    expected_effort: str,
    expected_template: bool | None,
) -> None:
    endpoint = probe.resolve_local_endpoint(300.0, test_model=True)
    config = AgentInferenceConfig(
        model_name=probe.DEFAULT_MODEL,
        thinking_effort=probe.THINKING[level],
        use_test_model=True,
        local_endpoint=endpoint,
    )
    agent = build_extractor_agent(config)
    resolved = probe.boundary_settings(agent, config, test_model=True)
    assert resolved == {
        "thinking": thinking,
        "enable_thinking": expected_template,
        "resolved_reasoning_effort": expected_effort,
    }


def test_absent_reasoning_usage_stays_missing_instead_of_zero() -> None:
    result = SimpleNamespace(usage=lambda: SimpleNamespace(output_tokens=21))
    assert probe.usage_counts(result) == {"reasoning_tokens": None, "output_tokens": 21}


def test_response_marker_is_reduced_to_a_boolean() -> None:
    result = SimpleNamespace(
        all_messages=lambda: [ModelResponse(parts=[TextPart(content="<think>hidden chain</think>")])]
    )
    assert probe.reasoning_marker_detected(result) is True


@pytest.mark.asyncio
async def test_test_model_cli_writes_twelve_rows_and_real_boundary_settings(tmp_path: Path) -> None:
    output = tmp_path / "effort.json"
    exit_code = await probe.main(
        [
            "--test-model",
            "--levels",
            "off,low,medium,high",
            "--repeats",
            "3",
            "--per-call-timeout",
            "300",
            "--max-wall-seconds",
            "1200",
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert len(payload["rows"]) == payload["run"]["planned_requests"] == 12
    assert payload["run"]["finalized"] is True
    assert output.with_suffix(".md").is_file()
    for level, expected in zip(probe.LEVEL_ORDER, ("none", "low", "medium", "high"), strict=True):
        level_rows = [row for row in payload["rows"] if row["level"] == level]
        assert len(level_rows) == 3
        assert {row["resolved_reasoning_effort"] for row in level_rows} == {expected}
        assert all(row["valid_output"] is True for row in level_rows)
        # TestModel has no reasoning usage detail.  The harness must exercise
        # the omission path without manufacturing a zero-token PASS.
        assert all(row["status"] == "NOT MEASURED" for row in level_rows)
        assert all(row["reasoning_tokens"] is None for row in level_rows)
    off_rows = [row for row in payload["rows"] if row["level"] == "off"]
    assert {row["thinking"] for row in off_rows} == {False}
    assert {row["enable_thinking"] for row in off_rows} == {False}
    assert payload["analysis"]["cancellation_fired"] is None


@pytest.mark.asyncio
async def test_zero_wall_budget_records_every_unlaunched_request(tmp_path: Path) -> None:
    output = tmp_path / "budget.json"
    exit_code, payload = await probe.run_probe(_args(output, max_wall_seconds=0.0))
    assert exit_code == 1
    assert len(payload["rows"]) == 12
    assert payload["run"]["budget_exhausted"] is True
    assert all(row["status"] == "NOT MEASURED" for row in payload["rows"])
    assert all(row["reason"] == "wall_budget_before_launch" for row in payload["rows"])
    assert payload["analysis"]["cancellation_fired"] is None


@pytest.mark.asyncio
async def test_one_logical_row_allows_only_one_provider_request() -> None:
    sentinel = object()
    seen: dict[str, Any] = {}

    class FakeAgent:
        async def run(self, *_args: Any, **kwargs: Any) -> object:
            seen.update(kwargs)
            return sentinel

    config = SimpleNamespace(model_settings={})
    result = await probe._run_one(FakeAgent(), config, "fixed source", 1.0)
    assert result is sentinel
    assert seen["usage_limits"].request_limit == 1


@pytest.mark.asyncio
async def test_test_model_exit_fails_when_boundaries_do_not_resolve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_boundary(*_args: Any, **_kwargs: Any) -> Any:
        raise TypeError("missing boundary")

    monkeypatch.setattr(probe, "boundary_settings", fail_boundary)
    output = tmp_path / "bad-boundary.json"
    exit_code, payload = await probe.run_probe(_args(output, levels="off", repeats=1))
    assert exit_code == 1
    assert payload["rows"][0]["status"] == "NOT MEASURED"
    assert payload["rows"][0]["reason"] == "boundary_resolution_error"


@pytest.mark.asyncio
async def test_timeout_is_not_retried_and_does_not_serialize_exception_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    async def timeout_once(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise TimeoutError("secret model output")

    monkeypatch.setattr(probe, "_run_one", timeout_once)
    output = tmp_path / "timeout.json"
    _exit_code, payload = await probe.run_probe(_args(output, levels="off", repeats=1))
    assert calls == 1
    assert payload["rows"][0]["status"] == "TIMEOUT"
    assert payload["rows"][0]["timeout"] is True
    assert "secret model output" not in output.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_provider_timeout_is_recorded_as_timeout_without_exception_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    async def provider_timeout(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        request = httpx.Request("POST", "https://secret.example/provider-token")
        raise APITimeoutError(request=request)

    monkeypatch.setattr(probe, "_run_one", provider_timeout)
    output = tmp_path / "provider-timeout.json"
    _exit_code, payload = await probe.run_probe(_args(output, levels="off", repeats=1))

    assert calls == 1
    assert payload["rows"][0]["status"] == "TIMEOUT"
    assert payload["rows"][0]["timeout"] is True
    assert "secret.example" not in output.read_text(encoding="utf-8")


def test_limits_enforce_twelve_calls_and_live_budgets() -> None:
    with pytest.raises(ValueError, match="twelve"):
        probe.validate_limits(probe.LEVEL_ORDER, 4, 300, 1200)
    with pytest.raises(ValueError, match="at most 300"):
        probe.validate_limits(probe.LEVEL_ORDER, 3, 301, 1200)
    with pytest.raises(ValueError, match="between zero and 1200"):
        probe.validate_limits(probe.LEVEL_ORDER, 3, 300, 1201)
