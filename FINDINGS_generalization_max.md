# Generalization-max — findings

**Branch:** `generalization-max` · **Date:** 2026-07-08 · Diagnostic; `main`, website, demo untouched.
Code: `src/generalization_max.py` (unified harness + LODO driver), `src/plot_generalization_max.py`.
Outputs: `results/generalization_max.csv`, `results/generalization_max.png`.

## TL;DR — did anything close the gap to PASTE2?

**No.** Across every intervention, the best held-out (unseen-donor) error is **8.26
spot-pitches** (augmentation + regularization), versus PASTE2's LODO-mean **4.36** —
a residual gap of **+3.9 pitch (~1.9×)**. Nothing reached the ~3.5–4.4 target. The
interventions we can apply in-house each move the number a little; none is close to
sufficient. The binding constraint is **data**: the DLPFC dataset has only **3
donors**, so maximum donor diversity is 2 training donors, and the diversity trend
extrapolates to needing **~5+ donors (optimistically) and realistically many more**
to match PASTE2.

## Setup

Leave-one-donor-out (LODO) 3-fold CV across Br5292 / Br5595 / Br8100. The frozen
shared basis is kept throughout and **re-fit per fold on the training donors only**
(transform-only). Held-out = tear benchmark (severities 0–8, median error in
spot-pitches) on the held-out donor's pair; in-distribution = a training-donor pair
(held-out warp seeds). PASTE2 baselines reused from the prior full-resolution sweep
(Br5292 5.28, Br5595 4.35, Br8100 3.46; LODO mean 4.36). Cheaper ablations
(1-donor, HVG, contrastive+spatial) were run on the Br8100 fold; the core configs
ran full 3-fold LODO.

## Ranked results (held-out median error, spot-pitches; lower is better)

| rank | intervention | in-dist | **held-out** | folds | vs PASTE2 |
|---:|---|--:|--:|:--:|--:|
| 1 | **augment + weight-decay + early-stop** (2 donors × 2 pairs) | 3.25 | **8.26** | LODO | +3.9 |
| 2 | contrastive + spatial losses (on aug base) | 3.32 | 9.03 | Br8100 | +5.6 |
| 3 | diversity: 2 donors × 2 pairs | 2.12 | 9.09 | LODO | +4.7 |
| 4 | HVG-shared features (aug base) | 3.36 | 9.43 | Br8100 | +6.0 |
| 5 | baseline: 2 donors × 1 pair (shared basis) | 1.17 | 9.82 | LODO | +5.5 |
| 6 | baseline: 1 donor × 1 pair | 0.72 | 11.00 | Br8100 | +7.5 |
| — | **PASTE2** | — | **4.36** | — | — |

## Ranked by how much each lever *moved* the held-out number

From the standard shared-basis baseline (2 donors × 1 pair, LODO 9.82):

1. **Augmentation + regularization: −1.56 pitch** (9.82 → 8.26). The single biggest
   mover. Heavy domain randomization (feature dropout/noise, spot subsampling, batch
   shift, random rotation, wider tears) + weight decay + early stopping. It works by
   *narrowing the train/held-out gap* — note in-distribution error **rose** (1.2 →
   3.3) as the model was forced to stop memorizing donors. But the held-out floor
   only fell to ~8.
2. **More donors (1 → 2): −1.29 pitch** on Br8100 (11.0 → 9.71). Real but shallow.
3. **More pairs per donor (1 → 2): −0.73 pitch** LODO (9.82 → 9.09). Diminishing.
4. **Contrastive + spatial losses: −0.68 pitch** on Br8100 vs the 2-donor baseline —
   but *worse* than augmentation alone (9.03 vs 8.44 on the same fold), i.e. stacking
   the correspondence-contrastive InfoNCE + displacement-smoothness terms on top of
   augmentation did **not** help and slightly hurt.
5. **HVG-shared features: −0.28 pitch** on Br8100. Re-fitting the frozen basis on
   2,000 shared highly-variable genes barely changed anything — consistent with the
   earlier finding that the representation was not the bottleneck once rotation was
   fixed.

## Does more donor diversity shrink held-out error? (the extrapolation)

Yes, monotonically, but far too slowly. On Br8100:

| training data | held-out error |
|---|--:|
| 1 donor, 1 pair | 11.00 |
| 2 donors, 1 pair each | 9.71 |
| 2 donors, 2 pairs each | 8.42 |

A crude linear fit reaches PASTE2 (~4.4) at **~9 training pairs ≈ ~5 donors**. That is
already more donors than the dataset contains (3), and the trend is almost certainly
**sub-linear / diminishing** (the 1→2-pair step gained less than the 1→2-donor step),
so the true requirement is **substantially more than 5 donors** — plausibly a
multi-donor atlas (dozens). With only 3 DLPFC donors available we cannot get there,
and no amount of the other interventions substitutes for it.

## Honest per-front summary

- **Donor diversity (front 1):** helps, monotonic, but shallow and capped at 2
  training donors by the data. This is the *right* lever and the root cause, but we
  lack the donors to pull it far enough.
- **Regularization + augmentation (front 2):** the best in-house lever (−1.56). It
  buys generalization by sacrificing in-distribution accuracy, but plateaus at ~8.
- **Better features (front 3):** HVG-shared basis ≈ no change. Pretrained expression
  encoders (scVI / scGPT / Geneformer) were **not run** — scVI's VAE and the
  foundation-model embeddings need heavy installs / multi-GB model + gene-vocabulary
  mapping that were not feasible in this environment. Flagged as untested, not
  dismissed; given HVG's null result and the earlier silhouette≈0 diagnosis, a better
  static feature space is unlikely to be the missing factor, but a foundation-model
  embedding trained across many donors is the one feature idea that could in principle
  supply the cross-donor prior the data doesn't.
- **Architecture / losses (front 4):** correspondence-contrastive + spatial-smoothness
  did not help on top of augmentation (slightly worse). Note the contrastive term here
  used within-pair negatives; true cross-donor contrastive negatives would need
  multi-donor batching — a further extension, but not promising given the trend.
- **LODO (front 5):** applied as the metric throughout; the numbers above are 3-fold
  LODO for the core configs, so they are not a lucky single split. Per-fold spread is
  modest (e.g. augment_reg: 8.53 / 7.83 / 8.44), so the ~8-pitch floor is robust.

## Bottom line

The remaining gap is **not** closable with the levers available on 3 donors.
Augmentation + regularization is the best single intervention (held-out 9.82 → 8.26)
and diversity helps monotonically, but the model floors at ~8 pitch held-out while
PASTE2 sits at ~4.4. The extrapolated requirement — a genuinely multi-donor training
set (≥5, realistically many more) — is the only thing the evidence says would close
it. Until such data exists, the honest product answer stands: **route off-distribution
inputs to PASTE2** (the orchestrator already does this), use **auto-adapt** to narrow
the gap on the user's own data when possible, and treat a broad multi-donor atlas as
the prerequisite for making Sutura itself competitive out-of-distribution.
