"""
The unified benchmark runner.

One entry point runs any set of methods against any set of datasets across a grid
of severities and seeds, writing one CSV row per (dataset, method, severity,
seed) scoring cell. Every design choice here exists to make the numbers trustable
and the run cheap to repeat:

  * PASTE2 base caching - the expensive PASTE2 solve for a (dataset, severity,
    seed) cell is computed once, cached to disk, and shared by PASTE2 and every
    gate variant. The cache also transparently reuses the research cache
    (research/results/paste2_cache) so reproducing prior numbers is instant.
  * Resumable - a cell already present in the output CSV is skipped, so a run can
    be killed and restarted freely.
  * Per-cell isolation - any dataset/cell/method failure is caught, logged, and
    recorded with status="error"; the run continues.
  * Regime-correct severities - DLPFC uses the 7-point grid, OOD/self-warp the
    5-point grid, unless overridden.

Results schema (one row per cell) is documented in RESULT_FIELDS.
"""

from __future__ import annotations

import csv
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from . import config, datasets, methods
from .tasks import PairContext, Task

RESULT_FIELDS = [
    "run_tag", "timestamp", "dataset", "group", "regime", "degenerate", "tissue",
    "method", "kind", "severity", "seed",
    "median_pitch", "mean_pitch", "p90_pitch", "p95_pitch", "median_px",
    "n", "pitch_px", "bridge_coverage",
    "base_err_pitch", "beats_base", "seconds", "status", "detail",
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class RunConfig:
    datasets: list[str]
    methods: list[str]
    seeds: list[int] = field(default_factory=lambda: [0])
    severities: Optional[list[float]] = None    # None -> per-dataset default grid
    out_csv: Optional[Path] = None
    run_tag: str = "run"
    resume: bool = True


# --------------------------------------------------------------------------- #
# logging
# --------------------------------------------------------------------------- #
class _Log:
    def __init__(self, path: Path):
        self.path = path

    def __call__(self, msg: str) -> None:
        line = f"[{_now()}] {msg}"
        print(line, flush=True)
        with open(self.path, "a", encoding="ascii", errors="replace") as fh:
            fh.write(line + "\n")


# --------------------------------------------------------------------------- #
# PASTE2 base cache (two-tier: our cache, then read-only research cache)
# --------------------------------------------------------------------------- #
def _base_key(dataset_id: str, sev: float, seed: int) -> str:
    return f"{dataset_id}_s{sev:g}_seed{seed}.npz"


def load_or_compute_base(task: Task) -> tuple[np.ndarray, str]:
    """Return (base_coords, source) where source is 'bench-cache', 'research-cache',
    or 'computed'. Computes real PASTE2 only on a cache miss and stores it."""
    config.ensure_dirs()
    key = _base_key(task.spec.id, task.severity, task.seed)
    ours = config.BENCH_CACHE / key
    if ours.exists():
        try:
            return np.load(ours)["base"], "bench-cache"
        except Exception:
            pass
    research = config.PASTE2_CACHE / key
    if research.exists():
        try:
            base = np.load(research)["base"]
            if base.shape[0] == task.moving_coords.shape[0]:
                return base, "research-cache"
        except Exception:
            pass
    base = methods.compute_paste2_base(task)
    np.savez_compressed(ours, base=base.astype(np.float32))
    return base, "computed"


# --------------------------------------------------------------------------- #
# resume support
# --------------------------------------------------------------------------- #
def _done_cells(csv_path: Path) -> set:
    done = set()
    if not csv_path.exists():
        return done
    with open(csv_path, newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("status") == "ok":
                done.add((r["dataset"], r["method"], r["severity"], r["seed"]))
    return done


def _append(csv_path: Path, row: dict) -> None:
    exists = csv_path.exists()
    full = {k: row.get(k, "") for k in RESULT_FIELDS}
    with open(csv_path, "a", newline="", encoding="ascii", errors="replace") as fh:
        w = csv.DictWriter(fh, fieldnames=RESULT_FIELDS)
        if not exists:
            w.writeheader()
        w.writerow(full)


def _severities_for(spec: datasets.DatasetSpec, override: Optional[list]) -> list:
    if override is not None:
        return override
    return config.DLPFC_SEVERITIES if spec.group == "dlpfc" else config.OOD_SEVERITIES


# --------------------------------------------------------------------------- #
# main runner
# --------------------------------------------------------------------------- #
def run(cfg: RunConfig) -> Path:
    config.ensure_dirs()
    out = Path(cfg.out_csv) if cfg.out_csv else config.BENCH_RESULTS / f"{cfg.run_tag}.csv"
    log = _Log(out.with_suffix(".log"))

    method_objs = [methods.get(m) for m in cfg.methods]
    needs_base = any(m.requires_base for m in method_objs)
    done = _done_cells(out) if cfg.resume else set()

    log("=" * 78)
    log(f"RUN '{cfg.run_tag}' -> {out.name}")
    log(f"  datasets={cfg.datasets}")
    log(f"  methods={cfg.methods}  seeds={cfg.seeds}  needs_paste2_base={needs_base}")
    log(f"  resume={cfg.resume} ({len(done)} cells already done)")
    log("=" * 78)

    t_all = time.time()
    for ds_id in cfg.datasets:
        try:
            spec = datasets.get(ds_id)
        except KeyError as e:
            log(f"[{ds_id}] SKIP: {e}")
            continue
        if not datasets.is_available(spec):
            log(f"[{ds_id}] SKIP: section files not on disk")
            continue

        sevs = _severities_for(spec, cfg.severities)
        try:
            t0 = time.time()
            ctx = PairContext(spec)
            log(f"[{ds_id}] built pair A={ctx.A.n_obs} B={ctx.B.n_obs} "
                f"pitch={ctx.pitch:.1f} regime={spec.regime} "
                f"bridge={ctx.bridge_coverage*100:.0f}% ({time.time()-t0:.0f}s)")
        except Exception as e:
            log(f"[{ds_id}] BUILD FAILED: {e!r}\n{traceback.format_exc()}")
            continue

        for seed in cfg.seeds:
            for sev in sevs:
                _run_cell(cfg, out, log, spec, ctx, sev, seed, method_objs,
                          needs_base, done)
    log(f"RUN '{cfg.run_tag}' DONE ({time.time()-t_all:.0f}s) -> {out}")
    return out


def _run_cell(cfg, out, log, spec, ctx, sev, seed, method_objs, needs_base, done):
    task = ctx.make_task(sev, seed)
    base_err = None

    # populate the shared PASTE2 base once if any method needs it
    if needs_base:
        pending = [m for m in method_objs
                   if (spec.id, m.name, str(sev), str(seed)) not in done]
        if any(m.requires_base for m in pending):
            try:
                task.base, src = load_or_compute_base(task)
                bstats = task.score(task.base)
                base_err = bstats["median_pitch"]
                log(f"[{spec.id}] s{sev:g} seed{seed} base ({src}): "
                    f"paste2={base_err:.3f}p")
            except Exception as e:
                log(f"[{spec.id}] s{sev:g} seed{seed} BASE FAILED: {e!r}")

    for m in method_objs:
        cellkey = (spec.id, m.name, str(sev), str(seed))
        if cellkey in done:
            continue
        if m.requires_base and task.base is None:
            _append(out, dict(run_tag=cfg.run_tag, timestamp=_now(), dataset=spec.id,
                              group=spec.group, regime=spec.regime, method=m.name,
                              kind=m.kind, severity=sev, seed=seed,
                              status="error", detail="paste2 base unavailable"))
            continue
        t0 = time.time()
        try:
            pred = m.run(task)
            st = task.score(pred)
            row = dict(
                run_tag=cfg.run_tag, timestamp=_now(), dataset=spec.id,
                group=spec.group, regime=spec.regime, degenerate=spec.degenerate,
                tissue=spec.tissue, method=m.name, kind=m.kind,
                severity=sev, seed=seed,
                median_pitch=round(st["median_pitch"], 4),
                mean_pitch=round(st["mean_pitch"], 4),
                p90_pitch=round(st["p90_pitch"], 4),
                p95_pitch=round(st["p95_pitch"], 4),
                median_px=round(st["median_px"], 2),
                n=st["n"], pitch_px=round(ctx.pitch, 1),
                bridge_coverage=st["bridge_coverage"],
                base_err_pitch=("" if base_err is None else round(base_err, 4)),
                beats_base=("" if base_err is None
                            else bool(st["median_pitch"] <= base_err)),
                seconds=round(time.time() - t0, 2), status="ok", detail="")
            _append(out, row)
        except Exception as e:
            _append(out, dict(run_tag=cfg.run_tag, timestamp=_now(), dataset=spec.id,
                              group=spec.group, regime=spec.regime, method=m.name,
                              kind=m.kind, severity=sev, seed=seed, status="error",
                              detail=f"{type(e).__name__}: {e}"[:180]))
            log(f"[{spec.id}] {m.name} s{sev:g} seed{seed} FAILED: {e!r}")
