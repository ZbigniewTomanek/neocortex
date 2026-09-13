"""Unit tests for bounded shared E2E readiness helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pytest
from scripts import e2e_common  # ty: ignore[unresolved-import]


class FakeConnection:
    def __init__(
        self,
        extraction: list[Mapping[str, object]],
        routing: list[Mapping[str, object]] | None = None,
    ) -> None:
        self.extraction = extraction
        self.routing = routing or [{"active": 0}]
        self.extraction_calls = 0
        self.routing_calls = 0
        self.closed = False

    async def fetchrow(self, query: str, *args: object) -> Mapping[str, object]:
        del args
        if "task_name IN" in query:
            index = min(self.routing_calls, len(self.routing) - 1)
            self.routing_calls += 1
            return self.routing[index]
        index = min(self.extraction_calls, len(self.extraction) - 1)
        self.extraction_calls += 1
        return self.extraction[index]

    async def close(self) -> None:
        self.closed = True


@dataclass
class FakeClock:
    now: float = 0.0

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


def _row(pending: int, running: int, completed: int, failed: int = 0) -> dict[str, object]:
    return {"pending": pending, "running": running, "completed": completed, "failed": failed}


def _install_clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    clock = FakeClock()
    monkeypatch.setattr(e2e_common.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(e2e_common.asyncio, "sleep", clock.sleep)
    return clock


@pytest.mark.asyncio
async def test_todo_to_terminal_returns_final_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_clock(monkeypatch)
    conn = FakeConnection([_row(1, 0, 0), _row(0, 0, 1)])

    counts = await e2e_common.wait_for_jobs(baseline_job_id=17, timeout_s=10, stall_s=5, poll_s=0.1, conn=conn)

    assert counts == e2e_common.JobCounts(pending=0, running=0, completed=1, failed=0)


@pytest.mark.asyncio
async def test_frozen_counts_raise_with_last_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_clock(monkeypatch)
    conn = FakeConnection([_row(1, 0, 0)])

    with pytest.raises(e2e_common.JobWaitError, match=r"stalled.*pending=1 running=0 completed=0 failed=0"):
        await e2e_common.wait_for_jobs(baseline_job_id=17, timeout_s=10, stall_s=0.2, poll_s=0.1, conn=conn)


class FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class FakeClient:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        del args

    async def get(self, *args: object, **kwargs: object) -> FakeResponse:
        del args, kwargs
        index = min(self.calls, len(self.outcomes) - 1)
        self.calls += 1
        outcome = self.outcomes[index]
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, FakeResponse)
        return outcome


@pytest.mark.asyncio
async def test_ready_after_two_connection_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_clock(monkeypatch)
    client = FakeClient([ConnectionError(), ConnectionError(), FakeResponse(200)])
    monkeypatch.setattr(e2e_common.httpx, "AsyncClient", lambda: client)

    await e2e_common.wait_for_ready("http://service", token="token", timeout_s=1)

    assert client.calls == 3


@pytest.mark.asyncio
async def test_ready_timeout_reports_last_error(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _install_clock(monkeypatch)
    client = FakeClient([ConnectionError()])
    monkeypatch.setattr(e2e_common.httpx, "AsyncClient", lambda: client)

    with pytest.raises(TimeoutError, match="ConnectionError"):
        await e2e_common.wait_for_ready("http://service", timeout_s=0.25)

    assert clock.now == pytest.approx(0.25)


@pytest.mark.asyncio
async def test_terminal_below_minimum_keeps_polling_then_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_clock(monkeypatch)
    conn = FakeConnection([_row(0, 0, 0)])

    with pytest.raises(e2e_common.JobWaitError):
        await e2e_common.wait_for_jobs(
            baseline_job_id=17,
            min_completed=1,
            timeout_s=0.25,
            stall_s=10,
            poll_s=0.1,
            conn=conn,
        )

    assert conn.extraction_calls > 1


@pytest.mark.asyncio
async def test_routing_activity_delays_terminal_return(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_clock(monkeypatch)
    conn = FakeConnection(
        [_row(0, 0, 1)],
        routing=[{"active": 1}, {"active": 0}],
    )

    counts = await e2e_common.wait_for_jobs(
        baseline_job_id=17,
        timeout_s=1,
        stall_s=1,
        poll_s=0.1,
        require_routing_idle=True,
        conn=conn,
    )

    assert counts.route_active == 0
    assert conn.routing_calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(("env_value", "expected_elapsed"), [("0.25", 0.25), (None, 900.0)])
async def test_default_timeout_reads_environment_or_uses_900(
    monkeypatch: pytest.MonkeyPatch, env_value: str | None, expected_elapsed: float
) -> None:
    clock = _install_clock(monkeypatch)
    if env_value is None:
        monkeypatch.delenv("NEOCORTEX_E2E_JOB_WAIT_S", raising=False)
    else:
        monkeypatch.setenv("NEOCORTEX_E2E_JOB_WAIT_S", env_value)
    conn = FakeConnection([_row(0, 0, 0)])

    with pytest.raises(e2e_common.JobWaitError, match=f"within {expected_elapsed:g}s"):
        await e2e_common.wait_for_jobs(
            baseline_job_id=17,
            timeout_s=None,
            stall_s=2000,
            poll_s=1000,
            conn=conn,
        )

    assert clock.now == pytest.approx(expected_elapsed)


@pytest.mark.asyncio
async def test_injected_connection_is_not_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_clock(monkeypatch)
    conn = FakeConnection([_row(0, 0, 1)])

    await e2e_common.wait_for_jobs(baseline_job_id=17, timeout_s=1, conn=conn)

    assert conn.closed is False
