# Post-mortem: local Qwen Swift run

## Scope and evidence inspected

I inspected the execution contract and state (`goal.md`, `state.json`, `journal.md`), all four frozen stage briefs, the Stage 1–4 validation records, the three compact-run summaries/metrics and comparison tables, the final Stage 4 evidence review, and the accepted commit history. The report contains only aggregate results and safe error categories; it omits credentials, prompts, source episode text, model outputs, and private diagnostic paths.

## What was tried and where time went

The run proceeded through five stages:

1. **Speed harness.** Added an in-memory, per-stage probe with bounded episode calls and a private extraction cache. The test-model corpus pass completed 8/8 episodes. The live E04 baseline was 353.6 seconds (ontology 84.4 s, extractor 167.8 s, librarian 100.4 s; 15 requests).
2. **One-shot librarian.** Added a Qwen-only host-side resolver. Fresh graphs correctly required zero librarian requests; populated replays used one request in about 20–23 seconds and were idempotent. Temporal-chain behavior was tested and repaired.
3. **Extractor/ontology compaction.** Disabled Qwen thinking for real, made ontology tool-free, capped and shortened extractor output, and added tolerant classifier handling. Live E04/E05 became 40.1/46.8 seconds with zero reasoning tokens; E18 classification completed in 3.9 seconds.
4. **Compact service benchmark.** Three benchmark attempts consumed most of the wall-clock time. Run 1 took 683 seconds but stopped before quality metrics because a librarian failure exposed a database mutation-risk gate. Run 2 took 2,401 seconds and exposed a recall-scorer null-handling defect plus quality/E2E failures. One repair round addressed those issues and homonym/endpoint behavior; final Run 3 took 2,397 seconds including snapshots, metrics, recall, and five E2E children.
5. **Routing fan-out.** Not triggered: final corpus work was about 1.3 minutes per episode and the full bakeoff was under the 90-minute gate, despite 22 pipeline runs for 8 episodes (2.75x fan-out).

The final corpus run used 68 model requests, zero reasoning tokens, 22 ontology runs/25 requests, 22 extractor requests, 13 librarian requests, and 8 classifier requests. Compared with the reference, the dominant savings came from removing librarian tool loops, disabling thinking, and reducing extractor output—not from fan-out changes.

## Failures and why

- **Run 1 fail-closed metrics:** a librarian retry followed an `InvalidCachedStatementError` after mutations. The cause was asyncpg prepared-statement caching across transactions that changed `search_path`; a statement prepared for one graph schema was reused in another. The pool was changed to disable statement caching. A separate extractor validation failure recovered on retry.
- **Temporal edge drift:** a normal relation on the same node pair overwrote a temporal correction edge. The write order and relation handling were changed so temporal edges win and conflicting ordinary relations are skipped/audited.
- **Duplicate/homonym behavior:** one-shot create decisions could collide with existing names, and relation endpoints not present in the extraction were not resolved graph-side. The resolver now considers homonyms, preserves the existing type when merging a lone same-name node, honors explicit creates, and resolves endpoints by graph name/alias.
- **Recall scorer crash:** a null activation score caused `float(None)` and prevented Run 2 recall measurement. Null coercion was fixed; Run 3 recall became measurable.
- **Final E2E quality:** all five E2E children exited 1. Plan 15 had 9 PASS, 3 PARTIAL, 2 FAIL; Plan 17 had 12 acceptable, 1 partial, 1 FAIL. The substantive failures were loss of numeric facts during terse extraction/merge (deadline contradiction, superseded exponent, and correction precision). The episodic-memory child also lacked a formatted episode block despite recall listing episodes.
- **Final E2E infrastructure flakes:** the extraction-pipeline child hit a PostgreSQL connection reset during its migration step; the cognitive-recall child hit a fixed 120-second job wait. Both had passed in the prior run, so these are timing/startup reliability failures rather than stable quality evidence.
- **Not reproduced:** the previously reported E18 classifier validation defect was not reproduced; the run still added defensive defaults/clamping. It must remain “not measured,” not “fixed by reproduction.”

## Unblocked evidence and accepted source state

The run unblocked measured recall (M1 max activation 0.667, M2 top-1 count 2, M3 1/1, M4 3/3), terminal-job/integrity evidence, and the per-stage timing/request/token comparison. Final integrity was clean across all six schemas: zero stored leaks, invalid type names, or garbage types; zero failed agent runs and zero tool-validation rejections. The final restore check left services stopped and the development schema restored.

Accepted commits and implications:

- `913f3c6`: speed probe, cache hook, and harness tests.
- `524a3f2` + `a52d452`: Qwen one-shot librarian plus collision/merge repair.
- `ad85426`: Qwen-only thinking-off settings, compact extractor, tool-free ontology, classifier safeguards, and temporal-edge repair.
- `6d3bae4`: disables asyncpg statement caching for schema-scoped pools.
- `653cbd6`: homonym merge and graph-side endpoint resolution, plus recall null handling.
- `219e56e`: records the compact benchmark artifacts.

Hosted-model prompts/tools remained unchanged by the stage checks. The current source therefore supports a fast Qwen path and keeps the hosted path separate, but the Qwen compaction is not quality-equivalent for numeric facts and the E2E suite is not green.

## Stage 6 invariants/gates to add

1. **Numeric-fact retention gate:** seed explicit dates, deadlines, versions, exponents, and precision values; assert they survive extraction, merge, correction, and recall. Assert the newer value replaces the old one without deleting unrelated facts.
2. **Structured-fact preservation invariant:** terse Qwen descriptions may be short, but explicit scalar properties must be retained in structured node content; cardinality caps must not silently discard a fact-bearing entity.
3. **Schema-isolation concurrency gate:** run parallel extraction across at least two schemas while changing `search_path`; fail on cached-plan errors and verify no cross-schema writes.
4. **Temporal-edge integrity gate:** assert `SUPERSEDES`/`CORRECTS` edges survive any ordinary relation emitted for the same pair, with skipped-conflict counts audited.
5. **Idempotence/homonym gate:** replay the same extraction and test same-name nodes of different types; assert no duplicates unless an explicit create decision requires one, and assert unbound endpoints resolve or are counted as skipped.
6. **E2E timing/startup gate:** replace fixed child waits with a readiness condition derived from job state and a generous model-aware timeout; separately retry/diagnose connection-reset startup failures.
7. **Formatted-context gate:** assert episodic recall includes at least one parseable episode block whenever episode records are returned.
8. **Evidence honesty gate:** keep recall/E2E outcomes as report values, preserve failed-run artifacts, and label unreproduced historical defects as not measured. Do not turn the final 0/5 E2E result into a pass based only on corpus-job speed or integrity.

## Commands run and observed outputs

Read-only inspection commands included:

- `ls -la .tmp/qwen-swift && find .tmp/qwen-swift -maxdepth 3 -type f | sort` — enumerated the run record and validation artifacts.
- `jq` over `state.json` and the Stage 4 summaries — showed stages 1–5 complete, final jobs 30/30, 2,397 seconds, measured recall, and 0/5 E2E by exit code.
- `sed`/`rg` over the goal, journal, briefs, validation text, and review — reconstructed the failed attempts, repairs, and gate dispositions.
- `git log --oneline` and `git show --stat` for the accepted commits — confirmed the source sequence and that the final branch head is `219e56e`.

The evidence review reported no findings and no credential-pattern hits. No source or run-record files were changed by this post-mortem; only this report was created.
