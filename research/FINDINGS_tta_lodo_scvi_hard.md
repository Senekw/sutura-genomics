# Test-time adaptation on the held-out donor - LODO tear benchmark

_Generated 2026-07-11T17:03:37Z on branch `foundation-features`._

**Question.** The foundation-features experiment showed the cross-donor gap is an ALIGNER problem, not a feature problem. Does adapting the trained aligner to the held-out donor at inference - self-supervised, on the donor's own section geometry, no target correspondence used - close the gap to PASTE2?


**Headline.** Self-supervised TTA moves held-out error 7.91 -> 5.11 pitches (PASTE2 3.46). It **narrows the gap but does NOT reach PASTE2** (-2.80 vs no-TTA, +1.65 vs PASTE2; 0/1 folds beat PASTE2).


## Per-fold

| held-out donor | no-TTA | +self-TTA | delta | PASTE2 | beats PASTE2 | in-dist | TTA steps |
|---|---|---|---|---|---|---|---|
| Br8100 | 7.909 | 5.111 | -2.798 | 3.46 | False | 2.662 | 720 |

Reference: prior SVD plateau 9.6, inductive SVD no-TTA mean was ~8.26 pitches.


## Interpretation

Self-TTA recovers part of the gap (consistent with autoadapt's ~30-70% error reductions) but still trails PASTE2 - adaptation helps yet the aligner's inductive bias remains the ceiling. Routing OOD inputs to PASTE2 stays the right product call.
