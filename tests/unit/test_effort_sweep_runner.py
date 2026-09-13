"""Deterministic tests for the Stage 6 effort-sweep runner."""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from scripts import qwen_speed_probe as probe  # ty: ignore[unresolved-import]

RUNNER_PATH = (
    Path(__file__).resolve().parents[2] / "docs/plans/34-qwen-thinking-benchmark/validation/effort_sweep_runner.py"
)
SPEC = importlib.util.spec_from_file_location("effort_sweep_runner", RUNNER_PATH)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


def _identity(*, cancellation: bool | None = None) -> dict[str, Any]:
    return {
        "run": {"finalized": True, "configured_model": "local:qwen3.8-flash-next"},
        "analysis": {
            "distinct_levels": ["off", "low", "medium", "high"],
            "cancellation_fired": cancellation,
        },
    }


def _raw(
    spec: Any,
    *,
    facts_found: int = 40,
    triplet_passes: int = 2,
    defects: list[str] | None = None,
    timeout_labels: set[str] | None = None,
    domain_tag: str = "known:technical_knowledge",
) -> dict[str, Any]:
    defects = defects or []
    timeout_labels = timeout_labels or set()
    compact_scores = []
    remaining = facts_found
    for _ in runner.COMPACT_UNITS:
        found = min(remaining, 7)
        remaining -= found
        compact_scores.append({"facts_found": found, "facts_total": 7, "missing_keys": []})
    summaries: list[dict[str, Any]] = [
        {
            "episode": label,
            "fact_score": score,
            "supersession": None,
            "critical_defects": list(defects),
            "status": "ok",
        }
        for label, score in zip(runner.COMPACT_UNITS, compact_scores, strict=True)
    ]
    if spec.corpus == "both":
        summaries.extend(
            {
                "episode": label,
                "fact_score": None,
                "supersession": {
                    "new_present": index < triplet_passes,
                    "old_absent": True,
                    "temporal_edge_present": False,
                },
                "critical_defects": list(defects),
                "status": "ok",
            }
            for index, label in enumerate(runner.TRIPLET_UNITS)
        )
    rows: list[dict[str, Any]] = []
    for index, label in enumerate(spec.expected_source_labels, start=1):
        row: dict[str, Any] = {
            "episode": label,
            "stage": spec.agent,
            "seconds": float(index),
            "reasoning_tokens": index,
            "status": "timeout" if label in timeout_labels else "ok",
        }
        if spec.agent == "classifier":
            row.update({"valid_result": True, "domain_keys": [domain_tag]})
        if spec.agent == "ontology":
            row.update(
                {
                    "accepted_node_proposals": 1,
                    "accepted_edge_proposals": 2,
                    "rejected_node_proposals": 3,
                    "rejected_edge_proposals": 4,
                    "proposal_rejection_reasons": {"node:already_exists": 3},
                }
            )
        rows.append(row)
    return {
        "run": {
            "model": "test-model",
            "corpus": spec.corpus,
            "stage": spec.stage,
            "cache_thinking": spec.cache_thinking or "off",
            **{f"thinking_{agent}": level for agent, level in spec.levels.items()},
            "wall_seconds": 12.5,
        },
        "episodes": summaries,
        "stages": rows,
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _cell(level: str, *, facts: int, triplets: int | None, status: str = "PASS") -> dict[str, Any]:
    return {
        "agent": "extractor",
        "level": level,
        "facts_found": facts,
        "triplet_passes": triplets,
        "status": status,
        "selected": False,
    }


def test_higher_triplet_tier_beats_any_fact_count() -> None:
    cells = [_cell("off", facts=56, triplets=1), _cell("low", facts=10, triplets=2)]

    selection = runner.select_agent("extractor", cells)

    assert selection["level"] == "low"
    assert selection["highest_triplet_tier"] == 2


def test_two_fact_band_selects_the_lowest_effort() -> None:
    cells = [
        _cell("off", facts=40, triplets=3),
        _cell("low", facts=42, triplets=3),
        _cell("medium", facts=43, triplets=3),
    ]

    selection = runner.select_agent("extractor", cells)

    assert selection["best_facts_in_tier"] == 43
    assert selection["two_fact_floor"] == 41
    assert selection["level"] == "low"


def test_disqualified_and_unmeasured_cells_cannot_win() -> None:
    cells = [
        _cell("off", facts=30, triplets=1),
        _cell("low", facts=56, triplets=3, status="DISQUALIFIED"),
        _cell("medium", facts=56, triplets=3, status="NOT MEASURED"),
    ]

    assert runner.select_agent("extractor", cells)["level"] == "off"


def test_no_eligible_cell_is_an_unmeasured_off_fallback() -> None:
    cells = [
        _cell("off", facts=0, triplets=None, status="NOT MEASURED"),
        _cell("low", facts=0, triplets=None, status="NOT MEASURED"),
    ]

    selection = runner.select_agent("extractor", cells)

    assert selection == {
        "level": "off",
        "status": "NOT MEASURED",
        "reason": "no_eligible_measured_level",
        "highest_triplet_tier": None,
        "best_facts_in_tier": None,
        "two_fact_floor": None,
        "candidates": [],
    }
    assert cells[0]["selected"] is True


def test_classifier_requires_eight_valid_results_and_chooses_lowest() -> None:
    cells = [
        {"agent": "classifier", "level": "off", "status": "DISQUALIFIED", "selected": False},
        {"agent": "classifier", "level": "low", "status": "PASS", "selected": False},
        {"agent": "classifier", "level": "medium", "status": "PASS", "selected": False},
    ]

    assert runner.select_agent("classifier", cells)["level"] == "low"


def test_analyse_raw_rejects_row_mismatch_instead_of_padding(tmp_path: Path) -> None:
    spec = runner.make_spec("extractor", "low", {})
    raw = _raw(spec)
    raw["stages"].pop()
    path = tmp_path / "raw.json"
    _write_json(path, raw)

    cell = runner.analyse_raw(spec, path, test_model=True)

    assert cell["status"] == "NOT MEASURED"
    assert cell["reason"] == "target_stage_row_mismatch"
    assert cell["facts_found"] is None


def test_analyse_raw_counts_distinct_timeout_labels_and_disqualifies_two(tmp_path: Path) -> None:
    spec = runner.make_spec("extractor", "low", {})
    path = tmp_path / "raw.json"
    _write_json(path, _raw(spec, timeout_labels={"S05-1", "S05-2"}))

    cell = runner.analyse_raw(spec, path, test_model=True)

    assert cell["timeouts"] == 2
    assert cell["status"] == "DISQUALIFIED"


def test_analyse_raw_one_timeout_with_unavailable_usage_has_null_median(tmp_path: Path) -> None:
    """One allowed timeout stays eligible but cannot invent a reasoning-token median."""
    spec = runner.make_spec("extractor", "low", {})
    raw = _raw(spec)
    [timeout_row] = probe.aggregate_stage_rows(
        "E02",
        [{"event": "agent_run_started", "fields": {"agent": "extractor"}}],
        outcome="timeout",
    )
    raw["stages"][0] = timeout_row
    path = tmp_path / "raw.json"
    _write_json(path, raw)

    cell = runner.analyse_raw(spec, path, test_model=True)

    assert cell["timeouts"] == 1
    assert cell["status"] == "PASS"
    assert cell["median_reasoning_tokens"] is None


def test_analyse_raw_requires_each_stage_status_for_timeout_evidence(tmp_path: Path) -> None:
    spec = runner.make_spec("extractor", "low", {})
    raw = _raw(spec)
    raw["stages"][0]["status"] = None
    path = tmp_path / "raw.json"
    _write_json(path, raw)

    cell = runner.analyse_raw(spec, path, test_model=True)

    assert cell["status"] == "NOT MEASURED"
    assert cell["reason"] == "missing_stage_status"
    assert cell["timeouts"] is None


def test_analyse_raw_rejects_a_wrong_live_model(tmp_path: Path) -> None:
    spec = runner.make_spec("extractor", "low", {})
    raw = _raw(spec)
    raw["run"]["model"] = "local:wrong-model"
    path = tmp_path / "raw.json"
    _write_json(path, raw)

    cell = runner.analyse_raw(
        spec,
        path,
        test_model=False,
        expected_model="local:qwen3.8-flash-next",
    )

    assert cell["status"] == "NOT MEASURED"
    assert cell["reason"] == "raw_configuration_mismatch"


def test_analyse_raw_disqualifies_a_critical_defect(tmp_path: Path) -> None:
    spec = runner.make_spec("extractor", "low", {})
    path = tmp_path / "raw.json"
    _write_json(path, _raw(spec, defects=["reasoning_marker"]))

    cell = runner.analyse_raw(spec, path, test_model=True)

    assert cell["critical_defects"] == ["reasoning_marker"]
    assert cell["status"] == "DISQUALIFIED"


def test_analyse_raw_aggregates_nullable_ontology_observations(tmp_path: Path) -> None:
    spec = runner.make_spec("ontology", "off", {"extractor": "low", "librarian": "off"})
    path = tmp_path / "raw.json"
    _write_json(path, _raw(spec))

    cell = runner.analyse_raw(spec, path, test_model=True)

    assert cell["triplet_passes"] is None
    assert cell["tier"] == "compact"
    assert cell["accepted_node_proposals"] == 8
    assert cell["accepted_edge_proposals"] == 16
    assert cell["rejected_node_proposals"] == 24
    assert cell["proposal_rejection_reasons"] == {"node:already_exists": 24}


def test_analyse_raw_never_turns_missing_ontology_counts_into_zero(tmp_path: Path) -> None:
    spec = runner.make_spec("ontology", "off", {"extractor": "low", "librarian": "off"})
    raw = _raw(spec)
    raw["stages"][0]["accepted_node_proposals"] = None
    path = tmp_path / "raw.json"
    _write_json(path, raw)

    cell = runner.analyse_raw(spec, path, test_model=True)

    assert cell["status"] == "NOT MEASURED"
    assert cell["accepted_node_proposals"] is None


def test_classifier_agreement_compares_sets_not_counts(tmp_path: Path) -> None:
    selected = {"extractor": "off", "librarian": "off", "ontology": "off"}
    cells = []
    for level, tag in (("off", "known:technical_knowledge"), ("low", "known:work_context")):
        spec = runner.make_spec("classifier", level, selected)
        path = tmp_path / f"{level}.json"
        _write_json(path, _raw(spec, domain_tag=tag))
        cells.append(runner.analyse_raw(spec, path, test_model=True))

    agreement = runner.classifier_agreement(cells)

    assert agreement["off:low"] == {"compared": 8, "equal": 0}
    assert agreement["off:medium"] is None


def test_classifier_raw_requires_all_eight_valid_results(tmp_path: Path) -> None:
    spec = runner.make_spec(
        "classifier",
        "off",
        {"extractor": "off", "librarian": "off", "ontology": "off"},
    )
    raw = _raw(spec)
    raw["stages"][0]["valid_result"] = False
    raw["stages"][0]["domain_keys"] = None
    path = tmp_path / "classifier.json"
    _write_json(path, raw)

    cell = runner.analyse_raw(spec, path, test_model=True)

    assert cell["valid_results"] == 7
    assert cell["domain_sets"] is None
    assert cell["status"] == "DISQUALIFIED"


def test_commands_pin_upstream_levels_and_librarian_cache(tmp_path: Path) -> None:
    selected = {"extractor": "medium", "librarian": "low", "ontology": "high"}
    librarian = runner.make_spec("librarian", "off", selected)
    classifier = runner.make_spec("classifier", "low", selected)

    librarian_command = runner.probe_command(
        librarian, tmp_path / "lib.json", tmp_path / "cache", "local:model", 100, test_model=True
    )
    classifier_command = runner.probe_command(
        classifier, tmp_path / "cls.json", tmp_path / "cache", "local:model", 100, test_model=True
    )

    assert librarian_command[librarian_command.index("--cache-thinking") + 1] == "off"
    assert librarian_command[librarian_command.index("--thinking-extractor") + 1] == "medium"
    assert librarian_command[librarian_command.index("--thinking-ontology") + 1] == "off"
    assert classifier_command[classifier_command.index("--thinking") + 1] == "off"
    assert classifier_command[classifier_command.index("--thinking-extractor") + 1] == "medium"
    assert classifier_command[classifier_command.index("--thinking-librarian") + 1] == "low"
    assert classifier_command[classifier_command.index("--thinking-ontology") + 1] == "high"
    assert "--classify" in classifier_command


def test_full_mock_plan_launches_each_nonbaseline_cell_once(tmp_path: Path) -> None:
    identity_path = tmp_path / "identity.json"
    baseline_path = tmp_path / "baseline.json"
    output_dir = tmp_path / "result/sweep"
    cache_dir = tmp_path / "cache"
    _write_json(identity_path, _identity())
    _write_json(baseline_path, _raw(runner.make_spec("extractor", "off", {})))
    commands: list[list[str]] = []

    def fake_launcher(command: Any, env: Any, log_path: Path, timeout: float) -> Any:
        del env, timeout
        argv = list(command)
        commands.append(argv)
        raw_path = Path(argv[argv.index("--output") + 1])
        agent, level = raw_path.stem.split("-", maxsplit=1)
        levels = {
            name: argv[argv.index(f"--thinking-{name}") + 1]
            for name in ("ontology", "extractor", "librarian", "classifier")
        }
        spec = runner.CellSpec(
            agent=agent,
            level=level,
            corpus=argv[argv.index("--corpus") + 1],
            stage="librarian" if "--stage" in argv else "all",
            classify="--classify" in argv,
            levels=levels,
            cache_thinking="off" if "--cache-thinking" in argv else None,
        )
        _write_json(raw_path, _raw(spec))
        return runner.ChildResult("EXITED", 0, 0.01, log_path)

    args = runner.build_parser().parse_args(
        [
            "--test-model",
            "--output-dir",
            str(output_dir),
            "--identity-json",
            str(identity_path),
            "--baseline-json",
            str(baseline_path),
            "--cache-dir",
            str(cache_dir),
            "--max-wall-seconds",
            "100",
        ]
    )
    result = runner.execute(args, launcher=fake_launcher)

    assert len(result["cells"]) == 16
    assert len(commands) == 15
    assert len({tuple(command) for command in commands}) == 15
    assert all(selection["level"] == "off" for selection in result["selections"].values())
    assert result["cells"][0]["reused_baseline"] is True
    assert (output_dir.parent / "effort-sweep.json").is_file()
    assert (output_dir.parent / "effort-sweep.md").is_file()


def test_identity_cancellation_makes_no_launch_and_selects_unmeasured_off(tmp_path: Path) -> None:
    identity_path = tmp_path / "identity.json"
    baseline_path = tmp_path / "baseline.json"
    _write_json(identity_path, _identity(cancellation=True))
    _write_json(baseline_path, {})
    args = runner.build_parser().parse_args(
        [
            "--test-model",
            "--output-dir",
            str(tmp_path / "result/sweep"),
            "--identity-json",
            str(identity_path),
            "--baseline-json",
            str(baseline_path),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--max-wall-seconds",
            "100",
        ]
    )

    def forbidden_launcher(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("cancellation launched a cell")

    result = runner.execute(args, launcher=forbidden_launcher)

    assert len(result["cells"]) == 16
    assert all(cell["status"] == "NOT MEASURED" for cell in result["cells"])
    assert all(selection["status"] == "NOT MEASURED" for selection in result["selections"].values())


def test_runner_refuses_a_hosted_identity_before_launch(tmp_path: Path) -> None:
    identity = _identity()
    identity["run"]["configured_model"] = "openai-responses:gpt-5.4-mini"
    identity_path = tmp_path / "identity.json"
    baseline_path = tmp_path / "baseline.json"
    _write_json(identity_path, identity)
    _write_json(baseline_path, {})
    args = runner.build_parser().parse_args(
        [
            "--output-dir",
            str(tmp_path / "result/sweep"),
            "--identity-json",
            str(identity_path),
            "--baseline-json",
            str(baseline_path),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--max-wall-seconds",
            "100",
        ]
    )

    with pytest.raises(ValueError, match="local model route"):
        runner.execute(args)


def test_runner_refuses_existing_raw_artifact(tmp_path: Path) -> None:
    identity_path = tmp_path / "identity.json"
    baseline_path = tmp_path / "baseline.json"
    output_dir = tmp_path / "result/sweep"
    _write_json(identity_path, _identity())
    _write_json(baseline_path, _raw(runner.make_spec("extractor", "off", {})))
    _write_json(output_dir / "extractor-low.json", {})
    args = runner.build_parser().parse_args(
        [
            "--test-model",
            "--output-dir",
            str(output_dir),
            "--identity-json",
            str(identity_path),
            "--baseline-json",
            str(baseline_path),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--max-wall-seconds",
            "100",
        ]
    )

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        runner.execute(args)


def test_global_process_timeout_stops_every_later_cell(tmp_path: Path) -> None:
    identity_path = tmp_path / "identity.json"
    baseline_path = tmp_path / "baseline.json"
    output_dir = tmp_path / "result/sweep"
    _write_json(identity_path, _identity())
    _write_json(baseline_path, _raw(runner.make_spec("extractor", "off", {})))
    launched: list[list[str]] = []

    def timeout_launcher(command: Any, env: Any, log_path: Path, timeout: float) -> Any:
        del env, timeout
        launched.append(list(command))
        return runner.ChildResult("TIMEOUT", -15, 0.01, log_path)

    args = runner.build_parser().parse_args(
        [
            "--test-model",
            "--output-dir",
            str(output_dir),
            "--identity-json",
            str(identity_path),
            "--baseline-json",
            str(baseline_path),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--max-wall-seconds",
            "100",
        ]
    )
    result = runner.execute(args, launcher=timeout_launcher)

    assert len(launched) == 1
    assert len(result["cells"]) == 16
    assert result["cells"][1]["status"] == "TIMEOUT"
    assert all(cell["status"] == "NOT MEASURED" for cell in result["cells"][2:])
    assert result["run"]["budget_exhausted"] is True


def test_process_backstop_terminates_only_its_child(tmp_path: Path) -> None:
    started = time.monotonic()
    result = runner.run_child(
        [sys.executable, "-c", "import time; time.sleep(2)"],
        {},
        tmp_path / "child.log",
        0.05,
    )

    assert result.status == "TIMEOUT"
    assert result.returncode is not None
    assert time.monotonic() - started < 0.75
    assert result.log_path.read_text(encoding="utf-8") == ""
