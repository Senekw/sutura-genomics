# `sutura_bench` — the alignment benchmark harness

Permanent, reusable evaluation infrastructure for spatial-transcriptomics
alignment. One harness runs **any** alignment method (Sutura, PASTE2, the gate,
or a future method) against a **standard suite** of datasets, severities, and
seeds, and produces **directly comparable** numbers — so every future change can
be measured the same way.

It replaces the pile of one-off experiment scripts (`generalization_max.py`,
`hybrid_validate.py`, `external_eval.py`, …) with a single package that
reproduces their headline numbers exactly (verified bit-for-bit — see
[Reproduction](#reproduction)) while remaining easy to extend.

---

## One command

```bash
# from the repo root, using the project venv
.venv/Scripts/python.exe -m sutura_bench run --datasets suite --methods all --seeds 0,1,2
```

That runs the full standard suite and writes, under `benchmarks/results/`:

- `run.csv` — one row per (dataset, method, severity, seed) scoring cell
- `run_leaderboard.md` — the aggregated leaderboard with honest caveats
- `run.png` — error-vs-severity curves + a DLPFC-LODO summary bar

Shorthand for the machine used here (Windows, Git-Bash):

```bash
py="/c/Users/karti/arca/.venv/Scripts/python.exe"
$py -m sutura_bench <command> ...
```

---

## Commands

| command | what it does |
|---|---|
| `list` | catalogue every dataset with metadata (regime, spot counts, GT coverage). `--methods` lists methods instead. |
| `run` | run methods × datasets × severities × seeds → CSV (+ leaderboard/plots). Resumable. |
| `report <csv>` | (re)generate the leaderboard + plots from any results CSV. |
| `save-reference <csv>` | snapshot a run as the regression reference. |
| `check <csv>` | compare a run against the stored reference and flag regressions (exit 1 on failure). |
| `reproduce` | re-derive the headline PASTE2 / gate / Sutura numbers and prove they match prior results. |

Key `run` options: `--datasets` (`suite`｜`dlpfc`｜`ood`｜`self`｜`all`｜comma-list),
`--methods` (`all` or comma-list), `--seeds`, `--severities` (default per-dataset
grid), `--tag`, `--no-resume`. Every command has `-h`.

---

## What gets measured

The headline metric is **median registration error in spot-pitches**: for each
moving spot, the Euclidean distance between the method's predicted
reference-frame coordinate and the ground-truth coordinate, divided by the spot
pitch (median nearest-neighbour distance), then median-reduced over scorable
spots. Lower is better. Reporting in *pitches* makes datasets with different
physical scales comparable.

A method is anything with the signature *(reference section A, moving section B,
the moving spots' possibly-warped coordinates) → predicted A-frame coordinates,
one (x, y) per moving spot*. The harness applies a controlled synthetic tear
(`warp_slice.apply_warp`) at each severity, runs the method, and scores against
ground truth.

### Methods (built in)

| method | kind | notes |
|---|---|---|
| `identity` | aligner | control: no alignment (measures the perturbation magnitude) |
| `paste2` | aligner | PASTE2 partial-FGW OT baseline (the classical reference) |
| `gate_rigid` | refiner | the gate, per-piece rigid fit on PASTE2 — reproduces the headline **3.73** |
| `gate_affine` | refiner | the gate, per-piece affine (recommended default) — **3.08** LODO |
| `gate_quad` | refiner | the gate, per-piece quadratic |
| `sutura` | aligner | Sutura (`ARCACrossNet`) checkpoint inference (`arca_cross.pt`) |

Refiners consume a shared PASTE2 **base** that the harness computes once per cell
and caches — so PASTE2 and every gate variant are scored on one identical solve.

### Datasets and the two regimes (read this)

Results are only comparable within a **regime**. The harness enforces this:

- **`real_serial`** — two physically distinct adjacent sections sharing the
  Visium array grid. Ground truth is the *array bridge* (matching spots by
  identical `array_row`/`array_col`). **This is the honest cross-section regime
  every headline number uses.** Includes the 3 DLPFC donors (× 2 pairs each) and
  the off-distribution breast + mouse-brain pairs.
- **`self_warp`** — a single section aligned against a synthetically warped copy
  of itself. **DEGENERATE**: the base aligner matches identical expression and is
  near-exact, so refinement cannot be validated. These are reported in a separate,
  clearly-flagged section and are **never** pooled with real-serial numbers. Opt
  in with `--datasets self`.

`sutura_bench list` shows every dataset's regime, spot counts, and array-bridge
coverage.

---

## Interpreting the output

- **DLPFC-LODO mean** — the primary comparison: mean over the three first-pair
  DLPFC donors of each donor's severity-averaged error. This is the number the
  gate result (`gate_affine` 3.08, `gate_rigid` 3.73) is quoted on.
- **`± std`** is across seeds — the improvement from the gate (~1.2 pitch)
  dwarfs the across-seed noise (~0.04), so it is not a lucky seed.
- **Sutura is excellent in-distribution and does not transfer.** On its training
  donor Br5292 it scores ~0.75 pitch; on other donors it is far worse (16–19).
  The leaderboard surfaces this honestly — it is the documented cross-donor
  generalization gap (see `research/FINDINGS_cross_donor_gap_summary.md`), not a
  bug in the harness.
- **The gate is a refinement, not a standalone aligner.** Its claim is
  "PASTE2 + gate > PASTE2". It never regresses on a realistic (imperfect-OT)
  base, but it cannot rescue a grossly wrong base.
- **All ground truth is synthetic tears on real serial sections.** Real tears may
  differ; the array bridge is Visium-specific.

---

## Reproduction

`reproduce` re-derives the headline numbers through the harness and cross-checks
every PASTE2/gate cell against the prior authoritative run
(`research/results/hybrid_validate.csv`):

```bash
.venv/Scripts/python.exe -m sutura_bench reproduce
```

Result (see `benchmarks/results/REPRODUCTION.md`): **bit-exact** — max cell
discrepancy `0.0001` pitch, and

| quantity | published | reproduced |
|---|---|---|
| PASTE2 DLPFC-LODO (7-grid, seed 0) | 4.28 | 4.276 |
| gate_rigid DLPFC-LODO (5-grid, seed 0) | 3.73 | 3.729 |
| gate_affine DLPFC-LODO (7-grid, seed 0) | 3.08 | 3.076 |
| Sutura in-distribution (Br5292, seed 0) | ~0.7–1 | 0.762 |

The reproduction is fast because it reuses the cached PASTE2 bases in
`research/results/paste2_cache/` (transparently, read-only); a fresh machine
recomputes and caches them under `benchmarks/cache/`.

---

## Regression detection

```bash
# after changing an aligner, re-run and check it did not get worse
$py -m sutura_bench run --tag candidate --seeds 0
$py -m sutura_bench check benchmarks/results/candidate.csv
```

`check` flags a cell as a **regression** only when the new error exceeds the
reference by *both* an absolute (0.05 pitch) and a relative (3%) tolerance — wide
enough to absorb float/CV noise, tight enough to catch a real accuracy loss. It
exits non-zero on any regression (CI-friendly). Improvements and new/missing
cells are reported too. Refresh the reference with `save-reference` once a change
is intentionally accepted.

---

## Adding a method

Write a `run(task) -> (n_moving, 2)` function and register it — that is the entire
extension surface (no harness, metric, or dataset changes):

```python
from sutura_bench.methods import Method, register

def my_align(task):
    # task.ctx.A, task.ctx.B, task.moving_coords, task.ctx.Z_A/Z_B,
    # task.pitch, and (for refiners) task.base are all available.
    return predicted_reference_coords          # (task.moving_coords.shape[0], 2)

register(Method("my_method", "aligner", my_align, requires_base=False,
                description="..."))
```

Set `kind="refiner"` and `requires_base=True` to receive the shared PASTE2 base
in `task.base`.

---

## Package layout

```
benchmarks/
  sutura_bench/
    config.py        paths + constants (adds repo src/ to the import path)
    metrics.py       ALL metrics in one place (parity-tested vs src/scoring.py)
    datasets.py      the dataset registry + auto-introspected catalogue
    tasks.py         PairContext + Task: warp + both GT regimes
    methods.py       the method registry + adapters
    harness.py       the runner (resumable, base-cached, per-cell isolation)
    report.py        leaderboard + plots
    regression.py    reference snapshot + regression check
    reproduce.py     headline-number reproduction + cross-check
    cli.py           `python -m sutura_bench ...`
  references/        reference_results.json, dataset_catalogue.json
  results/           run CSVs, leaderboards, plots, REPRODUCTION.md
  tests/             pytest suite (metrics parity, datasets, methods, harness, regression)
```

Requires the project venv (`.venv`): scanpy/anndata, torch (CPU), POT, paste2,
scikit-learn, pandas, matplotlib. Nothing here reimplements alignment or metric
math — the adapters import the canonical research code from `src/`, so the
benchmark measures exactly what the experiments produce.
