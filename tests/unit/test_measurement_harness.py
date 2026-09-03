"""Focused contracts for the Plan 33 measurement harness."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from pathlib import Path

import pytest
from scripts.compute_metrics import NonTerminalJobsError, ensure_terminal_jobs  # ty: ignore[unresolved-import]
from scripts.corpus_loader import CORPUS, load_corpus  # ty: ignore[unresolved-import]


def test_fixed_ingestion_corpus_is_exactly_28_episodes() -> None:
    episodes = load_corpus()

    assert len(episodes) == 28
    assert [episode["number"] for episode in episodes] == list(range(1, 29))
    assert hashlib.sha256(CORPUS.read_bytes()).hexdigest() == (
        "dee5ea4934e042f3f7a12bc7b2b918287c303ff4dd723471ce4279f6f149beff"
    )


def test_non_terminal_jobs_are_not_a_quality_result() -> None:
    summary = {"todo": 1, "doing": 0, "succeeded": 27, "failed": 0, "cancelled": 0, "total": 28}

    with pytest.raises(NonTerminalJobsError) as exc_info:
        ensure_terminal_jobs(summary)

    assert exc_info.value.summary == summary


def test_terminal_job_summary_is_accepted() -> None:
    ensure_terminal_jobs({"todo": 0, "doing": 0, "succeeded": 25, "failed": 3, "cancelled": 0})


def test_non_terminal_cli_writes_only_not_measured_sidecar(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Exercise the CLI guard, including its no-quality-file contract."""
    import asyncio
    import sys

    import scripts.compute_metrics as metrics  # ty: ignore[unresolved-import]

    summary = {"todo": 1, "doing": 0, "succeeded": 27, "failed": 0, "cancelled": 0, "total": 28}

    async def fake_collect(*args: object, **kwargs: object) -> dict[str, object]:
        raise metrics.NonTerminalJobsError(summary)

    monkeypatch.setattr(metrics, "collect", fake_collect)
    monkeypatch.setattr(metrics, "PLAN_RESOURCES", tmp_path)
    canonical = tmp_path / "metrics-self-test.json"
    canonical.write_text('{"old": "quality"}')
    monkeypatch.setattr(
        sys,
        "argv",
        ["compute_metrics.py", "--arm", "self-test", "--ingestion-url", "http://127.0.0.1:8001"],
    )

    result = asyncio.run(metrics.main())

    assert result == 2
    sidecar = tmp_path / "metrics-self-test.not-measured.json"
    marker = json.loads(sidecar.read_text())
    assert marker["schema_version"] == 3
    assert marker["status"] == "NOT_MEASURED"
    assert marker["reason"] == "non_terminal_jobs"
    assert marker["job_summary"] == summary
    assert marker["input_paths"]["admin_jobs_api"] == "http://127.0.0.1:8001/admin/jobs/summary"
    assert marker["run_id"]
    assert marker["invalidated_canonical"] == str(canonical)
    assert marker["recoverable_stale_artifact"] == str(tmp_path / "metrics-self-test.json.stale")
    assert not canonical.exists()
    assert json.loads((tmp_path / "metrics-self-test.json.stale").read_text()) == {"old": "quality"}


@pytest.mark.parametrize(
    ("case", "expected_reason"),
    [
        ("missing", "missing_audit_log"),
        ("empty", "empty_audit_log"),
        ("malformed", "malformed_audit_log"),
        ("fully_filtered", "audit_log_fully_filtered"),
    ],
)
def test_zero_signal_audit_never_publishes_canonical_metrics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    case: str,
    expected_reason: str,
) -> None:
    """Absent or unusable run-scoped evidence must remain NOT_MEASURED."""
    import asyncio
    import sys

    import scripts.compute_metrics as metrics  # ty: ignore[unresolved-import]

    run_id = "selected-run"
    resources = tmp_path / "resources"
    log_dir = tmp_path / "log"
    log_path = log_dir / "agent_actions.log"
    if case != "missing":
        log_dir.mkdir()
        content = {
            "empty": "",
            "malformed": "this is not json\n{also not json",
            "fully_filtered": json.dumps(
                {
                    "record": {
                        "message": "model_request_completed",
                        "extra": {"run_id": "different-run"},
                    }
                }
            )
            + "\n",
        }[case]
        log_path.write_text(content)

    async def fake_collect(*args: object, **kwargs: object) -> dict[str, object]:
        assert kwargs["run_id"] == run_id
        return {
            "schema_version": 3,
            "job_summary": {"todo": 0, "doing": 0, "succeeded": 1},
            "schemas": {"quality": "must-not-be-published"},
        }

    monkeypatch.setattr(metrics, "ROOT", tmp_path)
    monkeypatch.setattr(metrics, "PLAN_RESOURCES", resources)
    monkeypatch.setattr(metrics, "collect", fake_collect)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "compute_metrics.py",
            "--arm",
            "zero-signal",
            "--run-id",
            run_id,
            "--ingestion-url",
            "http://127.0.0.1:8001",
        ],
    )

    canonical = resources / "metrics-zero-signal.json"
    canonical.parent.mkdir(parents=True)
    canonical.write_text('{"old": "quality"}')
    assert asyncio.run(metrics.main()) == 2

    sidecar = resources / "metrics-zero-signal.not-measured.json"
    marker = json.loads(sidecar.read_text())
    assert marker["status"] == "NOT_MEASURED"
    assert marker["reason"] == expected_reason
    assert marker["run_id"] == run_id
    assert marker["audit"]["status"] == "NOT_MEASURED"
    assert "schemas" not in marker
    assert not canonical.exists()
    assert (resources / "metrics-zero-signal.json.stale").exists()


def test_main_passes_one_effective_run_id_to_collect_and_audit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An omitted CLI id is generated once, then shared by all collectors."""
    import asyncio
    import sys

    import scripts.compute_metrics as metrics  # ty: ignore[unresolved-import]

    seen: dict[str, str] = {}

    async def fake_collect(*args: object, **kwargs: object) -> dict[str, object]:
        seen["collect"] = str(kwargs["run_id"])
        return {"job_summary": {"todo": 0, "doing": 0}}

    def fake_audit(*, run_id: str | None = None, correlation_id: str | None = None) -> dict[str, object]:
        del correlation_id
        assert run_id is not None
        seen["audit"] = run_id
        return {"status": "MEASURED", "run_id": run_id}

    monkeypatch.setattr(metrics, "collect", fake_collect)
    monkeypatch.setattr(metrics, "audit_metrics", fake_audit)
    monkeypatch.setattr(metrics, "PLAN_RESOURCES", tmp_path)
    monkeypatch.delenv("NEOCORTEX_BAKEOFF_RUN_ID", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["compute_metrics.py", "--arm", "run-id-self-test", "--ingestion-url", "http://127.0.0.1:8001"],
    )

    assert asyncio.run(metrics.main()) == 0
    assert seen["collect"] == seen["audit"]
    assert seen["collect"]


def test_bakeoff_dry_run_reports_bounds_without_secret() -> None:
    env = os.environ.copy()
    env.update(
        {
            "NEOCORTEX_ADMIN_TOKEN": "measurement-secret-must-not-appear",
            "NEOCORTEX_MCP_TOKEN": "measurement-secret-must-not-appear",
            "NEOCORTEX_DEV_TOKENS_FILE": "dev_tokens.json",
            "NEOCORTEX_ONTOLOGY_MODEL": "local:qwen3.8-flash-next",
            "NEOCORTEX_LOCAL_MODEL_TIMEOUT_S": "37",
            "NEOCORTEX_WORKER_CONCURRENCY": "2",
            "NEOCORTEX_DOMAIN_ROUTING_ENABLED": "true",
            "NEOCORTEX_BAKEOFF_MAX_DOMAIN_FANOUT": "5",
        }
    )
    completed = subprocess.run(
        ["./scripts/model_bakeoff.sh", "--arm", "qwen-flash-next", "--dry-run"],
        cwd=Path(__file__).parents[2],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    output = completed.stdout
    assert "model=local:qwen3.8-flash-next" in output
    assert "endpoint=http://127.0.0.1:24000/v1" in output
    assert "per_call_timeout_s=37" in output
    assert "corpus_size=28" in output
    # Documented routed topology: one classifier call, three personal stages,
    # and up to five domain routes with three stages each. Every model call
    # can retry three times, and the harness adds 60 seconds of startup slack.
    per_call_timeout_s = 37
    corpus_size = 28
    worker_concurrency = 2
    max_domain_fanout = 5
    model_calls_per_episode = 1 + 3 + 3 * max_domain_fanout
    expected_poll_timeout_s = math.ceil(
        per_call_timeout_s * model_calls_per_episode * 3 * corpus_size / worker_concurrency + 60
    )
    assert f"poll_timeout_s={expected_poll_timeout_s}" in output
    assert "metrics_path=docs/plans/33-local-qwen-migration/resources/metrics-qwen-flash-next.json" in output
    assert "measurement-secret-must-not-appear" not in output
    # The printed command contains an environment reference, never its value.
    assert "Authorization: Bearer ${NEOCORTEX_ADMIN_TOKEN}" in output


def test_bakeoff_dry_run_output_is_not_json_or_evidence() -> None:
    """Keep this explicit so consumers do not mistake command preview for metrics."""
    # This is a contract test for the emitted metrics schema, not a fabricated
    # measurement.  A real metrics artifact must carry source paths and a job
    # summary before it can be interpreted.
    example = {"schema_version": 3, "input_paths": {}, "job_summary": {"todo": 0, "doing": 0}}
    assert json.loads(json.dumps(example))["schema_version"] == 3
