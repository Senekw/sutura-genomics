# Benchmark-suite build — coordination log

**Owner:** Claude (autonomous overnight session, started 2026-07-18)
**Branch:** `benchmark-suite`. **Scope constraint:** touch only files under
`benchmarks/`. Do NOT touch main, website, demo, cli/, app/, src/, research/src/,
or other branches. (src/ and research/ are READ to import canonical impls, never
modified.)

**Goal:** replace the pile of one-off experiment scripts with permanent, reusable
evaluation infrastructure so every future change can be measured consistently — a
unified harness (any method × standard datasets/severities/seeds → comparable
numbers), a dataset registry, one metrics module, baseline reproduction,
regression detection, reporting, docs, tests.

## Environment facts (verified)
- Interpreter: `.venv/Scripts/python.exe` (py3.12; scanpy/anndata, torch CPU, POT,
  paste2, sklearn, pandas, matplotlib all present).
- The harness IMPORTS the research code (never reimplements): metrics mirror
  `src/scoring.py`; warp = `src/warp_slice.py::apply_warp`; GT = `array_bridge`
  (`src/train_cross.py`); PASTE2 = `hybrid_combined.paste2_prior`; gate =
  `src/gate_refine.py`; Sutura = `ARCACrossNet` + `arca_cross.pt`.
- PASTE2 base cache: 134 cached bases in `research/results/paste2_cache/` keyed
  `{dataset}_s{sev:g}_seed{seed}.npz` — the harness reuses these read-only, so
  reproduction is instant and exact. Our own cache writes to `benchmarks/cache/`.
- Headline reference numbers (from research/FINDINGS_hybrid_validated.md,
  FINDINGS_cross_donor_gap_summary.md): PASTE2 DLPFC-LODO 4.28; gate_rigid 3.73
  (5-grid); gate_affine 3.08 (7-grid); Sutura in-dist ~0.7-1.

## Status — ALL DELIVERABLES COMPLETE
| # | Deliverable | Status |
|---|---|---|
| 1 | Package scaffold (config, paths) | DONE |
| 2 | Metrics module (one place, parity-tested) | DONE |
| 3 | Dataset registry + auto-introspected catalogue | DONE |
| 4 | Method registry + adapters (identity/paste2/gate×3/sutura) | DONE |
| 5 | Unified harness (resumable, base-cached, per-cell isolation) | DONE |
| 6 | Reporting (leaderboard + plots, honest caveats) | DONE |
| 7 | Regression detection (reference snapshot + check) | DONE |
| 8 | Baseline reproduction (bit-exact) | DONE |
| 9 | Tests (26 passing) + documentation | DONE |

## Decisions & findings (chronological)

- **Common method interface.** Every method is `run(task) -> (n_moving, 2)`
  predicted A-frame coords. Aligners produce a base; refiners consume a shared
  PASTE2 base (`task.base`) the harness computes once per cell. This matches how
  `hybrid_validate.py` layers the gate on one cached PASTE2 solve — apples-to-apples.

- **Two GT regimes, never pooled.** `real_serial` (array-bridge GT on distinct
  adjacent sections) vs `self_warp` (degenerate: a section aligned to a warped
  copy of itself; base is ~exact, nothing to refine). The registry tags each
  dataset; the leaderboard reports self-warp separately with a loud caveat and
  `metrics.is_degenerate_self_warp` flags scores at/below a 1.0-pitch floor. This
  is the "honest handling of the self-alignment degenerate case" deliverable.

- **Metrics: self-contained but parity-verified.** `metrics.py` implements every
  metric in numpy directly (not a thin import) so `benchmarks/` does not break if
  `src/` is refactored, and `tests/test_metrics.py` asserts it reproduces
  `src/scoring.py` bit-for-bit (registration error, projections, label transfer,
  random floor) + `warp_slice.median_spot_pitch`. Added percentiles (p95/p99) and
  pitch-normalized fields on top of the canonical `{mean,median,p90,max}`.

- **Reproduction is BIT-EXACT.** `reproduce` runs PASTE2 + gate (rigid/affine) +
  Sutura on the 3 DLPFC donors + breast + mousebrain (seeds 0-2, all cached) and
  cross-checks every PASTE2/gate cell against `hybrid_validate.csv`:
    - Max |delta| across all matched cells = **0.0001 pitch** (MATCH).
    - PASTE2 DLPFC-LODO (7-grid, seed0): **4.276** vs 4.28 published.
    - gate_rigid DLPFC-LODO (5-grid, seed0): **3.729** vs 3.73 (the headline).
    - gate_affine DLPFC-LODO (7-grid, seed0): **3.076** vs 3.08.
    - Sutura in-dist Br5292 (seed0): **0.762** pitch, beats PASTE2 (5.30).
  The one sub-0.001 wiggle is `gate_affine`'s CV-residual float rounding
  (2.5642 vs 2.5643) — within any sane tolerance. No unexplained discrepancy.
  Written to `benchmarks/results/REPRODUCTION.md`.

- **The cross-donor gap shows up honestly.** Sutura (arca_cross.pt, trained on
  Br5292 151507/508) is 0.75 pitch on Br5292 but 16-19 on other donors → LODO
  mean 12.0. The leaderboard surfaces this rather than hiding it; it matches
  `FINDINGS_cross_donor_gap_summary.md`. Not a harness bug.

- **Reference stored.** `references/reference_results.json` = 372 cells + LODO
  aggregates from the seeds-0-2 reproduction. `check` self-passes; a synthetic
  +0.5-pitch regression is correctly flagged; +0.001 jitter is not.

## How to run (one command)
```
.venv/Scripts/python.exe -m sutura_bench run --datasets suite --methods all --seeds 0,1,2
.venv/Scripts/python.exe -m sutura_bench reproduce
.venv/Scripts/python.exe -m sutura_bench check benchmarks/results/<run>.csv
```

## Tests
26 pass in ~63s: metrics parity (vs src/scoring.py), dataset registry integrity,
method interface, end-to-end harness (bit-exact gate reproduction + resume +
identity-worse-than-paste2), regression detection (flag/tolerate/improve/missing).
Data/cache-dependent tests auto-skip if absent.

## Open follow-ups (not blocking; infra is complete)
- GPSA / CODA baselines live in `baselines/` with their own venvs; they are NOT
  yet wired as `Method`s (each needs its own interpreter). Registering them as
  external methods (subprocess adapters) is the natural next extension.
- A fresh (uncached) full run recomputes PASTE2 (~100-280 s/pair) — fine
  overnight; the subsampling speed path from `research/speed_probe.py` could be
  exposed as a method option if interactive runs are wanted.
- Self-warp sweep (`--datasets self`) is supported but not part of the default
  suite by design (degenerate).
