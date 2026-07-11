# Test-time adaptation on the held-out donor - LODO tear benchmark

_Generated 2026-07-11T01:25:49Z on branch `foundation-features`._

**Question.** The foundation-features experiment showed the cross-donor gap is an ALIGNER problem, not a feature problem. Does adapting the trained aligner to the held-out donor at inference - self-supervised, on the donor's own section geometry, no target correspondence used - close the gap to PASTE2?


**Headline.** Self-supervised TTA moves held-out error 7.13 -> 4.10 pitches (PASTE2 4.81). It **CLOSES the gap (reaches PASTE2)** (-3.03 vs no-TTA, -0.72 vs PASTE2; 2/2 folds beat PASTE2).


## Per-fold

| held-out donor | no-TTA | +self-TTA | delta | PASTE2 | beats PASTE2 | in-dist | TTA steps |
|---|---|---|---|---|---|---|---|
| Br5292 | 7.277 | 4.203 | -3.074 | 5.28 | True | 2.748 | 360 |
| Br5595 | 6.981 | 3.991 | -2.99 | 4.35 | True | 2.733 | 360 |

Reference: prior SVD plateau 9.6, inductive SVD no-TTA mean was ~8.26 pitches.


## Interpretation

Inference-time self-adaptation reaches PASTE2 - the aligner CAN generalize to an unseen donor given a few unsupervised steps on its geometry; the gap is a deploy-time adaptation problem, not a fundamental limit.
