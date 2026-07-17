# Hybrid torn-tissue alignment - does combining cheap levers beat PASTE2?

_Generated 2026-07-17T09:23:11Z on branch `hybrid-combined`._

**Question.** Combine, in one toggleable pipeline, an OT correspondence prior (PASTE2-style, no training), tear-detection + piecewise classical alignment, a learned residual trained only on SYNTHETIC tears, and per-dataset self-supervised adaptation. Does the combination beat PASTE2 on held-out / torn tissue - and which components drive any gain? No large proprietary dataset is used anywhere.


**Benchmark.** 3-donor DLPFC leave-one-donor-out (Br5292/Br5595/Br8100), tear benchmark, median registration error in spot-pitches, eval severities 0,1,2,3,4,6,8 (tear=True, eval-seed 0) - identical to generalization_max.py so numbers overlay prior work. Two tracks: a FAST track (training-free/cheap levers on an expression-OT surrogate, no PASTE2) and a REAL-PASTE2-BASE track (the same refinements layered on actual PASTE2 output, so `paste2_*` vs `paste2` is apples-to-apples on identical torn slices; PASTE2 severities 0,2,4,6,8). PASTE2 held-out reference (full-res FGW): Br5292 5.28, Br5595 4.35, Br8100 3.46 (mean 4.36); shared-basis plateau 9.6.


## Headline

On the real-PASTE2-base track, PASTE2 alone is **4.39** (LODO-mean; reproduces the 4.36 reference). Always-on tear-detect + piecewise correction is 5.09 - it does NOT beat PASTE2 in aggregate (the gain is real but concentrated at LOW tear severity; it hurts at high severity - see the per-severity table). The deployable fit-residual-**gated** piecewise is **3.73**, which **beats** PASTE2 (-0.66); the oracle (perfect-gate) ceiling is 3.67. On the off-distribution breast pair, a residual self-trained on the pair's OWN synthetic tears (no external data) is 1.199 vs PASTE2 3.652 - a large win, but this is per-pair specialization, not cross-donor generalization.

## Ranked breakdown - what worked, what didn't

**Worked (beats PASTE2):**
1. **Fit-residual-gated piecewise on PASTE2** - 3.73 vs 4.39 LODO-mean, wins on ALL 3 folds, ~15% error cut, near the 3.67 oracle ceiling. Training-free, deployable, no ground truth. THE result.
2. **Self-supervised per-pair residual (off-distribution breast)** - 1.199 vs PASTE2 3.652. Trained only on the input pair's own synthetic tears; no external data. Per-pair specialization.

**Didn't (does not beat PASTE2):**
- **Always-on piecewise** (5.09) - net worse than PASTE2; wins at low tear severity but hurts at high. Needs the gate.
- **Cross-donor synthetic-trained residual** (fast 13.96, on PASTE2 13.58) - does NOT transfer across donors; hurts on the PASTE2 base. The central negative.
- **Agentic advisor fusion** (`paste2_hybrid` 10.21) - the miscalibrated always-on blend is dragged down by the residual; the gate is the advisor idea done right.
- **Expression-OT surrogate + all cheap levers** (fast track, ~9-14) - the warp-invariant surrogate base is the ceiling; far from PASTE2.

## Real-PASTE2-base track (refinements layered on PASTE2's own output)

| config | LODO-mean | vs PASTE2 | Br5292 | Br5595 | Br8100 |
|---|---|---|---|---|---|
| `paste2_gated` | 3.73 | -0.66 | 4.743 | 3.497 | 2.946 |
| `paste2` | 4.39 | +0.00 | 5.407 | 4.338 | 3.417 |
| `paste2_piecewise` | 5.09 | +0.71 | 5.213 | 4.753 | 5.313 |
| `paste2_hybrid` | 10.21 | +5.82 | 8.383 | 8.594 | 13.641 |
| `paste2_residual` | 13.58 | +9.19 | 12.699 | 11.281 | 16.757 |
| _oracle (min per severity)_ | 3.67 | -0.72 | - | - | - |

### Per-severity crossover (why always-on piecewise is a wash but the gate wins)

Mean-over-folds median error (pitch) at each severity:

| severity | 0 | 2 | 4 | 6 | 8 |
|---|---|---|---|---|---|
| `paste2` | 3.91 | 3.99 | 4.32 | 4.64 | 5.07 |
| `paste2_piecewise` | 1.51 | 2.83 | 5.21 | 7.18 | 8.72 |
| `paste2_gated` | 2.14 | 2.95 | 3.95 | 4.56 | 5.04 |

Piecewise beats PASTE2 sharply at low severity (small, rigid tears) and loses at high severity (strong non-rigid warp the per-piece rigid model cannot represent). The gate reads each piece's own rigid-fit residual and applies the correction only where the tissue is rigid enough (logistic at 4.5 pitch), recovering the low-severity wins without the high-severity harm - no ground truth needed.

## Fast surrogate-OT track (each cheap lever alone, no PASTE2)

| config | LODO-mean | vs PASTE2 | Br5292 | Br5595 | Br8100 |
|---|---|---|---|---|---|
| `shared_basis` | 9.05 | +4.69 | 10.328 | 8.941 | 7.895 |
| `hybrid_full` | 10.77 | +6.41 | 12.383 | 11.293 | 8.639 |
| `residual_ssa` | 10.91 | +6.55 | 12.592 | 11.45 | 8.691 |
| `ot_only` | 11.24 | +6.88 | 12.631 | 11.543 | 9.561 |
| `piecewise_only` | 11.81 | +7.45 | 13.269 | 12.632 | 9.538 |
| `hybrid_no_ssa` | 12.94 | +8.57 | 11.429 | 11.598 | 15.78 |
| `residual` | 13.96 | +9.60 | 12.292 | 12.458 | 17.142 |

The expression-OT surrogate is warp-invariant (ignores the moving geometry), so it and its refinements sit far above PASTE2 - the surrogate base, not the refinements, is the ceiling here. This is why the load-bearing experiment layers the refinements on REAL PASTE2 (above).

## Synthetic-data transfer (the key negative)

A residual trained purely on the TRAINING donors' synthetic tears and evaluated on the real HELD-OUT donor moves surrogate-track error 11.24 -> 13.96 pitch: it **does NOT transfer across donors**. Layered on the real PASTE2 base it is 13.58 (vs PASTE2 4.39) - it actively hurts, because it was trained against the surrogate coarse and PASTE2 is far too slow (~5 min/pair) to train a residual against directly. BUT the SAME architecture trained self-supervised on a single pair's OWN synthetic tears reaches 1.199 on breast - so the learned residual is a per-pair specializer, not a cross-donor generalizer. The cross-donor gap is an aligner-generalization problem synthetic volume alone does not close.

## Breast (off-distribution) pair

No held-out donor exists, so the learned residual is self-supervised on the pair's OWN synthetic tears (array-bridge correspondence, no external data); `paste2_real` is the true FGW baseline on the same warped slices.

| config | error (pitch) |
|---|---|
| `hybrid_no_ssa` | 1.163 |
| `residual` | 1.199 |
| `paste2_real` | 3.652 |
| `piecewise_only` | 17.258 |
| `ot_only` | 17.769 |

## On the requested internet-scouring agent

The brief asked for AI agents that scour the internet, learn how to fix data when PASTE2's output is wrong, and feed corrections to the aligner. That online loop is **not** run here, for three honest reasons: (1) this is an offline, detached, reproducible benchmark with no live web access in the run environment; (2) there is no validated public corpus of 'PASTE2 was wrong here, fix it thus' to scrape - the correction signal that actually exists is the residual between a method's output and ground-truth, which we already have from synthetic tears; and (3) an unsupervised web agent editing alignment data would be a fabrication risk with no way to verify its 'fixes' don't corrupt results. What we DID build is the grounded, testable core of that idea - one method learning to correct another: (a) the **agentic error advisor** learns from the training donors' synthetic tears where the OT+residual output is worse than the piecewise estimate and blends accordingly (it helps vs pure residual - `paste2_hybrid` 10.21 < `paste2_residual` 13.58 - but neither approaches PASTE2); and (b) the **fit-residual gate**, which is the version that actually works: it reads PASTE2's own per-piece rigid-fit quality and decides, per piece, whether the structural correction is trustworthy - and that is what beats PASTE2 (3.73 vs 4.39). The lesson: the useful 'agent that fixes another method's output' is a VERIFIED gate on an observable signal, not an unverified web scrape. A genuinely online version would still need a curated, citable corpus of registration failure/fix cases and a verification harness (score every proposed fix against held-out GT before trusting it); without that, scouring the web adds risk, not accuracy.
