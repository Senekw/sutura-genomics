# Test-time adaptation on the held-out donor - LODO tear benchmark

_Generated 2026-07-11T02:19:36Z on branch `foundation-features`._

**Question.** The foundation-features experiment showed the cross-donor gap is an ALIGNER problem, not a feature problem. Does adapting the trained aligner to the held-out donor at inference - self-supervised, on the donor's own section geometry, no target correspondence used - close the gap to PASTE2?


**Headline.** Self-supervised TTA moves held-out error 7.28 -> 5.96 pitches (PASTE2 5.28). It **narrows the gap but does NOT reach PASTE2** (-1.32 vs no-TTA, +0.68 vs PASTE2; 0/1 folds beat PASTE2).


## Per-fold

| held-out donor | no-TTA | +self-TTA | delta | PASTE2 | beats PASTE2 | in-dist | TTA steps |
|---|---|---|---|---|---|---|---|
| Br5292 | 7.277 | 5.956 | -1.321 | 5.28 | False | 2.748 | 360 |

Reference: prior SVD plateau 9.6, inductive SVD no-TTA mean was ~8.26 pitches.


## Interpretation

Self-TTA recovers part of the gap (consistent with autoadapt's ~30-70% error reductions) but still trails PASTE2 - adaptation helps yet the aligner's inductive bias remains the ceiling. Routing OOD inputs to PASTE2 stays the right product call.
