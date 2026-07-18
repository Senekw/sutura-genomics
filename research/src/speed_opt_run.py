"""
speed_opt_run.py -- phase orchestration for the PASTE2 speed study. Imported by
speed_opt.py's __main__. Kept separate so the core solver module stays clean and
so process-pool workers can re-import the core without re-running main().

Phases:
  B  subsampling grid  (N x method x sev x seed x dataset, gate on+off)
  C  solver variants   (exact-EMD / armijo / entropic-Sinkhorn reg sweep)
  D  caching           (build vs solve split; distance-matrix reuse on a chain)
  E  parallelization   (4/8/12-section chain: sequential vs process pool)
  F  scale             (runtime vs spot count; synthetic upsample tail; sev 8)
  G  end-to-end        (recommended fast config, per dataset, vs full PASTE2)
"""
from __future__ import annotations

import os
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from scipy.spatial import distance

import speed_opt as so
from speed_opt import (log, stage, append_row, run_cell, prep_pair, chain_task,
                       _read, _now, PAIRS, CHAIN, SEVS, SEEDS, N_LEVELS, METHODS)

FULL = 100000       # n_target sentinel meaning "no subsample"


# --------------------------------------------------------------------------- #
# Phase B: subsampling grid
# --------------------------------------------------------------------------- #
def phase_B(names, sevs, seeds, n_levels, methods):
    log(f"=== PHASE B (subsampling) datasets={names} sevs={sevs} seeds={seeds} "
        f"N={n_levels} methods={methods} ===")
    for name in names:                                   # warm the pair cache
        prep_pair(name)
    # Pass 1: all subsample cells, smallest N first, so the full accuracy-vs-N
    # Pareto lands early even if the night is cut short.
    for n in n_levels:
        for name in names:
            pair = prep_pair(name)
            for seed in seeds:
                for sev in sevs:
                    for method in methods:
                        run_cell("B", pair, sev, seed, n, method)
        log(f"=== PHASE B pass1 N={n} done ===")
    # Pass 2: full-resolution anchors last (most expensive; ~5 min each).
    # seed 0 only -- the accuracy ceiling; extra seeds add little and cost a lot.
    for name in names:
        pair = prep_pair(name)
        for sev in sevs:
            run_cell("B", pair, sev, seeds[0], FULL, "full")
    log("=== PHASE B full anchors done ===")


# --------------------------------------------------------------------------- #
# Phase C: solver variants on representative pairs
# --------------------------------------------------------------------------- #
def phase_C(names, seeds):
    reps = [n for n in ("Br8100", "breast") if n in names] or names[:1]
    sev, seed = 4.0, (seeds[0] if seeds else 0)
    log(f"=== PHASE C (solvers) reps={reps} sev={sev} seed={seed} ===")
    for name in reps:
        pair = prep_pair(name)
        for n in (1500, FULL):
            run_cell("C", pair, sev, seed, n, "random", solver="emd")
            run_cell("C", pair, sev, seed, n, "random", solver="armijo", armijo=True)
            for reg in (1e-1, 1e-2, 1e-3):
                run_cell("C", pair, sev, seed, n, "random",
                         solver=f"sinkhorn{reg:g}", reg=reg)
    log("=== PHASE C done ===")


# --------------------------------------------------------------------------- #
# Phase D: caching -- build/solve split + distance-matrix reuse on a chain
# --------------------------------------------------------------------------- #
def phase_D():
    log("=== PHASE D (caching) ===")
    # build cost matrices for a real (unwarped) consecutive-section chain both
    # ways: naive (recompute every intra-distance) vs cached (each section's
    # intra-distance matrix computed once, reused as A of pair i and B of pair i-1).
    try:
        secs = [s for s in CHAIN if so._find(s).exists()]
        if len(secs) < 3:
            log("Phase D: chain sections missing, skipping chain-reuse")
            return
        stage("D:load-chain")
        slices = {s: _read(s) for s in secs}
        from paste2.helper import intersect
        pairs = list(zip(secs[:-1], secs[1:]))

        # naive: cdist for every slice in every pair it appears in
        t0 = time.time()
        for a, b in pairs:
            _ = distance.cdist(slices[a].obsm["spatial"], slices[a].obsm["spatial"])
            _ = distance.cdist(slices[b].obsm["spatial"], slices[b].obsm["spatial"])
        naive_d_s = time.time() - t0

        # cached: each section's cdist computed once
        t0 = time.time()
        cache = {}
        for s in secs:
            cache[s] = distance.cdist(slices[s].obsm["spatial"], slices[s].obsm["spatial"])
        cached_d_s = time.time() - t0

        # expression cost (M) time for one pair, for the build split
        a, b = pairs[0]
        t0 = time.time()
        Aa = slices[a][:, intersect(slices[a].var.index, slices[b].var.index)]
        Bb = slices[b][:, intersect(slices[a].var.index, slices[b].var.index)]
        from paste2.helper import pca_distance
        _ = pca_distance(Aa, Bb, so.N_HVG, so.LATENT)
        m_s = time.time() - t0

        append_row(dict(phase="D", config="dist_naive", solver="chain",
                        n_target=len(pairs), solve_s=round(naive_d_s, 2),
                        detail=f"{len(pairs)} pairs, 2 cdist each", status="ok",
                        timestamp=_now()))
        append_row(dict(phase="D", config="dist_cached", solver="chain",
                        n_target=len(secs), solve_s=round(cached_d_s, 2),
                        detail=f"{len(secs)} sections, 1 cdist each", status="ok",
                        timestamp=_now()))
        append_row(dict(phase="D", config="pca_cost_per_pair", solver="chain",
                        solve_s=round(m_s, 2),
                        detail="pca_distance one pair (NOT chain-cacheable: joint HVG/PCA)",
                        status="ok", timestamp=_now()))
        log(f"Phase D: chain dist-matrix naive={naive_d_s:.2f}s cached={cached_d_s:.2f}s "
            f"(save {100*(1-cached_d_s/max(naive_d_s,1e-9)):.0f}%); "
            f"pca_cost/pair={m_s:.2f}s")
    except Exception as e:                                       # noqa: BLE001
        log(f"Phase D FAILED: {e!r}")
        append_row(dict(phase="D", config="error", status="error",
                        detail=f"{type(e).__name__}: {e}"[:180], timestamp=_now()))


# --------------------------------------------------------------------------- #
# Phase E: parallelization across a multi-section chain
# --------------------------------------------------------------------------- #
def _chain_tasklist(length, sev, seed, n):
    """Cycle available consecutive-section pairs to build a chain of `length`."""
    secs = [s for s in CHAIN if so._find(s).exists()]
    base = list(zip(secs[:-1], secs[1:]))
    if not base:
        base = [(PAIRS["Br8100"][0], PAIRS["Br8100"][1])]
    tasks = []
    i = 0
    while len(tasks) < length:
        ref, mov = base[i % len(base)]
        tasks.append((ref, mov, sev, seed, n))
        i += 1
    return tasks


def _seq_run(tasks):
    return [chain_task(*t) for t in tasks]


def _pool_run(tasks, workers):
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(chain_task, *t) for t in tasks]
        return [f.result() for f in futs]


def phase_E(sev=4.0, seed=0, n=1200):
    log(f"=== PHASE E (parallel) sev={sev} seed={seed} N={n} ===")
    # pin BLAS to 1 thread in child processes so P workers x 1 thread saturates
    # the 8 cores cleanly (isolates parallelism from BLAS threading).
    os.environ["SPEED_OPT_THREADS"] = "1"
    os.environ["PYTHONPATH"] = str(Path(__file__).resolve().parent) + os.pathsep + \
        os.environ.get("PYTHONPATH", "")
    for length in (4, 8, 12):
        tasks = _chain_tasklist(length, sev, seed, n)
        try:
            stage(f"E:seq{length}")
            t0 = time.time()
            seq = _pool_run(tasks, 1)             # sequential = pool of 1 (startup-symmetric)
            seq_wall = time.time() - t0
            per_task = np.mean([r["wall_s"] for r in seq]) if seq else float("nan")
        except Exception as e:                                   # noqa: BLE001
            log(f"Phase E seq{length} FAILED: {e!r}")
            append_row(dict(phase="E", config="seq", n_target=length, status="error",
                            detail=f"{type(e).__name__}: {e}"[:160], timestamp=_now()))
            continue
        append_row(dict(phase="E", config="sequential", n_target=length, seed=seed,
                        severity=sev, solve_s=round(per_task, 2),
                        total_s=round(seq_wall, 2), status="ok",
                        detail=f"{length} pairs serial", timestamp=_now()))
        workers = min(length, 8)
        try:
            stage(f"E:par{length}")
            t0 = time.time()
            _ = _pool_run(tasks, workers)
            par_wall = time.time() - t0
        except Exception as e:                                   # noqa: BLE001
            log(f"Phase E par{length} FAILED: {e!r}")
            append_row(dict(phase="E", config="parallel", n_target=length, status="error",
                            detail=f"{type(e).__name__}: {e}"[:160], timestamp=_now()))
            continue
        speedup = seq_wall / max(par_wall, 1e-9)
        append_row(dict(phase="E", config=f"parallel_w{workers}", n_target=length,
                        seed=seed, severity=sev, total_s=round(par_wall, 2),
                        solve_s=round(speedup, 2), status="ok",
                        detail=f"{length} pairs, {workers} workers, {speedup:.2f}x vs serial",
                        timestamp=_now()))
        log(f"Phase E chain={length}: serial={seq_wall:.0f}s parallel({workers}w)="
            f"{par_wall:.0f}s -> {speedup:.2f}x")
    os.environ["SPEED_OPT_THREADS"] = so._THREADS
    log("=== PHASE E done ===")


# --------------------------------------------------------------------------- #
# Phase F: scale -- runtime vs spot count + synthetic upsample tail
# --------------------------------------------------------------------------- #
def _upsample(adata, target, seed):
    """Jitter-duplicate spots to reach ~target for O(n^3) tail probing."""
    n = adata.n_obs
    if target <= n:
        return adata.copy()
    rng = np.random.default_rng(seed)
    reps = int(np.ceil(target / n))
    idx = np.tile(np.arange(n), reps)[:target]
    a = adata[idx].copy()
    coords = np.asarray(a.obsm["spatial"], float)
    pit = np.median(np.abs(np.diff(np.sort(coords[:, 0]))) + 1e-6)
    a.obsm["spatial"] = coords + rng.normal(0, 0.15 * max(pit, 1.0), coords.shape)
    a.obs_names = [f"c{i}" for i in range(a.n_obs)]
    return a


def phase_F(names, seed=0, do_upsample=True):
    log("=== PHASE F (scale) ===")
    name = "Br5292" if "Br5292" in names else names[0]     # largest real pair
    pair = prep_pair(name)
    # fine runtime-vs-n sweep at the hardest severity
    for n in (500, 1000, 1500, 2000, 2500, 3000, FULL):
        run_cell("F", pair, 8.0, seed, n, "random")
    if not do_upsample:
        log("=== PHASE F done (no upsample) ===")
        return
    # synthetic upsample tail: confirm no hang, characterize O(n^3) growth
    for target in (5000, 6500):
        key = ("F", name, "8.0", str(seed), str(target), "upsample", "emd",
               "gated_rigid", "final")
        if key in so._done_keys:
            continue
        try:
            stage(f"F:upsample{target}")
            A = _upsample(pair["A"], target, seed)
            B = _upsample(pair["B"], target, seed + 1)
            from warp_slice import apply_warp
            w, _ = apply_warp(B, 8.0, seed=seed, tear=True)
            from scipy.spatial import cKDTree
            cA = np.asarray(A.obsm["spatial"], float)
            pitch = float(np.median(cKDTree(cA).query(cA, k=2)[0][:, 1]))
            t0 = time.time()
            M, D_A, D_B, a, b = so.build_costs(A, w)
            build_s = time.time() - t0
            # score against self-identity target is meaningless here; we only
            # characterize TIME + confirm completion within the watchdog.
            gt = cA.copy()
            have = np.ones(A.n_obs, bool)[:w.n_obs] if w.n_obs <= A.n_obs else \
                np.ones(w.n_obs, bool)
            gt2 = np.zeros((w.n_obs, 2))
            pi, n_iter, solve_s, _ = so.call_with_timeout(
                so.solve_fgw, so.SOLVE_TIMEOUT, M, D_A, D_B, a, b,
                cA, gt2, np.zeros(w.n_obs, bool), pitch,
                numItermax=100, stopThr=so.STOPTHR, checkpoints=[])
            append_row(dict(phase="F", dataset=name, severity=8.0, seed=seed,
                            n_target=target, sub_method="upsample", solver="emd",
                            config="scale_time", iter=n_iter, n_a=A.n_obs, n_b=w.n_obs,
                            build_s=round(build_s, 2), solve_s=round(solve_s, 2),
                            total_s=round(build_s + solve_s, 2), status="ok",
                            detail="synthetic upsample; time only", timestamp=_now()))
            log(f"Phase F upsample n~{target}: build={build_s:.1f}s solve={solve_s:.1f}s "
                f"iters={n_iter} (no hang)")
        except Exception as e:                                   # noqa: BLE001
            log(f"Phase F upsample {target} FAILED/timeout: {e!r}")
            append_row(dict(phase="F", dataset=name, n_target=target,
                            sub_method="upsample", config="scale_time", status="error",
                            detail=f"{type(e).__name__}: {e}"[:160], timestamp=_now()))
    log("=== PHASE F done ===")


# --------------------------------------------------------------------------- #
# Phase G: end-to-end recommended fast config vs full PASTE2
# --------------------------------------------------------------------------- #
def phase_G(names, seeds, n_target=1500, method="spatial", cap=100):
    log(f"=== PHASE G (end-to-end) N={n_target} method={method} cap={cap} ===")
    seed = seeds[0] if seeds else 0
    for name in names:
        pair = prep_pair(name)
        for sev in (0.0, 4.0, 8.0):
            run_cell("G", pair, sev, seed, n_target, method, solver="emd",
                     numItermax=cap, stopThr=so.STOPTHR)
    log("=== PHASE G done ===")


# --------------------------------------------------------------------------- #
def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--phases", default="B,C,D,E,F,G")
    p.add_argument("--datasets", default="")
    p.add_argument("--seeds", default="")
    args = p.parse_args()

    names = [d.strip() for d in args.datasets.split(",") if d.strip()] or list(PAIRS)
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()] or SEEDS
    sevs = SEVS
    n_levels = N_LEVELS
    methods = METHODS
    phases = [x.strip().upper() for x in args.phases.split(",") if x.strip()]

    if args.smoke:
        names = ["Br8100"]
        seeds = [0]
        sevs = [0.0, 4.0]
        n_levels = [500, 1000]
        methods = ["random", "spatial"]

    so._load_done()
    hb = threading.Thread(target=so._heartbeat, daemon=True)
    hb.start()
    log("=" * 80)
    log(f"speed_opt START phases={phases} datasets={names} seeds={seeds} "
        f"smoke={args.smoke} threads={so._THREADS}")
    log(f"numItermax={so.NUMITERMAX} stopThr={so.STOPTHR} timeout={so.SOLVE_TIMEOUT}s")
    log("=" * 80)
    t_all = time.time()

    if "B" in phases:
        try:
            phase_B(names, sevs, seeds, n_levels, methods)
        except Exception as e:                                   # noqa: BLE001
            log(f"PHASE B crashed: {e!r}")
    if "C" in phases:
        try:
            phase_C(names, seeds)
        except Exception as e:                                   # noqa: BLE001
            log(f"PHASE C crashed: {e!r}")
    if "D" in phases:
        try:
            phase_D()
        except Exception as e:                                   # noqa: BLE001
            log(f"PHASE D crashed: {e!r}")
    if "E" in phases:
        try:
            phase_E(seed=seeds[0] if seeds else 0,
                    n=800 if args.smoke else 1200)
        except Exception as e:                                   # noqa: BLE001
            log(f"PHASE E crashed: {e!r}")
    if "F" in phases:
        try:
            phase_F(names, seed=seeds[0] if seeds else 0,
                    do_upsample=not args.smoke)
        except Exception as e:                                   # noqa: BLE001
            log(f"PHASE F crashed: {e!r}")
    if "G" in phases:
        try:
            phase_G(names, seeds, n_target=500 if args.smoke else 1500,
                    cap=50 if args.smoke else 100)
        except Exception as e:                                   # noqa: BLE001
            log(f"PHASE G crashed: {e!r}")

    so._HB_STOP = True
    log(f"speed_opt DONE total={time.time()-t_all:.0f}s -> {so.CSV_PATH}")
    log("DONE")
