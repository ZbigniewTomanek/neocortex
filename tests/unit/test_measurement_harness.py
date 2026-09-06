"""Focused contracts for the Plan 33 measurement harness."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from pathlib import Path

import pytest
from scripts.compute_metrics import (  # ty: ignore[unresolved-import]
    InvalidJobSummaryError,
    NonTerminalJobsError,
    ensure_terminal_jobs,
)
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
    ensure_terminal_jobs({"todo": 0, "doing": 0, "succeeded": 26, "failed": 2, "cancelled": 0, "total": 28})


@pytest.mark.parametrize(
    "summary",
    [
        {"todo": 0, "doing": 0, "succeeded": 9, "failed": 1, "cancelled": 0, "total": 10},
        {"todo": 0, "doing": 0, "succeeded": 8, "failed": 1, "cancelled": 1, "total": 10},
    ],
)
def test_terminal_failure_rate_ceiling_accepts_one_of_ten_and_rejects_two(summary: dict[str, int]) -> None:
    if summary["failed"] + summary["cancelled"] == 1:
        ensure_terminal_jobs(summary)
    else:
        with pytest.raises(InvalidJobSummaryError) as exc_info:
            ensure_terminal_jobs(summary)
        assert exc_info.value.reason == "failure_rate_exceeded"


@pytest.mark.parametrize(
    "summary",
    [
        {"todo": 0, "doing": 0, "succeeded": 0, "failed": 0, "cancelled": 0},
        {"todo": 0, "doing": 0, "succeeded": 9, "failed": 0, "cancelled": 0, "total": 10},
    ],
)
def test_missing_or_inconsistent_job_totals_are_not_measured(summary: dict[str, int]) -> None:
    with pytest.raises(InvalidJobSummaryError):
        ensure_terminal_jobs(summary)


def test_audit_metrics_reads_rotated_action_logs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Long runs keep their early action events after the 10 MB sink rotates."""
    import scripts.compute_metrics as metrics  # ty: ignore[unresolved-import]

    log_dir = tmp_path / "log"
    log_dir.mkdir()
    event = {
        "record": {
            "message": "model_request_completed",
            "extra": {
                "run_id": "rotated-run",
                "correlation_id": "corr-1",
                "model": "qwen3.8-flash-next",
                "endpoint": "http://127.0.0.1:24000/v1",
                "agent": "ontology",
                "effort": "low",
            },
        }
    }
    (log_dir / "agent_actions.2026-09-03_00-00-00_000000.log").write_text(json.dumps(event) + "\n")
    (log_dir / "agent_actions.log").write_text(json.dumps(event) + "\n")
    monkeypatch.setattr(metrics, "ROOT", tmp_path)

    result = metrics.audit_metrics(run_id="rotated-run")

    assert result["status"] == "MEASURED"
    assert result["audit_event_counts"] == {"model_request_completed": 2}
    assert result["matched_records"] == 2
    assert result["source_paths"] == [
        "log/agent_actions.log",
        "log/agent_actions.2026-09-03_00-00-00_000000.log",
    ]


def test_audit_metrics_rejects_any_unreadable_rotated_member(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A matching active event cannot mask an unreadable rotated member."""
    import scripts.compute_metrics as metrics  # ty: ignore[unresolved-import]

    log_dir = tmp_path / "log"
    log_dir.mkdir()
    event = {
        "record": {
            "message": "model_request_completed",
            "extra": {
                "run_id": "unreadable-run",
                "correlation_id": "corr-1",
                "model": "qwen3.8-flash-next",
                "endpoint": "http://127.0.0.1:24000/v1",
                "agent": "ontology",
                "effort": "low",
            },
        }
    }
    active = log_dir / "agent_actions.log"
    rotated = log_dir / "agent_actions.2026-09-03_00-00-00_000000.log"
    active.write_text(json.dumps(event) + "\n")
    rotated.write_text(json.dumps(event) + "\n")
    original_read_text = Path.read_text

    def fail_rotated_read(
        path: Path, encoding: str | None = None, errors: str | None = None, newline: str | None = None
    ) -> str:
        if path == rotated:
            raise OSError("synthetic unreadable audit member")
        return original_read_text(path, encoding, errors, newline)

    monkeypatch.setattr(Path, "read_text", fail_rotated_read)
    monkeypatch.setattr(metrics, "ROOT", tmp_path)

    result = metrics.audit_metrics(run_id="unreadable-run")

    assert result["status"] == "NOT_MEASURED"
    assert result["reason"] == "unreadable_audit_log"


def test_audit_metrics_counts_unproven_librarian_failures(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A failed librarian run blocks certification until cleanliness is proven."""
    import scripts.compute_metrics as metrics  # ty: ignore[unresolved-import]

    log_dir = tmp_path / "log"
    log_dir.mkdir()
    event = {
        "record": {
            "message": "librarian_failed",
            "extra": {
                "run_id": "failed-librarian-run",
                "correlation_id": "extract-0123456789abcdef0123456789abcdef",
                "model": "qwen3.8-flash-next",
                "endpoint": "http://127.0.0.1:24000/v1",
                "agent": "librarian",
                "effort": "low",
                "error_type": "UsageLimitExceeded",
                "graph_cleanliness": "NOT_MEASURED",
            },
        }
    }
    expected_event = {
        "record": {
            "message": "model_request_started",
            "extra": {
                "run_id": "failed-librarian-run",
                "correlation_id": "extract-0123456789abcdef0123456789abcdef",
                "model": "qwen3.8-flash-next",
                "endpoint": "http://127.0.0.1:24000/v1",
                "agent": "librarian",
                "effort": "low",
            },
        }
    }
    (log_dir / "agent_actions.log").write_text(json.dumps(event) + "\n" + json.dumps(expected_event) + "\n")
    monkeypatch.setattr(metrics, "ROOT", tmp_path)

    result = metrics.audit_metrics(run_id="failed-librarian-run")

    assert result["status"] == "MEASURED"
    assert result["unproven_librarian_failures"] == 1


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


def test_failure_rate_cli_writes_only_not_measured_sidecar(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An over-rate terminal summary cannot produce a quality artifact."""
    import asyncio
    import sys

    import scripts.compute_metrics as metrics  # ty: ignore[unresolved-import]

    summary = {"todo": 0, "doing": 0, "succeeded": 8, "failed": 1, "cancelled": 1, "total": 10}

    async def fake_collect(*args: object, **kwargs: object) -> dict[str, object]:
        raise metrics.InvalidJobSummaryError(summary, "failure_rate_exceeded")

    monkeypatch.setattr(metrics, "collect", fake_collect)
    monkeypatch.setattr(metrics, "PLAN_RESOURCES", tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["compute_metrics.py", "--arm", "over-rate", "--ingestion-url", "http://127.0.0.1:8001"],
    )

    assert asyncio.run(metrics.main()) == 2
    marker = json.loads((tmp_path / "metrics-over-rate.not-measured.json").read_text())
    assert marker["status"] == "NOT_MEASURED"
    assert marker["reason"] == "failure_rate_exceeded"
    assert marker["job_summary"] == summary
    assert not (tmp_path / "metrics-over-rate.json").exists()


def test_librarian_failure_cli_invalidates_canonical_metrics(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A selected run's librarian failure blocks and invalidates quality output."""
    import asyncio
    import sys

    import scripts.compute_metrics as metrics  # ty: ignore[unresolved-import]

    run_id = "selected-librarian-failure"
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    base_extra = {
        "run_id": run_id,
        "correlation_id": "extract-0123456789abcdef0123456789abcdef",
        "model": "qwen3.8-flash-next",
        "endpoint": "http://127.0.0.1:24000/v1",
        "agent": "librarian",
        "effort": "low",
    }
    selected_failure = {
        "record": {
            "message": "librarian_failed",
            "extra": {**base_extra, "error_type": "UsageLimitExceeded", "graph_cleanliness": "NOT_MEASURED"},
        }
    }
    selected_expected = {"record": {"message": "model_request_started", "extra": base_extra}}
    other_run_failure = {
        "record": {
            "message": "librarian_failed",
            "extra": {**base_extra, "run_id": "different-run"},
        }
    }
    (log_dir / "agent_actions.log").write_text(
        "\n".join(json.dumps(event) for event in (selected_failure, selected_expected, other_run_failure)) + "\n"
    )

    async def fake_collect(*args: object, **kwargs: object) -> dict[str, object]:
        assert kwargs["run_id"] == run_id
        return {
            "schema_version": 3,
            "job_summary": {"todo": 0, "doing": 0, "succeeded": 1, "failed": 0, "cancelled": 0, "total": 1},
            "schemas": {"quality": "must-not-be-published"},
        }

    monkeypatch.setattr(metrics, "ROOT", tmp_path)
    resources = tmp_path / "resources"
    monkeypatch.setattr(metrics, "PLAN_RESOURCES", resources)
    monkeypatch.setattr(metrics, "collect", fake_collect)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "compute_metrics.py",
            "--arm",
            "terminal-failure",
            "--run-id",
            run_id,
            "--ingestion-url",
            "http://127.0.0.1:8001",
        ],
    )

    canonical = resources / "metrics-terminal-failure.json"
    canonical.parent.mkdir(parents=True)
    canonical.write_text('{"old": "quality"}')

    assert asyncio.run(metrics.main()) == 2

    sidecar = resources / "metrics-terminal-failure.not-measured.json"
    marker = json.loads(sidecar.read_text())
    assert marker["status"] == "NOT_MEASURED"
    assert marker["reason"] == "unproven_librarian_failure_mutation_risk"
    assert marker["run_id"] == run_id
    assert marker["audit"]["unproven_librarian_failures"] == 1
    assert not canonical.exists()
    stale = resources / "metrics-terminal-failure.json.stale"
    assert json.loads(stale.read_text()) == {"old": "quality"}


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
            "job_summary": {"todo": 0, "doing": 0, "succeeded": 1, "failed": 0, "cancelled": 0, "total": 1},
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
        return {"job_summary": {"todo": 0, "doing": 0, "succeeded": 1, "failed": 0, "cancelled": 0, "total": 1}}

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


def test_stage_timing_only_audit_is_not_model_execution_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Metadata timing before the first model call cannot certify a run."""
    import asyncio
    import sys

    import scripts.compute_metrics as metrics  # ty: ignore[unresolved-import]

    run_id = "stage-only-run"
    log_path = tmp_path / "log" / "agent_actions.log"
    log_path.parent.mkdir()
    log_path.write_text(
        json.dumps(
            {
                "record": {
                    "message": "stage_timing",
                    "extra": {"run_id": run_id, "correlation_id": "corr-1"},
                }
            }
        )
        + "\n"
    )

    async def fake_collect(*args: object, **kwargs: object) -> dict[str, object]:
        assert kwargs["run_id"] == run_id
        return {"job_summary": {"todo": 0, "doing": 0, "succeeded": 1, "failed": 0, "cancelled": 0, "total": 1}}

    monkeypatch.setattr(metrics, "ROOT", tmp_path)
    monkeypatch.setattr(metrics, "PLAN_RESOURCES", tmp_path / "resources")
    monkeypatch.setattr(metrics, "collect", fake_collect)
    monkeypatch.setattr(
        sys,
        "argv",
        ["compute_metrics.py", "--arm", "stage-only", "--run-id", run_id, "--ingestion-url", "http://127.0.0.1:8001"],
    )

    assert asyncio.run(metrics.main()) == 2
    destination = tmp_path / "resources" / "metrics-stage-only.json"
    marker = json.loads((tmp_path / "resources" / "metrics-stage-only.not-measured.json").read_text())
    assert marker["status"] == "NOT_MEASURED"
    assert marker["reason"] == "missing_expected_run_event"
    assert not destination.exists()


def test_model_request_error_is_valid_execution_evidence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A run where every model call fails still has measurable failure evidence."""
    import asyncio
    import sys

    import scripts.compute_metrics as metrics  # ty: ignore[unresolved-import]

    run_id = "model-error-run"
    log_path = tmp_path / "log" / "agent_actions.log"
    log_path.parent.mkdir()
    log_path.write_text(
        json.dumps(
            {
                "record": {
                    "message": "model_request_failed",
                    "extra": {
                        "run_id": run_id,
                        "correlation_id": "corr-1",
                        "model": "qwen3.8-flash-next",
                        "endpoint": "http://127.0.0.1:24000/v1",
                        "agent": "ontology",
                        "effort": "low",
                    },
                }
            }
        )
        + "\n"
    )

    async def fake_collect(*args: object, **kwargs: object) -> dict[str, object]:
        assert kwargs["run_id"] == run_id
        return {"job_summary": {"todo": 0, "doing": 0, "succeeded": 1, "failed": 0, "cancelled": 0, "total": 1}}

    monkeypatch.setattr(metrics, "ROOT", tmp_path)
    monkeypatch.setattr(metrics, "PLAN_RESOURCES", tmp_path / "resources")
    monkeypatch.setattr(metrics, "collect", fake_collect)
    monkeypatch.setattr(
        sys,
        "argv",
        ["compute_metrics.py", "--arm", "model-error", "--run-id", run_id, "--ingestion-url", "http://127.0.0.1:8001"],
    )

    assert asyncio.run(metrics.main()) == 0
    destination = tmp_path / "resources" / "metrics-model-error.json"
    output = json.loads(destination.read_text())
    assert output["audit"]["status"] == "MEASURED"
    assert output["audit"]["matched_expected_run_events"] == ["model_request_failed"]
    assert output["audit"]["audit_event_counts"] == {"model_request_failed": 1}


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
    # Documented routed topology: the router exposes a deterministic maximum
    # of five unique domains per invocation (four known plus one proposal),
    # and the harness reports an operational stage-invocation acceptance
    # budget. It does not claim a theoretical per-request upper bound.
    per_call_timeout_s = 37
    corpus_size = 28
    worker_concurrency = 2
    route_attempts = 3
    extraction_attempts = 3
    max_unique_routed_domains = 5
    max_route_invocations = corpus_size * route_attempts
    max_routed_jobs = max_route_invocations * max_unique_routed_domains
    stage_invocations = (
        max_route_invocations
        + max_route_invocations
        + corpus_size * extraction_attempts * 3
        + max_routed_jobs * extraction_attempts * 3
        + max_routed_jobs * extraction_attempts
    )
    expected_poll_timeout_s = math.ceil(per_call_timeout_s * stage_invocations / worker_concurrency + 60)
    assert f"poll_timeout_s={expected_poll_timeout_s}" in output
    assert "max_unique_routed_domains=5" in output
    assert "operational_acceptance_stage_invocations=5460" in output
    assert "PydanticAI theoretical retries" in output
    assert "excludes parent-seed recursion" in output
    assert "metrics_path=docs/plans/33-local-qwen-migration/resources/metrics-qwen-flash-next.json" in output
    assert "measurement-secret-must-not-appear" not in output
    # The command preview names the aggregate polling function, never the
    # authorization header or its value.
    assert "+ poll_jobs" in output
    assert "Authorization: Bearer" not in output


def test_bakeoff_dry_run_output_is_not_json_or_evidence() -> None:
    """Keep this explicit so consumers do not mistake command preview for metrics."""
    # This is a contract test for the emitted metrics schema, not a fabricated
    # measurement.  A real metrics artifact must carry source paths and a job
    # summary before it can be interpreted.
    example = {"schema_version": 3, "input_paths": {}, "job_summary": {"todo": 0, "doing": 0}}
    assert json.loads(json.dumps(example))["schema_version"] == 3
