# Sutura Genomics — Hardened Abstract v2 (post-adversarial-review)

Incorporates every surviving fix from the reviewer2 + falsify-all + harden + surveil battery
([`ADVERSARIAL_REVIEW.md`](ADVERSARIAL_REVIEW.md)). Every number traces to a `results/*.csv` or to
`results/validation_ablations_run.txt`. No claim here failed the four-lane review.

---

## Title

**Tissue tearing degrades optimal-transport registration of spatial transcriptomics: a controlled
deformation benchmark and a supervised graph cross-attention proof-of-concept**

---

## Abstract (≈300 words)

**Background.** Three-dimensional reconstruction from serial spatial-transcriptomics (ST) sections requires
registering adjacent slices, but physical sectioning introduces *tears* — discontinuous, non-isometric
deformations. Leading methods rely on priors that tears strain: PASTE/PASTE2 use Fused Gromov-Wasserstein
optimal transport (OT), which assumes near-isometric preservation of within-slice distances, and STalign uses
diffeomorphic (LDDMM) mapping, which cannot change tissue topology. Learned-deformation ST methods are emerging
(e.g. STaCker, INST-Align), but the behaviour of OT/diffeomorphic registration under tearing has not been
systematically characterised.

**Methods.** On the spatialLIBD human DLPFC Visium dataset (Maynard et al., 2021), we build a controlled
benchmark: known smooth (near-isometric) warps, single-block rigid tears (gene expression left unchanged), and an
identity self-control, applied to a real slice at severities of 0–8 spot pitches, scored against an *approximate*
array-position ground truth (adjacent sections are different tissue ~300 µm apart; raw residual ~8 px). We
evaluate PASTE2 and a minimal graph model, **Sutura**, which encodes each slice as a spot graph, finds
correspondence by cross-attention between the two graphs, and predicts a per-spot displacement; its only spatial
coupling is local kNN message passing (there is **no explicit global-smoothness penalty**), so cross-tear
correspondences are not pulled toward a globally isometric solution. Sutura is trained **supervised** on this
tissue's ground truth (held-out warp seeds only); PASTE2 is **unsupervised/zero-shot**.

**Results.** In a single-seed evaluation, OT registration is robust to smooth warps but degrades under tearing:
nearest-correspondence (argmax) error rises **728→863 px** and layer-label accuracy falls **64.4%→57.5%**; the
effect strengthens with geometric weight, and a self-control gives **0 px** (the ~647 px soft-projection "floor"
is OT plan-smearing, not biology). Trained and evaluated on the *same donor*, Sutura fits torn-tissue
correspondence to a **median 99→118 px** (mean 115→319, p90 200→1205 — the tail concentrates at the seam),
well below a non-trivial expression-nearest-neighbour baseline (2532 px) — but this is a **supervised, in-sample,
fit-to-target** result, not a zero-shot accuracy comparable to PASTE2. Critically, the advantage is
**donor-specific**: on a held-out donor, error is **1029–1593 px across four training regimes — ~1.7–2.5× worse
than PASTE2 (526→691 px)** on the same tissue; multi-donor training and embedding-space batch correction narrow
but do not close the gap.

**Conclusion.** Tearing is a real, characterisable failure mode of OT/diffeomorphic ST registration. A learned
local-correspondence model can fit it in-sample, but **donor-invariant generalisation — already a recognised hard
problem for deep ST models — remains open**; we quantify it and define the path, benchmarking against
learned-deformation incumbents (STaCker, INST-Align).

---

## What changed from v1 (and why)

| v1 (pre-review) | v2 (hardened) | Driver |
|---|---|---|
| "~7× lower than OT" | PASTE2 **argmax 728→863** as the head-to-head; ~647 floor labelled an OT artifact; median **+ mean + p90** | FATAL 1 (estimator mismatch) + stats (median-only) |
| in-sample win stated like an accuracy | "**supervised, in-sample, fit-to-target**; PASTE2 is zero-shot" | FATAL 2 |
| "regularized only locally so tears aren't forced to agree" | "**no explicit global-smoothness penalty**; only local kNN message passing" | falsify C5 (the regularizer doesn't exist in code) |
| "do not yet reach OT parity" | "**~1.7–2.5× worse than PASTE2** on held-out donors" | framing asymmetry |
| "degrades systematically" / "monotonic" | "in a **single-seed** evaluation" / "four training regimes" (no trend claim) | stats FAIL (single seed) |
| novelty: "first to combine …" | dropped; reframed as **benchmark + proof-of-concept**, benchmark vs STaCker/INST-Align | surveil (crowded field; INST-Align Apr 2026) |
| "exact ground-truth correspondence" | "**approximate** array-position GT (~300 µm / ~8 px)" | methods reviewer + dataset check |
| title: "graph cross-attention **alternative**" | "supervised graph cross-attention **proof-of-concept**" | overclaiming reviewer |

## Survived every lane (keep, load-bearing)
- **OT/diffeomorphic tearing-failure characterisation** — survives argmax, α=0.5, and a 0 px self-control.
- **The negative generalisation result** — survived all 3 falsification skeptics *unanimously* (attacked as a
  training bug; held under direct re-experiment). This is the paper's most robust finding.

## Open caveat to disclose (do not hide)
The tear arm carries a *larger total displacement* than the smooth arm (the tear adds a rigid block offset on top
of the smooth field), so magnitude is not perfectly matched between regimes; the argmax, α=0.5, and self-control
controls are what implicate the *discontinuity* specifically rather than mere magnitude. A magnitude-matched tear
sweep and a multi-seed/multi-fold run are the next required experiments.
