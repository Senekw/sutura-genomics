# Sutura Genomics — Competitive Benchmark (head-to-head on the tear benchmark)
**2026-06-24 · Sutura project only · no GL/GI-brain-2 contact**

The ask was to run Sutura "against" STaCker and INST-Align. Two of the three named competitors are **not
runnable on this benchmark** (documented below — no fabricated numbers). The third relevant incumbent,
**STalign**, IS runnable, is the method the brief names as the diffeomorphic competitor, and its result directly
tests the core thesis — so it was run on the *exact same* tear benchmark, scored identically.

---

## 1. What could and could not be run

| Method | Class | Runnable here? | Why |
|---|---|---|---|
| **PASTE2** | OT (partial FGW) | ✅ done | coordinate+expression; already the baseline |
| **STalign** | diffeomorphic (LDDMM) | ✅ **done (new)** | public code (JEFworks-Lab/STalign); rasterizes point density |
| **STaCker** | CNN/U-Net image reg. | ❌ blocked | **requires H&E histology images** (overlays expression contours on the tissue image); our benchmark warps spot *coordinates* with no warped image, and **no public code repo** is available (Sci Rep 2025 code-availability section has no GitHub/Zenodo link) |
| **INST-Align** | implicit-neural deformation | ❌ blocked | arXiv 2604.12084 (Apr 2026): *"code will be released after the review phase"* — **no code exists publicly yet** |

For STaCker/INST-Align, the honest reference is their **published** DLPFC numbers (different splits/metrics, not
directly comparable). I did not invent head-to-head numbers for methods I could not execute.

## 2. STalign run — method & fairness

- Code: `JEFworks-Lab/STalign` (installed from source; PyPI build was broken by an ancient `pims==0.3.0` pin —
  installed `--no-deps` + real runtime deps). Script: `validation/run_stalign.py`.
- Procedure (identical benchmark): source = warped-151508, target = 151507. STalign rasterizes each slice's spot
  **density** (dx = pitch/2 ≈ 68 px), runs **LDDMM** (affine + diffeomorphism, niter = 2000, CPU, float64),
  then `transform_points_source_to_target` maps the warped-B spots into A's frame. Scored with the **same**
  `registration_error_stats` vs the **same** array-bridge ground truth used for PASTE2 and Sutura.
- Fairness notes: STalign aligns by spatial density (its design; it does not use gene expression), is fully
  **unsupervised** (like PASTE2), and was given 2000 iterations (its sev0 result is excellent, confirming it
  converged and was not hobbled).

## 3. Head-to-head — registration error (median px), tear regime, seed 0, scored identically

| Severity | **Sutura** (in-sample, *supervised*) | **PASTE2** OT (unsup.) bary / argmax | **STalign** LDDMM (unsup.) |
|---|---|---|---|
| 0 | 99 | 659 / 729 | **79** |
| 4 | 103 | 729 / 768 | 463 |
| 8 | 118 | 838 / 863 | **866** |
| Δ (sev0→8) | +19 (+19%) | +180 (+27%) | **+787 (+11×)** |

(STalign mean/p90 at sev8: 1965 / 4267 px — the torn chunk dominates the tail. Source:
`results/stalign_tear.csv`, `results/sutura_multiseed_tear.csv`, `results/sweep_deformation_ms_tear_seed0.csv`.)

## 4. What this shows

1. **Both unsupervised incumbents fail at tears — by different mechanisms.** OT (PASTE2) degrades by diffuse-plan
   smearing (659→838); the diffeomorphism (STalign) degrades by smooth-overshoot (79→866). At a severe tear they
   **converge to ~850 px** — neither can represent the discontinuity. This is the strongest direct evidence yet
   for the thesis, and it now rests on **two** runnable methods, not one.
2. **STalign is excellent on small deformation (79 px at sev0 — better than OT's 659)** because it does true
   spatial registration without OT smearing. So the failure is specifically the *tear*, not registration in
   general — exactly the "diffeomorphism cannot change topology" prediction (steepest degradation, +11×).
3. **Sutura's low in-sample curve (99→118) is real but supervised and same-donor.** It beats both incumbents
   *only* in-sample; on held-out donors it is 1041–1432 px — **worse than both** PASTE2 (407–838) and STalign
   (which, at sev0, can hit ~80 px on a fresh pair it was never trained on, since it is unsupervised).

## 5. Honest bottom line for positioning
- Sutura can now cite a **real two-method incumbent comparison** (OT *and* diffeomorphic) that both break under
  tearing — a clean, defensible "white space."
- But the same table shows Sutura's advantage is **supervised + in-sample**; the unsupervised incumbents need no
  training and STalign is near-perfect at low severity. Against an *unsupervised, zero-shot* bar, Sutura does not
  yet win out-of-sample.
- STaCker and INST-Align remain **un-benchmarked here** (image-only / no code). They are the closest learned-
  deformation competitors and should be run once code/images are available — until then, do not claim superiority
  over them.
