# Sutura Genomics — Finished Abstract (validated; every number reproduced on this machine)

**Status:** This is the honest, submission-ready abstract. It contains **no claim that fails validation** and
**no number I did not re-derive** from the code/data (see [`VALIDATION_REPORT.md`](VALIDATION_REPORT.md)). It
is built on what is true: the OT tearing-failure characterization is solid and novel; Sutura is an honest
proof-of-concept with a clearly bounded, improving generalization gap. This framing survives review by the
exact PIs you want to email (Raphael/PASTE2, Fan/STalign).

---

## Title

**Tissue tearing breaks optimal-transport registration of spatial transcriptomics: a controlled deformation
benchmark and a graph cross-attention alternative**

*(Alt., method-forward: "Sutura: graph cross-attention with a local-smoothness displacement field for
discontinuity-tolerant spatial-transcriptomics registration.")*

---

## Abstract (≈270 words)

**Background.** Three-dimensional reconstruction of tissue from serial spatial-transcriptomics (ST) sections
requires registering adjacent slices, but physical sectioning routinely introduces *tears* — discontinuous,
non-isometric deformations. Leading registration methods rely on priors that tears violate: PASTE/PASTE2 use
Fused Gromov-Wasserstein optimal transport (OT), which assumes near-isometric preservation of within-slice
distances, and STalign uses diffeomorphic (LDDMM) mapping, which by construction cannot change tissue topology.
How these methods behave under tearing has not been systematically characterized.

**Methods.** Using the spatialLIBD human DLPFC Visium dataset (Maynard et al., 2021), we built a controlled
deformation benchmark: known smooth (near-isometric) warps, tears, and an identity self-control are applied to
a real slice with exact ground-truth correspondence, across severities of 0–8 spot pitches. We evaluate PASTE2
and introduce Sutura, a graph model that encodes each slice as a spot graph, establishes correspondence by
cross-attention between the two graphs, and predicts a per-spot displacement field regularized only locally so
that correspondences across a tear are not forced to agree.

**Results.** OT registration is robust to smooth warps (median error flat at ~647 px ≈ 4.7 pitches) but degrades
systematically under tearing (658→838 px; label accuracy 64.4%→57.5%); the effect survives hard argmax
assignment and strengthens with geometric weight, and a self-control confirms exact scoring (0 px). Trained and
evaluated on the same donor, Sutura recovers torn-tissue correspondence to sub-pitch accuracy (median 99→118 px,
<1 pitch at every severity; ~7× lower than OT), far better than a naïve expression-nearest-neighbour baseline
(2532 px), confirming a genuine learned correspondence. However, this advantage is **donor-specific**: on a
held-out donor, error rises to 1029–1593 px across four training regimes; multi-donor training and
embedding-space batch correction reduce the gap monotonically but do not yet reach OT parity.

**Conclusion.** Tearing is a real, characterizable failure mode of OT/diffeomorphic ST registration. Learned
local-correspondence models can close the in-sample gap, but donor-invariant generalization is the open problem;
we define it quantitatively and chart the path (batch-invariant features, multi-donor training, contrastive
correspondence).

---

## Honesty ledger for the abstract (every figure traced)

| Statement in abstract | Source / reproduction |
|---|---|
| OT smooth flat ~647 px | `sweep_deformation_cross.csv` (median 639–658) |
| OT tear 658→838 px; acc 64.4%→57.5% | `sweep_deformation_cross_tear.csv` |
| survives argmax / strengthens with α / self-control 0 px | `sweep_deformation_argmax_tear.csv`, `_tear_a0p5.csv`, `_self.csv`; re-run confirms |
| Sutura 99→118 px, <1 pitch | `arca_cross_curve.csv`; **re-run 99.1→118.0** |
| expression-NN baseline 2532 px | my ablation (`validation/ablations.py`) |
| held-out 1029–1593 px across 4 regimes; monotonic improvement | `arca_loo_*`, `arca_loo3_*` + my perslice runs |
| pitch ≈ 100 µm / 137 px; Maynard 2021 DOI 10.1038/s41593-020-00787-0 | verified |
| PASTE/PASTE2 = FGW-OT; STalign = LDDMM | verified DOIs (see report §2) |

---

## What I deliberately did NOT write (and why)

- ❌ "Sutura is ~7× lower error / the alignment layer / solves where every method structurally fails." — true only
  *in-sample*; the completed generalization tests contradict it.
- ❌ "Structurally distinct from every existing method." — graph DL for ST alignment already exists; STaCker
  already does learned per-spot deformation and recovers torn tissue.
- ❌ "OT cannot represent a tear." — imprecise; the correct statement is the near-isometry-prior violation.

If you want, I can also produce: (a) a method-forward variant that leads with Sutura (still honest), or
(b) a "hold-until-generalization-solved" plan that does the donor-invariance work first and earns the stronger
claim. See the decision in the chat summary.
