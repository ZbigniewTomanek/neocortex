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
    parser.add_argument("--owned-workload", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--owned-receipt", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--capture-services", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--verify-services", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--group-receipt", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--service-receipt", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--pid-file", type=Path, action="append", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--status", type=Path, help="Incremental supervisor status JSON")
    parser.add_argument("--run-id")
    parser.add_argument("--arm")
    parser.add_argument("--workload-seconds", type=float, default=DEFAULT_WORKLOAD_SECONDS)
    parser.add_argument("--total-seconds", type=float, default=DEFAULT_TOTAL_SECONDS)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def _process_start(pid: int) -> str:
    return subprocess.check_output(["ps", "-o", "lstart=", "-p", str(pid)], text=True).strip()


def capture_services(group_receipt: Path, service_receipt: Path, pid_files: list[Path]) -> None:
    group = json.loads(group_receipt.read_text(encoding="utf-8"))
    pgid = group.get("process_group")
    if type(pgid) is not int or pgid <= 1 or len(pid_files) != 2:
        raise ValueError("owned service group receipt is invalid")
    services = []
    for pid_file in pid_files:
        raw_pid = pid_file.read_text(encoding="utf-8").strip()
        if not raw_pid.isdigit():
            raise ValueError("owned service pid receipt is invalid")
        pid = int(raw_pid)
        if pid <= 1 or os.getpgid(pid) != pgid:
            raise ValueError("service does not belong to the owned process group")
        services.append({"pid_file": str(pid_file), "pid": pid, "process_start": _process_start(pid)})
    _write_status(
        service_receipt,
        {"schema_version": 1, "process_group": pgid, "services": services},
    )


def verify_services(service_receipt: Path) -> int:
    receipt = json.loads(service_receipt.read_text(encoding="utf-8"))
    pgid = receipt.get("process_group")
    services = receipt.get("services")
    if type(pgid) is not int or pgid <= 1 or not isinstance(services, list) or len(services) != 2:
        raise ValueError("owned service receipt is invalid")
    for service in services:
        if not isinstance(service, dict):
            raise ValueError("owned service entry is invalid")
        pid = service.get("pid")
        pid_file = service.get("pid_file")
        process_start = service.get("process_start")
        if type(pid) is not int or not isinstance(pid_file, str) or not isinstance(process_start, str):
            raise ValueError("owned service identity is invalid")
        if Path(pid_file).read_text(encoding="utf-8").strip() != str(pid):
            raise ValueError("owned service pid file changed")
        if os.getpgid(pid) != pgid or _process_start(pid) != process_start:
            raise ValueError("owned service process identity changed")
    return pgid


def run_owned_workload(command: list[str], receipt_path: Path | None = None) -> int:
    """Run one workload in its own group and relay one control signal to it."""
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise ValueError("a command is required after --")

    process = subprocess.Popen(command, start_new_session=True)
    if receipt_path is not None:
        _write_status(receipt_path, {"schema_version": 1, "process_group": process.pid})
    forwarded_signal: int | None = None

    def forward_once(signum: int, _frame: object) -> None:
        nonlocal forwarded_signal
        if forwarded_signal is not None:
            return
        forwarded_signal = signum
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signum)

    previous_term = signal.signal(signal.SIGTERM, forward_once)
    previous_int = signal.signal(signal.SIGINT, forward_once)
    try:
        return_code = process.wait()
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)
    return return_code if return_code >= 0 else 128 - return_code


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
    recovery_marker = status_path.with_name(f".{status_path.name}.recovery")
    with contextlib.suppress(FileNotFoundError):
        recovery_marker.unlink()
    child_environment.update(
        {
            "NEOCORTEX_BAKEOFF_RUN_ID": run_id,
            "NEOCORTEX_BAKEOFF_ARM": arm,
            "NEOCORTEX_BAKEOFF_RECOVERY_MARKER": str(recovery_marker),
        }
    )
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
        if forwarded_signal is not None:
            return
        forwarded_signal = signum
        if recovery_marker.exists():
            return
        with contextlib.suppress(ProcessLookupError):
            # The bake-off owns and stops its active workload group.  Signal
            # only its control process so snapshot restoration never shares a
            # supervisor-signalled process group.
            os.kill(process.pid, signum)

    previous_term = signal.signal(signal.SIGTERM, forward_signal)
    previous_int = signal.signal(signal.SIGINT, forward_signal)

    timed_out = False
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
        if forwarded_signal is None and not recovery_marker.exists():
            forwarded_signal = signal.SIGTERM
            with contextlib.suppress(ProcessLookupError):
                os.kill(process.pid, signal.SIGTERM)
        # Recovery is mandatory. Never SIGKILL an in-progress snapshot load
        # to make the outer budget look green.
        return_code = process.wait()

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
    status["recovery_started"] = recovery_marker.exists()
    try:
        _write_status(status_path, status)
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)
        with contextlib.suppress(FileNotFoundError):
            recovery_marker.unlink()
    return return_code if return_code >= 0 else 125


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.owned_workload:
            return run_owned_workload(args.command, args.owned_receipt)
        if args.capture_services:
            if args.group_receipt is None or args.service_receipt is None:
                raise ValueError("service capture receipts are required")
            capture_services(args.group_receipt, args.service_receipt, args.pid_file)
            return 0
        if args.verify_services:
            if args.service_receipt is None:
                raise ValueError("service receipt is required")
            print(verify_services(args.service_receipt))
            return 0
        if args.status is None or args.run_id is None or args.arm is None:
            raise ValueError("--status, --run-id, and --arm are required")
        return supervise(args.command, args.status, args.run_id, args.arm, args.workload_seconds, args.total_seconds)
    except (OSError, ValueError) as exc:
        print(f"stage7 supervisor: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
