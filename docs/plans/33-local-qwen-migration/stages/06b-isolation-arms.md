# Stage 6b: Isolation and Root-Cause Diagnosis

**Goal**: Attribute local failures to a transport, prompt, schema, tool, classifier, or serving cause before issuing per-agent verdicts.
**Dependencies**: Stage 6 DONE. Run this stage when the joint arm has a critical or material quality miss; otherwise mark it `SKIPPED` with evidence in `journal.md`.

## Steps

1. Enumerate every failed gate and every unexplained quality regression from the local arm. Do not
   attribute a joint graph metric to one agent by intuition.
2. Reproduce each failure with a minimal fixture and the same endpoint/model. Classify the root cause:
   authentication, system-message ordering, prompt framing, tool-call protocol, structured schema,
   normalization rejection, timeout/resource pressure, domain routing, or persisted-data corruption.
3. Where credentials and an isolated environment are available, run one-agent-local isolation arms
   with the other agents on the known hosted configuration. If hosted credentials are unavailable,
   use targeted real-agent probes and call the attribution `NOT MEASURED`, not a pass.
4. Preserve all raw requests/results except secrets. Compare against the optional baseline only when
   its two runs are complete and same-input. Record which defect each check would detect and whether
   the issue is local-only, hosted-only, or an interaction.
5. Use a dedicated GPT-5.6-Luna xhigh subagent for adversarial diagnosis. It must inspect artefacts
   rather than receive expected verdicts. Cap light repairs at two attempts; defer architectural or
   serving work to `backlog.md`.
6. Write `resources/isolation-attribution.md` with one row per failed metric, implicated agent union,
   evidence, confidence, and unresolved root cause. If local quality is inadequate, this file becomes
   the evidence source for the ASD-STE100 report in Stage 9.

## Verification

- [ ] GATE attribution integrity — every failed metric has a named raw input and reproducible defect, or is explicitly `NOT MEASURED`; inference from the joint graph alone makes this red.
- [ ] GATE repair safety — any compatibility fix preserves the hosted path and passes the relevant tests; a weakened assertion or unrecorded confound makes this red.
- [ ] REPORT isolation and root-cause matrix — record arm identity, agent mix, outcome, evidence paths, and unresolved items in `journal.md` and `resources/isolation-attribution.md`.

## Commit

`docs(plan): diagnose local Flash Next stability failures`
