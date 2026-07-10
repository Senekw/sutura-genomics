# Foundation-model features vs Sutura SVD - cross-donor generalization

_Generated 2026-07-10T18:28:27Z on branch `foundation-features`._

**Question.** Sutura's per-fold TruncatedSVD node features plateau at ~9.6 spot-pitches held-out-donor error (PASTE2 ~3.5). Does swapping in a pretrained/self-supervised foundation-model embedding - with the alignment architecture, tear benchmark, LODO protocol, and training recipe (augmentation + weight decay + early stopping) all held fixed - move held-out error toward or below PASTE2?


**Headline.** Best embedding = `scvi` at 7.39 pitches held-out (PASTE2 4.36, prior SVD 9.6). It **narrows but does NOT reach PASTE2** (moves +2.21 vs the SVD plateau; +3.03 vs PASTE2).


## Ranked held-out error (mean over LODO folds, lower is better)

| rank | feature | held-out (pitch) | PASTE2 | vs PASTE2 | vs SVD plateau | folds |
|---|---|---|---|---|---|---|
| 1 | `scvi` | 7.39 | 4.36 | +3.03 | -2.21 | 3 |
| 2 | `svd` | 8.26 | 4.36 | +3.90 | -1.34 | 3 |

Reference lines: prior SVD plateau 9.6, PASTE2 mean 4.36 pitches.


## Conditions skipped or failed (installability / runtime)

- `scvi_batch`: error - ValueError: Category 151669 not found in source registry. Cannot transfer setup without `extend_categories = True`.
- `scgpt`: skipped_unavailable - no backend importable (needs pretrained scGPT checkpoint + gene vocab download, often flash-attn/CUDA). scgpt: ModuleNotFoundError: No module named 'scgpt'
- `geneformer`: skipped_unavailable - no backend importable (needs HuggingFace Geneformer model + tokenizer/median-dict download). geneformer: ModuleNotFoundError: No module named 'geneformer'
- `uce`: skipped_unavailable - no backend importable (needs UCE repo + multi-GB protein-embedding + model checkpoint download). uce: ModuleNotFoundError: No module named 'uce' | UCE: ModuleNotFoundError: No module named 'UCE'


## Per-fold detail

| feature | held-out donor | held-out (pitch) | in-dist | PASTE2 | beats PASTE2 | dim | sec | status |
|---|---|---|---|---|---|---|---|---|
| `svd` | Br5292 | 8.527 | 3.147 | 5.28 | False | 50 | 893.9 | ok |
| `svd` | Br5595 | 7.826 | 3.17 | 4.35 | False | 50 | 1099.6 | ok |
| `svd` | Br8100 | 8.44 | 3.423 | 3.46 | False | 50 | 967.0 | ok |
| `scvi` | Br5292 | 7.277 | 2.748 | 5.28 | False | 50 | 1201.4 | ok |
| `scvi` | Br5595 | 6.981 | 2.733 | 4.35 | False | 50 | 1305.4 | ok |
| `scvi` | Br8100 | 7.909 | 2.662 | 3.46 | False | 50 | 1335.3 | ok |
| `scvi_batch` | Br5292 | - | - | - | - | - | 379.8 | error |
| `scvi_batch` | Br5595 | - | - | - | - | - | 412.9 | error |
| `scvi_batch` | Br8100 | - | - | - | - | - | 421.9 | error |
| `scgpt` |  | - | - | - | - | - |  | skipped_unavailable |
| `geneformer` |  | - | - | - | - | - |  | skipped_unavailable |
| `uce` |  | - | - | - | - | - |  | skipped_unavailable |

## Interpretation

`scvi` narrows the cross-donor gap materially vs the SVD plateau (7.39 vs 9.6) but still trails PASTE2 - the embedding is a better prior, yet not sufficient on its own.
