#!/usr/bin/env python3
"""Build and validate privacy-safe, run-scoped bake-off evidence."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "docs/plans/33-local-qwen-migration/resources"
E2E_SCRIPTS = (
    "e2e_extraction_pipeline_test.py",
    "e2e_plan15_scenarios_test.py",
    "e2e_plan17_validation.py",
    "e2e_episodic_memory_test.py",
    "e2e_cognitive_recall_test.py",
)
SCENARIO_GATES = {
    "e2e_plan15_scenarios_test.py": ("PASS", 11),
    "e2e_plan17_validation.py": ("ACCEPTABLE", 13),
}
# The top-level run id is also embedded in manage.sh snapshot names, whose
# contract is exactly [a-zA-Z0-9_-]+.  Child ids append ``.e2e.NN`` only in
# safe, run-scoped result metadata and are not passed to snapshot management.
SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SAFE_STATUSES = frozenset({"PASS", "FAIL", "NOT_MEASURED"})
SAFE_VERDICTS = frozenset({"PASS", "PARTIAL", "ACCEPTABLE", "FAIL"})


class EvidenceError(ValueError):
    """Raised when evidence is missing, malformed, inconsistent, or unsafe."""


def atomic_write_json(destination: Path, payload: dict[str, Any]) -> None:
    """Publish JSON with a same-directory fsync and atomic replacement."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(payload, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, destination)
        temporary_name = None
    finally:
        if temporary_name is not None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary_name)


def sha256_file(path: Path) -> str:
    """Return a file digest without exposing file contents."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_path(path: Path) -> str:
    """Represent only repository-relative evidence paths."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError as exc:
        raise EvidenceError("evidence path is outside the repository") from exc


def _safe_relative_path(value: object, label: str) -> str:
    """Validate a persisted path cannot escape the repository."""
    path_text = _require_string(value, label)
    path = Path(path_text)
    if path.is_absolute() or ".." in path.parts or path_text != path.as_posix():
        raise EvidenceError(f"{label} must be a repository-relative path")
    try:
        (ROOT / path).resolve().relative_to(ROOT.resolve())
    except ValueError as exc:
        raise EvidenceError(f"{label} must be inside the repository") from exc
    return path_text


def _require_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvidenceError(f"{label} must be an object")
    return cast(dict[str, Any], value)


def _require_string(value: object, label: str, *, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or not value:
        raise EvidenceError(f"{label} must be a non-empty string")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise EvidenceError(f"{label} has an invalid safe format")
    return value


def _require_nonnegative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:  # bool is deliberately not an integer here.
        raise EvidenceError(f"{label} must be a non-negative integer")
    return value


def validate_scenario_result(result: object, *, script: str, child_run_id: str, exit_code: int) -> dict[str, Any]:
    """Validate a Plan 15/17 machine result, including every scenario index."""
    data = _require_object(result, "scenario result")
    expected_family, threshold = SCENARIO_GATES[script]
    required = {
        "schema_version",
        "kind",
        "script",
        "child_run_id",
        "status",
        "exit_code",
        "counts",
        "gate",
        "scenarios",
    }
    if set(data) != required:
        raise EvidenceError(f"{script} result fields are incomplete or contain unsafe fields")
    if data["schema_version"] != 1 or data["kind"] != "neocortex-e2e-scenario-result":
        raise EvidenceError(f"{script} result schema is invalid")
    if data["script"] != script or data["child_run_id"] != child_run_id:
        raise EvidenceError(f"{script} result identity does not match its child run")
    result_exit_code = _require_nonnegative_int(data["exit_code"], "scenario exit code")
    if result_exit_code != exit_code or result_exit_code > 255:
        raise EvidenceError(f"{script} result exit status disagrees with the child process")
    status = _require_string(data["status"], "scenario status")
    if status not in {"PASS", "FAIL"}:
        raise EvidenceError(f"{script} scenario status is invalid")

    counts = _require_object(data["counts"], "scenario counts")
    if set(counts) != {"total", "pass", "partial", "acceptable", "fail"}:
        raise EvidenceError(f"{script} scenario counts are incomplete")
    total = _require_nonnegative_int(counts["total"], "scenario total")
    pass_count = _require_nonnegative_int(counts["pass"], "scenario pass count")
    partial_count = _require_nonnegative_int(counts["partial"], "scenario partial count")
    acceptable_count = _require_nonnegative_int(counts["acceptable"], "scenario acceptable count")
    fail_count = _require_nonnegative_int(counts["fail"], "scenario fail count")
    if script.startswith("e2e_plan15"):
        if total != 14 or pass_count + partial_count + fail_count != total:
            raise EvidenceError(f"{script} scenario counts are inconsistent")
        if acceptable_count != pass_count + partial_count:
            raise EvidenceError("Plan 15 acceptable count must equal PASS plus PARTIAL")
        expected_counts = {
            "PASS": pass_count,
            "PARTIAL": partial_count,
            "ACCEPTABLE": 0,
            "FAIL": fail_count,
        }
    else:
        if total != 14 or acceptable_count + partial_count + fail_count != total:
            raise EvidenceError(f"{script} scenario counts are inconsistent")
        if pass_count != 0:
            raise EvidenceError("Plan 17 PASS count must be zero")
        expected_counts = {
            "PASS": 0,
            "PARTIAL": partial_count,
            "ACCEPTABLE": acceptable_count,
            "FAIL": fail_count,
        }

    scenarios = data["scenarios"]
    if not isinstance(scenarios, list) or len(scenarios) != total:
        raise EvidenceError(f"{script} must report exactly {total} scenarios")
    seen: set[int] = set()
    observed = {"PASS": 0, "PARTIAL": 0, "ACCEPTABLE": 0, "FAIL": 0}
    for row in scenarios:
        item = _require_object(row, "scenario row")
        if set(item) != {"index", "verdict"}:
            raise EvidenceError(f"{script} scenario row contains unsafe or incomplete fields")
        index = item["index"]
        if type(index) is not int or not 1 <= index <= total or index in seen:
            raise EvidenceError(f"{script} scenario indices are missing or duplicated")
        seen.add(index)
        verdict = _require_string(item["verdict"], "scenario verdict")
        if verdict not in SAFE_VERDICTS:
            raise EvidenceError(f"{script} scenario verdict is invalid")
        observed[verdict] += 1
    if seen != set(range(1, total + 1)):
        raise EvidenceError(f"{script} scenario indices are incomplete")
    if any(observed[key] != value for key, value in expected_counts.items()):
        raise EvidenceError(f"{script} scenario verdict rows disagree with counts")

    gate = _require_object(data["gate"], "scenario gate")
    if set(gate) != {"basis", "threshold", "passed"}:
        raise EvidenceError(f"{script} gate fields are incomplete")
    if gate["basis"] != expected_family or gate["threshold"] != threshold or type(gate["passed"]) is not bool:
        raise EvidenceError(f"{script} gate definition is inconsistent")
    measured = pass_count if script.startswith("e2e_plan15") else acceptable_count
    expected_passed = measured >= threshold and (script.startswith("e2e_plan15") or fail_count == 0)
    if (
        gate["passed"] != expected_passed
        or (status == "PASS") != expected_passed
        or (exit_code == 0) != expected_passed
    ):
        raise EvidenceError(f"{script} status, exit code, and gate disagree")
    return {
        "status": status,
        "exit_code": exit_code,
        "counts": {
            "total": total,
            "pass": pass_count,
            "partial": partial_count,
            "acceptable": acceptable_count,
            "fail": fail_count,
        },
        "gate": {"basis": gate["basis"], "threshold": threshold, "passed": expected_passed},
        "scenarios": [{"index": item["index"], "verdict": item["verdict"]} for item in scenarios],
    }


def validate_exit_result(result: object, *, script: str, child_run_id: str, exit_code: int) -> dict[str, Any]:
    """Validate an exit-only result for scripts without scenario score tables."""
    data = _require_object(result, "exit result")
    required = {"schema_version", "kind", "script", "child_run_id", "status", "exit_code", "reason"}
    if set(data) != required or data["schema_version"] != 1 or data["kind"] != "neocortex-e2e-exit-result":
        raise EvidenceError(f"{script} exit result schema is invalid")
    result_exit_code = _require_nonnegative_int(data["exit_code"], "exit result code")
    if data["script"] != script or data["child_run_id"] != child_run_id or result_exit_code != exit_code:
        raise EvidenceError(f"{script} exit result identity is inconsistent")
    if result_exit_code > 255:
        raise EvidenceError(f"{script} exit result code is out of range")
    status = _require_string(data["status"], "exit result status")
    if status not in {"PASS", "FAIL", "NOT_MEASURED"}:
        raise EvidenceError(f"{script} exit result status is invalid")
    reason = _require_string(data["reason"], "exit result reason")
    if status == "PASS" and exit_code != 0:
        raise EvidenceError(f"{script} cannot pass with a nonzero exit code")
    if status == "FAIL" and exit_code == 0:
        raise EvidenceError(f"{script} cannot fail with a zero exit code")
    return {"status": status, "exit_code": exit_code, "reason": reason}


def write_exit_result(path: Path, *, script: str, child_run_id: str, exit_code: int) -> None:
    """Write a safe fallback result when a generic E2E emits no score table."""
    status = "PASS" if exit_code == 0 else "FAIL"
    atomic_write_json(
        path,
        {
            "schema_version": 1,
            "kind": "neocortex-e2e-exit-result",
            "script": script,
            "child_run_id": child_run_id,
            "status": status,
            "exit_code": exit_code,
            "reason": "exit_status_only",
        },
    )


def write_missing_result(path: Path, *, script: str, child_run_id: str, exit_code: int) -> None:
    """Write an explicit NOT_MEASURED result for a missing scenario table."""
    atomic_write_json(
        path,
        {
            "schema_version": 1,
            "kind": "neocortex-e2e-exit-result",
            "script": script,
            "child_run_id": child_run_id,
            "status": "NOT_MEASURED",
            "exit_code": exit_code,
            "reason": "scenario_result_missing",
        },
    )


def _safe_recall_summary(value: object, *, run_id: str) -> dict[str, Any]:
    """Validate source recall evidence and return its only publishable summary."""
    data = _require_object(value, "recall evidence")
    required = {
        "schema_version",
        "kind",
        "status",
        "run_id",
        "query_count",
        "query_results",
        "metrics",
        "opaque_item_hashes",
        "top1_id_availability",
    }
    compact = data.get("schema_version") == 2
    if compact:
        required.add("query_set")
    if set(data) != required or data["schema_version"] not in {1, 2} or data["kind"] != "neocortex-recall-evidence":
        raise EvidenceError("recall evidence schema is invalid")
    if compact and data["query_set"] != {
        "corpus_profile": "compact",
        "query_ids": ["Q2", "Q3", "Q6", "Q7", "Q8", "Q9"],
        "excluded_query_ids": ["Q1", "Q4", "Q5"],
        "specific_event_total": 1,
        "temporal_total": 3,
    }:
        raise EvidenceError("compact recall query set or denominators are invalid")
    if data["run_id"] != run_id or data["status"] != "MEASURED":
        raise EvidenceError("recall evidence run identity or status is invalid")
    query_count = _require_nonnegative_int(data["query_count"], "recall query count")
    if compact and query_count != 6:
        raise EvidenceError("compact recall must contain six selected queries")
    query_results = data["query_results"]
    if not isinstance(query_results, list) or len(query_results) != query_count or query_count == 0:
        raise EvidenceError("recall query result count is invalid")
    seen: set[int] = set()
    top_hashes: list[str] = []
    for row in query_results:
        item = _require_object(row, "recall query result")
        if set(item) != {"index", "result_count", "top_item_hash", "keyword_match_count"}:
            raise EvidenceError("recall evidence contains unsafe fields")
        index = item["index"]
        if type(index) is not int or index not in range(1, query_count + 1) or index in seen:
            raise EvidenceError("recall query indices are missing or duplicated")
        seen.add(index)
        _require_nonnegative_int(item["result_count"], "recall result count")
        _require_nonnegative_int(item["keyword_match_count"], "recall keyword match count")
        top_hash = item["top_item_hash"]
        if top_hash is not None and (not isinstance(top_hash, str) or SHA256.fullmatch(top_hash) is None):
            raise EvidenceError("recall top item hash is invalid")
        if isinstance(top_hash, str):
            top_hashes.append(top_hash)
    if seen != set(range(1, query_count + 1)):
        raise EvidenceError("recall query indices are incomplete")
    metrics = _require_object(data["metrics"], "recall metrics")
    if set(metrics) != {"M1_max_activation", "M2_max_top1_count", "M3_specific_event_pass", "M4_temporal_pass"}:
        raise EvidenceError("recall metrics are incomplete")
    if any(type(metrics[key]) not in {int, float} or not math.isfinite(metrics[key]) for key in metrics):
        raise EvidenceError("recall metrics contain non-numeric values")
    if compact:
        for metric, indices in (("M3_specific_event_pass", (1,)), ("M4_temporal_pass", (3, 4, 5))):
            by_index = {row["index"]: row for row in query_results}
            measured = sum(by_index[index + 1]["keyword_match_count"] > 0 for index in indices)
            if type(metrics[metric]) is not int or metrics[metric] != measured:
                raise EvidenceError("compact recall metric disagrees with measured query rows")
    hashes = data["opaque_item_hashes"]
    if (
        not isinstance(hashes, list)
        or len(set(hashes)) != len(hashes)
        or any(not isinstance(item, str) or SHA256.fullmatch(item) is None for item in hashes)
    ):
        raise EvidenceError("recall opaque item hashes are invalid")
    availability = _require_object(data["top1_id_availability"], "recall top-1 ID availability")
    if set(availability) != {"known", "missing"}:
        raise EvidenceError("recall top-1 ID availability is invalid")
    known = _require_nonnegative_int(availability["known"], "recall known top-1 ID count")
    missing = _require_nonnegative_int(availability["missing"], "recall missing top-1 ID count")
    if known != len(top_hashes) or missing != query_count - known:
        raise EvidenceError("recall top-1 ID availability is inconsistent")
    m2 = metrics["M2_max_top1_count"]
    if type(m2) is not int or m2 < 0 or m2 != max(Counter(top_hashes).values(), default=0) or m2 > known:
        raise EvidenceError("recall M2 or top-1 ID availability is inconsistent")
    return {
        "status": "MEASURED",
        **({"query_set": data["query_set"]} if compact else {}),
        "query_count": query_count,
        "metrics": metrics,
        "opaque_item_hash_count": len(hashes),
        "top1_id_availability": {"known": known, "missing": missing},
    }


def validate_recall_evidence(value: object, *, run_id: str) -> dict[str, Any]:
    """Validate the aggregate-only recall artifact."""
    return _safe_recall_summary(value, run_id=run_id)


def _match_recall_profile(summary: dict[str, Any], metadata: dict[str, Any]) -> None:
    if summary.get("status") == "NOT_MEASURED":
        return
    profile = metadata.get("corpus_profile", "full")
    recall_profile = summary.get("query_set", {}).get("corpus_profile", "full")
    if profile not in {"full", "compact"} or profile != recall_profile:
        raise EvidenceError("recall profile does not match the measured corpus")


def _validate_recall_reference(recall: dict[str, Any], *, run_id: str) -> dict[str, Any]:
    """Validate the referenced source and bind its digest to its safe summary."""
    if set(recall) != {"path", "sha256", "result"}:
        raise EvidenceError("recall reference is invalid")
    path = ROOT / _safe_relative_path(recall["path"], "recall path")
    digest = _require_string(recall["sha256"], "recall digest", pattern=SHA256)
    if not path.is_file() or sha256_file(path) != digest:
        raise EvidenceError("recall reference file or digest is invalid")
    source = _require_object(json.loads(path.read_text(encoding="utf-8")), "recall evidence")
    if source.get("status") == "NOT_MEASURED":
        if set(source) != {"schema_version", "kind", "status", "run_id", "reason"}:
            raise EvidenceError("NOT_MEASURED recall evidence is malformed")
        if source.get("run_id") != run_id:
            raise EvidenceError("NOT_MEASURED recall evidence run identity is invalid")
        summary = {"status": "NOT_MEASURED", "reason": _require_string(source["reason"], "recall reason")}
    else:
        summary = validate_recall_evidence(source, run_id=run_id)
    if recall["result"] != summary:
        raise EvidenceError("published recall summary does not match its referenced source")
    return summary


def write_not_measured_recall(path: Path, *, run_id: str, reason: str) -> None:
    atomic_write_json(
        path,
        {
            "schema_version": 1,
            "kind": "neocortex-recall-evidence",
            "status": "NOT_MEASURED",
            "run_id": run_id,
            "reason": reason,
        },
    )


def _parse_status_file(path: Path, run_id: str) -> list[tuple[str, str, int, Path]]:
    if not path.is_file():
        raise EvidenceError("E2E status file is missing")
    rows: list[tuple[str, str, int, Path]] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) != 4:
            raise EvidenceError("E2E status row is malformed")
        script, child_run_id, exit_text, result_path_text = fields
        if (
            script not in E2E_SCRIPTS
            or script in seen
            or child_run_id != f"{run_id}.e2e.{E2E_SCRIPTS.index(script) + 1:02d}"
        ):
            raise EvidenceError("E2E status rows are duplicated or have inconsistent child ids")
        try:
            exit_code = int(exit_text)
        except ValueError as exc:
            raise EvidenceError("E2E exit code is malformed") from exc
        if not 0 <= exit_code <= 255:
            raise EvidenceError("E2E exit code is out of range")
        result_path = Path(result_path_text)
        if not result_path.is_file():
            raise EvidenceError("E2E result file is missing")
        seen.add(script)
        rows.append((script, child_run_id, exit_code, result_path))
    if set(seen) != set(E2E_SCRIPTS):
        raise EvidenceError("not all five required E2Es were recorded")
    return rows


def build_manifest(
    *,
    arm: str,
    run_id: str,
    metrics_path: Path,
    snapshot_path: Path,
    snapshot_sha256: str,
    recall_path: Path,
    statuses_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Validate child evidence and atomically publish one safe manifest."""
    _require_string(run_id, "run id", pattern=SAFE_RUN_ID)
    _require_string(arm, "arm", pattern=SAFE_RUN_ID)
    if not metrics_path.is_file() or not snapshot_path.is_file() or not recall_path.is_file():
        raise EvidenceError("manifest input is missing")
    metrics = _require_object(json.loads(metrics_path.read_text(encoding="utf-8")), "corpus metrics")
    metadata = _require_object(metrics.get("run_metadata"), "corpus run metadata")
    if metadata.get("run_id") != run_id or metrics.get("phase") != "corpus" or metrics.get("arm") != arm:
        raise EvidenceError("corpus metrics run identity is inconsistent")
    snapshot_digest = sha256_file(snapshot_path)
    if snapshot_sha256 != snapshot_digest or metadata.get("snapshot_sha256") != snapshot_digest:
        raise EvidenceError("snapshot digest does not match corpus metrics")
    metrics_rel = relative_path(metrics_path)
    snapshot_rel = relative_path(snapshot_path)
    input_paths = _require_object(metrics.get("input_paths"), "corpus input paths")
    if input_paths.get("graph_snapshot") != snapshot_rel:
        raise EvidenceError("corpus metrics snapshot path is inconsistent")
    recall = _require_object(json.loads(recall_path.read_text(encoding="utf-8")), "recall evidence")
    recall_summary: dict[str, Any]
    if recall.get("status") == "NOT_MEASURED":
        if set(recall) != {"schema_version", "kind", "status", "run_id", "reason"} or recall.get("run_id") != run_id:
            raise EvidenceError("NOT_MEASURED recall evidence is malformed")
        recall_summary = {"status": "NOT_MEASURED", "reason": _require_string(recall["reason"], "recall reason")}
    else:
        recall_summary = validate_recall_evidence(recall, run_id=run_id)
    _match_recall_profile(recall_summary, metadata)
    children = []
    for script, child_run_id, exit_code, result_path in _parse_status_file(statuses_path, run_id):
        raw_result = _require_object(json.loads(result_path.read_text(encoding="utf-8")), "E2E result")
        if script in SCENARIO_GATES:
            try:
                safe_result = validate_scenario_result(
                    raw_result, script=script, child_run_id=child_run_id, exit_code=exit_code
                )
            except EvidenceError:
                if raw_result.get("status") == "NOT_MEASURED" and raw_result.get("reason") == "scenario_result_missing":
                    safe_result = {
                        "status": "NOT_MEASURED",
                        "exit_code": exit_code,
                        "reason": "scenario_result_missing",
                    }
                else:
                    raise
        else:
            safe_result = validate_exit_result(
                raw_result, script=script, child_run_id=child_run_id, exit_code=exit_code
            )
        children.append(
            {
                "script": script,
                "script_sha256": sha256_file(ROOT / "scripts" / script),
                "child_run_id": child_run_id,
                "exit_code": exit_code,
                "result": safe_result,
            }
        )
    passed = sum(1 for item in children if item["exit_code"] == 0)
    failed = sum(1 for item in children if item["exit_code"] != 0)
    status = "MEASURED"
    if recall_summary["status"] != "MEASURED" or any(child["result"]["status"] == "NOT_MEASURED" for child in children):
        status = "NOT_MEASURED"
    manifest = {
        "schema_version": 1,
        "kind": "neocortex-bakeoff-e2e-manifest",
        "status": status,
        "arm": arm,
        "run_id": run_id,
        "corpus_metrics": {"path": metrics_rel, "sha256": sha256_file(metrics_path)},
        "post_snapshot": {"path": snapshot_rel, "sha256": snapshot_digest},
        "recall": {"path": relative_path(recall_path), "sha256": sha256_file(recall_path), "result": recall_summary},
        "e2e": {"total": len(children), "passed": passed, "failed": failed, "children": children},
    }
    atomic_write_json(output_path, manifest)
    return manifest


def _validate_published_manifest(manifest: dict[str, Any], *, run_id: str) -> None:
    required = {"schema_version", "kind", "status", "arm", "run_id", "corpus_metrics", "post_snapshot", "recall", "e2e"}
    if (
        set(manifest) != required
        or manifest.get("schema_version") != 1
        or manifest.get("kind") != "neocortex-bakeoff-e2e-manifest"
    ):
        raise EvidenceError("E2E manifest schema is invalid")
    if manifest.get("status") not in {"MEASURED", "NOT_MEASURED"}:
        raise EvidenceError("E2E manifest status is invalid")
    if manifest.get("run_id") != run_id:
        raise EvidenceError("E2E manifest run identity is invalid")
    _require_string(manifest.get("arm"), "E2E arm", pattern=SAFE_RUN_ID)
    for key in ("corpus_metrics", "post_snapshot"):
        value = _require_object(manifest[key], key)
        if set(value) != {"path", "sha256"}:
            raise EvidenceError(f"{key} reference is invalid")
        _safe_relative_path(value["path"], f"{key} path")
        _require_string(value["sha256"], f"{key} digest", pattern=SHA256)
    recall = _require_object(manifest["recall"], "recall reference")
    recall_result = _validate_recall_reference(recall, run_id=run_id)
    e2e = _require_object(manifest["e2e"], "E2E summary")
    if set(e2e) != {"total", "passed", "failed", "children"}:
        raise EvidenceError("E2E summary is inconsistent")
    total = _require_nonnegative_int(e2e["total"], "E2E total")
    passed = _require_nonnegative_int(e2e["passed"], "E2E passed count")
    failed = _require_nonnegative_int(e2e["failed"], "E2E failed count")
    if total != len(E2E_SCRIPTS) or passed + failed != total:
        raise EvidenceError("E2E summary is inconsistent")
    children = e2e["children"]
    if not isinstance(children, list) or len(children) != len(E2E_SCRIPTS):
        raise EvidenceError("E2E children are incomplete")
    seen: set[str] = set()
    for position, child in enumerate(children, 1):
        item = _require_object(child, "E2E child")
        if set(item) != {"script", "script_sha256", "child_run_id", "exit_code", "result"}:
            raise EvidenceError("E2E child contains unsafe fields")
        script = _require_string(item["script"], "E2E script")
        child_run_id = f"{run_id}.e2e.{position:02d}"
        if script not in E2E_SCRIPTS or script in seen or item["child_run_id"] != child_run_id:
            raise EvidenceError("E2E child identities are duplicated or inconsistent")
        _require_string(item["script_sha256"], "E2E script digest", pattern=SHA256)
        if item["script_sha256"] != sha256_file(ROOT / "scripts" / script):
            raise EvidenceError("E2E script digest is stale or inconsistent")
        exit_code = _require_nonnegative_int(item["exit_code"], "E2E exit code")
        if exit_code > 255:
            raise EvidenceError("E2E exit code is out of range")
        result = _require_object(item["result"], "E2E safe result")
        if script in SCENARIO_GATES:
            if set(result) != {"status", "exit_code", "counts", "gate", "scenarios"}:
                if set(result) != {"status", "exit_code", "reason"} or result.get("status") != "NOT_MEASURED":
                    raise EvidenceError("scenario child safe result is invalid")
                if result.get("exit_code") != exit_code:
                    raise EvidenceError("scenario child exit status is inconsistent")
                _require_string(result.get("reason"), "scenario child reason")
            else:
                raw = {
                    "schema_version": 1,
                    "kind": "neocortex-e2e-scenario-result",
                    "script": script,
                    "child_run_id": child_run_id,
                    "status": result["status"],
                    "exit_code": result["exit_code"],
                    "counts": result["counts"],
                    "gate": result["gate"],
                    "scenarios": result["scenarios"],
                }
                validate_scenario_result(raw, script=script, child_run_id=child_run_id, exit_code=exit_code)
        else:
            raw = {
                "schema_version": 1,
                "kind": "neocortex-e2e-exit-result",
                "script": script,
                "child_run_id": child_run_id,
                **result,
            }
            validate_exit_result(raw, script=script, child_run_id=child_run_id, exit_code=exit_code)
        seen.add(script)
    if set(seen) != set(E2E_SCRIPTS):
        raise EvidenceError("all five E2Es are not present")
    observed_passed = sum(1 for child in children if child["exit_code"] == 0)
    observed_failed = len(children) - observed_passed
    if passed != observed_passed or failed != observed_failed:
        raise EvidenceError("E2E summary counts are inconsistent")
    expected_status = (
        "NOT_MEASURED"
        if (
            recall_result["status"] == "NOT_MEASURED"
            or any(child["result"]["status"] == "NOT_MEASURED" for child in children)
        )
        else "MEASURED"
    )
    if manifest["status"] != expected_status:
        raise EvidenceError("E2E manifest status is inconsistent")


def merge_manifest(
    *, manifest_path: Path, metrics_path: Path, run_id: str, snapshot_path: Path, snapshot_sha256: str
) -> dict[str, Any]:
    """Attach a validated manifest to corpus metrics with cross-run/hash checks."""
    manifest = _require_object(json.loads(manifest_path.read_text(encoding="utf-8")), "E2E manifest")
    _validate_published_manifest(manifest, run_id=run_id)
    metrics = _require_object(json.loads(metrics_path.read_text(encoding="utf-8")), "corpus metrics")
    metadata = _require_object(metrics.get("run_metadata"), "corpus run metadata")
    if metadata.get("run_id") != run_id or metrics.get("phase") != "corpus":
        raise EvidenceError("offline merge run identity is inconsistent")
    if metrics.get("arm") != manifest.get("arm"):
        raise EvidenceError("offline merge arm identity is inconsistent")
    if "e2e_manifest" in metrics or "phases" in metrics:
        raise EvidenceError("corpus metrics already have an E2E attachment")
    if not snapshot_path.is_file() or sha256_file(snapshot_path) != snapshot_sha256:
        raise EvidenceError("offline merge snapshot digest is invalid")
    if manifest.get("post_snapshot") != {"path": relative_path(snapshot_path), "sha256": snapshot_sha256}:
        raise EvidenceError("offline merge snapshot path or digest is inconsistent")
    recall_summary = _validate_recall_reference(_require_object(manifest["recall"], "recall reference"), run_id=run_id)
    _match_recall_profile(recall_summary, metadata)
    expected_metrics = {"path": relative_path(metrics_path), "sha256": sha256_file(metrics_path)}
    if manifest.get("corpus_metrics") != expected_metrics:
        raise EvidenceError("offline merge corpus metrics hash is inconsistent")
    metrics["e2e_manifest"] = manifest
    atomic_write_json(metrics_path, metrics)
    return metrics


def _cli() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    write_exit = subparsers.add_parser("write-exit-result")
    write_exit.add_argument("--path", type=Path, required=True)
    write_exit.add_argument("--script", required=True, choices=E2E_SCRIPTS)
    write_exit.add_argument("--child-run-id", required=True)
    write_exit.add_argument("--exit-code", type=int, required=True)
    write_missing = subparsers.add_parser("write-missing-result")
    write_missing.add_argument("--path", type=Path, required=True)
    write_missing.add_argument("--script", required=True, choices=E2E_SCRIPTS)
    write_missing.add_argument("--child-run-id", required=True)
    write_missing.add_argument("--exit-code", type=int, required=True)
    write_recall = subparsers.add_parser("write-not-measured-recall")
    write_recall.add_argument("--path", type=Path, required=True)
    write_recall.add_argument("--run-id", required=True)
    write_recall.add_argument("--reason", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--arm", required=True)
    build.add_argument("--run-id", required=True)
    build.add_argument("--metrics-path", type=Path, required=True)
    build.add_argument("--snapshot-path", type=Path, required=True)
    build.add_argument("--snapshot-sha256", required=True)
    build.add_argument("--recall-path", type=Path, required=True)
    build.add_argument("--statuses-path", type=Path, required=True)
    build.add_argument("--output-path", type=Path, required=True)
    merge = subparsers.add_parser("merge")
    merge.add_argument("--manifest-path", type=Path, required=True)
    merge.add_argument("--metrics-path", type=Path, required=True)
    merge.add_argument("--run-id", required=True)
    merge.add_argument("--snapshot-path", type=Path, required=True)
    merge.add_argument("--snapshot-sha256", required=True)
    args = parser.parse_args()
    try:
        if args.command == "write-exit-result":
            write_exit_result(args.path, script=args.script, child_run_id=args.child_run_id, exit_code=args.exit_code)
        elif args.command == "write-missing-result":
            write_missing_result(
                args.path, script=args.script, child_run_id=args.child_run_id, exit_code=args.exit_code
            )
        elif args.command == "write-not-measured-recall":
            write_not_measured_recall(args.path, run_id=args.run_id, reason=args.reason)
        elif args.command == "build":
            build_manifest(
                arm=args.arm,
                run_id=args.run_id,
                metrics_path=args.metrics_path,
                snapshot_path=args.snapshot_path,
                snapshot_sha256=args.snapshot_sha256,
                recall_path=args.recall_path,
                statuses_path=args.statuses_path,
                output_path=args.output_path,
            )
        else:
            merge_manifest(
                manifest_path=args.manifest_path,
                metrics_path=args.metrics_path,
                run_id=args.run_id,
                snapshot_path=args.snapshot_path,
                snapshot_sha256=args.snapshot_sha256,
            )
    except (EvidenceError, OSError, json.JSONDecodeError) as exc:
        print(f"evidence validation failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
