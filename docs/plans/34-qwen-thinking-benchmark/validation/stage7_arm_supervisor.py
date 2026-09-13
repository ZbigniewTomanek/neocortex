#!/usr/bin/env python3
"""Run one Stage 7 arm in an isolated process group with a cleanup reserve."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_WORKLOAD_SECONDS = 6_600.0
DEFAULT_TOTAL_SECONDS = 7_200.0
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(payload, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary_name)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", type=Path, required=True, help="Incremental supervisor status JSON")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--arm", required=True)
    parser.add_argument("--workload-seconds", type=float, default=DEFAULT_WORKLOAD_SECONDS)
    parser.add_argument("--total-seconds", type=float, default=DEFAULT_TOTAL_SECONDS)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def supervise(
    command: list[str], status_path: Path, run_id: str, arm: str, workload_seconds: float, total_seconds: float
) -> int:
    if not command:
        raise ValueError("a command is required after --")
    if command[0] == "--":
        command = command[1:]
    if not command:
        raise ValueError("a command is required after --")
    if workload_seconds <= 0 or total_seconds <= workload_seconds:
        raise ValueError("total seconds must exceed positive workload seconds")
    if SAFE_ID.fullmatch(run_id) is None or SAFE_ID.fullmatch(arm) is None:
        raise ValueError("run id and arm must use the safe identifier grammar")

    started = time.monotonic()
    status: dict[str, Any] = {
        "schema_version": 1,
        "status": "RUNNING",
        "run_id": run_id,
        "arm": arm,
        "started_at": _utc_now(),
        "workload_budget_seconds": workload_seconds,
        "cleanup_reserve_seconds": total_seconds - workload_seconds,
        "total_budget_seconds": total_seconds,
        "timed_out": False,
    }
    _write_status(status_path, status)
    child_environment = os.environ.copy()
    child_environment.update({"NEOCORTEX_BAKEOFF_RUN_ID": run_id, "NEOCORTEX_BAKEOFF_ARM": arm})
    process = subprocess.Popen(command, env=child_environment, start_new_session=True)
    status["owned_process_group"] = process.pid
    try:
        _write_status(status_path, status)
    except OSError:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        process.wait()
        raise

    forwarded_signal: int | None = None

    def forward_signal(signum: int, _frame: object) -> None:
        nonlocal forwarded_signal
        forwarded_signal = signum
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signum)

    previous_term = signal.signal(signal.SIGTERM, forward_signal)
    previous_int = signal.signal(signal.SIGINT, forward_signal)

    timed_out = False
    try:
        try:
            return_code = process.wait(timeout=workload_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            workload_wall = time.monotonic() - started
            status.update(
                {
                    "status": "CLEANUP",
                    "timed_out": True,
                    "workload_stopped_at": _utc_now(),
                    "workload_wall_seconds": workload_wall,
                }
            )
            _write_status(status_path, status)
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            # Recovery is mandatory. Never SIGKILL an in-progress snapshot load
            # to make the outer budget look green.
            return_code = process.wait()
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)

    total_wall = time.monotonic() - started
    status.update(
        {
            "status": (
                "TIMEOUT"
                if timed_out and return_code == 124
                else (
                    "INTERRUPTED"
                    if forwarded_signal is not None and return_code in {124, 130}
                    else "COMPLETED" if return_code == 0 else "FAILED"
                )
            ),
            "finished_at": _utc_now(),
            "return_code": return_code,
            "workload_wall_seconds": status.get("workload_wall_seconds", total_wall),
            "total_wall_seconds": total_wall,
            "cleanup_reserve_exceeded": total_wall > total_seconds,
        }
    )
    if forwarded_signal is not None:
        status["forwarded_signal"] = signal.Signals(forwarded_signal).name
    _write_status(status_path, status)
    return return_code if return_code >= 0 else 125


def main() -> int:
    args = _parser().parse_args()
    try:
        return supervise(args.command, args.status, args.run_id, args.arm, args.workload_seconds, args.total_seconds)
    except (OSError, ValueError) as exc:
        print(f"stage7 supervisor: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
