#!/usr/bin/env python3
"""Generate and validate the privacy-safe Stage 7 compact parsing report."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

RUN_ID = "20260911T001509Z-swift3"
ARM = "qwen-flash-next-compact"
MODEL = "qwen3.8-flash-next"
EFFORT = "false"
EPISODE_IDS = (2, 4, 5, 10, 18, 20, 26, 27)
EPISODE_KEYS = tuple(f"E{number:02d}" for number in EPISODE_IDS)
AGENT_NAMES = ("ontology", "extractor", "librarian", "domain_classifier")
QUALITY_CHECKS = (
    "extraction_smoke",
    "plan15",
    "plan17",
    "episodic_memory",
    "cognitive_recall",
)
REPORT_SCHEMA = "resources/qwen-parsing-report-compact.schema.json"
SAMPLE_SCHEMA = "resources/quality-sample-qwen-flash-next.schema.json"
CORPUS_PATH = "docs/plans/33-local-qwen-migration/resources/compact-corpus.md"
METRICS_PATH = "docs/plans/33-local-qwen-migration/resources/metrics-qwen-flash-next-compact.json"
E2E_PATH = (
    "docs/plans/33-local-qwen-migration/resources/e2e-manifest-qwen-flash-next-compact-20260911T001509Z-swift3.json"
)
RECALL_PATH = (
    "docs/plans/33-local-qwen-migration/resources/recall-results-qwen-flash-next-compact-20260911T001509Z-swift3.json"
)
MISSING_ADMIN_PATH = "NOT_MEASURED/admin_jobs"
MISSING_GRAPH_PATH = "NOT_MEASURED/graph_export"
OUTPUT_FILES = (
    "qwen-parsing-inputs.json",
    "qwen-parsing-report.json",
    "qwen-parsing-report.md",
    "quality-sample-qwen-flash-next.json",
)
REASON_PER_EPISODE = "No committed privacy-safe per-episode attribution exists for this field."
REASON_ADMIN = "No committed privacy-safe per-job admin response exists for this run."
REASON_GRAPH = "No privacy-safe graph export with source episode and job identifiers is committed."
REASON_AUDIT = "The private audit log was not read; only committed aggregate counters are used."
REASON_SAMPLE = (
    "The snapshot was hash-verified but not extracted because no committed privacy-safe graph export "
    "links records to source episode and job identifiers."
)
COMPARISON_AGENTS = ("Ontology", "Extractor", "Librarian", "Domain classifier")
COMPARISON_COLUMNS = (
    "Reasoning agent",
    "Verdict",
    "Integrity disposition",
    "E2E and quality disposition",
    "Hosted baseline",
    "Direct evidence",
    "Next action",
)


class ReportError(ValueError):
    """Raised when evidence cannot support a deterministic safe report."""


def _repo_root(plan_dir: Path) -> Path:
    current = plan_dir.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    raise ReportError("plan directory is not inside a Git repository")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise ReportError(f"required source is missing: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise ReportError(f"invalid JSON source: {path.name}") from exc
    if not isinstance(value, dict):
        raise ReportError(f"JSON source must be an object: {path.name}")
    return value


def _digest(path: Path) -> str:
    if not path.is_file():
        raise ReportError(f"required source is missing: {path.name}")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=False, ensure_ascii=True) + "\n").encode()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _expect(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise ReportError(f"{label} mismatch")


def _load_sources(plan_dir: Path) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
    root = _repo_root(plan_dir)
    metrics = _read_json(root / METRICS_PATH)
    e2e = _read_json(root / E2E_PATH)
    recall = _read_json(root / RECALL_PATH)
    metadata = metrics.get("run_metadata", {})

    _expect(metadata.get("run_id"), RUN_ID, "metrics run id")
    _expect(metrics.get("arm"), ARM, "metrics arm")
    _expect(metadata.get("corpus_profile"), "compact", "metrics corpus profile")
    _expect(metadata.get("corpus_episode_ids"), list(EPISODE_IDS), "metrics episode set")
    _expect(metadata.get("corpus_size"), len(EPISODE_IDS), "metrics corpus size")
    _expect(metadata.get("corpus_sha256"), _digest(root / CORPUS_PATH), "metrics corpus digest")
    _expect(metadata.get("source_paths", {}).get("corpus"), CORPUS_PATH, "metrics corpus path")
    _expect(tuple(metadata.get("model_ids", {})), AGENT_NAMES, "metrics agent set")
    _expect(tuple(metadata.get("efforts", {})), AGENT_NAMES, "metrics effort agent set")
    _expect(set(metadata.get("model_ids", {}).values()), {f"local:{MODEL}"}, "metrics model ids")
    _expect(set(metadata.get("efforts", {}).values()), {EFFORT}, "metrics effort profile")

    metrics_digest = _digest(root / METRICS_PATH)
    _expect(e2e.get("run_id"), RUN_ID, "E2E run id")
    _expect(e2e.get("arm"), ARM, "E2E arm")
    _expect(e2e.get("corpus_metrics", {}).get("path"), METRICS_PATH, "E2E metrics path")
    _expect(e2e.get("corpus_metrics", {}).get("sha256"), metrics_digest, "E2E metrics digest")
    _expect(e2e.get("status"), "MEASURED", "E2E status")
    _expect(e2e.get("e2e", {}).get("total"), 5, "E2E child count")

    _expect(recall.get("run_id"), RUN_ID, "recall run id")
    _expect(recall.get("status"), "MEASURED", "recall status")
    _expect(recall.get("query_set", {}).get("corpus_profile"), "compact", "recall profile")
    _expect(e2e.get("recall", {}).get("path"), RECALL_PATH, "E2E recall path")
    _expect(e2e.get("recall", {}).get("sha256"), _digest(root / RECALL_PATH), "E2E recall digest")

    snapshot_path = metadata.get("source_paths", {}).get("graph_snapshot")
    snapshot_digest = metadata.get("snapshot_sha256")
    if not isinstance(snapshot_path, str) or not snapshot_path:
        raise ReportError("metrics snapshot path is unavailable")
    if not isinstance(snapshot_digest, str):
        raise ReportError("metrics snapshot digest is unavailable")
    _expect(metadata.get("source_paths", {}).get("graph_snapshot_sha256"), snapshot_digest, "snapshot digest")
    _expect(e2e.get("post_snapshot", {}).get("path"), snapshot_path, "E2E snapshot path")
    _expect(e2e.get("post_snapshot", {}).get("sha256"), snapshot_digest, "E2E snapshot digest")
    _expect(_digest(root / snapshot_path), snapshot_digest, "snapshot file digest")
    return root, metrics, e2e, recall


def _manifest(root: Path, metrics: dict[str, Any]) -> dict[str, Any]:
    metadata = metrics["run_metadata"]
    snapshot_path = metadata["source_paths"]["graph_snapshot"]
    artifacts = [
        _available("corpus", CORPUS_PATH, _digest(root / CORPUS_PATH)),
        _available("metrics", METRICS_PATH, _digest(root / METRICS_PATH)),
        _available("snapshot", snapshot_path, _digest(root / snapshot_path)),
        _unavailable(
            "admin_jobs",
            MISSING_ADMIN_PATH,
            REASON_ADMIN,
        ),
        _unavailable(
            "graph_export",
            MISSING_GRAPH_PATH,
            REASON_GRAPH,
        ),
        _unavailable(
            "audit_log",
            "log/agent_actions.log",
            REASON_AUDIT,
        ),
        _available("e2e_manifest", E2E_PATH, _digest(root / E2E_PATH)),
        _available("recall", RECALL_PATH, _digest(root / RECALL_PATH)),
    ]
    return {"schema_version": 1, "run_id": RUN_ID, "artifacts": artifacts}


def _available(kind: str, path: str, digest: str) -> dict[str, str]:
    return {"kind": kind, "path": path, "sha256": digest, "availability": "MEASURED"}


def _unavailable(kind: str, path: str, reason: str) -> dict[str, str]:
    return {"kind": kind, "path": path, "sha256": "NOT_MEASURED", "availability": "NOT_MEASURED", "reason": reason}


def _pointer_escape(part: str) -> str:
    return part.replace("~", "~0").replace("/", "~1")


def _leaves(value: Any, pointer: str) -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _leaves(child, f"{pointer}/{_pointer_escape(key)}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _leaves(child, f"{pointer}/{index}")
    else:
        yield pointer, value


def _source_for_pointer(pointer: str) -> str:
    if pointer.endswith("/kind"):
        return REPORT_SCHEMA
    if "/quality_integrity/" in pointer:
        return E2E_PATH
    if "/events/" in pointer:
        return "log/agent_actions.log"
    if "/jobs/" in pointer:
        return MISSING_ADMIN_PATH
    if "/domains/" in pointer:
        return METRICS_PATH
    if "/ontology/" in pointer or "/extraction/" in pointer or "/librarian/" in pointer:
        return MISSING_GRAPH_PATH
    return REPORT_SCHEMA


def _episode(index: int, key: str, metadata: dict[str, Any]) -> dict[str, Any]:
    missing_collection = {
        "count": "NOT_MEASURED",
        "stable_ids": "NOT_MEASURED",
        "representative_safe_values": "NOT_MEASURED",
    }
    row: dict[str, Any] = {
        "episode_key": key,
        "source": {"path": CORPUS_PATH, "locator": f"episode:{key}"},
        "jobs": [
            {"kind": kind, "status": "NOT_MEASURED", "job_id": "NOT_MEASURED", "outcome": "NOT_MEASURED"}
            for kind in ("ingestion", "routing", "extraction")
        ],
        "run_provenance": {
            "model": MODEL,
            "effort": EFFORT,
            "run_id": RUN_ID,
            "snapshot_path": metadata["source_paths"]["graph_snapshot"],
            "source_revision": metadata["source_revision"],
        },
        "domains": {"accepted": "NOT_MEASURED", "proposal": "NOT_MEASURED"},
        "ontology": {
            status: {"node": "NOT_MEASURED", "edge": "NOT_MEASURED"} for status in ("proposed", "accepted", "rejected")
        },
        "extraction": {"entities": dict(missing_collection), "relations": dict(missing_collection)},
        "librarian": {
            "actions": {
                action: "NOT_MEASURED"
                for action in ("created_nodes", "updated_nodes", "archived_nodes", "created_edges", "removed_edges")
            }
        },
        "events": {"retries": "NOT_MEASURED", "timeouts": "NOT_MEASURED", "rejections": "NOT_MEASURED"},
        "quality_integrity": {
            "status": "NOT_MEASURED",
            "checks": [{"name": name, "status": "NOT_MEASURED", "source": E2E_PATH} for name in QUALITY_CHECKS],
        },
    }
    evidence = []
    for section in ("jobs", "domains", "ontology", "extraction", "librarian", "events", "quality_integrity"):
        for pointer, value in _leaves(row[section], f"/episodes/{index}/{section}"):
            item = {"pointer": pointer, "status": "MEASURED", "value": value, "source": _source_for_pointer(pointer)}
            if value == "NOT_MEASURED":
                item["status"] = "NOT_MEASURED"
                item["reason"] = REASON_PER_EPISODE
            evidence.append(item)
    row["evidence"] = evidence
    return row


def _report(metrics: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    metadata = metrics["run_metadata"]
    snapshot_path = metadata["source_paths"]["graph_snapshot"]
    return {
        "schema_version": 1,
        "status": "NOT_MEASURED",
        "run": {
            "run_id": RUN_ID,
            "model": MODEL,
            "effort": EFFORT,
            "source_revision": metadata["source_revision"],
            "corpus_profile": "compact",
            "corpus_revision": 1,
            "corpus_path": CORPUS_PATH,
            "corpus_sha256": metadata["corpus_sha256"],
            "snapshot_path": snapshot_path,
            "snapshot_sha256": metadata["snapshot_sha256"],
        },
        "source_artifacts": manifest["artifacts"],
        "episodes": [_episode(index, key, metadata) for index, key in enumerate(EPISODE_KEYS)],
        "checks": {
            "episode_set": ",".join(EPISODE_KEYS),
            "source_links": "PASS",
            "evidence_coverage": "PASS",
            "evidence_value_equality": "PASS",
            "no_invented_rows": "PASS",
            "hidden_reasoning_absent": "PASS",
            "raw_secrets_absent": "PASS",
            "sensitive_audit_absent": "PASS",
            "domain_privacy": "PASS",
        },
    }


def _sample(metrics: dict[str, Any]) -> dict[str, Any]:
    metadata = metrics["run_metadata"]
    return {
        "schema_version": 1,
        "status": "NOT_MEASURED",
        "expected_counts": {"nodes": 20, "edges": 20},
        "observed_counts": {"nodes": "NOT_MEASURED", "edges": "NOT_MEASURED"},
        "snapshot": {
            "path": metadata["source_paths"]["graph_snapshot"],
            "sha256": metadata["snapshot_sha256"],
        },
        "missing_input": "graph_export",
        "reason": REASON_SAMPLE,
        "consequence": "absolute_quality_fails_closed_all_agents_hold",
    }


def _resolve_pointer(document: Any, pointer: str) -> Any:
    value = document
    for raw in pointer.lstrip("/").split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def _validate_evidence(report: dict[str, Any]) -> int:
    for index, row in enumerate(report["episodes"]):
        prefix = f"/episodes/{index}/"
        if any(not evidence["pointer"].startswith(prefix) for evidence in row["evidence"]):
            raise ReportError("evidence pointer belongs to another episode")
    total = 0
    for index, row in enumerate(report["episodes"]):
        expected: set[str] = set()
        for section in ("jobs", "domains", "ontology", "extraction", "librarian", "events", "quality_integrity"):
            expected.update(pointer for pointer, _ in _leaves(row[section], f"/episodes/{index}/{section}"))
        actual: set[str] = set()
        for evidence in row["evidence"]:
            pointer = evidence["pointer"]
            if pointer in actual:
                raise ReportError("duplicate evidence pointer")
            actual.add(pointer)
            try:
                pointed_value = _resolve_pointer(report, pointer)
            except (KeyError, IndexError, ValueError, TypeError) as exc:
                raise ReportError("evidence pointer does not resolve") from exc
            if pointed_value != evidence["value"]:
                raise ReportError("evidence value mismatch")
            if pointed_value == "NOT_MEASURED":
                if evidence["status"] != "NOT_MEASURED" or evidence.get("reason") != REASON_PER_EPISODE:
                    raise ReportError("NOT_MEASURED evidence requires a reason")
            elif evidence["status"] != "MEASURED" or "reason" in evidence:
                raise ReportError("measured evidence metadata is invalid")
        if actual != expected:
            raise ReportError("evidence coverage mismatch")
        total += len(actual)
    return total


def _privacy_counts(values: list[bytes]) -> dict[str, int]:
    patterns = {
        "dynamic_schema_name": rb"ncx_[a-z0-9]+__[a-z0-9_]+",
        "email_address": rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        "reasoning_marker": rb"(?i)</?think>|<tool_call>|</tool_call>",
        "secret_assignment": rb"(?i)(authorization|api[_-]?key|password|cookie)\s*[:=]\s*[^\s,}]+",
        "forbidden_payload_key": (
            rb'(?i)"(episode_text|prompt|raw_model_output|hidden_reasoning|tool_arguments|schema_name)"\s*:'
        ),
        "forbidden_label": (
            rb"(?i)(?:^|[^A-Za-z0-9_])"
            rb"(episode_text|prompt|raw_model_output|hidden_reasoning|tool_arguments|schema_name|"
            rb"domain_value|domain_description|dynamic_schema)"
            rb"(?:$|[^A-Za-z0-9_])"
        ),
        "sensitive_audit_key": rb'(?i)"(agent_id|endpoint|correlation_id)"\s*:',
        "dynamic_domain_key": rb'(?i)"(domain_value|domain_description|dynamic_schema)"\s*:',
    }
    return {name: sum(len(re.findall(pattern, value)) for value in values) for name, pattern in patterns.items()}


def _validate_safe_content(*documents: Any) -> None:
    counts = _privacy_counts([_json_bytes(document) for document in documents])
    if any(counts.values()):
        raise ReportError("privacy or safe-value scan failed")


def _validate_manifest(root: Path, manifest: dict[str, Any]) -> None:
    if set(manifest) != {"schema_version", "run_id", "artifacts"}:
        raise ReportError("input manifest fields are invalid")
    _expect(manifest.get("schema_version"), 1, "input manifest schema version")
    _expect(manifest.get("run_id"), RUN_ID, "input manifest run id")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ReportError("input manifest artifacts are invalid")
    expected_kinds = (
        "corpus",
        "metrics",
        "snapshot",
        "admin_jobs",
        "graph_export",
        "audit_log",
        "e2e_manifest",
        "recall",
    )
    _expect(tuple(item.get("kind") for item in artifacts), expected_kinds, "input manifest source kinds")
    if len({item.get("path") for item in artifacts}) != len(artifacts):
        raise ReportError("input manifest source paths are not unique")
    for item in artifacts:
        expected_fields = {"kind", "path", "sha256", "availability"}
        if item.get("availability") == "NOT_MEASURED":
            expected_fields.add("reason")
        if set(item) != expected_fields:
            raise ReportError("input manifest artifact fields are invalid")
        path = item.get("path")
        if (
            not isinstance(path, str)
            or not path
            or Path(path).is_absolute()
            or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", path)
            or re.search(r"ncx_[a-z0-9]+__[a-z0-9_]+", path)
        ):
            raise ReportError("source path is not a safe relative reference")
        if item.get("availability") == "MEASURED":
            _expect(item.get("sha256"), _digest(root / path), f"{item.get('kind')} digest")
            if "reason" in item:
                raise ReportError("measured source must not have a missing reason")
        elif item.get("availability") == "NOT_MEASURED":
            if item.get("sha256") != "NOT_MEASURED" or not item.get("reason"):
                raise ReportError("unavailable source needs NOT_MEASURED digest and reason")
            expected_reason = {
                "admin_jobs": REASON_ADMIN,
                "graph_export": REASON_GRAPH,
                "audit_log": REASON_AUDIT,
            }.get(item["kind"])
            if item["reason"] != expected_reason:
                raise ReportError("unavailable source reason is not approved")
        else:
            raise ReportError("source availability is invalid")


def _validate_source_links(plan_dir: Path, manifest: dict[str, Any], report: dict[str, Any]) -> None:
    artifacts = {item["path"]: item for item in manifest["artifacts"]}
    allowed = {*artifacts, REPORT_SCHEMA}
    for row in report["episodes"]:
        if row["source"]["path"] not in artifacts:
            raise ReportError("episode source link is absent from the manifest")
        for check in row["quality_integrity"]["checks"]:
            if check["source"] not in artifacts:
                raise ReportError("quality source link is absent from the manifest")
        for evidence in row["evidence"]:
            source = evidence["source"]
            if source != _source_for_pointer(evidence["pointer"]):
                raise ReportError("evidence source mismatch")
            if source not in allowed:
                raise ReportError("evidence source link is absent from the manifest")
            if (
                evidence["status"] == "MEASURED"
                and source != REPORT_SCHEMA
                and artifacts[source]["availability"] != "MEASURED"
            ):
                raise ReportError("measured evidence links to an unavailable source")
    if not (plan_dir / REPORT_SCHEMA).is_file():
        raise ReportError("report schema source link is missing")


def _validate_sample(
    root: Path,
    sample: dict[str, Any],
    schema: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(sample)
    snapshot = sample["snapshot"]
    _expect(_digest(root / snapshot["path"]), snapshot["sha256"], "sample snapshot digest")
    if sample["status"] == "MEASURED":
        graph_source = next(item for item in manifest["artifacts"] if item["kind"] == "graph_export")
        if graph_source["availability"] != "MEASURED":
            raise ReportError("measured sample requires an available graph export")
        _expect(graph_source["sha256"], _digest(root / graph_source["path"]), "graph export digest")
        graph_export = _read_json(root / graph_source["path"])
        if set(graph_export) != {"schema_version", "status", "snapshot_sha256", "declared_types", "nodes", "edges"}:
            raise ReportError("graph export fields are invalid")
        _expect(graph_export["schema_version"], 1, "graph export schema version")
        _expect(graph_export["status"], "MEASURED", "graph export status")
        _expect(graph_export["snapshot_sha256"], snapshot["sha256"], "graph export snapshot digest")
        if len(sample["nodes"]) != 20 or len(sample["edges"]) != 20:
            raise ReportError("measured sample must contain exactly 20 nodes and 20 edges")
        node_ids = {node["id"] for node in sample["nodes"]}
        if len(node_ids) != 20:
            raise ReportError("measured sample node ids are not unique")
        if any(
            edge["source_node_id"] not in node_ids or edge["target_node_id"] not in node_ids for edge in sample["edges"]
        ):
            raise ReportError("measured sample contains invalid references")
        declared = sample["declared_types"]
        if any(node["type"] not in declared["node"] for node in sample["nodes"]):
            raise ReportError("measured sample contains an undeclared node type")
        if any(edge["type"] not in declared["edge"] for edge in sample["edges"]):
            raise ReportError("measured sample contains an undeclared edge type")
        _expect(declared, graph_export["declared_types"], "sample declared types")
        exported_nodes = {record["id"]: record for record in graph_export["nodes"]}
        exported_edges = {record["id"]: record for record in graph_export["edges"]}
        if len(exported_nodes) != len(graph_export["nodes"]) or len(exported_edges) != len(graph_export["edges"]):
            raise ReportError("graph export record ids are not unique")
        for node in sample["nodes"]:
            if exported_nodes.get(node["id"]) != node:
                raise ReportError("sample node does not match the graph export")
        for edge in sample["edges"]:
            if exported_edges.get(edge["id"]) != edge:
                raise ReportError("sample edge does not match the graph export")
    elif sample["reason"] != REASON_SAMPLE:
        raise ReportError("sample reason is not approved")


def _derive_report_status(report: dict[str, Any], manifest: dict[str, Any]) -> str:
    if any(item["availability"] == "NOT_MEASURED" for item in manifest["artifacts"]):
        return "NOT_MEASURED"
    for row in report["episodes"]:
        for section in ("jobs", "domains", "ontology", "extraction", "librarian", "events", "quality_integrity"):
            if any(value == "NOT_MEASURED" for _, value in _leaves(row[section], "")):
                return "NOT_MEASURED"
    return "MEASURED"


def validate_artifacts(plan_dir: Path, manifest_path: Path, report_path: Path, sample_path: Path) -> dict[str, Any]:
    root, metrics, _e2e, _recall = _load_sources(plan_dir)
    expected_manifest = _manifest(root, metrics)
    expected_report = _report(metrics, expected_manifest)
    expected_sample = _sample(metrics)
    manifest = _read_json(manifest_path)
    report = _read_json(report_path)
    sample = _read_json(sample_path)
    report_schema = _read_json(plan_dir / REPORT_SCHEMA)
    sample_schema = _read_json(plan_dir / SAMPLE_SCHEMA)
    try:
        Draft202012Validator.check_schema(report_schema)
        Draft202012Validator(report_schema).validate(report)
    except (SchemaError, ValidationError) as exc:
        raise ReportError("report schema validation failed") from exc
    _validate_manifest(root, manifest)
    _expect(manifest, expected_manifest, "canonical input manifest")
    _expect(report.get("source_artifacts"), manifest["artifacts"], "report source artifacts")
    _expect([row.get("episode_key") for row in report["episodes"]], list(EPISODE_KEYS), "report episode order")
    _expect(report.get("run"), expected_report["run"], "report run")
    _expect(report.get("status"), _derive_report_status(report, manifest), "report status")
    _validate_source_links(plan_dir, manifest, report)
    for row in report["episodes"]:
        _expect(
            tuple(job["kind"] for job in row["jobs"]),
            ("ingestion", "routing", "extraction"),
            "job kinds",
        )
        _expect(
            tuple(check["name"] for check in row["quality_integrity"]["checks"]),
            QUALITY_CHECKS,
            "quality checks",
        )
    evidence_count = _validate_evidence(report)
    try:
        _validate_sample(root, sample, sample_schema, manifest)
    except (SchemaError, ValidationError) as exc:
        raise ReportError("sample schema validation failed") from exc
    _validate_safe_content(manifest, report, sample)
    _expect(report, expected_report, "canonical report")
    _expect(sample, expected_sample, "canonical sample")
    return {
        "status": "PASS",
        "episodes": len(report["episodes"]),
        "evidence_records": evidence_count,
        "sources": len(manifest["artifacts"]),
        "sample_status": sample["status"],
    }


def _markdown_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def render_markdown(report: dict[str, Any]) -> str:
    run = report["run"]
    lines = [
        "# Qwen Flash Next compact parsing report",
        "",
        (
            "This report covers compact corpus revision 1 only. It does not measure 28-episode endurance, "
            "hosted equivalence, or a fully offline deployment."
        ),
        "",
        "## Report control",
        "",
        "| Field | Value |",
        "|---|---|",
    ]
    control = (
        ("Report status", report["status"]),
        ("Schema version", report["schema_version"]),
        ("Model", run["model"]),
        ("Effort", run["effort"]),
        ("Run id", run["run_id"]),
        ("Snapshot", run["snapshot_path"]),
        ("Source revision", run["source_revision"]),
        ("Corpus path", run["corpus_path"]),
        ("Corpus SHA-256", run["corpus_sha256"]),
    )
    lines.extend(f"| {field} | `{value}` |" for field, value in control)
    lines.extend(
        ["", "## Input manifest", "", "| Kind | Path | Availability | SHA-256 | Reason |", "|---|---|---|---|---|"]
    )
    for source in report["source_artifacts"]:
        lines.append(
            f"| {source['kind']} | `{source['path']}` | {source['availability']} | "
            f"`{source['sha256']}` | {source.get('reason', '')} |"
        )
    for row in report["episodes"]:
        lines.extend(["", f"## {row['episode_key']}", "", "| Field | Value |", "|---|---|"])
        for field in (
            "source",
            "jobs",
            "run_provenance",
            "domains",
            "ontology",
            "extraction",
            "librarian",
            "events",
            "quality_integrity",
        ):
            lines.append(f"| {field} | `{_markdown_value(row[field])}` |")
        lines.extend(
            [
                "",
                "### Evidence",
                "",
                "| JSON Pointer | Status | Exact value | Source | Reason |",
                "|---|---|---|---|---|",
            ]
        )
        for item in row["evidence"]:
            lines.append(
                f"| `{item['pointer']}` | {item['status']} | `{_markdown_value(item['value'])}` | "
                f"`{item['source']}` | {item.get('reason', '')} |"
            )
    lines.extend(["", "## Checks", "", "| Check | Result |", "|---|---|"])
    lines.extend(f"| {name} | {value} |" for name, value in report["checks"].items())
    return "\n".join(lines) + "\n"


def generate(plan_dir: Path, output_dir: Path) -> dict[str, Any]:
    root, metrics, _e2e, _recall = _load_sources(plan_dir)
    manifest = _manifest(root, metrics)
    manifest_path = output_dir / OUTPUT_FILES[0]
    _write_json(manifest_path, manifest)
    report = _report(metrics, manifest)
    sample = _sample(metrics)
    _validate_safe_content(manifest, report, sample)
    report_path = output_dir / OUTPUT_FILES[1]
    markdown_path = output_dir / OUTPUT_FILES[2]
    sample_path = output_dir / OUTPUT_FILES[3]
    _write_json(report_path, report)
    markdown_path.write_text(render_markdown(report))
    _write_json(sample_path, sample)
    return validate_artifacts(plan_dir, manifest_path, report_path, sample_path)


def self_check(plan_dir: Path, output: Path) -> dict[str, Any]:
    with (
        tempfile.TemporaryDirectory(prefix="qwen-report-a-") as first_name,
        tempfile.TemporaryDirectory(prefix="qwen-report-b-") as second_name,
    ):
        first = Path(first_name)
        second = Path(second_name)
        first_result = generate(plan_dir, first)
        generate(plan_dir, second)
        for filename in OUTPUT_FILES:
            if (first / filename).read_bytes() != (second / filename).read_bytes():
                raise ReportError(f"nondeterministic output: {filename}")
    result = {"status": "PASS", "files_compared": len(OUTPUT_FILES), **first_result}
    _write_json(output, result)
    return result


def _markdown_row(line: str) -> tuple[str, ...] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    return tuple(cell.strip() for cell in stripped[1:-1].split("|"))


def _verdict_table_counts(text: str) -> dict[str, int]:
    lines = text.splitlines()
    headings = [index for index, line in enumerate(lines) if line.strip() == "## Per-agent verdicts"]
    table_rows: list[tuple[str, ...]] = []
    table_row_indexes: set[int] = set()
    header_mismatch = 1
    separator_mismatch = 1
    if len(headings) == 1:
        cursor = headings[0] + 1
        while cursor < len(lines) and not lines[cursor].strip():
            cursor += 1
        header = _markdown_row(lines[cursor]) if cursor < len(lines) else None
        header_mismatch = int(header != COMPARISON_COLUMNS)
        cursor += 1
        separator = _markdown_row(lines[cursor]) if cursor < len(lines) else None
        separator_mismatch = int(separator != ("---",) * len(COMPARISON_COLUMNS))
        cursor += 1
        while cursor < len(lines):
            row = _markdown_row(lines[cursor])
            if row is None:
                break
            table_row_indexes.add(cursor)
            table_rows.append(row)
            cursor += 1

    well_formed_rows = [row for row in table_rows if len(row) == len(COMPARISON_COLUMNS)]
    parsed_agents = [row[0] for row in well_formed_rows]
    outside_verdict_rows = 0
    for index, line in enumerate(lines):
        if index in table_row_indexes:
            continue
        row = _markdown_row(line)
        if row and len(row) >= 2 and re.search(r"\b(?:HOLD|MIGRATE|BLOCKED)\b", row[1]):
            outside_verdict_rows += 1

    return {
        "comparison_verdict_heading_count": len(headings),
        "comparison_table_header_mismatch": header_mismatch,
        "comparison_table_separator_mismatch": separator_mismatch,
        "comparison_html_comment_markers": len(re.findall(r"<!--|-->", text)),
        "comparison_agent_rows": len(table_rows),
        "comparison_malformed_agent_rows": len(table_rows) - len(well_formed_rows),
        "comparison_unique_agents": len(set(parsed_agents)),
        "comparison_hold_rows": sum(row[1] == "HOLD" for row in well_formed_rows),
        "comparison_invalid_verdict_cells": sum(row[1] != "HOLD" for row in well_formed_rows),
        "comparison_duplicate_agents": len(parsed_agents) - len(set(parsed_agents)),
        "comparison_extra_rows": max(0, len(table_rows) - len(COMPARISON_AGENTS)),
        "comparison_unknown_agent_rows": sum(agent not in COMPARISON_AGENTS for agent in parsed_agents),
        "comparison_missing_agents": sum(agent not in parsed_agents for agent in COMPARISON_AGENTS),
        "comparison_outside_verdict_rows": outside_verdict_rows,
    }


def _comparison_counts(comparison: Path) -> dict[str, int]:
    root = _repo_root(Path(__file__))
    plan_dir = root / Path(METRICS_PATH).parents[1]
    _root, metrics, e2e, recall = _load_sources(plan_dir)
    text = comparison.read_text()
    jobs = metrics["job_summary"]
    usage = metrics["audit"]["usage"]
    requests = sum(item["requests"] for item in usage)
    reasoning_tokens = sum(item["reasoning_tokens"] for item in usage)
    events = metrics["audit"]["audit_event_counts"]
    recall_metrics = recall["metrics"]
    required = (
        RUN_ID,
        ARM,
        "compact corpus revision 1",
        f"{jobs['succeeded']}/{jobs['total']} succeeded",
        f"{jobs['failed'] + jobs['cancelled']}/{jobs['total']}",
        f"| Model requests | {requests} |",
        f"| Reasoning tokens | {reasoning_tokens} |",
        f"| Recall M1 maximum activation | {recall_metrics['M1_max_activation']} |",
        f"| Recall M2 maximum top-1 count | {recall_metrics['M2_max_top1_count']} |",
        f"| Recall M3 specific-event pass | {recall_metrics['M3_specific_event_pass']}/1 |",
        f"| Recall M4 temporal pass | {recall_metrics['M4_temporal_pass']}/3 |",
        f"| Required E2E set | {e2e['e2e']['passed']}/{e2e['e2e']['total']} passed |",
        f"| Missing-endpoint skips | {events['edge_skipped_missing_node']} |",
        f"| Temporal-pair conflicts | {events['edge_skipped_temporal_pair']} |",
        "9 PASS of 14",
        "12 ACCEPTABLE of 14, one FAIL",
        "No valid two-run, same-input hosted baseline exists.",
        "Keep the current model defaults.",
    )
    next_action = "Add privacy-safe per-event reason and correlation evidence"
    counts = {
        "comparison_missing_required_value": sum(value not in text for value in required),
        "comparison_next_action": text.count(next_action),
    }
    counts.update(_verdict_table_counts(text))
    return counts


def privacy_scan(paths: list[Path], output: Path) -> dict[str, Any]:
    values = []
    for path in paths:
        if not path.is_file():
            raise ReportError(f"privacy input is missing: {path.name}")
        values.append(path.read_bytes())
    counts = _privacy_counts(values)
    parsed_report = _read_json(paths[1])
    counts["markdown_canonical_mismatch"] = int(paths[2].read_text() != render_markdown(parsed_report))
    counts.update(_comparison_counts(paths[-1]))
    expected_nonzero = {
        "comparison_next_action": 4,
        "comparison_verdict_heading_count": 1,
        "comparison_agent_rows": 4,
        "comparison_unique_agents": 4,
        "comparison_hold_rows": 4,
    }
    passed = all(count == expected_nonzero.get(name, 0) for name, count in counts.items())
    _write_json(output, counts)
    if not passed:
        raise ReportError("privacy scan failed")
    return counts


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    generate_parser = commands.add_parser("generate")
    generate_parser.add_argument("--plan-dir", type=Path, required=True)
    generate_parser.add_argument("--output-dir", type=Path, required=True)
    validate_parser = commands.add_parser("validate")
    validate_parser.add_argument("--plan-dir", type=Path, required=True)
    validate_parser.add_argument("--input-manifest", type=Path, required=True)
    validate_parser.add_argument("--report", type=Path, required=True)
    validate_parser.add_argument("--sample", type=Path, required=True)
    self_parser = commands.add_parser("self-check")
    self_parser.add_argument("--plan-dir", type=Path, required=True)
    self_parser.add_argument("--output", type=Path, required=True)
    privacy_parser = commands.add_parser("privacy-scan")
    privacy_parser.add_argument("--input-manifest", type=Path, required=True)
    privacy_parser.add_argument("--report", type=Path, required=True)
    privacy_parser.add_argument("--markdown", type=Path, required=True)
    privacy_parser.add_argument("--sample", type=Path, required=True)
    privacy_parser.add_argument("--comparison", type=Path, required=True)
    privacy_parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "generate":
            generate(args.plan_dir, args.output_dir)
        elif args.command == "validate":
            print(
                json.dumps(
                    validate_artifacts(args.plan_dir, args.input_manifest, args.report, args.sample),
                    separators=(",", ":"),
                )
            )
        elif args.command == "self-check":
            self_check(args.plan_dir, args.output)
        else:
            privacy_scan([args.input_manifest, args.report, args.markdown, args.sample, args.comparison], args.output)
    except ReportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
