# Stage 7: Tuned compact service run

**Goal**: Run the compact corpus once through the real services with the selected levels and produce complete, privacy-safe stability, integrity, sample, recall, and E2E evidence.
**Dependencies**: 2, 3, 6
**Reference**: [resources/commands.md](../resources/commands.md)

Live budget 2 hours per arm; at most two arms in this plan. Arm name `qwen-flash-next-compact-tuned`.

---

## Steps

1. Preflight. Export the active configuration from `resources/commands.md` with the selected levels from
   `resources/effort-sweep.json` (`off` → `false`), `NEOCORTEX_LOCAL_MODEL_TIMEOUT_S=300`, and a fresh
   `NEOCORTEX_BAKEOFF_RUN_ID=<UTC>-tuned1`. Run the authenticated `/v1/models` check, the settings
   validation one-liner, and `./scripts/model_bakeoff.sh --arm qwen-flash-next-compact-tuned
   --corpus-profile compact --dry-run`. Snapshot the development graph first (`manage.sh snapshot save`).

2. Launch detached and poll. `nohup ./scripts/model_bakeoff.sh --arm qwen-flash-next-compact-tuned
   --corpus-profile compact > .tmp/plan34/arm-tuned1.log 2>&1 &`. Poll `/admin/jobs/summary` no more often
   than every 5 minutes. At 2 hours, record the last summary and treat the arm as `NOT MEASURED`; do not
   wait longer.

3. Evidence after completion. In order: `scripts/export_skip_events.py --run-id … --arm …`,
   `scripts/export_graph_sample.py --check-temporal … --sample 20`, `scripts/compute_metrics.py … --skip-events
   …` (consistency and survival fields), `scripts/generate_qwen_parsing_report.py --run-id … --arm …`.
   Commit the metrics, recall, E2E manifest, skip-events, sample, and parsing report under
   `docs/plans/33-local-qwen-migration/resources/` next to their swift3 predecessors.

4. One repair arm at most. If an evidence line below fails because of a root-caused harness or product
   defect, fix it, record the decision, and run `-tuned2` once. A third arm is out of scope: record the
   failure, hand the item to `backlog.md`, and **continue to Stage 8**. These lines are REPORT, not GATE
   (D-7) — they feed Stage 8's rubric, where any failed or `NOT MEASURED` input already yields `HOLD`.
   Stage 7 is `DONE` once the arm has run and its evidence is recorded, green or not; a red evidence line
   must never leave Stage 8 unreachable, because the truthful `HOLD` the plan exists to publish lives
   there.

---

## Verification

- [ ] GATE the arm ran and its evidence exists — `metrics-qwen-flash-next-compact-tuned.json`, the recall results, the E2E manifest, `skip-events-*-tuned*.json` and `quality-sample-*-tuned*.json` are all written and committed for this run id. A missing artifact is the one thing that blocks: Stage 8 cannot compute a verdict from nothing. If the 2 h budget expired, record the last summary and the partial artifacts, and say which are `NOT MEASURED`.
- [ ] REPORT terminal stability — all submitted jobs terminal and `(failed+cancelled)/total ≤ 0.10`, read from the captured `/admin/jobs/summary` in `metrics-qwen-flash-next-compact-tuned.json`; a non-terminal queue or a higher ratio is a failed rubric input, recorded and passed to Stage 8.
- [ ] REPORT critical integrity — zero stored reasoning markers, invalid type names, garbage types, or source leaks in the same metrics file's integrity scan.
- [ ] REPORT skip-event attribution — `skip_events_consistent` true for both reason codes and `temporal_survived.total == temporal_survived.survived`, read from the metrics file and `skip-events-*-tuned*.json`; a count mismatch or `survived == false` is recorded with the offending event ids and closes Plan 33 backlog 16 as still open.
- [ ] REPORT fixed graph sample — `quality-sample-qwen-flash-next-compact-tuned-<run>.json` holds 20 node and 20 edge rows, all `type_valid` and `endpoints_exist` true, validated against `resources/quality-sample-tuned.schema.json`; a shortfall is recorded as a shortfall with its `count`, never padded.
- [ ] REPORT five E2E outcomes with `failure_step`/`exception_class` for failures, Plan 15 and Plan 17 scores, recall M1–M4, wall time, requests, reasoning and completion tokens, p50/p95 per agent — record in `journal.md`.

---

## Commit

`test(models): record tuned Qwen compact run`
