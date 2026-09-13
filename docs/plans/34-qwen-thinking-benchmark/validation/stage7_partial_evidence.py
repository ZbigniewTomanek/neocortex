#!/usr/bin/env python3
"""Write truthful Stage 7 NOT_MEASURED artifacts without contacting services."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}$")
JOB_KEYS = ("todo", "doing", "succeeded", "failed", "cancelled", "total")
E2E_SCRIPTS = (
    "e2e_extraction_pipeline_test.py",
    "e2e_plan15_scenarios_test.py",
    "e2e_plan17_validation.py",
    "e2e_episodic_memory_test.py",
    "e2e_cognitive_recall_test.py",
)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(text)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary_name)


def validate_summary(value: object) -> dict[str, int]:
    if not isinstance(value, dict) or set(value) != set(JOB_KEYS):
        raise ValueError("job summary fields are invalid")
    document = cast(dict[str, object], value)
    summary: dict[str, int] = {}
    for key in JOB_KEYS:
        raw_count = document[key]
        if type(raw_count) is not int or cast(int, raw_count) < 0:
            raise ValueError("job summary counts are invalid")
        summary[key] = cast(int, raw_count)
    if summary["total"] <= 0 or sum(summary[key] for key in JOB_KEYS[:-1]) != summary["total"]:
        raise ValueError("job summary total is invalid")
    return summary


def write_job_summary(path: Path, run_id: str, arm: str, summary: dict[str, int]) -> None:
    terminal = summary["todo"] == 0 and summary["doing"] == 0
    failure_rate = (summary["failed"] + summary["cancelled"]) / summary["total"]
    atomic_write_json(
        path,
        {
            "schema_version": 1,
            "kind": "neocortex-stage7-job-summary",
            "run_id": run_id,
            "arm": arm,
            "status": "MEASURED",
            "terminal": terminal,
            "job_summary": summary,
            "stability": {
                "status": "PASS" if terminal and failure_rate <= 0.10 else "FAIL" if terminal else "NOT_MEASURED",
                "failed_or_cancelled_rate": failure_rate if terminal else None,
            },
        },
    )


def _read_statuses(path: Path | None, run_id: str) -> dict[str, dict[str, Any]]:
    observed: dict[str, dict[str, Any]] = {}
    if path is None or not path.is_file():
        return observed
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        fields = raw_line.split("\t")
        if len(fields) != 4:
            raise ValueError("E2E status row is malformed")
        script, child_run_id, raw_exit_code, _result_path = fields
        if script not in E2E_SCRIPTS or child_run_id != f"{run_id}.e2e.{E2E_SCRIPTS.index(script) + 1:02d}":
            raise ValueError("E2E status identity is invalid")
        exit_code = int(raw_exit_code)
        if not 0 <= exit_code <= 255:
            raise ValueError("E2E exit code is invalid")
        observed[script] = {
            "script": script,
            "child_run_id": child_run_id,
            "status": "MEASURED",
            "exit_code": exit_code,
        }
    return observed


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.name


def _marker(kind: str, run_id: str, arm: str, reason: str, sources: dict[str, str]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "neocortex-stage7-partial-evidence",
        "artifact_kind": kind,
        "status": "NOT_MEASURED",
        "run_id": run_id,
        "arm": arm,
        "reason": reason,
        "available_sources": sources,
    }


def validate_unavailable(path: Path, kind: str, run_id: str, arm: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise ValueError("unavailable evidence path is not a regular file")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("unavailable evidence is not an object")
    if (
        document.get("schema_version") != 1
        or document.get("kind") != "neocortex-stage7-partial-evidence"
        or document.get("artifact_kind") != kind
        or document.get("status") != "NOT_MEASURED"
        or document.get("run_id") != run_id
        or document.get("arm") != arm
    ):
        raise ValueError("unavailable evidence identity is invalid")
    reason = document.get("reason")
    if not isinstance(reason, str) or SAFE_ID.fullmatch(reason) is None:
        raise ValueError("unavailable evidence reason is invalid")
    sources = document.get("available_sources")
    if not isinstance(sources, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in sources.items()
    ):
        raise ValueError("unavailable evidence sources are invalid")
    base_fields = {
        "schema_version",
        "kind",
        "artifact_kind",
        "status",
        "run_id",
        "arm",
        "reason",
        "available_sources",
    }
    summary_fields = {"job_summary", "stability"}
    if frozenset(document) not in {frozenset(base_fields), frozenset(base_fields | summary_fields)}:
        raise ValueError("unavailable evidence fields are invalid")
    if "job_summary" in document:
        summary = validate_summary(document["job_summary"])
        terminal = summary["todo"] == 0 and summary["doing"] == 0
        failure_rate = (summary["failed"] + summary["cancelled"]) / summary["total"]
        expected_stability = {
            "status": "PASS" if terminal and failure_rate <= 0.10 else "FAIL" if terminal else "NOT_MEASURED",
            "failed_or_cancelled_rate": failure_rate if terminal else None,
        }
        if document["stability"] != expected_stability:
            raise ValueError("unavailable evidence stability is invalid")


def finalize(args: argparse.Namespace) -> list[Path]:
    for value in (args.run_id, args.arm, args.reason):
        if SAFE_ID.fullmatch(value) is None:
            raise ValueError("run id, arm, and reason must use the safe identifier grammar")
    sources: dict[str, str] = {}
    summary_document: dict[str, Any] | None = None
    if args.job_summary_path.is_file():
        summary_document = json.loads(args.job_summary_path.read_text(encoding="utf-8"))
        if (
            not isinstance(summary_document, dict)
            or summary_document.get("run_id") != args.run_id
            or summary_document.get("arm") != args.arm
        ):
            raise ValueError("job summary identity is invalid")
        validate_summary(summary_document.get("job_summary"))
        sources["job_summary"] = display_path(args.job_summary_path)

    observed = _read_statuses(args.statuses_path, args.run_id)
    children = []
    for index, script in enumerate(E2E_SCRIPTS, start=1):
        children.append(
            observed.get(
                script,
                {
                    "script": script,
                    "child_run_id": f"{args.run_id}.e2e.{index:02d}",
                    "status": "NOT_MEASURED",
                    "reason": args.reason,
                },
            )
        )

    created: list[Path] = []
    paths = {
        "metrics": args.metrics_path,
        "recall": args.recall_path,
        "e2e_manifest": args.manifest_path,
        "skip_events": args.skip_events_path,
        "quality_sample": args.sample_path,
        "report": args.report_json_path,
    }
    for kind, path in paths.items():
        if path.exists() or path.is_symlink():
            sources[kind] = display_path(path)
            continue
        payload = _marker(kind, args.run_id, args.arm, args.reason, dict(sources))
        if kind == "metrics" and summary_document is not None:
            payload["job_summary"] = summary_document["job_summary"]
            payload["stability"] = summary_document["stability"]
        if kind == "e2e_manifest":
            payload["children"] = children
        atomic_write_json(path, payload)
        created.append(path)
        sources[kind] = display_path(path)

    if not args.report_md_path.exists() and not args.report_md_path.is_symlink():
        text = (
            f"# Stage 7 partial report: {args.arm}\n\n"
            f"Status: NOT_MEASURED\n\nRun ID: `{args.run_id}`\n\nReason: `{args.reason}`\n\n"
            "No missing numeric value, graph sample row, or child execution was inferred.\n"
        )
        atomic_write_text(args.report_md_path, text)
        created.append(args.report_md_path)
    return created


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    summary = subparsers.add_parser("record-summary")
    summary.add_argument("--path", type=Path, required=True)
    summary.add_argument("--run-id", required=True)
    summary.add_argument("--arm", required=True)
    summary.add_argument("--summary", required=True)

    unavailable = subparsers.add_parser("write-unavailable")
    unavailable.add_argument("--path", type=Path, required=True)
    unavailable.add_argument("--kind", required=True)
    unavailable.add_argument("--run-id", required=True)
    unavailable.add_argument("--arm", required=True)
    unavailable.add_argument("--reason", required=True)
    unavailable.add_argument("--source", action="append", default=[])
    unavailable.add_argument("--job-summary-path", type=Path)

    validate = subparsers.add_parser("validate-unavailable")
    validate.add_argument("--path", type=Path, required=True)
    validate.add_argument("--kind", required=True)
    validate.add_argument("--run-id", required=True)
    validate.add_argument("--arm", required=True)

    partial = subparsers.add_parser("finalize")
    partial.add_argument("--run-id", required=True)
    partial.add_argument("--arm", required=True)
    partial.add_argument("--reason", required=True)
    partial.add_argument("--job-summary-path", type=Path, required=True)
    partial.add_argument("--metrics-path", type=Path, required=True)
    partial.add_argument("--recall-path", type=Path, required=True)
    partial.add_argument("--manifest-path", type=Path, required=True)
    partial.add_argument("--skip-events-path", type=Path, required=True)
    partial.add_argument("--sample-path", type=Path, required=True)
    partial.add_argument("--report-json-path", type=Path, required=True)
    partial.add_argument("--report-md-path", type=Path, required=True)
    partial.add_argument("--statuses-path", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "record-summary":
            for value in (args.run_id, args.arm):
                if SAFE_ID.fullmatch(value) is None:
                    raise ValueError("run id and arm must use the safe identifier grammar")
            write_job_summary(args.path, args.run_id, args.arm, validate_summary(json.loads(args.summary)))
            print(args.path)
        elif args.command == "write-unavailable":
            for value in (args.run_id, args.arm, args.reason, args.kind):
                if SAFE_ID.fullmatch(value) is None:
                    raise ValueError("partial evidence identifiers must use the safe identifier grammar")
            if not args.path.exists() and not args.path.is_symlink():
                sources = {
                    f"source_{index}": display_path(Path(value)) for index, value in enumerate(args.source, start=1)
                }
                payload = _marker(args.kind, args.run_id, args.arm, args.reason, sources)
                if args.job_summary_path is not None and args.job_summary_path.is_file():
                    summary_document = json.loads(args.job_summary_path.read_text(encoding="utf-8"))
                    if (
                        not isinstance(summary_document, dict)
                        or summary_document.get("run_id") != args.run_id
                        or summary_document.get("arm") != args.arm
                    ):
                        raise ValueError("job summary identity is invalid")
                    validate_summary(summary_document.get("job_summary"))
                    payload["job_summary"] = summary_document["job_summary"]
                    payload["stability"] = summary_document["stability"]
                atomic_write_json(args.path, payload)
                print(args.path)
        elif args.command == "validate-unavailable":
            validate_unavailable(args.path, args.kind, args.run_id, args.arm)
        else:
            for path in finalize(args):
                print(path)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"stage7 partial evidence: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
