# Stage 1 post-review — commit `0101ce4`

Reviewer: `claude/opus`, effort high. Read-only. Skill: `plan-post-review`.
Placement: `review-each-stage-after`. Budget: `one-review-one-fix` (this review is spent).

**Reviewer verdict: PASS with 8 non-blocking findings. No BLOCKING finding.**

## Gate dispositions (reviewer's, independent of the orchestrator's own re-runs)

| Gate | Disposition | Evidence |
|---|---|---|
| G1 both unit files incl. the mutation test | PASS — `47 passed in 0.80s` | `stage1-unit-3.txt` |
| G2 `--test-model --corpus both` writes 11 rows each with `fact_score` | PASS — 11/11; triplets carry `supersession`, `run.thinking_extractor == "high"` with the other three `"off"` | `stage1-testmodel-3.txt` + `.tmp/plan34/stage1-verify.json` |
| G3 full suite | PASS — `1322 passed, 7 skipped` vs baseline `1288/7` (+34, none removed) | `stage1-suite-3.txt`, `baseline-pytest.txt` |
| G4 ruff | PASS — `All checks passed!`; ruff's only exclude is `test_agents`, so both new files are really linted | `stage1-ruff-3.txt` |
| Run-wide: hosted path identity | PASS — `0101ce4` touches nothing under `src/neocortex/extraction/`; its only `src/` change is `db/mock.py` | `git show --stat 0101ce4` |

## Answers to the questions the review was asked

- **Can the scorer pass where the E2E child fails?** No for S05 and S07 — byte-for-byte the same anchor
  rule and haystack. Structurally different for S11 (F4).
- **Is the haystack anchor `content` only?** Yes: `fact_retention.py:239`, pinned by
  `test_anchor_text_ignores_name_and_properties`.
- **Is the mutation test real?** Yes. A constant-full-marks scorer fails both of its assertions.
- **Does any fixture fact fail to occur in its episode text?** No — all 56 re-validated outside pytest.
- **`fact_score: null`, never `0/0`?** Correct, on three independent surfaces.
- **Any new text leak into a committed artifact?** Nothing new; one pre-existing channel (F7).
- **Does the D-10 key stop cross-level cache reuse?** Yes — but the miss crashes (F1).
- **Any pre-existing test weakened?** No. `git show 0101ce4 --numstat -- tests/` is `305 0` and `314 0`
  — zero deleted lines.
- **`--max-wall-seconds` → `NOT MEASURED`?** Yes, checked before each launch; every field nulled.

## Findings

**F1 — Stage 6 step 2's librarian sweep will miss the new cache key and die on an uncaught
`FileNotFoundError`, writing no output at all. NON-BLOCKING for Stage 1; blocks Stage 6's
sweep-completeness gate when it runs.**
`qwen_speed_probe.py:499-507` folds the *resolved* ontology and extractor levels into the key, and those
resolve from `--thinking` (default `"low"`) when the per-agent flags are absent. Stage 6 step 1 writes the
cache with `--thinking off --thinking-extractor <level>`; step 2
(`stages/06-per-agent-effort-sweep.md:31-33`) reads it with `--stage librarian --cache-thinking <L_ext>
--thinking-librarian <level>` and passes neither. Verified key hashes for E04:
`step1 → E04-04c212aba9cf`; `step2 as written → E04-957d37180cb3` (miss);
`step2 + --thinking off --thinking-extractor medium → E04-04c212aba9cf` (hit).
`load_cached_extraction` at `:512` sits outside the `try` at `:547`, so the miss propagates out of
`run_text → run_unit → main`; the reviewer reproduced it live and **no output file was written at all**.
The cell yields a traceback, not a `NOT MEASURED` row.

**F2 — Under `--repo shared`, `score_episode` credits E27 with three facts only its predecessor E02
could have produced. NON-BLOCKING** (Stage 6 runs `--repo fresh`).
`fact_retention.py:184-193` builds the haystack from all non-forgotten nodes and the probe snapshots the
accumulated repo. E27 facts 0/2/3 (`Jonas Weber`, `Sarah Kim`, `Anya Kowalski`) occur verbatim in E02,
which runs first: an E02-only graph scores E27 at 3/6.

**F3 — `chain.satisfied` counts `SUPERSEDES`/`CORRECTS` edges graph-wide, not among the chain's
episodes. NON-BLOCKING.** `count_temporal_edges` (`fact_retention.py:213-216`) scans every edge. Under
`--repo shared`, one temporal edge produced while processing E27 would make the E18→E20→E26 chain read
`satisfied: true` having produced nothing. Latent: every plan command uses `--repo fresh`, which
correctly records `NOT MEASURED / repo_mode=fresh`.

**F4 — the "mirrors the E2E exactly" docstring holds for S05 and S07 but not S11. NON-BLOCKING.**
S11's child (`e2e_plan15_scenarios_test.py:699-731`) does not look at node names at all: it runs
`_recall(...)` and ranks `0.62` against `0.57` in the returned content. The probe runs with
`embeddings=none`, the child with real Gemini embeddings, so a node recall would not return can pass the
probe and fail the child. Documentation accuracy, not a code change — the anchor names were pinned by the
brief.

**F5 — a triplet's cache key covers neither the triplet text nor the fixture revision. NON-BLOCKING.**
The key uses `corpus_sha256` (the hash of `compact-corpus.md`); triplet texts live in
`fact-fixture.json`, which contributes nothing to the preimage. Editing a triplet and bumping `revision`
silently reuses the old extraction. The fixture already carries `revision` for exactly this purpose.

**F6 — `_node_haystack` joins node fields with a bare space, so a multi-word fact can match across two
unrelated nodes. NON-BLOCKING.** Demonstrated: nodes named `"Encoding length: 8-character"` and
`"Metaphone3 for Latin-script input"` credit E26's fact `"8-character Metaphone3 for Latin-script"`,
which neither node states. Six of the 56 fixture facts are multi-word phrases exposed to this. A
separator no fact can contain removes the channel without changing any specified semantics.

**F7 — `edge_types_after` puts model-proposed ontology edge-type names into the summary JSON,
contradicting the probe's own docstring ("model output never reaches it"). NON-BLOCKING; pre-existing at
`8766e90`, not introduced here.** Stage 6 commits these files under `resources/sweep/*.json`.

**F8 — the G2 artifact named in the brief no longer exists on disk. NON-BLOCKING (evidence hygiene; the
gate is genuinely met).** `stage1-testmodel-*.txt` end with `summary written to
.tmp/plan34/stage1-testmodel.json`, which is absent; only the orchestrator's independent re-run
`.tmp/plan34/stage1-verify.json` survives, and `.tmp/` is gitignored. The committed stdout contains no
`fact_score` field, so the gate's load-bearing property rests on that re-run plus
`test_test_model_run_over_the_full_corpus_and_triplets`. Also: `run_meta["episodes"]` records
`["E04","E05"]` (the `--episodes` default) even under `--corpus both`, where it is ignored.

## Candidates the reviewer raised and then refuted (recorded so they are not re-raised)

Timed-out unit still carrying a numeric `fact_score` (the count is the true graph content; `status`
carries `timeout`); an empty `new_tokens` entry (no such token in the committed fixture); `facts: []`
accepted by `load_fixture` (pinned by an assertion on the committed artifact); `_blank_row` zero-filling
a timed-out stage (pre-existing); `graph_snapshot` violating CLAUDE.md rule 1 (the brief mandates exactly
this and forbids adding it to the protocol); the exit-code change (strictly safer); `normalize`'s
docstring ordering (equivalent compositions).

---

## Triage — orchestrator, 2026-09-11

Budget is `one-review-one-fix`; this review is spent. **No fix round was opened**, because no finding
blocks a Stage 1 gate and the owner ended the session before a fix round could be run and verified.
Stage 1 stays `DONE` at `0101ce4`. Every finding below is carried to `backlog.md` with its evidence.

- **F1 — accepted, highest priority, backlog 6.** I reproduced the reviewer's reasoning against the
  code: `load_cached_extraction` is genuinely outside the `try`, so this is a crash and not a recorded
  measurement, which is the one failure mode `goal.md` forbids most explicitly. It is a *Stage 6*
  defect, not a Stage 1 one — Stage 1's own gates do not exercise `--stage librarian`. Two fixes are
  needed and both are recorded: pin the upstream levels in the Stage 6 step-2 command, **and** catch the
  miss so a cell records `error:FileNotFoundError` instead of killing the run. Whoever runs Stage 6 must
  do this first; it is a guaranteed failure otherwise.
- **F5 — accepted, backlog 7.** Same class as F1 and cheap: fold the fixture `revision` into the cache
  preimage. Do it in the same change as F1.
- **F6 — accepted, backlog 8.** A real over-count channel with a demonstrated failing input, affecting
  six of 56 facts. Not blocking because it can only inflate `facts_found`, and Stage 6 ranks triplet
  passes *first*, which this cannot touch. Fix before the numbers are published in Stage 8.
- **F2 and F3 — accepted as latent, backlog 9.** Both are `--repo shared` only, and every command in
  this plan uses `--repo fresh`, which the code correctly records as `NOT MEASURED`. The backlog entry
  exists so nobody adds `--repo shared` to a sweep cell without fixing them first.
- **F4 — accepted as documentation, backlog 10.** The docstring overclaims. The S11 anchor names came
  from the fixture spec, so this is not an implementation defect; the wording must be narrowed before
  Stage 8 cites the probe as an E2E mirror.
- **F7 — accepted, routed to Stage 2, backlog 11.** Pre-existing, but Stage 6 commits these files and
  Stage 2 is the privacy-evidence stage, so it belongs there rather than reopening Stage 1.
- **F8 — accepted, backlog 12, no action.** The gate is met; I verified it from the re-run JSON myself
  and recorded that in the journal. The lesson is that a gate whose proof lives under a gitignored path
  needs its artifact copied into `validation/`, which future stages should do.

No finding was dismissed. Per `goal.md` guardrail 8, none of these is a product-correctness, privacy, or
false-`PASS` issue in Stage 1's own deliverable, so none blocks the stage.
