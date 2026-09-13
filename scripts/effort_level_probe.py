#!/usr/bin/env python3
"""Measure the Qwen extractor's effective reasoning-effort levels.

The probe calls only the extractor agent, using the fixed E04 compact-corpus
episode.  Its durable output is counts and code-owned statuses only: source
text, prompts, model output, exception messages, and credentials are never
serialized.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import statistics
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pydantic_ai
from openai import APITimeoutError
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.settings import ThinkingLevel
from pydantic_ai.usage import UsageLimits

from neocortex.extraction.agents import (
    AgentInferenceConfig,
    ExtractorAgentDeps,
    build_extractor_agent,
)
from neocortex.extraction.schemas import ExtractionResult
from neocortex.mcp_settings import MCPSettings
from neocortex.model_factory import LocalEndpoint, build_model

try:  # Direct ``python scripts/effort_level_probe.py`` invocation.
    from corpus_loader import corpus_path, load_corpus  # ty: ignore[unresolved-import]
except ModuleNotFoundError:  # Imported as ``scripts.effort_level_probe``.
    from scripts.corpus_loader import corpus_path, load_corpus  # ty: ignore[unresolved-import]

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "local:qwen3.8-flash-next"
DEFAULT_BASE_URL = "http://127.0.0.1:24000/v1"
DEFAULT_API_KEY_ENV = "LITELLM_API_KEY"
LEVEL_ORDER = ("off", "low", "medium", "high")
THINKING: dict[str, ThinkingLevel] = {
    "off": False,
    "low": "low",
    "medium": "medium",
    "high": "high",
}
NODE_TYPES = ("SoftwareComponent", "Database", "Table", "Feature", "Person", "Organization")
EDGE_TYPES = ("USES", "CONTAINS", "HAS_FEATURE", "CORRECTS", "SUPERSEDES")
USER_PROMPT = "Extract entities and relations from the source text."
REASONING_MARKERS = ("<think>", "</think>")
SCHEMA_VERSION = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Measure Qwen extractor reasoning-effort identity.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--levels", default=",".join(LEVEL_ORDER))
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--per-call-timeout", type=float, default=300.0)
    parser.add_argument("--max-wall-seconds", type=float, default=1200.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--test-model", action="store_true")
    return parser


def parse_levels(value: str) -> list[str]:
    """Validate a comma-separated level selection and return canonical order."""
    requested = [item.strip() for item in value.split(",") if item.strip()]
    if not requested:
        raise ValueError("--levels must contain at least one level")
    unknown = sorted(set(requested) - set(LEVEL_ORDER))
    if unknown:
        raise ValueError(f"unknown levels: {', '.join(unknown)}")
    if len(requested) != len(set(requested)):
        raise ValueError("--levels must not contain duplicates")
    return [level for level in LEVEL_ORDER if level in requested]


def validate_limits(levels: Sequence[str], repeats: int, per_call_timeout: float, max_wall_seconds: float) -> None:
    if repeats < 1:
        raise ValueError("--repeats must be at least 1")
    if len(levels) * repeats > 12:
        raise ValueError("the probe is limited to twelve requests")
    if not 0 < per_call_timeout <= 300:
        raise ValueError("--per-call-timeout must be greater than zero and at most 300")
    if not 0 <= max_wall_seconds <= 1200:
        raise ValueError("--max-wall-seconds must be between zero and 1200")


def resolve_local_endpoint(timeout_s: float, *, test_model: bool) -> LocalEndpoint:
    """Resolve the probe endpoint without loading the repository ``.env`` file."""
    settings = MCPSettings(
        _env_file=None,  # ty: ignore[unknown-argument]
        local_model_base_url=os.environ.get("NEOCORTEX_LOCAL_MODEL_BASE_URL") or DEFAULT_BASE_URL,
        local_model_api_key_env=(
            "" if test_model else os.environ.get("NEOCORTEX_LOCAL_MODEL_API_KEY_ENV") or DEFAULT_API_KEY_ENV
        ),
        local_model_timeout_s=timeout_s,
    )
    return LocalEndpoint.from_settings(settings)


def boundary_settings(agent: Any, config: AgentInferenceConfig, *, test_model: bool) -> dict[str, bool | str | None]:
    """Read effective effort after PydanticAI's request preparation boundary.

    A TestModel agent deliberately has no OpenAI request boundary.  In that
    mode only, build the same local model with a credential-free placeholder
    endpoint and resolve the exact settings the live agent would receive.
    """
    model = build_model(config.model_name, config.local_endpoint) if test_model else agent.model
    if not isinstance(model, Model):
        raise TypeError("the extractor did not resolve to a PydanticAI Model")
    settings = config.model_settings
    resolved, params = model.prepare_request(settings, ModelRequestParameters())
    resolved = resolved or {}
    get_effort = getattr(model, "_get_reasoning_effort", None)
    if get_effort is None:
        raise TypeError("the resolved model has no OpenAI reasoning-effort boundary")
    extra_body = resolved.get("extra_body")
    extra_body_map = cast(dict[str, object], extra_body) if isinstance(extra_body, dict) else None
    chat_kwargs = extra_body_map.get("chat_template_kwargs") if extra_body_map is not None else None
    chat_kwargs_map = cast(dict[str, object], chat_kwargs) if isinstance(chat_kwargs, dict) else None
    enable_thinking = chat_kwargs_map.get("enable_thinking") if chat_kwargs_map is not None else None
    return {
        "thinking": resolved.get("thinking"),
        "enable_thinking": enable_thinking if isinstance(enable_thinking, bool) else None,
        "resolved_reasoning_effort": get_effort(resolved, params),
    }


def _safe_nonnegative_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def usage_counts(result: Any) -> dict[str, int | None]:
    """Extract required usage without turning absent values into zero."""
    usage = result.usage()
    details = getattr(usage, "details", None)
    details = details if isinstance(details, dict) else {}
    return {
        "reasoning_tokens": _safe_nonnegative_int(details.get("reasoning_tokens")),
        "output_tokens": _safe_nonnegative_int(getattr(usage, "output_tokens", None)),
    }


def _contains_marker(value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.lower()
        return any(marker in lowered for marker in REASONING_MARKERS)
    if isinstance(value, Mapping):
        return any(_contains_marker(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_marker(item) for item in value)
    return False


def reasoning_marker_detected(result: Any) -> bool:
    """Inspect response parts in memory and retain only a boolean finding."""
    for message in result.all_messages():
        if not isinstance(message, ModelResponse):
            continue
        for part in message.parts:
            for attribute in ("content", "args", "args_json"):
                if _contains_marker(getattr(part, attribute, None)):
                    return True
    return False


def are_aliases(left: Sequence[int], right: Sequence[int]) -> bool:
    """Apply the pre-committed median-difference and range-overlap rule."""
    if not left or not right:
        raise ValueError("alias comparison requires two non-empty samples")
    left_median = float(statistics.median(left))
    right_median = float(statistics.median(right))
    difference = abs(left_median - right_median)
    scale = max(abs(left_median), abs(right_median))
    close_medians = difference == 0 if scale == 0 else difference / scale < 0.20
    ranges_overlap = max(min(left), min(right)) <= min(max(left), max(right))
    return close_medians and ranges_overlap


def pairwise_alias_matrix(
    samples: Mapping[str, Sequence[int]], levels: Sequence[str]
) -> dict[str, dict[str, bool | None]]:
    """Return the full symmetric alias matrix; unavailable comparisons are null."""
    matrix: dict[str, dict[str, bool | None]] = {}
    for left in levels:
        matrix[left] = {}
        for right in levels:
            if left == right:
                matrix[left][right] = True
            elif "off" in (left, right):
                matrix[left][right] = False
            elif not samples.get(left) or not samples.get(right):
                matrix[left][right] = None
            else:
                matrix[left][right] = are_aliases(samples[left], samples[right])
    return matrix


def distinct_levels(samples: Mapping[str, Sequence[int]], levels: Sequence[str] = LEVEL_ORDER) -> list[str]:
    """Reduce pairwise aliases by walking levels in ascending canonical order.

    An unknown relation is retained conservatively: missing data can never
    remove a level from the later sweep.
    """
    ordered = [level for level in LEVEL_ORDER if level in levels]
    matrix = pairwise_alias_matrix(samples, ordered)
    kept: list[str] = ["off"] if "off" in ordered else []
    for level in (item for item in ordered if item != "off"):
        if all(matrix[level][previous] is not True for previous in kept):
            kept.append(level)
    return kept


def cancellation_decision(
    samples: Mapping[str, Sequence[int]], levels: Sequence[str], expected_repeats: int
) -> tuple[bool | None, str]:
    """Return whether effort is ignored, refusing to infer from missing rows."""
    if "off" not in levels or not any(level != "off" for level in levels):
        return None, "off_and_positive_levels_required"
    if any(len(samples.get(level, ())) != expected_repeats for level in levels):
        return None, "missing_measured_valid_rows"
    off_max = max(samples["off"])
    if all(float(statistics.median(samples[level])) <= off_max for level in levels if level != "off"):
        return True, "no_positive_median_exceeds_off_maximum"
    return False, "at_least_one_positive_median_exceeds_off_maximum"


def _pending_row(level: str, repeat: int, boundary: Mapping[str, Any] | None, reason: str) -> dict[str, Any]:
    return {
        "level": level,
        "repeat": repeat,
        "status": "NOT MEASURED",
        "reason": reason,
        "thinking": None if boundary is None else boundary["thinking"],
        "enable_thinking": None if boundary is None else boundary["enable_thinking"],
        "resolved_reasoning_effort": None if boundary is None else boundary["resolved_reasoning_effort"],
        "reasoning_tokens": None,
        "output_tokens": None,
        "elapsed_s": None,
        "valid_output": None,
        "timeout": False,
        "reasoning_marker_detected": None,
    }


def _usable_row(row: Mapping[str, Any]) -> bool:
    return (
        row.get("status") == "OK"
        and row.get("valid_output") is True
        and row.get("timeout") is False
        and row.get("reasoning_marker_detected") is False
        and _safe_nonnegative_int(row.get("reasoning_tokens")) is not None
        and (_safe_nonnegative_int(row.get("output_tokens")) or 0) > 0
    )


def analyze_rows(rows: Sequence[Mapping[str, Any]], levels: Sequence[str], repeats: int) -> dict[str, Any]:
    """Compute measured distributions without allowing partial rows to prove aliases."""
    samples: dict[str, list[int]] = {}
    summaries: dict[str, dict[str, Any]] = {}
    for level in levels:
        usable = [row for row in rows if row.get("level") == level and _usable_row(row)]
        values = [int(row["reasoning_tokens"]) for row in usable]
        complete_values = values if len(values) == repeats else []
        samples[level] = complete_values
        summaries[level] = {
            "measured_valid_rows": len(values),
            "expected_rows": repeats,
            "median_reasoning_tokens": float(statistics.median(values)) if values else None,
            "min_reasoning_tokens": min(values) if values else None,
            "max_reasoning_tokens": max(values) if values else None,
        }
    matrix = pairwise_alias_matrix(samples, levels)
    cancelled, cancellation_reason = cancellation_decision(samples, levels, repeats)
    kept = ["off"] if cancelled else distinct_levels(samples, levels)
    return {
        "levels": summaries,
        "pairwise_alias": matrix,
        "distinct_levels": kept,
        "cancellation_fired": cancelled,
        "cancellation_reason": cancellation_reason,
    }


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _write_markdown(path: Path, payload: Mapping[str, Any]) -> None:
    run = payload["run"]
    analysis = payload["analysis"]
    lines = [
        "# Qwen reasoning-effort identity probe",
        "",
        f"- Mode: {'TestModel instrumentation' if run['test_model'] else 'live endpoint'}",
        f"- Planned requests: {run['planned_requests']}",
        f"- Wall time: {run['wall_seconds']} s",
        f"- Budget exhausted: {str(run['budget_exhausted']).lower()}",
        f"- Cancellation: {analysis['cancellation_fired']} ({analysis['cancellation_reason']})",
        f"- Distinct levels: {', '.join(analysis['distinct_levels'])}",
        "",
        "| Level | Valid measured | Median reasoning | Range |",
        "|---|---:|---:|---:|",
    ]
    for level in run["levels"]:
        summary = analysis["levels"][level]
        minimum = summary["min_reasoning_tokens"]
        maximum = summary["max_reasoning_tokens"]
        range_text = "NOT MEASURED" if minimum is None else f"{minimum}-{maximum}"
        median = summary["median_reasoning_tokens"]
        lines.append(
            f"| {level} | {summary['measured_valid_rows']}/{summary['expected_rows']} | "
            f"{'NOT MEASURED' if median is None else median} | {range_text} |"
        )
    lines.extend(["", "## Pairwise aliases", ""])
    lines.append("| | " + " | ".join(run["levels"]) + " |")
    lines.append("|---|" + "---:|" * len(run["levels"]))
    for left in run["levels"]:
        values = [analysis["pairwise_alias"][left][right] for right in run["levels"]]
        lines.append("| " + left + " | " + " | ".join(str(value) for value in values) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _refresh_payload(payload: dict[str, Any], started: float, *, finalized: bool) -> None:
    run = payload["run"]
    run["wall_seconds"] = round(time.monotonic() - started, 3)
    run["finalized"] = finalized
    if finalized:
        run["finished_at"] = datetime.now(UTC).isoformat()
    payload["analysis"] = analyze_rows(payload["rows"], run["levels"], run["repeats"])


async def _run_one(agent: Any, config: AgentInferenceConfig, text: str, timeout_s: float) -> Any:
    return await asyncio.wait_for(
        agent.run(
            USER_PROMPT,
            deps=ExtractorAgentDeps(
                episode_text=text,
                node_types=list(NODE_TYPES),
                edge_types=list(EDGE_TYPES),
                agent_id="effort_level_probe",
            ),
            model_settings=config.model_settings,
            # A structured-output retry is another provider request.  The
            # identity probe budgets requests, not logical rows, so forbid it.
            usage_limits=UsageLimits(request_limit=1),
        ),
        timeout=timeout_s,
    )


async def run_probe(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    levels = parse_levels(args.levels)
    validate_limits(levels, args.repeats, args.per_call_timeout, args.max_wall_seconds)
    corpus_file = corpus_path("compact")
    episode = next(item for item in load_corpus(profile="compact") if item["number"] == 4)
    source_text = str(episode["text"])
    endpoint = resolve_local_endpoint(args.per_call_timeout, test_model=args.test_model)
    started = time.monotonic()
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run": {
            "model": "test-model" if args.test_model else args.model,
            "configured_model": args.model,
            "test_model": args.test_model,
            "episode": "E04",
            "compact_corpus_path": corpus_file.relative_to(ROOT).as_posix(),
            "compact_corpus_sha256": hashlib.sha256(corpus_file.read_bytes()).hexdigest(),
            "pydantic_ai_version": pydantic_ai.__version__,
            "levels": levels,
            "repeats": args.repeats,
            "planned_requests": len(levels) * args.repeats,
            "per_call_timeout_s": args.per_call_timeout,
            "max_wall_seconds": args.max_wall_seconds,
            "started_at": datetime.now(UTC).isoformat(),
            "finished_at": None,
            "wall_seconds": 0.0,
            "budget_exhausted": False,
            "finalized": False,
        },
        "rows": [],
        "analysis": {},
    }
    agents: dict[str, tuple[Any, AgentInferenceConfig]] = {}
    boundaries: dict[str, dict[str, Any] | None] = {}
    for level in levels:
        config = AgentInferenceConfig(
            model_name=args.model,
            thinking_effort=THINKING[level],
            use_test_model=args.test_model,
            local_endpoint=endpoint,
        )
        try:
            agent = build_extractor_agent(config)
            boundaries[level] = boundary_settings(agent, config, test_model=args.test_model)
            agents[level] = (agent, config)
        except Exception:
            # Exception text can contain a URL or credential.  The class is
            # sufficient to diagnose construction without persisting it.
            boundaries[level] = None

    for level in levels:
        reason = "pending" if level in agents else "boundary_resolution_error"
        for repeat in range(1, args.repeats + 1):
            payload["rows"].append(_pending_row(level, repeat, boundaries[level], reason))
    _refresh_payload(payload, started, finalized=False)
    _atomic_write_json(args.output, payload)

    try:
        for index, row in enumerate(payload["rows"]):
            elapsed = time.monotonic() - started
            remaining = args.max_wall_seconds - elapsed
            if remaining <= 0:
                payload["run"]["budget_exhausted"] = True
                for pending in payload["rows"][index:]:
                    if pending["reason"] == "pending":
                        pending["reason"] = "wall_budget_before_launch"
                break
            level = row["level"]
            if level not in agents:
                continue
            agent, config = agents[level]
            request_started = time.monotonic()
            try:
                result = await _run_one(agent, config, source_text, min(args.per_call_timeout, remaining))
            except (TimeoutError, APITimeoutError):
                row.update(
                    status="TIMEOUT",
                    reason="per_call_or_wall_timeout",
                    elapsed_s=round(time.monotonic() - request_started, 3),
                    timeout=True,
                )
            except Exception as exc:
                row.update(
                    status="ERROR",
                    reason="model_request_error",
                    error_class=type(exc).__name__,
                    elapsed_s=round(time.monotonic() - request_started, 3),
                )
            else:
                counts = usage_counts(result)
                valid_output = isinstance(result.output, ExtractionResult)
                marker = reasoning_marker_detected(result)
                missing = [name for name, value in counts.items() if value is None]
                row.update(
                    status="NOT MEASURED" if missing else "OK",
                    reason="missing_usage:" + ",".join(missing) if missing else None,
                    elapsed_s=round(time.monotonic() - request_started, 3),
                    valid_output=valid_output,
                    reasoning_marker_detected=marker,
                    **counts,
                )
            _refresh_payload(payload, started, finalized=False)
            _atomic_write_json(args.output, payload)
    finally:
        _refresh_payload(payload, started, finalized=True)
        _atomic_write_json(args.output, payload)
        _write_markdown(args.output.with_suffix(".md"), payload)

    complete = len(payload["rows"]) == payload["run"]["planned_requests"]
    if args.test_model:
        expected_efforts = {"off": "none", "low": "low", "medium": "medium", "high": "high"}
        harness_valid = complete and all(
            row["resolved_reasoning_effort"] == expected_efforts[row["level"]]
            and row["valid_output"] is True
            and row["timeout"] is False
            and row["status"] not in {"ERROR", "TIMEOUT"}
            for row in payload["rows"]
        )
        return (0 if harness_valid else 1), payload
    statuses = {row["status"] for row in payload["rows"]}
    return (0 if complete and statuses == {"OK"} else 1), payload


async def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        exit_code, payload = await run_probe(args)
    except ValueError as exc:
        parser.error(str(exc))
    measured = sum(row["status"] == "OK" for row in payload["rows"])
    print(
        f"effort probe: {len(payload['rows'])}/{payload['run']['planned_requests']} rows, "
        f"{measured} fully measured; JSON={args.output}; Markdown={args.output.with_suffix('.md')}"
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
