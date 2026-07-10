# Foundation-model features vs Sutura SVD - cross-donor generalization

_Generated 2026-07-10T22:11:12Z on branch `foundation-features`._

**Question.** Sutura's per-fold TruncatedSVD node features plateau at ~9.6 spot-pitches held-out-donor error (PASTE2 ~3.5). Does swapping in a pretrained/self-supervised foundation-model embedding - with the alignment architecture, tear benchmark, LODO protocol, and training recipe (augmentation + weight decay + early stopping) all held fixed - move held-out error toward or below PASTE2?


**Headline.** Best embedding = `scvi` at 7.67 pitches held-out (PASTE2 4.36, prior SVD 9.6). It **narrows but does NOT reach PASTE2** (moves +1.93 vs the SVD plateau; +3.31 vs PASTE2).


## Ranked held-out error (mean over LODO folds, lower is better)

| rank | feature | held-out (pitch) | PASTE2 | vs PASTE2 | vs SVD plateau | folds |
|---|---|---|---|---|---|---|
| 1 | `scvi` | 7.67 | 4.36 | +3.31 | -1.93 | 3 |
| 2 | `svd` | 8.82 | 4.36 | +4.46 | -0.78 | 3 |

Reference lines: prior SVD plateau 9.6, PASTE2 mean 4.36 pitches.


## Per-fold detail

| feature | held-out donor | held-out (pitch) | in-dist | PASTE2 | beats PASTE2 | dim | sec | status |
|---|---|---|---|---|---|---|---|---|
| `svd` | Br5292 | 8.783 | 3.085 | 5.28 | False | 50 | 1201.5 | ok |
| `svd` | Br5595 | 7.905 | 3.136 | 4.35 | False | 50 | 1224.9 | ok |
| `svd` | Br8100 | 9.784 | 3.312 | 3.46 | False | 50 | 1282.0 | ok |
| `scvi` | Br5292 | 6.767 | 2.827 | 5.28 | False | 50 | 1314.3 | ok |
| `scvi` | Br5595 | 6.689 | 2.88 | 4.35 | False | 50 | 1341.4 | ok |
| `scvi` | Br8100 | 9.551 | 2.635 | 3.46 | False | 50 | 1513.0 | ok |

## Interpretation

`scvi` narrows the cross-donor gap materially vs the SVD plateau (7.67 vs 9.6) but still trails PASTE2 - the embedding is a better prior, yet not sufficient on its own.
