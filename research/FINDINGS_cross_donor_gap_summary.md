# What closes Sutura's cross-donor generalization gap? — a ledger

_Branch `foundation-features`, 2026-07-10/11. Every number is held-out-donor median
registration error in spot-pitches on the 3-DLPFC-donor leave-one-donor-out (LODO)
tear benchmark (train on 2 donors, hold out the 3rd, rotate; error averaged over tear
severities 0-8). Lower is better. PASTE2 is the unsupervised classical baseline._

## The gap

Sutura is excellent **in-distribution** (~2.7-3.4 pitches) but its per-fold SVD-feature
aligner does **not transfer across donors**: held-out mean **~8.3 pitches** (~1.9x PASTE2
**4.36**). The question this session answered: which lever actually closes that gap?

## Levers tested

| # | lever | held-out mean | vs PASTE2 (4.36) | folds beating PASTE2 | verdict |
|---|---|---|---|---|---|
| 0 | SVD baseline (this harness) | 8.26 | +3.90 | 0/3 | the gap |
| 1 | cross-tissue training diversity ¹ | ~10-26 | worse | 0/20 | no |
| 2 | foundation embeddings — scVI | 7.39 | +3.03 | 0/9 | marginal |
| 2 | foundation embeddings — scVI+batch (scArches) | **6.95** | +2.58 | 0/9 | marginal |
| 3 | transductive featurizer (SVD) | 8.82 | worse | 0/6 | no |
| 3 | transductive featurizer (scVI) | 7.67 | +3.31 | 0/6 | no |
| 4 | self-supervised TTA on SVD features (target's own geometry) | 5.66 | +1.29 | 1/3 | strong |
| 5 | sibling-supervised TTA (donor's 2nd pair, real GT) | 7.79 | +3.43 | 0/3 | worse than #4 |
| 6 | **scVI features + self-supervised TTA (composed)** | **4.47** | **+0.11** | **2/3** | **WINNER (PASTE2 parity)** |
| 7 | scVI + self-TTA, head-only (encoder frozen) | 6.39 | +2.03 | 0/3 | ablation: full-param is essential |

¹ from the earlier `atlas-train` experiment (cross-tissue diversity does not close the gap).

scGPT / Geneformer / UCE were attempted but **do not install cleanly** in this env
(scGPT forces `scvi-tools<1.0` + jax/numpy2.4, an incompatible stack; Geneformer and UCE
are not on PyPI). Logged and skipped.

## The one finding

**The cross-donor gap is closed to PASTE2 parity by composing a learned featurizer with
deploy-time self-adaptation — it was an ALIGNER problem all along, and the fix lives at
inference, not in the features alone.**

Progression, held-out mean: SVD **8.26** -> scVI features **7.39** -> self-TTA **5.66** ->
**scVI + self-TTA 4.47** (PASTE2 **4.36**), beating PASTE2 on 2/3 donors (Br5292
7.28->4.20 vs 5.28; Br5595 6.98->3.99 vs 4.35). Only the hardest donor Br8100 remains above
PASTE2 (5.22 vs 3.46) - still a large improvement over every earlier lever.

- Every *feature-side* lever failed to close it: better learned embeddings (scVI) help
  only ~16% and never beat PASTE2; even a *transductive* featurizer that sees the
  held-out donor's full expression distribution doesn't help. So it is not that the node
  features fail to transfer.
- The *aligner-side* lever worked: **self-supervised test-time adaptation** — at
  inference, adapt the trained aligner to the held-out donor's OWN section geometry via
  synthetic tears (self-GT, no target correspondence) — cuts held-out error **8.26 -> 5.66
  (~31%)**, beats PASTE2 on Br5292 and reaches near-parity on Br5595.
- **The two working levers COMPOUND.** scVI features (better base, 7.39) + self-TTA lands
  at **4.47 mean — PASTE2 parity — beating PASTE2 on 2/3 donors.** A better featurizer
  gives self-TTA a better starting point, and adaptation does the rest. So the featurizer
  is not useless; it is just insufficient *without* deploy-time adaptation.
- **More/real supervision is not better.** Sibling-supervised TTA (real GT from the
  donor's *other* section pair) mean 7.79 — worse than self-TTA and it *hurt* on Br5595
  (7.83->8.92). The right adaptation signal is the target section's own multi-severity
  self-warps, which teach robustness to that donor's geometry without overfitting to one
  pair's specific deformation.

## Product / research implications

1. **Deploy scVI-features + self-TTA for new-donor inputs.** Train the aligner on scVI
   node features, and at inference run a short unsupervised self-adaptation on the
   incoming section's own geometry (no target labels). This reaches PASTE2 parity on
   average and beats it on typical donors — the first configuration to do so. It belongs
   in the off-distribution path (cf. `autoadapt.py`, which implements the TTA mechanism
   but had never been evaluated on this LODO protocol, nor composed with scVI features).
2. **Keep a keep-best router for the hardest inputs.** The composition does not yet
   uniformly beat PASTE2 (Br8100 5.22 vs 3.46). keep-best-of {zero-shot, scVI+self-TTA,
   PASTE2} stays the safe product policy while Br8100-class donors are worked on.
3. **The featurizer matters only in combination.** Foundation embeddings and transductive
   features are dead ends *on their own*, but scVI's better base is what let self-TTA
   reach parity — so the lever is (better features) x (deploy-time adaptation), not either
   alone.

## Open follow-ups (not yet run)

- **Br8100 is not closable by more adaptation** (tested): partial-parameter TTA underfits
  (6.39 vs 4.47), and doubling the self-TTA budget to 720 steps at max-severity 10 left it
  at 5.11 (vs 5.22 at the standard budget) - flat. It is a genuinely harder donor, not
  under-adapted or overfit. The remaining lever for Br8100-class donors is **training-side
  (more within-tissue donors)**, consistent with the atlas finding, not more inference-time
  adaptation.
- More within-tissue donors (the atlas work suggested donor count, not tissue variety, is
  the training-side constraint) combined with scVI+self-TTA at inference.
- scVI + self-TTA is the current best config; a multi-seed rerun would firm up the 4.47
  vs 4.36 near-tie.

## Artifacts (all on branch `foundation-features`)

- `research/results/foundation_features.{csv,png,log}` + `research/FINDINGS_foundation_features.md` — levers 2 (inductive).
- `research/results/foundation_features_transductive.{csv,png,log}` + `..._transductive.md` — lever 3.
- `research/results/tta_lodo.{csv,png,log}` + `research/FINDINGS_tta_lodo.md` — lever 4 (self-TTA on SVD features).
- `research/results/tta_lodo_sibling.{csv,png,log}` + `..._sibling.md` — lever 5 (sibling-supervised TTA).
- `research/results/tta_lodo_scvi.{csv,png,log}` + `..._scvi.md` — lever 6 (scVI + self-TTA, the winner).
- Code: `src/foundation_features.py`, `src/tta_lodo.py` (reuse `generalization_max.py`'s LODO harness unchanged; `tta_lodo.py` supports `--mode {self,sibling}` and `--features {svd,scvi}`).
