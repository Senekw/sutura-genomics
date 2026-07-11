# Test-time adaptation on the held-out donor - LODO tear benchmark

_Generated 2026-07-11T01:49:03Z on branch `foundation-features`._

**Question.** The foundation-features experiment showed the cross-donor gap is an ALIGNER problem, not a feature problem. Does adapting the trained aligner to the held-out donor at inference - self-supervised, on the donor's own section geometry, no target correspondence used - close the gap to PASTE2?


**Headline.** Self-supervised TTA moves held-out error 7.39 -> 4.47 pitches (PASTE2 4.36). It **narrows the gap but does NOT reach PASTE2** (-2.92 vs no-TTA, +0.11 vs PASTE2; 2/3 folds beat PASTE2).


## Per-fold

| held-out donor | no-TTA | +self-TTA | delta | PASTE2 | beats PASTE2 | in-dist | TTA steps |
|---|---|---|---|---|---|---|---|
| Br5292 | 7.277 | 4.203 | -3.074 | 5.28 | True | 2.748 | 360 |
| Br5595 | 6.981 | 3.991 | -2.99 | 4.35 | True | 2.733 | 360 |
| Br8100 | 7.909 | 5.217 | -2.692 | 3.46 | False | 2.662 | 360 |

Reference: prior SVD plateau 9.6, inductive SVD no-TTA mean was ~8.26 pitches.


## Interpretation

Self-TTA recovers part of the gap (consistent with autoadapt's ~30-70% error reductions) but still trails PASTE2 - adaptation helps yet the aligner's inductive bias remains the ceiling. Routing OOD inputs to PASTE2 stays the right product call.
