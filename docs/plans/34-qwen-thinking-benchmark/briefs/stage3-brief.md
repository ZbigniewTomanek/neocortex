# Stage 3 brief — E2E harness reliability and recall formatter

| | |
|---|---|
| Implementer | `codex/gpt-5.6-sol`, effort `high` (strong tier) |
| Reviewer | `codex/gpt-5.6-sol`, effort `high` (strong tier) |
| Tier reason | A shared helper replacing seven hand-rolled poll loops without changing any assertion, plus an open-ended root-cause investigation. Judgment throughout. |
| Plan stage | [stages/03-e2e-harness-reliability.md](../stages/03-e2e-harness-reliability.md) |
| Run contract | [goal.md](../goal.md) · [PROTOCOL.md](../PROTOCOL.md) |

**No live model call. No services started.** The formatter work is reproduced on `InMemoryRepository`.

---

## Why this stage exists

Two of Plan 33's five E2E failures were the harness, not the model. `e2e_cognitive_recall_test.py` gave
local Qwen a **120-second** budget tuned for a hosted model. `e2e_extraction_pipeline_test.py` hit
`ConnectionResetError` in `step_setup_domain_routing` immediately after `manage.sh` restarted services,
because nothing waits for them. Both passed on a rerun. Until a failed child means a quality defect,
Stage 7's rubric is measuring the clock.

---

## Ground truth, already verified — build on these, do not re-derive

An inventory of the current tree established all of the following. Where it contradicts the stage text,
this brief is right and the stage text is stale; the contradictions are called out.

**The seven children and their hard-coded waits.** No shared module exists; each file duplicates the
loop and opens its own `asyncpg.connect(dsn=PostgresConfig().dsn)`.

| File | `JOB_WAIT_TIMEOUT` | Poll | Baselines captured per run | Banner |
|---|---|---|---|---|
| `e2e_cognitive_recall_test.py` | `:70` = **120** | 3 s | 2 (`:149`, `:250`) | `=== Step N ===` |
| `e2e_extraction_pipeline_test.py` | `:83` = 300 | 3 s | 1 (`:199`), threaded to two waiters | `=== Step N ===` |
| `e2e_episodic_memory_test.py` | `:48` = 600 | **5 s** | 1 (`:741`, before all stages) | `=== Stage N ===` |
| `e2e_plan15_scenarios_test.py` | `:57` = 600 | 3 s | 2 (`:858`, `:899`) | `PHASE X:` + `--- docstring ---` |
| `e2e_plan17_validation.py` | `:48` = 600 | 3 s | 2 (`:879`, `:904`) | `PHASE X:` + `--- docstring ---` |
| `e2e_weight_stability_test.py` | `:75` = **120** | 3 s | 1 (`:201`) | `=== Step N ===` |
| `e2e_content_update_test.py` | `:47` = 300 | 3 s | 2 (`:181`, `:237`) | `=== Step N ===` |

**Stage-text correction 1.** The stage says the two `120` constants are the problem. Only
`e2e_cognitive_recall_test.py` and `e2e_weight_stability_test.py` carry `120`; the other five carry
300 or 600. The gate `git grep -n "JOB_WAIT_TIMEOUT = 120"` therefore proves less than it looks — it
goes green as soon as those two files change. The real requirement is that **all seven** files stop
using a module-level constant and go through the shared helper. Gate G2 below is written to check that.

**Existing loop shapes worth knowing:**

- `e2e_cognitive_recall_test.py`'s **second** loop (`:261-273`) has **no `raise` on timeout** — it falls
  out of the `while` and continues silently. That is a real defect: a timed-out wait currently reads as
  success. Fix it by routing it through the shared helper like every other loop.
- `e2e_plan15_scenarios_test.py:243-297` and `e2e_plan17_validation.py:154-204` poll a **second**
  query in the same iteration, counting active `route_episode`/`extract_episode` jobs, and require
  `route_active == 0` as well. `e2e_content_update_test.py:102-152` runs a 60-second routing wait
  **after** its main timeout expires and then raises regardless. These routing conditions are part of
  what those children assert; preserve them.
- `e2e_extraction_pipeline_test.py` additionally has `step_verify_routing_jobs` (`:267+`) with its own
  loop, including a nested one at `:356`.

**`/admin/jobs/summary` cannot replace the SQL.** `src/neocortex/admin/routes.py:333` `_SUMMARY_SQL`
filters on `queue_name = 'extraction'` and `($1::text IS NULL OR args->>'agent_id' = $1)` only. The
handler (`:415`) takes `agent_id` from auth and an `all_agents: bool` query parameter. **There is no
since/baseline/job-id parameter** — it returns lifetime totals. `model_bakeoff.sh` runs the five children
sequentially in one session under one agent, so a cumulative total would return a stale "done". Keep the
per-child PostgreSQL query. `src/neocortex/admin/` is out of scope.

**`scripts/run_e2e.sh` is where the startup race lives.** `wait_for_healthy` (`:71-82`, a fixed 1-second
poll) is called for the MCP and ingestion URLs **only in the `docker` branch**. The `local` branch —
which is the one `model_bakeoff.sh` uses — calls `"$SCRIPT_DIR/manage.sh" start --fresh` and goes
straight to `uv run python "$TEST_SCRIPT"` with no readiness check at all. That gap is the
`ConnectionResetError`.

**`scripts/model_bakeoff.sh`** starts services at `:534` (`manage.sh start --fresh`) before the E2E loop;
`run_e2e_with_test_tokens` (`:317-366`) calls `run_e2e.sh` per child, which restarts the stack per child.

**The formatter.** `src/neocortex/tools/recall.py:14-74` `_format_recall_context(results)` selects
`[r for r in results if r.source_kind == "episode"]` at `:16` and returns the literal
`"(no episodes recalled)"` at `:74` when nothing survives. `recall` calls it at `:289` with
`final_results = truncate_preserving_neighbors(all_results, limit)`.

**Stage-text correction 2.** The stage lists two candidate causes: "episode results filtered by session
or agent id before formatting" and "the formatter reading a key the episode rows do not carry".
`recall.py` contains **no** session-id or agent-id filter — `agent_id` is only passed *into*
`repo.recall(...)` for the repository to scope internally. So candidate one does not exist in this file.
A third candidate the inventory surfaced: everything downstream of `:16` hinges on `source_kind`, so any
path that returns episode rows with a different `source_kind` produces exactly the reported symptom.
**Do not assume any of the three. Reproduce first.**

**Stage-text correction 3.** `scripts/e2e_episodic_memory_test.py:621-689` `test_formatted_context`
never compares against `"(no episodes recalled)"`. It asserts `formatted is not None` and non-empty,
splits on `"\n---\n"`, tries `json.loads` per block, and raises
`AssertionError("No JSON-parseable blocks in formatted_context")` when none parse. So the swift3 symptom
would surface through **that** message, not a null-context one. Match your reproduction to this
behaviour.

**Existing coverage.** `tests/test_recall_session_output.py` imports `_format_recall_context` and
`recall` directly and has 14 tests, three of which already assert the `"(no episodes recalled)"` string
(`:86`, `:90`, `:319`). Read them before writing a new test — one may already encode the intended
behaviour. `NEOCORTEX_E2E_JOB_WAIT_S` does not exist anywhere in the source today; no E2E child reads any
environment variable for a timeout.

---

## Scope

- `scripts/e2e_common.py` (new)
- The seven E2E children in the table above
- `scripts/run_e2e.sh`, `scripts/model_bakeoff.sh`
- `src/neocortex/tools/recall.py` (only if step 4 reproduces a defect)
- `tests/unit/test_e2e_common.py` (new), `tests/test_recall_formatted_context.py` (new),
  `tests/test_recall_session_output.py` (only if step 4's fix changes documented behaviour)

Out of scope: `src/neocortex/admin/`, every other `scripts/e2e_*.py`, and any change to an E2E
assertion. You may change **how** a child waits. You may not change **what** it asserts.

---

## Step 1 — `scripts/e2e_common.py`

```python
DEFAULT_JOB_WAIT_S = 900.0   # env NEOCORTEX_E2E_JOB_WAIT_S
DEFAULT_POLL_S = 3.0
DEFAULT_STALL_S = 300.0

async def wait_for_ready(base_url: str, token: str | None = None, timeout_s: float = 60.0) -> None
async def wait_for_jobs(*, baseline_job_id: int, min_completed: int = 1,
                        timeout_s: float | None = None, stall_s: float = DEFAULT_STALL_S,
                        poll_s: float = DEFAULT_POLL_S, label: str = "",
                        require_routing_idle: bool = False,
                        conn=None) -> JobCounts
```

**`wait_for_ready`** retries `GET {base_url}/admin/jobs/summary` with exponential backoff, treating a
connection error **and** any non-200 as "not ready", until it answers 200 or `timeout_s` elapses, then
raises with the last error. This is a **liveness check only** — it deliberately ignores the counts in the
body, because the endpoint reports lifetime totals (see Ground truth) and says nothing about this run.
Put that reason in the docstring so nobody later "improves" it into a job wait.

**`wait_for_jobs`** keeps the children's existing query verbatim:

```sql
SELECT count(*) FILTER (WHERE status = 'todo')      AS pending,
       count(*) FILTER (WHERE status = 'doing')     AS running,
       count(*) FILTER (WHERE status = 'succeeded') AS completed,
       count(*) FILTER (WHERE status = 'failed')    AS failed
FROM procrastinate_jobs
WHERE queue_name = 'extraction' AND id > $1
```

and, when `require_routing_idle`, the routing query the plan15/plan17/content-update children already
run. It polls until `pending == 0 and running == 0 and completed >= min_completed` (and
`route_active == 0` when required). It **raises** on `timeout_s`, and **raises** when the four counts do
not change for `stall_s`, in both cases with the last observed counts in the message. It returns the
final counts.

`timeout_s=None` resolves to `float(os.environ.get("NEOCORTEX_E2E_JOB_WAIT_S", 900))`, so a local model
is never judged by a hosted timer. The stall guard is what keeps a raised default from turning a hung
run into a 15-minute wait.

`conn=None` opens and closes its own `asyncpg.connect(dsn=PostgresConfig().dsn)`; an injected connection
is used and left open. **The injected-connection path is what makes this testable with a fake** — every
test in step 5 drives it that way, with no database.

Preserve each child's existing print line format as closely as you can; these logs are how a failed arm
is read afterwards.

## Step 2 — route all seven children through the helper

Replace every module-level `JOB_WAIT_TIMEOUT` constant and every hand-rolled loop listed in the Ground
truth table with a `wait_for_jobs` call. Each child keeps capturing its own baseline job id exactly where
it does today, and keeps passing it through — including the children that capture two.

Preserve behaviour that is part of an assertion:

- the routing-idle requirement in plan15, plan17, and content-update → `require_routing_idle=True`;
- `e2e_episodic_memory_test.py`'s distinction between "all jobs failed" and "no jobs enqueued" — both
  currently raise with different messages, and both must still raise;
- `e2e_cognitive_recall_test.py`'s second wait, which today only needs `pending == 0`, becomes a real
  wait that **raises on timeout**. Note this in your report as a behaviour change: it is a bug fix, and a
  child that used to slide past a timeout may now legitimately fail.

`e2e_extraction_pipeline_test.py`'s `step_verify_routing_jobs` may keep its own specialised loop if it
asserts something `wait_for_jobs` does not express — say so in your report if you leave it.

Call `wait_for_ready` before the **first admin write** in each child. For
`e2e_extraction_pipeline_test.py` that is `step_setup_domain_routing`, the exact site of the
`ConnectionResetError`.

## Step 3 — readiness in the orchestrators

In `scripts/run_e2e.sh`, call the existing `wait_for_healthy` in the **local** branch too, right after
`"$SCRIPT_DIR/manage.sh" start --fresh` and before the test script runs. The function already exists at
`:71-82`; do not write a second one. In `scripts/model_bakeoff.sh`, add one readiness check after the
`manage.sh start --fresh` at `:534`, before the first child.

## Step 4 — root-cause the empty `formatted_context`

**Order matters. Write the test first, run it on unchanged product code, and record what it did.**

1. Create `tests/test_recall_formatted_context.py`. It drives `recall` on `InMemoryRepository` with a
   graph in which the repository returns episode records among the results, and asserts the formatted
   context contains an episode block.
2. Run it against **current** `src/neocortex/tools/recall.py` and save that output to
   `validation/stage3-formatter-red-1.txt`, whatever the result. This file is the evidence that the
   regression test was capable of failing. A test that never ran red proves nothing, and reporting one
   as if it did is the failure mode this step exists to prevent.
3. Then, and only then, fix whatever the reproduction showed. Read `tests/test_recall_session_output.py`
   first — its three existing assertions on `"(no episodes recalled)"` (`:86`, `:90`, `:319`) may already
   pin the behaviour you are about to change. If your fix contradicts one of them, **stop and report**;
   do not edit those assertions to suit the fix.
4. **If the defect does not reproduce in-memory**, that is an acceptable and expected outcome. Record
   `NOT MEASURED` with your root-cause notes, say precisely what a live reproduction would need, and
   report it — I will open the backlog item. Do not weaken the E2E assertion, do not fix a defect you
   cannot demonstrate, and do not keep a regression test that has never been red.

This step is a **REPORT**, not a gate. It cannot block the stage: Stage 7 measures the child for real.

## Step 5 — tests

`tests/unit/test_e2e_common.py`, all driven with a fake connection object exposing `fetchrow`:

1. A sequence `todo>0 → terminal` returns, with the final counts.
2. A frozen sequence (identical counts every poll) raises after `stall_s`, and the message carries the
   last counts.
3. `wait_for_ready` returns after two connection errors then a 200.
4. `wait_for_ready` raises when every attempt fails, within roughly `timeout_s`.
5. A sequence that reaches `pending == 0, running == 0` but `completed < min_completed` does **not**
   return — it keeps polling and then raises. A helper that returns on the first poll regardless of
   counts must fail this test. This is the case the gate is really about.
6. `require_routing_idle=True` keeps waiting while `route_active > 0` even though the extraction counts
   are terminal.
7. `timeout_s=None` reads `NEOCORTEX_E2E_JOB_WAIT_S` from the environment (monkeypatched) and falls back
   to 900 when unset.
8. An injected connection is not closed by the helper.

Use short `poll_s`/`timeout_s`/`stall_s` values so the file runs in well under a second. Do not use real
sleeps of seconds.

---

## Gates — run these exact commands, save raw output to these paths

| # | Command | Evidence | What turns it red |
|---|---|---|---|
| G1 | `uv run pytest tests/unit/test_e2e_common.py -q` | `validation/stage3-unit-1.txt` | any failure; a helper returning on the first poll fails case 5 |
| G2 | `git grep -n "JOB_WAIT_TIMEOUT" scripts/` → **no output**, and `git grep -l e2e_common scripts/e2e_*.py` → lists **all seven** files from the Ground truth table | `validation/stage3-structural-1.txt` (both commands and their output) | any surviving `JOB_WAIT_TIMEOUT`, or a child not importing `e2e_common` |
| G3 | `uv run pytest tests/ -q` | `validation/stage3-suite-1.txt` | fewer than 1,288 passed, or any failure |
| G4 | `uv run ruff check .` | `validation/stage3-ruff-1.txt` | anything but `All checks passed!` |
| R1 | the step-4 reproduction | `validation/stage3-formatter-red-1.txt`, then `-green-1.txt` if fixed | REPORT only — never blocks |

G2 is deliberately stricter than the stage's own `JOB_WAIT_TIMEOUT = 120` grep, which would go green
after changing only two of the seven files. If you believe a `JOB_WAIT_TIMEOUT` name must survive
somewhere, report why instead of leaving it.

The E2E children cannot be executed in this stage — they need running services and a live model. Their
correctness here is proven structurally (G2) and by the helper's unit tests (G1); Stage 7 runs them for
real. Say so plainly rather than implying you ran them.

---

## Report back

- Every changed path; each gate with exit code, runtime, evidence path.
- **The step-4 finding**: did it reproduce, what was the root cause, what did you change, and the
  before/after evidence paths. If it did not reproduce, say so and name what a live reproduction needs.
- Whether any existing assertion in `tests/test_recall_session_output.py` conflicted with your fix.
- The behaviour change in `e2e_cognitive_recall_test.py`'s second wait, confirmed.
- Any child whose specialised loop you kept, and the assertion that justified it.
- Anything in this brief that turned out to be wrong about the code.
- Everything you could not measure.

Do not commit. Do not edit `goal.md`, `state.json`, `journal.md`, `backlog.md`, `decisions.md`,
`PROTOCOL.md`, or any `validation/stage*-review.md`.
