# Agentic alignment orchestrator — findings

**Branch:** `orchestrator` · **Date:** 2026-07-08 · Diagnostic; `main`, website, demo untouched.
Code: `src/orchestrator.py` (pipeline), `src/plot_orchestrator.py` (comparison).
Outputs: `results/orchestrator_eval.csv`, `results/orchestrator_compare.png`.

## TL;DR

The orchestrator routes every input to the method that actually wins on it, and the
combined system **beats both fixed strategies across the full dataset set**:

| Strategy | mean median error (pitch) | worst-case (pitch) |
|---|---:|---:|
| Sutura-always | 9.41 | 20.16 |
| PASTE2-always | 4.38 | 5.42 |
| **Orchestrator (routed)** | **3.00** | **5.42** |

On every one of the 5 datasets the orchestrator's error equals the better of the two
methods (`orchestrator ≤ min(Sutura, PASTE2)` holds on all 5). It never does worse
than either fixed strategy, and it is strictly better than each on the datasets where
that strategy fails. The routing signal — Mahalanobis distance through the frozen
shared basis — separates in- from off-distribution cleanly, including the hard case
(a new donor of the same tissue and gene panel).

## Pipeline (autonomous, per input pair)

1. **Load & QC** — read both sections; check spot counts, `obsm['spatial']`,
   `array_row/array_col`, non-empty genes. Stops with a reason if QC fails.
2. **Distribution check** — project both sections' expression through the FROZEN
   shared basis (`results/shared_basis.npz`), then compute (a) gene-vocabulary
   overlap with the basis and (b) Mahalanobis distance of the input's embedding mean
   to the training-donor (Br5292+Br5595) embedding distribution. Emits an
   in-distribution confidence.
3. **Method selection** — in-distribution (high confidence) → **Sutura**; off-
   distribution (low confidence) → **PASTE2**. Decision + rationale logged.
4. **Alignment** — run the selected method on the (tear-warped) pair.
5. **Post-alignment QC** — median error vs array-bridge GT when available; else the
   footprint-coverage proxy. If the result is bad, retry the alternate method and
   keep the better one.
6. **Report** — structured row + plain-English summary.

## Distribution check — the routing signal (calibrated)

Measured on our donors (frozen-basis embedding; training distribution = Br5292 +
Br5595, both sections):

| dataset | truth | gene overlap | Mahalanobis | confidence | routed to |
|---|---|---:|---:|---:|---|
| Br5292 | in-dist | 100% | 0.85 | 0.92 | Sutura |
| Br5595 | in-dist | 100% | 1.02 | 0.90 | Sutura |
| Br8100 | off-dist | 100% | 4.77 | 0.03 | PASTE2 |
| mouse | off-dist | 0% (gate) | — | 0.02 | PASTE2 |
| breast | off-dist | 95% | 20.40 | 0.00 | PASTE2 |

Mahalanobis distance is the discriminating signal: in-distribution donors sit at
~1.0, all off-distribution inputs at ≥4.5 — a wide margin around the configurable
threshold (default **2.5**). It correctly flags **Br8100**, the hard case (same
species, same tissue, identical 33,538-gene panel, only a different donor) where
gene-overlap and kNN-distance do **not** separate it (kNN median distance for Br8100
is 6.6, right between the two in-distribution donors at 6.3 and 7.2). A gene-overlap
gate (default 0.5) handles species mismatch (mouse, 0% overlap) up front. Both
thresholds are configurable in `OrchestratorConfig`.

## Routing validation (all 5 datasets)

Every dataset routed to the method that actually wins (tear severity 4, seed 0):

| dataset | chosen | orchestrator err | Sutura-always | PASTE2-always |
|---|---|---:|---:|---:|
| Br5292 (in) | sutura | **1.41** | 1.41 | 5.32 |
| Br5595 (in) | sutura | **1.19** | 1.19 | 4.17 |
| Br8100 (off) | paste2 | **3.39** | 9.45 | 3.39 |
| mouse (off) | paste2 | **5.42** | 14.87 * | 5.42 |
| breast (off) | paste2 | **3.61** | 20.16 * | 3.61 |

\* On non-DLPFC panels the current (shared-basis) Sutura **cannot even run** (gene
mismatch); the figure shown is the older per-SVD Sutura, which runs but collapses.
So "Sutura-always" is not merely inaccurate off-distribution — on foreign panels it
is inapplicable, which is itself a reason to route.

## Does the combined system beat both? (the key question)

**Yes, across the full set.** Per dataset the orchestrator matches the winner
(`≤ min(Sutura, PASTE2)` on all 5). Aggregated, it beats each fixed strategy because
each fixed strategy fails precisely where the other wins:

- vs **Sutura-always**: orchestrator wins big on all 3 off-distribution datasets
  (3.4/5.4/3.6 vs 9.4/14.9/20.2) and ties on the 2 in-distribution ones. Mean 3.00 vs
  9.41.
- vs **PASTE2-always**: orchestrator wins on both in-distribution datasets
  (1.4/1.2 vs 5.3/4.2) and ties on the 3 off-distribution ones. Mean 3.00 vs 4.38.

Honest nuance: on any *single* dataset the orchestrator equals whichever fixed
strategy chose correctly — it does not beat both *simultaneously on one dataset*
(that is impossible: the ceiling per input is the better of the two methods). Its
advantage is that it achieves that per-input ceiling on *every* input, which neither
fixed strategy does. Worst-case error drops from 20.16 (Sutura-always) / 5.42
(PASTE2-always) to 5.42 — i.e. it matches PASTE2's worst case while gaining PASTE2's
robustness *and* Sutura's in-distribution accuracy.

## Post-alignment QC and retry (safety net)

With correct routing and array-bridge GT, retries do not fire in the validation
(all 5 pass post-QC). The retry path was exercised by forcing a mis-route (Mahalanobis
threshold set to ∞ so Br8100 routes to Sutura):

> Routed to SUTURA → 9.45 pitch. Post-QC flagged it (> threshold); retried PASTE2 →
> 3.39 pitch; kept PASTE2.

So the safety net recovers from a routing error automatically.

**No-GT proxy.** When array-bridge GT is unavailable, post-QC falls back to a
footprint-coverage proxy (spread of predicted locations vs the reference footprint;
~1 healthy, →0 collapse). It is validated to catch **gross collapse**: the old
per-SVD Sutura on Br8100 gives coverage **0.34** (flagged) at 19-pitch error.
Honest limitation: it does **not** catch the shared-basis model's *subtler*
cross-donor mis-registration — Br8100 there is 9.5-pitch wrong but the predictions
still spread across the tissue, so coverage stays ~0.97 (unflagged). Detecting a
"smooth-but-wrong" alignment without ground truth is genuinely hard. This is why the
orchestrator's **primary** safeguard is the *pre-alignment* distribution check (which
does flag Br8100), with post-QC as a secondary net for gross failures.

## Honest caveats

- **Two-donor calibration.** The in-distribution class has only 2 donors, so the
  Mahalanobis threshold is a 2-point calibration. The margin here is wide
  (in-dist ~1.0 vs off-dist ≥4.5), but more in-distribution donors would firm it up.
- **PASTE2 reused from cache.** The off-distribution alignments reuse the identical
  full-resolution PASTE2 numbers computed in the earlier sweep
  (`results/generalization_sweep.csv`) to avoid recomputing ~250 s/pair; Sutura is run
  live. Pass `--no-paste2-cache` to force live PASTE2.
- **"Beating both" is a per-input-ceiling claim**, not a claim of beating both on one
  input (see above) — stated precisely to avoid overclaiming.
- **The orchestrator's value depends on the router being right.** It is here (5/5),
  but the whole system is only as good as the distribution check; the retry net
  covers gross mistakes, not subtle ones.

## Bottom line

A concrete, calibrated distribution signal (Mahalanobis through the frozen shared
basis) is enough to route each input to the right aligner. The resulting orchestrator
gets the best of both methods on every dataset and strictly dominates both
Sutura-always and PASTE2-always in aggregate (mean 3.00 vs 4.38 vs 9.41), turning two
individually-limited methods into one robust system.
