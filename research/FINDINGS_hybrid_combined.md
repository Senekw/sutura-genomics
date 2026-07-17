# Hybrid torn-tissue alignment ? does combining cheap levers beat PASTE2?

_Generated 2026-07-17T08:17:46Z on branch `hybrid-combined`._

**Question.** Combine, in one toggleable pipeline, an OT correspondence prior (PASTE2-style, no training), tear-detection + piecewise classical alignment, a learned residual trained only on SYNTHETIC tears, and per-dataset self-supervised adaptation. Does the combination beat PASTE2 on held-out / torn DLPFC and on an off-distribution breast pair ? and which components drive any gain?


**Benchmark.** 3-donor DLPFC leave-one-donor-out (Br5292/Br5595/Br8100), tear benchmark, median registration error in spot-pitches, eval severities 0,1,2,3,4,6,8 (tear=True, eval-seed 0) ? identical to generalization_max.py so numbers overlay prior work. PASTE2 held-out reference (full-res FGW, prior sweep): Br5292 5.28, Br5595 4.35, Br8100 3.46 (mean 4.36); shared-basis plateau 9.6.


## Headline

Best configuration: **`shared_basis`** at **9.05** LODO-mean pitches, which does **not** beat PASTE2 (mean 4.36). Shared-basis baseline recomputed here for reference.


## LODO ranking (mean held-out error, lower=better)

| rank | config | LODO-mean | vs PASTE2 | Br5292 | Br5595 | Br8100 |
|---|---|---|---|---|---|---|
| 1 | `shared_basis` | 9.05 | +4.69 | 10.328 | 8.941 | 7.895 |
| 2 | `hybrid_full` | 10.77 | +6.41 | 12.383 | 11.293 | 8.639 |
| 3 | `residual_ssa` | 10.91 | +6.55 | 12.592 | 11.45 | 8.691 |
| 4 | `ot_only` | 11.24 | +6.88 | 12.631 | 11.543 | 9.561 |
| 5 | `piecewise_only` | 11.81 | +7.45 | 13.269 | 12.632 | 9.538 |
| 6 | `hybrid_no_ssa` | 12.94 | +8.57 | 11.429 | 11.598 | 15.78 |
| 7 | `residual` | 13.96 | +9.60 | 12.292 | 12.458 | 17.142 |

## What each component contributes

- **OT prior alone** (`ot_only`): 11.24 ? the training-free PASTE2-style correspondence surrogate (expression entropic-OT).
- **+ tear-detect/piecewise** (`piecewise_only`): 11.81 ? structural, training-free tear correction on top of OT.
- **+ learned residual, synthetic-trained** (`residual`): 13.96 ? the synthetic-tear-transfer test (trained on TRAIN donors' synthetic tears, evaluated on the real held-out donor).
- **+ self-supervised adaptation** (`residual_ssa`): 10.91.
- **full hybrid, no SSA** (`hybrid_no_ssa`): 12.94 ? OT+piecewise+residual fused by the agentic advisor gate.
- **full hybrid** (`hybrid_full`): 10.77.
- **shared-basis NN** (`shared_basis`): 9.05 (prior plateau reference 9.6).

## Synthetic-data transfer

Training the residual purely on synthetic tears of the training donors and evaluating on the real held-out donor moves error 11.24 -> 13.96 pitches. Synthetic training **does NOT transfer (no improvement over the OT base on held-out real tissue)**.

## On the requested internet-scouring agent

The brief asked for AI agents that scour the internet, learn how to fix data when PASTE2's output is wrong, and feed corrections to the aligner. That online loop is **not** run here, for three honest reasons: (1) this is an offline, detached, reproducible benchmark with no live web access in the run environment; (2) there is no validated public corpus of 'PASTE2 was wrong here, fix it thus' to scrape ? the correction signal that actually exists is the residual between a method's output and ground-truth, which we already have from synthetic tears; and (3) an unsupervised web agent editing alignment data would be a fabrication risk with no way to verify its 'fixes' don't corrupt results. What we DID build is the grounded, testable core of that idea: the **agentic error advisor** learns ? from the training donors' synthetic tears ? exactly where the OT+residual output is worse than the piecewise estimate, and feeds that judgment into the final blend (one model correcting another's errors). Its measured contribution is the `hybrid_*` vs `residual` delta above. A genuinely online version would need a curated, citable corpus of registration failure/fix cases and a verification harness (score every proposed fix against held-out GT before trusting it); without that, scouring the web adds risk, not accuracy.
