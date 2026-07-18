# model-gen-2 - can a learned correction beat the gate on torn tissue?
_Generated 2026-07-18T08:41:39Z on branch `model-gen-2`._
**Question.** The learned absolute-coordinate model does not generalize to a held-out donor (~9 spot-pitches). PASTE2 generalizes for free (~4.4). The hand gate - a fit-residual-gated per-piece rigid refinement layered on PASTE2 - beats PASTE2 (~3.7) because it is a CORRECTION in base-relative geometry, not an absolute prediction. This experiment asks, systematically: can a LEARNED correction restricted to base-relative features transfer across donors and beat the hand gate?

**Benchmark.** (PASTE2 base not yet computed - re-run without --no-paste2.)

## Ranked results on the REAL PASTE2 base (lower is better)
| config | err (pitch) | std | n | vs PASTE2 base | vs hand gate |
|---|---|---|---|---|---|

## Verdict
- PASTE2 base not yet computed; no verdict against the gate available.
- OT-surrogate base (free, warp-invariant) is weak (12.63); its gate=12.62 . Confirms all real headroom is on the PASTE2 base, as expected.

## Leakage discipline
- Fold basis, every trained corrector, the learned gate: fit ONLY on the two TRAIN donors' SYNTHETIC tears. No ground-truth correspondence, test warp, or held-out coordinate enters training or the base.
- Base-relative correctors are trained on the cheap OT-surrogate base and evaluated on the real PASTE2 base; the transfer is legitimate precisely because the features carry no absolute/test information.
- PASTE2 runs on the test slice at inference only (baseline/base), never as a training signal. Eval warp seeds are disjoint from training seed streams.

## Configs run
