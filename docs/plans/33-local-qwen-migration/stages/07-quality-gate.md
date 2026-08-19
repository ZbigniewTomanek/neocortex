# Stage 7: Quality Gate Evaluation

**Goal**: Decide, per agent, whether local Qwen clears the gate — and produce a written verdict with the evidence attached.
**Dependencies**: Stages 5 and 6 DONE.

---

## This stage writes no code

It is a judgement stage. Its entire output is a decision document plus the index's Decisions
section. The temptation it must resist is obvious: the plan has by now invested six stages, and
the cheapest way to "succeed" is to soften a threshold. **Don't.** A clean "no" answered with
evidence is the successful outcome of a gate — the plan's stated goal is to *determine* whether
the model is capable, not to arrive at a migration.

---

## Steps

1. **Diff the two arms.**
   - Details: produce `resources/bakeoff-comparison.md` — a side-by-side of every Tier 1, Tier 2,
     and Tier 3 metric from `metrics-baseline-gpt54mini.json` and `metrics-qwen38-27b.json`, with
     the delta and a PASS/FAIL against the absolute thresholds Stage 5 resolved.

2. **Apply Tier 1 — hard fail, absolute.**
   - Details: any miss on garbage types, instance-level types, extraction failure rate > 10%,
     invalid type names, leaked reasoning markers, or a failing
     `e2e_extraction_pipeline_test.py` **blocks the responsible agent from migrating**, no matter
     what the baseline scored. These encode the Plan 28 ontology crisis.
   - Attribute each failure to an agent where possible. Garbage and instance-level type names come
     from the **ontology** agent (`propose_type`) and the **extractor** (`type_name`); leaked
     markers in node *content* point at the **librarian**; a failure to route points at the
     **classifier**. Where attribution is genuinely ambiguous, say so and treat it as blocking for
     every agent it could plausibly implicate.

3. **Apply Tier 2 — near-parity, relative.**
   - Details: score against the absolute numbers fixed in Stage 5. Note which are *soft* signals:
     Plan 18.5 measured **M4 temporal evolution at 0/3** and **M5 domain routing at 0/28** on the
     old stack, so those metrics have a weak historical floor and a Qwen regression there is far
     less informative than a Qwen regression on dedup rate or scenario pass count.

4. **Write a per-agent verdict.**
   - Details: for each of ontology, extractor, librarian, and domain classifier, one of:
     - **MIGRATE** — clears Tier 1 outright and Tier 2 within tolerance.
     - **HOLD** — clears Tier 1 but misses Tier 2. Stays hosted; the specific misses become a
       Backlog entry with the measured numbers, because a targeted prompt or effort change may
       clear it later.
     - **BLOCKED** — misses Tier 1. Stays hosted; Backlog entry records the failure mode with an
       example of the bad output.
     The seed generator follows the classifier's verdict (it shares `domain_classifier_model`).

5. **Sanity-check a MIGRATE verdict against the qualitative record.**
   - Details: metrics can pass while the graph is visibly worse. Before confirming any MIGRATE,
     read a sample of ~20 nodes and ~20 edges from the Qwen snapshot and compare them against the
     baseline snapshot for the same episodes. Plan 28's crisis produced types like
     `ActivityfunctiondefaultApicreateOrUpdateNodecontent`, and the E2E report before it produced
     Creatine → `ProbabilisticModel` and Serotonin → `DatabaseSystem` — failures that a
     count-based metric can miss entirely. If the sample looks wrong, downgrade the verdict and
     say why.

6. **Record the decision.**
   - File: `docs/plans/33-local-qwen-migration/index.md`
   - Details: add a Decisions entry (D9) stating the verdict for each agent with the deciding
     numbers inline. Add Backlog entries for every HOLD and BLOCKED.

7. **Set the downstream stages' disposition.**
   - Details:
     - **At least one MIGRATE** → Stages 8 and 9 proceed, scoped to the migrating agents only.
     - **No MIGRATE** → mark Stages 8 and 9 **SKIPPED**, and write a short closing summary at the
       top of the index: the question was asked and answered, with the evidence. End the run
       successfully.

---

## Verification

- [ ] `resources/bakeoff-comparison.md` exists with every metric, both arms, delta, and PASS/FAIL.
- [ ] Every one of the four agents has an explicit MIGRATE / HOLD / BLOCKED verdict.
- [ ] Every HOLD and BLOCKED has a Backlog entry containing the measured numbers and, for BLOCKED,
      an example of the bad output.
- [ ] The qualitative 20-node / 20-edge sample review is recorded for every MIGRATE verdict.
- [ ] Index Decisions contains D9 with the deciding numbers inline.
- [ ] Stage 8 and 9 statuses in the progress tracker reflect the decision.
- [ ] **No threshold in the index was edited during this stage.** `git diff` on the Success
      Criteria tables shows only the Baseline/Qwen result columns changing, never the Target column.

---

## Commit

`docs(plans): record Plan 33 quality gate verdict per agent`
