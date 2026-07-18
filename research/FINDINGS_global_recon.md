# Global multi-section reconstruction vs. pairwise chaining — findings

**Branch:** `global-recon` · **Date:** 2026-07-18 · autonomous overnight run
**Code:** `research/src/global_recon.py` (solver + experiments), `research/src/global_recon_plot.py`
**Data:** `research/results/global_recon.csv` · **Plots:** `research/results/global_recon_drift.png`, `research/results/global_recon_panels.png`

## TL;DR verdict

**Global solving is worth it — but not for the reason you'd guess, and not always.**
The improvement does **not** come from "solving simultaneously." A global solve fed only
adjacent edges is *bit-for-bit identical* to the pairwise chain (confirmed: `global_adj` ==
`pairwise_chain` at every chain length). The entire win comes from **adding redundant
non-adjacent constraints** (loop closures) that the chain never uses. Given those, the global
solve cuts terminal drift on a 12-section chain by **~75%** (278 px → 65 px) and, crucially,
**stops error from accumulating with chain length at all** (it stays flat at ~60 px while the
chain grows without bound).

The catch is cost: those extra constraints require running extra pairwise **alignments**
(O(N²) for the full graph vs. N−1 for the chain). The *solve itself* is free (0.15 s for 32
sections); the price is entirely in the alignments you must run to feed it.

**Recommendation:** adopt a **banded global solve (band-3) with the fit-residual gate + IRLS**.
It captures most of the drift reduction for ~3N alignments (not N²), and the gate/IRLS make it
robust to the real-world failure modes where the current pairwise chain is catastrophic
(missing sections, one bad alignment). For short chains (≤4 sections) it doesn't matter — keep
the cheap chain.

---

## 1. The drift problem is real and grows with chain length

Measured against **exactly-known ground truth**: real DLPFC section geometry (layer centroids
of section 151507 as landmarks) placed into the stack by known random similarity transforms,
then re-estimated from noisy landmark correspondences. Error = RMS displacement of a section's
spots vs. their true placement, in pixels. 5 seeds × 3 severities (noise = 1/3/5 % of tissue
radius).

**Terminal-section error** (the worst-drifted section), mean over seeds & severities:

| chain length | pairwise chain | global adj-only | global band-3 | global full |
|---|---|---|---|---|
| 2  | 100.0 | 100.0 | 100.0 | 100.0 |
| 4  | 118.1 | 118.1 | 66.2  | 66.2  |
| 8  | 216.8 | 216.8 | 98.7  | 58.9  |
| 12 | 277.9 | 277.9 | 136.2 | **64.8** |

Two honest facts jump out:

1. **`global adj-only` = `pairwise_chain` exactly.** Simultaneity alone buys nothing. This is
   the finding that keeps us honest — a "global solver" that only sees the same adjacent edges
   is just the chain rewritten.
2. **Pairwise error grows ~linearly with chain length (random walk of composed errors); the
   full global solve is flat.** At 2 sections they're identical (one edge, nothing to average).
   By 12 sections the full solve is 4.3× better.

By severity (12-section terminal error): the gap widens as alignment gets noisier —
pairwise {sev1: 83, sev3: 235, sev5: 516} vs. global-full {sev1: 34, sev3: 70, sev5: 91}.
The worse your per-pair alignment, the more drift the chain accumulates and the more a global
solve helps.

See `global_recon_drift.png`.

## 2. Real DLPFC chains (no synthetic ground truth)

On the actual 12 sections, two GT-free metrics. **All-edge constraint residual** (how
self-consistent the recovered poses are against every measured pairwise transform; lower =
better):

| chain | pairwise | global |
|---|---|---|
| donor Br5292 (4) | 140.1 | 105.8 |
| donor Br5595 (4) | 257.2 | 167.2 |
| donor Br8100 (4) | 200.2 | 142.3 |
| full 12 | 994.9 | **718.3** |

Global poses are consistently more self-consistent (28–35% lower residual).

**Label-consistency** (do a spot's nearest neighbours in the adjacent section share its
cortical layer?) is essentially **tied** within a donor (~0.81 both) and slightly *favours
pairwise* on the full-12 (0.77 vs 0.73). **This is honest and expected:** (a) real Visium serial
sections here already share the array coordinate frame, so within a 4-section donor there is
little frame drift for a global solve to fix; (b) the full-12 "chain" concatenates three
different donors — layers do not correspond across donors, so that metric is not meaningful
there and neither method should "win" it. The drift problem bites when sections arrive in
**arbitrary frames** (H&E/multi-batch/cross-platform, or any pipeline that doesn't inherit a
shared array grid) — which is exactly the controlled experiment in §1.

## 3. Robustness — where the pairwise chain actually breaks

12-section controlled chains, moderate severity. Mean pose error (px, lower better):

| scenario | pairwise chain | global (best) |
|---|---|---|
| **Missing section** (section 6 dropped) | **4218.9** | 79.9 (`global_band`) |
| **One corrupted edge** (bogus (5,6)) | naive 3068.3 | **74.5** (`global_gated`) |
| **Inconsistent estimates** (high noise) | 564.8 | 296.6 (`global_band` + IRLS) |

- **Missing section is catastrophic for the chain**: it breaks at the gap and every downstream
  section inherits a stale pose (4219 px). The global solve routes around the gap through
  non-adjacent band edges and barely notices (80 px). This alone is a strong practical argument.
- **A single bad alignment** poisons the whole naive global solve (3068 px) just as it would
  corrupt the chain. The **gate** (drop edges whose landmark-fit residual exceeds a robust
  median+3·MAD fence) fixes it (74 px); **IRLS** (Huber re-weighting) helps but less on a gross
  outlier (283 px). Gate > IRLS for gross outliers; combine them.

See `global_recon_panels.png` (centre).

## 4. Gate inside the global solve

We injected 0/10/20 % corrupted edges and compared no-gate vs. gate vs. gate+IRLS:

| frac bad edges | no gate | gated | gated + IRLS |
|---|---|---|---|
| 0.0 | 100.1 | 100.1 | 97.6 |
| 0.1 | 5706.0 | **103.2** | 99.6 |
| 0.2 | 6570.0 | **113.0** | 110.6 |

The gate is **harmless when there's nothing to gate** (identical at 0 % bad) and **essential
when there is** (50–60× error reduction at 10–20 % bad). This is the same fit-residual-gating
idea that beat PASTE2 in the hybrid work, applied at the edge level: trust an edge only if its
alignment fit is clean. **Ship the gate on by default.**

## 5. Runtime / cost — is it practical?

The solve is a two-step complex linear least squares (rotation+scale averaging, then translation
averaging). It is **negligible**:

| sections | pairwise solve | global band-3 | global full | full edges |
|---|---|---|---|---|
| 12 | 0.001 s | 0.011 s | 0.016 s | 66 |
| 24 | 0.002 s | 0.017 s | 0.065 s | 276 |
| 32 | 0.003 s | 0.022 s | 0.154 s | 496 |

**The solver is not the cost.** The cost is the number of **pairwise alignments** you must run to
produce the edges — each edge is one real Sutura/PASTE2 alignment (seconds to minutes), not a
0.1 ms landmark fit:

- pairwise chain: **N−1** alignments
- global band-k: **~kN** alignments (band-3 on 12 sections = 30 vs 11 — ~2.7× more)
- global full: **N(N−1)/2** alignments (12 sections = 66 vs 11 — 6× more; 32 sections = 496 vs
  31 — 16× more)

So "full" is quadratic in alignments and impractical past ~15–20 sections. **Band-3 is the
practical sweet spot**: linear in alignments (~3×), captures most of the drift reduction
(136 px vs full's 65 px at 12 sections — still 2× better than the 278 px chain), and gives the
non-adjacent edges the gate/IRLS need to survive missing/bad sections.

## Bottom line

| question | answer |
|---|---|
| Is drift real? | **Yes** — grows ~linearly with chain length, worse at higher alignment noise. |
| Does "solving globally" fix it? | **Only via non-adjacent constraints.** Adjacent-only global == the chain. |
| How much better? | Full solve: ~75% less terminal drift at 12 sections, and **flat** vs. chain length. Band-3: ~50% less. |
| On real DLPFC? | More self-consistent poses (28–35% lower residual); label-consistency tied within-donor (sections already share the array frame — drift shows up in arbitrary-frame regimes). |
| Robust to real-world mess? | **This is the biggest win.** Chain is catastrophic on a missing section (4219 px) or a bad edge (3068 px); gated global stays ~80 px. |
| Practical? | Solve is free. **Cost = number of alignments.** Band-3 (~3N) is practical and near-full quality; full (N²) isn't past ~20 sections. |
| Recommendation | **Banded (band-3) global solve + fit-residual gate + IRLS**, on by default for chains ≥ ~6 sections or any pipeline with arbitrary section frames / risk of dropped or low-quality sections. Keep the cheap chain for short, clean, array-registered stacks. |

### Honesty notes / limitations
- The controlled drift numbers use a **similarity** (rotation+scale+translation) transform
  model and **layer-centroid landmarks** as the correspondence proxy — the same family the
  current reconstructor fits. Non-rigid within-section warp is not modelled by either method
  here; this study is about the *frame composition*, which is where drift lives.
- Ground truth is synthetic (known random placements applied to real geometry). That is the
  honest way to measure drift — there is no per-spot cross-section correspondence in real serial
  sections to score against. The real-data section (§2) is reported separately and not dressed
  up as ground truth.
- Label-consistency on the concatenated 12 spans donors and is not a meaningful alignment metric
  there; reported for completeness, not as a global-vs-pairwise verdict.
