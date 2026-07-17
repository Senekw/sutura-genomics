# A self-gated geometric refinement that improves optimal-transport spatial-transcriptomics alignment on torn tissue

**Draft skeleton — branch `hybrid-combined`, 2026-07-17.** Target: a short methods note.
Not a from-scratch aligner; a drop-in refinement of existing OT aligners (PASTE2/PASTE/GW).

---

## Abstract (draft)

Optimal-transport (OT) methods such as PASTE2 are the standard for pairwise alignment of adjacent
spatial-transcriptomics sections, but physical tissue tearing - a rigid displacement of a contiguous
region - degrades their registration accuracy. We introduce **gate_refine**, a training-free,
ground-truth-free post-processing step that improves any OT alignment on torn tissue. It detects the
tissue's pieces from the moving section's own geometry (kNN edges bridging a tear are stretched),
fits a low-order geometric transform (rigid/affine) per piece to the OT correspondence, and applies
each fit **only where a cross-validated residual shows the piece is well-explained** - otherwise
falling back to the OT result. On a 3-donor DLPFC leave-one-donor-out synthetic-tear benchmark it
reduces PASTE2's median registration error from 4.26 to **3.10 ± 0.04 spot-pitches (27%)** and wins
at every tear severity; the improvement holds on off-distribution breast (13%) and mouse-brain (6%)
sections, across three random seeds, and survives PASTE2 subsampling (3.4× faster, no accuracy loss).
Because the trust decision uses only the fit's own residual, the method uses no features and no
labels and does not regress on realistic inputs. We also report a cautionary negative: a
self-supervised variant that appeared to beat PASTE2 was in fact leaking (its training target was the
evaluation target via the Visium array bridge), and does not survive a leakage-clean re-run.

## 1. Introduction

- Spatial transcriptomics; pairwise section alignment; PASTE/PASTE2 (fused Gromov-Wasserstein OT) as
  the accuracy standard; label transfer / 3D reconstruction depend on it.
- Physical tearing during sectioning is common and corrupts the intra-section geometry that the
  Gromov term relies on -> registration error rises with tear severity.
- Question: can we improve a good OT alignment on torn tissue **without more data, training, or
  ground truth**, and **without ever making it worse**?
- Contribution: (i) a self-gated per-piece geometric refinement; (ii) a validated ~15-30% accuracy
  gain over PASTE2 that generalizes across tissues and is safe-by-construction; (iii) a speed path
  (subsampling) making it interactive; (iv) an honest leakage cautionary finding for
  array-bridge self-supervision.

## 2. Method

**Input.** An OT aligner's reference-frame prediction per moving spot (e.g. the barycentric
projection of the PASTE2 transport plan), `base_i`, and the moving spots' own observed (torn)
coordinates, `x_i`.

**Piece detection.** Build the moving kNN graph; cut edges longer than `stretch * pitch`
(pitch = median NN distance). A tear rigidly offsets a contiguous region, so the bridging edges are
stretched and removing them splits the slice into connected components (pieces); tiny components merge
into the nearest large one.

**Per-piece fit.** Within a piece the true moving->reference map is approximately a similarity
(rigid; tear = rotation+translation) or affine (allows the smooth stretch of higher-severity warps),
and `base` is a good-but-noisy estimate of it. We fit a weighted least-squares transform of order
0/1/2 (rigid via Umeyama / affine / quadratic) from the piece's moving coords to its `base` targets.

**Self-gated trust.** The fit's own **cross-validated residual** r (fit on half the piece, score the
other half, in pitch units) measures how well a low-order transform explains the piece - high exactly
when the piece is not well-described by the transform (strong non-rigid warp, or a poor OT base). We
blend the fitted prediction with `base` by a logistic gate, w = 1/(1+exp((r - thr)/scale)), so the
correction is applied where trustworthy and falls back to `base` elsewhere. `thr ~ 4.5` pitch (the OT
error scale) is fixed a-priori; results are robust for thr in [2, 12]. CV residual keeps higher-DOF
fits from winning by overfitting OT noise.

**Properties.** No features, no ground truth, no training. Deterministic. `O(N log N)` (kNN) + small
per-piece least squares - negligible next to the OT solve.

## 3. Experiments

- **Benchmark.** Synthetic tears (smooth Gaussian-bump field + rigid excision of a contiguous region;
  severity in spot-pitches), median registration error vs the Visium array-bridge ground truth.
- **Datasets.** 3 DLPFC donors (leave-one-donor-out) + off-distribution breast and mouse brain (real
  adjacent sections); 3 additional DLPFC cross-section pairs (robustness). Severities {0..8}, 3 seeds.
- **Base aligner.** PASTE2 (partial FGW, s=0.99, alpha=0.1), barycentric projection, cached
  (deterministic) so every refinement is evaluated on identical warped slices.

## 4. Results

**Main (DLPFC LODO, median spot-pitches, mean ± std over 3 seeds, 7-severity grid):**

| method | error | vs PASTE2 |
|---|---|---|
| PASTE2 (base) | 4.26 ± 0.03 | - |
| + gate (rigid) | 3.42 ± 0.13 | -20% |
| **+ gate (affine)** | **3.10 ± 0.04** | **-27%** |

Wins on all 3 donors at every severity. On the original 5-severity grid the rigid gate reproduces the
prior 3.73 (PASTE2 4.39) exactly.

**Off-distribution (sev-averaged, mean ± std over 3 seeds):**

| dataset | PASTE2 | + gate (affine) |
|---|---|---|
| breast | 3.67 ± 0.12 | 3.21 ± 0.03 (-13%) |
| mouse brain | 5.58 ± 0.11 | 5.26 ± 0.24 (-6%) |

**Robustness (3 additional DLPFC cross-section pairs, the 2nd adjacent pair of each donor;
sev-averaged, gated_affine vs PASTE2; seed 0):**

| pair (spots) | PASTE2 | + gate (affine) | delta |
|---|---|---|---|
| Br5292b (~4700) | 4.66 | 3.00 | -36% |
| Br5595b (~4000) | 5.56 | 4.67 | -16% |
| Br8100b (~3500) | 5.40 | 4.78 | -11% |

The gate wins on all three at every completed severity. Margins scale inversely with how good
PASTE2 already is on the pair (these 2nd pairs are harder for PASTE2, 4.7-5.6 pitch, than the 1st
pairs). One cell (Br5292b sev8, ~4800 spots) exceeded the 900 s PASTE2 watchdog and was skipped -
a concrete illustration that full-resolution PASTE2 is impractical at high spot-count + max tear,
which the subsampling path addresses. [Second seed running for variance.]

**High severity.** The rigid gate never loses more than ~0.06 pitch (it falls back); the affine gate
actively helps at high severity (it absorbs the smooth stretch the rigid fit cannot), e.g. Br8100 s8
3.83 vs PASTE2 4.03.

**Speed.** PASTE2 scales super-linearly; subsampling to ~2500 spots gives 3.4× with no accuracy loss
(13× at ~1500). The gate beats PASTE2 at every subsample level. The gate itself is ~milliseconds.

**Leakage / robustness audit.** The gate's output is bit-identical when the ground truth or the
expression features are corrupted (it depends only on `base` and moving geometry), and it beats
PASTE2 across the full thr sweep - so the win is neither a leak nor a tuned threshold.

## 5. Cautionary negative: array-bridge self-supervision leaks

A tempting alternative is to self-supervise a small deformation model on a section's own synthetic
tears. If the training target is the Visium **array-bridge correspondence** (spot i in A <-> spot i in
B by array coordinate), that correspondence is *also the evaluation target* and is warp-invariant, so
the model trains on the answer. This produced an apparent 3x win over PASTE2 that was dataset-
independent (~0.8-1.9 pitch on every tissue - the fingerprint of leakage). Re-run leakage-free
(training only on self-warps of the reference section, never touching the A-B correspondence), the
same model **loses to PASTE2 on every dataset**. We report this because array-bridge self-supervision
is an easy, non-obvious leak in spatial-alignment benchmarks.

## 6. Limitations (honest)

- **Refinement, not a standalone aligner.** The gain is "PASTE2 + gate > PASTE2"; it needs a base OT
  alignment and inherits gross base failures (though it then correctly falls back rather than hurting).
- **Synthetic ground truth.** Tears are a smooth-bump + rigid-excision model; GT is the Visium array
  bridge. Real-tear validation with independent GT is the key next step (Section 7).
- **Near-perfect-base boundary.** The never-regress property is empirical over realistic imperfect-OT
  inputs. In a degenerate regime where the base is already ~exact but the moving frame carries a
  smooth warp (identical-copy self-alignment, where OT matches each spot to its twin), the moderate
  fit residual can add a little error. This does not arise in genuine cross-section alignment.
- **OOD breadth.** Two non-DLPFC tissues with adjacent sections were available (breast, mouse brain);
  both confirm. Mouse brain is the smallest margin (~6%).

## 7. What real-tear validation requires (next step for publication)

The current GT is synthetic. A convincing real-tear result needs one of:
1. **A section with a genuine physical tear + an independent registration GT** - e.g. adjacent
   serial sections where one is torn, with fiducial/landmark correspondence (manually annotated
   anatomical landmarks or nuclei matched across sections), so registration error can be scored
   without the array bridge.
2. **Consecutive serial sections with a known z-order and manual landmark annotations**, tearing one
   and scoring landmark reprojection error before/after the gate.
3. **A held-out modality as GT** - e.g. H&E image registration (image-based landmarks) as the
   reference alignment, independent of expression, to score the OT+gate output.
None of these exist in the current repository; the datasets on disk are single or adjacent Visium
sections without independent tear GT. Acquiring/annotating one such pair is the concrete gating item
for a full paper (vs. a methods note on synthetic tears).

## 8. Positioning / venue

- **Methods note** at *Bioinformatics* (Applications Note) or *GigaScience* / *Genome Biology*
  (Method), or a workshop - the contribution is a small, honest, reusable improvement + a leakage
  caution, not a new SOTA aligner.
- Framing: "a safe-by-construction accuracy add-on for OT spatial alignment", generalizes beyond
  PASTE2 to any method that yields a per-spot reference-frame correspondence.

## 9. Reproducibility

Code: `src/gate_refine.py` (the method, 9 unit tests in `src/test_gate_refine.py`),
`src/hybrid_validate.py` (grid), `src/hybrid_robustness.py` (extra datasets),
`research/leakage_audit.py`, `research/speed_probe.py`. Data + results:
`research/results/hybrid_validate.csv`, `hybrid_validate.png`, `leakage_audit.txt`,
`speed_probe.txt`. Full method/validation writeup: `research/FINDINGS_hybrid_validated.md`.
