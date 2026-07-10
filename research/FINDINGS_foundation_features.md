# Foundation-model features vs Sutura SVD - cross-donor generalization

_Generated 2026-07-10T15:48:27Z on branch `foundation-features`._

**Question.** Sutura's per-fold TruncatedSVD node features plateau at ~9.6 spot-pitches held-out-donor error (PASTE2 ~3.5). Does swapping in a pretrained/self-supervised foundation-model embedding - with the alignment architecture, tear benchmark, LODO protocol, and training recipe (augmentation + weight decay + early stopping) all held fixed - move held-out error toward or below PASTE2?


**Headline.** Best embedding = `scvi` at 12.52 pitches held-out (PASTE2 5.28, prior SVD 9.6). It **does NOT help vs the SVD plateau** (moves -2.92 vs the SVD plateau; +7.24 vs PASTE2).


## Ranked held-out error (mean over LODO folds, lower is better)

| rank | feature | held-out (pitch) | PASTE2 | vs PASTE2 | vs SVD plateau | folds |
|---|---|---|---|---|---|---|
| 1 | `scvi` | 12.52 | 5.28 | +7.24 | +2.92 | 1 |
| 2 | `svd` | 13.69 | 5.28 | +8.41 | +4.09 | 1 |

Reference lines: prior SVD plateau 9.6, PASTE2 mean 5.28 pitches.


## Per-fold detail

| feature | held-out donor | held-out (pitch) | in-dist | PASTE2 | beats PASTE2 | dim | sec | status |
|---|---|---|---|---|---|---|---|---|
| `svd` | Br5292 | 13.687 | 8.381 | 5.28 | False | 50 | 114.2 | ok |
| `scvi` | Br5292 | 12.522 | 7.924 | 5.28 | False | 50 | 80.3 | ok |

## Interpretation

No embedding tested meaningfully beat the SVD plateau. The cross-donor gap does NOT appear to be fixable by swapping node features alone - consistent with the atlas-diversity result that the bottleneck is donor count / the alignment prior, not the expression featurizer.
