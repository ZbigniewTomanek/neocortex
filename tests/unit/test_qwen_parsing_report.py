"""Deterministic, fail-closed tests for the Stage 7 parsing report."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).parents[2]
PLAN = ROOT / "docs/plans/33-local-qwen-migration"
SCRIPT = ROOT / "scripts/generate_qwen_parsing_report.py"
SPEC = importlib.util.spec_from_file_location("generate_qwen_parsing_report", SCRIPT)
assert SPEC and SPEC.loader
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)


def _generate(tmp_path: Path) -> tuple[dict, dict, dict, Path]:
    output = tmp_path / "generated"
    report.generate(PLAN, output)
    manifest = json.loads((output / "qwen-parsing-inputs.json").read_text())
    parsed = json.loads((output / "qwen-parsing-report.json").read_text())
    sample = json.loads((output / "quality-sample-qwen-flash-next.json").read_text())
    return manifest, parsed, sample, output


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


def test_happy_path_generation_and_exact_episode_membership(tmp_path: Path) -> None:
    manifest, parsed, sample, output = _generate(tmp_path)
    result = report.validate_artifacts(
        PLAN,
        output / "qwen-parsing-inputs.json",
        output / "qwen-parsing-report.json",
        output / "quality-sample-qwen-flash-next.json",
    )
    assert result["status"] == "PASS"
    assert [row["episode_key"] for row in parsed["episodes"]] == list(report.EPISODE_KEYS)
    assert len(manifest["artifacts"]) == 8
    assert sample["status"] == "NOT_MEASURED"


def test_missing_required_source_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(report, "METRICS_PATH", "docs/plans/33-local-qwen-migration/resources/missing-metrics.json")
    with pytest.raises(report.ReportError, match="required source is missing"):
        report.generate(PLAN, tmp_path)


def test_digest_mismatch_is_rejected(tmp_path: Path) -> None:
    manifest, _parsed, _sample, output = _generate(tmp_path)
    manifest["artifacts"][0]["sha256"] = "0" * 64
    _write(output / "qwen-parsing-inputs.json", manifest)
    with pytest.raises(report.ReportError, match="digest mismatch"):
        report.validate_artifacts(
            PLAN,
            output / "qwen-parsing-inputs.json",
            output / "qwen-parsing-report.json",
            output / "quality-sample-qwen-flash-next.json",
        )


def test_run_mismatch_is_rejected(tmp_path: Path) -> None:
    _manifest, parsed, _sample, output = _generate(tmp_path)
    parsed["run"]["run_id"] = "different-run"
    _write(output / "qwen-parsing-report.json", parsed)
    with pytest.raises(report.ReportError, match="report schema validation failed"):
        report.validate_artifacts(
            PLAN,
            output / "qwen-parsing-inputs.json",
            output / "qwen-parsing-report.json",
            output / "quality-sample-qwen-flash-next.json",
        )


@pytest.mark.parametrize(
    ("mutation", "message"), [("run", "E2E run id mismatch"), ("digest", "E2E metrics digest mismatch")]
)
def test_source_artifact_run_and_digest_mismatches_are_rejected(
    monkeypatch: pytest.MonkeyPatch, mutation: str, message: str
) -> None:
    metrics = {
        "arm": report.ARM,
        "run_metadata": {
            "run_id": report.RUN_ID,
            "corpus_profile": "compact",
            "corpus_episode_ids": list(report.EPISODE_IDS),
            "corpus_size": len(report.EPISODE_IDS),
            "corpus_sha256": "b" * 64,
            "source_revision": "e" * 40,
            "source_paths": {
                "corpus": report.CORPUS_PATH,
                "graph_snapshot": "backups/snapshot.tar.gz",
                "graph_snapshot_sha256": "a" * 64,
            },
            "snapshot_sha256": "a" * 64,
            "model_ids": {name: f"local:{report.MODEL}" for name in report.AGENT_NAMES},
            "efforts": {name: report.EFFORT for name in report.AGENT_NAMES},
        },
    }
    e2e = {
        "run_id": "other" if mutation == "run" else report.RUN_ID,
        "arm": report.ARM,
        "status": "MEASURED",
        "corpus_metrics": {"path": report.METRICS_PATH, "sha256": "x" * 64 if mutation == "digest" else "c" * 64},
        "post_snapshot": {"path": "backups/snapshot.tar.gz", "sha256": "a" * 64},
        "recall": {"path": report.RECALL_PATH, "sha256": "d" * 64},
        "e2e": {"total": 5},
    }
    recall = {"run_id": report.RUN_ID, "status": "MEASURED", "query_set": {"corpus_profile": "compact"}}

    def fake_read(path: Path) -> dict:
        if path.name.startswith("metrics-"):
            return metrics
        if path.name.startswith("e2e-manifest-"):
            return e2e
        return recall

    def fake_digest(path: Path) -> str:
        if path.name == "compact-corpus.md":
            return "b" * 64
        if path.name.startswith("metrics-"):
            return "c" * 64
        if path.name.startswith("recall-results-"):
            return "d" * 64
        return "a" * 64

    monkeypatch.setattr(report, "_read_json", fake_read)
    monkeypatch.setattr(report, "_digest", fake_digest)
    with pytest.raises(report.ReportError, match=message):
        report._load_sources(PLAN)


@pytest.mark.parametrize("missing", ["pointer", "status", "value", "source"])
def test_missing_evidence_metadata_is_rejected(tmp_path: Path, missing: str) -> None:
    _manifest, parsed, _sample, output = _generate(tmp_path)
    parsed["episodes"][0]["evidence"][0].pop(missing)
    _write(output / "qwen-parsing-report.json", parsed)
    with pytest.raises(report.ReportError, match="report schema validation failed"):
        report.validate_artifacts(
            PLAN,
            output / "qwen-parsing-inputs.json",
            output / "qwen-parsing-report.json",
            output / "quality-sample-qwen-flash-next.json",
        )


def test_evidence_value_mismatch_is_rejected(tmp_path: Path) -> None:
    _manifest, parsed, _sample, output = _generate(tmp_path)
    measured = next(item for item in parsed["episodes"][0]["evidence"] if item["status"] == "MEASURED")
    measured["value"] = "routing"
    _write(output / "qwen-parsing-report.json", parsed)
    with pytest.raises(report.ReportError, match="evidence value mismatch"):
        report.validate_artifacts(
            PLAN,
            output / "qwen-parsing-inputs.json",
            output / "qwen-parsing-report.json",
            output / "quality-sample-qwen-flash-next.json",
        )


def test_not_measured_evidence_requires_reason(tmp_path: Path) -> None:
    _manifest, parsed, _sample, output = _generate(tmp_path)
    missing = next(item for item in parsed["episodes"][0]["evidence"] if item["status"] == "NOT_MEASURED")
    missing.pop("reason")
    _write(output / "qwen-parsing-report.json", parsed)
    with pytest.raises(report.ReportError, match="report schema validation failed"):
        report.validate_artifacts(
            PLAN,
            output / "qwen-parsing-inputs.json",
            output / "qwen-parsing-report.json",
            output / "quality-sample-qwen-flash-next.json",
        )


@pytest.mark.parametrize(
    "forbidden",
    ["ncx_shared__private", "person@example.com", "<think>private</think>"],
)
def test_forbidden_text_domain_or_schema_values_are_rejected(tmp_path: Path, forbidden: str) -> None:
    _manifest, parsed, _sample, output = _generate(tmp_path)
    parsed["episodes"][0]["quality_integrity"]["checks"][0]["source"] = forbidden
    evidence = next(
        item
        for item in parsed["episodes"][0]["evidence"]
        if item["pointer"] == "/episodes/0/quality_integrity/checks/0/source"
    )
    evidence["value"] = forbidden
    _write(output / "qwen-parsing-report.json", parsed)
    with pytest.raises(report.ReportError):
        report.validate_artifacts(
            PLAN,
            output / "qwen-parsing-inputs.json",
            output / "qwen-parsing-report.json",
            output / "quality-sample-qwen-flash-next.json",
        )


def test_invented_safe_value_kind_is_rejected() -> None:
    schema = json.loads((PLAN / "resources/qwen-parsing-report-compact.schema.json").read_text())
    validator = Draft202012Validator(schema["$defs"]["safeValue"])
    with pytest.raises(ValidationError):
        validator.validate({"kind": "source_text", "value": "invented"})


def test_dynamic_domain_value_is_rejected(tmp_path: Path) -> None:
    _manifest, parsed, _sample, output = _generate(tmp_path)
    parsed["episodes"][0]["domains"]["accepted"] = "customer_finance"
    _write(output / "qwen-parsing-report.json", parsed)
    with pytest.raises(report.ReportError, match="report schema validation failed"):
        report.validate_artifacts(
            PLAN,
            output / "qwen-parsing-inputs.json",
            output / "qwen-parsing-report.json",
            output / "quality-sample-qwen-flash-next.json",
        )


def test_absent_episode_evidence_is_not_measured_with_reasons(tmp_path: Path) -> None:
    _manifest, parsed, _sample, _output = _generate(tmp_path)
    for row in parsed["episodes"]:
        assert all(job["status"] == "NOT_MEASURED" for job in row["jobs"])
        assert row["domains"] == {"accepted": "NOT_MEASURED", "proposal": "NOT_MEASURED"}
        missing = [item for item in row["evidence"] if item["value"] == "NOT_MEASURED"]
        assert missing
        assert all(item["status"] == "NOT_MEASURED" and item["reason"] for item in missing)


def test_reruns_are_byte_identical(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    report.generate(PLAN, first)
    report.generate(PLAN, second)
    for filename in report.OUTPUT_FILES:
        assert (first / filename).read_bytes() == (second / filename).read_bytes()


def test_corrupt_sample_snapshot_digest_is_rejected(tmp_path: Path) -> None:
    _manifest, _parsed, sample, output = _generate(tmp_path)
    sample["snapshot"]["sha256"] = "0" * 64
    _write(output / "quality-sample-qwen-flash-next.json", sample)
    with pytest.raises(report.ReportError, match="sample snapshot digest mismatch"):
        report.validate_artifacts(
            PLAN,
            output / "qwen-parsing-inputs.json",
            output / "qwen-parsing-report.json",
            output / "quality-sample-qwen-flash-next.json",
        )


def test_not_measured_sample_forbids_record_arrays(tmp_path: Path) -> None:
    _manifest, _parsed, sample, _output = _generate(tmp_path)
    sample["nodes"] = []
    schema = json.loads((PLAN / "resources/quality-sample-qwen-flash-next.schema.json").read_text())
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(sample)


def test_fabricated_measured_sample_status_is_rejected(tmp_path: Path) -> None:
    _manifest, _parsed, sample, _output = _generate(tmp_path)
    sample["status"] = "MEASURED"
    schema = json.loads((PLAN / "resources/quality-sample-qwen-flash-next.schema.json").read_text())
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(sample)


def test_measured_sample_requires_exact_twenty_twenty(tmp_path: Path) -> None:
    _manifest, _parsed, sample, _output = _generate(tmp_path)
    measured = {
        "schema_version": 1,
        "status": "MEASURED",
        "snapshot": copy.deepcopy(sample["snapshot"]),
        "nodes": [],
        "edges": [],
        "validator_result": {
            "status": "PASS",
            "node_count": 20,
            "edge_count": 20,
            "invalid_references": 0,
            "invalid_records": 0,
        },
    }
    schema = json.loads((PLAN / "resources/quality-sample-qwen-flash-next.schema.json").read_text())
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(measured)
