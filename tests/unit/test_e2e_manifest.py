"""Strict, privacy-safe contracts for Stage 6 child evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, TypedDict, cast

import pytest
from scripts import e2e_manifest as evidence  # ty: ignore[unresolved-import]
from scripts.compute_metrics import invalid_type_names  # ty: ignore[unresolved-import]
from scripts.e2e_plan15_scenarios_test import (  # ty: ignore[unresolved-import]
    ScenarioResult,
    Verdict,
    build_result_payload,
)


class ManifestFixture(TypedDict):
    run_id: str
    snapshot: Path
    snapshot_digest: str
    metrics: Path
    recall: Path
    statuses: Path
    output: Path


def _scenario_result(script: str, verdicts: list[str], child_run_id: str, exit_code: int) -> dict:
    counts = {
        "total": len(verdicts),
        "pass": verdicts.count("PASS"),
        "partial": verdicts.count("PARTIAL"),
        "acceptable": verdicts.count("ACCEPTABLE"),
        "fail": verdicts.count("FAIL"),
    }
    if script == "e2e_plan15_scenarios_test.py":
        counts["acceptable"] = counts["pass"] + counts["partial"]
        passed = counts["pass"] >= 11
        basis = "PASS"
        threshold = 11
    else:
        passed = counts["acceptable"] >= 13 and counts["fail"] == 0
        basis = "ACCEPTABLE"
        threshold = 13
    return {
        "schema_version": 1,
        "kind": "neocortex-e2e-scenario-result",
        "script": script,
        "child_run_id": child_run_id,
        "status": "PASS" if passed else "FAIL",
        "exit_code": exit_code,
        "counts": counts,
        "gate": {"basis": basis, "threshold": threshold, "passed": passed},
        "scenarios": [{"index": i, "verdict": verdict} for i, verdict in enumerate(verdicts, 1)],
    }


@pytest.mark.parametrize(("passed", "exit_code"), [(11, 0), (10, 1)])
def test_plan15_gate_is_strict_pass_only(passed: int, exit_code: int) -> None:
    verdicts = ["PASS"] * passed + ["PARTIAL"] * (14 - passed)
    result = _scenario_result("e2e_plan15_scenarios_test.py", verdicts, "run.e2e.01", exit_code)

    safe = evidence.validate_scenario_result(
        result, script="e2e_plan15_scenarios_test.py", child_run_id="run.e2e.01", exit_code=exit_code
    )

    assert safe["gate"]["passed"] is (passed >= 11)


@pytest.mark.parametrize(("pass_count", "partial_count", "expected_exit"), [(11, 3, 0), (10, 4, 1)])
def test_plan15_producer_keeps_partial_informational_only(
    pass_count: int, partial_count: int, expected_exit: int
) -> None:
    results = [
        *[ScenarioResult(f"pass-{index}", Verdict.PASS) for index in range(pass_count)],
        *[ScenarioResult(f"partial-{index}", Verdict.PARTIAL) for index in range(partial_count)],
    ]

    payload = build_result_payload(results, "run.e2e.01")

    assert payload["counts"] == {
        "total": 14,
        "pass": pass_count,
        "partial": partial_count,
        "acceptable": 14,
        "fail": 0,
    }
    assert payload["gate"] == {"basis": "PASS", "threshold": 11, "passed": expected_exit == 0}
    assert payload["status"] == ("PASS" if expected_exit == 0 else "FAIL")
    assert payload["exit_code"] == expected_exit


@pytest.mark.parametrize("mutation", ["m2_low", "m2_high", "known_mismatch", "missing_mismatch", "no_id_m2"])
def test_recall_validator_rejects_forged_m2_or_availability(mutation: str) -> None:
    recall = cast(
        dict[str, Any],
        {
            "schema_version": 1,
            "kind": "neocortex-recall-evidence",
            "status": "MEASURED",
            "run_id": "run-123",
            "query_count": 1,
            "query_results": [{"index": 1, "result_count": 1, "top_item_hash": "a" * 64, "keyword_match_count": 0}],
            "metrics": {
                "M1_max_activation": 1.0,
                "M2_max_top1_count": 1,
                "M3_specific_event_pass": 0,
                "M4_temporal_pass": 0,
            },
            "opaque_item_hashes": ["a" * 64],
            "top1_id_availability": {"known": 1, "missing": 0},
        },
    )
    if mutation == "m2_low":
        recall["metrics"]["M2_max_top1_count"] = 0
    elif mutation == "m2_high":
        recall["metrics"]["M2_max_top1_count"] = 2
    elif mutation == "known_mismatch":
        recall["top1_id_availability"] = {"known": 0, "missing": 1}
    elif mutation == "missing_mismatch":
        recall["top1_id_availability"] = {"known": 1, "missing": 1}
    else:
        recall["query_results"][0]["top_item_hash"] = None
        recall["top1_id_availability"] = {"known": 0, "missing": 1}

    with pytest.raises(evidence.EvidenceError):
        evidence.validate_recall_evidence(recall, run_id="run-123")


@pytest.mark.parametrize(
    ("acceptable", "fail", "exit_code"),
    [(13, 0, 0), (12, 0, 1), (13, 1, 1)],
)
def test_plan17_gate_requires_thirteen_acceptable_and_zero_failures(acceptable: int, fail: int, exit_code: int) -> None:
    verdicts = ["ACCEPTABLE"] * acceptable + ["FAIL"] * fail + ["PARTIAL"] * (14 - acceptable - fail)
    result = _scenario_result("e2e_plan17_validation.py", verdicts, "run.e2e.02", exit_code)

    safe = evidence.validate_scenario_result(
        result, script="e2e_plan17_validation.py", child_run_id="run.e2e.02", exit_code=exit_code
    )

    assert safe["gate"]["passed"] is (acceptable >= 13 and fail == 0)


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "count_mismatch"])
def test_scenario_result_rejects_malformed_or_duplicate_rows(mutation: str) -> None:
    result = _scenario_result("e2e_plan15_scenarios_test.py", ["PASS"] * 11 + ["PARTIAL"] * 3, "run.e2e.01", 0)
    if mutation == "duplicate":
        result["scenarios"][1]["index"] = 1
    elif mutation == "missing":
        result["scenarios"] = result["scenarios"][:-1]
    else:
        result["counts"]["pass"] = 10

    with pytest.raises(evidence.EvidenceError):
        evidence.validate_scenario_result(
            result, script="e2e_plan15_scenarios_test.py", child_run_id="run.e2e.01", exit_code=0
        )


def test_node_and_edge_type_validation_keeps_valid_builtins() -> None:
    result = invalid_type_names(
        ["Concept", "Person", "Document", "Organization", "APIKey"],
        ["RELATES_TO", "SUPERSEDES", "HAS_GOAL", "EXPERIENCED"],
    )

    assert result == {"invalid_node_type_names": [], "invalid_edge_type_names": [], "invalid_type_names": []}


def test_node_and_edge_type_validation_rejects_malformed_values() -> None:
    result = invalid_type_names(["bad_node", "Bad_Node"], ["BadEdge", "bad_edge", "VALID_EDGE"])

    assert result["invalid_node_type_names"] == ["bad_node", "Bad_Node"]
    assert result["invalid_edge_type_names"] == ["BadEdge", "bad_edge"]
    assert result["invalid_type_names"] == ["bad_node", "Bad_Node", "BadEdge", "bad_edge"]


def _manifest_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ManifestFixture:
    monkeypatch.setattr(evidence, "ROOT", tmp_path)
    scripts = tmp_path / "scripts"
    resources = tmp_path / "resources"
    results = tmp_path / "results"
    scripts.mkdir()
    resources.mkdir()
    results.mkdir()
    for script in evidence.E2E_SCRIPTS:
        (scripts / script).write_text(f"# {script}\n")
    run_id = "run-123"
    snapshot = resources / "post.tar.gz"
    snapshot.write_bytes(b"safe snapshot bytes")
    snapshot_digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    metrics = resources / "metrics-arm.json"
    metrics.write_text(
        json.dumps(
            {
                "arm": "arm",
                "phase": "corpus",
                "run_metadata": {"run_id": run_id, "snapshot_sha256": snapshot_digest},
                "input_paths": {"graph_snapshot": "resources/post.tar.gz"},
            }
        )
    )
    recall = resources / "recall.json"
    recall.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "neocortex-recall-evidence",
                "status": "MEASURED",
                "run_id": run_id,
                "query_count": 1,
                "query_results": [{"index": 1, "result_count": 1, "top_item_hash": "a" * 64, "keyword_match_count": 1}],
                "metrics": {
                    "M1_max_activation": 1.0,
                    "M2_max_top1_count": 1,
                    "M3_specific_event_pass": 1,
                    "M4_temporal_pass": 1,
                },
                "opaque_item_hashes": ["a" * 64],
                "top1_id_availability": {"known": 1, "missing": 0},
            }
        )
    )
    statuses = tmp_path / "status.tsv"
    status_lines = []
    for index, script in enumerate(evidence.E2E_SCRIPTS, 1):
        result_path = results / f"{index:02d}.json"
        child = f"{run_id}.e2e.{index:02d}"
        if script in evidence.SCENARIO_GATES:
            verdicts = ["PASS"] * 14 if script.startswith("e2e_plan15") else ["ACCEPTABLE"] * 14
            result = _scenario_result(script, verdicts, child, 0)
        else:
            evidence.write_exit_result(result_path, script=script, child_run_id=child, exit_code=0)
            result = None
        if result is not None:
            result_path.write_text(json.dumps(result))
        status_lines.append(f"{script}\t{child}\t0\t{result_path}\n")
    statuses.write_text("".join(status_lines))
    return {
        "run_id": run_id,
        "snapshot": snapshot,
        "snapshot_digest": snapshot_digest,
        "metrics": metrics,
        "recall": recall,
        "statuses": statuses,
        "output": resources / "manifest.json",
    }


def test_build_validate_and_validation_only_merge_are_run_scoped_atomic_and_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _manifest_fixture(tmp_path, monkeypatch)
    manifest = evidence.build_manifest(
        arm="arm",
        run_id=fixture["run_id"],
        metrics_path=fixture["metrics"],
        snapshot_path=fixture["snapshot"],
        snapshot_sha256=fixture["snapshot_digest"],
        recall_path=fixture["recall"],
        statuses_path=fixture["statuses"],
        output_path=fixture["output"],
    )
    assert manifest["schema_version"] == 2
    assert manifest["status"] == "MEASURED"
    assert manifest["recall"]["result"] == {
        "status": "MEASURED",
        "query_count": 1,
        "metrics": {
            "M1_max_activation": 1.0,
            "M2_max_top1_count": 1,
            "M3_specific_event_pass": 1,
            "M4_temporal_pass": 1,
        },
        "opaque_item_hash_count": 1,
        "top1_id_availability": {"known": 1, "missing": 0},
    }
    assert [child["child_run_id"] for child in manifest["e2e"]["children"]] == [
        f"run-123.e2e.{index:02d}" for index in range(1, 6)
    ]
    serialized = fixture["output"].read_text()
    assert all(secret not in serialized for secret in ("SECRET", "Project Nexus", "prompt text", "schema_name"))
    assert not list(fixture["output"].parent.glob(".manifest.json.*.tmp"))

    with pytest.raises(evidence.EvidenceError):
        evidence.merge_manifest(
            manifest_path=fixture["output"],
            metrics_path=fixture["metrics"],
            run_id="other-run",
            snapshot_path=fixture["snapshot"],
            snapshot_sha256=fixture["snapshot_digest"],
        )
    before = fixture["metrics"].read_bytes()
    merged = evidence.merge_manifest(
        manifest_path=fixture["output"],
        metrics_path=fixture["metrics"],
        run_id=fixture["run_id"],
        snapshot_path=fixture["snapshot"],
        snapshot_sha256=fixture["snapshot_digest"],
    )
    assert merged["run_metadata"]["run_id"] == fixture["run_id"]
    assert fixture["metrics"].read_bytes() == before
    assert "e2e_manifest" not in json.loads(fixture["metrics"].read_text())
    assert not list(fixture["metrics"].parent.glob(".metrics-arm.json.*.tmp"))


def test_validation_detects_each_referenced_file_tamper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _manifest_fixture(tmp_path, monkeypatch)
    evidence.build_manifest(
        arm="arm",
        run_id=fixture["run_id"],
        metrics_path=fixture["metrics"],
        snapshot_path=fixture["snapshot"],
        snapshot_sha256=fixture["snapshot_digest"],
        recall_path=fixture["recall"],
        statuses_path=fixture["statuses"],
        output_path=fixture["output"],
    )
    originals = {key: fixture[key].read_bytes() for key in ("metrics", "snapshot", "recall")}
    for key, message in (
        ("metrics", "corpus_metrics reference file or digest is invalid"),
        ("snapshot", "post_snapshot reference file or digest is invalid"),
        ("recall", "recall reference file or digest is invalid"),
    ):
        fixture[key].write_bytes(originals[key] + b"x")
        with pytest.raises(evidence.EvidenceError, match=message):
            evidence.validate_manifest(manifest_path=fixture["output"], run_id=fixture["run_id"])
        fixture[key].write_bytes(originals[key])


def test_offline_merge_rejects_forged_recall_summary_with_genuine_source_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _manifest_fixture(tmp_path, monkeypatch)
    evidence.build_manifest(
        arm="arm",
        run_id=fixture["run_id"],
        metrics_path=fixture["metrics"],
        snapshot_path=fixture["snapshot"],
        snapshot_sha256=fixture["snapshot_digest"],
        recall_path=fixture["recall"],
        statuses_path=fixture["statuses"],
        output_path=fixture["output"],
    )
    manifest = json.loads(fixture["output"].read_text())
    source_digest = manifest["recall"]["sha256"]
    manifest["recall"]["result"]["metrics"]["M1_max_activation"] = 999.0
    evidence.atomic_write_json(fixture["output"], manifest)

    assert evidence.sha256_file(fixture["recall"]) == source_digest
    with pytest.raises(evidence.EvidenceError, match="does not match"):
        evidence.merge_manifest(
            manifest_path=fixture["output"],
            metrics_path=fixture["metrics"],
            run_id=fixture["run_id"],
            snapshot_path=fixture["snapshot"],
            snapshot_sha256=fixture["snapshot_digest"],
        )


def test_offline_merge_rejects_snapshot_hash_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _manifest_fixture(tmp_path, monkeypatch)
    evidence.build_manifest(
        arm="arm",
        run_id=fixture["run_id"],
        metrics_path=fixture["metrics"],
        snapshot_path=fixture["snapshot"],
        snapshot_sha256=fixture["snapshot_digest"],
        recall_path=fixture["recall"],
        statuses_path=fixture["statuses"],
        output_path=fixture["output"],
    )
    fixture["snapshot"].write_bytes(b"tampered snapshot")

    with pytest.raises(evidence.EvidenceError):
        evidence.merge_manifest(
            manifest_path=fixture["output"],
            metrics_path=fixture["metrics"],
            run_id=fixture["run_id"],
            snapshot_path=fixture["snapshot"],
            snapshot_sha256=fixture["snapshot_digest"],
        )


# ── Failure attribution for children recorded by exit status only ──

_STEP_STDOUT = """Starting run
=== Step 1: Ingest seed corpus & wait for extraction ===
ingested 8 episodes
=== Step 2: Wait for extraction jobs (timeout 120s) ===
"""

_STAGE_STDOUT = """=== Stage 1: Session Ingestion ===
=== Stage 1 PASSED ===
=== Stage 2: Session Recall with Neighbors ===
"""

_SCENARIO_STDOUT = """======================================================================
PHASE A: Ingesting initial episodes
======================================================================
--- Scenario 1: entity is recalled after ingestion ---
--- Scenario 2: temporal correction supersedes the old node ---
"""

_PHASE_ONLY_STDOUT = """======================================================================
PHASE B: Recall after consolidation
======================================================================
querying the graph
"""

_BOTH_BANNERS_STDOUT = """--- Scenario 7: contradiction is resolved in favour of the newer episode ---
======================================================================
PHASE B: Recall after consolidation
======================================================================
"""

_EPISODIC_STAGE3_STDOUT = """=== Stage 2: Session Recall with Neighbors ===
=== Stage 2 PASSED ===
--- Cross-Session Isolation Check ---
  Cross-session isolation verified
=== Stage 3: STM Boost Validation ===
Backdating Session A episodes to 3h ago...
"""


@pytest.mark.parametrize(
    ("stdout", "expected_kind", "expected_fragment"),
    [
        (_STEP_STDOUT, "step", "=== Step 2:"),
        (_STAGE_STDOUT, "stage", "=== Stage 2:"),
        (_SCENARIO_STDOUT, "scenario", "--- Scenario 2:"),
        (_PHASE_ONLY_STDOUT, "phase", "PHASE B:"),
    ],
)
def test_every_banner_convention_yields_a_failure_step(stdout: str, expected_kind: str, expected_fragment: str) -> None:
    # A parser that matches only ``=== Step`` fails three of these four cases.
    step, kind = evidence.parse_failure_step(stdout)
    assert kind == expected_kind
    assert step is not None and expected_fragment in step


@pytest.mark.parametrize("script", sorted(evidence.SCENARIO_GATES))
def test_a_scenario_docstring_beats_a_later_phase_banner(script: str) -> None:
    # "Last banner wins" would answer ``PHASE B``, which only says which third
    # of the run died.  The scenario docstring localizes the failure.
    step, kind = evidence.parse_failure_step(_BOTH_BANNERS_STDOUT, script=script)
    assert kind == "scenario"
    assert step is not None and step.startswith("--- Scenario 7:")


@pytest.mark.parametrize("rule", ["=" * 70, "-" * 70, "=" * 3])
def test_a_rule_line_is_never_a_failure_step(rule: str) -> None:
    assert evidence.parse_failure_step(f"{rule}\n") == (None, None)


def test_stdout_without_any_banner_has_no_failure_step() -> None:
    assert evidence.parse_failure_step("just some output\nand more\n") == (None, None)


def test_exception_class_is_extracted_without_the_message_text() -> None:
    stderr = (
        "Traceback (most recent call last):\n"
        '  File "scripts/e2e_episodic_memory_test.py", line 512, in _stage\n'
        "    print(formatted_ctx)\n"
        "NameError: name 'formatted_ctx' is not defined. Did you mean: 'formatted_context'?\n"
    )
    assert evidence.parse_exception_class(stderr) == "NameError"


def test_exception_class_reads_the_last_traceback_not_the_first() -> None:
    stderr = (
        "Traceback (most recent call last):\n"
        '  File "a.py", line 1, in <module>\n'
        "ValueError: first\n"
        "Traceback (most recent call last):\n"
        '  File "b.py", line 2, in <module>\n'
        "asyncio.exceptions.TimeoutError: second\n"
    )
    assert evidence.parse_exception_class(stderr) == "asyncio.exceptions.TimeoutError"


def test_stderr_without_a_traceback_has_no_exception_class() -> None:
    assert evidence.parse_exception_class("connection refused\n") is None


def test_write_exit_result_records_attribution_and_survives_validation(tmp_path: Path) -> None:
    stdout_path = tmp_path / "stdout"
    stderr_path = tmp_path / "stderr"
    stdout_path.write_text(_STAGE_STDOUT)
    stderr_path.write_text('Traceback (most recent call last):\n  File "x.py", line 1\nNameError: boom\n')
    result_path = tmp_path / "result.json"

    evidence.write_exit_result(
        result_path,
        script="e2e_episodic_memory_test.py",
        child_run_id="run.e2e.04",
        exit_code=1,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )
    written = json.loads(result_path.read_text())
    assert written["failure_step_kind"] == "stage"
    assert written["failure_step"].startswith("=== Stage 2:")
    assert written["exception_class"] == "NameError"
    assert "boom" not in result_path.read_text()

    safe = evidence.validate_exit_result(
        written, script="e2e_episodic_memory_test.py", child_run_id="run.e2e.04", exit_code=1
    )
    assert safe["failure_step_kind"] == "stage"
    assert safe["exception_class"] == "NameError"


def test_write_exit_result_uses_later_stage_over_episodic_section_heading(tmp_path: Path) -> None:
    stdout_path = tmp_path / "stdout"
    stdout_path.write_text(_EPISODIC_STAGE3_STDOUT)
    result_path = tmp_path / "result.json"

    evidence.write_exit_result(
        result_path,
        script="e2e_episodic_memory_test.py",
        child_run_id="run.e2e.04",
        exit_code=1,
        stdout_path=stdout_path,
    )

    written = json.loads(result_path.read_text())
    assert written["failure_step_kind"] == "stage"
    assert written["failure_step"] == "=== Stage 3: STM Boost Validation ==="


def test_write_exit_result_without_streams_records_nulls_not_guesses(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    evidence.write_exit_result(
        result_path, script="e2e_cognitive_recall_test.py", child_run_id="run.e2e.05", exit_code=0
    )
    written = json.loads(result_path.read_text())
    assert written["failure_step"] is None
    assert written["failure_step_kind"] is None
    assert written["exception_class"] is None


def test_a_legacy_exit_result_without_attribution_still_validates() -> None:
    # Plan 33's committed manifests carry the three-field safe result and must
    # keep validating; nothing in this stage may invalidate frozen evidence.
    legacy = {
        "schema_version": 1,
        "kind": "neocortex-e2e-exit-result",
        "script": "e2e_cognitive_recall_test.py",
        "child_run_id": "run.e2e.05",
        "status": "FAIL",
        "exit_code": 1,
        "reason": "exit_status_only",
    }
    safe = evidence.validate_exit_result(
        legacy, script="e2e_cognitive_recall_test.py", child_run_id="run.e2e.05", exit_code=1
    )
    assert safe == {"status": "FAIL", "exit_code": 1, "reason": "exit_status_only"}


def test_an_unsafe_attribution_field_is_rejected() -> None:
    tainted = {
        "schema_version": 1,
        "kind": "neocortex-e2e-exit-result",
        "script": "e2e_cognitive_recall_test.py",
        "child_run_id": "run.e2e.05",
        "status": "FAIL",
        "exit_code": 1,
        "reason": "exit_status_only",
        "failure_step": "x" * 121,
        "failure_step_kind": "step",
        "exception_class": None,
    }
    with pytest.raises(evidence.EvidenceError, match="attribution field is unsafe"):
        evidence.validate_exit_result(
            tainted, script="e2e_cognitive_recall_test.py", child_run_id="run.e2e.05", exit_code=1
        )
