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
| 4 | **self-supervised TTA** (target's own geometry) | **5.66** | **+1.29** | **1/3** | **WINNER** |
| 5 | sibling-supervised TTA (donor's 2nd pair, real GT) | 7.79 | +3.43 | 0/3 | worse than #4 |

¹ from the earlier `atlas-train` experiment (cross-tissue diversity does not close the gap).

scGPT / Geneformer / UCE were attempted but **do not install cleanly** in this env
(scGPT forces `scvi-tools<1.0` + jax/numpy2.4, an incompatible stack; Geneformer and UCE
are not on PyPI). Logged and skipped.

## The one finding

**The cross-donor gap is an ALIGNER problem, not a feature problem — and it is
addressable at deploy time.**

- Every *feature-side* lever failed to close it: better learned embeddings (scVI) help
  only ~16% and never beat PASTE2; even a *transductive* featurizer that sees the
  held-out donor's full expression distribution doesn't help. So it is not that the node
  features fail to transfer.
- The *aligner-side* lever worked: **self-supervised test-time adaptation** — at
  inference, adapt the trained aligner to the held-out donor's OWN section geometry via
  synthetic tears (self-GT, no target correspondence) — cuts held-out error **8.26 -> 5.66
  (~31%)**, beats PASTE2 on Br5292 (8.53->4.63 vs 5.28) and reaches near-parity on Br5595
  (5.06 vs 4.35). The hardest donor Br8100 improves (8.44->7.27) but stays ~2x PASTE2.
- **More/real supervision is not better.** Sibling-supervised TTA (real GT from the
  donor's *other* section pair) mean 7.79 — worse than self-TTA and it *hurt* on Br5595
  (7.83->8.92). The right adaptation signal is the target section's own multi-severity
  self-warps, which teach robustness to that donor's geometry without overfitting to one
  pair's specific deformation.

## Product / research implications

1. **Deploy self-TTA for new-donor inputs.** A short unsupervised adaptation on the
   incoming section's own geometry recovers ~a third of the gap and can match or beat
   PASTE2 on typical donors — with no target labels. This is the first thing that has
   moved the needle; it belongs in the off-distribution path (cf. `autoadapt.py`, which
   already implements the mechanism but had never been evaluated on this LODO protocol).
2. **Keep routing the hardest inputs to PASTE2.** Self-TTA does not yet uniformly beat
   PASTE2 (Br8100 remains ~2x). A keep-best-of {zero-shot, self-TTA, PASTE2} router stays
   the safe product policy.
3. **Stop chasing the featurizer.** Foundation embeddings and transductive features are
   dead ends for this gap; effort is better spent on the aligner's inductive bias and
   deploy-time adaptation.

## Open follow-ups (not yet run)

- Longer / higher-severity self-TTA budget — can Br8100 be pushed below PASTE2?
- Stack self-TTA on top of scVI features (each helped separately; do they compound?).
- Partial-parameter TTA (adapt only the refine head / a LoRA-style subset) to reduce
  overfitting on small held-out sections.
- More within-tissue donors (the atlas work suggested donor count, not tissue variety,
  is the training-side constraint) combined with self-TTA at inference.

## Artifacts (all on branch `foundation-features`)

- `research/results/foundation_features.{csv,png,log}` + `research/FINDINGS_foundation_features.md` — levers 2 (inductive).
- `research/results/foundation_features_transductive.{csv,png,log}` + `..._transductive.md` — lever 3.
- `research/results/tta_lodo.{csv,png,log}` + `research/FINDINGS_tta_lodo.md` — lever 4 (self-TTA, the winner).
- `research/results/tta_lodo_sibling.{csv,png,log}` + `..._sibling.md` — lever 5.
- Code: `src/foundation_features.py`, `src/tta_lodo.py` (reuse `generalization_max.py`'s LODO harness unchanged).
