#!/usr/bin/env python3
"""Bounded, incremental runner for Plan 34's per-agent effort sweep."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
PLAN_DIR = Path(__file__).resolve().parents[1]
PROBE = ROOT / "scripts/qwen_speed_probe.py"
FIXTURE = PLAN_DIR / "resources/fact-fixture.json"
LEVELS = ("off", "low", "medium", "high")
AGENTS = ("extractor", "librarian", "ontology", "classifier")
COMPACT_UNITS = ("E02", "E04", "E05", "E10", "E18", "E20", "E26", "E27")
TRIPLET_UNITS = ("S05", "S11", "S07")
TRIPLET_LABELS = tuple(f"{unit}-{part}" for unit in TRIPLET_UNITS for part in (1, 2))
ALL_SOURCE_LABELS = (*COMPACT_UNITS, *TRIPLET_LABELS)
MAX_STAGE_WALL_SECONDS = 14_400.0
MAX_CELL_WALL_SECONDS = 3_600.0
PER_CALL_TIMEOUT_SECONDS = 300.0
EPISODE_TIMEOUT_SECONDS = 600.0
_DOMAIN_KEY = re.compile(
    r"^(?:known:(?:user_profile|technical_knowledge|work_context|domain_knowledge)|proposed:sha256:[0-9a-f]{64})$"
)


@dataclass(frozen=True)
class CellSpec:
    """One agent/level cell with all upstream levels resolved."""

    agent: str
    level: str
    corpus: str
    stage: str
    classify: bool
    levels: Mapping[str, str]
    cache_thinking: str | None = None

    @property
    def expected_units(self) -> tuple[str, ...]:
        return COMPACT_UNITS if self.corpus == "compact" else (*COMPACT_UNITS, *TRIPLET_UNITS)

    @property
    def expected_source_labels(self) -> tuple[str, ...]:
        return COMPACT_UNITS if self.corpus == "compact" else ALL_SOURCE_LABELS


@dataclass(frozen=True)
class ChildResult:
    """Bounded subprocess outcome; stdout is stored only at ``log_path``."""

    status: str
    returncode: int | None
    wall_seconds: float
    log_path: Path


Launcher = Callable[[Sequence[str], Mapping[str, str], Path, float], ChildResult]


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON object {path}: {type(exc).__name__}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    for base in (PLAN_DIR, ROOT):
        try:
            return resolved.relative_to(base).as_posix()
        except ValueError:
            continue
    return resolved.as_posix()


def levels_from_identity(identity: Mapping[str, Any]) -> tuple[str, ...]:
    """Return supported distinct levels without inventing a Stage 5 result."""
    run = identity.get("run")
    analysis = identity.get("analysis")
    if not isinstance(run, Mapping) or run.get("finalized") is not True or not isinstance(analysis, Mapping):
        raise ValueError("identity evidence is not finalized")
    distinct = analysis.get("distinct_levels")
    if not isinstance(distinct, list) or not distinct:
        raise ValueError("identity evidence has no distinct_levels")
    unknown = [level for level in distinct if level not in LEVELS]
    if unknown:
        raise ValueError("identity evidence contains unsupported levels")
    return tuple(level for level in LEVELS if level in distinct)


def make_spec(agent: str, level: str, selected: Mapping[str, str]) -> CellSpec:
    """Build one fully pinned probe cell."""
    if agent not in AGENTS or level not in LEVELS:
        raise ValueError("unsupported agent or effort level")
    levels = {
        "ontology": "off",
        "extractor": "off",
        "librarian": "off",
        "classifier": "off",
    }
    if agent == "extractor":
        levels["extractor"] = level
        return CellSpec(agent, level, "both", "all", False, levels)
    if agent == "librarian":
        levels["extractor"] = selected.get("extractor", "off")
        levels["librarian"] = level
        return CellSpec(agent, level, "both", "librarian", False, levels, cache_thinking="off")
    if agent == "ontology":
        levels["ontology"] = level
        levels["extractor"] = selected.get("extractor", "off")
        levels["librarian"] = selected.get("librarian", "off")
        return CellSpec(agent, level, "compact", "all", False, levels)
    levels["ontology"] = selected.get("ontology", "off")
    levels["extractor"] = selected.get("extractor", "off")
    levels["librarian"] = selected.get("librarian", "off")
    levels["classifier"] = level
    return CellSpec(agent, level, "compact", "all", True, levels)


def probe_command(
    spec: CellSpec,
    raw_path: Path,
    cache_dir: Path,
    model: str,
    remaining_seconds: float,
    *,
    test_model: bool,
) -> list[str]:
    """Return an explicit, shell-free probe command for one cell."""
    cell_wall = max(0.001, min(MAX_CELL_WALL_SECONDS, remaining_seconds))
    command = [
        sys.executable,
        str(PROBE),
        "--model",
        model,
        "--corpus",
        spec.corpus,
        "--fixture",
        str(FIXTURE),
        "--thinking",
        "off",
        "--thinking-ontology",
        spec.levels["ontology"],
        "--thinking-extractor",
        spec.levels["extractor"],
        "--thinking-librarian",
        spec.levels["librarian"],
        "--thinking-classifier",
        spec.levels["classifier"],
        "--per-call-timeout",
        str(PER_CALL_TIMEOUT_SECONDS),
        "--episode-timeout",
        str(EPISODE_TIMEOUT_SECONDS),
        "--max-wall-seconds",
        f"{cell_wall:.6f}",
        "--cache-dir",
        str(cache_dir),
        "--output",
        str(raw_path),
    ]
    if spec.stage == "librarian":
        command.extend(["--stage", "librarian", "--cache-thinking", str(spec.cache_thinking)])
    if spec.classify:
        command.append("--classify")
    if test_model:
        command.append("--test-model")
    return command


def child_environment() -> dict[str, str]:
    """Keep the local credential by reference while removing hosted-model keys."""
    env = dict(os.environ)
    env.pop("GOOGLE_API_KEY", None)
    env.pop("GEMINI_API_KEY", None)
    env["NEOCORTEX_LOCAL_MODEL_BASE_URL"] = "http://127.0.0.1:24000/v1"
    return env


def run_child(command: Sequence[str], env: Mapping[str, str], log_path: Path, timeout: float) -> ChildResult:
    """Run and bound exactly one child, retaining its combined output privately."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    process = subprocess.Popen(
        list(command),
        cwd=ROOT,
        env=dict(env),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    status = "EXITED"
    try:
        stdout, _ = process.communicate(timeout=max(0.001, timeout))
    except subprocess.TimeoutExpired:
        status = "TIMEOUT"
        process.terminate()
        try:
            stdout, _ = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, _ = process.communicate()
    log_path.write_text(stdout, encoding="utf-8")
    return ChildResult(status, process.returncode, round(time.monotonic() - started, 3), log_path)


def _nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 3)


def _unmeasured_cell(spec: CellSpec, reason: str, raw_path: Path | None = None) -> dict[str, Any]:
    return {
        "agent": spec.agent,
        "level": spec.level,
        "configuration": dict(spec.levels),
        "cache_thinking": spec.cache_thinking,
        "raw_path": _display_path(raw_path) if raw_path is not None else None,
        "episodes": None,
        "source_text_rows": None,
        "triplet_passes": None,
        "facts_found": None,
        "facts_total": None,
        "tier": None,
        "selected": False,
        "timeouts": None,
        "critical_defects": None,
        "median_reasoning_tokens": None,
        "p50_s": None,
        "p95_s": None,
        "wall_seconds": None,
        "valid_results": None,
        "domain_sets": None,
        "accepted_node_proposals": None,
        "accepted_edge_proposals": None,
        "rejected_node_proposals": None,
        "rejected_edge_proposals": None,
        "proposal_rejection_reasons": None,
        "status": "NOT MEASURED",
        "reason": reason,
    }


def _raw_config_matches(
    spec: CellSpec,
    run: Mapping[str, Any],
    *,
    test_model: bool,
    expected_model: str | None,
    expected_corpus_sha256: str | None,
) -> bool:
    if run.get("corpus") != spec.corpus or run.get("stage") != spec.stage:
        return False
    if test_model != (run.get("model") == "test-model"):
        return False
    if not test_model and expected_model is not None and run.get("model") != expected_model:
        return False
    if expected_corpus_sha256 is not None and run.get("corpus_sha256") != expected_corpus_sha256:
        return False
    if spec.cache_thinking is not None and run.get("cache_thinking") != spec.cache_thinking:
        return False
    return all(run.get(f"thinking_{agent}") == level for agent, level in spec.levels.items())


def analyse_raw(
    spec: CellSpec,
    raw_path: Path,
    *,
    test_model: bool,
    expected_model: str | None = None,
    expected_corpus_sha256: str | None = None,
) -> dict[str, Any]:
    """Recompute a cell from raw probe rows; absence never becomes zero."""
    try:
        raw = _load_object(raw_path)
    except ValueError as exc:
        return _unmeasured_cell(spec, str(exc), raw_path)
    run = raw.get("run")
    summaries = raw.get("episodes")
    rows = raw.get("stages")
    if not isinstance(run, Mapping) or not isinstance(summaries, list) or not isinstance(rows, list):
        return _unmeasured_cell(spec, "malformed_raw_shape", raw_path)
    if not _raw_config_matches(
        spec,
        run,
        test_model=test_model,
        expected_model=expected_model,
        expected_corpus_sha256=expected_corpus_sha256,
    ):
        return _unmeasured_cell(spec, "raw_configuration_mismatch", raw_path)
    if [summary.get("episode") for summary in summaries if isinstance(summary, Mapping)] != list(spec.expected_units):
        return _unmeasured_cell(spec, "summary_row_mismatch", raw_path)
    if not all(
        isinstance(summary, Mapping) and isinstance(summary.get("critical_defects"), list) for summary in summaries
    ):
        return _unmeasured_cell(spec, "missing_defect_observation", raw_path)
    if any(not isinstance(row, Mapping) or row.get("episode") not in spec.expected_source_labels for row in rows):
        return _unmeasured_cell(spec, "raw_stage_label_mismatch", raw_path)
    if any(not isinstance(row.get("status"), str) or not row.get("status") for row in rows):
        return _unmeasured_cell(spec, "missing_stage_status", raw_path)

    target_rows = [row for row in rows if isinstance(row, Mapping) and row.get("stage") == spec.agent]
    if [row.get("episode") for row in target_rows] != list(spec.expected_source_labels):
        return _unmeasured_cell(spec, "target_stage_row_mismatch", raw_path)

    compact = summaries[: len(COMPACT_UNITS)]
    fact_scores = [summary.get("fact_score") for summary in compact]
    if not all(
        isinstance(score, Mapping)
        and isinstance(score.get("facts_found"), int)
        and isinstance(score.get("facts_total"), int)
        for score in fact_scores
    ):
        return _unmeasured_cell(spec, "missing_fact_score", raw_path)
    facts_found = sum(int(score["facts_found"]) for score in fact_scores if isinstance(score, Mapping))
    facts_total = sum(int(score["facts_total"]) for score in fact_scores if isinstance(score, Mapping))

    triplet_passes: int | None = None
    if spec.corpus == "both":
        supersession = [summary.get("supersession") for summary in summaries[len(COMPACT_UNITS) :]]
        if not all(isinstance(score, Mapping) for score in supersession):
            return _unmeasured_cell(spec, "missing_supersession_score", raw_path)
        triplet_passes = sum(
            bool(score.get("new_present")) and bool(score.get("old_absent"))
            for score in supersession
            if isinstance(score, Mapping)
        )

    defects = sorted(
        {
            str(defect)
            for summary in summaries
            if isinstance(summary, Mapping)
            for defect in summary.get("critical_defects", [])
        }
    )
    timeout_labels = {
        str(row.get("episode"))
        for row in rows
        if isinstance(row, Mapping) and str(row.get("status", "")).lower() == "timeout"
    }
    seconds = [float(row["seconds"]) for row in target_rows if isinstance(row.get("seconds"), int | float)]
    reasoning = [
        float(row["reasoning_tokens"]) for row in target_rows if isinstance(row.get("reasoning_tokens"), int | float)
    ]
    median_reasoning = round(statistics.median(reasoning), 3) if len(reasoning) == len(target_rows) else None

    valid_results: int | None = None
    domain_sets: dict[str, list[str]] | None = None
    if spec.agent == "classifier":
        if not all("valid_result" in row and "domain_keys" in row for row in target_rows):
            return _unmeasured_cell(spec, "missing_classifier_observation", raw_path)
        valid_results = sum(
            row.get("valid_result") is True and isinstance(row.get("domain_keys"), list) for row in target_rows
        )
        if valid_results == len(target_rows):
            if not all(
                all(isinstance(key, str) and _DOMAIN_KEY.fullmatch(key) for key in row["domain_keys"])
                and row["domain_keys"] == sorted(set(row["domain_keys"]))
                for row in target_rows
            ):
                return _unmeasured_cell(spec, "unsafe_classifier_domain_keys", raw_path)
            domain_sets = {str(row["episode"]): list(row["domain_keys"]) for row in target_rows}

    proposal_totals: dict[str, Any] = {
        "accepted_node_proposals": None,
        "accepted_edge_proposals": None,
        "rejected_node_proposals": None,
        "rejected_edge_proposals": None,
        "proposal_rejection_reasons": None,
    }
    if spec.agent == "ontology":
        proposal_fields = (
            "accepted_node_proposals",
            "accepted_edge_proposals",
            "rejected_node_proposals",
            "rejected_edge_proposals",
        )
        if not all(all(isinstance(row.get(field), int) for field in proposal_fields) for row in target_rows):
            return _unmeasured_cell(spec, "missing_ontology_proposal_observation", raw_path)
        for field in proposal_fields:
            proposal_totals[field] = sum(int(row[field]) for row in target_rows)
        reasons: dict[str, int] = {}
        for row in target_rows:
            row_reasons = row.get("proposal_rejection_reasons")
            if not isinstance(row_reasons, Mapping):
                return _unmeasured_cell(spec, "missing_ontology_rejection_reasons", raw_path)
            for reason, count in row_reasons.items():
                if not isinstance(count, int):
                    return _unmeasured_cell(spec, "invalid_ontology_rejection_count", raw_path)
                reasons[str(reason)] = reasons.get(str(reason), 0) + count
        proposal_totals["proposal_rejection_reasons"] = reasons

    eligible = not defects and len(timeout_labels) <= 1
    if spec.agent == "classifier":
        eligible = eligible and valid_results == len(COMPACT_UNITS)
    status = "PASS" if eligible else "DISQUALIFIED"
    tier = (
        f"valid:{valid_results}/{len(COMPACT_UNITS)}"
        if spec.agent == "classifier"
        else "compact" if spec.agent == "ontology" else f"triplet:{triplet_passes}"
    )
    return {
        "agent": spec.agent,
        "level": spec.level,
        "configuration": dict(spec.levels),
        "cache_thinking": spec.cache_thinking,
        "raw_path": _display_path(raw_path),
        "episodes": len(summaries),
        "source_text_rows": len(target_rows),
        "triplet_passes": triplet_passes,
        "facts_found": facts_found,
        "facts_total": facts_total,
        "tier": tier,
        "selected": False,
        "timeouts": len(timeout_labels),
        "critical_defects": defects,
        "median_reasoning_tokens": median_reasoning,
        "p50_s": _nearest_rank(seconds, 0.5) if len(seconds) == len(target_rows) else None,
        "p95_s": _nearest_rank(seconds, 0.95) if len(seconds) == len(target_rows) else None,
        "wall_seconds": float(run["wall_seconds"]) if isinstance(run.get("wall_seconds"), int | float) else None,
        "valid_results": valid_results,
        "domain_sets": domain_sets,
        **proposal_totals,
        "status": status,
        "reason": None if eligible else "selection_gate_failed",
    }


def select_agent(agent: str, cells: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply the pre-committed rule and mutate exactly one cell as selected."""
    own = [cell for cell in cells if cell["agent"] == agent]
    eligible = [cell for cell in own if cell["status"] == "PASS"]
    if not eligible:
        fallback = next(cell for cell in own if cell["level"] == "off")
        fallback["selected"] = True
        return {
            "level": "off",
            "status": "NOT MEASURED",
            "reason": "no_eligible_measured_level",
            "highest_triplet_tier": None,
            "best_facts_in_tier": None,
            "two_fact_floor": None,
            "candidates": [],
        }

    if agent == "classifier":
        winner = min(eligible, key=lambda cell: LEVELS.index(str(cell["level"])))
        arithmetic = {
            "highest_triplet_tier": None,
            "best_facts_in_tier": None,
            "two_fact_floor": None,
            "candidates": [cell["level"] for cell in eligible],
        }
    else:
        if agent == "ontology":
            tier_cells = eligible
            highest_tier: int | None = None
        else:
            highest_tier = max(int(cell["triplet_passes"]) for cell in eligible)
            tier_cells = [cell for cell in eligible if cell["triplet_passes"] == highest_tier]
        best_facts = max(int(cell["facts_found"]) for cell in tier_cells)
        floor = best_facts - 2
        candidates = [cell for cell in tier_cells if int(cell["facts_found"]) >= floor]
        winner = min(candidates, key=lambda cell: LEVELS.index(str(cell["level"])))
        arithmetic = {
            "highest_triplet_tier": highest_tier,
            "best_facts_in_tier": best_facts,
            "two_fact_floor": floor,
            "candidates": [cell["level"] for cell in candidates],
        }
    winner["selected"] = True
    return {"level": winner["level"], "status": "SELECTED", "reason": "precommitted_rule", **arithmetic}


def classifier_agreement(cells: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare exact privacy-safe domain sets, never their cardinalities."""
    classifier_cells = {cell["level"]: cell for cell in cells if cell["agent"] == "classifier"}
    result: dict[str, Any] = {}
    for left_index, left in enumerate(LEVELS):
        for right in LEVELS[left_index + 1 :]:
            left_sets = classifier_cells.get(left, {}).get("domain_sets")
            right_sets = classifier_cells.get(right, {}).get("domain_sets")
            key = f"{left}:{right}"
            if not isinstance(left_sets, Mapping) or not isinstance(right_sets, Mapping):
                result[key] = None
                continue
            labels = sorted(set(left_sets) & set(right_sets))
            result[key] = {
                "compared": len(labels),
                "equal": sum(left_sets[label] == right_sets[label] for label in labels),
            }
    return result


def _render_markdown(result: Mapping[str, Any]) -> str:
    lines = [
        "# Qwen per-agent effort sweep",
        "",
        "| Agent | Level | Status | Selected | Triplets | Facts | Timeouts | p50 s | p95 s | Raw |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for cell in result["cells"]:
        lines.append(
            "| {agent} | {level} | {status} | {selected} | {triplets} | {facts} | {timeouts} | "
            "{p50} | {p95} | {raw} |".format(
                agent=cell["agent"],
                level=cell["level"],
                status=cell["status"],
                selected="yes" if cell["selected"] else "no",
                triplets="—" if cell["triplet_passes"] is None else cell["triplet_passes"],
                facts="—" if cell["facts_found"] is None else f"{cell['facts_found']}/{cell['facts_total']}",
                timeouts="—" if cell["timeouts"] is None else cell["timeouts"],
                p50="—" if cell["p50_s"] is None else cell["p50_s"],
                p95="—" if cell["p95_s"] is None else cell["p95_s"],
                raw=cell["raw_path"] or "—",
            )
        )
    lines.extend(["", "## Applied selections", ""])
    for agent in AGENTS:
        selection = result["selections"].get(agent)
        if selection is None:
            lines.append(f"- {agent}: NOT MEASURED")
        else:
            lines.append(
                f"- {agent}: **{selection['level']}** ({selection['status']}); "
                f"tier={selection['highest_triplet_tier']}, best={selection['best_facts_in_tier']}, "
                f"floor={selection['two_fact_floor']}, candidates={selection['candidates']}"
            )
    lines.extend(
        [
            "",
            "Selection first maximizes the applicable triplet tier, then compact facts, then chooses the lowest",
            "effort within two facts of the tier best. Classifier chooses the lowest 8/8-valid eligible level.",
            "NOT MEASURED never passes a selection gate.",
            "",
        ]
    )
    return "\n".join(lines)


def persist(result: dict[str, Any], json_path: Path, markdown_path: Path) -> None:
    """Atomically replace the two incremental aggregate artifacts."""
    json_path.parent.mkdir(parents=True, exist_ok=True)
    result["classifier_domain_agreement"] = classifier_agreement(result["cells"])
    json_tmp = json_path.with_suffix(".json.tmp")
    md_tmp = markdown_path.with_suffix(".md.tmp")
    json_tmp.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    md_tmp.write_text(_render_markdown(result), encoding="utf-8")
    json_tmp.replace(json_path)
    md_tmp.replace(markdown_path)


def execute(args: argparse.Namespace, *, launcher: Launcher = run_child) -> dict[str, Any]:
    """Execute the frozen cell plan once and return the incremental aggregate."""
    identity_path = args.identity_json.resolve()
    baseline_path = args.baseline_json.resolve()
    output_dir = args.output_dir.resolve()
    cache_dir = args.cache_dir.resolve()
    identity = _load_object(identity_path)
    _load_object(baseline_path)
    levels = levels_from_identity(identity)
    if "off" not in levels:
        raise ValueError("identity evidence must retain off")
    if not 0 <= args.max_wall_seconds <= MAX_STAGE_WALL_SECONDS:
        raise ValueError("max-wall-seconds must be between 0 and 14400")
    model = str(identity.get("run", {}).get("configured_model") or "")
    if not model.startswith("local:"):
        raise ValueError("identity configured_model must use the local model route")

    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    aggregate_json = output_dir.parent / "effort-sweep.json"
    aggregate_md = output_dir.parent / "effort-sweep.md"
    planned_raw = [
        output_dir / f"{agent}-{level}.json"
        for agent in AGENTS
        for level in levels
        if agent != "extractor" or level != "off"
    ]
    existing = [path for path in (*planned_raw, aggregate_json, aggregate_md) if path.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite existing sweep artifact: {existing[0]}")

    analysis = identity.get("analysis")
    cancellation_fired = isinstance(analysis, Mapping) and analysis.get("cancellation_fired") is True
    corpus_sha256_value = identity.get("run", {}).get("compact_corpus_sha256")
    expected_corpus_sha256 = str(corpus_sha256_value) if corpus_sha256_value is not None else None
    result: dict[str, Any] = {
        "schema_version": 1,
        "run": {
            "model": "test-model" if args.test_model else model,
            "test_model": args.test_model,
            "identity_path": _display_path(identity_path),
            "baseline_path": _display_path(baseline_path),
            "levels": list(levels),
            "max_wall_seconds": float(args.max_wall_seconds),
            "budget_exhausted": False,
            "started_at": time.time(),
            "runner_wall_seconds": 0.0,
            "total_cell_wall_seconds": 0.0,
            "live_wall_seconds": 0.0,
            "complete": False,
        },
        "cells": [],
        "selections": {},
        "classifier_domain_agreement": {},
    }
    selected: dict[str, str] = {}
    started = time.monotonic()
    deadline = started + args.max_wall_seconds
    log_dir = ROOT / ".tmp/plan34/stage6-runner-logs" / f"{time.time_ns()}"

    if cancellation_fired:
        for agent in AGENTS:
            for level in levels:
                spec = make_spec(agent, level, selected)
                result["cells"].append(_unmeasured_cell(spec, "endpoint_ignores_effort"))
            selection = select_agent(agent, result["cells"])
            result["selections"][agent] = selection
            selected[agent] = "off"
        result["run"]["complete"] = True
        persist(result, aggregate_json, aggregate_md)
        return result

    env = child_environment()
    budget_stopped = False
    for agent in AGENTS:
        for level in levels:
            spec = make_spec(agent, level, selected)
            if agent == "extractor" and level == "off":
                cell = analyse_raw(
                    spec,
                    baseline_path,
                    test_model=args.test_model,
                    expected_model=model,
                    expected_corpus_sha256=expected_corpus_sha256,
                )
                cell["reused_baseline"] = True
                result["cells"].append(cell)
                persist(result, aggregate_json, aggregate_md)
                continue

            raw_path = output_dir / f"{agent}-{level}.json"
            remaining = deadline - time.monotonic()
            if budget_stopped or remaining <= 0:
                result["run"]["budget_exhausted"] = True
                result["cells"].append(_unmeasured_cell(spec, "wall_budget", raw_path))
                persist(result, aggregate_json, aggregate_md)
                continue

            command = probe_command(spec, raw_path, cache_dir, model, remaining, test_model=args.test_model)
            child = launcher(command, env, log_dir / f"{agent}-{level}.log", remaining)
            result["run"]["total_cell_wall_seconds"] = round(
                float(result["run"]["total_cell_wall_seconds"]) + child.wall_seconds, 3
            )
            if raw_path.exists():
                cell = analyse_raw(
                    spec,
                    raw_path,
                    test_model=args.test_model,
                    expected_model=model,
                    expected_corpus_sha256=expected_corpus_sha256,
                )
            else:
                reason = (
                    "process_timeout_no_raw" if child.status == "TIMEOUT" else f"child_exit_{child.returncode}_no_raw"
                )
                cell = _unmeasured_cell(spec, reason, raw_path)
            cell["child_status"] = child.status
            cell["child_returncode"] = child.returncode
            cell["child_wall_seconds"] = child.wall_seconds
            if child.status == "TIMEOUT":
                result["run"]["budget_exhausted"] = True
                budget_stopped = True
                cell["status"] = "TIMEOUT"
                cell["reason"] = "global_wall_budget"
            result["cells"].append(cell)
            persist(result, aggregate_json, aggregate_md)

        selection = select_agent(agent, result["cells"])
        result["selections"][agent] = selection
        selected[agent] = str(selection["level"])
        persist(result, aggregate_json, aggregate_md)

    result["run"]["runner_wall_seconds"] = round(time.monotonic() - started, 3)
    result["run"]["live_wall_seconds"] = 0.0 if args.test_model else result["run"]["total_cell_wall_seconds"]
    result["run"]["complete"] = True
    persist(result, aggregate_json, aggregate_md)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-model", action="store_true")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--identity-json", required=True, type=Path)
    parser.add_argument("--baseline-json", required=True, type=Path)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--max-wall-seconds", required=True, type=float)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        result = execute(build_parser().parse_args(argv))
    except (FileExistsError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"selections": result["selections"], "run": result["run"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
