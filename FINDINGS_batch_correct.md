# Batch correction on shared-basis features — findings

**Branch:** `batch-correct` · **Date:** 2026-07-08 · Diagnostic; `main`, website, demo untouched.
Code: `src/batch_correct.py` (feature integration), `src/train_batch_correct.py`,
`src/eval_batch_correct.py`, `src/plot_batch_correct.py`.
Outputs: `results/batch_correct.csv`, `results/batch_correct.png`, checkpoints
`results/arca_batch_{none,harmony,scanorama}.pt`, feature caches
`results/batchfeat_{none,harmony,scanorama}.npz`.

## TL;DR

**Batch correction does not close the held-out gap.** Held-out donor Br8100 stays at
~9–11 spot-pitches — statistically unchanged from the shared-basis baseline (9.59) —
versus PASTE2's 3.46. Harmony nudges it by 0.27 pitch (~3%, within seed noise);
Scanorama makes it *worse* (11.13). Neither comes close to PASTE2.

| Donor | Condition | shared-basis (none) | + Harmony | + Scanorama | PASTE2 |
|---|---|---:|---:|---:|---:|
| Br5292 | in-distribution | 1.38 | 1.00 | 1.39 | 5.28 |
| Br5595 | in-distribution | 1.17 | 0.75 | 1.17 | 4.35 |
| **Br8100** | **held-out** | **9.59** | **9.33** | **11.13** | **3.46** |

(median registration error in spot-pitches, tear benchmark severities 0–8, seeds 0–2.)

## The key questions, answered

- **Does batch correction move held-out Br8100 below the 9.58 baseline?** Barely, and
  only for Harmony: **9.33** (−0.27 pitch, ~3% — inside run-to-run noise). Scanorama
  goes the wrong way: **11.13** (+1.53). So: no meaningful improvement.
- **How close does it get to PASTE2's 3.46?** Not close. The held-out error stays
  ~2.7–3.2× PASTE2. The 6-pitch gap is essentially unchanged.

## Why it doesn't help (diagnosed up front, confirmed after)

Before training, we measured donor separation in the frozen-basis feature space with
a silhouette score (donor as label):

- raw frozen-basis features: silhouette **+0.001** — i.e. the donors are *already
  mixed*; there is almost no donor batch effect left in the 50-d shared-basis space.
- after Harmony: −0.031; after Scanorama: −0.036 — marginally more mixed, but starting
  from ~0 there is nothing to gain.

**The shared frozen basis is itself an alignment**: because the SVD directions are fit
once on pooled donors and applied identically to everyone, donor feature distributions
already overlap. So there is no residual batch effect for Harmony/Scanorama to remove.
The held-out failure is therefore **not** a feature-distribution shift — it is the
model overfitting the *training donors' feature→geometry mapping*. Aligning feature
distributions cannot fix a mapping that was learned on too few donors. This matches the
`FINDINGS_shared_basis.md` conclusion: closing the gap needs more donor diversity in
*supervised* training, not more feature preprocessing.

In-distribution, correction is a wash (Harmony marginally helps, ~0.75–1.00 pitch;
Scanorama unchanged), consistent with "little to correct."

## Method / adaptations (honest)

- **Pipeline (frozen basis kept throughout):** raw counts → lib-norm + log1p → FROZEN
  shared-basis SVD projection → **donor batch integration** → standardization → model.
  Integration is done on the 50-d frozen-basis embedding with **donor** as the batch
  variable (section-level variation within a donor is the registration signal, so it
  is not treated as batch). Integrating in the frozen-embedding space (rather than in
  gene space) keeps the shared basis intact, is Harmony's native input space, and lets
  Harmony and Scanorama be compared in the same space/dimension.
- **Transductive integration.** Harmony and Scanorama have no out-of-sample transform,
  so the held-out donor's *expression* participates in the unsupervised integration
  (all three donors integrated jointly); it never participates in supervised training.
  This is the standard "integrate-then-hold-out" setup — and if anything it *favors*
  batch correction (the held-out donor is included in the alignment), so the negative
  result is conservative.
- **`none` reproduces the baseline.** The pipeline's no-correction condition retrains
  to 9.6 pitch held-out / ~1.2 in-distribution, matching `arca_shared_basis.pt`, which
  validates that the comparison isolates the effect of batch correction.
- Same architecture, same 100-epoch protocol, same train/held-out split as
  `train_shared_basis.py`; only the node-feature source changes.

## Bottom line

Batch correction (Harmony or Scanorama) on the shared-basis features **does not help**
cross-donor generalization: held-out error is unchanged (Harmony) or worse (Scanorama),
and remains ~3× PASTE2. The reason is concrete and was measured: the shared frozen
basis already removes donor separation in the feature space (silhouette ≈ 0), so there
is no batch effect left to correct. The remaining held-out gap is a supervised-model
generalization problem, not a feature-normalization problem — the productive next step
is broader training-donor diversity (or an architecture that does not memorize a single
donor's feature→geometry map), not more preprocessing. For deploying on off-distribution
data today, PASTE2 (or the orchestrator that routes to it) remains the right choice.
