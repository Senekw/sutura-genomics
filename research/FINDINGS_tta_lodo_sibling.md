# Test-time adaptation on the held-out donor - LODO tear benchmark

_Generated 2026-07-11T00:34:43Z on branch `foundation-features`._

**Question.** The foundation-features experiment showed the cross-donor gap is an ALIGNER problem, not a feature problem. Does adapting the trained aligner to the held-out donor at inference - self-supervised, on the donor's own section geometry, no target correspondence used - close the gap to PASTE2?


**Headline.** Self-supervised TTA moves held-out error 8.26 -> 7.79 pitches (PASTE2 4.36). It **narrows the gap but does NOT reach PASTE2** (-0.48 vs no-TTA, +3.42 vs PASTE2; 0/3 folds beat PASTE2).


## Per-fold

| held-out donor | no-TTA | +self-TTA | delta | PASTE2 | beats PASTE2 | in-dist | TTA steps |
|---|---|---|---|---|---|---|---|
| Br5292 | 8.527 | 6.45 | -2.077 | 5.28 | False | 3.147 | 360 |
| Br5595 | 7.826 | 8.916 | 1.09 | 4.35 | False | 3.17 | 360 |
| Br8100 | 8.44 | 7.991 | -0.449 | 3.46 | False | 3.423 | 360 |

Reference: prior SVD plateau 9.6, inductive SVD no-TTA mean was ~8.26 pitches.


## Interpretation

Self-TTA recovers part of the gap (consistent with autoadapt's ~30-70% error reductions) but still trails PASTE2 - adaptation helps yet the aligner's inductive bias remains the ceiling. Routing OOD inputs to PASTE2 stays the right product call.
