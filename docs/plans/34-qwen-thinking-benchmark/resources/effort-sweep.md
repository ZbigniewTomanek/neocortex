# Qwen per-agent effort sweep

| Agent | Level | Status | Selected | Triplets | Facts | Timeouts | p50 s | p95 s | Raw |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| extractor | off | PASS | yes | 1 | 42/56 | 0 | 17.7 | 36.71 | resources/sweep/off.json |
| extractor | low | PASS | no | 1 | 39/56 | 0 | 38.64 | 67.06 | resources/sweep/extractor-low.json |
| extractor | medium | DISQUALIFIED | no | 0 | 22/56 | 0 | — | — | resources/sweep/extractor-medium.json |
| extractor | high | DISQUALIFIED | no | 0 | 0/56 | 0 | — | — | resources/sweep/extractor-high.json |
| librarian | off | PASS | yes | 1 | 42/56 | 0 | 0.0 | 4.82 | resources/sweep/librarian-off.json |
| librarian | low | PASS | no | 1 | 42/56 | 0 | 0.0 | 9.91 | resources/sweep/librarian-low.json |
| librarian | medium | PASS | no | 1 | 42/56 | 0 | 0.0 | 9.1 | resources/sweep/librarian-medium.json |
| librarian | high | DISQUALIFIED | no | 0 | 42/56 | 0 | — | — | resources/sweep/librarian-high.json |
| ontology | off | PASS | yes | — | 43/56 | 0 | 6.74 | 8.38 | resources/sweep/ontology-off.json |
| ontology | low | NOT MEASURED | no | — | — | — | — | — | resources/sweep/ontology-low.json |
| ontology | medium | NOT MEASURED | no | — | — | — | — | — | resources/sweep/ontology-medium.json |
| ontology | high | NOT MEASURED | no | — | — | — | — | — | resources/sweep/ontology-high.json |
| classifier | off | PASS | yes | — | 45/56 | 0 | 3.67 | 6.06 | resources/sweep/classifier-off.json |
| classifier | low | PASS | no | — | 46/56 | 0 | 8.64 | 12.71 | resources/sweep/classifier-low.json |
| classifier | medium | PASS | no | — | 47/56 | 0 | 5.09 | 13.02 | resources/sweep/classifier-medium.json |
| classifier | high | DISQUALIFIED | no | — | 43/56 | 0 | 0.04 | 0.25 | resources/sweep/classifier-high.json |

## Applied selections

- extractor: **off** (SELECTED); tier=1, best=42, floor=40, candidates=['off']
- librarian: **off** (SELECTED); tier=1, best=42, floor=40, candidates=['off', 'low', 'medium']
- ontology: **off** (SELECTED); tier=None, best=43, floor=41, candidates=['off']
- classifier: **off** (SELECTED); tier=None, best=None, floor=None, candidates=['off', 'low', 'medium']

Selection first maximizes the applicable triplet tier, then compact facts, then chooses the lowest
effort within two facts of the tier best. Classifier chooses the lowest 8/8-valid eligible level.
NOT MEASURED never passes a selection gate.
