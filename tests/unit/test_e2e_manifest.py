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


def test_build_and_offline_merge_are_run_scoped_atomic_and_private(
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
    merged = evidence.merge_manifest(
        manifest_path=fixture["output"],
        metrics_path=fixture["metrics"],
        run_id=fixture["run_id"],
        snapshot_path=fixture["snapshot"],
        snapshot_sha256=fixture["snapshot_digest"],
    )
    assert merged["e2e_manifest"]["run_id"] == fixture["run_id"]
    assert "e2e_manifest" in json.loads(fixture["metrics"].read_text())
    assert not list(fixture["metrics"].parent.glob(".metrics-arm.json.*.tmp"))


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
