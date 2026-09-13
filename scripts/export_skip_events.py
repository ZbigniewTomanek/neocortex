#!/usr/bin/env python3
"""Export the librarian's edge-skip events as a committed, privacy-safe artifact.

``oneshot_librarian._apply`` already records every skipped edge with full
identifiers, but only to ``log/agent_actions.log``, which the evidence tooling
refuses to read because it is private.  This exporter lifts the two skip events
out of that log under a strict field allowlist so a run's integrity gaps can be
attributed from a committed file.

Nothing here touches PostgreSQL or a model endpoint.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

try:  # Package import (tests, ``python -m``).
    from scripts.compute_metrics import (  # ty: ignore[unresolved-import]
        _atomic_write_json,
        _audit_log_paths,
        _read_audit_logs,
        _relative_path,
    )
    from scripts.generate_qwen_parsing_report import (  # ty: ignore[unresolved-import]
        ReportError,
        _validate_safe_content,
    )
except ModuleNotFoundError:  # Direct script execution.
    from compute_metrics import (  # ty: ignore[unresolved-import]
        _atomic_write_json,
        _audit_log_paths,
        _read_audit_logs,
        _relative_path,
    )
    from generate_qwen_parsing_report import ReportError, _validate_safe_content  # ty: ignore[unresolved-import]

SCHEMA_VERSION = 1
KIND = "neocortex-skip-events"

# Event name -> the ``reason_code`` the exported row carries.
SKIP_EVENTS = {
    "edge_skipped_missing_node": "missing_node",
    "edge_skipped_temporal_pair": "temporal_pair",
}

# The complete set of keys an exported event may carry.  Nothing outside this
# tuple is ever written, whatever the source record holds.
ALLOWED_EVENT_FIELDS = (
    "reason_code",
    "episode_id",
    "correlation_id",
    "stage",
    "source_present",
    "target_present",
    "source_id",
    "target_id",
    "timestamp",
    "survived",
)

# ``build_audit_fields`` falls back to this literal when the worker did not
# export ``NEOCORTEX_BAKEOFF_RUN_ID``.  Such records cannot be attributed to a
# run, and "cannot be attributed" is a different answer from "zero skips".
UNAVAILABLE_RUN_ID = "unavailable"

# A record key outside the allowlist is graph text if it is long or if its name
# reads like a text carrier.  Either one refuses the whole export.
TEXT_KEY_MARKERS = ("name", "content", "description", "text", "title")
MAX_UNLISTED_STRING_LENGTH = 40

_SAFE_STAGE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_SAFE_CORRELATION_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SAFE_TIMESTAMP = re.compile(r"^[0-9A-Za-z:+. -]{1,64}$")

# ``generate_qwen_parsing_report.privacy_scan`` is NOT reusable here: its
# signature is ``privacy_scan(paths: list[Path], output: Path)`` and it hard
# codes the parsing report's five-file layout plus a table of expected-nonzero
# comparison counts.  Only ``_validate_safe_content`` is general enough to
# reuse.  That scanner does, however, treat ``"correlation_id":`` as a
# forbidden key, because the Stage 7 *report* must not publish correlation ids.
# This artifact must: the allowlist names ``correlation_id`` so a skip can be
# tied back to one extraction run.  So the scan runs over a view of the
# document with that one key removed, and every correlation id is validated
# separately against an opaque-token regex.  Every other scanner category still
# applies to the full document.
_SCAN_EXEMPT_EVENT_FIELDS = ("correlation_id",)


class SkipEventError(ValueError):
    """Raised when skip evidence cannot be exported safely or truthfully."""


def _unsafe_key(key: str, value: Any) -> bool:
    """Return True when an unlisted record key may carry graph text."""
    if any(marker in key.casefold() for marker in TEXT_KEY_MARKERS):
        return True
    return isinstance(value, str) and len(value) > MAX_UNLISTED_STRING_LENGTH


def iter_audit_records(lines: list[str]) -> Iterator[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Yield ``(event, extra, record)`` for every well-formed action-log line.

    The parse mirrors ``compute_metrics.audit_metrics`` so the two agree on
    what a record is; malformed lines are skipped, exactly as there.
    """
    for line in lines:
        try:
            payload = json.loads(line)
        except (ValueError, TypeError):
            continue
        record = payload.get("record") if isinstance(payload, dict) else None
        if not isinstance(record, dict):
            continue
        extra = record.get("extra")
        if not isinstance(extra, dict):
            continue
        message = record.get("message", "")
        if not isinstance(message, str):
            message = str(message)
        event_value = extra.get("event") or message.split(" ", 1)[0]
        event = str(event_value) if event_value else ""
        if not event:
            continue
        yield event, extra, record


def select_candidates(lines: list[str]) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Return every skip-event record in the log, before any run filtering."""
    return [item for item in iter_audit_records(lines) if item[0] in SKIP_EVENTS]


def _require_int_or_none(value: Any, key: str) -> int | None:
    if value is None or (isinstance(value, int) and not isinstance(value, bool)):
        return value
    raise SkipEventError(f"skip event field is not an integer identifier: {key}")


def _require_bool_or_none(value: Any, key: str) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    raise SkipEventError(f"skip event field is not a boolean: {key}")


def _require_pattern(value: Any, key: str, pattern: re.Pattern[str]) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and pattern.fullmatch(value):
        return value
    raise SkipEventError(f"skip event field is not a safe opaque token: {key}")


def shape_event(event: str, extra: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    """Project one audit record onto the allowlist, refusing anything else.

    ``edge_skipped_temporal_pair`` logs no ``source_present`` / ``target_present``
    (verified in ``oneshot_librarian._apply``), so those two keys stay ``null``
    on temporal rows.  Synthesising ``true`` there would invent evidence.
    """
    expected_reason = SKIP_EVENTS[event]
    logged_reason = extra.get("reason_code")
    if logged_reason is not None and logged_reason != expected_reason:
        raise SkipEventError(f"skip event reason_code does not match its event name: {event}")
    for key, value in extra.items():
        if key in ALLOWED_EVENT_FIELDS or key in {"event", "action_log"}:
            continue
        if _unsafe_key(key, value):
            # Name the key, never its value: the value is what may be unsafe.
            raise SkipEventError(f"skip event carries an unsafe field: {key}")
    time_block = record.get("time")
    timestamp = time_block.get("repr") if isinstance(time_block, dict) else None
    row = {
        "reason_code": expected_reason,
        "episode_id": _require_int_or_none(extra.get("episode_id"), "episode_id"),
        "correlation_id": _require_pattern(extra.get("correlation_id"), "correlation_id", _SAFE_CORRELATION_ID),
        "stage": _require_pattern(extra.get("stage"), "stage", _SAFE_STAGE),
        "source_present": _require_bool_or_none(extra.get("source_present"), "source_present"),
        "target_present": _require_bool_or_none(extra.get("target_present"), "target_present"),
        "source_id": _require_int_or_none(extra.get("source_id"), "source_id"),
        "target_id": _require_int_or_none(extra.get("target_id"), "target_id"),
        "timestamp": _require_pattern(timestamp, "timestamp", _SAFE_TIMESTAMP),
    }
    if expected_reason == "temporal_pair":
        # Only a temporal pair can survive as a SUPERSEDES/CORRECTS edge.
        # ``export_graph_sample.py --check-temporal`` fills this in; until it
        # runs the answer is unknown, never ``false``.
        row["survived"] = None
    return row


def _scan_view(document: dict[str, Any]) -> dict[str, Any]:
    """Return the document with scan-exempt identifier keys dropped."""
    events = document.get("events")
    if not isinstance(events, list):
        return document
    return {
        **document,
        "events": [
            {key: value for key, value in event.items() if key not in _SCAN_EXEMPT_EVENT_FIELDS} for event in events
        ],
    }


def validate_document(document: dict[str, Any]) -> None:
    """Refuse to publish a document the shared privacy scanner rejects."""
    for event in document.get("events", []):
        unexpected = set(event) - set(ALLOWED_EVENT_FIELDS)
        if unexpected:
            raise SkipEventError(f"skip event carries an unsafe field: {sorted(unexpected)[0]}")
    try:
        _validate_safe_content(_scan_view(document))
    except ReportError as exc:
        raise SkipEventError("skip events failed the shared privacy scan") from exc


def build_document(
    lines: list[str],
    *,
    run_id: str,
    arm: str,
    source_paths: list[str],
) -> dict[str, Any]:
    """Assemble the skip-events document for one run, or say why it cannot be."""
    base: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "run_id": run_id,
        "arm": arm,
        "source_paths": source_paths,
    }
    candidates = select_candidates(lines)
    if run_id == UNAVAILABLE_RUN_ID or (
        candidates and all(item[1].get("run_id") == UNAVAILABLE_RUN_ID for item in candidates)
    ):
        # Every skip in the log was written by a worker without
        # ``NEOCORTEX_BAKEOFF_RUN_ID``.  Zero events and unattributable events
        # are different answers; do not let them collapse into one file.
        return {**base, "status": "NOT MEASURED", "reason": "run_id_unavailable"}
    events = [shape_event(event, extra, record) for event, extra, record in candidates if extra.get("run_id") == run_id]
    counts = {
        "missing_node": sum(row["reason_code"] == "missing_node" for row in events),
        "temporal_pair": sum(row["reason_code"] == "temporal_pair" for row in events),
    }
    return {**base, "status": "MEASURED", "counts": counts, "events": events}


def export(*, run_id: str, arm: str, output: Path) -> dict[str, Any]:
    """Write the skip-events artifact for one run and return the document."""
    paths, lines, read_error = _read_audit_logs()
    source_paths = [_relative_path(path) for path in paths]
    if not paths:
        document: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "kind": KIND,
            "run_id": run_id,
            "arm": arm,
            "source_paths": source_paths,
            "status": "NOT MEASURED",
            "reason": "missing_audit_log",
        }
    elif read_error:
        # A rotated member is part of the run's evidence; a partial read cannot
        # prove a complete count, so never publish one.
        document = {
            "schema_version": SCHEMA_VERSION,
            "kind": KIND,
            "run_id": run_id,
            "arm": arm,
            "source_paths": source_paths,
            "status": "NOT MEASURED",
            "reason": "unreadable_audit_log",
        }
    else:
        document = build_document(lines, run_id=run_id, arm=arm, source_paths=source_paths)
    validate_document(document)
    _atomic_write_json(output, document)
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--arm", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        document = export(run_id=args.run_id, arm=args.arm, output=args.output)
    except SkipEventError as exc:
        print(f"skip-event export refused: {exc}", file=sys.stderr)
        return 2
    print(f"{args.output} status={document['status']}")
    return 0


__all__ = [
    "ALLOWED_EVENT_FIELDS",
    "SKIP_EVENTS",
    "SkipEventError",
    "_audit_log_paths",
    "build_document",
    "export",
    "select_candidates",
    "shape_event",
    "validate_document",
]

if __name__ == "__main__":
    raise SystemExit(main())
