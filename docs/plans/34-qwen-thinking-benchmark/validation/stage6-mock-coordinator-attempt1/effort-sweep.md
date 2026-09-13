# Qwen per-agent effort sweep

| Agent | Level | Status | Selected | Triplets | Facts | Timeouts | p50 s | p95 s | Raw |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| extractor | off | PASS | yes | 0 | 0/56 | 0 | 0.0 | 0.0 | validation/stage6-mock-coordinator-attempt1/baseline.json |
| extractor | low | PASS | no | 0 | 0/56 | 0 | 0.0 | 0.0 | validation/stage6-mock-coordinator-attempt1/sweep/extractor-low.json |
| extractor | medium | PASS | no | 0 | 0/56 | 0 | 0.0 | 0.0 | validation/stage6-mock-coordinator-attempt1/sweep/extractor-medium.json |
| extractor | high | PASS | no | 0 | 0/56 | 0 | 0.0 | 0.0 | validation/stage6-mock-coordinator-attempt1/sweep/extractor-high.json |
| librarian | off | PASS | yes | 0 | 0/56 | 0 | 0.0 | 0.0 | validation/stage6-mock-coordinator-attempt1/sweep/librarian-off.json |
| librarian | low | PASS | no | 0 | 0/56 | 0 | 0.0 | 0.0 | validation/stage6-mock-coordinator-attempt1/sweep/librarian-low.json |
| librarian | medium | PASS | no | 0 | 0/56 | 0 | 0.0 | 0.0 | validation/stage6-mock-coordinator-attempt1/sweep/librarian-medium.json |
| librarian | high | PASS | no | 0 | 0/56 | 0 | 0.0 | 0.0 | validation/stage6-mock-coordinator-attempt1/sweep/librarian-high.json |
| ontology | off | PASS | yes | — | 0/56 | 0 | 0.0 | 0.0 | validation/stage6-mock-coordinator-attempt1/sweep/ontology-off.json |
| ontology | low | PASS | no | — | 0/56 | 0 | 0.0 | 0.0 | validation/stage6-mock-coordinator-attempt1/sweep/ontology-low.json |
| ontology | medium | PASS | no | — | 0/56 | 0 | 0.0 | 0.0 | validation/stage6-mock-coordinator-attempt1/sweep/ontology-medium.json |
| ontology | high | PASS | no | — | 0/56 | 0 | 0.0 | 0.0 | validation/stage6-mock-coordinator-attempt1/sweep/ontology-high.json |
| classifier | off | PASS | yes | — | 0/56 | 0 | 0.0 | 0.0 | validation/stage6-mock-coordinator-attempt1/sweep/classifier-off.json |
| classifier | low | PASS | no | — | 0/56 | 0 | 0.0 | 0.01 | validation/stage6-mock-coordinator-attempt1/sweep/classifier-low.json |
| classifier | medium | PASS | no | — | 0/56 | 0 | 0.0 | 0.0 | validation/stage6-mock-coordinator-attempt1/sweep/classifier-medium.json |
| classifier | high | PASS | no | — | 0/56 | 0 | 0.0 | 0.0 | validation/stage6-mock-coordinator-attempt1/sweep/classifier-high.json |

## Applied selections

- extractor: **off** (SELECTED); tier=0, best=0, floor=-2, candidates=['off', 'low', 'medium', 'high']
- librarian: **off** (SELECTED); tier=0, best=0, floor=-2, candidates=['off', 'low', 'medium', 'high']
- ontology: **off** (SELECTED); tier=None, best=0, floor=-2, candidates=['off', 'low', 'medium', 'high']
- classifier: **off** (SELECTED); tier=None, best=None, floor=None, candidates=['off', 'low', 'medium', 'high']

Selection first maximizes the applicable triplet tier, then compact facts, then chooses the lowest
effort within two facts of the tier best. Classifier chooses the lowest 8/8-valid eligible level.
NOT MEASURED never passes a selection gate.
