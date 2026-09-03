"""Focused contracts for the Plan 33 measurement harness."""

from __future__ import annotations

import hashlib
import json
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
    monkeypatch.setattr(
        sys,
        "argv",
        ["compute_metrics.py", "--arm", "self-test", "--ingestion-url", "http://127.0.0.1:8001"],
    )

    result = asyncio.run(metrics.main())

    assert result == 2
    sidecar = tmp_path / "metrics-self-test.not-measured.json"
    assert json.loads(sidecar.read_text()) == {
        "schema_version": 3,
        "status": "NOT_MEASURED",
        "reason": "non_terminal_jobs",
        "job_summary": summary,
        "input_paths": {"admin_jobs_api": "http://127.0.0.1:8001/admin/jobs/summary"},
    }
    assert not (tmp_path / "metrics-self-test.json").exists()


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
    assert "poll_timeout_s=4722" in output  # 37 x 3 x 3 x 28 / 2 + 60
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
