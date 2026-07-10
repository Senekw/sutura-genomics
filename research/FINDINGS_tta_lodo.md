# Test-time adaptation on the held-out donor - LODO tear benchmark

_Generated 2026-07-10T22:43:34Z on branch `foundation-features`._

**Question.** The foundation-features experiment showed the cross-donor gap is an ALIGNER problem, not a feature problem. Does adapting the trained aligner to the held-out donor at inference - self-supervised, on the donor's own section geometry, no target correspondence used - close the gap to PASTE2?


**Headline.** Self-supervised TTA moves held-out error 8.53 -> 4.63 pitches (PASTE2 5.28). It **CLOSES the gap (reaches PASTE2)** (-3.90 vs no-TTA, -0.65 vs PASTE2; 1/1 folds beat PASTE2).


## Per-fold

| held-out donor | no-TTA | +self-TTA | delta | PASTE2 | beats PASTE2 | in-dist | TTA steps |
|---|---|---|---|---|---|---|---|
| Br5292 | 8.527 | 4.631 | -3.896 | 5.28 | True | 3.147 | 360 |

Reference: prior SVD plateau 9.6, inductive SVD no-TTA mean was ~8.26 pitches.


## Interpretation

Inference-time self-adaptation reaches PASTE2 - the aligner CAN generalize to an unseen donor given a few unsupervised steps on its geometry; the gap is a deploy-time adaptation problem, not a fundamental limit.
