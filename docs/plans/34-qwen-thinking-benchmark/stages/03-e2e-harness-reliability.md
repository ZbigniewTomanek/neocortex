# Stage 3: E2E harness reliability and recall formatter

**Goal**: Remove the two hosted-tuned E2E flakes and root-cause the empty `formatted_context`, so a failed E2E child means a quality defect and not a timer.
**Dependencies**: None

No live model call. The formatter fix is reproduced deterministically on `InMemoryRepository`.

---

## Steps

1. Shared readiness and job-wait helpers.
   - Where: new `scripts/e2e_common.py`.
   - Details: `wait_for_ready(base_url, token, timeout_s=60)` retries `GET /admin/jobs/summary` with
     backoff on connection errors and non-200 until it answers. `wait_for_jobs(base_url, token, *,
     min_total, timeout_s, stall_s)` polls the same endpoint until `todo == 0 and doing == 0 and total >=
     min_total`; raises with the last summary on timeout or when counts do not change for `stall_s`.
     `timeout_s` defaults to `NEOCORTEX_E2E_JOB_WAIT_S` (default 900) so local models are not judged by
     hosted timers.

2. Replace every fixed wait in the five children.
   - Where: `JOB_WAIT_TIMEOUT` loops in `scripts/e2e_cognitive_recall_test.py` (120 s, two loops),
     `scripts/e2e_extraction_pipeline_test.py` (three loops), `scripts/e2e_episodic_memory_test.py`,
     `scripts/e2e_plan15_scenarios_test.py`, `scripts/e2e_plan17_validation.py`; also
     `scripts/e2e_weight_stability_test.py` and `scripts/e2e_content_update_test.py` if the edit is
     mechanical.
   - Details: call `wait_for_ready` before the first admin write (`step_setup_domain_routing` in the
     extraction-pipeline child hit `ConnectionResetError` right after `manage.sh` restart) and use
     `wait_for_jobs` instead of the local loops. Keep each child's assertions unchanged.

3. Readiness before children in the orchestrator.
   - Where: the E2E loop in `scripts/model_bakeoff.sh` (`run_e2e_with_test_tokens`) and `scripts/run_e2e.sh`.
   - Details: call the readiness check once after services start, before the first child.

4. Root-cause the empty `formatted_context`.
   - Where: `_format_recall_context` and `recall` in `src/neocortex/tools/recall.py`; the assertion is
     `test_formatted_context` in `scripts/e2e_episodic_memory_test.py`.
   - Details: write `tests/test_recall_formatted_context.py` first: it drives `recall` on `InMemoryRepository` with a graph where the
     repository returns episode records among results, and asserts the formatted context contains an
     episode block. Run it on current code and record the failure in `journal.md`. Then fix the cause
     (candidate causes: episode results filtered by session or agent id before formatting; the formatter
     reading a key the episode rows do not carry). If the defect does not reproduce in-memory, record
     `NOT MEASURED`, open a backlog item naming what a live reproduction needs, and leave the child as a
     REPORT value; do not weaken the E2E assertion.

---

## Verification

- [ ] GATE `uv run pytest tests/unit/test_e2e_common.py tests/test_recall_formatted_context.py -q` — passes: a fake summary sequence `todo>0 → terminal` returns; a frozen sequence raises after `stall_s`; two connection errors then 200 returns from `wait_for_ready`; the formatter regression test passes on fixed code after having been recorded red on `8766e90`-era code in `journal.md`. A regression test that never ran red is vacuous and turns this line red.
- [ ] GATE `git grep -n "JOB_WAIT_TIMEOUT = 120" scripts/` returns nothing, and each of the five children imports `e2e_common` (`git grep -l e2e_common scripts/e2e_*.py` lists all five) — structural.
- [ ] GATE `uv run pytest tests/ -q` and `uv run ruff check .` — pass.
- [ ] REPORT whether the formatter defect reproduced in-memory and its root cause — record in `journal.md`.

---

## Commit

`fix(e2e): readiness-based waits and formatted recall context`
