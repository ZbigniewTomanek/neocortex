"""Privacy-safe skip-event export: selection, refusal, and the unavailable rule.

Every case here exists to make one specific wrong implementation fail.  No
database and no model endpoint is touched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from scripts import compute_metrics  # ty: ignore[unresolved-import]
from scripts import export_skip_events as exporter  # ty: ignore[unresolved-import]

ROOT = Path(__file__).parents[2]
SCHEMA_PATH = ROOT / "docs/plans/34-qwen-thinking-benchmark/resources/skip-events.schema.json"
RUN_ID = "20260911T001509Z-swift3"
OTHER_RUN_ID = "20260910T231754Z-swift2"


def _record(event: str, extra: dict[str, Any], *, timestamp: str = "2026-09-11 02:37:19.568393+02:00") -> str:
    return json.dumps(
        {
            "text": f"{event}\n",
            "record": {
                "message": event,
                "level": {"name": "WARNING"},
                "extra": {"action_log": True, **extra},
                "time": {"repr": timestamp, "timestamp": 1789087039.568393},
            },
        }
    )


def _missing_node(run_id: str, *, episode_id: int = 7, extra: dict[str, Any] | None = None) -> str:
    return _record(
        "edge_skipped_missing_node",
        {
            "stage": "librarian_agent",
            "agent": "librarian",
            "agent_id": "admin",
            "episode_id": episode_id,
            "correlation_id": "c-0001",
            "model": "qwen3.8-flash-next",
            "endpoint": "http://127.0.0.1:24000/v1",
            "effort": "false",
            "run_id": run_id,
            "source_id": 11,
            "target_id": None,
            "source_present": True,
            "target_present": False,
            "reason_code": "missing_node",
            **(extra or {}),
        },
    )


def _temporal_pair(run_id: str, *, source_id: int = 21, target_id: int = 22) -> str:
    return _record(
        "edge_skipped_temporal_pair",
        {
            "stage": "librarian_agent",
            "agent": "librarian",
            "agent_id": "admin",
            "episode_id": 8,
            "correlation_id": "c-0002",
            "model": "qwen3.8-flash-next",
            "endpoint": "http://127.0.0.1:24000/v1",
            "effort": "false",
            "run_id": run_id,
            "source_id": source_id,
            "target_id": target_id,
            "reason_code": "temporal_pair",
        },
    )


@pytest.fixture
def audit_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the shared log discovery at a fixture directory."""
    directory = tmp_path / "log"
    directory.mkdir()
    monkeypatch.setattr(compute_metrics, "ROOT", tmp_path)

    def _write(lines: list[str]) -> Path:
        path = directory / "agent_actions.log"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    return _write


def _validate_schema(document: dict[str, Any]) -> None:
    schema = json.loads(SCHEMA_PATH.read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(document)


def test_selection_is_run_scoped_and_counts_both_reason_codes(audit_log, tmp_path: Path) -> None:
    audit_log(
        [
            _missing_node(RUN_ID, episode_id=1),
            _missing_node(RUN_ID, episode_id=2),
            _temporal_pair(RUN_ID),
            # A different run's skips must never reach this artifact.
            _missing_node(OTHER_RUN_ID, episode_id=3),
            _temporal_pair(OTHER_RUN_ID, source_id=90, target_id=91),
            _missing_node(RUN_ID, episode_id=4),
            _temporal_pair(RUN_ID, source_id=31, target_id=32),
            # An unrelated event must not be selected at all.
            _record("model_request_completed", {"run_id": RUN_ID}),
        ]
    )
    output = tmp_path / "skip-events.json"
    document = exporter.export(run_id=RUN_ID, arm="tuned", output=output)

    assert document["status"] == "MEASURED"
    assert document["counts"] == {"missing_node": 3, "temporal_pair": 2}
    assert len(document["events"]) == 5
    assert [row["episode_id"] for row in document["events"] if row["reason_code"] == "missing_node"] == [1, 2, 4]
    assert json.loads(output.read_text()) == document
    _validate_schema(document)


def test_only_allowlisted_fields_are_written(audit_log, tmp_path: Path) -> None:
    audit_log([_missing_node(RUN_ID), _temporal_pair(RUN_ID)])
    document = exporter.export(run_id=RUN_ID, arm="tuned", output=tmp_path / "skip-events.json")

    missing, temporal = document["events"]
    assert set(missing) <= set(exporter.ALLOWED_EVENT_FIELDS)
    assert set(temporal) <= set(exporter.ALLOWED_EVENT_FIELDS)
    # ``agent_id``, ``model``, ``endpoint`` and ``effort`` are in the source
    # record and must not be copied out of it.
    assert "agent_id" not in missing and "model" not in missing
    # The temporal event logs no presence flags; they stay null rather than
    # being synthesised as ``true``.
    assert temporal["source_present"] is None and temporal["target_present"] is None
    assert temporal["survived"] is None
    # Only a temporal pair can survive, so a missing-node row has no such key.
    assert "survived" not in missing


def test_an_event_carrying_a_name_field_is_refused(audit_log, tmp_path: Path) -> None:
    audit_log([_missing_node(RUN_ID, extra={"source_name": "Weber"})])
    output = tmp_path / "skip-events.json"
    with pytest.raises(exporter.SkipEventError, match="source_name"):
        exporter.export(run_id=RUN_ID, arm="tuned", output=output)
    assert not output.exists()


def test_a_refusal_message_never_repeats_the_offending_value(audit_log, tmp_path: Path) -> None:
    audit_log([_missing_node(RUN_ID, extra={"entity_description": "a confidential project code name"})])
    with pytest.raises(exporter.SkipEventError) as caught:
        exporter.export(run_id=RUN_ID, arm="tuned", output=tmp_path / "skip-events.json")
    assert "confidential" not in str(caught.value)


def test_a_long_unlisted_string_is_refused(audit_log, tmp_path: Path) -> None:
    audit_log([_missing_node(RUN_ID, extra={"note": "x" * 41})])
    with pytest.raises(exporter.SkipEventError, match="note"):
        exporter.export(run_id=RUN_ID, arm="tuned", output=tmp_path / "skip-events.json")


def test_an_all_unavailable_selection_is_not_measured_rather_than_empty(audit_log, tmp_path: Path) -> None:
    audit_log([_missing_node("unavailable"), _temporal_pair("unavailable")])
    document = exporter.export(run_id=RUN_ID, arm="tuned", output=tmp_path / "skip-events.json")

    assert document["status"] == "NOT MEASURED"
    assert document["reason"] == "run_id_unavailable"
    assert "events" not in document and "counts" not in document
    _validate_schema(document)


def test_a_run_with_no_skips_is_a_measured_zero(audit_log, tmp_path: Path) -> None:
    audit_log([_record("model_request_completed", {"run_id": RUN_ID})])
    document = exporter.export(run_id=RUN_ID, arm="tuned", output=tmp_path / "skip-events.json")

    # Zero skips and unattributable skips are different answers.
    assert document["status"] == "MEASURED"
    assert document["counts"] == {"missing_node": 0, "temporal_pair": 0}
    assert document["events"] == []
    _validate_schema(document)


def test_a_mismatched_reason_code_is_refused(audit_log, tmp_path: Path) -> None:
    audit_log([_record("edge_skipped_temporal_pair", {"run_id": RUN_ID, "reason_code": "missing_node"})])
    with pytest.raises(exporter.SkipEventError, match="reason_code"):
        exporter.export(run_id=RUN_ID, arm="tuned", output=tmp_path / "skip-events.json")


# ── Consistency fields in compute_metrics ──


def _measured(events: list[dict[str, Any]], *, run_id: str = RUN_ID) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "neocortex-skip-events",
        "status": "MEASURED",
        "run_id": run_id,
        "counts": {
            "missing_node": sum(row.get("reason_code") == "missing_node" for row in events),
            "temporal_pair": sum(row.get("reason_code") == "temporal_pair" for row in events),
        },
        "events": events,
    }


def _measured_audit(counts: dict[str, int], *, run_id: str = RUN_ID) -> dict[str, Any]:
    return {"status": "MEASURED", "run_id": run_id, "audit_event_counts": counts}


def test_consistency_is_true_only_when_exported_and_aggregate_counts_agree() -> None:
    document = _measured(
        [
            {"reason_code": "missing_node"},
            {"reason_code": "missing_node"},
            {"reason_code": "temporal_pair", "survived": True},
        ]
    )
    audit = _measured_audit({"edge_skipped_missing_node": 2, "edge_skipped_temporal_pair": 1})
    assert compute_metrics.skip_event_consistency(document, audit)["skip_events_consistent"] == {
        "missing_node": True,
        "temporal_pair": True,
    }

    audit_off = _measured_audit({"edge_skipped_missing_node": 3, "edge_skipped_temporal_pair": 1})
    assert compute_metrics.skip_event_consistency(document, audit_off)["skip_events_consistent"] == {
        "missing_node": False,
        "temporal_pair": True,
    }


def test_a_missing_aggregate_key_agrees_only_with_zero_exported_rows() -> None:
    empty = compute_metrics.skip_event_consistency(_measured([]), _measured_audit({}))
    assert empty["skip_events_consistent"] == {"missing_node": True, "temporal_pair": True}

    populated = compute_metrics.skip_event_consistency(
        _measured([{"reason_code": "missing_node"}]), _measured_audit({})
    )
    assert populated["skip_events_consistent"]["missing_node"] is False


def test_temporal_survival_separates_survived_from_unresolved() -> None:
    document = _measured(
        [
            {"reason_code": "temporal_pair", "survived": True},
            {"reason_code": "temporal_pair", "survived": False},
            {"reason_code": "temporal_pair", "survived": None},
            {"reason_code": "missing_node"},
        ]
    )
    survival = compute_metrics.skip_event_consistency(document, _measured_audit({}))["temporal_survived"]
    assert survival == {"total": 3, "survived": 1, "unresolved": 1}


def test_an_unattributable_export_never_becomes_a_boolean() -> None:
    document = {"schema_version": 1, "status": "NOT MEASURED", "reason": "run_id_unavailable"}
    result = compute_metrics.skip_event_consistency(document, _measured_audit({}))
    assert result["skip_events_consistent"] == {"missing_node": "NOT MEASURED", "temporal_pair": "NOT MEASURED"}
    assert result["temporal_survived"] == "NOT MEASURED"


@pytest.mark.parametrize(
    "audit",
    [
        {"status": "NOT_MEASURED", "run_id": RUN_ID, "audit_event_counts": {}},
        {"status": "MEASURED", "run_id": OTHER_RUN_ID, "audit_event_counts": {}},
        {"status": "MEASURED", "run_id": RUN_ID},
    ],
)
def test_unmeasured_unrelated_or_malformed_audit_never_certifies_a_zero(audit: dict[str, Any]) -> None:
    result = compute_metrics.skip_event_consistency(_measured([]), audit)
    assert result["skip_events_consistent"] == {
        "missing_node": "NOT MEASURED",
        "temporal_pair": "NOT MEASURED",
    }
    assert result["temporal_survived"] == "NOT MEASURED"


@pytest.mark.parametrize(
    "mutation",
    [
        {"events": None},
        {"counts": None},
        {"counts": {"missing_node": 1, "temporal_pair": 0}},
    ],
)
def test_malformed_or_internally_inconsistent_export_never_certifies_a_zero(mutation: dict[str, Any]) -> None:
    document = {**_measured([]), **mutation}
    result = compute_metrics.skip_event_consistency(document, _measured_audit({}))
    assert result["skip_events_consistent"] == {
        "missing_node": "NOT MEASURED",
        "temporal_pair": "NOT MEASURED",
    }
    assert result["temporal_survived"] == "NOT MEASURED"
