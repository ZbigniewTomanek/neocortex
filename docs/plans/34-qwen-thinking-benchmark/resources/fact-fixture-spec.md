# Fact fixture specification

`resources/fact-fixture.json` is built in Stage 1 from these sources. Every `facts[]` string must be an
exact, case-insensitive substring of its episode text; the loader rejects anything else. Do not paraphrase
a fact. Candidate facts are listed so the implementer copies from the corpus, not from memory.

Corpus: `load_corpus(profile="compact")` in `scripts/corpus_loader.py`, backed by
`docs/plans/33-local-qwen-migration/resources/compact-corpus.md`.

## Compact episodes — candidate scalar facts

| Key | Candidate facts (copy exact substrings from the episode text) |
|-----|------------------------------------------------------------------|
| E02 | `Tomek Zbigniew`, `Anya Kowalski`, `Jonas Weber`, `Sarah Kim`, `TDD-first`, `pytest`, `Poetry`, `Precision, Recall, F1` |
| E04 | `~15 normalized tables`, `person_normalized_data`, `phones_normalized`, `E.164`, `addresses_normalized`, `Libpostal`, `identifiers_normalized`, `ORDER BY + SEGMENTED BY`, `entity_object_id` |
| E05 | `39 atomic features`, `27 for organization`, `15 composite features`, `NAMEPHONE`, `NAMEDATE`, `phonetic_family_name + phone_e164` |
| E10 | `IdentifierLinkNormalizationService`, `db/quoting.py`, `quote_identifier`, `phone_link_service.py`, `address_link_service.py` |
| E18 | `Metaphone3`, `Soundex`, `>98% accuracy`, `~70%`, `4-character`, `252M entities`, `XMT0` |
| E20 | `8-character`, `maxCodeLen=8`, `approximately 60%`, `P1-P8`, `O1-O5`, `DoubleMetaphone`, `vertica-functions-datawalk-library.jar`, `encodeVowels`, `1M scale` |
| E26 | `HYBRID APPROACH`, `8-character Metaphone3 for Latin-script`, `4-character Metaphone3 for non-Latin`, `Korean, Chinese, and Arabic`, `3-4 different 8-char codes`, `language detection` |
| E27 | `Jonas Weber`, `Security team`, `Sarah Kim`, `Anya Kowalski`, `three people instead of four`, `deferred to Q3` |

Keep 6–10 facts per episode. Prefer numbers, identifiers, and code names over prose. Names count because
the librarian merge can lose them on homonym handling.

Chain expectation: `{"chain": ["E18", "E20", "E26"], "min_temporal_edges": 1}` — after the three episodes
run on one shared repository in order, at least one `SUPERSEDES` or `CORRECTS` edge exists.

## Supersession triplets — copied verbatim from the E2E scripts

These reproduce the three quality scenarios that failed in Plan 33 run `20260911T001509Z-swift3`. S05 and S11 are two-episode supersessions; S07 is a single correction-framing episode after an introduction, so only `new_present` carries signal there.

| Id | Source constants | `anchor_names` | `new_tokens` | `old_tokens` | E2E check mirrored |
|----|------------------|----------------|--------------|--------------|--------------------|
| S05 | `S5_INITIAL`, `S5_UPDATE` in `scripts/e2e_plan15_scenarios_test.py` | `["zenith"]` | `["may 1", "may"]` | `["april 15", "april"]` | `scenario_05_deadline_contradiction`: content has `may`, not `april` |
| S11 | `S11_INITIAL`, `S11_UPDATE` in `scripts/e2e_plan15_scenarios_test.py` | `["plan 42", "scaling exponent"]` | `["0.62"]` | `["0.57"]` | `scenario_11_fact_supersession`: `0.62` present |
| S07 | `EP1_TEAM` (initial; introduces DataForge) then `EP7_PRECISION` (update; states both 87% and 94.2% in one text) in `scripts/e2e_plan17_validation.py` | `["dataforge", "nlp", "precision"]` | `["94.2"]` | `[]` (the correction legitimately names the old 87%; `old_absent` is vacuously true) | `scenario_07_correction_framing`: content has `94.2` |

Each triplet runs `initial_text` then `update_text` through the full pipeline on one shared in-memory
repository. `old_absent` is judged over the anchor nodes' `content` only, matching the E2E scripts.

## JSON shape

```json
{
  "revision": 1,
  "episodes": [{"key": "E04", "facts": ["~15 normalized tables", "E.164"]}],
  "chain": {"episodes": ["E18", "E20", "E26"], "min_temporal_edges": 1},
  "supersession": [{
    "id": "S05", "initial_text": "...", "update_text": "...",
    "anchor_names": ["zenith"], "new_tokens": ["may 1", "may"], "old_tokens": ["april 15", "april"]
  }]
}
```

## Scoring rules (implemented in `scripts/fact_retention.py`)

- Normalize: lower-case, collapse whitespace, on both the fact and the concatenation of node `name`,
  `content`, and stringified property values.
- `facts_found` counts distinct fixture facts matched anywhere in the graph produced for that episode.
- `new_present`: any `new_tokens` in the concatenated `content` of nodes whose lower-cased name contains
  any anchor. `old_absent`: no `old_tokens` in that same text. `temporal_edge_present`: any
  `SUPERSEDES`/`CORRECTS` edge with an anchor node at either end.
- Output carries fixture indices and booleans only; never graph text.
