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


def _measured_sample(snapshot: dict) -> dict:
    nodes = [
        {
            "id": index,
            "type": "Concept",
            "name": {"kind": "opaque_id", "value": index},
            "source_episode_key": "E02",
            "source_job_id": 1,
        }
        for index in range(1, 21)
    ]
    edges = [
        {
            "id": 100 + index,
            "type": "RELATES_TO",
            "source_node_id": index,
            "target_node_id": index % 20 + 1,
            "source_episode_key": "E02",
            "source_job_id": 1,
        }
        for index in range(1, 21)
    ]
    return {
        "schema_version": 1,
        "status": "MEASURED",
        "snapshot": copy.deepcopy(snapshot),
        "declared_types": {"node": ["Concept"], "edge": ["RELATES_TO"]},
        "nodes": nodes,
        "edges": edges,
        "validator_result": {
            "status": "PASS",
            "node_count": 20,
            "edge_count": 20,
            "invalid_references": 0,
            "invalid_records": 0,
        },
    }


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


def test_f1_forged_per_episode_count_and_evidence_are_rejected(tmp_path: Path) -> None:
    _manifest, parsed, _sample, output = _generate(tmp_path)
    parsed["episodes"][0]["ontology"]["proposed"]["node"] = 999
    evidence = next(
        item for item in parsed["episodes"][0]["evidence"] if item["pointer"] == "/episodes/0/ontology/proposed/node"
    )
    evidence.update(status="MEASURED", value=999, source=report.REPORT_SCHEMA)
    evidence.pop("reason")
    _write(output / "qwen-parsing-report.json", parsed)
    with pytest.raises(report.ReportError, match="evidence source mismatch"):
        report.validate_artifacts(
            PLAN,
            output / "qwen-parsing-inputs.json",
            output / "qwen-parsing-report.json",
            output / "quality-sample-qwen-flash-next.json",
        )


def test_f2_measured_top_status_is_rejected_when_inputs_are_unavailable(tmp_path: Path) -> None:
    _manifest, parsed, _sample, output = _generate(tmp_path)
    parsed["status"] = "MEASURED"
    _write(output / "qwen-parsing-report.json", parsed)
    with pytest.raises(report.ReportError, match="report status mismatch"):
        report.validate_artifacts(
            PLAN,
            output / "qwen-parsing-inputs.json",
            output / "qwen-parsing-report.json",
            output / "quality-sample-qwen-flash-next.json",
        )


def test_f3_complete_run_object_is_bound_to_canonical_sources(tmp_path: Path) -> None:
    _manifest, parsed, _sample, output = _generate(tmp_path)
    parsed["run"]["corpus_path"] = "docs/plans/33-local-qwen-migration/resources/compact-corpus-design.md"
    parsed["run"]["corpus_sha256"] = "a" * 64
    _write(output / "qwen-parsing-report.json", parsed)
    with pytest.raises(report.ReportError, match="report run mismatch"):
        report.validate_artifacts(
            PLAN,
            output / "qwen-parsing-inputs.json",
            output / "qwen-parsing-report.json",
            output / "quality-sample-qwen-flash-next.json",
        )


def test_f4_measured_sample_requires_available_digest_verified_graph_export(tmp_path: Path) -> None:
    _manifest, _parsed, sample, output = _generate(tmp_path)
    _write(output / "quality-sample-qwen-flash-next.json", _measured_sample(sample["snapshot"]))
    with pytest.raises(report.ReportError, match="measured sample requires an available graph export"):
        report.validate_artifacts(
            PLAN,
            output / "qwen-parsing-inputs.json",
            output / "qwen-parsing-report.json",
            output / "quality-sample-qwen-flash-next.json",
        )


def test_measured_sample_records_must_match_digest_verified_graph_export(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "snapshot.bin"
    snapshot_path.write_bytes(b"safe aggregate snapshot digest fixture")
    snapshot = {"path": snapshot_path.name, "sha256": report._digest(snapshot_path)}
    sample = _measured_sample(snapshot)
    graph_export = {
        "schema_version": 1,
        "status": "MEASURED",
        "snapshot_sha256": snapshot["sha256"],
        "declared_types": copy.deepcopy(sample["declared_types"]),
        "nodes": copy.deepcopy(sample["nodes"]),
        "edges": copy.deepcopy(sample["edges"]),
    }
    graph_path = tmp_path / "graph-export.json"
    _write(graph_path, graph_export)
    manifest = {
        "artifacts": [
            {
                "kind": "graph_export",
                "path": graph_path.name,
                "sha256": report._digest(graph_path),
                "availability": "MEASURED",
            }
        ]
    }
    sample["nodes"][0]["name"]["value"] = 999
    schema = json.loads((PLAN / "resources/quality-sample-qwen-flash-next.schema.json").read_text())
    with pytest.raises(report.ReportError, match="sample node does not match the graph export"):
        report._validate_sample(tmp_path, sample, schema, manifest)


def test_f5_unapproved_reason_is_rejected(tmp_path: Path) -> None:
    _manifest, parsed, _sample, output = _generate(tmp_path)
    missing = next(item for item in parsed["episodes"][0]["evidence"] if item["status"] == "NOT_MEASURED")
    missing["reason"] = "episode_text: private"
    _write(output / "qwen-parsing-report.json", parsed)
    with pytest.raises(report.ReportError, match="report schema validation failed"):
        report.validate_artifacts(
            PLAN,
            output / "qwen-parsing-inputs.json",
            output / "qwen-parsing-report.json",
            output / "quality-sample-qwen-flash-next.json",
        )


def test_f5_noncanonical_markdown_with_forbidden_label_is_rejected(tmp_path: Path) -> None:
    _manifest, _parsed, _sample, output = _generate(tmp_path)
    markdown = output / "qwen-parsing-report.md"
    markdown.write_text(markdown.read_text() + "\nepisode_text: private\n")
    with pytest.raises(report.ReportError, match="privacy scan failed"):
        report.privacy_scan(
            [
                output / "qwen-parsing-inputs.json",
                output / "qwen-parsing-report.json",
                markdown,
                output / "quality-sample-qwen-flash-next.json",
                PLAN / "resources/bakeoff-comparison.md",
            ],
            tmp_path / "privacy.json",
        )


def test_f6_comparison_requires_each_of_four_agents_once_with_hold(tmp_path: Path) -> None:
    _manifest, _parsed, _sample, output = _generate(tmp_path)
    source = PLAN / "resources/bakeoff-comparison.md"
    comparison = tmp_path / "bakeoff-comparison.md"
    comparison.write_text(source.read_text().replace("| Domain classifier | HOLD |", "| Ontology | HOLD |"))
    with pytest.raises(report.ReportError, match="privacy scan failed"):
        report.privacy_scan(
            [
                output / "qwen-parsing-inputs.json",
                output / "qwen-parsing-report.json",
                output / "qwen-parsing-report.md",
                output / "quality-sample-qwen-flash-next.json",
                comparison,
            ],
            tmp_path / "privacy.json",
        )


def test_f8_hidden_rows_and_decorated_visible_verdicts_are_rejected(tmp_path: Path) -> None:
    _manifest, _parsed, _sample, output = _generate(tmp_path)
    source = PLAN / "resources/bakeoff-comparison.md"
    text = source.read_text().replace(" | HOLD |", " | `HOLD` |")
    text = text.replace("| Domain classifier | `HOLD` |", "| Ontology | `HOLD` |")
    text += """
<!--
| Ontology | HOLD |
| Extractor | HOLD |
| Librarian | HOLD |
| Domain classifier | HOLD |
-->
"""
    counts = report._verdict_table_counts(text)
    assert counts["comparison_html_comment_markers"] == 2
    assert counts["comparison_invalid_verdict_cells"] == 4
    assert counts["comparison_duplicate_agents"] == 1
    assert counts["comparison_missing_agents"] == 1
    assert counts["comparison_outside_verdict_rows"] == 4

    comparison = tmp_path / "bakeoff-comparison.md"
    comparison.write_text(text)
    with pytest.raises(report.ReportError, match="privacy scan failed"):
        report.privacy_scan(
            [
                output / "qwen-parsing-inputs.json",
                output / "qwen-parsing-report.json",
                output / "qwen-parsing-report.md",
                output / "quality-sample-qwen-flash-next.json",
                comparison,
            ],
            tmp_path / "privacy.json",
        )


def test_f8_extra_visible_verdict_row_is_rejected() -> None:
    text = (PLAN / "resources/bakeoff-comparison.md").read_text()
    ontology_row = next(line for line in text.splitlines() if line.startswith("| Ontology | HOLD |"))
    text = text.replace(ontology_row, f"{ontology_row}\n{ontology_row}", 1)
    counts = report._verdict_table_counts(text)
    assert counts["comparison_agent_rows"] == 5
    assert counts["comparison_extra_rows"] == 1
    assert counts["comparison_duplicate_agents"] == 1


def test_f7_evidence_cannot_be_moved_between_episode_arrays(tmp_path: Path) -> None:
    _manifest, parsed, _sample, output = _generate(tmp_path)
    moved = parsed["episodes"][0]["evidence"].pop()
    parsed["episodes"][1]["evidence"].append(moved)
    _write(output / "qwen-parsing-report.json", parsed)
    with pytest.raises(report.ReportError, match="evidence pointer belongs to another episode"):
        report.validate_artifacts(
            PLAN,
            output / "qwen-parsing-inputs.json",
            output / "qwen-parsing-report.json",
            output / "quality-sample-qwen-flash-next.json",
        )


# ── Run-id / arm parametrization and the Stage 2 exports ──

_STANDIN_SKIP_EVENTS = "docs/plans/34-qwen-thinking-benchmark/resources/skip-events.schema.json"
_STANDIN_GRAPH_SAMPLE = "docs/plans/34-qwen-thinking-benchmark/resources/quality-sample-tuned.schema.json"


def test_explicit_default_run_and_arm_reproduce_the_implicit_output(tmp_path: Path) -> None:
    implicit = tmp_path / "implicit"
    explicit = tmp_path / "explicit"
    report.generate(PLAN, implicit)
    report.generate(PLAN, explicit, run_id=report.RUN_ID, arm=report.ARM)
    for filename in report.OUTPUT_FILES:
        assert (implicit / filename).read_bytes() == (explicit / filename).read_bytes()


def test_a_non_default_run_and_arm_resolve_their_own_source_paths() -> None:
    metrics, e2e, recall = report._sources_for("20260912T000000Z-tuned", "qwen-flash-next-compact-tuned")
    assert metrics.endswith("metrics-qwen-flash-next-compact-tuned.json")
    assert e2e.endswith("e2e-manifest-qwen-flash-next-compact-tuned-20260912T000000Z-tuned.json")
    assert recall.endswith("recall-results-qwen-flash-next-compact-tuned-20260912T000000Z-tuned.json")
    # The defaults are unchanged, so every existing invocation still resolves
    # the swift3 artifacts.
    assert report._sources_for(report.RUN_ID, report.ARM) == (
        report.METRICS_PATH,
        report.E2E_PATH,
        report.RECALL_PATH,
    )


def test_exports_are_discovered_only_when_both_are_present(tmp_path: Path) -> None:
    output = tmp_path / "resources"
    output.mkdir()
    run_id, arm = "run-1", "arm-1"
    skip = output / f"skip-events-{arm}-{run_id}.json"
    sample = output / f"quality-sample-{arm}-{run_id}.json"

    assert report.find_exports(tmp_path, output, run_id, arm) == {}
    skip.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "neocortex-skip-events",
                "run_id": run_id,
                "arm": arm,
                "status": "MEASURED",
            }
        )
    )
    # One without the other would mix two evidence generations in one report.
    assert report.find_exports(tmp_path, output, run_id, arm) == {}
    sample.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "neocortex-graph-sample",
                "run_id": run_id,
                "arm": arm,
                "status": "MEASURED",
            }
        )
    )
    assert report.find_exports(tmp_path, output, run_id, arm) == {
        "audit_log": f"resources/skip-events-{arm}-{run_id}.json",
        "graph_export": f"resources/quality-sample-{arm}-{run_id}.json",
    }


def test_an_export_outside_the_repository_is_refused(tmp_path: Path) -> None:
    output = tmp_path / "outside"
    output.mkdir()
    (output / "skip-events-a-r.json").write_text(
        json.dumps({"kind": "neocortex-skip-events", "run_id": "r", "arm": "a", "status": "MEASURED"})
    )
    (output / "quality-sample-a-r.json").write_text(
        json.dumps({"kind": "neocortex-graph-sample", "run_id": "r", "arm": "a", "status": "MEASURED"})
    )
    with pytest.raises(report.ReportError, match="outside the repository"):
        report.find_exports(tmp_path / "elsewhere", output, "r", "a")


@pytest.mark.parametrize("field", ["run_id", "arm", "status"])
def test_export_identity_or_measurement_mismatch_is_rejected(tmp_path: Path, field: str) -> None:
    output = tmp_path / "resources"
    output.mkdir()
    skip = {"kind": "neocortex-skip-events", "run_id": "r", "arm": "a", "status": "MEASURED"}
    sample = {"kind": "neocortex-graph-sample", "run_id": "r", "arm": "a", "status": "MEASURED"}
    if field == "status":
        skip[field] = "NOT MEASURED"
    else:
        skip[field] = "other"
    (output / "skip-events-a-r.json").write_text(json.dumps(skip))
    (output / "quality-sample-a-r.json").write_text(json.dumps(sample))
    with pytest.raises(report.ReportError, match=f"audit_log export {field.replace('_', ' ')} mismatch"):
        report.find_exports(tmp_path, output, "r", "a")


def test_present_exports_replace_the_audit_and_graph_not_measured_reasons(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exports = {"audit_log": _STANDIN_SKIP_EVENTS, "graph_export": _STANDIN_GRAPH_SAMPLE}
    monkeypatch.setattr(report, "find_exports", lambda *_args, **_kwargs: dict(exports))
    output = tmp_path / "generated"
    result = report.generate(PLAN, output)
    assert result["status"] == "PASS"

    manifest = json.loads((output / "qwen-parsing-inputs.json").read_text())
    by_kind = {item["kind"]: item for item in manifest["artifacts"]}
    for kind, path in (("audit_log", _STANDIN_SKIP_EVENTS), ("graph_export", _STANDIN_GRAPH_SAMPLE)):
        assert by_kind[kind]["availability"] == "MEASURED"
        assert by_kind[kind]["path"] == path
        assert "reason" not in by_kind[kind]
    assert report.REASON_AUDIT not in (output / "qwen-parsing-inputs.json").read_text()
    assert report.REASON_GRAPH not in (output / "qwen-parsing-inputs.json").read_text()

    parsed = json.loads((output / "qwen-parsing-report.json").read_text())
    sources = {item["source"] for row in parsed["episodes"] for item in row["evidence"]}
    assert _STANDIN_SKIP_EVENTS in sources and _STANDIN_GRAPH_SAMPLE in sources
    assert report.MISSING_GRAPH_PATH not in sources
    # admin_jobs is still unavailable, so no export may flip the report to
    # MEASURED, and no per-episode leaf became measured: neither export carries
    # a corpus episode key.
    assert parsed["status"] == "NOT_MEASURED"
    from_exports = [
        item
        for row in parsed["episodes"]
        for item in row["evidence"]
        if item["source"] in {_STANDIN_SKIP_EVENTS, _STANDIN_GRAPH_SAMPLE}
    ]
    assert from_exports
    assert all(item["status"] == "NOT_MEASURED" for item in from_exports)
    assert all(item["reason"] == report.REASON_PER_EPISODE for item in from_exports)


def test_tuned_generation_preserves_mixed_efforts_and_existing_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "20260913T120000Z-tuned1"
    arm = "qwen-flash-next-compact-tuned"
    root = tmp_path
    output = root / "docs/plans/33-local-qwen-migration/resources"
    output.mkdir(parents=True)
    corpus = root / report.CORPUS_PATH
    corpus.parent.mkdir(parents=True, exist_ok=True)
    corpus.write_text("safe compact fixture")
    snapshot = root / "backups/tuned-snapshot.tar.gz"
    snapshot.parent.mkdir()
    snapshot.write_bytes(b"snapshot")
    for reference in (report.TUNED_REPORT_SCHEMA, report.TUNED_SAMPLE_SCHEMA):
        copied_schema = root / reference
        copied_schema.parent.mkdir(parents=True, exist_ok=True)
        copied_schema.write_bytes((ROOT / reference).read_bytes())
    efforts = {"ontology": "low", "extractor": "medium", "librarian": "off", "domain_classifier": "high"}
    metrics = {
        "arm": arm,
        "run_metadata": {
            "run_id": run_id,
            "corpus_profile": "compact",
            "corpus_episode_ids": list(report.EPISODE_IDS),
            "corpus_size": len(report.EPISODE_IDS),
            "corpus_sha256": report._digest(corpus),
            "source_revision": "e" * 40,
            "source_paths": {
                "corpus": report.CORPUS_PATH,
                "graph_snapshot": "backups/tuned-snapshot.tar.gz",
                "graph_snapshot_sha256": report._digest(snapshot),
            },
            "snapshot_sha256": report._digest(snapshot),
            "model_ids": {name: f"local:{report.MODEL}" for name in report.AGENT_NAMES},
            "efforts": efforts,
        },
    }
    metrics_path, e2e_path, recall_path = report._sources_for(run_id, arm)
    for relative, value in (
        (metrics_path, metrics),
        (e2e_path, {"fixture": "e2e"}),
        (recall_path, {"fixture": "recall"}),
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        _write(path, value)

    skip_path = output / f"skip-events-{arm}-{run_id}.json"
    _write(
        skip_path,
        {
            "schema_version": 1,
            "kind": "neocortex-skip-events",
            "run_id": run_id,
            "arm": arm,
            "status": "MEASURED",
            "counts": {"missing_node": 0, "temporal_pair": 0},
            "events": [],
        },
    )
    sample_path = output / f"quality-sample-{arm}-{run_id}.json"
    _write(
        sample_path,
        {
            "schema_version": 1,
            "kind": "neocortex-graph-sample",
            "run_id": run_id,
            "arm": arm,
            "status": "MEASURED",
            "schema_source": "metrics",
            "schemas": [],
            "requested": 20,
            "nodes": {"count": 0, "sampled": 0, "shortfall": True, "rows": []},
            "edges": {"count": 0, "sampled": 0, "shortfall": True, "rows": []},
        },
    )
    original_sample = sample_path.read_bytes()
    monkeypatch.setattr(report, "_load_sources", lambda *_args, **_kwargs: (root, metrics, {}, {}))

    result = report.generate(PLAN, output, run_id=run_id, arm=arm)
    names = report.output_files(run_id, arm, graph_sample_present=True)
    assert result["status"] == "PASS"
    assert sample_path.read_bytes() == original_sample
    assert all((output / name).is_file() for name in names)
    assert not (output / "qwen-parsing-report.json").exists()
    parsed = json.loads((output / names[1]).read_text())
    assert parsed["run"]["efforts"] == efforts
    assert all(row["run_provenance"]["efforts"] == efforts for row in parsed["episodes"])


def test_normalized_ontology_type_names_are_an_explicit_privacy_exemption() -> None:
    values = [b'{"edge_types_after":{"RELATES_TO":2,"CORRECTS":1}}']
    assert not any(report._privacy_counts(values).values())


def test_absent_exports_keep_todays_not_measured_reasons(tmp_path: Path) -> None:
    _manifest, parsed, _sample, output = _generate(tmp_path)
    del parsed
    manifest = json.loads((output / "qwen-parsing-inputs.json").read_text())
    by_kind = {item["kind"]: item for item in manifest["artifacts"]}
    assert by_kind["audit_log"] == {
        "kind": "audit_log",
        "path": "log/agent_actions.log",
        "sha256": "NOT_MEASURED",
        "availability": "NOT_MEASURED",
        "reason": report.REASON_AUDIT,
    }
    assert by_kind["graph_export"]["reason"] == report.REASON_GRAPH
