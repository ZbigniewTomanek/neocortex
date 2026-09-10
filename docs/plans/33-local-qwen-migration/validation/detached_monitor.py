"""Keep read-only benchmark evidence collection alive outside the chat session."""

import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
RECEIPT = HERE / "stage6-active-run.json"
STATUS = HERE / "stage6-detached-status.json"


def process_start(pid):
    return subprocess.run(["ps", "-p", str(pid), "-o", "lstart="], capture_output=True, text=True).stdout.strip()


def save(status):
    status["updated_at_utc"] = datetime.now(UTC).isoformat()
    temporary = STATUS.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(status, indent=2) + "\n")
    temporary.replace(STATUS)


def main():
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    receipt = json.loads(RECEIPT.read_text())
    pid = receipt["pid"]
    expected_start = receipt["harness_process_start"]
    command = [sys.executable, str(HERE / "capture_stage6.py"), "--run-id", receipt["run_id"]]
    watcher = subprocess.Popen(
        [*command, "--watch-terminal", "--watch-max-seconds", "86400"],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
    )
    status = {
        "run_id": receipt["run_id"],
        "harness_pid": pid,
        "monitor_pid": os.getpid(),
        "terminal_watcher_pid": watcher.pid,
        "status": "RUNNING",
        "periodic_capture_enabled": True,
        "result_status": "NOT MEASURED",
        "capture_interval_s": 60,
    }
    expected_keys = {"E02", "E04", "E05", "E10", "E18", "E20", "E26", "E27"}
    start = datetime.fromisoformat(receipt["start_utc"])
    try:
        while process_start(pid) == expected_start:
            status["terminal_watcher_exit_code"] = watcher.poll()
            if status["periodic_capture_enabled"]:
                try:
                    captured = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=90)
                    status["last_capture_exit_code"] = captured.returncode
                    if captured.returncode == 0:
                        result = json.loads(captured.stdout.strip().splitlines()[-1])
                        artifact = json.loads((ROOT / result["path"]).read_text())
                        mapped = {e["episode_key"] for e in artifact["episodes"]} == expected_keys
                        mapped = mapped and all(
                            datetime.fromisoformat(e["created_at"]) >= start for e in artifact["episodes"]
                        )
                        if mapped:
                            status["latest_corpus_capture"] = result["path"]
                            status["last_corpus_summary"] = result["summary"]
                            status["last_corpus_nodes"] = result["nodes"]
                            status["last_corpus_edges"] = result["edges"]
                            if result["summary"].get("todo") == 0 and result["summary"].get("doing") == 0:
                                status["periodic_capture_enabled"] = False
                        else:
                            status["periodic_capture_enabled"] = False
                            status["corpus_replaced"] = True
                except Exception as exc:
                    status["last_capture_error_type"] = type(exc).__name__
            save(status)
            time.sleep(60)
        status["status"] = "HARNESS_EXITED_REVIEW_REQUIRED"
        status["harness_exit_code"] = "NOT MEASURED: monitor is not its parent"
        status["result_status"] = "NOT MEASURED: inspect metrics, E2E manifest and restoration evidence on resume"
        metrics = ROOT / "docs/plans/33-local-qwen-migration/resources/metrics-qwen-flash-next-compact.json"
        status["canonical_metrics_present"] = metrics.exists()
        status["finished_observed_at_utc"] = datetime.now(UTC).isoformat()
    finally:
        if watcher.poll() is None:
            watcher.terminate()
            try:
                watcher.wait(timeout=10)
            except subprocess.TimeoutExpired:
                watcher.kill()
                watcher.wait()
        status["terminal_watcher_exit_code"] = watcher.poll()
        save(status)


if __name__ == "__main__":
    main()
